"""Feb-2026 · P29 — Muted reasons CRUD.

Tenant-scoped. Reasons are soft-deactivated (never hard-deleted) so
the historical ``customers.muted_reason`` snapshots — which are
free-text on the customer, not FKs — remain contextual even after
a reason is retired.

RBAC:
  * GET  — any authenticated staff user (needed by the mute-modal picker)
  * POST/PATCH/DELETE — super_admin, admin, manager
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user, new_id, now_iso
from routers.customers import _p27_write_audit  # audit-log helper


router = APIRouter(tags=["muted-reasons"])


DEFAULT_MUTED_REASONS = (
    "Billing dispute",
    "Requested no contact",
    "Legal / collections",
    "Deceased",
    "Other",
)


def _staff_only(user: dict) -> None:
    role = (user.get("role") or "").lower()
    if role not in ("technician", "admin", "manager", "super_admin"):
        raise HTTPException(403, "Not allowed")


def _writer_only(user: dict) -> None:
    role = (user.get("role") or "").lower()
    if role not in ("admin", "manager", "super_admin"):
        raise HTTPException(
            status_code=403,
            detail={"detail": "role_not_permitted",
                      "message": "Only admin, manager, or super_admin can edit muted reasons."},
        )


class ReasonCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=120)
    sort_order: Optional[int] = 0


class ReasonPatch(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=120)
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


def _shape(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in doc.items() if k != "_id"}


async def seed_muted_reasons_for_tenant(tenant_id: str) -> int:
    """Idempotent — inserts DEFAULT_MUTED_REASONS iff the tenant has
    zero rows in ``muted_reasons``. Returns count inserted."""
    if await db.muted_reasons.count_documents({"tenant_id": tenant_id}) > 0:
        return 0
    now = now_iso()
    rows = [{
        "id": new_id(), "tenant_id": tenant_id, "label": label,
        "label_norm": label.lower(),
        "is_active": True, "sort_order": i * 10,
        "created_at": now, "created_by": None,
        "updated_at": now, "updated_by": None,
    } for i, label in enumerate(DEFAULT_MUTED_REASONS)]
    await db.muted_reasons.insert_many(rows)
    return len(rows)


@router.get("/settings/muted-reasons")
async def list_muted_reasons(
    include_inactive: bool = False,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _staff_only(user)
    await seed_muted_reasons_for_tenant(tenant["id"])
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if not include_inactive:
        q["is_active"] = True
    rows = await db.muted_reasons.find(q, {"_id": 0}).sort(
        [("sort_order", 1), ("label", 1)]
    ).to_list(200)
    return {"items": rows, "total": len(rows)}


@router.post("/settings/muted-reasons")
async def create_muted_reason(
    request: Request,
    body: ReasonCreate,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _writer_only(user)
    label = body.label.strip()
    if not label:
        raise HTTPException(400, "Label is required")
    dup = await db.muted_reasons.find_one(
        {"tenant_id": tenant["id"], "label_norm": label.lower()},
    )
    if dup:
        raise HTTPException(
            status_code=409,
            detail={"detail": "duplicate_label",
                      "message": f"Reason '{label}' already exists."},
        )
    now = now_iso()
    doc = {
        "id": new_id(), "tenant_id": tenant["id"], "label": label,
        "label_norm": label.lower(),
        "is_active": True,
        "sort_order": int(body.sort_order or 0),
        "created_at": now, "created_by": user.get("id"),
        "updated_at": now, "updated_by": user.get("id"),
    }
    await db.muted_reasons.insert_one(doc)
    await _p27_write_audit(event="muted_reason_create", cid=doc["id"],
                              tenant_id=tenant["id"], user=user,
                              request=request, extra={"label": label})
    return _shape(doc)


@router.patch("/settings/muted-reasons/{rid}")
async def update_muted_reason(
    rid: str,
    request: Request,
    body: ReasonPatch,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _writer_only(user)
    doc = await db.muted_reasons.find_one(
        {"id": rid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Reason not found")
    updates: Dict[str, Any] = {}
    if body.label is not None:
        new_label = body.label.strip()
        if not new_label:
            raise HTTPException(400, "Label cannot be blank")
        if new_label.lower() != doc.get("label_norm"):
            dup = await db.muted_reasons.find_one({
                "tenant_id": tenant["id"], "label_norm": new_label.lower(),
                "id": {"$ne": rid},
            })
            if dup:
                raise HTTPException(
                    status_code=409,
                    detail={"detail": "duplicate_label",
                              "message": f"Reason '{new_label}' already exists."},
                )
        updates["label"] = new_label
        updates["label_norm"] = new_label.lower()
    if body.sort_order is not None:
        updates["sort_order"] = int(body.sort_order)
    if body.is_active is not None:
        updates["is_active"] = bool(body.is_active)
    if not updates:
        return doc
    updates["updated_at"] = now_iso()
    updates["updated_by"] = user.get("id")
    await db.muted_reasons.update_one({"id": rid}, {"$set": updates})
    await _p27_write_audit(event="muted_reason_update", cid=rid,
                              tenant_id=tenant["id"], user=user,
                              request=request, extra=updates)
    return _shape({**doc, **updates})


@router.delete("/settings/muted-reasons/{rid}")
async def deactivate_muted_reason(
    rid: str,
    request: Request,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _writer_only(user)
    doc = await db.muted_reasons.find_one(
        {"id": rid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Reason not found")
    if not doc.get("is_active"):
        return {"deactivated": False, "reason": "already_inactive"}
    await db.muted_reasons.update_one(
        {"id": rid},
        {"$set": {"is_active": False, "updated_at": now_iso(),
                    "updated_by": user.get("id")}},
    )
    await _p27_write_audit(event="muted_reason_deactivate", cid=rid,
                              tenant_id=tenant["id"], user=user,
                              request=request)
    return {"deactivated": True, "id": rid}
