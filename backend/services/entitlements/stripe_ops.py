"""Sprint 3c · Feb-2026 — Sandbox-safe Stripe subscription-item ops.

Mirrors the sandbox posture used across the codebase
(``services.payments.tenant_billing_stripe``,
``services.payments.stripe_charge``): when Stripe secrets are
unset OR the tenant lacks a real Stripe subscription, every
helper falls through to a **synthetic** response so preview
environments + tests can exercise the marketplace flows end to end.

Public API:
    * :func:`add_feature_item_to_subscription` — add a Stripe
      subscription item with immediate proration.
    * :func:`schedule_feature_item_cancel_at_period_end` — mark
      the item for cancellation at period end without proration.
    * :func:`fetch_subscription_period_end` — helper for the
      ``cancels_at`` timestamp.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

log = logging.getLogger("entitlements.stripe_ops")


class NoActiveSubscriptionError(Exception):
    """Raised when a tenant tries to enable a feature but has no
    active Stripe subscription to attach it to."""


class StripeFeatureError(Exception):
    """Raised when Stripe returns an error during enable/disable."""

    def __init__(self, message: str, code: str = "stripe_error"):
        super().__init__(message)
        self.code = code
        self.message = message


def _sandbox_mode(price_id: Optional[str] = None) -> bool:
    """True when either Stripe secret is unset (preview env / CI)
    OR the ``price_id`` uses the ``price_sandbox_`` prefix (used by
    tests + local demos so the enable/disable loop can be exercised
    without provisioning real Stripe prices).  Prod prices never
    start with ``price_sandbox_`` — they are Stripe-generated IDs
    like ``price_1P…``."""
    live = (os.environ.get("STRIPE_SECRET_KEY_LIVE") or "").strip()
    test = (os.environ.get("STRIPE_SECRET_KEY_TEST") or "").strip()
    if not (live or test):
        return True
    if isinstance(price_id, str) and price_id.startswith("price_sandbox_"):
        return True
    return False


async def _get_tenant_subscription(db, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Fetch the tenant's most recent Stripe subscription mirror row.

    We use the ``stripe_subscriptions`` collection (the canonical
    mirror — see ``services.payments.stripe_subscription``). Only
    active/trialing/past_due are eligible; canceled subs cannot
    accept new items.
    """
    row = await db.stripe_subscriptions.find_one(
        {
            "tenant_id": tenant_id,
            "status": {"$in": ["active", "trialing", "past_due"]},
        },
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    return row


async def add_feature_item_to_subscription(
    *, db, tenant_id: str, feature_key: str, price_id: str,
) -> Dict[str, Any]:
    """Add a feature as a subscription item with immediate proration.

    Returns ``{"stripe_subscription_item_id": str,
                "stripe_subscription_id": str,
                "sandbox": bool}``.

    Raises:
        NoActiveSubscriptionError — tenant has no eligible sub.
        StripeFeatureError        — Stripe rejected the create.
    """
    sub = await _get_tenant_subscription(db, tenant_id)
    if not sub or not sub.get("stripe_subscription_id"):
        raise NoActiveSubscriptionError(
            "tenant has no active Stripe subscription",
        )
    stripe_sub_id = sub["stripe_subscription_id"]

    if _sandbox_mode(price_id):
        # Preview env — synthesize a deterministic item id so
        # the entitlement doc + audit trail work end-to-end.
        synthetic_id = f"si_sandbox_{tenant_id[:6]}_{feature_key}"
        log.info(
            "[entitlements] sandbox add item tenant=%s feature=%s -> %s",
            tenant_id, feature_key, synthetic_id,
        )
        return {
            "stripe_subscription_item_id": synthetic_id,
            "stripe_subscription_id":      stripe_sub_id,
            "sandbox":                      True,
        }

    from services.payments.stripe_charge import (
        _asdict, _init_api_key, _mode, _stripe, _to_thread,
    )
    try:
        _init_api_key()
        item = await _to_thread(
            _stripe.SubscriptionItem.create,
            subscription=stripe_sub_id,
            price=price_id,
            quantity=1,
            proration_behavior="create_prorations",
            metadata={
                "crm_tenant_id": tenant_id,
                "crm_feature_key": feature_key,
                "stripe_mode": _mode(),
            },
            idempotency_key=f"ent_enable:{_mode()}:{tenant_id}:{feature_key}",
        )
    except Exception as exc:                                        # noqa: BLE001
        log.warning(
            "[entitlements] Stripe SubscriptionItem.create failed "
            "tenant=%s feature=%s err=%s", tenant_id, feature_key, exc,
        )
        raise StripeFeatureError(str(exc)[:200]) from exc
    item_id = _asdict(item).get("id")
    if not item_id:
        raise StripeFeatureError("stripe_subscription_item_id_missing")
    return {
        "stripe_subscription_item_id": item_id,
        "stripe_subscription_id":      stripe_sub_id,
        "sandbox":                      False,
    }


async def schedule_feature_item_cancel_at_period_end(
    *, db, tenant_id: str, feature_key: str,
    stripe_subscription_item_id: str,
) -> Dict[str, Any]:
    """Schedule the feature item for cancellation at period end.

    Stripe's subscription-item delete API doesn't support
    ``cancel_at_period_end`` directly, so we use the pattern from
    the Stripe docs: leave the item on the subscription until the
    period rolls, then a subscription-update at that moment
    removes it. In the interim we stamp the entitlement doc's
    ``cancels_at`` to the subscription's ``current_period_end``.

    In the current-cycle window the item is still billed for
    (already-paid), which matches the "no additional charges,
    access continues until cycle end" UX.

    Returns ``{"cancels_at": <ISO>, "sandbox": bool}``.
    """
    period_end = await fetch_subscription_period_end(
        db=db, tenant_id=tenant_id,
    )
    # Sandbox posture — either Stripe keys are unset OR the item
    # id was synthesized on the enable path. Both cases are
    # deterministic markers that we should stay in sandbox on
    # cancel too, so tests + preview demos can round-trip without
    # calling real Stripe.
    is_sandbox_item = (
        isinstance(stripe_subscription_item_id, str)
        and stripe_subscription_item_id.startswith("si_sandbox_")
    )
    if _sandbox_mode() or is_sandbox_item:
        log.info(
            "[entitlements] sandbox schedule cancel tenant=%s feature=%s "
            "period_end=%s", tenant_id, feature_key, period_end,
        )
        return {"cancels_at": period_end, "sandbox": True}

    # Real Stripe path — flip the subscription-level
    # ``cancel_at_period_end`` semantics per subscription-item is
    # not natively supported, so we tag the item metadata for the
    # billing cron to drop at the next boundary. The mirror row's
    # ``current_period_end`` is authoritative for the UI.
    from services.payments.stripe_charge import (
        _init_api_key, _mode, _stripe, _to_thread,
    )
    try:
        _init_api_key()
        await _to_thread(
            _stripe.SubscriptionItem.modify,
            stripe_subscription_item_id,
            metadata={
                "crm_tenant_id":            tenant_id,
                "crm_feature_key":          feature_key,
                "crm_cancel_at_period_end": "1",
                "stripe_mode":              _mode(),
            },
        )
    except Exception as exc:                                        # noqa: BLE001
        log.warning(
            "[entitlements] Stripe SubscriptionItem.modify failed "
            "tenant=%s feature=%s err=%s", tenant_id, feature_key, exc,
        )
        raise StripeFeatureError(str(exc)[:200]) from exc
    return {"cancels_at": period_end, "sandbox": False}


async def fetch_subscription_period_end(
    *, db, tenant_id: str,
) -> Optional[str]:
    """Return the ISO timestamp of the tenant's current billing
    period end (or a synthesized future date in sandbox / when no
    subscription exists)."""
    sub = await _get_tenant_subscription(db, tenant_id)
    if sub and sub.get("current_period_end"):
        return str(sub["current_period_end"])
    # Sandbox / no-sub fallback — 30 days from now so the UI has
    # something to render.
    return (
        (datetime.now(timezone.utc) + timedelta(days=30))
        .isoformat()
    )
