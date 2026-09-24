"""Sprint 3c wrap-up · Feb-2026 — Super-admin cross-tenant entitlement ops.

Currently exposes:
    * ``POST /api/admin/entitlements/{tenant_id}/{feature_key}/force-off``
      — Immediate entitlement revocation for ops (chargebacks, TOS
      violations, mistaken enables). Attempts a synchronous Stripe
      cleanup; on failure the local revocation still persists (403
      access is the priority; Stripe cleanup is a follow-up).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from config import db
from routers.tenants import get_current_tenant
from services.entitlements.check import (
    BILLING_STATUS_CANCEL_IMMEDIATE, BILLING_STATUS_MANUAL_OVERRIDE,
    is_entitlement_active,
)
from services.entitlements.registry import FEATURE_REGISTRY
from services.entitlements.stripe_ops import (
    _sandbox_mode, StripeFeatureError,
)
from utils import get_current_user


log = logging.getLogger("admin_entitlements")
router = APIRouter(tags=["admin-entitlements"])


def _require_super_admin(user: Dict[str, Any]) -> None:
    role = (user.get("role") or "").lower()
    if role != "super_admin":
        raise HTTPException(status_code=403, detail={
            "detail": "super_admin_required",
            "message": "This action requires super_admin.",
        })


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ForceOffIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Optional[str] = None


class ForceOnIn(BaseModel):
    """Task J · Commit 3 · Feb-2026 — super_admin force-on body.

    ``bypass_billing`` is an acknowledgement gate: the caller must
    explicitly pass ``true`` to proceed. This exists so an ops
    engineer can never accidentally comp a feature without
    signalling that they know they're bypassing the Stripe flow.
    """
    model_config = ConfigDict(extra="forbid")
    bypass_billing: bool = False
    reason: Optional[str] = None


async def _stripe_immediate_delete(
    *, tenant_id: str, feature_key: str, item_id: str,
) -> Dict[str, Any]:
    """Best-effort Stripe cleanup: delete the subscription item
    immediately (with proration credit). Returns
    ``{"cleanup_status": "success"|"failed"|"skipped", "detail": ...}``.

    Never raises — the caller expects a report, not an exception.
    Real-Stripe failures do NOT block the local force-off write.
    """
    if not item_id:
        return {"cleanup_status": "skipped",
                "detail": "no stripe_subscription_item_id on record"}
    if _sandbox_mode() or item_id.startswith("si_sandbox_"):
        log.info(
            "[admin-entitlements] sandbox immediate delete tenant=%s "
            "feature=%s item=%s", tenant_id, feature_key, item_id,
        )
        return {"cleanup_status": "success",
                "detail": "sandbox", "sandbox": True}
    try:
        from services.payments.stripe_charge import (
            _init_api_key, _mode, _stripe, _to_thread,
        )
        _init_api_key()
        await _to_thread(
            _stripe.SubscriptionItem.delete,
            item_id,
            proration_behavior="create_prorations",
            idempotency_key=f"ent_force_off:{_mode()}:{tenant_id}:{feature_key}",
        )
        return {"cleanup_status": "success",
                "detail": "stripe_subscription_item deleted"}
    except Exception as exc:                                       # noqa: BLE001
        log.warning(
            "[admin-entitlements] Stripe force-off cleanup failed "
            "tenant=%s feature=%s item=%s err=%s: %s",
            tenant_id, feature_key, item_id, type(exc).__name__, exc,
        )
        return {
            "cleanup_status": "failed",
            "detail": f"{type(exc).__name__}: {str(exc)[:200]}",
        }


@router.post(
    "/admin/entitlements/{tenant_id}/{feature_key}/force-off",
    operation_id="admin.entitlements.force_off",
    summary="Sprint 3c · Immediate entitlement revocation (super_admin)",
)
async def force_off_entitlement(
    tenant_id: str,
    feature_key: str,
    body: Optional[ForceOffIn] = None,
    user: Dict[str, Any] = Depends(get_current_user),
    _caller_tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    """Force an entitlement to immediate-off. Sets
    ``enabled=false``, ``billing_status="cancelled_immediate"``,
    ``cancels_at=now()``, and attempts to delete the Stripe
    subscription item synchronously.

    Response:
        ``{status, feature_key, tenant_id, stripe_cleanup_status,
           stripe_cleanup_detail?, entitlement}``

    Idempotent: calling twice returns 200 with the existing
    force-off state on the second call.
    """
    _require_super_admin(user)
    if feature_key not in FEATURE_REGISTRY:
        raise HTTPException(status_code=404, detail={
            "detail": "feature_not_found", "feature_key": feature_key,
        })
    # Confirm the target tenant exists — avoids silently no-op'ing.
    target = await db.tenants.find_one({"id": tenant_id}, {"_id": 0, "id": 1})
    if not target:
        raise HTTPException(status_code=404, detail={
            "detail": "tenant_not_found", "tenant_id": tenant_id,
        })
    existing = await db.feature_entitlements.find_one(
        {"tenant_id": tenant_id, "feature_key": feature_key},
        {"_id": 0},
    )
    # Idempotency — already force-off. Return current state.
    if existing and existing.get("billing_status") == BILLING_STATUS_CANCEL_IMMEDIATE:
        return {
            "status":                  "already_forced_off",
            "feature_key":             feature_key,
            "tenant_id":               tenant_id,
            "stripe_cleanup_status":   "skipped",
            "stripe_cleanup_detail":   "already force-off; no cleanup attempted",
            "entitlement":             existing,
        }
    item_id = (existing or {}).get("stripe_subscription_item_id") or ""
    cleanup = await _stripe_immediate_delete(
        tenant_id=tenant_id, feature_key=feature_key, item_id=item_id,
    )
    now = _now_iso()
    set_doc = {
        "tenant_id":            tenant_id,
        "feature_key":          feature_key,
        "enabled":              False,
        "billing_status":       BILLING_STATUS_CANCEL_IMMEDIATE,
        "cancels_at":           now,
        "disabled_by_user_id":  user.get("id"),
        "updated_at":           now,
    }
    await db.feature_entitlements.update_one(
        {"tenant_id": tenant_id, "feature_key": feature_key},
        {
            "$set": set_doc,
            "$setOnInsert": {
                "id":         str(uuid.uuid4()),
                "created_at": now,
            },
        },
        upsert=True,
    )
    try:
        await db.audit_logs.insert_one({
            "id":            str(uuid.uuid4()),
            "tenant_id":     tenant_id,
            "event":         "feature_force_off",
            "feature_key":   feature_key,
            "actor_user_id": user.get("id"),
            "reason":        (body.reason if body else None),
            "stripe_cleanup_status": cleanup.get("cleanup_status"),
            "at":            now,
            "created_at":    now,
        })
    except Exception as exc:  # pragma: no cover — audit is best-effort
        log.warning(
            "[admin-entitlements] audit insert failed tenant=%s feat=%s err=%s",
            tenant_id, feature_key, exc,
        )
    doc = await db.feature_entitlements.find_one(
        {"tenant_id": tenant_id, "feature_key": feature_key},
        {"_id": 0},
    )
    return {
        "status":                  "forced_off",
        "feature_key":             feature_key,
        "tenant_id":               tenant_id,
        "stripe_cleanup_status":   cleanup.get("cleanup_status"),
        "stripe_cleanup_detail":   cleanup.get("detail"),
        "entitlement":             doc,
    }


@router.post(
    "/admin/entitlements/{tenant_id}/{feature_key}/force-on",
    operation_id="admin.entitlements.force_on",
    summary="Task J · Immediate entitlement force-on (super_admin)",
)
async def force_on_entitlement(
    tenant_id: str,
    feature_key: str,
    body: Optional[ForceOnIn] = None,
    user: Dict[str, Any] = Depends(get_current_user),
    _caller_tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    """Force an entitlement to immediate-on. Sets
    ``enabled=true``, ``billing_status="manual_override"``,
    ``enabled_at=now()``, ``enabled_by=<caller user_id>``, and
    ``enabled_reason=<body.reason>``. Preserves any pre-existing
    fields on the row (Stripe subscription IDs, etc.) — the write
    uses ``$set`` only on the fields it owns.

    Guardrail: the caller MUST pass ``bypass_billing=true`` in the
    body. Any other value returns 400. This is an ops acknowledgement
    gate — force-on side-steps the Stripe marketplace flow and the
    caller is expected to know that.

    Idempotent: calling twice on the same ``(tenant_id, feature_key)``
    updates ``enabled_at`` + ``enabled_by`` but does NOT insert a
    duplicate entitlement row. Each call writes ONE audit_log entry
    (audit trail is intentionally NOT idempotent so ops history is
    preserved).

    Response:
        ``{status, feature_key, tenant_id, entitlement}``
    """
    _require_super_admin(user)
    if feature_key not in FEATURE_REGISTRY:
        # Matches force-off's :124 behaviour. Symmetric API; the
        # FEATURE_REGISTRY is source-of-truth for known features
        # and writing arbitrary keys would produce ghost rows that
        # no has_feature() check will ever consume.
        raise HTTPException(status_code=404, detail={
            "detail": "feature_not_found", "feature_key": feature_key,
        })
    payload = body or ForceOnIn()
    if payload.bypass_billing is not True:
        raise HTTPException(status_code=400, detail=(
            "Force-on bypasses billing; pass bypass_billing=true "
            "to acknowledge."
        ))
    target = await db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0, "id": 1},
    )
    if not target:
        raise HTTPException(status_code=404, detail={
            "detail": "tenant_not_found", "tenant_id": tenant_id,
        })
    now = _now_iso()
    set_doc = {
        "tenant_id":       tenant_id,
        "feature_key":     feature_key,
        "enabled":         True,
        "billing_status":  BILLING_STATUS_MANUAL_OVERRIDE,
        "enabled_at":      now,
        "enabled_by":      user.get("id"),
        "enabled_reason":  payload.reason,
        # Clear any stale cancel marker so the row is coherent
        # after being flipped back on. is_entitlement_active
        # doesn't consult cancels_at for MANUAL_OVERRIDE rows,
        # but leaving a stale ISO string around is a footgun for
        # ops dashboards.
        "cancels_at":      None,
        "updated_at":      now,
    }
    await db.feature_entitlements.update_one(
        {"tenant_id": tenant_id, "feature_key": feature_key},
        {
            "$set":         set_doc,
            "$setOnInsert": {
                "id":         str(uuid.uuid4()),
                "created_at": now,
            },
        },
        upsert=True,
    )
    try:
        await db.audit_logs.insert_one({
            "id":              str(uuid.uuid4()),
            "tenant_id":       tenant_id,
            "event":           "feature_force_on",
            "feature_key":     feature_key,
            "actor_user_id":   user.get("id"),
            "reason":          payload.reason,
            "bypass_billing":  True,
            "at":              now,
            "created_at":      now,
        })
    except Exception as exc:  # pragma: no cover — audit is best-effort
        log.warning(
            "[admin-entitlements] audit insert (force-on) failed "
            "tenant=%s feat=%s err=%s",
            tenant_id, feature_key, exc,
        )
    doc = await db.feature_entitlements.find_one(
        {"tenant_id": tenant_id, "feature_key": feature_key},
        {"_id": 0},
    )
    return {
        "status":       "forced_on",
        "feature_key":  feature_key,
        "tenant_id":    tenant_id,
        "entitlement":  doc,
    }

