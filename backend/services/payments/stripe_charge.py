"""Phase 14a · Feb-2026 — Stripe card-on-file service.

Fresh re-integration of Stripe as the primary card-capture / charge-card-on-
file provider. Runs alongside the parked Lumino/Zapier bridge; this module
is scoped strictly to the SetupIntent → attach → off_session PaymentIntent
pipeline used by the customer portal and admin-on-behalf capture.

Design notes
------------
* Uses the *raw* ``stripe`` Python SDK (14.x). No emergentintegrations —
  the Checkout-based emergent helpers do not cover our SetupIntent flow.
* Mode split: ``STRIPE_MODE`` env var selects ``test`` vs ``live``.
  Corresponding keys: ``STRIPE_SECRET_KEY_TEST`` / ``STRIPE_SECRET_KEY_LIVE``
  and ``STRIPE_WEBHOOK_SECRET_TEST`` / ``STRIPE_WEBHOOK_SECRET_LIVE``.
  When mode-specific keys are missing, we fall back to the pre-injected
  ``STRIPE_API_KEY`` (no fallback — see ``_UnconfiguredStripeError``) so
  has a working sandbox key.
* NO db.stripe_payments_live — that legacy LZ4 collection stays retired.
  Every charge attempt is logged into the *fresh* ``db.stripe_charges``
  collection with the shape documented in ``_persist_charge``.
* Payment methods are mirrored into the existing ``db.payment_methods``
  collection with ``provider="stripe"`` so Lumino rows (if any) stay
  isolated by provider.
* All non-webhook helpers are ``async`` — Stripe SDK calls happen inside
  ``asyncio.to_thread`` so the FastAPI event loop is never blocked.
* The module-level ``_stripe`` object is injectable: tests substitute a
  stub via ``set_stripe_client`` without monkeypatching ``sys.modules``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import stripe as _stripe_module

from config import db

logger = logging.getLogger("stripe_charge")

# ── SDK client (injectable for tests) ─────────────────────────────────
_stripe: Any = _stripe_module


def set_stripe_client(stub: Any) -> None:
    """Testing hook — replace the module-level Stripe SDK with a stub.

    Passing ``None`` restores the real ``stripe`` SDK.
    """
    global _stripe
    _stripe = stub if stub is not None else _stripe_module


def _mode() -> str:
    val = (os.environ.get("STRIPE_MODE") or "test").strip().lower()
    return "live" if val == "live" else "test"


# Phase 20 · Feb-2026 · Sub-item C — helper: publishable key for the
# current mode. Returns ``""`` when the env is missing; logs a WARNING
# on the first miss so ops can see the mis-config without crashing
# the payment flow (frontend falls back gracefully).
_PUB_KEY_WARNED = False


def _publishable_key() -> str:
    global _PUB_KEY_WARNED  # noqa: PLW0603
    env_var = (
        "STRIPE_PUBLISHABLE_KEY_LIVE"
        if _mode() == "live"
        else "STRIPE_PUBLISHABLE_KEY_TEST"
    )
    key = (os.environ.get(env_var) or "").strip()
    if not key and not _PUB_KEY_WARNED:
        logger.warning(
            "[stripe] %s is not set — /config + /setup-intent will "
            "return an empty publishable_key. Set the env to unblock "
            "Elements init.", env_var,
        )
        _PUB_KEY_WARNED = True
    return key


def _select_secret_key() -> Optional[str]:
    """Return the Stripe secret key to use for API calls in the current
    mode. Returns ``None`` when nothing resolves — callers must
    fail-fast via ``_UnconfiguredStripeError``.

    Phase 42.2 (Feb 2026) · removed the hardcoded placeholder fallback.
    Silent placeholder keys deferred real failures to request time
    instead of surfacing at startup — a mis-config should be loud
    and immediate, not a mystery Stripe 401 in prod.
    """
    mode = _mode()
    env_key = "STRIPE_SECRET_KEY_LIVE" if mode == "live" else "STRIPE_SECRET_KEY_TEST"
    resolved = (
        (os.environ.get(env_key) or "").strip()
        or (os.environ.get("STRIPE_API_KEY") or "").strip()
    )
    return resolved or None


class _UnconfiguredStripeError(RuntimeError):
    """Raised on the first Stripe API call when no valid secret key
    resolved from the environment. Phase 42.2 · Feb 2026."""


def _select_webhook_secret() -> str:
    mode = _mode()
    env_key = "STRIPE_WEBHOOK_SECRET_LIVE" if mode == "live" else "STRIPE_WEBHOOK_SECRET_TEST"
    return (os.environ.get(env_key) or "").strip() or (
        os.environ.get("STRIPE_WEBHOOK_SECRET") or ""
    ).strip()


# Phase 42.3 · Feb 2026 — pin api_version centrally. Matches the SDK-
# shipped default at stripe-python@15.0.0 → insulates the response
# shape from whoever last touched the Stripe dashboard.
STRIPE_API_VERSION = "2026-03-25.dahlia"

_STARTUP_LOGGED = False


def _init_api_key() -> None:
    """Assign the SDK-level ``stripe.api_key`` + ``stripe.api_version``.
    Called lazily on each helper so mid-test env swaps
    (``monkeypatch.setenv``) take effect.

    Fail-fast: raises ``_UnconfiguredStripeError`` if no real key
    resolves. Logs a one-time startup line with api_version + key-tail
    so a future rotation is auditable from process logs.
    """
    global _STARTUP_LOGGED  # noqa: PLW0603
    if _stripe is not _stripe_module:
        # Injected stub — tests provide their own methods, no key needed.
        return
    key = _select_secret_key()
    if not key:
        raise _UnconfiguredStripeError(
            "No Stripe secret key configured. Set STRIPE_SECRET_KEY_"
            f"{'LIVE' if _mode() == 'live' else 'TEST'} or STRIPE_API_KEY "
            "in the process env before calling Stripe helpers."
        )
    _stripe.api_key = key
    _stripe.api_version = STRIPE_API_VERSION
    if not _STARTUP_LOGGED:
        logger.info(
            "[stripe] configured for api_version %s with secret key ending in ...%s",
            STRIPE_API_VERSION,
            key[-4:],
        )
        _STARTUP_LOGGED = True


def _asdict(resp: Any) -> Dict[str, Any]:
    """Phase 42.3 · Feb 2026 — return a plain dict view of a Stripe
    response, tolerating both stripe-python v13/v14 (``StripeObject``
    inherits ``dict``) AND v15+ (``StripeObject`` no longer inherits
    from ``dict`` — ``.get()`` / ``.items()`` raise ``AttributeError``).
    """
    if resp is None:
        return {}
    if isinstance(resp, dict):
        return resp
    for method in ("to_dict_recursive", "to_dict"):
        fn = getattr(resp, method, None)
        if callable(fn):
            try:
                out = fn()
                if isinstance(out, dict):
                    return out
            except Exception:  # noqa: BLE001
                pass
    # Fall back to attribute scrape for a defensive minimum.
    return {k: getattr(resp, k) for k in dir(resp) if not k.startswith("_")}


async def _to_thread(fn, /, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


async def _create_intent(
    *,
    amount_cents: int,
    currency: str,
    customer: Optional[str],
    payment_method: str,
    off_session: bool,
    confirm: bool,
    description: Optional[str],
    metadata: Dict[str, Any],
    idempotency_key: str,
) -> Any:
    """Thin wrapper around ``stripe.PaymentIntent.create`` — kept as a
    module-level coroutine so pytest can monkeypatch it and drive
    ``charge_card_on_file`` without hitting Stripe. Returns whatever
    the SDK returns (StripeObject or, in tests, a plain dict); the
    caller normalises via :func:`_asdict`.
    """
    return await _to_thread(
        _stripe.PaymentIntent.create,
        amount=amount_cents,
        currency=currency,
        customer=customer,
        payment_method=payment_method,
        off_session=off_session,
        confirm=confirm,
        description=description or None,
        metadata=metadata,
        idempotency_key=idempotency_key,
    )


# ── Public helpers ────────────────────────────────────────────────────
async def create_setup_intent(
    *,
    tenant_id: str,
    customer_id: str,
    actor_user_id: Optional[str] = None,
    payment_method_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a Stripe Customer (if needed) + a SetupIntent for saving a card.

    Returns the SetupIntent client_secret + the Stripe customer id so the
    frontend can render ``<Elements clientSecret={...}>`` and confirm the
    card with ``stripe.confirmSetup``.

    Feb 2026 · P0 fix — accept ``payment_method_types`` so the ACH
    endpoint (``customer_portal.start_ach_link_session``) can request
    a ``us_bank_account`` SetupIntent instead of the default card-only
    one. Previously the ACH endpoint passed this kwarg and blew up
    with a ``TypeError`` on every click, silently returning
    ``{ok:false, reason:"stripe_error"}`` to the frontend.
    """
    _init_api_key()

    customer = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not customer:
        raise ValueError("customer not found")

    provider_customer_id = customer.get("stripe_customer_id") or ""

    async def _create_fresh_stripe_customer() -> str:
        # Cross-mode auto-recovery: when a live-mode customer id is
        # left over on the record after flipping ``STRIPE_MODE``, we
        # can't reuse it (Stripe returns 404 on the SetupIntent).
        # This helper is called both when the CRM has no id AND after
        # ``resource_missing`` on the SetupIntent create below.
        # Idempotency key includes the current Stripe mode so a
        # retry after a mode flip creates a fresh customer instead
        # of deduping back to the stale one.
        stripe_cust = await _to_thread(
            _stripe.Customer.create,
            email=(customer.get("email") or None),
            name=(customer.get("name") or None),
            metadata={
                "crm_customer_id": customer_id,
                "crm_tenant_id": tenant_id,
                "stripe_mode": _mode(),
            },
            idempotency_key=f"cust_create:{_mode()}:{tenant_id}:{customer_id}",
        )
        new_id = _asdict(stripe_cust).get("id") or stripe_cust["id"]
        await db.customers.update_one(
            {"id": customer_id, "tenant_id": tenant_id},
            {"$set": {"stripe_customer_id": new_id}},
        )
        return new_id

    if not provider_customer_id:
        provider_customer_id = await _create_fresh_stripe_customer()

    # Feb 2026 · P0 fix — the ACH flow needs a ``us_bank_account``
    # SetupIntent, the card flow needs ``card`` (default). Callers
    # pass a list; we normalise here so a bad value fails fast.
    types = payment_method_types or ["card"]
    if not isinstance(types, (list, tuple)) or not types:
        types = ["card"]
    # Bake the requested types + Stripe mode into the idempotency
    # key so a repeat click within the same day for a different
    # flavour (or after a mode flip) doesn't dedupe back to the
    # wrong SetupIntent.
    def _build_si_kwargs(cust_id: str) -> Dict[str, Any]:
        return dict(
            customer=cust_id,
            payment_method_types=list(types),
            usage="off_session",
            metadata={
                "crm_customer_id": customer_id,
                "crm_tenant_id": tenant_id,
                "actor_user_id": actor_user_id or "",
            },
            idempotency_key=(
                f"si:{_mode()}:{tenant_id}:{customer_id}:"
                f"{'-'.join(sorted(types))}:"
                f"{datetime.now(timezone.utc).strftime('%Y%m%d')}"
            ),
        )

    try:
        setup_intent = await _to_thread(
            _stripe.SetupIntent.create, **_build_si_kwargs(provider_customer_id),
        )
    except Exception as exc:  # pragma: no cover — happy path first
        # Cross-mode auto-recovery — if we're pointing at a customer
        # id from the wrong Stripe mode (e.g. live-mode id after
        # flipping STRIPE_MODE=test), Stripe returns 404
        # ``resource_missing``. Clear the stale id, mint a new one
        # in the current mode, and retry the SetupIntent create.
        code = getattr(getattr(exc, "error", None), "code", None) or ""
        msg = str(exc)
        looks_stale = (
            code == "resource_missing"
            or "No such customer" in msg
            or ("resource_missing" in msg and "customer" in msg)
        )
        if not looks_stale:
            raise
        logger.info(
            "[stripe] stale stripe_customer_id=%s for CRM customer %s "
            "(mode=%s) — auto-recovering with fresh Stripe customer",
            provider_customer_id, customer_id, _mode(),
        )
        provider_customer_id = await _create_fresh_stripe_customer()
        setup_intent = await _to_thread(
            _stripe.SetupIntent.create, **_build_si_kwargs(provider_customer_id),
        )

    si = _asdict(setup_intent)
    return {
        "client_secret": si.get("client_secret"),
        "setup_intent_id": si.get("id"),
        "stripe_customer_id": provider_customer_id,
        "mode": _mode(),
        # Phase 20 · Feb-2026 · Sub-item C — return the publishable key
        # alongside the setup-intent so the frontend can init Elements
        # without reading it from ``REACT_APP_STRIPE_PUBLISHABLE_KEY``
        # env (which is now scheduled for removal). Returns ``None`` if
        # the env var isn't configured — frontend must fall back to
        # ``GET /api/payments/stripe/config``.
        "publishable_key": _publishable_key(),
    }


async def attach_payment_method(
    *,
    tenant_id: str,
    customer_id: str,
    payment_method_id: str,
    set_default: bool = True,
) -> Dict[str, Any]:
    """Attach a Stripe payment method to the customer + mirror card
    metadata into ``db.payment_methods``. Idempotent on the mirrored row.
    """
    _init_api_key()

    customer = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not customer:
        raise ValueError("customer not found")
    provider_customer_id = customer.get("stripe_customer_id")
    if not provider_customer_id:
        raise ValueError("customer has no stripe_customer_id — run setup_intent first")

    # Attach + retrieve the fresh PM so we get the latest card metadata.
    try:
        await _to_thread(
            _stripe.PaymentMethod.attach,
            payment_method_id,
            customer=provider_customer_id,
        )
    except Exception as exc:
        # ``attach`` is idempotent but still surfaces already-attached
        # states as InvalidRequestError. Swallow the specific case, re-raise
        # anything else.
        msg = str(exc).lower()
        if "already been attached" not in msg:
            raise

    pm = await _to_thread(_stripe.PaymentMethod.retrieve, payment_method_id)
    # Phase 42.3 · Feb 2026 — v15-safe response scrape.
    pm_dict = _asdict(pm)
    card = pm_dict.get("card") or {}
    if not isinstance(card, dict):
        card = _asdict(card)
    # B1 · Feb-2026 — Admin ACH parity. Extract ``us_bank_account``
    # fields when the PM is an ACH bank account so the mirror row
    # carries ``type`` / ``bank_name`` / ``verification_status`` /
    # ``account_holder_type`` alongside the card fields.  For card
    # PMs these stay empty/None so the row shape is stable.
    us_bank = pm_dict.get("us_bank_account") or {}
    if not isinstance(us_bank, dict):
        us_bank = _asdict(us_bank)
    verifications = us_bank.get("verifications") or {}
    if not isinstance(verifications, dict):
        verifications = _asdict(verifications)
    pm_type = (pm_dict.get("type") or "").strip() or (
        "us_bank_account" if us_bank else "card"
    )
    ach_verification_status = None
    if pm_type == "us_bank_account":
        # Stripe returns ``verifications.status`` = "verified" |
        # "pending" | "failed" when micro-deposits are in flight;
        # for Financial Connections flows the PM lands already
        # ``verified`` at attach time.  Absent field → "unverified"
        # so the admin UI can prompt for the next step.
        ach_verification_status = (
            verifications.get("status") or "unverified"
        )

    now = datetime.now(timezone.utc).isoformat()
    mirror = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "provider": "stripe",
        "provider_customer_id": provider_customer_id,
        "provider_payment_method_id": payment_method_id,
        # B1 · discriminator so the CRM UI can render card vs ACH
        # rows without a second call to Stripe.
        "type": pm_type,
        "brand": card.get("brand") or "",
        # last4 falls back to the ACH last4 when the PM is a bank
        # account (Stripe puts it under ``us_bank_account.last4``).
        "last4": card.get("last4") or us_bank.get("last4") or "",
        "exp_month": card.get("exp_month"),
        "exp_year": card.get("exp_year"),
        # ACH-specific fields — safe empties when the PM is a card.
        "bank_name": us_bank.get("bank_name") or "",
        "account_holder_type": us_bank.get("account_holder_type") or "",
        "verification_status": ach_verification_status,
        "is_default": bool(set_default),
        "stripe_mode": _mode(),
        "created_at": now,
        "updated_at": now,
    }
    # Idempotent upsert on the provider PM id (Stripe id is globally unique).
    await db.payment_methods.update_one(
        {"provider_payment_method_id": payment_method_id, "tenant_id": tenant_id},
        {"$set": mirror},
        upsert=True,
    )
    if set_default:
        # Any siblings for the same customer become non-default.
        await db.payment_methods.update_many(
            {
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "provider_payment_method_id": {"$ne": payment_method_id},
            },
            {"$set": {"is_default": False}},
        )
        await db.customers.update_one(
            {"id": customer_id, "tenant_id": tenant_id},
            {
                "$set": {
                    "stripe_default_payment_method_id": payment_method_id,
                    "saved_payment_methods_count": await db.payment_methods.count_documents(
                        {"customer_id": customer_id, "tenant_id": tenant_id}
                    ),
                }
            },
        )
    else:
        await db.customers.update_one(
            {"id": customer_id, "tenant_id": tenant_id},
            {
                "$set": {
                    "saved_payment_methods_count": await db.payment_methods.count_documents(
                        {"customer_id": customer_id, "tenant_id": tenant_id}
                    )
                }
            },
        )
    return mirror


async def list_payment_methods(
    *, tenant_id: str, customer_id: str
) -> List[Dict[str, Any]]:
    """Return the local mirror rows for this customer. Never hits Stripe —
    the DB is the source of truth for the CRM UI. Detach + attach flows
    keep the mirror in sync."""
    cursor = db.payment_methods.find(
        {"tenant_id": tenant_id, "customer_id": customer_id, "provider": "stripe"},
        {"_id": 0},
    ).sort("created_at", -1)
    return [row async for row in cursor]


async def detach_payment_method(
    *, tenant_id: str, payment_method_id: str
) -> Dict[str, Any]:
    """Detach a PM from its Stripe customer + remove the local mirror row."""
    _init_api_key()

    row = await db.payment_methods.find_one(
        {"provider_payment_method_id": payment_method_id, "tenant_id": tenant_id},
        {"_id": 0},
    )
    if not row:
        raise ValueError("payment method not found")

    try:
        await _to_thread(_stripe.PaymentMethod.detach, payment_method_id)
    except Exception as exc:
        # Already-detached PMs raise InvalidRequestError — treat as no-op.
        msg = str(exc).lower()
        if "was previously detached" not in msg and "no such payment_method" not in msg:
            raise

    await db.payment_methods.delete_one(
        {"provider_payment_method_id": payment_method_id, "tenant_id": tenant_id}
    )
    # Refresh the count + clear the customer's default pointer if it matched.
    customer_id = row.get("customer_id")
    if customer_id:
        count = await db.payment_methods.count_documents(
            {"customer_id": customer_id, "tenant_id": tenant_id}
        )
        set_ops = {"saved_payment_methods_count": count}
        customer = await db.customers.find_one(
            {"id": customer_id, "tenant_id": tenant_id},
            {"_id": 0, "stripe_default_payment_method_id": 1},
        ) or {}
        if customer.get("stripe_default_payment_method_id") == payment_method_id:
            set_ops["stripe_default_payment_method_id"] = None
        await db.customers.update_one(
            {"id": customer_id, "tenant_id": tenant_id}, {"$set": set_ops}
        )
    return {
        "ok": True,
        "provider_payment_method_id": payment_method_id,
        "customer_id": customer_id,
    }


# Feb-2026 · Stripe reconciliation exception hierarchy — the router
# maps these to HTTP 409 with the existing PI in the response body.
class InvoiceAlreadyPaidError(ValueError):
    """Raised when the target invoice is already flagged paid."""


class ChargeAlreadySucceededError(ValueError):
    """Raised when a prior succeeded PaymentIntent exists for the
    same (tenant, invoice, amount, payment_method) tuple. Carries
    the existing ``payment_intent_id`` so the router can echo it in
    the 409 body.
    """
    def __init__(self, msg: str, payment_intent_id: str | None = None):
        super().__init__(msg)
        self.payment_intent_id = payment_intent_id



async def charge_card_on_file(
    *,
    tenant_id: str,
    customer_id: str,
    payment_method_id: str,
    amount_cents: int,
    currency: str = "usd",
    invoice_id: Optional[str] = None,
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    actor_user_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an off_session PaymentIntent using a saved card + log the
    attempt into ``db.stripe_charges``. Raises ``ValueError`` on missing
    prerequisites so the router can convert to HTTPException.
    """
    _init_api_key()

    if not isinstance(amount_cents, int) or amount_cents <= 0:
        raise ValueError("amount_cents must be a positive integer")

    row = await db.payment_methods.find_one(
        {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "provider_payment_method_id": payment_method_id,
            "provider": "stripe",
        },
        {"_id": 0},
    )
    if not row:
        raise ValueError("payment method not attached to this customer")
    provider_customer_id = row.get("provider_customer_id")

    # Feb-2026 · Stripe reconciliation FIX 1 — pre-check guards to
    # prevent double-charges. Deterministic idempotency key across
    # retries. Multi-tenant scoped on every read.
    #
    # Order matters:
    #   (a) Prior succeeded charge for the same
    #       (tenant, invoice, amount, pm) → raise
    #       ChargeAlreadySucceededError carrying the existing PI so
    #       the caller/UI can echo it (more actionable than a bare
    #       "invoice paid" 409). This must run BEFORE the invoice-
    #       paid guard because the belt-and-suspenders sync flip in
    #       the success path (below) marks the invoice paid; on a
    #       retry both conditions match and we prefer the specific
    #       one.
    #   (b) Invoice already paid → InvoiceAlreadyPaidError. Covers
    #       the case where the invoice was marked paid by some other
    #       provider (Lumino bridge, manual, etc.) with no local
    #       stripe_charges row.
    if invoice_id:
        prior = await db.stripe_charges.find_one({
            "tenant_id": tenant_id,
            "invoice_id": invoice_id,
            "amount_cents": amount_cents,
            "provider_payment_method_id": payment_method_id,
            "status": {"$in": ["succeeded", "pending"]},
        }, {"_id": 0, "id": 1, "stripe_payment_intent_id": 1, "status": 1})
        if prior and prior.get("status") == "succeeded":
            raise ChargeAlreadySucceededError(
                f"invoice {invoice_id} already charged",
                payment_intent_id=prior.get("stripe_payment_intent_id"),
            )
        inv = await db.quotes.find_one(
            {"id": invoice_id, "tenant_id": tenant_id, "doc_type": "invoice"},
            {"_id": 0, "payment_status": 1},
        )
        if inv and (inv.get("payment_status") or "").lower() == "paid":
            raise InvoiceAlreadyPaidError(f"invoice {invoice_id} already paid")

    md = {
        "crm_tenant_id": tenant_id,
        "crm_customer_id": customer_id,
        "crm_invoice_id": invoice_id or "",
        "actor_user_id": actor_user_id or "",
        **{str(k): str(v) for k, v in (metadata or {}).items()},
    }
    charge_row_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    # Deterministic Stripe idempotency key across retries — same
    # (tenant, invoice, amount, pm) always resolves to the same PI.
    deterministic_key = (
        f"charge:{tenant_id}:{invoice_id or 'noinv'}:"
        f"{amount_cents}:{payment_method_id}"
    )

    try:
        intent = await _create_intent(
            amount_cents=amount_cents,
            currency=currency,
            customer=provider_customer_id,
            payment_method=payment_method_id,
            off_session=True,
            confirm=True,
            description=description,
            metadata=md,
            idempotency_key=idempotency_key or deterministic_key,
        )
        # Phase 42.3 · Feb 2026 — v15-safe response scrape.
        pi = _asdict(intent)
        status = pi.get("status")
        payment_intent_id = pi.get("id")
        outcome = "succeeded" if status == "succeeded" else status or "unknown"
        await _persist_charge(
            charge_row_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            payment_method_id=payment_method_id,
            amount_cents=amount_cents,
            currency=currency,
            invoice_id=invoice_id,
            payment_intent_id=payment_intent_id,
            status=outcome,
            error=None,
            actor_user_id=actor_user_id,
            created_at=now,
        )
        # Feb-2026 · FIX 2 (belt-and-suspenders) — synchronously flip
        # ``quotes.payment_status`` when the charge succeeded so the
        # UI doesn't wait on the webhook (which can be delayed by
        # tens of seconds). Idempotent: same values as the webhook
        # write.
        if status == "succeeded" and invoice_id:
            await _mark_invoice_paid(
                tenant_id=tenant_id, invoice_id=invoice_id,
                amount_cents=amount_cents, paid_at=now,
                payment_intent_id=payment_intent_id,
            )
        return {
            "ok": status == "succeeded",
            "charge_row_id": charge_row_id,
            "payment_intent_id": payment_intent_id,
            "status": outcome,
            "amount_cents": amount_cents,
            "currency": currency,
        }
    except Exception as exc:
        err_msg = str(exc) or exc.__class__.__name__
        await _persist_charge(
            charge_row_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            payment_method_id=payment_method_id,
            amount_cents=amount_cents,
            currency=currency,
            invoice_id=invoice_id,
            payment_intent_id=None,
            status="failed",
            error=err_msg[:500],
            actor_user_id=actor_user_id,
            created_at=now,
        )
        logger.warning(
            "[stripe_charge] charge failed tenant=%s customer=%s pm=%s: %s",
            tenant_id, customer_id, payment_method_id, err_msg,
        )
        raise


async def _persist_charge(
    row_id: str,
    *,
    tenant_id: str,
    customer_id: str,
    payment_method_id: str,
    amount_cents: int,
    currency: str,
    invoice_id: Optional[str],
    payment_intent_id: Optional[str],
    status: str,
    error: Optional[str],
    actor_user_id: Optional[str],
    created_at: str,
) -> None:
    """Insert a single ``stripe_charges`` row. Kept in one place so the
    schema is easy to audit."""
    await db.stripe_charges.insert_one(
        {
            "id": row_id,
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "provider_payment_method_id": payment_method_id,
            "amount_cents": amount_cents,
            "currency": currency,
            "invoice_id": invoice_id,
            "stripe_payment_intent_id": payment_intent_id,
            "status": status,
            "error": error,
            "actor_user_id": actor_user_id,
            "stripe_mode": _mode(),
            "created_at": created_at,
        }
    )


# ── Phase 47 · Feb 2026 — Direct Stripe Checkout for invoice payment ──
#
# Replaces the Lumino/Zapier bridge that previously produced payment
# URLs for the customer-facing "Pay $X" button. Callers (see
# `routers/lumino_link_request.py::request_payment_link`) get back a
# ready-to-redirect Stripe-hosted Checkout URL. Webhook reconciliation
# happens via `checkout.session.completed` (handled below in
# ``handle_webhook_event``) using the metadata we stamp here.
async def create_invoice_checkout_session(
    *,
    tenant_id: str,
    invoice: Dict[str, Any],
    customer: Dict[str, Any],
    return_base_url: str = "",
    save_for_future_billing: bool = False,
) -> Dict[str, Any]:
    """Create a Stripe Checkout Session (mode=payment) for an invoice.

    ``invoice`` — the quote/invoice doc from ``db.quotes``. Must carry
        ``id``, ``total`` (dollars, float), and optionally
        ``amount_paid``. The remaining balance is what we charge.
    ``customer`` — the customer doc from ``db.customers``. Must carry
        ``id`` and ideally ``email`` for prefill.
    ``return_base_url`` — override for ``APP_PUBLIC_URL``. When empty
        the env is consulted; a hard 500 is surfaced if neither is set
        (better than silently sending customers to ``/portal/...`` off
        the wrong origin).
    ``save_for_future_billing`` — Feb 2026 addendum. When ``True``, the
        underlying PaymentIntent is created with
        ``setup_future_usage="off_session"``, which tells Stripe to
        attach the PaymentMethod to the customer AND flag it as
        reusable for autobilling. The router pre-gates this on
        "customer has zero saved PMs today" so we never silently
        promote an alternate card behind a customer who already
        deliberately picked one. On webhook success we finish the job
        (attach + set as default) — see ``handle_webhook_event`` /
        ``checkout.session.completed``.

    Returns ``{"payment_url", "checkout_session_id", "amount_cents",
    "currency", "mode"}``. All accessors go through :func:`_asdict` so
    v15's non-``dict`` ``StripeObject`` doesn't trip us.
    """
    _init_api_key()

    invoice_id = invoice.get("id")
    if not invoice_id:
        raise ValueError("invoice.id required")
    customer_id = customer.get("id")
    if not customer_id:
        raise ValueError("customer.id required")

    total_dollars = float(invoice.get("total") or 0)
    paid_dollars = float(invoice.get("amount_paid") or 0)
    balance_dollars = round(total_dollars - paid_dollars, 2)
    if balance_dollars <= 0:
        raise ValueError("invoice_already_paid")
    amount_cents = int(round(balance_dollars * 100))
    currency = (invoice.get("currency") or "usd").lower()

    base = (return_base_url or os.environ.get("APP_PUBLIC_URL", "") or "").rstrip("/")
    if not base:
        raise ValueError("APP_PUBLIC_URL not configured")

    # Human-friendly description on the hosted Checkout page.
    invoice_number = (invoice.get("invoice_number")
                      or invoice.get("number")
                      or invoice_id)
    description = f"Invoice {invoice_number}"

    line_items = [{
        "price_data": {
            "currency": currency,
            "product_data": {
                "name": description,
                "metadata": {"crm_invoice_id": invoice_id},
            },
            "unit_amount": amount_cents,
        },
        "quantity": 1,
    }]

    metadata = {
        # Keep the same key spellings the existing PaymentIntent webhook
        # handler already reads (see the `payment_intent.succeeded`
        # branch in ``handle_webhook_event``). This way the reconcile
        # code doesn't need to grow another key alias.
        "crm_invoice_id": invoice_id,
        "crm_tenant_id": tenant_id,
        "crm_customer_id": customer_id,
        # Phase 47 tag so operators / dashboards can filter Sessions
        # generated by this path from ones created via, say, a future
        # subscription-billing flow.
        "source": "phase47_invoice_pay",
        # Feb 2026 addendum — mirrors the ``setup_future_usage`` flag
        # into metadata so the webhook can decide whether to
        # promote the resulting PM to the customer's autobilling
        # default without re-reading the PI's ``setup_future_usage``
        # (which requires an extra API call). String, not bool —
        # Stripe metadata is string-typed.
        "crm_save_for_future": "1" if save_for_future_billing else "0",
    }

    # Stripe Checkout carries a ``payment_intent_data`` block that lets
    # us set ``setup_future_usage`` + metadata on the auto-created PI.
    pi_data: Dict[str, Any] = {"metadata": metadata}
    if save_for_future_billing:
        pi_data["setup_future_usage"] = "off_session"

    session_kwargs: Dict[str, Any] = {
        "mode": "payment",
        "line_items": line_items,
        "success_url": f"{base}/portal/payment-complete?session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url":  f"{base}/portal/invoices/{invoice_id}",
        "metadata": metadata,
        # Pass the invoice metadata down onto the PaymentIntent that
        # Checkout auto-creates so ``payment_intent.succeeded`` webhooks
        # (which we already handle) can reconcile even if
        # ``checkout.session.completed`` were somehow missed.
        "payment_intent_data": pi_data,
        "client_reference_id": invoice_id,
    }

    email = customer.get("email")
    if email:
        session_kwargs["customer_email"] = email

    # Feb 2026 addendum — save flavour changes the idempotency key so
    # a customer who unchecks the "save this card" box and re-clicks
    # Pay doesn't dedupe back to a stale save-enabled Session.
    save_flag = "save" if save_for_future_billing else "nosave"
    idempotency_key = (
        f"phase47:invoice:{tenant_id}:{invoice_id}:"
        f"{amount_cents}:{save_flag}"
    )

    session = await asyncio.to_thread(
        _stripe.checkout.Session.create,
        idempotency_key=idempotency_key,
        **session_kwargs,
    )
    sd = _asdict(session)
    return {
        "payment_url": sd.get("url"),
        "checkout_session_id": sd.get("id"),
        "amount_cents": amount_cents,
        "currency": currency,
        "mode": _mode(),
        "save_for_future_billing": bool(save_for_future_billing),
    }


async def _save_pm_after_first_payment(
    *,
    tenant_id: Optional[str],
    customer_id: Optional[str],
    metadata: Dict[str, Any],
    payment_intent_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Feb 2026 addendum · save-on-first-payment.

    Fires from the ``checkout.session.completed`` webhook when the
    Session was created with the ``crm_save_for_future="1"`` metadata
    flag AND the payment succeeded. Retrieves the underlying
    PaymentIntent to discover the ``payment_method`` id, then routes
    the PM through the existing ``attach_payment_method`` helper —
    reusing the same code path the /portal Add-card flow uses, so
    the resulting ``db.payment_methods`` row has the exact same
    shape (last4, brand, is_default). ``set_default=True`` so
    autobilling picks up the new PM on the next run.

    Idempotent: ``attach_payment_method`` upserts on
    ``(tenant_id, provider_payment_method_id)`` so a duplicate
    webhook delivery re-runs cleanly.

    Returns the attached row on success; returns ``None`` (with a
    warning logged) if any precondition is missing so the caller
    can move on with the rest of the reconcile.
    """
    if (metadata or {}).get("crm_save_for_future") != "1":
        return None
    if not (tenant_id and customer_id and payment_intent_id):
        return None
    try:
        _init_api_key()
    except _UnconfiguredStripeError:
        logger.warning(
            "[phase47] save-on-first-payment skipped — Stripe key "
            "not configured (invoice_id=%s)",
            (metadata or {}).get("crm_invoice_id"),
        )
        return None
    pi = await asyncio.to_thread(
        _stripe.PaymentIntent.retrieve, payment_intent_id,
    )
    pm_id = _asdict(pi).get("payment_method")
    if not pm_id:
        logger.warning(
            "[phase47] save-on-first-payment · PaymentIntent %s "
            "carries no payment_method — nothing to save",
            payment_intent_id,
        )
        return None
    return await attach_payment_method(
        tenant_id=tenant_id,
        customer_id=customer_id,
        payment_method_id=pm_id,
        set_default=True,
    )



async def _mark_invoice_paid_from_session(
    *,
    invoice_id: str,
    amount_total_cents: int,
    session_id: str,
    payment_intent_id: Optional[str],
) -> bool:
    """Flip ``quotes.payment_status`` to ``paid`` (or ``partial``) and
    stamp ``paid_at`` when a ``checkout.session.completed`` event fires
    for one of our Phase-47 sessions.

    Mirrors the ``quotes/{qid}/record-payment`` code path so any
    downstream UI that keys off ``payment_status`` sees the update
    immediately. Returns True if the invoice doc was updated.
    """
    if not invoice_id:
        return False
    inv = await db.quotes.find_one({"id": invoice_id}, {"_id": 0})
    if not inv:
        return False
    if inv.get("payment_status") == "paid":
        return False  # idempotent — already reconciled

    amount_paid_prev = float(inv.get("amount_paid") or 0)
    amount_paid_new = round(amount_paid_prev + (amount_total_cents / 100.0), 2)
    total = float(inv.get("total") or 0)
    fully_paid = amount_paid_new + 0.01 >= total

    now = datetime.now(timezone.utc).isoformat()
    update = {
        "amount_paid": amount_paid_new,
        "payment_status": "paid" if fully_paid else "partial",
        "payment_method": "stripe_checkout",
        "stripe_checkout_session_id": session_id,
    }
    if fully_paid:
        update["paid_at"] = now
        update["status"] = "accepted"
    if payment_intent_id:
        update["stripe_payment_intent_id"] = payment_intent_id

    r = await db.quotes.update_one({"id": invoice_id}, {"$set": update})
    return bool(r.modified_count)


# ── Webhook helpers ───────────────────────────────────────────────────
# Feb-2026 · FIX 2 / FIX 3 · Invoice reconciliation helpers. All
# tenant-scoped on every write, idempotent (safe to re-run on
# webhook retries + belt-and-suspenders sync path).
async def _mark_invoice_paid(*, tenant_id: str, invoice_id: str,
                              amount_cents: int, paid_at: str,
                              payment_intent_id: Optional[str] = None) -> bool:
    """Increment ``quotes.amount_paid`` idempotently per PaymentIntent.

    Feb-2026 · double-count fix — the belt-and-suspenders sync path
    inside ``charge_card_on_file`` AND the async ``payment_intent.
    succeeded`` webhook both call this helper for the same PI, so a
    naïve ``prior + delta`` write doubles ``amount_paid`` on a $0.50
    charge to $1.00. We now dedupe on ``stripe_payment_intent_id``
    via a per-invoice ``paid_from_intents`` set: if the incoming PI
    is already recorded on the invoice, this is a no-op.

    Missing / falsy ``payment_intent_id`` falls back to the legacy
    ``$or`` idempotency guard for backwards compatibility (checkout
    session paths that don't carry a PI yet).
    """
    inv = await db.quotes.find_one(
        {"id": invoice_id, "tenant_id": tenant_id, "doc_type": "invoice"},
        {"_id": 0, "amount_paid": 1, "total": 1, "payment_status": 1,
         "paid_from_intents": 1},
    )
    if not inv:
        return False
    seen_intents = set(inv.get("paid_from_intents") or [])
    if payment_intent_id and payment_intent_id in seen_intents:
        # Replay / dual-path duplicate — the invoice already has this
        # PI's amount counted. No-op, safe on both sync+webhook races.
        logger.debug(
            "[stripe] _mark_invoice_paid noop pi=%s already in "
            "paid_from_intents for invoice=%s", payment_intent_id, invoice_id,
        )
        return False
    prior = float(inv.get("amount_paid") or 0)
    new_paid = round(prior + (int(amount_cents) / 100.0), 2)
    total = float(inv.get("total") or 0)
    fully = new_paid + 0.01 >= total if total > 0 else True
    set_doc: dict = {
        "amount_paid": new_paid,
        "payment_status": "paid" if fully else "partial",
        "payment_method": "stripe",
    }
    if fully:
        set_doc["paid_at"] = paid_at
    if payment_intent_id:
        set_doc["stripe_payment_intent_id"] = payment_intent_id

    # Atomic write. When we have a PI id, ``$addToSet`` is the
    # source-of-truth for "this PI has already flipped the invoice"
    # — and the match filter blocks a concurrent second writer that
    # slipped past the read-time check above.
    update_doc: dict = {"$set": set_doc}
    match: dict = {"id": invoice_id, "tenant_id": tenant_id,
                   "doc_type": "invoice"}
    if payment_intent_id:
        update_doc["$addToSet"] = {"paid_from_intents": payment_intent_id}
        # If a racing writer already added this PI, don't reapply.
        match["paid_from_intents"] = {"$ne": payment_intent_id}
    else:
        # Legacy fallback for callers that don't pass a PI id.
        match["$or"] = [{"payment_status": {"$ne": "paid"}},
                        {"amount_paid": {"$lt": new_paid}}]
    r = await db.quotes.update_one(match, update_doc)
    return bool(r.modified_count)


async def _mark_invoice_failed(*, tenant_id: str, invoice_id: str,
                                failure_reason: str) -> None:
    await db.quotes.update_one(
        {"id": invoice_id, "tenant_id": tenant_id, "doc_type": "invoice",
         "payment_status": {"$nin": ["paid", "refunded", "partially_refunded"]}},
        {"$set": {"payment_status": "failed",
                    "failure_reason": failure_reason}},
    )


async def _apply_refund_to_invoice(*, tenant_id: str, invoice_id: str,
                                     refund_cents: int, fully_refunded: bool,
                                     refund_key: str) -> bool:
    """Reduce ``quotes.amount_paid`` for a refund event, idempotent
    on ``refund_key``.

    Feb-2026 · replay fix — ``charge.refunded`` webhook retries
    (Stripe re-delivers on any non-2xx or when the operator clicks
    "Resend") re-invoke this handler with an identical payload. The
    prior code blindly subtracted ``amount_refunded`` again → double
    reduction. We now dedupe on a caller-computed ``refund_key`` via
    a per-invoice ``refunded_from_intents`` set. The key is stable
    per Stripe event so any replay is a no-op.

    Choice: keep the key in ``refunded_from_intents`` (audit trail)
    rather than remove it on partial→full transitions. That mirrors
    how ``paid_from_intents`` records the *forward* audit and keeps
    the ledger reconstructable from Mongo alone.
    """
    inv = await db.quotes.find_one(
        {"id": invoice_id, "tenant_id": tenant_id, "doc_type": "invoice"},
        {"_id": 0, "amount_paid": 1, "refunded_from_intents": 1},
    )
    if not inv:
        return False
    seen_refunds = set(inv.get("refunded_from_intents") or [])
    if refund_key in seen_refunds:
        logger.debug(
            "[stripe] _apply_refund_to_invoice noop key=%s already applied "
            "to invoice=%s", refund_key, invoice_id,
        )
        return False
    prior = float(inv.get("amount_paid") or 0)
    new_paid = round(max(prior - (int(refund_cents) / 100.0), 0.0), 2)
    r = await db.quotes.update_one(
        {"id": invoice_id, "tenant_id": tenant_id, "doc_type": "invoice",
         # Racing-writer guard: only apply if the key isn't already
         # in the audit set.
         "refunded_from_intents": {"$ne": refund_key}},
        {"$set": {
            "amount_paid": 0.0 if fully_refunded else new_paid,
            "payment_status": "refunded" if fully_refunded else "partially_refunded",
            "refunded_at": datetime.now(timezone.utc).isoformat(),
         },
         "$addToSet": {"refunded_from_intents": refund_key}},
    )
    return bool(r.modified_count)


class ThinPayloadRetrieveError(Exception):
    """Feb-2026 · Raised when the thin-payload fallback path fails to
    hydrate the full event via ``stripe.Event.retrieve``.

    Distinct from ``ValueError`` / ``SignatureVerificationError`` so
    the router can map it to a 5xx (transient — Stripe retries) rather
    than a 4xx (permanent — Stripe stops delivery). Stripe's own webhook
    retry policy honors 5xx with exponential backoff; a 4xx would silently
    drop the event and the invoice reconcile would never happen.
    """


def verify_and_parse_webhook(*, payload: bytes, sig_header: str) -> Dict[str, Any]:
    """Verify the Stripe-Signature header and return the parsed event
    dict. Raises the SDK's ``SignatureVerificationError`` on bad sig or
    ``ValueError`` on malformed payload — the router converts to 400.

    Feb-2026 · Thin-payload compat. Stripe's Workbench Event Destinations
    UI now defaults new destinations to "Thin" payload style, which the
    SDK's ``Webhook.construct_event`` explicitly rejects with a
    ``ValueError`` containing "thin event notification". When we detect
    that specific message we:

      1. Verify the signature manually via
         ``stripe.WebhookSignature.verify_header`` (same crypto path the
         classic ``construct_event`` uses internally — bad sig still 400s).
      2. Parse the payload as JSON to extract the event id.
      3. Call ``stripe.Event.retrieve(event_id)`` to hydrate the full
         Snapshot-shaped event. Downstream ``handle_webhook_event`` code
         doesn't change — it sees the same ``data.object`` shape.

    A transient ``Event.retrieve`` failure raises ``ThinPayloadRetrieveError``
    (mapped to 502 in the router → Stripe retries). Signature failures
    raise the SDK's own exception (mapped to 400 → Stripe stops).
    """
    secret = _select_webhook_secret()
    if not secret:
        raise ValueError("webhook secret not configured for current STRIPE_MODE")
    try:
        event = _stripe.Webhook.construct_event(payload, sig_header, secret)
        # Phase 42.3 · Feb 2026 — v15-safe scrape. Prior code did
        # ``dict(event)`` which relied on StripeObject inheriting dict.
        return _asdict(event)
    except Exception as exc:
        # Only fall back for the specific Thin-payload rejection. Every
        # other exception (SignatureVerificationError, malformed JSON,
        # unknown scheme) re-raises unchanged so the router 400s.
        if "thin event notification" not in str(exc).lower():
            raise
        logger.info(
            "[stripe.webhook] Thin-payload event detected — falling back "
            "to manual verify + Event.retrieve hydration",
        )
        # Manual signature check — bad sig raises SignatureVerificationError.
        _stripe.WebhookSignature.verify_header(payload, sig_header, secret)
        try:
            envelope = json.loads(payload)
        except Exception as parse_exc:
            raise ValueError(
                f"thin payload JSON parse failed: {parse_exc}"
            ) from parse_exc
        event_id = (envelope or {}).get("id")
        if not event_id:
            raise ValueError("thin payload missing 'id' field")
        try:
            hydrated = _stripe.Event.retrieve(event_id)
        except Exception as retrieve_exc:
            logger.warning(
                "[stripe.webhook] Event.retrieve(%s) failed during "
                "thin-payload fallback: %s", event_id, retrieve_exc,
            )
            raise ThinPayloadRetrieveError(
                f"Event.retrieve({event_id}) failed: {retrieve_exc}"
            ) from retrieve_exc
        return _asdict(hydrated)


async def handle_webhook_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Idempotent handler for the small set of Stripe events we care about.

    Currently:
      * ``payment_method.attached``  → mirror into ``payment_methods`` if
        absent (guards against a client that never called our ``/attach``
        endpoint after Elements confirmed).
      * ``payment_method.detached``  → drop the mirror row if present.
      * ``payment_intent.succeeded`` / ``payment_intent.payment_failed`` →
        upsert into ``stripe_charges`` on the ``stripe_payment_intent_id``
        so we never lose a status update even if the API-triggered path
        crashed mid-write.
    """
    # Phase 42.3 · Feb 2026 — v15-safe scrape. ``event`` may already
    # be a plain dict (from ``verify_and_parse_webhook``) or a raw
    # StripeObject if a caller invoked us directly.
    event = _asdict(event)
    etype = event.get("type") or ""
    data_env = _asdict(event.get("data") or {})
    data = _asdict(data_env.get("object") or {})
    result = {"type": etype, "handled": False}

    if etype == "payment_method.attached":
        pm_id = data.get("id")
        cust_id = data.get("customer")
        if not pm_id or not cust_id:
            return result
        crm_customer = await db.customers.find_one(
            {"stripe_customer_id": cust_id}, {"_id": 0, "id": 1, "tenant_id": 1}
        )
        if not crm_customer:
            return result
        card = data.get("card") or {}
        existing = await db.payment_methods.find_one(
            {"provider_payment_method_id": pm_id, "tenant_id": crm_customer["tenant_id"]},
            {"_id": 0, "id": 1},
        )
        if existing:
            result["handled"] = True
            return result
        now = datetime.now(timezone.utc).isoformat()
        await db.payment_methods.insert_one(
            {
                "id": str(uuid.uuid4()),
                "tenant_id": crm_customer["tenant_id"],
                "customer_id": crm_customer["id"],
                "provider": "stripe",
                "provider_customer_id": cust_id,
                "provider_payment_method_id": pm_id,
                "brand": card.get("brand") or "",
                "last4": card.get("last4") or "",
                "exp_month": card.get("exp_month"),
                "exp_year": card.get("exp_year"),
                "is_default": False,
                "stripe_mode": _mode(),
                "created_at": now,
                "updated_at": now,
            }
        )
        result["handled"] = True
        return result

    if etype == "payment_method.detached":
        pm_id = data.get("id")
        if pm_id:
            await db.payment_methods.delete_many({"provider_payment_method_id": pm_id})
            result["handled"] = True
        return result

    if etype in ("payment_intent.succeeded", "payment_intent.payment_failed"):
        pi_id = data.get("id")
        if not pi_id:
            return result
        status_final = "succeeded" if etype.endswith("succeeded") else "failed"
        err = None
        if status_final == "failed":
            err = (data.get("last_payment_error") or {}).get("message") or "failed"
        meta = (data.get("metadata") or {})
        pi_tenant = meta.get("crm_tenant_id")
        pi_invoice = meta.get("crm_invoice_id") or None
        # Upsert by payment_intent_id so a webhook that arrives before the
        # API-triggered row is fully persisted (rare) still records the
        # outcome without duplicating.
        await db.stripe_charges.update_one(
            {"stripe_payment_intent_id": pi_id},
            {
                "$setOnInsert": {
                    "id": str(uuid.uuid4()),
                    "tenant_id": pi_tenant,
                    "customer_id": meta.get("crm_customer_id"),
                    "provider_payment_method_id": data.get("payment_method"),
                    "amount_cents": data.get("amount"),
                    "currency": data.get("currency"),
                    "invoice_id": pi_invoice,
                    "stripe_mode": _mode(),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                "$set": {
                    "stripe_payment_intent_id": pi_id,
                    "status": status_final,
                    "error": err,
                    "webhook_updated_at": datetime.now(timezone.utc).isoformat(),
                },
            },
            upsert=True,
        )
        # Feb-2026 · FIX 2 — flip the linked invoice. Guarded on
        # tenant + invoice metadata presence. Dashboard-created PIs
        # (no metadata) skip the invoice update and log a warning.
        if pi_tenant and pi_invoice:
            amount = int(data.get("amount_received") or data.get("amount") or 0)
            if status_final == "succeeded":
                await _mark_invoice_paid(
                    tenant_id=pi_tenant, invoice_id=pi_invoice,
                    amount_cents=amount,
                    paid_at=datetime.now(timezone.utc).isoformat(),
                    payment_intent_id=pi_id,
                )
            else:
                await _mark_invoice_failed(
                    tenant_id=pi_tenant, invoice_id=pi_invoice,
                    failure_reason=err or "failed",
                )
            # Feb 2026 · Phase 1 Custom Trigger Builder — schema-v2
            # emissions. Correlation key = payment_intent id so a
            # replayed webhook dedupes. Ledger ALSO dedupes across
            # the manual invoice.paid path (same event_key format).
            try:
                from services.marketing.event_dispatcher import emit_event
                if status_final == "succeeded":
                    _fresh = await db.quotes.find_one(
                        {"id": pi_invoice, "tenant_id": pi_tenant},
                        {"_id": 0},
                    ) or {}
                    await emit_event(
                        event="invoice_paid",
                        tenant_id=pi_tenant,
                        entity_id=pi_invoice,
                        customer_id=_fresh.get("customer_id")
                            or meta.get("crm_customer_id"),
                        payload_extras={"invoice": _fresh,
                                          "correlation_id": pi_invoice},
                    )
                else:
                    await emit_event(
                        event="payment_failed",
                        tenant_id=pi_tenant,
                        entity_id=pi_invoice,
                        customer_id=meta.get("crm_customer_id"),
                        payload_extras={
                            "invoice_id": pi_invoice,
                            "failure_reason": err or "failed",
                            "correlation_id": f"{pi_invoice}:pf:{pi_id}",
                        },
                    )
            except Exception as _phase1_exc:  # pragma: no cover
                logger.warning(
                    "[phase1] stripe webhook emit failed: %s", _phase1_exc,
                )
        elif not pi_tenant or not pi_invoice:
            logger.warning(
                "[stripe.webhook] payment_intent.%s pi=%s missing "
                "metadata (tenant=%r invoice=%r) — invoice unchanged",
                status_final, pi_id, pi_tenant, pi_invoice,
            )
        result["handled"] = True
        return result

    # Feb-2026 · FIX 3 — refund lifecycle. Both events point at the
    # same charge; we key off ``payment_intent`` so partial refunds
    # arriving out-of-order still reconcile cleanly.
    if etype in ("charge.refunded", "refund.updated"):
        pi_id = data.get("payment_intent") or (data.get("charge") or {}).get("payment_intent")
        if not pi_id and etype == "refund.updated":
            # ``refund.updated`` payload sometimes only carries the
            # charge id — resolve to a PI via our stripe_charges row.
            charge_id = data.get("charge")
            if charge_id:
                pri = await db.stripe_charges.find_one(
                    {"stripe_charge_id": charge_id}, {"_id": 0, "stripe_payment_intent_id": 1},
                )
                pi_id = (pri or {}).get("stripe_payment_intent_id")
        if not pi_id:
            return result
        # Look up the charge row (tenant-scoped downstream).
        row = await db.stripe_charges.find_one(
            {"stripe_payment_intent_id": pi_id},
            {"_id": 0, "tenant_id": 1, "invoice_id": 1, "amount_cents": 1},
        )
        if not row:
            logger.warning("[stripe.webhook] %s pi=%s no local charge row", etype, pi_id)
            return result
        amount_orig = int(row.get("amount_cents") or 0)
        # ``charge.refunded``: ``amount_refunded`` lives on the top-
        # level charge. ``refund.updated``: payload IS the refund.
        # Compute a per-event refund_key that is stable across
        # webhook replays so ``_apply_refund_to_invoice`` can dedupe.
        if etype == "charge.refunded":
            amount_refunded = int(data.get("amount_refunded") or 0)
            refund_key = f"chr:{pi_id}:{amount_refunded}"
        else:
            amount_refunded = int(data.get("amount") or 0)
            # Prefer the refund's stable Stripe id (``re_...``); fall
            # back to a synthetic tuple if the payload is stripped.
            refund_key = (
                f"re:{data.get('id')}" if data.get("id")
                else f"reu:{pi_id}:{amount_refunded}"
            )
        full = amount_orig > 0 and amount_refunded >= amount_orig
        new_status = "refunded" if full else "partially_refunded"
        await db.stripe_charges.update_one(
            {"stripe_payment_intent_id": pi_id},
            {"$set": {
                "status": new_status,
                "amount_refunded_cents": amount_refunded,
                "refunded_at": datetime.now(timezone.utc).isoformat(),
                "webhook_updated_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        if row.get("invoice_id") and row.get("tenant_id"):
            await _apply_refund_to_invoice(
                tenant_id=row["tenant_id"], invoice_id=row["invoice_id"],
                refund_cents=amount_refunded, fully_refunded=full,
                refund_key=refund_key,
            )
        result["handled"] = True
        return result

    # Phase 47 · Feb 2026 — direct Stripe Checkout for invoice payment.
    # Reconciles a Session created by :func:`create_invoice_checkout_session`
    # back to the invoice. Idempotent — the invoice-side update is a no-op
    # if the doc is already marked paid; the stripe_charges upsert keys
    # off ``checkout_session_id`` so a duplicate delivery doesn't dupe.
    if etype == "checkout.session.completed":
        session_id = data.get("id")
        meta = _asdict(data.get("metadata") or {})
        invoice_id = meta.get("crm_invoice_id")
        tenant_id = meta.get("crm_tenant_id")
        customer_id = meta.get("crm_customer_id")
        payment_intent_id = data.get("payment_intent")
        payment_status = data.get("payment_status")  # "paid" | "unpaid" | "no_payment_required"
        amount_total_cents = int(data.get("amount_total") or 0)
        currency = (data.get("currency") or "usd").lower()

        if not session_id or not invoice_id:
            # Not a Phase-47 session (or metadata got stripped
            # somewhere) — nothing safe to reconcile.
            return result

        # Mirror the charge into stripe_charges so the same collection
        # backs both the PaymentIntent flow (existing) and the
        # Checkout Session flow (new). Keyed by the session id so a
        # duplicate delivery is a no-op.
        now_iso = datetime.now(timezone.utc).isoformat()
        await db.stripe_charges.update_one(
            {"stripe_checkout_session_id": session_id},
            {
                "$setOnInsert": {
                    "id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "customer_id": customer_id,
                    "provider_payment_method_id": None,
                    "amount_cents": amount_total_cents,
                    "currency": currency,
                    "invoice_id": invoice_id,
                    "stripe_mode": _mode(),
                    "created_at": now_iso,
                    "source": "phase47_invoice_pay",
                },
                "$set": {
                    "stripe_checkout_session_id": session_id,
                    "stripe_payment_intent_id": payment_intent_id,
                    "status": "succeeded" if payment_status == "paid" else "pending",
                    "webhook_updated_at": now_iso,
                },
            },
            upsert=True,
        )

        # Mark the invoice paid / partial. Only fire when Stripe says
        # ``payment_status == "paid"`` — anything else means the
        # customer hasn't actually paid (e.g. bank redirect abandoned).
        if payment_status == "paid":
            await _mark_invoice_paid_from_session(
                invoice_id=invoice_id,
                amount_total_cents=amount_total_cents,
                session_id=session_id,
                payment_intent_id=payment_intent_id,
            )
            # Feb 2026 addendum · save-on-first-payment.
            #
            # When the caller flagged ``save_for_future_billing`` at
            # Session-create time (customer had 0 saved PMs and left
            # the checkbox checked), Stripe issues the PaymentIntent
            # with ``setup_future_usage="off_session"``. The
            # resulting PM is auto-attached to the Stripe customer,
            # BUT we still need to (a) mirror it into
            # ``db.payment_methods`` and (b) mark it as the
            # customer's default so autobilling picks it up. We
            # gate on the metadata flag so this branch is a no-op
            # for existing-PM customers or opted-out ones.
            try:
                await _save_pm_after_first_payment(
                    tenant_id=tenant_id,
                    customer_id=customer_id,
                    metadata=meta,
                    payment_intent_id=payment_intent_id,
                )
            except Exception as _save_exc:  # pragma: no cover — best-effort
                logger.warning(
                    "[phase47] save-on-first-payment failed for "
                    "invoice=%s pi=%s: %s",
                    invoice_id, payment_intent_id, _save_exc,
                )
            # Audit trail row so operators can see the reconcile event
            # in ``db.payment_events`` alongside legacy Lumino callbacks.
            try:
                await db.payment_events.insert_one({
                    "id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "customer_id": customer_id,
                    "invoice_id": invoice_id,
                    "kind": "phase47_checkout_session_completed",
                    "session_id": session_id,
                    "payment_intent_id": payment_intent_id,
                    "amount_cents": amount_total_cents,
                    "currency": currency,
                    "created_at": now_iso,
                })
            except Exception as _log_exc:  # pragma: no cover — best-effort
                logger.warning("[phase47] payment_events insert failed: %s", _log_exc)

        result["handled"] = True
        return result

    # ═══════════════════════════════════════════════════════════════
    # Phase B3 · Feb-2026 — new event handlers.
    # ═══════════════════════════════════════════════════════════════

    # SetupIntent lifecycle for ACH bank-account verification.
    # ``verification_status`` is the source-of-truth flag on
    # ``payment_methods`` mirror rows for us_bank_account PMs.
    if etype in (
        "setup_intent.succeeded",
        "setup_intent.setup_failed",
        "setup_intent.requires_action",
    ):
        pm_id = data.get("payment_method")
        # Some SetupIntent payloads carry a nested object; unpack if
        # Stripe expanded ``payment_method`` inline.
        if isinstance(pm_id, dict):
            pm_id = pm_id.get("id")
        if not pm_id:
            return result
        if etype == "setup_intent.succeeded":
            new_status = "verified"
            update: Dict[str, Any] = {
                "verification_status": new_status,
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "webhook_updated_at": datetime.now(timezone.utc).isoformat(),
            }
        elif etype == "setup_intent.setup_failed":
            new_status = "failed"
            err_obj = data.get("last_setup_error") or {}
            update = {
                "verification_status": new_status,
                "verification_error": err_obj.get("message") or err_obj.get("code") or "failed",
                "webhook_updated_at": datetime.now(timezone.utc).isoformat(),
            }
        else:  # setup_intent.requires_action
            new_status = "pending"
            update = {
                "verification_status": new_status,
                "webhook_updated_at": datetime.now(timezone.utc).isoformat(),
            }
        r = await db.payment_methods.update_many(
            {"provider_payment_method_id": pm_id},
            {"$set": update},
        )
        result["handled"] = True
        result["matched"] = r.matched_count
        result["new_status"] = new_status
        return result

    # PaymentIntent processing — ACH in-transit. Update the local
    # charge mirror only; the invoice stays unpaid until
    # ``payment_intent.succeeded`` fires (already handled above).
    if etype == "payment_intent.processing":
        pi_id = data.get("id")
        if not pi_id:
            return result
        meta = (data.get("metadata") or {})
        await db.stripe_charges.update_one(
            {"stripe_payment_intent_id": pi_id},
            {
                "$setOnInsert": {
                    "id": str(uuid.uuid4()),
                    "tenant_id": meta.get("crm_tenant_id"),
                    "customer_id": meta.get("crm_customer_id"),
                    "provider_payment_method_id": data.get("payment_method"),
                    "amount_cents": data.get("amount"),
                    "currency": data.get("currency"),
                    "invoice_id": meta.get("crm_invoice_id"),
                    "stripe_mode": _mode(),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                "$set": {
                    "stripe_payment_intent_id": pi_id,
                    "status": "processing",
                    "webhook_updated_at": datetime.now(timezone.utc).isoformat(),
                },
            },
            upsert=True,
        )
        result["handled"] = True
        return result

    # Stripe-side invoice lifecycle. Only reconciles when the
    # invoice is linked to a live ``db.quotes`` row via metadata.
    # Unlinked Stripe invoices (Stripe-native billing, dashboard-
    # created) are logged and no-op'd.
    if etype in ("invoice.paid", "invoice.finalized", "invoice.payment_failed"):
        inv_meta = (data.get("metadata") or {})
        tenant_id = inv_meta.get("crm_tenant_id")
        crm_invoice_id = inv_meta.get("crm_invoice_id")
        if not tenant_id or not crm_invoice_id:
            logger.info(
                "[stripe.webhook] %s stripe_inv=%s no crm linkage — noop",
                etype, data.get("id"),
            )
            return result
        now_iso = datetime.now(timezone.utc).isoformat()
        if etype == "invoice.paid":
            amount_cents = int(data.get("amount_paid") or data.get("total") or 0)
            await _mark_invoice_paid(
                tenant_id=tenant_id, invoice_id=crm_invoice_id,
                amount_cents=amount_cents,
                paid_at=now_iso,
                payment_intent_id=data.get("payment_intent"),
            )
        elif etype == "invoice.payment_failed":
            err_obj = data.get("last_finalization_error") or {}
            reason = err_obj.get("message") or err_obj.get("code") or "payment_failed"
            await _mark_invoice_failed(
                tenant_id=tenant_id, invoice_id=crm_invoice_id,
                failure_reason=reason,
            )
        else:  # invoice.finalized
            # Store a minimal reference so operators can trace back
            # to the Stripe invoice; no state change on the CRM row.
            await db.quotes.update_one(
                {"id": crm_invoice_id, "tenant_id": tenant_id},
                {"$set": {
                    "stripe_invoice_id": data.get("id"),
                    "stripe_invoice_finalized_at": now_iso,
                }},
            )
        result["handled"] = True
        return result

    # Subscription lifecycle — mirror into ``stripe_subscriptions``.
    # This is the source-of-truth going forward; ``db.subscriptions``
    # is a legacy Lumino-era collection kept read-only (see B3 audit
    # note under §E).
    if etype in (
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        sub_id = data.get("id")
        if not sub_id:
            return result
        meta = (data.get("metadata") or {})
        tenant_hint = meta.get("crm_tenant_id")
        # Fall back to the customer's metadata if it was expanded.
        cust_obj = data.get("customer")
        if not tenant_hint and isinstance(cust_obj, dict):
            cust_meta = (cust_obj.get("metadata") or {})
            tenant_hint = cust_meta.get("crm_tenant_id")
        stripe_customer_id = cust_obj.get("id") if isinstance(cust_obj, dict) else cust_obj
        now_iso = datetime.now(timezone.utc).isoformat()

        def _epoch(v):
            if not v:
                return None
            try:
                return datetime.fromtimestamp(int(v), tz=timezone.utc).isoformat()
            except Exception:  # noqa: BLE001
                return None

        set_doc: Dict[str, Any] = {
            "status": data.get("status") or "unknown",
            "current_period_start": _epoch(data.get("current_period_start")),
            "current_period_end": _epoch(data.get("current_period_end")),
            "cancel_at_period_end": bool(data.get("cancel_at_period_end")),
            "canceled_at": _epoch(data.get("canceled_at")),
            "updated_at": now_iso,
            "webhook_source": etype,
        }
        # Feb-2026 · price enrichment — pull enriched price/product
        # fields off the incoming event when possible, otherwise
        # fall back to a Stripe retrieve. Best-effort — a missing
        # price shouldn't break the mirror upsert.
        try:
            from services.payments.stripe_subscription import (
                _extract_price_meta, _enrich_price_from_id,
            )
            price_meta = _extract_price_meta(data)
            if price_meta and not price_meta.get("price_product_name"):
                # ``product`` wasn't expanded on the event — hydrate it.
                extra = await _enrich_price_from_id(price_meta.get("price_id") or "")
                # Merge without clobbering the fields already resolved.
                for k, v in (extra or {}).items():
                    if v is not None:
                        price_meta[k] = v
            if price_meta:
                set_doc.update(price_meta)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[stripe.webhook] price enrich failed for sub %s: %s", sub_id, exc)
        if etype == "customer.subscription.deleted":
            set_doc["status"] = "canceled"
            set_doc["canceled_at"] = set_doc["canceled_at"] or now_iso

        insert_doc: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_hint,
            "customer_id": None,  # best-effort backfill below
            "stripe_subscription_id": sub_id,
            "stripe_customer_id": stripe_customer_id,
            "created_at": _epoch(data.get("created")) or now_iso,
        }
        # Best-effort CRM customer resolution — same pattern as the
        # PM.attached handler above.
        if stripe_customer_id:
            crm_cust = await db.customers.find_one(
                {"stripe_customer_id": stripe_customer_id},
                {"_id": 0, "id": 1, "tenant_id": 1},
            )
            if crm_cust:
                insert_doc["customer_id"] = crm_cust["id"]
                if not insert_doc["tenant_id"]:
                    insert_doc["tenant_id"] = crm_cust["tenant_id"]

        await db.stripe_subscriptions.update_one(
            {"stripe_subscription_id": sub_id},
            {"$setOnInsert": insert_doc, "$set": set_doc},
            upsert=True,
        )
        result["handled"] = True
        result["stripe_subscription_id"] = sub_id
        return result

    return result
