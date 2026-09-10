"""Feb-2026 P0 · Public magic-link pay flow — Stripe Checkout Session.

Route: ``POST /api/invoices/{iid}/request-payment-link-magic?token=<jwt>``

Symmetric to :mod:`routers.invoice_magic_view` for the read path.
Customers arriving via an emailed / SMS'd pay link land on
``/pay/invoice/{id}?token=<jwt>`` in the frontend WITHOUT an
authenticated portal session. The existing
``routers.lumino_link_request.request_payment_link`` endpoint is
gated on ``Depends(get_current_user)`` so those customers can't
mint a Checkout Session — the pay modal froze on "Preparing your
secure payment link…" in production (see the P0 bug report from
2026-02).

This endpoint verifies the SAME magic-link JWT
:func:`routers.invoice_magic_view._verify_invoice_magic_token`
accepts for the read path, then delegates to the same
``services.payments.stripe_charge.create_invoice_checkout_session``
Session builder. No new Stripe code paths — the customer just
gets to reach them without a portal login.

Token contract (fail-closed):

* ``sub``         must equal ``"invoice_pay"``.
* ``invoice_id``  must match the URL ``iid``.
* ``tenant_id``   must resolve to a live tenant row.
* ``exp``         30-day expiry.

Rate limit: piggybacks on the shared invoice-id rate window in
``routers.lumino_link_request._RATE_STATE`` (5 requests / 60 s /
invoice) so a customer can't rapidly re-fire the endpoint by
reloading the pay page. Anti-abuse only — the Session is idempotent
downstream so this is defensive, not correctness.

Save-for-future-billing: DISABLED on the magic-link path. The
magic-link customer has no portal login to manage their saved
methods with, so we never silently store one behind them. If the
tenant wants a "save my card" experience for magic-link customers
we'd have to bounce them into the portal login flow first — out
of scope for this P0.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from config import db
from routers.invoice_magic_view import _verify_invoice_magic_token
from routers.lumino_link_request import _rate_limit_check


router = APIRouter()


@router.post("/invoices/{iid}/request-payment-link-magic")
async def request_payment_link_magic(
    iid: str, token: str = Query(""),
):
    payload = _verify_invoice_magic_token(token)
    if payload.get("invoice_id") != iid:
        raise HTTPException(401, "token_invoice_mismatch")
    tenant_id = payload.get("tenant_id")

    if not _rate_limit_check(iid):
        raise HTTPException(429, "rate_limited")

    # Resolve the invoice ONLY inside the token's tenant — cross-tenant
    # leak-proof by construction.
    from services.invoice_lookup import find_invoice_dual
    inv, _collection = await find_invoice_dual(db, iid)
    if not inv:
        raise HTTPException(404, "invoice_not_found")
    if inv.get("tenant_id") != tenant_id:
        raise HTTPException(401, "token_invoice_mismatch")

    # Reuse the doc-type guard — magic-link customers should never be
    # able to pay against a quote / estimate.
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

    # Load the customer for the Session builder — best-effort.
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
            tenant_id=tenant_id,
            invoice=inv,
            customer=customer,
            # Magic-link customers never enter the save-a-card path —
            # they have no portal account to manage the saved method.
            save_for_future_billing=False,
        )
    except ValueError as exc:
        code = str(exc)
        if code == "invoice_already_paid":
            raise HTTPException(409, "invoice_already_paid")
        if code.startswith("APP_PUBLIC_URL"):
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "payment_gateway_unavailable",
                    "reason": "APP_PUBLIC_URL not configured",
                },
            )
        raise HTTPException(
            status_code=503,
            detail={"error": "payment_gateway_unavailable", "reason": code},
        )
    except Exception as exc:  # noqa: BLE001
        # Any other failure surfaces as a friendly 503 so the frontend
        # renders the retry copy — no naked 500s at the boundary.
        raise HTTPException(
            status_code=503,
            detail={
                "error": "payment_gateway_unavailable",
                "reason": type(exc).__name__,
            },
        )

    return out
