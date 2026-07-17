"""Phase 56.11 — Customer Equipment Photo Library.

Store up to 4 photos per equipment-type per customer, tenant-scoped.
Reuses the existing base64 data-URL upload pattern used by the
checklist PhotoUploader — no new storage backend required.

Endpoints (4):
  GET    /api/customers/{customer_id}/equipment-photos
  POST   /api/customers/{customer_id}/equipment-photos
  DELETE /api/customers/{customer_id}/equipment-photos/{photo_id}
  GET    /api/equipment-types

Collection: `customer_equipment_photos`.

RBAC:
- customer               → 403 on every endpoint (internal-only feature).
- technician (any dept)  → view + upload (equipment lib is not
                           department-gated; landscape techs may
                           still photograph pool equipment they see).
- admin / super_admin    → view + upload + delete.

Tenant isolation: every read/write is filtered by `tenant_id`. Cross-
tenant reads return 404; cross-tenant deletes are impossible.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from config_equipment_types import (
    EQUIPMENT_TYPES,
    EQUIPMENT_PHOTO_CAP,
    EQUIPMENT_PHOTO_TAGS,
)
from routers.tenants import get_current_tenant
from utils import get_current_user, new_id, now_iso

router = APIRouter()


# ─── helpers ────────────────────────────────────────────────────────────────
def _role(u: dict) -> str:
    return (u.get("role") or "").lower()


def _is_admin(u: dict) -> bool:
    return _role(u) in ("admin", "super_admin")


def _forbid_customer(u: dict) -> None:
    if _role(u) == "customer":
        raise HTTPException(403, "Equipment library is not available to customers")


async def _get_customer_or_404(customer_id: str, tenant_id: str) -> dict:
    doc = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id}, {"_id": 0, "id": 1, "name": 1},
    )
    if not doc:
        raise HTTPException(404, "Customer not found")
    return doc


# ─── models ─────────────────────────────────────────────────────────────────
class EquipmentPhotoIn(BaseModel):
    equipment_type: str
    photo: str = Field(..., description="Base64 data-URL or plain URL")
    caption: Optional[str] = ""
    tags: Optional[List[str]] = None


# ─── endpoints ──────────────────────────────────────────────────────────────
@router.get("/equipment-types")
async def list_equipment_types(user: dict = Depends(get_current_user)):
    _forbid_customer(user)
    return {"types": EQUIPMENT_TYPES, "photo_cap": EQUIPMENT_PHOTO_CAP,
            "allowed_tags": sorted(EQUIPMENT_PHOTO_TAGS)}


@router.get("/customers/{customer_id}/equipment-photos")
async def list_photos(
    customer_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _forbid_customer(user)
    await _get_customer_or_404(customer_id, tenant["id"])
    rows = await db.customer_equipment_photos.find(
        {"tenant_id": tenant["id"], "customer_id": customer_id}, {"_id": 0},
    ).sort("uploaded_at", 1).to_list(200)
    grouped: dict = {t: [] for t in EQUIPMENT_TYPES}
    for r in rows:
        et = r.get("equipment_type")
        if et in grouped:
            grouped[et].append(r)
        # Photos with a stale equipment_type (removed from enum) are
        # silently dropped — a cleanup migration would handle them.
    return {"customer_id": customer_id, "grouped": grouped,
            "types": EQUIPMENT_TYPES, "cap": EQUIPMENT_PHOTO_CAP}


@router.post("/customers/{customer_id}/equipment-photos", status_code=201)
async def create_photo(
    customer_id: str, body: EquipmentPhotoIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _forbid_customer(user)
    await _get_customer_or_404(customer_id, tenant["id"])

    et = (body.equipment_type or "").strip()
    if et not in EQUIPMENT_TYPES:
        raise HTTPException(400, f"equipment_type must be one of: {EQUIPMENT_TYPES}")

    # Enforce the 4-photo cap per (customer, equipment_type).
    count = await db.customer_equipment_photos.count_documents({
        "tenant_id": tenant["id"], "customer_id": customer_id, "equipment_type": et,
    })
    if count >= EQUIPMENT_PHOTO_CAP:
        raise HTTPException(
            400,
            f"Maximum of {EQUIPMENT_PHOTO_CAP} photos per equipment type reached "
            f"for '{et}'. Delete an existing photo before adding a new one.",
        )

    caption = (body.caption or "").strip()
    if len(caption) > 120:
        raise HTTPException(400, "caption must be 120 characters or fewer")

    # Tag validation — reject unknown tag values so we never write junk.
    tags = body.tags or []
    if tags:
        bad = [t for t in tags if t not in EQUIPMENT_PHOTO_TAGS]
        if bad:
            raise HTTPException(
                400,
                f"Unknown tag(s) {bad}. Allowed: {sorted(EQUIPMENT_PHOTO_TAGS)}",
            )
    if not tags:
        tags = ["general"]

    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "customer_id": customer_id,
        "equipment_type": et,
        "photo_url": body.photo,
        "thumbnail_url": None,  # reuse pipeline later — same URL for now
        "caption": caption,
        "tags": tags,
        "uploaded_by_user_id": user["id"],
        "uploaded_by_name": user.get("name") or user.get("email") or "Unknown",
        "uploaded_at": now_iso(),
    }
    await db.customer_equipment_photos.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.delete("/customers/{customer_id}/equipment-photos/{photo_id}")
async def delete_photo(
    customer_id: str, photo_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if not _is_admin(user):
        raise HTTPException(403, "Admin access required to delete equipment photos")
    await _get_customer_or_404(customer_id, tenant["id"])
    res = await db.customer_equipment_photos.delete_one({
        "id": photo_id, "tenant_id": tenant["id"], "customer_id": customer_id,
    })
    if res.deleted_count == 0:
        raise HTTPException(404, "Photo not found")
    return {"ok": True, "deleted": photo_id}
