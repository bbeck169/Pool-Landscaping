"""Income category enforcement · Feb-2026.

Endpoints:
  • GET    /api/income-categories             — list (admin)
  • POST   /api/income-categories             — create (admin)
  • PATCH  /api/income-categories/{id}        — edit (admin)
  • POST   /api/income-categories/{id}/archive
  • POST   /api/income-categories/{id}/restore
  • GET    /api/reports/uncategorized-count   — banner data (admin)
  • GET    /api/reports/uncategorized-items   — list (admin)

Grandfather rule: existing invoice line items with a null/empty
``category`` remain readable, but any NEW create or any EDIT that
touches a line item MUST supply a valid category id or name.

Enforcement is exposed as a helper (``validate_line_item_categories``)
that quotes.py and invoice_edit.py call.  It resolves either category
NAMES (backwards compatible — the existing line items use names like
``"Pool"``, ``"Chem"``) OR ids to an active row, and rejects any line
that has neither.
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
    "Pool", "Chemicals", "Landscaping", "Repair", "Late Fee", "Other",
]


def _require_admin(user: dict) -> None:
    if (user or {}).get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "admin_only")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _auto_color(name: str) -> str:
    h = int(hashlib.sha256(name.encode("utf-8")).hexdigest()[:8], 16)  # non-security: stable name→color slot
    hue = (h % 360) / 360.0
    r, g, b = colorsys.hls_to_rgb(hue, 0.55, 0.65)
    return "#" + "".join(f"{int(round(x * 255)):02x}" for x in (r, g, b))


# ═══════════════════════════════════════════════════════════════════
# Seed on first access
# ═══════════════════════════════════════════════════════════════════
async def ensure_defaults_for_tenant(tenant_id: str) -> None:
    """Idempotent — seeds the 6 default categories only if none exist."""
    if not tenant_id:
        return
    existing = await db.income_categories.count_documents({"tenant_id": tenant_id})
    if existing > 0:
        return
    now = _now()
    docs = [
        {
            "id": str(uuid.uuid4()),
            "name": name,
            "description": "",
            "color": _auto_color(name),
            "is_archived": False,
            "sort_order": i,
            "tenant_id": tenant_id,
            "created_at": now,
            "created_by_user_id": "system:seed",
            "updated_at": now,
        }
        for i, name in enumerate(_DEFAULTS)
    ]
    await db.income_categories.insert_many(docs)
    logger.info("[income_categories] seeded %d defaults for tenant=%s",
                len(docs), tenant_id)


# ═══════════════════════════════════════════════════════════════════
# Category enforcement helper — called by quotes.py + invoice_edit.py
# ═══════════════════════════════════════════════════════════════════
async def validate_line_item_categories(
    tenant_id: str, line_items: List[Dict[str, Any]],
) -> None:
    """Reject if ANY line item is missing a category or references an
    inactive/foreign one.  Called from create + edit paths.

    Accepts EITHER a category **id** (uuid) OR a category **name**
    (string that matches ``income_categories.name`` case-insensitively).
    """
    await ensure_defaults_for_tenant(tenant_id)
    active = await db.income_categories.find(
        {"tenant_id": tenant_id, "is_archived": False},
        {"_id": 0, "id": 1, "name": 1},
    ).to_list(500)
    valid_ids = {c["id"] for c in active}
    valid_names = {(c["name"] or "").strip().lower() for c in active}
    available = [c["name"] for c in active]

    for idx, li in enumerate(line_items or []):
        cat = (li.get("category") or "").strip() if isinstance(
            li.get("category"), str) else li.get("category")
        if not cat:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "category_required",
                    "field": f"line_items[{idx}].category",
                    "message": ("Each income line item must have a "
                                 "category. Available categories: "
                                 f"{available}"),
                    "available_categories": available,
                },
            )
        cat_str = str(cat).strip()
        if cat_str in valid_ids or cat_str.lower() in valid_names:
            continue
        raise HTTPException(
            status_code=400,
            detail={
                "error": "category_invalid",
                "field": f"line_items[{idx}].category",
                "message": (f"Unknown or archived category: {cat_str!r}. "
                             f"Available categories: {available}"),
                "available_categories": available,
            },
        )


# ═══════════════════════════════════════════════════════════════════
# CRUD models
# ═══════════════════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════
@router.get("/income-categories")
async def list_categories(
    include_archived: bool = Query(False),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    tenant_id = tenant["id"]
    await ensure_defaults_for_tenant(tenant_id)
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if not include_archived:
        q["is_archived"] = False
    cur = db.income_categories.find(q, {"_id": 0}).sort(
        [("sort_order", 1), ("name", 1)])
    items = await cur.to_list(1000)
    for c in items:
        if isinstance(c.get("created_at"), datetime):
            c["created_at"] = c["created_at"].isoformat()
        if isinstance(c.get("updated_at"), datetime):
            c["updated_at"] = c["updated_at"].isoformat()
    return {"items": items, "total": len(items)}


@router.post("/income-categories")
async def create_category(
    body: CategoryIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    tenant_id = tenant["id"]
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    existing = await db.income_categories.find_one(
        {"tenant_id": tenant_id,
          "name": {"$regex": f"^{name}$", "$options": "i"}},
        {"_id": 0, "id": 1},
    )
    if existing:
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
        "tenant_id": tenant_id,
        "created_at": now,
        "created_by_user_id": user.get("id") or "",
        "updated_at": now,
    }
    await db.income_categories.insert_one(dict(doc))
    doc.pop("_id", None)
    doc["created_at"] = now.isoformat()
    doc["updated_at"] = now.isoformat()
    return doc


@router.patch("/income-categories/{cid}")
async def update_category(
    cid: str, body: CategoryUpdate,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    tenant_id = tenant["id"]
    cat = await db.income_categories.find_one(
        {"id": cid, "tenant_id": tenant_id}, {"_id": 0})
    if not cat:
        raise HTTPException(404, "category_not_found")
    upd = {k: v for k, v in body.dict(exclude_unset=True).items() if v is not None}
    if "name" in upd:
        upd["name"] = upd["name"].strip()
        if upd["name"] and upd["name"].lower() != (cat.get("name") or "").lower():
            dup = await db.income_categories.find_one(
                {"tenant_id": tenant_id,
                  "name": {"$regex": f"^{upd['name']}$", "$options": "i"},
                  "id": {"$ne": cid}},
                {"_id": 0, "id": 1},
            )
            if dup:
                raise HTTPException(
                    status_code=409,
                    detail={"error": "duplicate_name", "field": "name"},
                )
    upd["updated_at"] = _now()
    await db.income_categories.update_one(
        {"id": cid, "tenant_id": tenant_id}, {"$set": upd})
    return await db.income_categories.find_one(
        {"id": cid, "tenant_id": tenant_id}, {"_id": 0})


@router.post("/income-categories/{cid}/archive")
async def archive_category(
    cid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    r = await db.income_categories.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"is_archived": True, "updated_at": _now()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "category_not_found")
    return {"ok": True, "id": cid, "is_archived": True}


@router.post("/income-categories/{cid}/restore")
async def restore_category(
    cid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    r = await db.income_categories.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"is_archived": False, "updated_at": _now()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "category_not_found")
    return {"ok": True, "id": cid, "is_archived": False}


# ═══════════════════════════════════════════════════════════════════
# Uncategorized report
# ═══════════════════════════════════════════════════════════════════
@router.get("/reports/uncategorized-count")
async def uncategorized_count(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    tenant_id = tenant["id"]
    count = 0
    sample: List[Dict[str, Any]] = []
    cur = db.quotes.find(
        {"tenant_id": tenant_id, "doc_type": "invoice"},
        {"_id": 0, "id": 1, "invoice_number": 1, "line_items": 1},
    )
    async for inv in cur:
        for idx, li in enumerate(inv.get("line_items") or []):
            cat = li.get("category")
            if not cat or (isinstance(cat, str) and not cat.strip()):
                count += 1
                if len(sample) < 10:
                    sample.append({
                        "invoice_id": inv.get("id"),
                        "invoice_number": inv.get("invoice_number"),
                        "line_item_index": idx,
                        "amount": (li.get("quantity", 0) or 0)
                                   * (li.get("unit_price", 0) or 0),
                    })
    return {"count": count, "sample_invoices": sample}


@router.get("/reports/uncategorized-items")
async def uncategorized_items(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Full list of uncategorized line items — used by the "Review"
    click-through from the dashboard banner."""
    _require_admin(user)
    tenant_id = tenant["id"]
    rows: List[Dict[str, Any]] = []
    cur = db.quotes.find(
        {"tenant_id": tenant_id, "doc_type": "invoice"},
        {"_id": 0, "id": 1, "invoice_number": 1, "line_items": 1,
          "customer_name": 1, "created_at": 1},
    )
    async for inv in cur:
        for idx, li in enumerate(inv.get("line_items") or []):
            cat = li.get("category")
            if not cat or (isinstance(cat, str) and not cat.strip()):
                rows.append({
                    "invoice_id": inv.get("id"),
                    "invoice_number": inv.get("invoice_number"),
                    "customer_name": inv.get("customer_name"),
                    "created_at": inv.get("created_at"),
                    "line_item_index": idx,
                    "description": li.get("description"),
                    "amount": (li.get("quantity", 0) or 0)
                               * (li.get("unit_price", 0) or 0),
                })
    return {"items": rows, "total": len(rows)}
