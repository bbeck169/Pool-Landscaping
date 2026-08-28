"""Phase 14a · Feb-2026 — Stripe endpoints.

Mounts under ``/api/payments/stripe/*``. Role guards:

* ``POST /setup-intent``           — customer (own record) OR admin/manager/super_admin.
* ``POST /attach``                 — customer (own record) OR admin/manager/super_admin.
* ``GET  /payment-methods/{cid}``  — customer (own record) OR admin/manager/super_admin.
                                     Technicians receive ``403`` (they must never see
                                     the mirrored card metadata).
* ``DELETE /payment-methods/{pm}`` — customer (own PM) OR admin/manager/super_admin.
* ``POST /charge``                 — admin/manager/super_admin ONLY. Tech + customer → 403.
* ``POST /webhook``                — public; signature verified inline.

Every endpoint returns JSON. Errors bubble up as HTTPException so the
FastAPI validator + our shared handler render the usual ``{detail: ...}``
envelope.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from config import db
from routers.tenants import get_current_tenant
from services.payments import stripe_charge as stripe_svc
from utils import get_current_user

router = APIRouter(prefix="/payments/stripe", tags=["payments-stripe"])
# Feb 2026 · P1 Hotfix #3 — Stripe Dashboard was historically pointed
# at ``/api/stripe/webhook`` (a legacy short path). The main router
# above mounts under ``/payments/stripe`` so that legacy URL returns
# 404 and Stripe retries endlessly, blocking payment-status updates.
# Expose a THIN alias router at ``/stripe`` that forwards to the same
# handler. The primary URL remains ``/api/payments/stripe/webhook``;
# this alias keeps the historical URL working with zero operator
# action (no Dashboard change required).
webhook_alias_router = APIRouter(prefix="/stripe", tags=["stripe-webhook-alias"])
logger = logging.getLogger("stripe_router")

_ADMIN_ROLES = ("admin", "manager", "super_admin")
_TECH_ROLES = ("technician", "tech")


# ── Helpers ───────────────────────────────────────────────────────────
def _is_admin(user: dict) -> bool:
    return (user.get("role") or "") in _ADMIN_ROLES


def _is_customer(user: dict) -> bool:
    return (user.get("role") or "") == "customer"


def _is_tech(user: dict) -> bool:
    return (user.get("role") or "") in _TECH_ROLES


def _require_self_or_admin(user: dict, customer_id: str) -> None:
    """Customer role → allowed only for their own customer_id.
    Admin/manager/super_admin → allowed for anyone in the tenant.
    Tech role → 403 (never sees card data)."""
    if _is_admin(user):
        return
    if _is_customer(user) and user.get("customer_id") == customer_id:
        return
    if _is_tech(user):
        raise HTTPException(403, "Technicians cannot access payment methods")
    raise HTTPException(403, "Not allowed")


def _require_admin(user: dict) -> None:
    if not _is_admin(user):
        raise HTTPException(403, "Admin/manager only")


async def _lookup_customer_from_pm(
    payment_method_id: str, tenant_id: str
) -> Optional[str]:
    row = await db.payment_methods.find_one(
        {
            "provider_payment_method_id": payment_method_id,
            "tenant_id": tenant_id,
            "provider": "stripe",
        },
        {"_id": 0, "customer_id": 1},
    )
    return row.get("customer_id") if row else None


# ── Request bodies ────────────────────────────────────────────────────
class SetupIntentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: Optional[str] = None  # required for admin-on-behalf; ignored for self-serve


class AttachBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: Optional[str] = None
    payment_method_id: str
    set_default: bool = True


class ChargeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: str
    payment_method_id: str
    amount_cents: int = Field(gt=0)
    currency: str = "usd"
    invoice_id: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


# ── Endpoints ─────────────────────────────────────────────────────────
@router.get("/config")
async def get_stripe_config(user: dict = Depends(get_current_user)):
    """Phase 20 · Feb-2026 · Sub-item C — return the Stripe
    publishable key + mode for the current pod, so the frontend can
    initialize ``<Elements>`` at page-load time without reading a
    ``REACT_APP_STRIPE_PUBLISHABLE_KEY`` env var.

    Role gate mirrors ``POST /setup-intent``: customer (any) OR
    admin/manager/super_admin. Techs are excluded (they never touch
    payment flows).
    """
    if not (_is_customer(user) or _is_admin(user)):
        raise HTTPException(403, "forbidden")
    return {
        "publishable_key": stripe_svc._publishable_key(),
        # Feb-2026 · FIX 4 — return BOTH ``mode`` (legacy) and
        # ``stripe_mode`` (new canonical) for one release cycle so
        # existing callers keep working. Deprecation of ``mode``
        # tracked in /app/memory/known_issues.md.
        "mode": stripe_svc._mode(),
        "stripe_mode": stripe_svc._mode(),
    }


@router.post("/setup-intent")
async def post_setup_intent(
    body: SetupIntentBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    # Self-serve customer → operate on THEIR customer_id, always. Admin →
    # must pass ``customer_id`` in the body.
    if _is_customer(user):
        target_id = user.get("customer_id")
        if not target_id:
            raise HTTPException(400, "customer account has no customer_id link")
    else:
        _require_admin(user)
        target_id = body.customer_id
        if not target_id:
            raise HTTPException(422, "customer_id is required for admin capture")
    try:
        return await stripe_svc.create_setup_intent(
            tenant_id=tenant["id"],
            customer_id=target_id,
            actor_user_id=user.get("id"),
        )
    except ValueError as exc:
        raise HTTPException(404 if "not found" in str(exc) else 400, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[stripe] setup_intent error: %s", exc)
        raise HTTPException(502, f"stripe error: {exc}")


@router.post("/attach")
async def post_attach(
    body: AttachBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if _is_customer(user):
        target_id = user.get("customer_id")
        if not target_id:
            raise HTTPException(400, "customer account has no customer_id link")
    else:
        _require_admin(user)
        target_id = body.customer_id
        if not target_id:
            raise HTTPException(422, "customer_id is required for admin capture")
    try:
        return await stripe_svc.attach_payment_method(
            tenant_id=tenant["id"],
            customer_id=target_id,
            payment_method_id=body.payment_method_id,
            set_default=body.set_default,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[stripe] attach error: %s", exc)
        raise HTTPException(502, f"stripe error: {exc}")


@router.get("/payment-methods/{customer_id}")
async def get_payment_methods(
    customer_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_self_or_admin(user, customer_id)
    rows = await stripe_svc.list_payment_methods(
        tenant_id=tenant["id"], customer_id=customer_id
    )
    return {"customer_id": customer_id, "payment_methods": rows}


@router.delete("/payment-methods/{payment_method_id}")
async def delete_payment_method(
    payment_method_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if _is_tech(user):
        raise HTTPException(403, "Technicians cannot access payment methods")
    owner = await _lookup_customer_from_pm(payment_method_id, tenant["id"])
    if not owner:
        raise HTTPException(404, "payment method not found")
    if _is_customer(user) and user.get("customer_id") != owner:
        raise HTTPException(403, "Not allowed")
    if not (_is_admin(user) or _is_customer(user)):
        raise HTTPException(403, "Not allowed")
    try:
        return await stripe_svc.detach_payment_method(
            tenant_id=tenant["id"], payment_method_id=payment_method_id
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[stripe] detach error: %s", exc)
        raise HTTPException(502, f"stripe error: {exc}")


@router.post("/charge")
async def post_charge(
    body: ChargeBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    # Admin-only. Tech and Customer roles must always 403.
    if _is_tech(user) or _is_customer(user):
        raise HTTPException(403, "Admin/manager only")
    _require_admin(user)
    try:
        return await stripe_svc.charge_card_on_file(
            tenant_id=tenant["id"],
            customer_id=body.customer_id,
            payment_method_id=body.payment_method_id,
            amount_cents=body.amount_cents,
            currency=body.currency,
            invoice_id=body.invoice_id,
            description=body.description,
            metadata=body.metadata,
            actor_user_id=user.get("id"),
        )
    except stripe_svc.ChargeAlreadySucceededError as exc:
        # Feb-2026 · FIX 1 — return 409 + existing PI so callers
        # can render "already paid" instead of double-charging.
        raise HTTPException(409, {
            "detail": "invoice already paid",
            "payment_intent_id": exc.payment_intent_id,
        })
    except stripe_svc.InvoiceAlreadyPaidError as exc:
        raise HTTPException(409, {"detail": "invoice already paid"})
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        # Charge attempts still get persisted inside ``charge_card_on_file``
        # so the audit trail survives — surface a 402 for card-decline
        # style errors and 502 for anything else.
        msg = str(exc)
        code = 402 if "declined" in msg.lower() or "card" in msg.lower() else 502
        raise HTTPException(code, msg or "stripe error")


@router.post("/session/{session_id}/reconcile",
              operation_id="stripe.session.reconcile")
async def reconcile_checkout_session(
    session_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Feb-2026 · Synchronous reconcile fallback for Checkout Sessions.

    Design gap this closes: the customer-portal invoice-pay flow ends
    with a browser redirect to ``/portal/payment-complete`` while the
    invoice status flip is driven ENTIRELY by
    ``checkout.session.completed`` webhook delivery. If Stripe's
    webhook mis-fires (Thin-payload rejection, transient network,
    Dashboard misconfig — all seen in the last two weeks on
    ``app.plofv.com``), the customer sees a "still processing"
    limbo while their card was actually charged.

    This endpoint lets the browser drive a synchronous reconcile as
    soon as it lands on ``/portal/payment-complete?session_id=…``.
    It fetches the Session from Stripe, verifies paid state + tenant
    ownership, then calls the SAME atomic ``_mark_invoice_paid_from
    _session`` the webhook uses. Idempotent by design — the helper
    short-circuits when ``invoice.payment_status == "paid"``, so a
    reconcile followed by a webhook (or vice versa) is a safe no-op
    on the second call.

    Auth:
      * customers may reconcile a session whose invoice they own
        (via ``user.customer_id == invoice.customer_id``).
      * admin-equivalent roles may reconcile any session in their
        tenant.

    Return shape:
      * ``{"reconciled": true,  "already_paid": <bool>,
             "invoice_id": ..., "amount_paid": <float>,
             "payment_status": "paid"|"partial"}``
      * ``{"reconciled": false, "reason": "unpaid",
             "payment_status": <stripe payment_status>}``
        — 200, not an error. The frontend falls back to polling.
    """
    # 1) Fetch the Session from Stripe (expand PI so we can stamp
    # ``stripe_payment_intent_id`` on the invoice for downstream audit
    # queries). Transient network / API failure → 502 so the browser
    # retries via its polling fallback.
    try:
        session = await stripe_svc._to_thread(
            stripe_svc._stripe.checkout.Session.retrieve,
            session_id, expand=["payment_intent"],
        )
    except Exception as exc:                                        # noqa: BLE001
        logger.warning(
            "[stripe.reconcile] session.retrieve failed sid=%s err=%s",
            session_id, exc,
        )
        raise HTTPException(
            502, f"stripe.session.retrieve failed: {exc}",
        )
    session_dict = stripe_svc._asdict(session)

    # 2) Session must be paid before we flip the invoice. Not an
    # error state — the caller polls if the customer landed here
    # while Stripe is still finalizing (bank-hold windows).
    if session_dict.get("payment_status") != "paid":
        return {
            "reconciled": False,
            "reason": "unpaid",
            "payment_status": session_dict.get("payment_status"),
        }

    # 3) Resolve the invoice id from the session and verify tenant scope.
    metadata = stripe_svc._asdict(session_dict.get("metadata") or {})
    invoice_id = (metadata.get("crm_invoice_id")
                   or session_dict.get("client_reference_id"))
    session_tenant = metadata.get("crm_tenant_id")
    if not invoice_id:
        raise HTTPException(
            400, "session has no crm_invoice_id or client_reference_id",
        )
    invoice = await db.quotes.find_one(
        {"id": invoice_id, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "customer_id": 1, "tenant_id": 1,
          "payment_status": 1, "amount_paid": 1, "total": 1},
    )
    if not invoice:
        # Either the invoice doesn't exist, or it lives in a
        # different tenant. Either way — this caller can't touch it.
        raise HTTPException(
            403, "invoice not found in caller's tenant",
        )
    # Extra guardrail — if the session metadata itself names a
    # different tenant, that's a strong tampering signal even
    # though ``find_one`` already scoped by tenant.
    if session_tenant and session_tenant != tenant["id"]:
        raise HTTPException(
            403, "session tenant does not match caller tenant",
        )
    # Customer-role callers must own the invoice too.
    role = (user.get("role") or "").lower()
    if role == "customer":
        if invoice.get("customer_id") != user.get("customer_id"):
            raise HTTPException(
                403, "invoice does not belong to caller",
            )

    # 4) Flip the invoice via the SAME helper the webhook uses.
    # Idempotent — returns False if the invoice was already paid.
    amount_total_cents = int(session_dict.get("amount_total") or 0)
    pi_field = session_dict.get("payment_intent")
    if isinstance(pi_field, dict):
        payment_intent_id = pi_field.get("id")
    else:
        payment_intent_id = pi_field  # str or None
    updated = await stripe_svc._mark_invoice_paid_from_session(
        invoice_id=invoice_id,
        amount_total_cents=amount_total_cents,
        session_id=session_id,
        payment_intent_id=payment_intent_id,
    )

    # Refetch to return the terminal amount_paid + payment_status.
    final = await db.quotes.find_one(
        {"id": invoice_id, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "amount_paid": 1, "payment_status": 1},
    ) or {}
    # Feb-2026 · Priority 3 — surface whether the checkout saved a
    # payment method for future billing so the payment-complete
    # screen can decide whether to prompt for autobilling. Flag
    # sources: session metadata (customer explicitly opted in at
    # checkout) AND the customer now carries a
    # ``default_payment_method_id`` (i.e. the async
    # ``_save_pm_after_first_payment`` finished). We also read
    # back ``autobilling_enabled`` so the frontend hides the CTA
    # for customers who already opted in on an earlier payment.
    payment_method_saved = False
    autobilling_enabled = False
    save_flag = str(metadata.get("crm_save_for_future") or "") == "1"
    if save_flag and invoice.get("customer_id"):
        cust_doc = await db.customers.find_one(
            {"id": invoice["customer_id"], "tenant_id": tenant["id"]},
            {"_id": 0, "default_payment_method_id": 1,
              "autobilling_enabled": 1},
        ) or {}
        payment_method_saved = bool(
            cust_doc.get("default_payment_method_id")
        )
        autobilling_enabled = bool(cust_doc.get("autobilling_enabled"))
    return {
        "reconciled": True,
        "already_paid": not updated,
        "invoice_id": invoice_id,
        "amount_paid": final.get("amount_paid") or 0.0,
        "payment_status": final.get("payment_status") or "paid",
        "payment_method_saved": payment_method_saved,
        "autobilling_enabled": autobilling_enabled,
    }


@router.post("/webhook")
async def post_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature") or ""
    try:
        event = stripe_svc.verify_and_parse_webhook(payload=payload, sig_header=sig)
    except stripe_svc.ThinPayloadRetrieveError as exc:
        # Feb-2026 · Transient failure hydrating a Thin-payload event via
        # ``stripe.Event.retrieve``. 502 tells Stripe "server-side blip,
        # please retry" — the webhook delivery pipeline honors 5xx with
        # exponential backoff, so the event isn't lost. A 4xx here would
        # silently drop the event.
        raise HTTPException(502, f"stripe.event.retrieve failed: {exc}")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # includes stripe.error.SignatureVerificationError
        raise HTTPException(400, f"invalid signature: {exc}")
    result = await stripe_svc.handle_webhook_event(event)
    return {"ok": True, **result}


# Feb 2026 · P1 Hotfix #3 — Legacy-URL alias. Stripe Dashboard was
# configured with the short path ``/api/stripe/webhook`` before the
# main router got its ``/payments/stripe`` prefix. Keep that URL live
# by forwarding to the same handler. Both routes accept the exact
# same payload + signature and produce identical responses.
@webhook_alias_router.post("/webhook")
async def post_webhook_alias(request: Request):
    return await post_webhook(request)
