"""Sprint 3c · Feb-2026 — Feature Marketplace API.

Admin-only endpoints for browsing + enabling/disabling premium
add-ons. Persistence lives in ``feature_entitlements`` (one row per
(tenant_id, feature_key)); Stripe billing changes go through
:mod:`services.entitlements.stripe_ops`.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from config import db
from routers.tenants import get_current_tenant
from services.entitlements.check import (
    BILLING_STATUS_ACTIVE, BILLING_STATUS_CANCEL_EOC,
    is_entitlement_active,
)
from services.entitlements.registry import (
    FEATURE_KEYS, FEATURE_REGISTRY, resolve_stripe_price_id,
)
from services.entitlements.stripe_ops import (
    NoActiveSubscriptionError, StripeFeatureError,
    add_feature_item_to_subscription,
    fetch_subscription_period_end,
    schedule_feature_item_cancel_at_period_end,
)
from utils import require_admin


log = logging.getLogger("feature_marketplace")
router = APIRouter(tags=["feature-marketplace"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _load_entitlement(tenant_id: str, feature_key: str) -> Optional[Dict[str, Any]]:
    return await db.feature_entitlements.find_one(
        {"tenant_id": tenant_id, "feature_key": feature_key},
        {"_id": 0},
    )


def _availability(feature_key: str, doc: Optional[Dict[str, Any]]) -> str:
    """Compute the ``availability`` field the UI renders as the
    status pill."""
    if is_entitlement_active(doc):
        return "already_enabled"
    if not resolve_stripe_price_id(feature_key):
        return "not_configured"
    return "available"


def _serialize(feature_key: str, doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    feat = FEATURE_REGISTRY[feature_key]
    doc = doc or {}
    return {
        "feature_key":        feature_key,
        "display_name":       feat["display_name"],
        "description":        feat["description"],
        "monthly_price_cents": feat["monthly_price_cents"],
        "billing_cadence":    feat["billing_cadence"],
        "icon":               feat.get("icon"),
        "enabled":            bool(doc.get("enabled")),
        "billing_status":     doc.get("billing_status"),
        "cancels_at":         doc.get("cancels_at"),
        "enabled_at":         doc.get("enabled_at"),
        "availability":       _availability(feature_key, doc),
    }


async def _write_audit(*, tenant_id: str, feature_key: str, event: str,
                        user_id: str, extra: Optional[Dict[str, Any]] = None):
    try:
        await db.audit_logs.insert_one({
            "id":            str(uuid.uuid4()),
            "tenant_id":     tenant_id,
            "event":         event,       # feature_enabled | feature_disabled
            "feature_key":   feature_key,
            "actor_user_id": user_id,
            "at":            _now_iso(),
            "created_at":    _now_iso(),
            **(extra or {}),
        })
    except Exception as exc:  # pragma: no cover — audit best-effort
        log.warning(
            "[feature-marketplace] audit insert failed tenant=%s feat=%s err=%s",
            tenant_id, feature_key, exc,
        )


# ─── GET marketplace list ────────────────────────────────────────
@router.get("/tenants/mine/feature-marketplace")
async def list_marketplace(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    out: List[Dict[str, Any]] = []
    for feature_key in FEATURE_KEYS:
        doc = await _load_entitlement(tenant["id"], feature_key)
        out.append(_serialize(feature_key, doc))
    return {"features": out}


# ─── POST enable ─────────────────────────────────────────────────
@router.post("/tenants/mine/feature-marketplace/{feature_key}/enable")
async def enable_feature(
    feature_key: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    if feature_key not in FEATURE_REGISTRY:
        raise HTTPException(status_code=404, detail={
            "detail": "feature_not_found",
            "feature_key": feature_key,
            "message": f"unknown feature '{feature_key}'",
        })
    tenant_id = tenant["id"]
    existing = await _load_entitlement(tenant_id, feature_key)
    # Idempotency — already active + not scheduled to cancel → 200
    # with the existing state, no new Stripe call.
    if existing and is_entitlement_active(existing) and \
            existing.get("billing_status") == BILLING_STATUS_ACTIVE:
        return {
            "status": "already_enabled",
            **_serialize(feature_key, existing),
        }
    price_id = resolve_stripe_price_id(feature_key)
    if not price_id:
        raise HTTPException(status_code=503, detail={
            "detail": "feature_not_configured",
            "feature_key": feature_key,
            "message": (
                f"Stripe price ID for '{feature_key}' is not "
                "configured. Contact ops to enable this add-on."
            ),
        })
    # Attach Stripe subscription item with immediate proration.
    try:
        stripe_res = await add_feature_item_to_subscription(
            db=db, tenant_id=tenant_id, feature_key=feature_key,
            price_id=price_id,
        )
    except NoActiveSubscriptionError as ex:
        raise HTTPException(status_code=409, detail={
            "detail": "no_active_subscription",
            "message": str(ex),
        })
    except StripeFeatureError as ex:
        raise HTTPException(status_code=502, detail={
            "detail": "stripe_error",
            "message": ex.message,
        })
    now = _now_iso()
    set_doc = {
        "tenant_id":                    tenant_id,
        "feature_key":                  feature_key,
        "enabled":                       True,
        "enabled_at":                   now,
        "enabled_by_user_id":           user.get("id"),
        "billing_status":               BILLING_STATUS_ACTIVE,
        "cancels_at":                   None,
        "stripe_subscription_item_id":  stripe_res.get("stripe_subscription_item_id"),
        "stripe_subscription_id":       stripe_res.get("stripe_subscription_id"),
        "updated_at":                   now,
    }
    insert_doc = {
        "id":         str(uuid.uuid4()),
        "created_at": now,
    }
    await db.feature_entitlements.update_one(
        {"tenant_id": tenant_id, "feature_key": feature_key},
        {"$set": set_doc, "$setOnInsert": insert_doc},
        upsert=True,
    )
    await _write_audit(
        tenant_id=tenant_id, feature_key=feature_key,
        event="feature_enabled", user_id=user.get("id"),
        extra={
            "stripe_subscription_item_id":
                stripe_res.get("stripe_subscription_item_id"),
            "sandbox": stripe_res.get("sandbox"),
        },
    )
    doc = await _load_entitlement(tenant_id, feature_key)
    return {"status": "enabled", **_serialize(feature_key, doc)}


# ─── POST disable ────────────────────────────────────────────────
@router.post("/tenants/mine/feature-marketplace/{feature_key}/disable")
async def disable_feature(
    feature_key: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    if feature_key not in FEATURE_REGISTRY:
        raise HTTPException(status_code=404, detail={
            "detail": "feature_not_found",
            "feature_key": feature_key,
        })
    tenant_id = tenant["id"]
    existing = await _load_entitlement(tenant_id, feature_key)
    if not existing or not existing.get("enabled"):
        raise HTTPException(status_code=409, detail={
            "detail": "feature_not_enabled",
            "message": (
                f"Feature '{feature_key}' is not currently enabled "
                "for this tenant."
            ),
        })
    # Idempotency — already scheduled to cancel → 200 with state.
    if existing.get("billing_status") == BILLING_STATUS_CANCEL_EOC:
        return {
            "status": "already_scheduled",
            **_serialize(feature_key, existing),
        }
    item_id = existing.get("stripe_subscription_item_id")
    try:
        result = await schedule_feature_item_cancel_at_period_end(
            db=db, tenant_id=tenant_id, feature_key=feature_key,
            stripe_subscription_item_id=item_id or "",
        )
    except StripeFeatureError as ex:
        raise HTTPException(status_code=502, detail={
            "detail": "stripe_error",
            "message": ex.message,
        })
    cancels_at = result.get("cancels_at") or \
                    await fetch_subscription_period_end(db=db, tenant_id=tenant_id)
    now = _now_iso()
    await db.feature_entitlements.update_one(
        {"tenant_id": tenant_id, "feature_key": feature_key},
        {"$set": {
            # ``enabled=True`` deliberately preserved — the tenant
            # keeps ACCESS through the current billing cycle. The
            # ``is_entitlement_active`` check enforces the
            # ``cancels_at`` cutoff at read time. Downstream
            # feature guards treat this state as granted.
            "enabled":              True,
            "billing_status":       BILLING_STATUS_CANCEL_EOC,
            "cancels_at":           cancels_at,
            "disabled_by_user_id":  user.get("id"),
            "updated_at":           now,
        }},
    )
    await _write_audit(
        tenant_id=tenant_id, feature_key=feature_key,
        event="feature_disabled", user_id=user.get("id"),
        extra={"cancels_at": cancels_at, "sandbox": result.get("sandbox")},
    )
    doc = await _load_entitlement(tenant_id, feature_key)
    return {"status": "scheduled_cancel", **_serialize(feature_key, doc)}


# ─── GET audit (last 20) ─────────────────────────────────────────
@router.get("/tenants/mine/feature-marketplace/{feature_key}/audit")
async def feature_audit(
    feature_key: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    if feature_key not in FEATURE_REGISTRY:
        raise HTTPException(status_code=404, detail={
            "detail": "feature_not_found",
            "feature_key": feature_key,
        })
    cursor = (
        db.audit_logs.find(
            {
                "tenant_id":   tenant["id"],
                "feature_key": feature_key,
                "event": {"$in": ["feature_enabled", "feature_disabled"]},
            },
            {"_id": 0},
        )
        .sort("created_at", -1)
        .limit(20)
    )
    rows = [r async for r in cursor]
    return {"rows": rows, "feature_key": feature_key}
