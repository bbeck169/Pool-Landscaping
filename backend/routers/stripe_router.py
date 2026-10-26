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
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
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
    # B1 · Feb-2026 — Admin ACH parity.  Callers pass
    # ``["us_bank_account"]`` to drive the ACH flow through the same
    # admin endpoint the card flow uses.  Default (``None``)
    # preserves the historical card-only behaviour.
    payment_method_types: Optional[List[str]] = None


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

    Phase K1 · Feb-2026 — adds an explicit ``stripe_configured``
    boolean so the frontend can render a neutral customer-facing
    fallback instead of exposing raw env-var names when the pod
    hasn't been configured.

    Role gate mirrors ``POST /setup-intent``: customer (any) OR
    admin/manager/super_admin. Techs are excluded (they never touch
    payment flows).
    """
    if not (_is_customer(user) or _is_admin(user)):
        raise HTTPException(403, "forbidden")
    pub_key = stripe_svc._publishable_key()
    stripe_configured = bool(pub_key)
    if not stripe_configured:
        stripe_svc._warn_unconfigured_once_per_hour()
    return {
        "publishable_key": pub_key,
        "stripe_configured": stripe_configured,
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
            # B1 · Feb-2026 — thread the caller's payment_method_types
            # through so admins can start an ACH SetupIntent from the
            # Customer Detail Payments tab.  ``None`` preserves the
            # card-only default inside the service.
            payment_method_types=body.payment_method_types,
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


# ── Phase I5 · Feb-2026 — Typed-last4 delete gate. ─────────────────
# Defense-in-depth on top of the raw DELETE above: the frontend
# TypedConfirmModal makes the operator retype the last-4 before
# arming Delete; this endpoint re-validates that keyword server-side
# so a scripted client can't skip the frontend check. Kept as its
# own endpoint (not folded into the DELETE) so B-series callers of
# the plain DELETE keep working unchanged.
class TypedDeleteBody(BaseModel):
    typed_last4: str = Field(..., min_length=1, max_length=8)


@router.post("/payment-methods/{payment_method_id}/delete-typed")
async def delete_payment_method_typed(
    payment_method_id: str,
    body: TypedDeleteBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if _is_tech(user):
        raise HTTPException(403, "Technicians cannot access payment methods")
    # Load the mirror row up-front so we can (a) validate the keyword
    # against the stored last4 without trusting the client, and
    # (b) enforce customer-scope on the customer role.
    row = await db.payment_methods.find_one(
        {
            "provider_payment_method_id": payment_method_id,
            "tenant_id": tenant["id"],
            "provider": "stripe",
        },
        {"_id": 0, "customer_id": 1, "last4": 1, "type": 1, "brand": 1},
    )
    if not row:
        raise HTTPException(404, "payment method not found")
    owner = row.get("customer_id")
    if _is_customer(user) and user.get("customer_id") != owner:
        raise HTTPException(403, "Not allowed")
    if not (_is_admin(user) or _is_customer(user)):
        raise HTTPException(403, "Not allowed")

    typed = (body.typed_last4 or "").strip()
    stored_last4 = (row.get("last4") or "").strip()
    # Case-sensitive exact match against the stored last4. Empty
    # stored_last4 (which would happen for a partially-populated
    # legacy row) short-circuits to a 400 rather than allow-through.
    if not stored_last4 or typed != stored_last4:
        raise HTTPException(
            status_code=400,
            detail="typed_last4_mismatch",
        )
    try:
        result = await stripe_svc.detach_payment_method(
            tenant_id=tenant["id"],
            payment_method_id=payment_method_id,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[stripe] detach-typed error: %s", exc)
        raise HTTPException(502, f"stripe error: {exc}")
    return {**result,
                "last4": stored_last4,
                "type": row.get("type") or "card",
                "brand": row.get("brand") or ""}


@router.post("/payment-methods/{payment_method_id}/set-default")
async def set_default_payment_method_endpoint(
    payment_method_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Phase J1 · Feb-2026 — flip an on-file PM to the customer's
    default.  Same auth surface as delete-typed: customer role can
    only touch their own PMs, admin/manager/super_admin can touch
    any PM inside the tenant, techs are 403'd outright."""
    if _is_tech(user):
        raise HTTPException(403, "Technicians cannot access payment methods")
    row = await db.payment_methods.find_one(
        {
            "provider_payment_method_id": payment_method_id,
            "tenant_id": tenant["id"],
            "provider": "stripe",
        },
        {"_id": 0, "customer_id": 1},
    )
    if not row:
        raise HTTPException(404, "payment method not found")
    owner = row.get("customer_id")
    if _is_customer(user) and user.get("customer_id") != owner:
        raise HTTPException(403, "Not allowed")
    if not (_is_admin(user) or _is_customer(user)):
        raise HTTPException(403, "Not allowed")
    try:
        result = await stripe_svc.set_default_payment_method(
            tenant_id=tenant["id"],
            payment_method_id=payment_method_id,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[stripe] set-default error: %s", exc)
        raise HTTPException(502, f"stripe error: {exc}")
    return result


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

    # Feb-2026 · Payment Processor Primary/Backup — canary call-site.
    # This endpoint is wired through :func:`with_failover` so that
    # a tenant that has configured ``backup_provider`` gets a
    # runtime retry on transient Stripe errors (5xx / network). The
    # non-retryable errors below (ChargeAlreadySucceededError,
    # InvoiceAlreadyPaidError, ValueError, generic Exception) STAY
    # in this handler and NEVER trigger a backup retry — declines
    # and 4xx bodies must surface to the operator, not double-charge.
    from services.payments_byo.failover_router import (
        PaymentProviderUnavailableError,
        ProviderTransientError,
        is_transient_httpx_error,
        with_failover,
    )
    from services.payments_byo.stripe_provider import StripeByoProvider

    async def _do_charge(provider):
        # When the failover router selected Stripe (the primary in
        # ~100% of tenants), preserve byte-identical semantics by
        # calling the same ``charge_card_on_file`` this handler
        # always has. This keeps existing tests + observability
        # (stripe_charges collection, 409-on-already-paid) intact.
        if isinstance(provider, StripeByoProvider):
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
            except Exception as exc:  # noqa: BLE001
                # Classify: only httpx transients / 5xx are eligible
                # for backup retry. Everything else re-raises so
                # the outer except-chain converts to 4xx/402/502.
                if is_transient_httpx_error(exc):
                    raise ProviderTransientError(str(exc)) from exc
                raise
        # Backup provider path — normalized BYO ``create_charge``.
        # Stripe-only fields (customer_id / payment_method_id) are
        # forwarded so that a Stripe-shaped body still validates
        # against a backup that doesn't need them.
        return await provider.create_charge(
            tenant_id=tenant["id"],
            amount_cents=body.amount_cents,
            currency=body.currency,
            customer_id=body.customer_id,
            payment_method_id=body.payment_method_id,
            description=body.description,
            metadata=body.metadata or None,
        )

    try:
        return await with_failover(
            tenant_id=tenant["id"],
            operation="create_charge",
            call=_do_charge,
            db=db,
            retryable_errors=(ProviderTransientError,),
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
    except PaymentProviderUnavailableError as exc:
        raise HTTPException(503, {
            "detail": "payment_provider_unavailable",
            "message": str(exc),
        })
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
async def post_webhook(request: Request, background_tasks: BackgroundTasks):
    """Stripe webhook ingress — P0c Stage 2 · Feb-2026.

    Flow (bounded by Stripe's 10s acknowledgment timeout):

      1. Read raw body + ``stripe-signature`` header.
      2. SIG VERIFY (synchronous, fast). Bad sig → 400 immediately
         so Stripe surfaces the misconfigured endpoint in its
         Dashboard delivery log. Thin-payload fallback transient
         failure → 502 so Stripe retries (we never got a valid
         event to persist).
      3. DEDUP LEDGER insert (synchronous, local-Mongo fast).
         Duplicate ``event.id`` short-circuits with 200 so Stripe
         stops retrying the same event.
      4. BACKGROUND DISPATCH — business logic (``handle_webhook_
         event``) + ledger status writes (mark_handled / mark_failed
         / record_dead_letter) run AFTER the 200 has been sent.
         Stripe never waits on step 4.

    Rationale: Stripe advertises a 10s acknowledgment budget, and
    the business handler can touch external APIs (``stripe.Event.
    retrieve`` on Thin payloads, tenant-billing downstream calls)
    that approach that budget on cold paths. Returning 200 before
    step 4 trades Stripe-level retry (via 5xx) for OUR dead-letter
    + replay surface (``POST /api/admin/stripe/dead-letter/{id}/
    retry``). The dead-letter path has always been the primary
    operator recovery mechanism; this commit just makes it the
    ONLY retry mechanism for post-200 failures.
    """
    payload = await request.body()
    sig = request.headers.get("stripe-signature") or ""
    try:
        event = stripe_svc.verify_and_parse_webhook(payload=payload, sig_header=sig)
    except stripe_svc.ThinPayloadRetrieveError as exc:
        # Transient fetch failure during Thin-payload hydration.
        # 502 → Stripe retries with backoff. No ledger row written
        # (we don't have a validated event yet).
        raise HTTPException(502, f"stripe.event.retrieve failed: {exc}")
    except ValueError as exc:
        # TD-stripe-webhook-400-every-event · Feb-2026 — surface the
        # exception context into pod logs (handler used to silently
        # 400 with the message buried in HTTPException detail only,
        # leaving the operator with no diagnostics on prod).  Routed
        # through ``config.logger`` (pool_crm) — the module-level
        # ``stripe_router`` logger is intercepted by uvicorn's log
        # config before our basicConfig handler lands, so operator
        # tails of ``backend.err.log`` never see those lines.
        from config import logger as _wh_logger  # noqa: PLC0415
        _, _wh_source = stripe_svc._select_webhook_secret_with_source()
        _wh_logger.error(
            "[stripe-webhook] construct_event FAILED exc=ValueError: %s "
            "body_len=%s sig_header_present=%s sig_header_prefix=%s "
            "secret_source=%s",
            exc, len(payload), bool(sig),
            (sig[:20] + "…") if sig else "<missing>",
            _wh_source or "<none>",
        )
        raise HTTPException(400, str(exc))
    except Exception as exc:  # includes stripe.error.SignatureVerificationError
        from config import logger as _wh_logger  # noqa: PLC0415
        _, _wh_source = stripe_svc._select_webhook_secret_with_source()
        _wh_logger.error(
            "[stripe-webhook] construct_event FAILED exc=%s: %s "
            "body_len=%s sig_header_present=%s sig_header_prefix=%s "
            "secret_source=%s",
            type(exc).__name__, exc, len(payload), bool(sig),
            (sig[:20] + "…") if sig else "<missing>",
            _wh_source or "<none>",
        )
        raise HTTPException(400, f"invalid signature: {exc}")

    # Dedup ledger — kept synchronous so a Stripe retry of the same
    # event.id doesn't produce a second background dispatch. First
    # insert wins; duplicates short-circuit before scheduling work.
    from services.payments.stripe_webhook_ledger import insert_or_skip
    ledger = await insert_or_skip(event)
    if ledger.get("status") == "skipped_duplicate":
        return {"ok": True, "handled": False, "status": "skipped_duplicate",
                "event_id": ledger.get("event_id")}

    # Hand off to the background processor. The 200 goes out next.
    background_tasks.add_task(
        _process_webhook_event_background,
        event=event,
        event_id=ledger.get("event_id") or "",
    )
    return {"ok": True, "status": "accepted",
            "event_id": ledger.get("event_id") or "",
            "handled": "pending"}


async def _process_webhook_event_background(
    *, event: Dict[str, Any], event_id: str,
) -> None:
    """P0c Stage 2 · Feb-2026 — Background processor for Stripe
    webhook events.

    Runs AFTER the handler has returned 200 to Stripe. Preserves the
    full prior failure semantics minus the Stripe-side retry: any
    exception lands in ``stripe_webhook_dead_letter`` (where an
    operator can inspect + replay via the admin endpoints) and
    flips the dedup-ledger row to ``status=failed``. The 200 we
    already sent means Stripe will NOT retry this event.
    """
    from services.payments.stripe_webhook_ledger import (
        mark_handled, mark_failed, record_dead_letter,
    )
    try:
        result = await stripe_svc.handle_webhook_event(event)
        await mark_handled(event_id, result=result)
    except stripe_svc.ThinPayloadRetrieveError as exc:
        # Post-200 Thin-payload fallback failure. Stripe won't retry
        # anymore — operator replays via dead-letter.
        import traceback
        await record_dead_letter(
            event,
            error_class="ThinPayloadRetrieveError",
            error_message=str(exc),
            stack_trace=traceback.format_exc(),
            raw_payload=event,
        )
        await mark_failed(event_id, error=str(exc))
        logger.error(
            "[stripe.webhook.bg] ThinPayloadRetrieveError event_id=%s: %s",
            event_id, exc,
        )
    except Exception as exc:  # noqa: BLE001
        import traceback
        await record_dead_letter(
            event,
            error_class=type(exc).__name__,
            error_message=str(exc),
            stack_trace=traceback.format_exc(),
            raw_payload=event,
        )
        await mark_failed(event_id, error=str(exc))
        logger.error(
            "[stripe.webhook.bg] handler crash event_id=%s class=%s: %s",
            event_id, type(exc).__name__, exc,
        )


# Feb 2026 · P1 Hotfix #3 — Legacy-URL alias. Stripe Dashboard was
# configured with the short path ``/api/stripe/webhook`` before the
# main router got its ``/payments/stripe`` prefix. Keep that URL live
# by forwarding to the same handler. Both routes accept the exact
# same payload + signature and produce identical responses.
@webhook_alias_router.post("/webhook")
async def post_webhook_alias(request: Request, background_tasks: BackgroundTasks):
    return await post_webhook(request, background_tasks)


# ═══════════════════════════════════════════════════════════════════
# SP3 · Feb-2026 — Test-hook endpoint for tenant-billing webhook smoke.
#
# Gated behind ``ALLOW_TEST_HOOKS=1`` — same env-var gate SP1's
# rate-limit bypass uses. Constructs a synthetic Stripe event
# envelope, signs it with the ``STRIPE_WEBHOOK_SECRET`` currently
# configured for THIS pod, and posts it to the real ``post_webhook``
# handler so the full signature-verify → dedup-ledger → dispatch
# path is exercised end-to-end.
#
# NEVER enable in production — a startup log line warns loudly when
# ALLOW_TEST_HOOKS=1 is set and the pod appears prod-detected
# (based on ``REACT_APP_PUBLIC_ENV`` / ``ENV`` env vars).
# ═══════════════════════════════════════════════════════════════════
import os as _os
import json as _json
import time as _time
import hmac as _hmac
import hashlib as _hashlib


class TestHookEventBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: str
    tenant_id: str
    subscription_id: Optional[str] = None
    amount_cents: Optional[int] = None


@router.post("/test-hook/tenant-billing-event")
async def post_test_hook_tenant_billing_event(body: TestHookEventBody):
    """SP3 · Feb-2026 — E2E smoke helper. Signs + posts a synthetic
    tenant-billing Stripe event through the real webhook route so
    the signature-verify + dispatch pipeline is genuinely exercised.
    Gated behind ``ALLOW_TEST_HOOKS=1``.
    """
    if _os.environ.get("ALLOW_TEST_HOOKS") != "1":
        raise HTTPException(404, "not found")
    # Match the secret the real verify_and_parse_webhook path uses
    # (mode-aware — TEST vs LIVE). Ensures the signature we compute
    # here validates in the real handler.
    from services.payments.stripe_charge import _select_webhook_secret
    secret = _select_webhook_secret()
    if not secret:
        raise HTTPException(400, {
            "code": "webhook_secret_missing",
            "hint": "Set STRIPE_WEBHOOK_SECRET_TEST (or _LIVE) before running the smoke hook.",
        })
    # Build a minimally-valid Stripe event envelope + sign it with
    # the shared webhook secret using the same scheme Stripe uses.
    ts = int(_time.time())
    obj_metadata = {
        "crm_billing_kind": "tenant_platform_fee",
        "crm_tenant_id":     body.tenant_id,
    }
    obj: Dict[str, Any] = {
        "id":       f"in_test_hook_{ts}",
        "metadata": obj_metadata,
    }
    if body.subscription_id:
        obj["subscription"] = body.subscription_id
    if body.amount_cents is not None:
        obj["amount_paid"] = int(body.amount_cents)
    envelope = {
        "id":       f"evt_test_hook_{ts}",
        "type":     body.event_type,
        "created":  ts,
        "data":     {"object": obj},
        "livemode": False,
    }
    payload = _json.dumps(envelope).encode("utf-8")
    signed_payload = f"{ts}.{payload.decode('utf-8')}".encode("utf-8")
    v1 = _hmac.new(secret.encode("utf-8"), signed_payload,
                     _hashlib.sha256).hexdigest()
    sig_header = f"t={ts},v1={v1}"

    # Drive the REAL post_webhook handler using an ASGI-safe Request
    # scope. We can't call ``post_webhook(request)`` directly with
    # our fresh envelope — it reads ``await request.body()``, so
    # we synthesize a minimal Request from the payload + headers.
    from starlette.requests import Request as _StarletteRequest

    async def _receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    scope = {
        "type": "http", "method": "POST",
        "path": "/api/payments/stripe/webhook",
        "headers": [
            (b"stripe-signature", sig_header.encode("utf-8")),
            (b"content-type", b"application/json"),
        ],
        "query_string": b"",
    }
    req = _StarletteRequest(scope, receive=_receive)
    # P0c Stage 2 · Feb-2026 — ``post_webhook`` now takes
    # ``BackgroundTasks`` as a dependency. The test-hook endpoint
    # drives it directly (not via FastAPI's DI graph), so we mint a
    # fresh ``BackgroundTasks()`` and run its tasks manually after
    # ``post_webhook`` returns so the smoke-test synchronously sees
    # the ledger write + any dead-letter row.
    bg = BackgroundTasks()
    resp = await post_webhook(req, bg)
    # Drain background tasks inline so the test-hook caller gets a
    # synchronous view of the final ledger / dead-letter state.
    for task in bg.tasks:
        func = task.func
        args = task.args
        kwargs = task.kwargs
        import inspect as _inspect
        if _inspect.iscoroutinefunction(func):
            await func(*args, **kwargs)
        else:
            func(*args, **kwargs)
    return resp
