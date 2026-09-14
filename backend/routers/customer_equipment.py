"""Phase Feb-2026 · Customer Equipment Library — canonical resource.

Represents one *unit* of equipment installed at a customer's site (a
specific pump, filter, heater, etc.) with brand / model / serial /
install-date metadata. Photos link to this record through the
existing ``/api/files/upload`` pipeline using::

    linked_entity_type='customer_equipment'
    linked_entity_id=<equipment_id>
    purpose='customer_equipment'

so photo storage stays on S3 (base64 blob pattern retired here).

RBAC
----
* customer                → 403 on every write and every read below
* technician (any dept)   → create / edit / (soft) delete / read
* admin / super_admin     → create / edit / (soft) delete / read

Tenant isolation
----------------
Every read / write is filtered by ``tenant_id`` from
``get_current_tenant``. Cross-tenant reads 404, cross-tenant
writes 404. No workaround via ``X-Tenant-Slug``.

Coupling with the legacy ``customer_equipment_photos`` collection is
intentional-zero — that photo-grid router remains untouched for
back-compat. Migration of the legacy blobs is deferred to Phase-3 S3
cutover.

Endpoints (5)
-------------
POST   /api/customer-equipment
GET    /api/customer-equipment?customer_id=<id>
GET    /api/customer-equipment/{id}
PATCH  /api/customer-equipment/{id}
DELETE /api/customer-equipment/{id}     (soft-delete)
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db
from config_equipment_types import EQUIPMENT_TYPES
from routers.tenants import get_current_tenant
from utils import get_current_user, new_id, now_iso

router = APIRouter(prefix="/customer-equipment", tags=["customer-equipment"])

_MAX_STR = 200


# ─── helpers ────────────────────────────────────────────────────────────────
def _role(u: dict) -> str:
    return (u.get("role") or "").lower()


def _forbid_customer(u: dict) -> None:
    if _role(u) == "customer":
        raise HTTPException(403, "Equipment library is not available to customers")


def _require_writer(u: dict) -> None:
    """admin / super_admin / technician may write. Everyone else 403."""
    r = _role(u)
    if r in ("admin", "super_admin", "technician"):
        return
    raise HTTPException(403, "Admin or technician access required")


async def _get_customer_or_404(customer_id: str, tenant_id: str) -> dict:
    doc = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1},
    )
    if not doc:
        raise HTTPException(404, "Customer not found")
    return doc


async def _load_photos(equipment_id: str, tenant_id: str) -> List[dict]:
    """Fetch S3-backed photo file rows joined to this equipment unit."""
    cur = db.files.find(
        {
            "tenant_id": tenant_id,
            "is_deleted": False,
            "linked_entity_type": "customer_equipment",
            "linked_entity_id": equipment_id,
            "purpose": "customer_equipment",
        },
        {"_id": 0},
    ).sort("created_at", 1)
    rows = await cur.to_list(200)
    out = []
    for r in rows:
        out.append({
            "id": r.get("id"),
            "filename": r.get("original_filename"),
            "content_type": r.get("content_type"),
            "size": r.get("size"),
            "url": f"/api/files/{r.get('id')}/download",
        })
    return out


def _clean_str(v: Optional[str], *, max_len: int = _MAX_STR) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    if len(s) > max_len:
        raise HTTPException(400, f"Field must be {max_len} characters or fewer")
    return s


def _validate_equipment_type(et: Optional[str]) -> str:
    if not et or not str(et).strip():
        raise HTTPException(400, "equipment_type is required")
    et = str(et).strip()
    if et not in EQUIPMENT_TYPES:
        raise HTTPException(
            400,
            f"equipment_type must be one of: {EQUIPMENT_TYPES}",
        )
    return et


async def _serialize(doc: dict, tenant_id: str) -> dict:
    photos = await _load_photos(doc["id"], tenant_id)
    return {
        "id": doc["id"],
        "tenant_id": doc["tenant_id"],
        "customer_id": doc["customer_id"],
        "equipment_type": doc["equipment_type"],
        "brand": doc.get("brand"),
        "model": doc.get("model"),
        "serial_number": doc.get("serial_number"),
        "install_date": doc.get("install_date"),
        "notes": doc.get("notes"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "photos": photos,
    }


# ─── models ─────────────────────────────────────────────────────────────────
class EquipmentCreateIn(BaseModel):
    customer_id: str
    equipment_type: str
    brand: Optional[str] = Field(default=None, max_length=_MAX_STR)
    model: Optional[str] = Field(default=None, max_length=_MAX_STR)
    serial_number: Optional[str] = Field(default=None, max_length=_MAX_STR)
    install_date: Optional[str] = Field(
        default=None, description="ISO-8601 date, YYYY-MM-DD"
    )
    notes: Optional[str] = Field(default=None, max_length=2000)


class EquipmentPatchIn(BaseModel):
    equipment_type: Optional[str] = None
    brand: Optional[str] = Field(default=None, max_length=_MAX_STR)
    model: Optional[str] = Field(default=None, max_length=_MAX_STR)
    serial_number: Optional[str] = Field(default=None, max_length=_MAX_STR)
    install_date: Optional[str] = None
    notes: Optional[str] = Field(default=None, max_length=2000)


# ─── endpoints ──────────────────────────────────────────────────────────────
@router.post("", status_code=201)
async def create_equipment(
    body: EquipmentCreateIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _forbid_customer(user)
    _require_writer(user)

    await _get_customer_or_404(body.customer_id, tenant["id"])
    et = _validate_equipment_type(body.equipment_type)

    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "customer_id": body.customer_id,
        "equipment_type": et,
        "brand": _clean_str(body.brand),
        "model": _clean_str(body.model),
        "serial_number": _clean_str(body.serial_number),
        "install_date": _clean_str(body.install_date, max_len=32),
        "notes": _clean_str(body.notes, max_len=2000),
        "created_by_user_id": user["id"],
        "created_by_name": user.get("name") or user.get("email") or "Unknown",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "is_deleted": False,
        "deleted_at": None,
    }
    await db.customer_equipment.insert_one(doc)
    doc.pop("_id", None)
    return await _serialize(doc, tenant["id"])


@router.get("")
async def list_equipment(
    customer_id: str = Query(..., description="Customer id to list units for"),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _forbid_customer(user)
    await _get_customer_or_404(customer_id, tenant["id"])
    cur = db.customer_equipment.find(
        {
            "tenant_id": tenant["id"],
            "customer_id": customer_id,
            "is_deleted": {"$ne": True},
        },
        {"_id": 0},
    ).sort("created_at", 1)
    rows = await cur.to_list(500)
    items = [await _serialize(r, tenant["id"]) for r in rows]
    return {"customer_id": customer_id, "items": items, "count": len(items)}


@router.get("/{equipment_id}")
async def get_equipment(
    equipment_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _forbid_customer(user)
    doc = await db.customer_equipment.find_one(
        {
            "id": equipment_id,
            "tenant_id": tenant["id"],
            "is_deleted": {"$ne": True},
        },
        {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Equipment not found")
    return await _serialize(doc, tenant["id"])


@router.patch("/{equipment_id}")
async def patch_equipment(
    equipment_id: str,
    body: EquipmentPatchIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _forbid_customer(user)
    _require_writer(user)

    existing = await db.customer_equipment.find_one(
        {
            "id": equipment_id,
            "tenant_id": tenant["id"],
            "is_deleted": {"$ne": True},
        },
        {"_id": 0},
    )
    if not existing:
        raise HTTPException(404, "Equipment not found")

    updates: dict = {}
    if body.equipment_type is not None:
        updates["equipment_type"] = _validate_equipment_type(body.equipment_type)
    if body.brand is not None:
        updates["brand"] = _clean_str(body.brand)
    if body.model is not None:
        updates["model"] = _clean_str(body.model)
    if body.serial_number is not None:
        updates["serial_number"] = _clean_str(body.serial_number)
    if body.install_date is not None:
        updates["install_date"] = _clean_str(body.install_date, max_len=32)
    if body.notes is not None:
        updates["notes"] = _clean_str(body.notes, max_len=2000)

    if not updates:
        # Nothing to change — return current state so callers stay idempotent.
        return await _serialize(existing, tenant["id"])

    updates["updated_at"] = now_iso()
    await db.customer_equipment.update_one(
        {"id": equipment_id, "tenant_id": tenant["id"]},
        {"$set": updates},
    )
    fresh = await db.customer_equipment.find_one(
        {"id": equipment_id, "tenant_id": tenant["id"]},
        {"_id": 0},
    )
    return await _serialize(fresh, tenant["id"])


@router.delete("/{equipment_id}")
async def delete_equipment(
    equipment_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _forbid_customer(user)
    _require_writer(user)

    existing = await db.customer_equipment.find_one(
        {"id": equipment_id, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "is_deleted": 1},
    )
    if not existing:
        raise HTTPException(404, "Equipment not found")
    if existing.get("is_deleted"):
        return {"ok": True, "deleted": equipment_id, "already": True}

    await db.customer_equipment.update_one(
        {"id": equipment_id, "tenant_id": tenant["id"]},
        {"$set": {"is_deleted": True, "deleted_at": now_iso()}},
    )
    return {"ok": True, "deleted": equipment_id}
