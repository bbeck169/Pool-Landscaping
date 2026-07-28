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
    # Comms Phase 3 — invoice.paid automation. Load fresh doc so the
    # engine payload reflects the flipped payment_status/paid_at.
    try:
        fresh = await db.quotes.find_one({"id": invoice_id}, {"_id": 0})
        if fresh and fresh.get("tenant_id"):
            from services.automation_engine import emit as _emit
            await _emit(
                "invoice.paid",
                {"invoice": fresh, "customer": {"id": fresh.get("customer_id"),
                                                   "name": fresh.get("customer_name")}},
                tenant_id=fresh["tenant_id"],
                entity_kind="invoice", entity_id=invoice_id,
                customer_id=fresh.get("customer_id"),
            )
    except Exception:
        pass


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
async def _auto_provision_customer_for_user(user: dict) -> dict:
    """Phase 34 · Task Q · Feb-2026 — self-heal for portal users who
    hit ``/payments/setup-session`` before any ``customers`` doc has
    been linked to their auth record.

    This used to raise ``404 Customer not found`` and hard-block the
    user (that's exactly the bug Brian hit on ``/portal/payment-method``).
    Now, if we can identify the acting user + tenant, we create the
    missing customer row on the fly from the auth-user fields, back-link
    it (``users.customer_id``) so subsequent lookups short-circuit, and
    return the freshly-created doc.

    We prefer to REUSE an existing row that matches the auth-user email
    within the same tenant before creating a new one — that's the case
    for Brian, whose ``customers`` doc was created by the migration
    (``migration.transfer_integrations_to_brian``) but never linked
    back to the auth-user via ``user_id`` / ``customer_id``.
    """
    from utils import new_id

    tenant_id = user.get("tenant_id")
    if not tenant_id:
        return None
    uid = user.get("id")
    email = (user.get("email") or "").strip().lower()
    if not (uid or email):
        return None

    # 1. Try to reuse a customer row already in this tenant that
    #    matches on user_id or email (case-insensitive).
    query = {"tenant_id": tenant_id, "$or": []}
    if uid:
        query["$or"].append({"user_id": uid})
    if email:
        query["$or"].append({"email": {"$regex": f"^{email}$", "$options": "i"}})
    cust = await db.customers.find_one(query, {"_id": 0})

    if not cust:
        # 2. Nothing to reuse — mint a fresh doc from the auth-user.
        new_customer_id = new_id()
        now = now_iso()
        cust = {
            "id": new_customer_id,
            "tenant_id": tenant_id,
            "user_id": uid,
            "name": user.get("name") or (email.split("@")[0] if email else "Customer"),
            "first_name": user.get("first_name") or "",
            "last_name": user.get("last_name") or "",
            "email": email or "",
            "phone": user.get("phone") or "",
            "address": "",
            "billing_address": "",
            "notes": "",
            "tags": [],
            "secondary_addresses": [],
            "waitlisted": False,
            "is_vip": False,
            "created_at": now,
            "updated_at": now,
            "created_by": "task_q_auto_provision",
            "source": "portal_self_serve_auto_provision",
        }
        await db.customers.insert_one(dict(cust))
        logger.info(
            "[task-q] auto-provisioned customer id=%s tenant=%s email=%s "
            "for user=%s (no existing row matched)",
            new_customer_id, tenant_id, email, uid,
        )
    else:
        # Fold missing ``user_id`` back onto the found row so future
        # lookups by user_id succeed immediately.
        set_patch = {}
        if uid and not cust.get("user_id"):
            set_patch["user_id"] = uid
        if set_patch:
            await db.customers.update_one({"id": cust["id"]}, {"$set": set_patch})
            cust.update(set_patch)
            logger.info(
                "[task-q] linked existing customer id=%s to user=%s (email=%s)",
                cust["id"], uid, email,
            )

    # 3. Back-link the auth-user record so subsequent portal calls
    #    that resolve ``user.customer_id`` succeed immediately.
    if uid and cust.get("id") and user.get("customer_id") != cust["id"]:
        try:
            await db.users.update_one(
                {"id": uid}, {"$set": {"customer_id": cust["id"]}}
            )
            user["customer_id"] = cust["id"]  # in-memory so caller sees it
        except Exception as exc:  # pragma: no cover — best-effort back-link
            logger.warning("[task-q] user back-link failed: %s", exc)

    return cust


async def _get_or_create_stripe_customer(app_customer_id: str,
                                          fallback_user: dict | None = None):
    cust = None
    if app_customer_id:
        cust = await db.customers.find_one({"id": app_customer_id}, {"_id": 0})
    # Phase 34 · Task Q — self-heal fallback. When we get here with a
    # missing ``app_customer_id`` OR the id doesn't resolve to a doc,
    # we auto-provision from the acting user rather than 404'ing the
    # portal. Only used by callers that pass ``fallback_user``.
    if not cust and fallback_user is not None:
        cust = await _auto_provision_customer_for_user(fallback_user)
        if cust:
            app_customer_id = cust["id"]
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


@router.post("/payments/setup-session", operation_id="payments.createSetupSession")
async def create_setup_session(body: SetupSessionReq, user: dict = Depends(get_current_user)):
    """Hosted Checkout in setup mode to save a card / bank (ACH) on file.

    Task QQ Phase 2 · Feb 2026 — this endpoint is now
    **provider-aware**. When ``PAYMENT_PROVIDER=lumino`` the request
    is delegated to ``LuminoProvider.create_setup_session`` via the
    payment-provider factory (which returns a hosted-checkout URL
    plus a ``session_id`` the frontend can pass to
    ``/portal/payment-method/return`` on completion). Preview safety
    is still enforced by ``LuminoProvider._enforce_test_scope`` —
    synthetic customers get a mock session id (``prev_…``); real
    customer refs raise ``PaymentTestScopeViolation`` and surface
    a 403. In preview the ``PAYMENT_PROVIDER`` env stays ``stripe``
    (per user directive: prod cutover is manual), so the Lumino
    branch is dead code until flipped in prod.

    Phase 34 · Task Q · Feb-2026 — this endpoint used to hard-fail with
    ``404 Customer not found`` for any portal user whose ``users.customer_id``
    wasn't set (e.g. Brian, whose auth-user was created by a migration
    that didn't back-link the customer row). We now:

      1. Accept ``customer`` (super-admin / owner acting on any customer)
         AND ``customer_id`` from ``users`` for the customer role AND
         a **fallback** ``fallback_user=user`` to
         :func:`_get_or_create_stripe_customer`. If the resolved id
         doesn't map to a customer row, the helper self-heals by either
         reusing an existing row that matches the user's email or
         minting a new one — and back-links it onto ``users.customer_id``
         so subsequent calls short-circuit.
      2. Only raise 404 if we truly cannot identify the acting user
         at all (which is impossible in a JWT-protected route today).
    """
    deny_impersonation(user)
    if user.get("role") == "customer":
        cid = user.get("customer_id")
    elif user.get("role") in ("admin", "super_admin", "owner"):
        # Super-admins / owners hitting this from their own portal
        # (like Brian) act AS a customer. Prefer the explicit body
        # value; fall back to the linked ``users.customer_id`` if
        # already set; otherwise let ``_get_or_create_stripe_customer``
        # self-heal from ``fallback_user``.
        cid = body.customer_id or user.get("customer_id")
    else:
        raise HTTPException(403, "Not allowed")

    # Task QQ Phase 2 · provider-aware dispatch. Lumino branch first;
    # Stripe branch is the legacy default and remains unchanged.
    _provider_name = (os.environ.get("PAYMENT_PROVIDER") or "stripe").strip().lower()
    if _provider_name == "lumino":
        from services.payments import (
            get_payment_provider,
            PaymentProviderDryRun,
            PaymentProviderNotConfigured,
            PaymentTestScopeViolation,
        )
        provider = get_payment_provider()
        # LuminoProvider expects a customer-ref that _is_synthetic_fixture
        # can validate (i.e. an email in @aquaterra.com / @plofv.com
        # or a value on PAYMENTS_TEST_ALLOWLIST_CUSTOMERS). We hand
        # over the user's own email as the customer_ref — synthetic
        # tenants use synthetic emails, so preview naturally short-
        # circuits to a mock session.
        customer_ref = user.get("email") or cid or ""
        # Force the return URL to the Lumino-flavoured page. The
        # frontend `PortalPaymentReturn.jsx` parses ?session_id=...
        # and POSTs back to /payments/lumino/return.
        return_url = body.return_url
        if return_url and "/portal/payment-method" in return_url and "/return" not in return_url:
            base = return_url.split("?")[0].rstrip("/")
            return_url = f"{base}/return"
        try:
            resp = await provider.create_setup_session(
                customer_ref=customer_ref,
                return_url=return_url,
                idempotency_key=f"setup-{cid or user.get('id')}-{int(datetime.now(timezone.utc).timestamp())}",
            )
            return {
                "url": (resp or {}).get("url") or "",
                "session_id": ((resp or {}).get("session_id")
                                     or (resp or {}).get("id") or ""),
                "provider": "lumino",
            }
        except PaymentProviderDryRun as ex:
            # Preview: no real Lumino call was made. Return the
            # synthetic session id so the frontend can walk through
            # the /portal/payment-method/return flow with a mock.
            payload = ex.payload or {}
            return {
                "url": return_url or "",
                "session_id": payload.get("session_id") or "",
                "provider": "lumino",
                "dry_run": True,
            }
        except PaymentTestScopeViolation as ex:
            raise HTTPException(403, str(ex))
        except PaymentProviderNotConfigured as ex:
            raise HTTPException(503, str(ex))

    # ── Stripe (legacy default) ──────────────────────────────────
    if not stripe.api_key:
        raise HTTPException(503, "Payments are not configured")
    scid, _ = await _get_or_create_stripe_customer(cid, fallback_user=user)
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
    return {"url": session.url, "session_id": session.id, "provider": "stripe"}


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


@router.post("/payments/charge-on-file/{qid}", operation_id="payments.chargeOnFile")
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


# ─── Bulk charge-on-file (Feb-2026 · Bulk-pay iteration 1 · Stripe path) ───
try:
    from typing import List as _BulkList, Dict as _BulkDict, Any as _BulkAny  # noqa: F401
except Exception:  # pragma: no cover
    _BulkList = list
    _BulkDict = dict
    _BulkAny = object

from typing import List, Dict, Any  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402


class BulkChargeIn(BaseModel):
    invoice_ids: List[str] = Field(default_factory=list)


_NON_CHARGEABLE_STATUSES = {"draft", "void", "voided", "cancelled", "paid"}


@router.post("/payments/bulk-charge-on-file",
               operation_id="payments.bulkChargeOnFile")
async def bulk_charge_on_file(body: BulkChargeIn,
                                 user: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    """Loop-per-invoice bulk-charge admin action for iteration 1.

    Server-side pre-filter (tenant scope + status + card-on-file) before
    delegating to :func:`charge_invoice_on_file`, the same single-charge
    helper the invoice detail page uses. Never partially fails — returns
    a per-invoice status envelope + summary count.

    Provider-aware routing (Lumino path) is deferred to Task QQ Phase 3.
    """
    ids = [i for i in (body.invoice_ids or []) if isinstance(i, str) and i.strip()]
    if not ids:
        raise HTTPException(400, "invoice_ids is required and must be a non-empty list")
    if not stripe.api_key:
        raise HTTPException(503, "Payments are not configured")

    invs = await db.quotes.find(
        {"id": {"$in": ids}, "tenant_id": tenant["id"]},
        {"_id": 0},
    ).to_list(len(ids))
    by_id = {i["id"]: i for i in invs}

    cust_ids = list({i.get("customer_id") for i in invs if i.get("customer_id")})
    custs: List[Dict[str, Any]] = []
    if cust_ids:
        custs = await db.customers.find(
            {"id": {"$in": cust_ids}, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "name": 1, "default_payment_method_id": 1,
             "stripe_customer_id": 1, "pm_brand": 1, "pm_last4": 1},
        ).to_list(len(cust_ids))
    cust_by_id = {c["id"]: c for c in custs}

    results: List[Dict[str, Any]] = []
    summary = {"total": len(ids), "succeeded": 0, "processing": 0,
                "no_card": 0, "not_chargeable": 0, "failed": 0,
                "not_found": 0, "requires_action": 0}

    for qid in ids:
        inv = by_id.get(qid)
        if not inv:
            results.append({"invoice_id": qid, "status": "not_found"})
            summary["not_found"] += 1
            continue

        cust = cust_by_id.get(inv.get("customer_id") or "") or {}
        base = {
            "invoice_id": qid,
            "customer_id": inv.get("customer_id"),
            "customer_name": inv.get("customer_name") or cust.get("name") or "",
        }

        status = (inv.get("status") or "").lower()
        pstatus = (inv.get("payment_status") or "").lower()
        if status in _NON_CHARGEABLE_STATUSES or pstatus in {"paid", "voided"}:
            results.append({**base, "status": "not_chargeable",
                              "reason": f"invoice_status_{status or pstatus or 'unknown'}"})
            summary["not_chargeable"] += 1
            continue

        if not (cust.get("default_payment_method_id") and cust.get("stripe_customer_id")):
            results.append({**base, "status": "no_card"})
            summary["no_card"] += 1
            continue

        try:
            res = await charge_invoice_on_file(qid)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("[bulk-charge] %s crashed: %s", qid, exc)
            results.append({**base, "status": "failed", "reason": "exception"})
            summary["failed"] += 1
            continue

        st = (res or {}).get("status") or "unknown"
        row: Dict[str, Any] = {**base, "status": st}
        if st == "succeeded":
            row["amount"] = res.get("amount")
            row["method"] = res.get("method")
            summary["succeeded"] += 1
        elif st == "processing":
            row["method"] = res.get("method")
            summary["processing"] += 1
        elif st == "requires_action":
            summary["requires_action"] += 1
        elif st == "no_method":
            row["status"] = "no_card"
            summary["no_card"] += 1
        elif st == "already_paid":
            row["status"] = "not_chargeable"
            row["reason"] = "already_paid"
            summary["not_chargeable"] += 1
        elif st == "nothing_due":
            row["status"] = "not_chargeable"
            row["reason"] = "nothing_due"
            summary["not_chargeable"] += 1
        elif st in ("failed", "error"):
            row["reason"] = res.get("message") or "declined"
            summary["failed"] += 1
        else:
            row["reason"] = st
            summary["failed"] += 1
        results.append(row)

    logger.info(
        "[bulk-charge] tenant=%s user=%s summary=%s",
        tenant["id"], user.get("email"), summary,
    )
    return {"results": results, "summary": summary}


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
