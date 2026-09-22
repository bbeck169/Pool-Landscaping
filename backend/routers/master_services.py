"""Phase P16 · Feb-2026 — Master Services (Pricebook).

Lightweight, tenant-scoped catalog of the services the business
offers.  Distinct from ``db.items`` (the full products / labor
catalog) — this collection only holds the flat name + default price
+ category triplets the "Add Recurring Job" combobox writes back
into.  A recurring-job template that references a master service
carries the NAME as a string (not an id) so the reference survives
even if the master row is later soft-deleted; the price is stamped
at create time (materialised, not lazy-joined).

Endpoints (mounted at ``/api/master-services``):
  * ``GET  /api/master-services``          — list + counts aggregate
  * ``POST /api/master-services``          — admin / manager
  * ``PATCH /api/master-services/{id}``    — admin / manager
  * ``DELETE /api/master-services/{id}``   — admin, soft by default;
    ``?hard=true`` with body ``{confirm:"DELETE"}`` writes an audit
    row via :func:`write_deletion_audit_entry`.
  * ``GET /api/master-services/categories`` — distinct category
    names, used by the "+ Add" mini-modal in the combobox.

Category source of truth:
  * The existing ``service_categories`` collection is the authority.
    The master-service ``category`` field carries the category NAME
    (a string) — case-insensitive match on
    ``service_categories.name`` for the current tenant.  Unknown
    names → HTTP 400 ``category_invalid`` on POST + PATCH.
  * The categories helper endpoint returns the same active names
    (name-only projection) so the FE combobox mini-modal can seed
    a dropdown without a second round-trip to
    ``/service-categories``.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import (
    get_current_user,
    new_id,
    now_iso,
    require_admin,
    require_admin_or_manager,
)
from routers.tenants import get_current_tenant
from routers.deletion_audit import write_deletion_audit_entry
from services.query_scope import tenant_scoped_filter


router = APIRouter()

_COLL = "pricebook"


# ─────────────────────────────────────────────────────────────────────
# Category source of truth — service_categories collection.
# ─────────────────────────────────────────────────────────────────────
async def _validate_category_name(
    tenant_id: str, category: Optional[str],
) -> str:
    """Reject if the category doesn't exist (case-insensitive) as a
    non-archived row in the tenant's ``service_categories``
    collection.  Returns the canonical stored NAME (case as saved
    on the category row) so the master service normalises casing.
    """
    name = (category or "").strip()
    if not name:
        raise HTTPException(
            400, {"error": "category_required", "field": "category"},
        )
    row = await db.service_categories.find_one(
        {"tenant_id": tenant_id,
          "is_archived": False,
          "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}},
        {"_id": 0, "name": 1},
    )
    if not row:
        raise HTTPException(
            400, {"error": "category_invalid", "field": "category",
                    "attempted": name},
        )
    return row["name"]


# ─────────────────────────────────────────────────────────────────────
# Pydantic models.
# ─────────────────────────────────────────────────────────────────────
class MasterServiceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    default_price: float = Field(0.0, ge=0)
    category: str = Field(..., min_length=1, max_length=200)


class MasterServiceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    default_price: Optional[float] = Field(None, ge=0)
    category: Optional[str] = Field(None, min_length=1, max_length=200)


# ─────────────────────────────────────────────────────────────────────
# Helpers.
# ─────────────────────────────────────────────────────────────────────
def _shape(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in (doc or {}).items() if k != "_id"}
    return out


async def _find_duplicate_name(
    tenant_id: str, name: str, *, exclude_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return an existing (non-soft-deleted) doc with the same name
    (case-insensitive) if one exists.  Used to enforce the unique
    ``(tenant_id, lower(name))`` constraint on both POST and PATCH.
    """
    q = tenant_scoped_filter(
        tenant_id,
        name={"$regex": f"^{re.escape(name)}$", "$options": "i"},
        is_active=True,
    )
    if exclude_id:
        q["id"] = {"$ne": exclude_id}
    return await db[_COLL].find_one(q, {"_id": 0, "id": 1, "name": 1})


# ═════════════════════════════════════════════════════════════════════
# GET /api/master-services · list + counts
# ═════════════════════════════════════════════════════════════════════
@router.get("/master-services")
async def list_master_services(
    include_inactive: bool = Query(
        False,
        description=(
            "Phase P16 · Feb-2026 — when False (default) the "
            "response only surfaces ``is_active=True`` rows.  Set "
            "to True on the admin management view to include "
            "soft-deleted rows."
        ),
    ),
    q: Optional[str] = Query(
        None,
        description=(
            "Case-insensitive substring match on ``name``.  Empty / "
            "whitespace-only strings are ignored."
        ),
    ),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    tid = tenant["id"]
    filter_kwargs: Dict[str, Any] = {}
    if not include_inactive:
        filter_kwargs["is_active"] = True
    if q and q.strip():
        filter_kwargs["name"] = {"$regex": re.escape(q.strip()),
                                    "$options": "i"}

    scoped = tenant_scoped_filter(tid, **filter_kwargs)
    rows = await db[_COLL].find(scoped, {"_id": 0}) \
        .sort("name", 1).to_list(1000)

    # ── counts aggregate — mirror the P18 pattern.  ``$ifNull``
    # coerces missing ``is_active`` to True (rows created before
    # P16 would have carried a value; new rows always do).  Single
    # round-trip regardless of tenant size.
    counts: Dict[str, int] = {"active": 0, "inactive": 0, "total": 0}
    pipeline = [
        {"$match": {"tenant_id": tid}},
        {"$group": {
            "_id": {
                "$cond": [
                    {"$eq": [True, {"$ifNull": ["$is_active", True]}]},
                    "active",
                    "inactive",
                ],
            },
            "count": {"$sum": 1},
        }},
    ]
    async for c in db[_COLL].aggregate(pipeline):
        bucket = c.get("_id")
        cnt = int(c.get("count") or 0)
        if bucket in ("active", "inactive"):
            counts[bucket] = cnt
        counts["total"] += cnt

    return {"items": rows, "count": len(rows), "counts": counts}


# ═════════════════════════════════════════════════════════════════════
# GET /api/master-services/categories · distinct name list
# ═════════════════════════════════════════════════════════════════════
@router.get("/master-services/categories")
async def list_master_service_categories(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Path-A helper — returns the active service-category names
    the tenant has configured (sourced from
    ``db.service_categories``).  Distinct from
    ``/service-categories`` in that it strips every field other
    than ``name`` so the FE combobox mini-modal can render a
    simple dropdown without a second admin-scoped fetch.
    """
    tid = tenant["id"]
    rows = await db.service_categories.find(
        {"tenant_id": tid, "is_archived": False},
        {"_id": 0, "name": 1, "sort_order": 1},
    ).sort([("sort_order", 1), ("name", 1)]).to_list(500)
    return {"items": [{"name": r["name"]} for r in rows if r.get("name")]}


# ═════════════════════════════════════════════════════════════════════
# POST /api/master-services · create
# ═════════════════════════════════════════════════════════════════════
@router.post("/master-services")
async def create_master_service(
    body: MasterServiceCreate,
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
):
    tid = tenant["id"]
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(
            400, {"error": "name_required", "field": "name"},
        )
    canonical_category = await _validate_category_name(tid, body.category)
    dup = await _find_duplicate_name(tid, name)
    if dup:
        raise HTTPException(
            409, {"error": "duplicate_name", "field": "name",
                    "attempted": name, "existing_id": dup["id"]},
        )
    now = now_iso()
    doc = {
        "id": new_id(),
        "tenant_id": tid,
        "name": name,
        "default_price": round(float(body.default_price or 0), 2),
        "category": canonical_category,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "created_by": user.get("id"),
        "updated_by": user.get("id"),
    }
    await db[_COLL].insert_one(dict(doc))
    return _shape(doc)


# ═════════════════════════════════════════════════════════════════════
# PATCH /api/master-services/{svc_id} · partial update
# ═════════════════════════════════════════════════════════════════════
@router.patch("/master-services/{svc_id}")
async def patch_master_service(
    svc_id: str,
    body: MasterServiceUpdate,
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
):
    tid = tenant["id"]
    scoped = tenant_scoped_filter(tid, id=svc_id)
    existing = await db[_COLL].find_one(scoped, {"_id": 0})
    if not existing:
        raise HTTPException(404, "master service not found")

    updates: Dict[str, Any] = {}

    if body.name is not None:
        name = (body.name or "").strip()
        if not name:
            raise HTTPException(
                400, {"error": "name_required", "field": "name"},
            )
        # Same-name PATCH is a no-op; skip the dedup lookup so a
        # user PATCHing only default_price + typing the same name
        # into the modal doesn't hit a 409 against themselves.
        if name.lower() != (existing.get("name") or "").lower():
            dup = await _find_duplicate_name(tid, name, exclude_id=svc_id)
            if dup:
                raise HTTPException(
                    409, {"error": "duplicate_name", "field": "name",
                            "attempted": name,
                            "existing_id": dup["id"]},
                )
        updates["name"] = name

    if body.default_price is not None:
        updates["default_price"] = round(float(body.default_price), 2)

    if body.category is not None:
        updates["category"] = await _validate_category_name(
            tid, body.category,
        )

    if not updates:
        return _shape(existing)

    updates["updated_at"] = now_iso()
    updates["updated_by"] = user.get("id")
    await db[_COLL].update_one(scoped, {"$set": updates})
    fresh = await db[_COLL].find_one(scoped, {"_id": 0})
    return _shape(fresh or {})


# ═════════════════════════════════════════════════════════════════════
# DELETE /api/master-services/{svc_id} · soft by default, hard opt-in
# ═════════════════════════════════════════════════════════════════════
@router.delete("/master-services/{svc_id}")
async def delete_master_service(
    svc_id: str,
    hard: bool = Query(
        False,
        description=(
            "Phase P16 · Feb-2026 — set to True to fully remove "
            "the row + write a ``deletion_audit`` snapshot.  "
            "Requires the request body ``{confirm:'DELETE'}``.  "
            "Admin-only either way."
        ),
    ),
    body: Optional[Dict[str, Any]] = Body(None),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    tid = tenant["id"]
    scoped = tenant_scoped_filter(tid, id=svc_id)
    existing = await db[_COLL].find_one(scoped, {"_id": 0})
    if not existing:
        raise HTTPException(404, "master service not found")

    if not hard:
        # Soft delete — flip ``is_active`` to False.  Idempotent —
        # calling twice is a no-op for the second call.
        await db[_COLL].update_one(
            scoped,
            {"$set": {"is_active": False,
                       "updated_at": now_iso(),
                       "updated_by": user.get("id")}},
        )
        fresh = await db[_COLL].find_one(scoped, {"_id": 0})
        return {"hard_deleted": False, "master_service": _shape(fresh or {})}

    # Hard delete — require the typed confirm gate + write audit row.
    if not isinstance(body, dict) or body.get("confirm") != "DELETE":
        raise HTTPException(
            400, {"error": "confirm_required",
                    "detail": "hard delete requires body {\"confirm\": \"DELETE\"}"},
        )

    audit_id = await write_deletion_audit_entry(
        tenant_id=tid,
        resource_type="master_service",
        resource_id=svc_id,
        user=user,
        snapshot=existing,
        deletion_reason="master_service.hard_delete",
    )
    res = await db[_COLL].delete_one(scoped)
    return {
        "hard_deleted": True,
        "deleted_count": int(res.deleted_count or 0),
        "audit_id": audit_id,
    }
