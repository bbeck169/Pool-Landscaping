"""LZ2 · Feb-2026 — Retroactive "request payment link" endpoint.

POST /api/invoices/{invoice_id}/request-payment-link — allows the
frontend to re-fire the Zap when a customer clicks Pay on an
invoice that still has no ``lumino_payment_url`` (e.g. Zap failed
the first time, or invoice pre-dates LZ2).

Invoices live in two collections in this codebase:
  • ``db.quotes`` where ``doc_type == "invoice"`` (main creation path
    via ``POST /api/quotes``)
  • ``db.quotes`` with ``doc_type == "invoice"``  (source of truth,
    lumino_return, etc — where LZ1's callback writes)
This endpoint looks in BOTH so it works regardless of provenance.

Rate limit: 5 requests / 60s per invoice, enforced via a bounded
in-memory dict. Not distributed — if we scale to >1 pod we'd move
to a Mongo TTL collection.
"""
from __future__ import annotations

import time
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException

from config import db
from services.lumino_zapier_dispatcher import dispatch_invoice_link_request
from utils import get_current_user

router = APIRouter()

# invoice_id → list[timestamps]. Trimmed opportunistically.
_RATE_STATE: Dict[str, list] = {}
_WINDOW_SECS = 60
_MAX_PER_WINDOW = 5


def _rate_limit_check(invoice_id: str) -> bool:
    now = time.time()
    hist = _RATE_STATE.setdefault(invoice_id, [])
    hist[:] = [t for t in hist if now - t < _WINDOW_SECS]
    if len(hist) >= _MAX_PER_WINDOW:
        return False
    hist.append(now)
    # Cap memory — prune stale keys opportunistically.
    if len(_RATE_STATE) > 5000:
        stale = [k for k, v in _RATE_STATE.items() if not v]
        for k in stale[:1000]:
            _RATE_STATE.pop(k, None)
    return True


async def _lookup_invoice(invoice_id: str) -> dict | None:
    """Delegate to the shared dual-collection helper."""
    from services.invoice_lookup import find_invoice_dual
    doc, _collection = await find_invoice_dual(db, invoice_id)
    return doc


@router.post("/invoices/{invoice_id}/request-payment-link")
async def request_payment_link(
    invoice_id: str,
    user: dict = Depends(get_current_user),
):
    """Phase 47 · Feb-2026 — RESERVED direct-Stripe Checkout flow.

    User has directed every payment surface must route through Stripe
    directly (no Lumino / Zapier). This endpoint now creates a
    ``stripe.checkout.Session`` (mode="payment") and returns the
    ready-to-redirect ``payment_url``. The Zapier catch-hook + Lumino
    dispatcher modules stay in-tree but no traffic flows to them.

    Response shape:
        {"payment_url": "https://checkout.stripe.com/…",
         "checkout_session_id": "cs_test_…",
         "amount_cents": <balance in cents>,
         "currency": "usd",
         "mode": "test" | "live"}

    Auth: any authenticated user. Customer role is scoped to their own
    invoices; staff can trigger for any invoice.
    """
    if not _rate_limit_check(invoice_id):
        raise HTTPException(429, "rate_limited")

    inv = await _lookup_invoice(invoice_id)
    if not inv:
        raise HTTPException(404, "invoice_not_found")

    # Ownership check for customer role.
    if user.get("role") == "customer":
        if inv.get("customer_id") != user.get("customer_id"):
            raise HTTPException(403, "not_your_invoice")

    # Load minimal customer doc for the payload / Session.
    customer: dict = {}
    cid = inv.get("customer_id")
    if cid:
        cust = await db.customers.find_one({"id": cid}, {"_id": 0})
        if cust:
            customer = cust
    if not customer:
        customer = {
            "id": cid,
            "name": inv.get("customer_name"),
            "email": inv.get("customer_email"),
        }

    from services.payments import stripe_charge as stripe_svc
    try:
        out = await stripe_svc.create_invoice_checkout_session(
            tenant_id=inv.get("tenant_id"),
            invoice=inv,
            customer=customer,
        )
    except ValueError as exc:
        # Business-logic failures (already paid, missing config, etc.)
        # surface as 4xx so the frontend renders a specific message
        # instead of the generic retry copy.
        code = str(exc)
        status = 409 if code == "invoice_already_paid" else 400
        raise HTTPException(status, code)
    except Exception as exc:
        # Stripe SDK failure or transient outage — 502 lets the browser
        # differentiate a "we couldn't reach the gateway" case from a
        # bad-request case (409/400 above).
        import logging as _logging
        _logging.getLogger("phase47").warning(
            "[phase47] checkout.Session.create failed for invoice=%s: %s",
            invoice_id, exc,
        )
        raise HTTPException(502, "payment_gateway_unavailable")

    return out
