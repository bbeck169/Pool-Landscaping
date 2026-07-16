"""Phase 53 · Stripe payments router — checkout, PaymentIntents, refunds,
subscriptions, and the reconciliation ledger feed.

Money-moving contract
=====================
* Every endpoint requires ``STRIPE_SECRET_KEY`` in ``os.environ``. When
  missing / invalid we return ``{"mocked": true, "reason":
  "stripe_not_configured"}`` with HTTP 200 so the frontend can render
  the disabled state without an error banner.
* Amounts are read from the invoice / product row **server-side only** —
  we never trust a frontend-supplied amount. See the security notes in
  the Stripe playbook.
* All webhook business logic lives in ``stripe_admin._STRIPE_EVENT_HANDLERS`` —
  this router only initiates the requests and persists the pending row
  in ``db.stripe_payments`` (aka the reconciliation ledger).

Ledger schema — ``db.stripe_payments``
======================================
```
{
  "id":              new_id(),
  "tenant_id":       str,
  "customer_id":     str | None,
  "invoice_id":      str | None,                    # our quote/invoice row
  "kind":            "checkout" | "payment_intent" | "subscription",
  "session_id":      str | None,                    # Stripe checkout session
  "payment_intent":  str | None,
  "charge_id":       str | None,
  "amount_cents":    int,
  "currency":        "usd",
  "status":          "initiated" | "processing" | "paid" | "failed" | "refunded",
  "customer_email":  str | None,
  "receipt_url":     str | None,
  "refunded_cents":  int,                           # running total
  "fee_cents":       int | None,
  "net_cents":       int | None,
  "created_at":      iso,
  "updated_at":      iso,
  "metadata":        dict                           # our internal ids
}
```
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from config import db, logger
from routers.tenants import get_current_tenant
from services.stripe_client import get_stripe, is_configured
from utils import get_current_user, new_id, now_iso, require_admin

router = APIRouter(prefix="/stripe", tags=["stripe"])

DEFAULT_STATEMENT_DESCRIPTOR = "POOL LANDSCPE VISTANCA"[:22]
DEFAULT_PAYMENT_METHODS = ["card", "us_bank_account"]


def _unavailable() -> dict:
    """Standard body returned when Stripe env is missing/invalid."""
    return {"mocked": True, "reason": "stripe_not_configured"}


def _dollars_to_cents(v) -> int:
    return int(round(float(v or 0) * 100))


async def _load_invoice(inv_id: str, tenant_id: str) -> dict:
    """Load a quote/invoice row scoped to the caller's tenant."""
    doc = await db.quotes.find_one({"id": inv_id, "tenant_id": tenant_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Invoice not found")
    if doc.get("doc_type") == "quote":
        # Allow paying a quote (this converts it to an invoice on success)
        pass
    return doc


async def _outstanding_cents(inv: dict) -> int:
    total_cents = _dollars_to_cents(inv.get("total"))
    paid_cents = _dollars_to_cents(inv.get("amount_paid"))
    return max(total_cents - paid_cents, 0)


# ─── Checkout Session (Hosted) ────────────────────────────────────────────
class CheckoutBody(BaseModel):
    invoice_id: str
    origin: str = Field(..., description="window.location.origin from the browser")


@router.post("/checkout/session")
async def create_checkout_session(
    body: CheckoutBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if not is_configured():
        return _unavailable()

    inv = await _load_invoice(body.invoice_id, tenant["id"])
    amt_cents = await _outstanding_cents(inv)
    if amt_cents <= 0:
        raise HTTPException(400, "Invoice is already fully paid")

    origin = (body.origin or "").rstrip("/")
    success_url = f"{origin}/invoices/{inv['id']}?stripe=success&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/invoices/{inv['id']}?stripe=cancel"

    stripe = get_stripe()
    total_cents_key = _dollars_to_cents(inv.get("total"))
    paid_cents_key = _dollars_to_cents(inv.get("amount_paid"))
    idem_key = f"co:{tenant['id']}:{inv['id']}:{total_cents_key}:{paid_cents_key}"
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=DEFAULT_PAYMENT_METHODS,
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": amt_cents,
                    "product_data": {
                        "name": (inv.get("title") or f"Invoice {inv['id'][:8]}"),
                        "description": inv.get("customer_name") or "",
                    },
                },
                "quantity": 1,
            }],
            payment_intent_data={
                "statement_descriptor": DEFAULT_STATEMENT_DESCRIPTOR,
                "metadata": {
                    "tenant_id": tenant["id"],
                    "invoice_id": inv["id"],
                    "customer_id": inv.get("customer_id") or "",
                },
            },
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "tenant_id": tenant["id"],
                "invoice_id": inv["id"],
                "customer_id": inv.get("customer_id") or "",
                "kind": "invoice_pay_now",
            },
            idempotency_key=idem_key,
        )
    except Exception as e:
        logger.warning(f"stripe checkout create failed: {type(e).__name__}")
        return {"mocked": True, "reason": "stripe_error", "error_type": type(e).__name__}

    ledger_id = new_id()
    await db.stripe_payments.insert_one({
        "id": ledger_id,
        "tenant_id": tenant["id"],
        "customer_id": inv.get("customer_id"),
        "invoice_id": inv["id"],
        "kind": "checkout",
        "session_id": session["id"],
        "payment_intent": session.get("payment_intent"),
        "charge_id": None,
        "amount_cents": amt_cents,
        "currency": "usd",
        "status": "initiated",
        "customer_email": inv.get("customer_email"),
        "receipt_url": None,
        "refunded_cents": 0,
        "fee_cents": None,
        "net_cents": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "metadata": {"invoice_id": inv["id"], "customer_id": inv.get("customer_id")},
    })
    return {"session_id": session["id"], "url": session["url"], "ledger_id": ledger_id}


@router.get("/checkout/status/{session_id}")
async def checkout_status(
    session_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Polling endpoint used by the frontend after Stripe redirects back
    to the invoice page. Reconciles the local ledger row idempotently
    even before the webhook lands."""
    if not is_configured():
        return _unavailable()
    stripe = get_stripe()
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception as e:
        logger.warning(f"stripe session retrieve failed: {type(e).__name__}")
        return {"mocked": True, "reason": "stripe_error"}
    row = await db.stripe_payments.find_one({"tenant_id": tenant["id"], "session_id": session_id}, {"_id": 0})
    if row and row.get("status") not in ("paid", "refunded", "failed") and session.get("payment_status") == "paid":
        # Idempotent apply — webhook may or may not have landed yet.
        from routers.stripe_admin import _apply_paid_invoice
        await _apply_paid_invoice(row, session)
    return {
        "session_id": session_id,
        "status": session.get("status"),
        "payment_status": session.get("payment_status"),
        "amount_total": session.get("amount_total"),
        "currency": session.get("currency"),
        "customer_email": session.get("customer_details", {}).get("email") if isinstance(session.get("customer_details"), dict) else None,
    }


# ─── PaymentIntent (Stripe Elements in-app) ────────────────────────────────
class PaymentIntentBody(BaseModel):
    invoice_id: str


@router.post("/payment-intent")
async def create_payment_intent(
    body: PaymentIntentBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if not is_configured():
        return _unavailable()
    inv = await _load_invoice(body.invoice_id, tenant["id"])
    amt_cents = await _outstanding_cents(inv)
    if amt_cents <= 0:
        raise HTTPException(400, "Invoice is already fully paid")
    stripe = get_stripe()
    try:
        pi = stripe.PaymentIntent.create(
            amount=amt_cents,
            currency="usd",
            automatic_payment_methods={"enabled": True},
            statement_descriptor_suffix=DEFAULT_STATEMENT_DESCRIPTOR[:22],
            metadata={
                "tenant_id": tenant["id"],
                "invoice_id": inv["id"],
                "customer_id": inv.get("customer_id") or "",
                "kind": "invoice_pay_now",
            },
            idempotency_key=f"pi:{tenant['id']}:{inv['id']}:{_dollars_to_cents(inv.get('amount_paid'))}",
        )
    except Exception as e:
        logger.warning(f"stripe payment_intent create failed: {type(e).__name__}")
        return {"mocked": True, "reason": "stripe_error", "error_type": type(e).__name__}

    ledger_id = new_id()
    await db.stripe_payments.insert_one({
        "id": ledger_id,
        "tenant_id": tenant["id"],
        "customer_id": inv.get("customer_id"),
        "invoice_id": inv["id"],
        "kind": "payment_intent",
        "session_id": None,
        "payment_intent": pi["id"],
        "charge_id": None,
        "amount_cents": amt_cents,
        "currency": "usd",
        "status": "initiated",
        "customer_email": inv.get("customer_email"),
        "receipt_url": None,
        "refunded_cents": 0,
        "fee_cents": None,
        "net_cents": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "metadata": {"invoice_id": inv["id"], "customer_id": inv.get("customer_id")},
    })
    return {"client_secret": pi["client_secret"], "payment_intent": pi["id"], "amount_cents": amt_cents, "ledger_id": ledger_id}


# ─── Refunds ───────────────────────────────────────────────────────────────
class RefundBody(BaseModel):
    payment_id: str = Field(..., description="local ledger row id OR Stripe payment_intent / charge id")
    amount_cents: Optional[int] = Field(None, ge=1, description="Partial refund; omit for full refund")
    reason: Optional[str] = Field(None, description="requested_by_customer | duplicate | fraudulent")


@router.post("/refunds")
async def create_refund(
    body: RefundBody,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    if not is_configured():
        return _unavailable()
    row = await db.stripe_payments.find_one(
        {"tenant_id": tenant["id"],
         "$or": [{"id": body.payment_id}, {"payment_intent": body.payment_id}, {"charge_id": body.payment_id}]},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Payment not found in ledger")
    if row.get("status") not in ("paid",):
        raise HTTPException(400, "Only paid payments can be refunded")
    already_refunded = int(row.get("refunded_cents") or 0)
    max_refundable = int(row.get("amount_cents") or 0) - already_refunded
    if max_refundable <= 0:
        raise HTTPException(400, "Nothing left to refund")
    amt = int(body.amount_cents or max_refundable)
    if amt > max_refundable:
        raise HTTPException(400, "Refund amount exceeds remaining refundable balance")
    stripe = get_stripe()
    try:
        params = {"amount": amt}
        if row.get("payment_intent"):
            params["payment_intent"] = row["payment_intent"]
        elif row.get("charge_id"):
            params["charge"] = row["charge_id"]
        else:
            raise HTTPException(400, "No underlying Stripe payment to refund")
        if body.reason:
            params["reason"] = body.reason
        params["metadata"] = {"tenant_id": tenant["id"], "invoice_id": row.get("invoice_id") or ""}
        refund = stripe.Refund.create(**params)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"stripe refund create failed: {type(e).__name__}")
        return {"mocked": True, "reason": "stripe_error", "error_type": type(e).__name__}

    new_refunded = already_refunded + amt
    new_status = "refunded" if new_refunded >= int(row.get("amount_cents") or 0) else "paid"
    await db.stripe_payments.update_one(
        {"id": row["id"]},
        {"$set": {"refunded_cents": new_refunded, "status": new_status, "updated_at": now_iso()}},
    )
    # Sync the invoice — decrement amount_paid.
    if row.get("invoice_id"):
        inv = await db.quotes.find_one({"id": row["invoice_id"], "tenant_id": tenant["id"]}, {"_id": 0})
        if inv:
            new_paid = max(float(inv.get("amount_paid") or 0) - amt / 100.0, 0.0)
            total = float(inv.get("total") or 0)
            await db.quotes.update_one(
                {"id": inv["id"], "tenant_id": tenant["id"]},
                {"$set": {
                    "amount_paid": round(new_paid, 2),
                    "payment_status": "paid" if new_paid + 0.01 >= total else ("partial" if new_paid > 0 else "unpaid"),
                }},
            )
    return {"refund_id": refund.get("id"), "amount_cents": amt, "status": new_status}


# ─── Reconciliation feed ───────────────────────────────────────────────────
@router.get("/payments")
async def list_payments(
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Reconciliation ledger — /admin/finance/stripe-payments feed."""
    q: dict = {"tenant_id": tenant["id"]}
    if status:
        q["status"] = status
    rows = await db.stripe_payments.find(q, {"_id": 0}).sort("created_at", -1).skip(offset).limit(limit).to_list(limit)
    # Rollups
    tot = {"paid_cents": 0, "refunded_cents": 0, "net_cents": 0, "count": len(rows)}
    for r in rows:
        if r.get("status") in ("paid", "refunded"):
            tot["paid_cents"] += int(r.get("amount_cents") or 0)
            tot["refunded_cents"] += int(r.get("refunded_cents") or 0)
    tot["net_cents"] = tot["paid_cents"] - tot["refunded_cents"]
    return {"rows": rows, "rollup": tot}


# ─── Products & Prices (thin wrapper for the admin UI) ────────────────────
@router.get("/products")
async def list_products(user: dict = Depends(require_admin)):
    if not is_configured():
        return _unavailable()
    stripe = get_stripe()
    try:
        prods = stripe.Product.list(active=True, limit=100)
    except Exception as e:
        logger.warning(f"stripe products list failed: {type(e).__name__}")
        return {"mocked": True, "reason": "stripe_error"}
    out = []
    for p in prods.get("data", []):
        try:
            prices = stripe.Price.list(product=p["id"], active=True, limit=20)
            plist = [{"id": pr["id"], "unit_amount": pr.get("unit_amount"),
                       "currency": pr.get("currency"),
                       "recurring": pr.get("recurring")} for pr in prices.get("data", [])]
        except Exception:
            plist = []
        out.append({"id": p["id"], "name": p.get("name"), "description": p.get("description"),
                     "active": p.get("active"), "prices": plist})
    return {"products": out}


class ProductBody(BaseModel):
    name: str
    description: Optional[str] = None
    unit_amount_cents: int = Field(..., ge=50, description="in cents")
    interval: Optional[str] = Field(None, description="month | year | week | day; omit for one-time")


@router.post("/products")
async def create_product(body: ProductBody, user: dict = Depends(require_admin)):
    if not is_configured():
        return _unavailable()
    stripe = get_stripe()
    try:
        prod = stripe.Product.create(name=body.name, description=body.description or None)
        price_params = {
            "product": prod["id"],
            "unit_amount": body.unit_amount_cents,
            "currency": "usd",
        }
        if body.interval:
            price_params["recurring"] = {"interval": body.interval}
        price = stripe.Price.create(**price_params)
    except Exception as e:
        logger.warning(f"stripe product create failed: {type(e).__name__}")
        return {"mocked": True, "reason": "stripe_error", "error_type": type(e).__name__}
    return {"product_id": prod["id"], "price_id": price["id"]}


# ─── Subscriptions ────────────────────────────────────────────────────────
class SubscriptionBody(BaseModel):
    customer_id: str = Field(..., description="Our internal customer id")
    price_id: str = Field(..., description="Stripe price id")


@router.post("/subscriptions")
async def create_subscription(
    body: SubscriptionBody,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    if not is_configured():
        return _unavailable()
    cust = await db.customers.find_one({"id": body.customer_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not cust:
        raise HTTPException(404, "Customer not found")
    stripe = get_stripe()
    try:
        stripe_cust_id = cust.get("stripe_customer_id")
        if not stripe_cust_id:
            sc = stripe.Customer.create(
                name=cust.get("name"),
                email=cust.get("email"),
                phone=(cust.get("phone") or None),
                metadata={"tenant_id": tenant["id"], "customer_id": cust["id"]},
            )
            stripe_cust_id = sc["id"]
            await db.customers.update_one(
                {"id": cust["id"], "tenant_id": tenant["id"]},
                {"$set": {"stripe_customer_id": stripe_cust_id}},
            )
        sub = stripe.Subscription.create(
            customer=stripe_cust_id,
            items=[{"price": body.price_id}],
            metadata={"tenant_id": tenant["id"], "customer_id": cust["id"]},
        )
    except Exception as e:
        logger.warning(f"stripe subscription create failed: {type(e).__name__}")
        return {"mocked": True, "reason": "stripe_error", "error_type": type(e).__name__}

    await db.stripe_subscriptions.insert_one({
        "id": new_id(),
        "tenant_id": tenant["id"],
        "customer_id": cust["id"],
        "stripe_customer_id": stripe_cust_id,
        "subscription_id": sub["id"],
        "price_id": body.price_id,
        "status": sub.get("status"),
        "current_period_end": sub.get("current_period_end"),
        "created_at": now_iso(),
    })
    return {"subscription_id": sub["id"], "status": sub.get("status")}


@router.get("/subscriptions")
async def list_subscriptions_for_customer(
    customer_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    rows = await db.stripe_subscriptions.find(
        {"tenant_id": tenant["id"], "customer_id": customer_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    return {"subscriptions": rows}
