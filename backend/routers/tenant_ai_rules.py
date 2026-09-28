"""MTH-A · Feb-2026 — Per-tenant AI rules router.

All endpoints registered under ``/api/tenant-ai-rules/**`` and
``/api/platform-ai-rules/**``.  Admin + super for the tenant surface;
super only for the platform surface + the master switch.

Every mutation carries a mandatory ``reason`` field (min 8 chars,
HD-A convention) and increments the tenant / platform revision
counter.  Every save invalidates the corresponding cache entry.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import logger
from routers.tenants import get_current_tenant
from utils import require_admin, require_super_admin

from services.tenant_ai_rules import (
    RULE_CATEGORIES,
    ACTION_INVENTORY,
    EMPLOYEE_KEYS,
)
from services.tenant_ai_rules import cache as _cache
from services.tenant_ai_rules import store
from services.tenant_ai_rules.resolver import resolve_rules_for_tenant


router = APIRouter(tags=["Tenant AI Rules"])


# ─── Pydantic bodies ──────────────────────────────────────────────

class CategoryPatch(BaseModel):
    """Body for ``PUT /api/tenant-ai-rules/{category}``.

    ``value`` is validated per-category by
    ``services.tenant_ai_rules.schema.validate_category_payload``.
    """
    value: Any
    reason: str = Field(..., min_length=1)


class ReasonBody(BaseModel):
    reason: str = Field(..., min_length=1)


class MasterSwitchBody(BaseModel):
    enabled: bool
    reason: str = Field(..., min_length=1)


class RevertBody(ReasonBody):
    pass


# ─── Error translation ───────────────────────────────────────────

def _raise_store_error(exc: "store.RuleStoreError") -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={
            "error_code": exc.error_code,
            "message": exc.message,
            **(exc.detail or {}),
        },
    )


# ─── Reads ────────────────────────────────────────────────────────

@router.get("/tenant-ai-rules")
async def get_resolved_rules(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Return resolved rules (tenant ∪ platform) + override_map.

    Admin + super — the FE editor reads this on every render.
    """
    payload = await resolve_rules_for_tenant(tenant["id"])
    payload["action_inventory"] = list(ACTION_INVENTORY)
    payload["employee_keys"] = list(EMPLOYEE_KEYS)
    return payload


@router.get("/tenant-ai-rules/raw")
async def get_raw_rules(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Return the tenant's explicit-override document only (no
    platform-default merge).  Admin + super.  Lazy-init is honoured
    so a first-time tenant still sees the empty-override skeleton.
    """
    row = await store.get_tenant_rules(tenant["id"])
    return row or {}


@router.get("/tenant-ai-rules/revisions")
async def list_tenant_rule_revisions(
    limit: int = 100,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    revisions = await store.list_revisions(tenant["id"], limit=limit)
    return {"count": len(revisions), "revisions": revisions}


# ─── Mutations ────────────────────────────────────────────────────

@router.put("/tenant-ai-rules/master-switch")
async def put_master_switch(
    body: MasterSwitchBody,
    user: dict = Depends(require_super_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Super-only flip of ``master_ai_send_live_comms``.  This is a
    global safety net — misuse can turn every AI-driven comm on for
    a tenant, which is why admin cannot flip it."""
    try:
        doc = await store.save_master_switch(
            tenant["id"], body.enabled,
            actor=user, reason=body.reason,
        )
    except store.RuleStoreError as exc:
        _raise_store_error(exc)
    logger.info(
        "[mth-a] master_switch flip tenant=%s enabled=%s actor=%s "
        "revision=%s",
        tenant["id"], body.enabled, (user or {}).get("email"),
        doc["revision_number"],
    )
    return {
        "ok": True,
        "master_ai_send_live_comms": doc["master_ai_send_live_comms"],
        "revision_number": doc["revision_number"],
    }


@router.put("/tenant-ai-rules/{category}")
async def put_tenant_rule_category(
    category: str, body: CategoryPatch,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    if category not in RULE_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "unknown_category",
                "message": f"unknown rule category {category!r}",
                "allowed": list(RULE_CATEGORIES),
            },
        )
    try:
        doc = await store.save_category(
            tenant["id"], category, body.value,
            actor=user, reason=body.reason,
        )
    except store.RuleStoreError as exc:
        _raise_store_error(exc)
    except Exception as exc:                                     # noqa: BLE001
        # Validation errors (RuleValidationError) inherit ValueError;
        # translate to 400.
        if isinstance(exc, ValueError):
            raise HTTPException(
                status_code=400,
                detail={
                    "error_code": "validation_failed",
                    "message": str(exc),
                    "category": category,
                },
            )
        raise
    return {
        "ok": True,
        "category": category,
        "revision_number": doc["revision_number"],
        "last_updated_at": doc["last_updated_at"],
        "last_update_reason": doc["last_update_reason"],
    }


@router.post("/tenant-ai-rules/reset/{category}")
async def reset_tenant_rule_category(
    category: str, body: ReasonBody,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    if category not in RULE_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "unknown_category",
                "message": f"unknown rule category {category!r}",
                "allowed": list(RULE_CATEGORIES),
            },
        )
    try:
        doc = await store.reset_category(
            tenant["id"], category,
            actor=user, reason=body.reason,
        )
    except store.RuleStoreError as exc:
        _raise_store_error(exc)
    return {
        "ok": True,
        "category": category,
        "revision_number": doc["revision_number"],
        "reset": True,
    }


@router.post("/tenant-ai-rules/revert/{revision_number}")
async def revert_tenant_rules(
    revision_number: int, body: RevertBody,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    try:
        doc = await store.revert_to_revision(
            tenant["id"], revision_number,
            actor=user, reason=body.reason,
        )
    except store.RuleStoreError as exc:
        _raise_store_error(exc)
    return {
        "ok": True,
        "reverted_to": revision_number,
        "revision_number": doc["revision_number"],
    }


# ─── Platform defaults (super-only) ───────────────────────────────

@router.get("/platform-ai-rules")
async def get_platform_defaults(
    user: dict = Depends(require_super_admin),
) -> Dict[str, Any]:
    doc = await store.get_platform_defaults()
    return {
        **doc,
        "action_inventory": list(ACTION_INVENTORY),
        "employee_keys": list(EMPLOYEE_KEYS),
    }


@router.put("/platform-ai-rules/{category}")
async def put_platform_default_category(
    category: str, body: CategoryPatch,
    user: dict = Depends(require_super_admin),
) -> Dict[str, Any]:
    if category not in RULE_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "unknown_category",
                "message": f"unknown rule category {category!r}",
                "allowed": list(RULE_CATEGORIES),
            },
        )
    try:
        doc = await store.save_platform_category(
            category=category, value=body.value,
            actor=user, reason=body.reason,
        )
    except store.RuleStoreError as exc:
        _raise_store_error(exc)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "validation_failed",
                "message": str(exc),
                "category": category,
            },
        )
    return {
        "ok": True,
        "category": category,
        "revision_number": doc["revision_number"],
    }


# ─── Test-only debug ping (not part of the public surface) ────────

@router.get("/tenant-ai-rules/_cache-stats")
async def _cache_stats(
    user: dict = Depends(require_super_admin),
) -> Dict[str, Any]:
    """Super-only introspection for ops.  Reports the in-process
    cache size so operators can confirm invalidation is landing.
    Not part of the FE contract — feel free to move to a diagnostics
    module later."""
    return {"cached_tenants": _cache.size(), "ttl_seconds":
            _cache.TTL_SECONDS}
