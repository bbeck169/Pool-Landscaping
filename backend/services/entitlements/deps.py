"""Sprint 3c · Feb-2026 — FastAPI dependency wrappers for feature guards.

Two dependency factories:

    * :func:`require_feature(feature_key)` — pure entitlement gate.
      Raises 402 ``feature_not_enabled`` when
      :func:`services.entitlements.check.has_feature` returns False.
      Used at every write / consume boundary for the three
      pure-entitlement features (``zillow_data``, ``seo_heatmap``,
      ``ai_copilot``).
    * :func:`require_ai_analytics` — layered gate. Sprint 3c note
      5a explicitly requires **AND** of the pre-existing org toggle
      (``settings.ai.analytics_enabled``) and the entitlement.
      Neither collapses into the other:
          * ``allowed = analytics_enabled AND has_feature("ai_analytics")``
      The 402 body carries ``org_toggle_state`` so the frontend can
      distinguish "org disabled" from "not purchased" and render
      distinct messaging.

Both helpers depend on ``get_current_tenant`` from
``routers.tenants`` — never invoke them without an authenticated
FastAPI dep chain.
"""
from __future__ import annotations

from typing import Any, Callable, Dict

from fastapi import Depends, HTTPException

from config import db
from routers.tenants import get_current_tenant
from services.entitlements.check import (
    ai_analytics_effective_gate, has_feature,
)


def require_feature(feature_key: str) -> Callable:
    """Build a FastAPI dependency that guards an endpoint with a
    pure entitlement check. Returns the tenant dict on success so
    downstream handlers can use it without re-declaring the dep.

    Usage::

        @router.post(
            "/seo/rank-heatmaps",
            dependencies=[Depends(require_feature("seo_heatmap"))],
        )
    """
    async def _dep(
        tenant: Dict[str, Any] = Depends(get_current_tenant),
    ) -> Dict[str, Any]:
        ok = await has_feature(tenant["id"], feature_key, db=db)
        if not ok:
            raise HTTPException(status_code=402, detail={
                "detail":      "feature_not_enabled",
                "code":        "feature_not_enabled",
                "feature_key": feature_key,
                "message": (
                    f"The '{feature_key}' add-on is not enabled for "
                    "this tenant. Enable it from Organization "
                    "Settings → Feature Marketplace."
                ),
            })
        return tenant
    return _dep


async def require_ai_analytics(
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Layered AI Analytics guard per Sprint 3c note 5a.

    Access is ``AND`` of:
        * ``settings.ai.analytics_enabled`` — pre-existing org
          toggle (Ticket #4 · ``AIConfigurationSettings``).
        * ``has_feature("ai_analytics")``   — billing entitlement.

    Both layers must be true. The 402 response body distinguishes
    the two failure modes via ``code`` (``feature_not_enabled`` vs
    ``org_toggle_disabled``) so the frontend can render distinct
    messaging (upgrade CTA vs "flip the toggle" hint).
    """
    result = await ai_analytics_effective_gate(
        tenant["id"], db=db,
    )
    if result.get("allowed"):
        return tenant
    code = result.get("code") or "feature_not_enabled"
    raise HTTPException(status_code=402, detail={
        "detail":            code,
        "code":              code,
        "feature_key":       "ai_analytics",
        "org_toggle_state":  bool(result.get("org_toggle_state")),
        "message": (
            "AI Analytics is not enabled. Enable the add-on in the "
            "Feature Marketplace AND turn on the analytics toggle "
            "in Organization Settings → AI Configuration."
        ) if code == "feature_not_enabled" else (
            "AI Analytics is purchased but the org-level toggle is "
            "off. Turn it on in Organization Settings → AI "
            "Configuration."
        ),
    })
