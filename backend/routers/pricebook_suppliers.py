"""Phase 56-a · Aug-2026 — Pricebook Suppliers CRUD.

Endpoints (all under ``/api/pricebook/suppliers/*``):
  * GET    /api/pricebook/suppliers?income_category_id=&include_deleted=
  * POST   /api/pricebook/suppliers                 — create
  * PATCH  /api/pricebook/suppliers/{id}            — display_name + is_active only
  * DELETE /api/pricebook/suppliers/{id}            — soft delete
  * POST   /api/pricebook/suppliers/{id}/restore    — undo soft delete

All gated by ``require_admin`` (admin / super_admin / owner). Manager /
technician / customer get 403 before any query runs.

Soft-delete field convention mirrors Fix #5 (Autobilling Runs) verbatim:
``deleted_at``, ``deleted_by_user_id``, ``restored_at``,
``restored_by_user_id``. ``include_deleted=true`` opts in; default is
false (hides deleted rows).

Write-once fields — ``slug`` and ``income_category_id`` are set at
create and can never be patched. PATCH accepts ``display_name`` and
``is_active`` only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db, logger
from models import PricebookSupplierIn, PricebookSupplierPatch
from routers.tenants import get_current_tenant
from utils import require_admin


router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/pricebook/suppliers")
async def list_pricebook_suppliers(
    income_category_id: Optional[str] = Query(None),
    include_deleted: bool = Query(False),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    q: dict = {"tenant_id": tenant["id"]}
    if income_category_id:
        q["income_category_id"] = income_category_id
    if not include_deleted:
        q["deleted_at"] = {"$in": [None, ""]}
    rows = await db.pricebook_suppliers.find(q, {"_id": 0}).sort(
        "display_name", 1).to_list(500)
    return rows


@router.post("/pricebook/suppliers", status_code=201)
async def create_pricebook_supplier(
    body: PricebookSupplierIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    slug = (body.slug or "").strip().lower()
    if not slug:
        raise HTTPException(400, "slug is required")
    name = (body.display_name or "").strip()
    if not name:
        raise HTTPException(400, "display_name is required")
    if not body.income_category_id:
        raise HTTPException(400, "income_category_id is required")

    # Category must exist and be active on this tenant.
    cat = await db.income_categories.find_one(
        {"tenant_id": tenant["id"], "id": body.income_category_id},
        {"_id": 0, "id": 1, "is_archived": 1},
    )
    if not cat or cat.get("is_archived"):
        raise HTTPException(400, "income_category_id is invalid or archived")

    # Slug uniqueness within (tenant, income_category, non-deleted).
    dup = await db.pricebook_suppliers.find_one(
        {"tenant_id": tenant["id"], "slug": slug,
          "deleted_at": {"$in": [None, ""]}},
        {"_id": 0, "id": 1},
    )
    if dup:
        raise HTTPException(409, {"error": "slug_taken",
                                    "message": f"slug '{slug}' already exists"})

    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant["id"],
        "slug": slug,
        "display_name": name,
        "income_category_id": body.income_category_id,
        "is_active": True,
        "is_seed": False,
        "deleted_at": None,
        "created_at": _now_iso(),
        "created_by_user_id": user.get("id"),
    }
    await db.pricebook_suppliers.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/pricebook/suppliers/{sid}")
async def patch_pricebook_supplier(
    sid: str,
    body: PricebookSupplierPatch,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    row = await db.pricebook_suppliers.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "supplier not found")
    updates: dict = {}
    if body.display_name is not None:
        v = body.display_name.strip()
        if not v:
            raise HTTPException(400, "display_name cannot be empty")
        updates["display_name"] = v
    if body.is_active is not None:
        updates["is_active"] = bool(body.is_active)
    if not updates:
        return row
    updates["updated_at"] = _now_iso()
    await db.pricebook_suppliers.update_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"$set": updates},
    )
    row.update(updates)
    return row


@router.delete("/pricebook/suppliers/{sid}")
async def soft_delete_pricebook_supplier(
    sid: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    row = await db.pricebook_suppliers.find_one(
        {"id": sid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "deleted_at": 1},
    )
    if not row:
        raise HTTPException(404, "supplier not found")
    if row.get("deleted_at"):
        return {"ok": True, "id": sid, "already_deleted": True}
    await db.pricebook_suppliers.update_one(
        {"id": sid, "tenant_id": tenant["id"]},
        {"$set": {"deleted_at": _now_iso(),
                    "deleted_by_user_id": user.get("id")}},
    )
    try:
        await db.audits.insert_one({
            "id": str(uuid.uuid4()),
            "kind": "pricebook_supplier_soft_delete",
            "tenant_id": tenant["id"], "target_id": sid,
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "at": _now_iso(),
        })
    except Exception as e:                                        # noqa: BLE001
        logger.warning(f"pricebook_supplier_soft_delete audit failed: {e}")
    return {"ok": True, "id": sid, "deleted": True}


@router.post("/pricebook/suppliers/{sid}/restore")
async def restore_pricebook_supplier(
    sid: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    row = await db.pricebook_suppliers.find_one(
        {"id": sid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "deleted_at": 1},
    )
    if not row:
        raise HTTPException(404, "supplier not found")
    if not row.get("deleted_at"):
        return {"ok": True, "id": sid, "already_active": True}
    await db.pricebook_suppliers.update_one(
        {"id": sid, "tenant_id": tenant["id"]},
        {"$set": {"deleted_at": None, "restored_at": _now_iso(),
                    "restored_by_user_id": user.get("id")},
          "$unset": {"deleted_by_user_id": ""}},
    )
    return {"ok": True, "id": sid, "restored": True}
