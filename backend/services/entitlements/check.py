"""Sprint 3c · Feb-2026 — Feature entitlement access check.

``has_feature(tenant_id, feature_key)`` is the sole public
predicate.  Semantics:

* ``billing_status="active"`` + ``enabled=true``  → **granted**.
* ``billing_status="cancelled_end_of_cycle"`` + ``enabled=true``
  + ``cancels_at > now()``                        → **granted**
  (tenant paid for the current cycle; access continues until
  ``cancels_at``).
* Everything else (missing row, ``enabled=false``, ``cancels_at``
  in the past, ``billing_status="pending_stripe"``) → **denied**.

``ai_analytics_effective_gate(tenant_id, tenant_doc)`` layers
``settings.ai.analytics_enabled`` on top of the entitlement per
Sprint 3c brief · Note 5a. Access is ``AND`` of the two layers —
neither collapses into the other.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

log = logging.getLogger("entitlements.check")


BILLING_STATUS_ACTIVE = "active"
BILLING_STATUS_PENDING = "pending_stripe"
BILLING_STATUS_CANCEL_EOC = "cancelled_end_of_cycle"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cancels_at_in_future(doc: Dict[str, Any]) -> bool:
    ca = doc.get("cancels_at")
    if not ca:
        return False
    try:
        stamp = datetime.fromisoformat(str(ca).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp > datetime.now(timezone.utc)


def is_entitlement_active(doc: Optional[Dict[str, Any]]) -> bool:
    """Pure predicate used by :func:`has_feature` and unit tests."""
    if not isinstance(doc, dict):
        return False
    if not bool(doc.get("enabled")):
        return False
    status = str(doc.get("billing_status") or "").strip().lower()
    if status == BILLING_STATUS_ACTIVE:
        return True
    if status == BILLING_STATUS_CANCEL_EOC:
        # Access continues until ``cancels_at``.
        return _cancels_at_in_future(doc)
    return False


async def has_feature(
    tenant_id: Optional[str], feature_key: str, db=None,
) -> bool:
    """Return True iff the tenant currently has access to the
    named feature. ``tenant_id=None`` always returns False (defensive
    — matches the deny-by-default posture at other feature guards)."""
    if not tenant_id or not feature_key:
        return False
    if db is None:
        from config import db as _db
        db = _db
    doc = await db.feature_entitlements.find_one(
        {"tenant_id": tenant_id, "feature_key": feature_key},
        {"_id": 0},
    )
    return is_entitlement_active(doc)


async def ai_analytics_effective_gate(
    tenant_id: Optional[str],
    tenant_doc: Optional[Dict[str, Any]] = None,
    db=None,
) -> Dict[str, Any]:
    """Layered gate for the ``ai_analytics`` feature per Sprint 3c
    brief · Note 5a.

    Access = ``settings.ai.analytics_enabled`` AND
             ``has_feature("ai_analytics")``.

    ``settings.ai.analytics_enabled`` is the pre-existing org
    toggle (Ticket #4). It expresses **intent to use** (an admin
    switched analytics ON at the org level). The entitlement
    layer expresses **paid-for access** (billing is current).
    Neither collapses into the other:

    * A tenant that hasn't purchased AI Analytics still sees the
      org toggle in ``AIConfigurationSettings`` (they might toggle
      it on in anticipation of buying).
    * A tenant that purchased but toggled analytics OFF sees a
      soft "you own this, flip the toggle to use it" state.

    Returns ``{allowed: bool, code?: str, org_toggle_state: bool}``
    so the caller can surface a 402 body that differentiates
    "org disabled" from "not purchased" per Sprint 3c note 5a.
    """
    if db is None:
        from config import db as _db
        db = _db
    if tenant_doc is None and tenant_id:
        tenant_doc = await db.tenants.find_one(
            {"id": tenant_id},
            {"_id": 0, "settings.ai.analytics_enabled": 1},
        ) or {}
    toggle = bool(
        (((tenant_doc or {}).get("settings") or {}).get("ai") or {})
        .get("analytics_enabled")
    )
    entitled = await has_feature(tenant_id, "ai_analytics", db=db)
    if entitled and toggle:
        return {"allowed": True, "org_toggle_state": toggle}
    if not entitled:
        return {
            "allowed": False,
            "code": "feature_not_enabled",
            "org_toggle_state": toggle,
        }
    # entitled but org toggle off
    return {
        "allowed": False,
        "code": "org_toggle_disabled",
        "org_toggle_state": toggle,
    }
