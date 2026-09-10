"""Feb-2026 · Task 5 — Admin ``Charge on file`` endpoint.

Route: ``POST /api/invoices/{iid}/charge-saved-card``

Charges an invoice against a customer's saved payment method
off-session. Backed by ``PaymentIntent.create(off_session=True,
confirm=True, ...)`` — Stripe returns synchronously with success /
requires_action / declined.

Auth posture · staff-only. Roles ``super_admin``, ``admin``,
``manager`` are permitted; ``tech`` / ``technician`` / ``customer`` are
403. Cross-tenant charges are blocked at the invoice-lookup layer.

PCI SAQ A posture — the request body never carries card data.
Callers pass either a specific ``payment_method_id`` (Stripe pm_id, or
the mirror row id in ``db.payment_methods``) or nothing (default PM).
All raw card material lives inside Stripe.

Audit — every attempt writes one row to ``db.invoice_charge_attempts``
with the acting admin, target invoice, PM used, and outcome so we
have a paper trail independent of Stripe.

Response codes:

    200 OK
        {"status": "succeeded", "payment_intent_id": ...,
         "amount_cents": ..., "brand": "visa", "last4": "4242"}
    402 Payment Required (structured, machine-readable code)
        {"error_code": "authentication_required" |
                        "card_declined" | "insufficient_funds",
         "message": "..."}
    403 Forbidden — non-admin caller
    404 Not Found — invoice or payment method missing
    409 Conflict — invoice already paid
    502 Bad Gateway — Stripe unavailable
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db
from services.invoice_lookup import find_invoice_dual
from utils import get_current_user


router = APIRouter()
_LOG = logging.getLogger("invoice.charge_saved")
_ALLOWED_ROLES = {"super_admin", "admin", "manager"}


@router.get("/invoices/{iid}/saved-cards")
async def list_invoice_saved_cards(
    iid: str, user: dict = Depends(get_current_user),
):
    """Feb-2026 · Task 5 — admin-only helper for the ``Charge on
    file`` button. Returns the customer's saved cards keyed off the
    invoice's ``customer_id``. Response shape mirrors the customer
    portal PM list so the frontend can reuse the same picker
    component.
    """
    role = (user or {}).get("role") or ""
    if role not in _ALLOWED_ROLES:
        raise HTTPException(403, "forbidden")
    inv, _ = await find_invoice_dual(db, iid)
    if not inv:
        raise HTTPException(404, "invoice_not_found")
    tenant_id = inv.get("tenant_id") or ""
    if user.get("tenant_id") and user["tenant_id"] != tenant_id:
        raise HTTPException(403, "cross_tenant_forbidden")
    cid = inv.get("customer_id") or ""
    if not cid:
        return {"methods": []}
    rows = await db.payment_methods.find(
        {"tenant_id": tenant_id, "customer_id": cid,
         "type": {"$ne": "ach"}},
        {"_id": 0},
    ).sort([("is_default", -1), ("created_at", -1)]).to_list(50)
    return {
        "methods": [{
            "id": r.get("id") or r.get("provider_payment_method_id"),
            "provider_payment_method_id":
                r.get("provider_payment_method_id"),
            "brand": r.get("brand") or "Card",
            "last4": r.get("last4") or "",
            "exp_month": r.get("exp_month"),
            "exp_year": r.get("exp_year"),
            "default": bool(r.get("is_default")),
        } for r in rows],
    }


class ChargeSavedCardBody(BaseModel):
    payment_method_id: Optional[str] = None
    """Optional — either the Stripe ``pm_...`` id OR the mirror row
    ``payment_methods.id``. When absent, uses the customer's default PM.
    """


def _cents_from_amount(amount) -> int:
    try:
        return int(round(float(amount) * 100))
    except (TypeError, ValueError):
        return 0


async def _resolve_target_pm(
    *, tenant_id: str, customer_id: str,
    payment_method_id: Optional[str],
):
    """Return the mirror row for the target PM or None."""
    if payment_method_id:
        row = await db.payment_methods.find_one(
            {"tenant_id": tenant_id, "customer_id": customer_id,
             "$or": [{"id": payment_method_id},
                     {"provider_payment_method_id": payment_method_id}]},
            {"_id": 0},
        )
        return row
    # Default fallback — is_default flag first, then most recent.
    row = await db.payment_methods.find_one(
        {"tenant_id": tenant_id, "customer_id": customer_id,
         "is_default": True, "type": {"$ne": "ach"}},
        {"_id": 0},
    )
    if row:
        return row
    return await db.payment_methods.find_one(
        {"tenant_id": tenant_id, "customer_id": customer_id,
         "type": {"$ne": "ach"}},
        {"_id": 0},
        sort=[("created_at", -1)],
    )


async def _audit(
    *, tenant_id: str, invoice_id: str, admin_user_id: str,
    pm_id: str, outcome: str, error_code: Optional[str] = None,
    amount_cents: int = 0,
):
    await db.invoice_charge_attempts.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "invoice_id": invoice_id,
        "admin_user_id": admin_user_id,
        "payment_method_id": pm_id,
        "outcome": outcome,
        "error_code": error_code,
        "amount_cents": amount_cents,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


@router.post("/invoices/{iid}/charge-saved-card")
async def charge_saved_card(
    iid: str, body: Optional[ChargeSavedCardBody] = None,
    user: dict = Depends(get_current_user),
):
    role = (user or {}).get("role") or ""
    if role not in _ALLOWED_ROLES:
        raise HTTPException(403, "forbidden")
    admin_user_id = (user or {}).get("id") or ""

    inv, _collection = await find_invoice_dual(db, iid)
    if not inv:
        raise HTTPException(404, "invoice_not_found")
    tenant_id = inv.get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(500, "invoice_missing_tenant")
    if user.get("tenant_id") and user["tenant_id"] != tenant_id:
        raise HTTPException(403, "cross_tenant_forbidden")

    if (inv.get("payment_status") or "").lower() == "paid":
        raise HTTPException(409, "invoice_already_paid")

    customer_id = inv.get("customer_id") or ""
    if not customer_id:
        raise HTTPException(400, "invoice_missing_customer_id")

    cust = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id}, {"_id": 0},
    ) or {}
    stripe_customer_id = cust.get("stripe_customer_id") or ""
    if not stripe_customer_id:
        raise HTTPException(400, "customer_no_stripe_customer")

    payload = body or ChargeSavedCardBody()
    row = await _resolve_target_pm(
        tenant_id=tenant_id, customer_id=customer_id,
        payment_method_id=payload.payment_method_id,
    )
    if not row:
        raise HTTPException(404, "no_saved_payment_method")
    provider_pm_id = row.get("provider_payment_method_id") or ""
    if not provider_pm_id:
        raise HTTPException(400, "payment_method_missing_provider_id")

    total_due = inv.get("total_due")
    if total_due in (None, 0, 0.0):
        total_due = (inv.get("total") or 0) - (inv.get("amount_paid") or 0)
    amount_cents = _cents_from_amount(total_due)
    if amount_cents <= 0:
        raise HTTPException(400, "nothing_to_charge")

    # Real Stripe call. Wrap so we can map errors → structured JSON.
    try:
        import stripe as _stripe
        _stripe.api_key = os.environ.get("STRIPE_SECRET_KEY") or ""
        if not _stripe.api_key:
            raise RuntimeError("STRIPE_SECRET_KEY_missing")
        intent = _stripe.PaymentIntent.create(
            amount=amount_cents,
            currency=(inv.get("currency") or "usd"),
            customer=stripe_customer_id,
            payment_method=provider_pm_id,
            off_session=True,
            confirm=True,
            description=f"Invoice {inv.get('invoice_number') or iid}",
            metadata={
                "crm_invoice_id": iid,
                "crm_tenant_id": tenant_id,
                "crm_admin_user_id": admin_user_id,
                "crm_charge_source": "charge_saved_card",
            },
        )
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", "") or getattr(exc, "error", None) or ""
        code_s = (str(code) if code else "").lower()
        # Stripe surfaces ``authentication_required`` as CardError with
        # code == 'authentication_required'.
        if "authentication_required" in code_s:
            await _audit(
                tenant_id=tenant_id, invoice_id=iid,
                admin_user_id=admin_user_id, pm_id=provider_pm_id,
                outcome="requires_action",
                error_code="authentication_required",
                amount_cents=amount_cents,
            )
            raise HTTPException(
                status_code=402,
                detail={
                    "error_code": "authentication_required",
                    "message": (
                        "Card requires additional authentication — "
                        "please send the customer a fresh payment link."
                    ),
                },
            )
        if "card_declined" in code_s or "insufficient_funds" in code_s:
            await _audit(
                tenant_id=tenant_id, invoice_id=iid,
                admin_user_id=admin_user_id, pm_id=provider_pm_id,
                outcome="declined", error_code=code_s or "card_declined",
                amount_cents=amount_cents,
            )
            raise HTTPException(
                status_code=402,
                detail={
                    "error_code": code_s or "card_declined",
                    "message": "Card declined — try a different payment method.",
                },
            )
        _LOG.warning(
            "[charge_saved_card] gateway failure invoice=%s pm=%s exc=%s",
            iid, provider_pm_id, exc,
        )
        await _audit(
            tenant_id=tenant_id, invoice_id=iid,
            admin_user_id=admin_user_id, pm_id=provider_pm_id,
            outcome="gateway_error", error_code=type(exc).__name__,
            amount_cents=amount_cents,
        )
        raise HTTPException(
            status_code=502,
            detail={"error_code": "payment_gateway_unavailable"},
        )

    status = getattr(intent, "status", "") or ""
    pi_id = getattr(intent, "id", "") or ""
    if status == "succeeded":
        await _audit(
            tenant_id=tenant_id, invoice_id=iid,
            admin_user_id=admin_user_id, pm_id=provider_pm_id,
            outcome="succeeded", amount_cents=amount_cents,
        )
        _LOG.info(
            "[charge_saved_card] success invoice=%s admin=%s pm=%s amount=%s",
            iid, admin_user_id, provider_pm_id, amount_cents,
        )
        return {
            "status": "succeeded",
            "payment_intent_id": pi_id,
            "amount_cents": amount_cents,
            "brand": row.get("brand") or "",
            "last4": row.get("last4") or "",
        }

    if status == "requires_action":
        await _audit(
            tenant_id=tenant_id, invoice_id=iid,
            admin_user_id=admin_user_id, pm_id=provider_pm_id,
            outcome="requires_action",
            error_code="authentication_required",
            amount_cents=amount_cents,
        )
        raise HTTPException(
            status_code=402,
            detail={
                "error_code": "authentication_required",
                "message": (
                    "Card requires additional authentication — please "
                    "send the customer a fresh payment link."
                ),
            },
        )

    await _audit(
        tenant_id=tenant_id, invoice_id=iid,
        admin_user_id=admin_user_id, pm_id=provider_pm_id,
        outcome=status or "unknown", amount_cents=amount_cents,
    )
    raise HTTPException(
        status_code=402,
        detail={
            "error_code": status or "unknown_status",
            "message": f"Charge did not complete (status: {status}).",
        },
    )
