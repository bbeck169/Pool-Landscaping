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


# ── Public helpers ────────────────────────────────────────────────────
async def create_setup_intent(
    *, tenant_id: str, customer_id: str, actor_user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Create a Stripe Customer (if needed) + a SetupIntent for saving a card.

    Returns the SetupIntent client_secret + the Stripe customer id so the
    frontend can render ``<Elements clientSecret={...}>`` and confirm the
    card with ``stripe.confirmSetup``.
    """
    _init_api_key()

    customer = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not customer:
        raise ValueError("customer not found")

    provider_customer_id = customer.get("stripe_customer_id") or ""
    if not provider_customer_id:
        # Create a fresh Stripe customer. Use the CRM customer id as
        # idempotency key so a retry from the same session doesn't
        # duplicate the Stripe-side record.
        stripe_cust = await _to_thread(
            _stripe.Customer.create,
            email=(customer.get("email") or None),
            name=(customer.get("name") or None),
            metadata={
                "crm_customer_id": customer_id,
                "crm_tenant_id": tenant_id,
                "stripe_mode": _mode(),
            },
            idempotency_key=f"cust_create:{tenant_id}:{customer_id}",
        )
        provider_customer_id = stripe_cust["id"]
        await db.customers.update_one(
            {"id": customer_id, "tenant_id": tenant_id},
            {"$set": {"stripe_customer_id": provider_customer_id}},
        )

    # Phase 42.3 · Feb 2026 — deterministic idempotency key so
    # re-tries within the same day for the same (tenant, customer)
    # don't proliferate SetupIntents.
    _si_idem = (
        f"si:{tenant_id}:{customer_id}:"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d')}"
    )
    setup_intent = await _to_thread(
        _stripe.SetupIntent.create,
        customer=provider_customer_id,
        payment_method_types=["card"],
        usage="off_session",
        metadata={
            "crm_customer_id": customer_id,
            "crm_tenant_id": tenant_id,
            "actor_user_id": actor_user_id or "",
        },
        idempotency_key=_si_idem,
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

    now = datetime.now(timezone.utc).isoformat()
    mirror = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "provider": "stripe",
        "provider_customer_id": provider_customer_id,
        "provider_payment_method_id": payment_method_id,
        "brand": card.get("brand") or "",
        "last4": card.get("last4") or "",
        "exp_month": card.get("exp_month"),
        "exp_year": card.get("exp_year"),
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

    md = {
        "crm_tenant_id": tenant_id,
        "crm_customer_id": customer_id,
        "crm_invoice_id": invoice_id or "",
        "actor_user_id": actor_user_id or "",
        **{str(k): str(v) for k, v in (metadata or {}).items()},
    }
    charge_row_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    try:
        intent = await _to_thread(
            _stripe.PaymentIntent.create,
            amount=amount_cents,
            currency=currency,
            customer=provider_customer_id,
            payment_method=payment_method_id,
            off_session=True,
            confirm=True,
            description=description or None,
            metadata=md,
            idempotency_key=idempotency_key or f"charge:{charge_row_id}",
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


# ── Webhook helpers ───────────────────────────────────────────────────
def verify_and_parse_webhook(*, payload: bytes, sig_header: str) -> Dict[str, Any]:
    """Verify the Stripe-Signature header and return the parsed event
    dict. Raises the SDK's ``SignatureVerificationError`` on bad sig or
    ``ValueError`` on malformed payload — the router converts to 400.
    """
    secret = _select_webhook_secret()
    if not secret:
        raise ValueError("webhook secret not configured for current STRIPE_MODE")
    event = _stripe.Webhook.construct_event(payload, sig_header, secret)
    # Phase 42.3 · Feb 2026 — v15-safe scrape. Prior code did
    # ``dict(event)`` which relied on StripeObject inheriting dict.
    return _asdict(event)


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
        # Upsert by payment_intent_id so a webhook that arrives before the
        # API-triggered row is fully persisted (rare) still records the
        # outcome without duplicating.
        await db.stripe_charges.update_one(
            {"stripe_payment_intent_id": pi_id},
            {
                "$setOnInsert": {
                    "id": str(uuid.uuid4()),
                    "tenant_id": (data.get("metadata") or {}).get("crm_tenant_id"),
                    "customer_id": (data.get("metadata") or {}).get("crm_customer_id"),
                    "provider_payment_method_id": data.get("payment_method"),
                    "amount_cents": data.get("amount"),
                    "currency": data.get("currency"),
                    "invoice_id": (data.get("metadata") or {}).get("crm_invoice_id") or None,
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
        result["handled"] = True
    return result
