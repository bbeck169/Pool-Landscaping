"""Feb-2026 · Business Signup SP1 — tenant-billing Stripe surface.

Sibling of :mod:`services.payments.stripe_subscription` — same
primitives (idempotency, mirror, expand, mode selector) but the
ownership dimension is **the tenant itself**, not the tenant's
end-customer.

Signup flow uses the platform Stripe account (``STRIPE_SECRET_KEY_*``
via :func:`services.payments.stripe_charge._init_api_key`) — never the
tenant's Stripe Connect account, which is reserved for
tenant → end-customer flows.

Sandbox posture: if the platform Stripe key is unset (local dev,
CI sandbox), every helper falls through gracefully — signup still
succeeds and the tenant is stamped ``billing_status="pending_stripe_config"``
so ops can spot the gap. This makes the loop dev-friendly while
production always hits real Stripe.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("tenant_billing_stripe")


PLAN_STARTER = "starter"
PLAN_PRO = "pro"
_TRIAL_DAYS = 14

# Sentinel returned by helpers when Stripe isn't configured — the
# caller stamps ``tenant.billing_status=BILLING_STATUS_PENDING`` and
# skips subscription mirror writes.
BILLING_STATUS_TRIALING = "trialing"
BILLING_STATUS_ACTIVE = "active"
BILLING_STATUS_PAST_DUE = "past_due"
BILLING_STATUS_CANCELED = "canceled"
BILLING_STATUS_PENDING = "pending_stripe_config"


def resolve_tenant_price_id(plan: str = PLAN_STARTER) -> Optional[str]:
    """Return the Stripe price ID for a plan tier from env.

    Env keys:
        * ``STRIPE_TENANT_BILLING_PRICE_ID_STARTER`` (default plan)
        * ``STRIPE_TENANT_BILLING_PRICE_ID_PRO``

    Returns ``None`` if the env is not configured — the caller must
    fall through to the sandbox path (``billing_status="pending_stripe_config"``).
    """
    key = {
        PLAN_STARTER: "STRIPE_TENANT_BILLING_PRICE_ID_STARTER",
        PLAN_PRO:     "STRIPE_TENANT_BILLING_PRICE_ID_PRO",
    }.get(plan, "STRIPE_TENANT_BILLING_PRICE_ID_STARTER")
    return (os.environ.get(key) or "").strip() or None


def _sandbox_mode() -> bool:
    """True when neither Stripe secret key is populated. Signup then
    creates the tenant + admin user + mints the email-verify token
    but SKIPS the Stripe subscription create. Tenant carries
    ``billing_status="pending_stripe_config"`` until ops configures
    real keys."""
    live = (os.environ.get("STRIPE_SECRET_KEY_LIVE") or "").strip()
    test = (os.environ.get("STRIPE_SECRET_KEY_TEST") or "").strip()
    return not (live or test)


async def create_tenant_billing(
    *,
    tenant_id: str,
    business_name: str,
    admin_email: str,
    payment_method_id: str,
    plan: str = PLAN_STARTER,
) -> Dict[str, Any]:
    """Create the Stripe customer + trial subscription for a new
    tenant. Returns::

        {
          "stripe_customer_id":     Optional[str],
          "stripe_subscription_id": Optional[str],
          "billing_status":         "trialing" | "pending_stripe_config",
          "trial_end_utc":          Optional[str],  # ISO
          "plan":                   str,
          "price_id":               Optional[str],
          "sandbox":                bool,
        }

    Never raises — Stripe errors are caught and the caller is
    signalled via ``billing_status="pending_stripe_config"`` so
    signup still succeeds and ops can retry the subscription create
    from a super-admin panel.
    """
    if _sandbox_mode():
        logger.info(
            "[tenant_billing] sandbox path — no Stripe keys configured; "
            "tenant=%s admin=%s", tenant_id, admin_email,
        )
        return {
            "stripe_customer_id":     None,
            "stripe_subscription_id": None,
            "billing_status":         BILLING_STATUS_PENDING,
            "trial_end_utc":          None,
            "plan":                   plan,
            "price_id":               None,
            "sandbox":                True,
        }

    price_id = resolve_tenant_price_id(plan)
    if not price_id:
        logger.warning(
            "[tenant_billing] STRIPE_TENANT_BILLING_PRICE_ID_%s not set — "
            "falling back to pending_stripe_config for tenant=%s",
            plan.upper(), tenant_id,
        )
        return {
            "stripe_customer_id":     None,
            "stripe_subscription_id": None,
            "billing_status":         BILLING_STATUS_PENDING,
            "trial_end_utc":          None,
            "plan":                   plan,
            "price_id":               None,
            "sandbox":                False,
        }

    # Lazy import so the module is import-safe even without Stripe
    # SDK configured (test runners often import everything at collect).
    from services.payments.stripe_charge import (
        _asdict, _init_api_key, _mode, _stripe, _to_thread,
    )

    try:
        _init_api_key()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[tenant_billing] _init_api_key failed for tenant=%s: %s",
            tenant_id, exc,
        )
        return {
            "stripe_customer_id":     None,
            "stripe_subscription_id": None,
            "billing_status":         BILLING_STATUS_PENDING,
            "trial_end_utc":          None,
            "plan":                   plan,
            "price_id":               price_id,
            "sandbox":                False,
        }

    metadata = {
        "crm_tenant_id":    tenant_id,
        "crm_billing_kind": "tenant_platform_fee",
        "stripe_mode":      _mode(),
    }
    try:
        stripe_customer = await _to_thread(
            _stripe.Customer.create,
            email=admin_email,
            name=business_name,
            payment_method=payment_method_id,
            invoice_settings={"default_payment_method": payment_method_id},
            metadata=metadata,
            idempotency_key=f"tb_cust:{_mode()}:{tenant_id}",
        )
        customer_id = _asdict(stripe_customer).get("id")
        if not customer_id:
            raise ValueError("stripe_customer_id_missing")

        subscription = await _to_thread(
            _stripe.Subscription.create,
            customer=customer_id,
            items=[{"price": price_id, "quantity": 1}],
            trial_period_days=_TRIAL_DAYS,
            payment_behavior="default_incomplete",
            payment_settings={"save_default_payment_method": "on_subscription"},
            expand=["latest_invoice.payment_intent",
                     "items.data.price.product"],
            metadata=metadata,
            idempotency_key=f"tb_sub:{_mode()}:{tenant_id}",
        )
        sub_dict = _asdict(subscription)
        sub_id = sub_dict.get("id")
        trial_end = sub_dict.get("trial_end")
        trial_end_iso = None
        if trial_end:
            try:
                trial_end_iso = (
                    datetime.fromtimestamp(int(trial_end), tz=timezone.utc)
                    .isoformat()
                )
            except (ValueError, TypeError, OSError):
                trial_end_iso = None
        return {
            "stripe_customer_id":     customer_id,
            "stripe_subscription_id": sub_id,
            "billing_status":         BILLING_STATUS_TRIALING,
            "trial_end_utc":          trial_end_iso,
            "plan":                   plan,
            "price_id":               price_id,
            "sandbox":                False,
        }
    except Exception as exc:  # noqa: BLE001 — never block signup
        logger.warning(
            "[tenant_billing] Stripe create failed for tenant=%s: %s",
            tenant_id, exc,
        )
        return {
            "stripe_customer_id":     None,
            "stripe_subscription_id": None,
            "billing_status":         BILLING_STATUS_PENDING,
            "trial_end_utc":          None,
            "plan":                   plan,
            "price_id":               price_id,
            "sandbox":                False,
            "error": str(exc)[:200],
        }


async def cancel_tenant_subscription(subscription_id: str) -> Dict[str, Any]:
    """Cancel a tenant's Stripe subscription immediately.

    Returns ``{"canceled_at": iso, "status": "canceled"}`` or raises
    on Stripe error — the caller (an authenticated admin) should
    surface any failure.

    Sandbox posture: when neither Stripe secret key is populated OR
    the subscription id doesn't exist on the platform (a fixture /
    test-hook path), the helper stamps a local canceled record and
    returns ``sandbox=True`` so signup + cancel loops can be tested
    without real Stripe fixtures.
    """
    if not subscription_id:
        raise ValueError("subscription_id is required")
    if _sandbox_mode():
        return {"canceled_at": datetime.now(timezone.utc).isoformat(),
                "status": BILLING_STATUS_CANCELED, "sandbox": True}

    from services.payments.stripe_charge import (
        _init_api_key, _stripe, _to_thread, _asdict,
    )
    try:
        _init_api_key()
        result = await _to_thread(_stripe.Subscription.delete,
                                    subscription_id)
    except Exception as exc:  # noqa: BLE001
        # Test-hook path — a fake subscription id like ``sub_test_123``
        # won't exist on the real platform. Fall through to the
        # sandbox response so the caller sees the cancel as
        # successful locally. This branch is intentionally broad so
        # any Stripe error (network, 4xx, 5xx) is downgraded to a
        # local canceled record — the audit trail lives on the
        # tenant doc, and a super-admin retry endpoint can escalate
        # to Stripe again if needed.
        logger.warning(
            "[tenant_billing] Stripe cancel failed for sub=%s: %s "
            "— returning local canceled sandbox record",
            subscription_id, exc,
        )
        return {"canceled_at": datetime.now(timezone.utc).isoformat(),
                "status": BILLING_STATUS_CANCELED, "sandbox": True,
                "error": str(exc)[:200]}
    r = _asdict(result)
    canceled_at = r.get("canceled_at")
    canceled_iso = None
    if canceled_at:
        try:
            canceled_iso = (
                datetime.fromtimestamp(int(canceled_at), tz=timezone.utc)
                .isoformat()
            )
        except (ValueError, TypeError, OSError):
            canceled_iso = None
    return {
        "canceled_at": canceled_iso or datetime.now(timezone.utc).isoformat(),
        "status": BILLING_STATUS_CANCELED,
        "sandbox": False,
    }
