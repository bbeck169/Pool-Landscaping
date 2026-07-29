"""Service categories · Feb-2026.

Higher-level business-unit taxonomy attached to **pricebook items**
(``db.items.service_category_id``). Distinct from income_categories
which attaches to invoice line items — they coexist as two
independent axes.

Endpoints:
  • GET/POST/PATCH/DELETE /api/service-categories
  • POST /api/service-categories/{id}/{archive,restore}

Enforcement is exposed as ``validate_service_category`` for
routers/items.py to call on pricebook create + edit.
"""
from __future__ import annotations

import colorsys
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter()

_DEFAULTS = [
    "Pool",
    "Landscaping",
    "Irrigation",
    "Hardscaping",
    "Landscape Lighting",
    "Rock Install",
    "Pool Equipment Installs",
    "Pool Equipment Upgrades",
    "Pool Drains",
    "Acid Wash",
    "Pool Cleaning",
    "Pool Repair",
    "Pool Maintenance",
]


def _require_admin(user: dict) -> None:
    if (user or {}).get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "admin_only")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _auto_color(name: str) -> str:
    h = int(hashlib.md5(name.encode("utf-8")).hexdigest()[:8], 16)  # noqa: S324
    hue = (h % 360) / 360.0
    r, g, b = colorsys.hls_to_rgb(hue, 0.55, 0.65)
    return "#" + "".join(f"{int(round(x * 255)):02x}" for x in (r, g, b))


async def ensure_defaults_for_tenant(tenant_id: str) -> None:
    """Idempotent — seeds any DEFAULT that isn't already present in
    the tenant.  This runs both on first-tenant-access AND as a
    silent backfill for tenants that were previously seeded with the
    smaller Pool+Landscaping set (Feb-2026 taxonomy merge).  A name
    is considered "already present" case-insensitively.
    """
    if not tenant_id:
        return
    existing = await db.service_categories.find(
        {"tenant_id": tenant_id}, {"_id": 0, "name": 1},
    ).to_list(500)
    have = {(r.get("name") or "").strip().lower() for r in existing}
    missing = [n for n in _DEFAULTS if n.lower() not in have]
    if not missing:
        return
    now = _now()
    docs = [{
        "id": str(uuid.uuid4()),
        "name": n, "description": "", "color": _auto_color(n),
        "is_archived": False, "sort_order": _DEFAULTS.index(n),
        "tenant_id": tenant_id,
        "created_at": now, "created_by_user_id": "system:seed",
        "updated_at": now,
    } for n in missing]
    await db.service_categories.insert_many(docs)
    logger.info(
        "[service_categories] seeded %d defaults for tenant=%s (missing=%s)",
        len(docs), tenant_id, missing,
    )


async def validate_service_category(tenant_id: str,
                                      service_category_id: Optional[str]) -> None:
    """Reject if missing or references an archived/foreign category."""
    await ensure_defaults_for_tenant(tenant_id)
    cid = (service_category_id or "").strip() if service_category_id else ""
    if not cid:
        active = await db.service_categories.find(
            {"tenant_id": tenant_id, "is_archived": False},
            {"_id": 0, "name": 1},
        ).to_list(50)
        raise HTTPException(
            status_code=400,
            detail={
                "error": "service_category_required",
                "field": "service_category_id",
                "available_categories": [c["name"] for c in active],
            },
        )
    cat = await db.service_categories.find_one(
        {"id": cid, "tenant_id": tenant_id, "is_archived": False},
        {"_id": 0, "id": 1},
    )
    if not cat:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "service_category_invalid",
                "field": "service_category_id",
            },
        )


class CategoryIn(BaseModel):
    name: str
    description: Optional[str] = ""
    color: Optional[str] = None
    sort_order: Optional[int] = 0


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None


@router.get("/service-categories")
async def list_categories(
    include_archived: bool = Query(False),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    tid = tenant["id"]
    await ensure_defaults_for_tenant(tid)
    q: Dict[str, Any] = {"tenant_id": tid}
    if not include_archived:
        q["is_archived"] = False
    cur = db.service_categories.find(q, {"_id": 0}).sort(
        [("sort_order", 1), ("name", 1)])
    items = await cur.to_list(1000)
    for c in items:
        for k in ("created_at", "updated_at"):
            if isinstance(c.get(k), datetime):
                c[k] = c[k].isoformat()
    return {"items": items, "total": len(items)}


@router.post("/service-categories")
async def create_category(
    body: CategoryIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    tid = tenant["id"]
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    dup = await db.service_categories.find_one(
        {"tenant_id": tid, "name": {"$regex": f"^{name}$", "$options": "i"}},
        {"_id": 0, "id": 1},
    )
    if dup:
        raise HTTPException(
            status_code=409,
            detail={"error": "duplicate_name", "field": "name"},
        )
    now = _now()
    doc = {
        "id": str(uuid.uuid4()),
        "name": name,
        "description": body.description or "",
        "color": body.color or _auto_color(name),
        "is_archived": False,
        "sort_order": body.sort_order or 0,
        "tenant_id": tid,
        "created_at": now,
        "created_by_user_id": user.get("id") or "",
        "updated_at": now,
    }
    await db.service_categories.insert_one(dict(doc))
    doc.pop("_id", None)
    doc["created_at"] = now.isoformat()
    doc["updated_at"] = now.isoformat()
    return doc


@router.patch("/service-categories/{cid}")
async def update_category(
    cid: str, body: CategoryUpdate,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    tid = tenant["id"]
    cat = await db.service_categories.find_one(
        {"id": cid, "tenant_id": tid}, {"_id": 0})
    if not cat:
        raise HTTPException(404, "not_found")
    upd = {k: v for k, v in body.dict(exclude_unset=True).items()
           if v is not None}
    if "name" in upd:
        upd["name"] = upd["name"].strip()
        if upd["name"].lower() != (cat.get("name") or "").lower():
            dup = await db.service_categories.find_one(
                {"tenant_id": tid,
                  "name": {"$regex": f"^{upd['name']}$", "$options": "i"},
                  "id": {"$ne": cid}}, {"_id": 0, "id": 1})
            if dup:
                raise HTTPException(
                    status_code=409,
                    detail={"error": "duplicate_name", "field": "name"},
                )
    upd["updated_at"] = _now()
    await db.service_categories.update_one({"id": cid, "tenant_id": tid},
                                              {"$set": upd})
    return await db.service_categories.find_one(
        {"id": cid, "tenant_id": tid}, {"_id": 0})


@router.post("/service-categories/{cid}/archive")
async def archive_category(cid: str,
                             user: dict = Depends(get_current_user),
                             tenant: dict = Depends(get_current_tenant)):
    _require_admin(user)
    r = await db.service_categories.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"is_archived": True, "updated_at": _now()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "not_found")
    return {"ok": True, "id": cid, "is_archived": True}


@router.post("/service-categories/{cid}/restore")
async def restore_category(cid: str,
                             user: dict = Depends(get_current_user),
                             tenant: dict = Depends(get_current_tenant)):
    _require_admin(user)
    r = await db.service_categories.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"is_archived": False, "updated_at": _now()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "not_found")
    return {"ok": True, "id": cid, "is_archived": False}


@router.delete("/service-categories/{cid}")
async def hard_delete_category(cid: str,
                                 user: dict = Depends(get_current_user),
                                 tenant: dict = Depends(get_current_tenant)):
    """Hard delete — refuses if any pricebook item references this
    category (409 category_in_use)."""
    _require_admin(user)
    tid = tenant["id"]
    linked = await db.items.count_documents(
        {"tenant_id": tid, "service_category_id": cid,
          "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]})
    if linked > 0:
        raise HTTPException(
            status_code=409,
            detail={"error": "category_in_use",
                    "linked_pricebook_items": linked},
        )
    r = await db.service_categories.delete_one(
        {"id": cid, "tenant_id": tid})
    if r.deleted_count == 0:
        raise HTTPException(404, "not_found")
    return {"ok": True, "id": cid, "deleted": True}
