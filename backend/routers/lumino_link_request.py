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

Feb 2026 addendum · save-on-first-payment.
Accepts an optional ``save_for_future_billing`` body flag. When
``True`` AND the customer has zero saved payment methods today, the
Checkout Session's PaymentIntent gets ``setup_future_usage="off_
session"``. Existing-PM customers or explicit opt-outs bypass this
entirely — we never silently promote a new PM behind a customer who
already chose one.
"""
from __future__ import annotations

import time
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from config import db
from utils import get_current_user

router = APIRouter()


# Feb 2026 addendum body — optional so older clients that don't send
# it keep working.
class PayLinkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    save_for_future_billing: Optional[bool] = False


async def _customer_pm_count(
    tenant_id: Optional[str],
    customer_id: Optional[str],
) -> int:
    """How many saved payment methods does this customer already have?

    Returns 0 when either id is missing so callers can safely treat
    "unknown tenant/customer" as "no PMs on file". On a hard read
    failure we err ON THE SAFE SIDE — return a sentinel large enough
    to fail the "0 PMs" gate downstream so we DON'T silently save
    behind an unhealthy collection.
    """
    if not tenant_id or not customer_id:
        return 0
    try:
        return await db.payment_methods.count_documents({
            "tenant_id": tenant_id,
            "customer_id": customer_id,
        })
    except Exception:
        return 999

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
    body: Optional[PayLinkBody] = None,
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
         "mode": "test" | "live",
         "save_for_future_billing": bool  # what actually got applied}

    Auth: any authenticated user. Customer role is scoped to their own
    invoices; staff can trigger for any invoice.

    Feb 2026 addendum — accepts ``save_for_future_billing`` in the
    body. Effective iff the customer has ZERO saved payment methods
    (server-side gate). Existing-PM customers keep their current
    default untouched.
    """
    if not _rate_limit_check(invoice_id):
        raise HTTPException(429, "rate_limited")

    inv = await _lookup_invoice(invoice_id)
    if not inv:
        raise HTTPException(404, "invoice_not_found")

    # Feb-2026 · P0 doc-type guard — the pay-link endpoint is
    # invoice-only.  ``find_invoice_dual`` will happily resolve a
    # quote/estimate row because both share the ``quotes``
    # collection; before this guard, clicking "Payment link" on an
    # Estimate detail page would 500 downstream in the Stripe
    # session creator OR (worse) mint a checkout session against
    # an estimate's total.  Refusing at the boundary keeps the
    # error message user-actionable.
    _doc_type = str(inv.get("doc_type") or "invoice").lower()
    if _doc_type in ("estimate", "quote"):
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "not_an_invoice",
                "message": (
                    f"Payment links can only be generated for invoices. "
                    f"This document is a {_doc_type}."
                ),
                "doc_type": _doc_type,
            },
        )

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

    # Feb 2026 addendum · resolve the save flag server-side.
    # The caller may have set it optimistically; we only honour it
    # when the customer has 0 saved PMs today.
    save_requested = bool((body or PayLinkBody()).save_for_future_billing)
    pm_count = await _customer_pm_count(inv.get("tenant_id"), cid)
    save_for_future = save_requested and pm_count == 0

    from services.payments import stripe_charge as stripe_svc
    try:
        out = await stripe_svc.create_invoice_checkout_session(
            tenant_id=inv.get("tenant_id"),
            invoice=inv,
            customer=customer,
            save_for_future_billing=save_for_future,
        )
    except ValueError as exc:
        # Business-logic failures (already paid, missing config, etc.)
        # surface as 4xx so the frontend renders a specific message
        # instead of the generic retry copy.
        code = str(exc)
        if code == "invoice_already_paid":
            raise HTTPException(409, "invoice_already_paid")
        # Feb-2026 P0 belt-and-braces — ``create_invoice_checkout_session``
        # raises ``ValueError("APP_PUBLIC_URL not configured")`` when
        # the env var is unset in the running pod. Frontend
        # ``PaymentForm.extractErrorCode`` doesn't map that literal
        # string, so users would see the generic
        # ``"Something went wrong preparing your payment link"`` copy.
        # Collapse every non-``invoice_already_paid`` config-time
        # ValueError to the SAME 502 code that the SDK-exception path
        # below uses so operators see a single well-known error mode
        # regardless of which env var is missing.
        import logging as _logging
        _logging.getLogger("phase47").warning(
            "[phase47] checkout config error for invoice=%s: %s",
            invoice_id, code,
        )
        raise HTTPException(502, "payment_gateway_unavailable")
    except stripe_svc._UnconfiguredStripeError as exc:
        # Feb-2026 P0 belt-and-braces — ``_init_api_key()`` raises this
        # from INSIDE ``create_invoice_checkout_session`` when no
        # Stripe secret key resolves in the running pod. Previously
        # bubbled up as an unmapped 500 → frontend showed the generic
        # error. Now maps to the same friendly code as any other
        # gateway outage so ops sees a single well-known error mode.
        import logging as _logging
        _logging.getLogger("phase47").warning(
            "[phase47] Stripe unconfigured for invoice=%s: %s",
            invoice_id, exc,
        )
        raise HTTPException(502, "payment_gateway_unavailable")
    except stripe_svc._IdempotencyConflict as exc:
        # Feb-2026 · TD-invoice-pay-now-stripe-idempotency-conflict —
        # ``create_invoice_checkout_session`` raises this when the
        # Stripe SDK returns ``IdempotencyError`` on the Checkout
        # Session create call (same ``idempotency_key`` replayed with
        # drifted params).  Map to HTTP 409 with the specific error
        # code so operators + the frontend can distinguish a param-
        # drift replay from a transient gateway outage (the 502 catch-
        # all below).  MUST stay AHEAD of the generic
        # ``except Exception`` so the specific case wins.
        import logging as _logging
        _logging.getLogger("phase47").warning(
            "[phase47] Stripe idempotency conflict for invoice=%s: %s",
            invoice_id, exc,
        )
        raise HTTPException(
            status_code=409,
            detail={"error": "stripe_idempotency_conflict",
                    "detail": str(exc)},
        )
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

    # Feb-2026 · Task 3 — Invoices bypass portal. Enrich the response
    # with a portal-free magic-link URL under `/i/<token>` so callers
    # (dunning, email/SMS reminders, admin toolbar) can send customers
    # to the full invoice viewer + inline Pay Now without routing
    # through the authenticated portal chrome. ``payment_url`` (the
    # Stripe hosted Checkout) stays as-is for direct-to-Stripe use.
    try:
        import os as _os
        from services.pay_link_builder import issue_invoice_magic_token
        _tid = inv.get("tenant_id")
        if _tid:
            _base = (_os.environ.get("APP_PUBLIC_URL") or "").rstrip("/")
            _tok = issue_invoice_magic_token(invoice_id, _tid, days=30)
            out["magic_link_url"] = (
                f"{_base}/i/{_tok}" if _base else f"/i/{_tok}"
            )
    except Exception:  # noqa: BLE001
        # Never fail the pay-link request over the enrichment path.
        pass

    return out
