import os
import asyncio
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, HTTPException, Depends, Request

from config import db, logger
from utils import now_iso, get_current_user, require_admin, notify_customer, deny_impersonation
from routers.tenants import get_current_tenant
from models import CheckoutRequest, SetupSessionReq

router = APIRouter()

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")


def _cents(amount: float) -> int:
    return int(round(float(amount) * 100))


async def _flag_charge_failed(qid: str, msg: str):
    await db.quotes.update_one({"id": qid}, {"$set": {
        "charge_failed": True, "charge_error": msg, "charge_failed_at": now_iso(),
    }})


async def _clear_charge_failed(qid: str):
    await db.quotes.update_one({"id": qid}, {"$set": {
        "charge_failed": False, "charge_error": "", "charge_failed_at": None,
    }})


async def _get_payable_invoice(qid: str, user: dict, tenant: dict) -> dict:
    """Fetch an invoice and enforce role/ownership + payable state (tenant-scoped)."""
    if user.get("role") == "technician":
        raise HTTPException(403, "Not allowed")
    doc = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Invoice not found")
    if user.get("role") == "customer" and doc.get("customer_id") != user.get("customer_id"):
        raise HTTPException(403, "Not allowed")
    if doc.get("payment_status") == "paid":
        raise HTTPException(400, "Invoice is already paid")
    if doc.get("total", 0) <= 0:
        raise HTTPException(400, "Invoice has no payable amount")
    return doc


async def _mark_paid(invoice_id: str):
    doc = await db.quotes.find_one({"id": invoice_id}, {"_id": 0})
    if not doc or doc.get("payment_status") == "paid":
        return
    await db.quotes.update_one(
        {"id": invoice_id},
        {"$set": {"payment_status": "paid", "status": "accepted", "amount_paid": float(doc.get("total") or 0), "paid_at": now_iso()}},
    )
    if doc.get("customer_id"):
        await notify_customer(doc["customer_id"], "Payment received",
                              f"Your payment for '{doc.get('title', 'invoice')}' was received. Thank you!")


# ----------------------- Payments list (admin) -----------------------
@router.get("/me/payments")
async def my_payments(user: dict = Depends(get_current_user),
                      tenant: dict = Depends(get_current_tenant)):
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customers only")
    paid = await db.quotes.find(
        {"customer_id": user["customer_id"], "tenant_id": tenant["id"], "payment_status": "paid"},
        {"_id": 0},
    ).sort("paid_at", -1).to_list(1000)
    total = round(sum(q.get("total", 0.0) for q in paid), 2)
    return {
        "total_paid": total,
        "count": len(paid),
        "payments": [{
            "id": q["id"], "title": q.get("title", ""), "amount": q.get("total", 0.0),
            "paid_at": q.get("paid_at"), "method": q.get("payment_method", "Card"),
        } for q in paid],
    }


@router.get("/payments")
async def list_payments(user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    paid = await db.quotes.find(
        {"tenant_id": tenant["id"], "payment_status": "paid"}, {"_id": 0}
    ).sort("paid_at", -1).to_list(1000)
    return [{"id": q["id"],
             "invoice_id": q["id"],
             "invoice_number": q.get("invoice_number") or None,
             "customer_name": q["customer_name"], "title": q["title"],
             "amount": q["total"], "paid_at": q.get("paid_at"), "method": "Card"} for q in paid]


# ----------------------- Payments summary widget (admin) -----------------------
@router.get("/payments/summary")
async def payments_summary(user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    now = datetime.now(timezone.utc)
    month_key = f"{now.year}-{now.month:02d}"

    paid = await db.quotes.find(
        {"tenant_id": tenant["id"], "payment_status": "paid"}, {"_id": 0}
    ).to_list(3000)
    collected_month = 0.0
    for q in paid:
        ds = q.get("paid_at") or q.get("created_at") or ""
        if ds[:7] == month_key:
            collected_month += q.get("total", 0.0)

    unpaid = await db.quotes.find(
        {"tenant_id": tenant["id"], "doc_type": "invoice", "payment_status": "unpaid"},
        {"_id": 0},
    ).sort("created_at", 1).to_list(2000)
    outstanding_total = round(sum(q.get("total", 0.0) for q in unpaid), 2)

    overdue = []
    for q in unpaid:
        created = q.get("created_at") or ""
        days = 0
        try:
            days = (now - datetime.fromisoformat(created)).days
        except Exception:
            pass
        overdue.append({
            "id": q["id"], "customer_id": q.get("customer_id"),
            "customer_name": q.get("customer_name", ""), "title": q.get("title", ""),
            "total": q.get("total", 0.0), "days": max(0, days),
            "reminded_at": q.get("reminded_at"),
        })
    # Most overdue first
    overdue.sort(key=lambda x: -x["days"])

    return {
        "collected_this_month": round(collected_month, 2),
        "outstanding_total": outstanding_total,
        "outstanding_count": len(unpaid),
        "month_label": now.strftime("%B %Y"),
        "overdue": overdue,
    }


@router.post("/quotes/{qid}/remind")
async def remind_invoice(qid: str,
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    doc = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Invoice not found")
    if doc.get("payment_status") == "paid":
        raise HTTPException(400, "Invoice is already paid")
    await notify_customer(
        doc.get("customer_id"),
        "Payment reminder",
        f"A friendly reminder: your invoice '{doc.get('title', 'invoice')}' for ${doc.get('total', 0):,.2f} is awaiting payment.",
        sms=True,
    )
    entry = {"at": now_iso(), "by": user.get("name", "Admin")}
    await db.quotes.update_one(
        {"id": qid, "tenant_id": tenant["id"]},
        {"$set": {"reminded_at": entry["at"]}, "$push": {"reminders": entry}},
    )
    return {"ok": True, "reminded_at": entry["at"], "reminders": (doc.get("reminders") or []) + [entry]}


# ----------------------- Stripe Checkout -----------------------
@router.post("/payments/checkout/{qid}")
async def create_checkout_session(qid: str, body: CheckoutRequest,
                                  user: dict = Depends(get_current_user),
                                  tenant: dict = Depends(get_current_tenant)):
    deny_impersonation(user)
    if not stripe.api_key:
        raise HTTPException(503, "Payments are not configured")
    doc = await _get_payable_invoice(qid, user, tenant)
    try:
        session = await asyncio.to_thread(
            stripe.checkout.Session.create,
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": doc.get("title", f"Invoice {qid[:8]}")},
                    "unit_amount": _cents(doc["total"]),
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=body.success_url + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=body.cancel_url,
            metadata={"invoice_id": qid, "customer_id": doc.get("customer_id", "")},
        )
    except Exception as e:
        logger.warning(f"Stripe checkout create failed: {e}")
        raise HTTPException(502, "Could not start checkout")
    await db.payment_sessions.insert_one({
        "id": session.id, "invoice_id": qid, "amount": doc["total"],
        "status": "initiated", "created_at": now_iso(),
    })
    return {"url": session.url, "session_id": session.id}


@router.get("/payments/status/{session_id}")
async def check_payment_status(session_id: str, user: dict = Depends(get_current_user)):
    if user.get("role") == "technician":
        raise HTTPException(403, "Not allowed")
    if not stripe.api_key:
        raise HTTPException(503, "Payments are not configured")
    try:
        session = await asyncio.to_thread(stripe.checkout.Session.retrieve, session_id)
    except Exception as e:
        logger.warning(f"Stripe session retrieve failed: {e}")
        raise HTTPException(400, "Invalid session")
    invoice_id = (session.get("metadata") or {}).get("invoice_id")
    pay_status = session.get("payment_status")
    if pay_status == "paid" and invoice_id:
        await _mark_paid(invoice_id)
        await db.payment_sessions.update_one({"id": session_id}, {"$set": {"status": "paid"}})
    return {"status": pay_status, "invoice_id": invoice_id}


@router.post("/payments/admin/generate-link/{qid}")
async def admin_generate_payment_link(qid: str,
                                       user: dict = Depends(require_admin),
                                       tenant: dict = Depends(get_current_tenant)):
    if not stripe.api_key:
        raise HTTPException(503, "Payments are not configured")
    doc = await _get_payable_invoice(qid, user, tenant)
    try:
        price = await asyncio.to_thread(
            stripe.Price.create,
            currency="usd",
            unit_amount=_cents(doc["total"]),
            product_data={"name": doc.get("title", f"Invoice {qid[:8]}")},
        )
        link = await asyncio.to_thread(
            stripe.PaymentLink.create,
            line_items=[{"price": price.id, "quantity": 1}],
            metadata={"invoice_id": qid, "customer_id": doc.get("customer_id", "")},
        )
    except Exception as e:
        logger.warning(f"Stripe payment link failed: {e}")
        raise HTTPException(502, "Could not create payment link")
    await db.quotes.update_one({"id": qid}, {"$set": {"payment_link": link.url}})
    return {"payment_url": link.url}


# ----------------------- Card / ACH on file (setup + off-session charge) -----------------------
async def _get_or_create_stripe_customer(app_customer_id: str):
    cust = await db.customers.find_one({"id": app_customer_id}, {"_id": 0})
    if not cust:
        raise HTTPException(404, "Customer not found")
    scid = cust.get("stripe_customer_id")
    if not scid:
        sc = await asyncio.to_thread(
            stripe.Customer.create,
            name=cust.get("name") or None,
            email=cust.get("email") or None,
            metadata={"customer_id": app_customer_id},
        )
        scid = sc.id
        await db.customers.update_one({"id": app_customer_id}, {"$set": {"stripe_customer_id": scid}})
    return scid, cust


def _pm_label(pm) -> tuple:
    """Return (brand/bank, last4, type) for display."""
    if pm.type == "card" and pm.get("card"):
        return pm.card.brand.title(), pm.card.last4, "card"
    if pm.type == "us_bank_account" and pm.get("us_bank_account"):
        return pm.us_bank_account.bank_name or "Bank", pm.us_bank_account.last4, "ach"
    return pm.type, "", pm.type


async def _save_pm_from_setup(session) -> bool:
    cid = (session.get("metadata") or {}).get("customer_id")
    si_id = session.get("setup_intent")
    scid = session.get("customer")
    if not (cid and si_id):
        return False
    si = await asyncio.to_thread(stripe.SetupIntent.retrieve, si_id)
    pm_id = si.payment_method
    if not pm_id:
        return False
    pm = await asyncio.to_thread(stripe.PaymentMethod.retrieve, pm_id)
    brand, last4, ptype = _pm_label(pm)
    await db.customers.update_one({"id": cid}, {"$set": {
        "stripe_customer_id": scid, "default_payment_method_id": pm_id,
        "pm_brand": brand, "pm_last4": last4, "pm_type": ptype,
    }})
    try:
        await asyncio.to_thread(stripe.Customer.modify, scid, invoice_settings={"default_payment_method": pm_id})
    except Exception:
        pass
    return True


@router.post("/payments/setup-session")
async def create_setup_session(body: SetupSessionReq, user: dict = Depends(get_current_user)):
    """Hosted Stripe Checkout in setup mode to save a card or bank (ACH) on file."""
    deny_impersonation(user)
    if not stripe.api_key:
        raise HTTPException(503, "Payments are not configured")
    if user.get("role") == "customer":
        cid = user.get("customer_id")
    elif user.get("role") == "admin":
        cid = body.customer_id
    else:
        raise HTTPException(403, "Not allowed")
    if not cid:
        raise HTTPException(400, "Customer required")
    scid, _ = await _get_or_create_stripe_customer(cid)
    try:
        session = await asyncio.to_thread(
            stripe.checkout.Session.create,
            mode="setup",
            payment_method_types=["card", "us_bank_account"],
            customer=scid,
            success_url=body.return_url + "?setup=success",
            cancel_url=body.return_url + "?setup=cancel",
            metadata={"customer_id": cid},
        )
    except Exception as e:
        logger.warning(f"Stripe setup session failed: {e}")
        raise HTTPException(502, "Could not start payment setup")
    return {"url": session.url, "session_id": session.id}


@router.get("/payments/setup-status/{session_id}")
async def setup_status(session_id: str, user: dict = Depends(get_current_user)):
    if not stripe.api_key:
        raise HTTPException(503, "Payments are not configured")
    try:
        session = await asyncio.to_thread(stripe.checkout.Session.retrieve, session_id)
    except Exception:
        raise HTTPException(400, "Invalid session")
    saved = False
    if session.get("status") == "complete" and session.get("mode") == "setup":
        saved = await _save_pm_from_setup(session)
    return {"saved": saved, "status": session.get("status")}


@router.get("/payments/method")
async def my_payment_method(user: dict = Depends(get_current_user),
                            tenant: dict = Depends(get_current_tenant)):
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customers only")
    cust = await db.customers.find_one(
        {"id": user["customer_id"], "tenant_id": tenant["id"]}, {"_id": 0}
    ) or {}
    has = bool(cust.get("default_payment_method_id"))
    label = ""
    if has:
        last4 = cust.get("pm_last4", "")
        label = f"{cust.get('pm_brand', 'Card')} ••{last4}" if last4 else cust.get("pm_brand", "On file")
    return {"has_method": has, "label": label, "type": cust.get("pm_type", "")}


@router.post("/payments/request-method/{customer_id}")
async def request_payment_method(customer_id: str,
                                 user: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    cust = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not cust:
        raise HTTPException(404, "Customer not found")
    await notify_customer(
        customer_id, "Payment method required",
        "Please add a card or bank account (ACH) on file in your portal so we can process payments automatically.",
        sms=True,
    )
    return {"ok": True}


async def charge_invoice_on_file(qid: str) -> dict:
    """Charge a customer's saved card/ACH off-session for an invoice's balance.
    Returns a status dict (never raises for business cases): no_method | succeeded |
    processing | requires_action | already_paid | nothing_due | not_found | failed | error."""
    doc = await db.quotes.find_one({"id": qid}, {"_id": 0})
    if not doc:
        return {"status": "not_found"}
    if doc.get("payment_status") == "paid":
        return {"status": "already_paid"}
    balance = round(float(doc.get("total") or 0) - float(doc.get("amount_paid") or 0), 2)
    if balance <= 0:
        return {"status": "nothing_due"}
    cust = await db.customers.find_one({"id": doc.get("customer_id")}, {"_id": 0}) or {}
    scid = cust.get("stripe_customer_id")
    pm = cust.get("default_payment_method_id")
    if not (scid and pm):
        return {"status": "no_method"}
    try:
        pi = await asyncio.to_thread(
            stripe.PaymentIntent.create,
            amount=_cents(balance), currency="usd", customer=scid, payment_method=pm,
            off_session=True, confirm=True,
            metadata={"invoice_id": qid, "customer_id": doc.get("customer_id", "")},
        )
    except stripe.error.CardError as e:
        err = e.error
        if getattr(err, "code", "") == "authentication_required":
            await _flag_charge_failed(qid, "Bank authentication required — customer must confirm the payment.")
            await notify_customer(doc.get("customer_id"), "Action needed to complete payment",
                                  "Your bank requires you to authenticate a payment. Please open your portal to complete it.")
            return {"status": "requires_action"}
        msg = getattr(err, "message", None) or "The payment method was declined."
        await _flag_charge_failed(qid, msg)
        return {"status": "failed", "message": msg}
    except Exception as e:
        logger.warning(f"charge_invoice_on_file failed: {e}")
        await _flag_charge_failed(qid, "The charge could not be processed. Please retry or request a new card.")
        return {"status": "error"}

    method = f"{cust.get('pm_brand', 'Card')} ••{cust.get('pm_last4', '')}"
    if pi.status == "processing":  # ACH settles in a few days
        await db.quotes.update_one({"id": qid}, {"$set": {"payment_status": "processing", "payment_intent_id": pi.id, "payment_method": method}})
        await _clear_charge_failed(qid)
        return {"status": "processing", "method": method}
    if pi.status == "succeeded":
        await db.quotes.update_one({"id": qid}, {"$set": {
            "payment_status": "paid", "status": "accepted", "amount_paid": float(doc.get("total") or 0),
            "paid_at": now_iso(), "payment_method": method, "payment_intent_id": pi.id,
        }})
        await _clear_charge_failed(qid)
        if doc.get("customer_id"):
            await notify_customer(doc["customer_id"], "Payment received",
                                  f"We charged {method} ${balance:,.2f} for '{doc.get('title', 'invoice')}'. Thank you!")
        return {"status": "succeeded", "amount": balance, "method": method}
    return {"status": pi.status}


@router.post("/payments/charge-on-file/{qid}")
async def charge_on_file(qid: str, user: dict = Depends(require_admin)):
    """Admin charges the customer's saved card/ACH off-session for the invoice balance."""
    if not stripe.api_key:
        raise HTTPException(503, "Payments are not configured")
    res = await charge_invoice_on_file(qid)
    st = res.get("status")
    if st == "not_found":
        raise HTTPException(404, "Invoice not found")
    if st == "already_paid":
        raise HTTPException(400, "Invoice is already paid")
    if st == "nothing_due":
        raise HTTPException(400, "Nothing to charge")
    if st == "no_method":
        raise HTTPException(400, "No card or bank on file for this customer")
    if st == "failed":
        raise HTTPException(402, res.get("message") or "The payment method was declined.")
    if st == "error":
        raise HTTPException(502, "Could not process the charge")
    return res


@router.post("/payments/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    event = None
    if STRIPE_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
        except Exception as e:
            logger.warning(f"Stripe webhook signature failed: {e}")
            raise HTTPException(400, "Invalid signature")
    else:
        import json
        try:
            event = json.loads(payload)
        except Exception:
            raise HTTPException(400, "Invalid payload")
    etype = event.get("type")
    obj = event.get("data", {}).get("object", {}) if isinstance(event, dict) else {}
    if etype == "checkout.session.completed":
        if obj.get("mode") == "setup":
            await _save_pm_from_setup(obj)
        else:
            invoice_id = (obj.get("metadata") or {}).get("invoice_id")
            if obj.get("payment_status") == "paid" and invoice_id:
                await _mark_paid(invoice_id)
    elif etype == "payment_intent.succeeded":
        invoice_id = (obj.get("metadata") or {}).get("invoice_id")
        if invoice_id:
            await _mark_paid(invoice_id)
    elif etype == "payment_intent.payment_failed":
        invoice_id = (obj.get("metadata") or {}).get("invoice_id")
        if invoice_id:
            q = await db.quotes.find_one({"id": invoice_id}, {"_id": 0})
            if q and q.get("payment_status") == "processing":
                await db.quotes.update_one({"id": invoice_id}, {"$set": {"payment_status": "unpaid"}})
                if q.get("customer_id"):
                    await notify_customer(q["customer_id"], "Payment failed",
                                          f"Your payment for '{q.get('title', 'invoice')}' could not be completed. Please update your payment method.")
    return {"received": True}
