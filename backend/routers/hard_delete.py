"""HARD-DELETE · Sub-phase HD-A · Feb 2026 — the /api/hard-delete/* router.

Two-step delete + Trash + tombstone + nightly purge.

Endpoints
---------
* POST   /api/hard-delete/{entity_type}/{id}/soft     — admin/super
* POST   /api/hard-delete/{entity_type}/{id}/restore  — admin/super
* POST   /api/hard-delete/{entity_type}/{id}/purge    — super only
* GET    /api/hard-delete/trash                       — admin/super
* GET    /api/hard-delete/tombstones                  — super only
* POST   /api/hard-delete/admin/run-nightly-purge     — super only
* GET    /api/hard-delete/admin/nightly-purge/dry-run — super only

The router imposes tenant scoping on every read/write; a tenant-A
admin cannot list, restore, or purge tenant-B rows.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from routers.tenants import get_current_tenant
from services.hard_delete.cascade import (
    purge_cascade, restore_batch, soft_delete_cascade,
)
from services.hard_delete.nightly_purge import dry_run, run_nightly_purge
from services.hard_delete.preview import preview_cascade
from services.hard_delete.query_filter import only_trashed_filter
from services.hard_delete.registry import (
    ELIGIBLE_COLLECTIONS, all_specs, get_spec,
)
from utils import get_current_user

router = APIRouter(prefix="/hard-delete", tags=["hard-delete"])


# ─── Role helpers ───────────────────────────────────────────────────
# HD-A per user brief §3 has TWO role bands:
#   * soft / restore / trash-list → admin OR super_admin
#   * purge (skip_trash true or false) → super_admin ONLY
# The pre-existing require_admin() in utils.py accepts owner/admin/
# super_admin — that's the widest legal band for HD-A/soft, so we
# inline a stricter admin+super gate here that excludes owner
# (which isn't relevant to this platform's HD-A brief anyway).

_SOFT_RESTORE_ROLES = {"admin", "super_admin"}
_PURGE_ROLES = {"super_admin"}


def _require_soft_restore_role(user: dict) -> dict:
    role = (user.get("role") or "").lower()
    if role not in _SOFT_RESTORE_ROLES:
        raise HTTPException(
            status_code=403,
            detail={"error_code": "forbidden",
                     "message": "Admin or super-admin required"},
        )
    return user


def _require_purge_role(user: dict) -> dict:
    role = (user.get("role") or "").lower()
    if role not in _PURGE_ROLES:
        raise HTTPException(
            status_code=403,
            detail={"error_code": "forbidden",
                     "message": "Super-admin required for hard purge"},
        )
    return user


def _resolve_spec(entity_type: str) -> Any:
    spec = get_spec(entity_type)
    if not spec:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "unsupported_entity_type",
                "message": f"entity_type {entity_type!r} is not managed by HD-A",
                "supported": [s.entity_type for s in all_specs()],
            },
        )
    return spec


# ─── Request models ─────────────────────────────────────────────────

class SoftDeleteBody(BaseModel):
    """Optional body payload for POST /soft — reason string."""
    reason: Optional[str] = Field(
        default=None, max_length=500,
        description="Free-text note stapled to the audit log entry.",
    )


class PurgeBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)
    skip_trash: bool = Field(
        default=False,
        description=(
            "Super-admin escape hatch — purge the doc even if it "
            "hasn't been through Trash. Skips the "
            "``trash_required`` guard."
        ),
    )


# ─── SOFT DELETE ────────────────────────────────────────────────────


# ─── PREVIEW CASCADE (HD-B) ─────────────────────────────────────────

@router.post("/{entity_type}/{doc_id}/preview-cascade")
async def preview_cascade_endpoint(
    entity_type: str,
    doc_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Read-only cascade preview.

    Returns descendant counts + external refs WITHOUT mutating any
    state. Wired to the FE's entity-detail-page HardDeleteModal so
    admins see exactly what the /soft call will affect before
    confirming.
    """
    _require_soft_restore_role(user)
    spec = _resolve_spec(entity_type)
    result = await preview_cascade(
        spec.entity_type, doc_id, tenant["id"],
    )
    if result.get("error_code") == "not_found":
        raise HTTPException(
            status_code=404,
            detail={"error_code": "not_found",
                     "entity_type": spec.entity_type, "id": doc_id},
        )
    return {"ok": True, **result}


# ─── SOFT DELETE ────────────────────────────────────────────────────

@router.post("/{entity_type}/{doc_id}/soft")
async def soft_delete_endpoint(
    entity_type: str,
    doc_id: str,
    body: Optional[SoftDeleteBody] = None,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_soft_restore_role(user)
    spec = _resolve_spec(entity_type)

    result = await soft_delete_cascade(
        spec.entity_type, doc_id, tenant["id"],
        user_id=user.get("id"),
    )
    if result.get("not_found"):
        raise HTTPException(
            status_code=404,
            detail={"error_code": "not_found",
                     "entity_type": spec.entity_type, "id": doc_id},
        )

    # Audit log — same collection legacy hard-delete uses so
    # forensic tooling has one place to grep.
    try:
        from utils import new_id, now_iso
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "event": f"hard_delete.soft.{spec.entity_type}",
            "actor_id": user.get("id"),
            "actor_email": user.get("email"),
            "actor_role": (user.get("role") or "").lower(),
            "entity_type": spec.entity_type,
            "entity_id": doc_id,
            "cascade_batch_id": result.get("cascade_batch_id"),
            "affected_counts": {
                k: len(v) for k, v in (result.get("affected") or {}).items()
            },
            "reason": (body.reason if body else None),
            "created_at": now_iso(),
        })
    except Exception:                                              # noqa: BLE001
        logger.exception("[hard_delete.soft] audit insert failed")
    return {"ok": True, **result}


# ─── RESTORE ────────────────────────────────────────────────────────

@router.post("/{entity_type}/{doc_id}/restore")
async def restore_endpoint(
    entity_type: str,
    doc_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_soft_restore_role(user)
    spec = _resolve_spec(entity_type)

    result = await restore_batch(spec.entity_type, doc_id, tenant["id"])
    if result.get("not_found"):
        raise HTTPException(
            status_code=404,
            detail={"error_code": "not_found",
                     "entity_type": spec.entity_type, "id": doc_id},
        )
    try:
        from utils import new_id, now_iso
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "event": f"hard_delete.restore.{spec.entity_type}",
            "actor_id": user.get("id"),
            "actor_email": user.get("email"),
            "actor_role": (user.get("role") or "").lower(),
            "entity_type": spec.entity_type,
            "entity_id": doc_id,
            "cascade_batch_id": result.get("cascade_batch_id"),
            "restored_counts": {
                k: len(v) for k, v in (result.get("restored") or {}).items()
            },
            "created_at": now_iso(),
        })
    except Exception:                                              # noqa: BLE001
        logger.exception("[hard_delete.restore] audit insert failed")
    return {"ok": True, **result}


# ─── PURGE ──────────────────────────────────────────────────────────

@router.post("/{entity_type}/{doc_id}/purge")
async def purge_endpoint(
    entity_type: str,
    doc_id: str,
    body: Optional[PurgeBody] = None,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_purge_role(user)
    spec = _resolve_spec(entity_type)

    body = body or PurgeBody()
    result, blocks = await purge_cascade(
        spec.entity_type, doc_id, tenant["id"],
        user_id=user.get("id"),
        user_email=user.get("email"),
        purge_reason=body.reason,
        skip_trash=body.skip_trash,
    )
    if result.get("not_found"):
        raise HTTPException(
            status_code=404,
            detail={"error_code": "not_found",
                     "entity_type": spec.entity_type, "id": doc_id},
        )
    if result.get("trash_required"):
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "trash_required",
                "message": (
                    "Doc has not been soft-deleted — call /soft first, "
                    "or pass skip_trash=true (super-admin only)."
                ),
                "entity_type": spec.entity_type,
                "id": doc_id,
            },
        )
    if blocks:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "blocked_external_reference",
                "message": (
                    "One or more descendants carry a Stripe "
                    "payment_intent_id — refund/void via Stripe first."
                ),
                "refs": blocks,
                "entity_type": spec.entity_type,
                "id": doc_id,
            },
        )
    # Purge succeeded — record the audit row.  The tombstones are
    # already immutable evidence; this is the operator-facing
    # timeline.
    try:
        from utils import new_id, now_iso
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "event": f"hard_delete.purge.{spec.entity_type}",
            "actor_id": user.get("id"),
            "actor_email": user.get("email"),
            "actor_role": (user.get("role") or "").lower(),
            "entity_type": spec.entity_type,
            "entity_id": doc_id,
            "cascade_batch_id": result.get("cascade_batch_id"),
            "purged_counts": {
                k: len(v) for k, v in (result.get("purged") or {}).items()
            },
            "reason": body.reason,
            "skip_trash": body.skip_trash,
            "created_at": now_iso(),
        })
    except Exception:                                              # noqa: BLE001
        logger.exception("[hard_delete.purge] audit insert failed")
    return {"ok": True, **result}


# ─── TRASH VIEW ─────────────────────────────────────────────────────

@router.get("/trash")
async def list_trash(
    entity_type: Optional[str] = Query(
        None,
        description="Filter to one entity type (customer/job/quote/…).",
    ),
    limit: int = Query(200, ge=1, le=1000),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_soft_restore_role(user)

    specs = ([get_spec(entity_type)] if entity_type else all_specs())
    if not all(specs):
        raise HTTPException(
            status_code=400,
            detail={"error_code": "unsupported_entity_type",
                     "supported": [s.entity_type for s in all_specs()]},
        )

    out: List[Dict[str, Any]] = []
    for spec in specs:
        q = only_trashed_filter(
            {"tenant_id": tenant["id"]}, collection=spec.collection,
        )
        cursor = db[spec.collection].find(
            q,
            {"_id": 0, "id": 1, "deleted_at": 1, "deleted_by_user_id": 1,
             "cascade_batch_id": 1, "cascade_role": 1,
             # Convenience labels — union of common name-ish fields.
             "name": 1, "title": 1, "invoice_number": 1,
             "doc_type": 1, "quote_number": 1, "filename": 1,
             "customer_id": 1, "job_id": 1},
        ).sort([("deleted_at", -1)]).limit(limit)
        async for row in cursor:
            row["entity_type"] = spec.entity_type
            row["_collection"] = spec.collection
            out.append(row)

    # Overall sort by most-recent first so a single-view scan is
    # chronological across entity types.
    out.sort(key=lambda r: r.get("deleted_at") or "", reverse=True)
    return {"count": len(out), "items": out,
            "supported_entity_types": [s.entity_type for s in all_specs()]}


# ─── TOMBSTONES ─────────────────────────────────────────────────────

@router.get("/tombstones")
async def list_tombstones(
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_purge_role(user)

    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if entity_type:
        q["entity_type"] = entity_type
    if entity_id:
        q["entity_id"] = entity_id
    cursor = db.hard_delete_tombstones.find(q, {"_id": 0}).sort(
        [("purged_at", -1)],
    ).limit(limit)
    rows = await cursor.to_list(limit)
    return {"count": len(rows), "items": rows}


# ─── NIGHTLY PURGE ─────────────────────────────────────────────────

@router.get("/admin/nightly-purge/dry-run")
async def nightly_dry_run(
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_purge_role(user)
    return await dry_run()


@router.post("/admin/run-nightly-purge")
async def nightly_run(
    days: Optional[int] = Query(
        None, description="Override HARD_DELETE_PURGE_AFTER_DAYS (default 30).",
    ),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_purge_role(user)
    return await run_nightly_purge(days=days)


# ─── DIAGNOSTICS ───────────────────────────────────────────────────

@router.get("/registry")
async def show_registry(
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return the entity registry — useful for the FE to render
    entity-type tabs on the Trash page."""
    _require_soft_restore_role(user)
    return {
        "supported": [
            {
                "entity_type": s.entity_type,
                "collection": s.collection,
                "label": s.label,
                "children": [
                    {"collection": r.collection,
                      "parent_field": r.parent_field,
                      "entity_type": r.entity_type}
                    for r in s.children_specs
                ],
            }
            for s in all_specs()
        ],
        "eligible_collections": ELIGIBLE_COLLECTIONS,
    }
