"""MR0 · Feb-2026 — Admin moderation queue for public check-ins.

Endpoints
---------
* ``GET   /api/admin/moderation/public-checkins``          list
* ``GET   /api/admin/moderation/public-checkins/{id}``     detail
* ``PATCH /api/admin/moderation/public-checkins/{id}``     edit content
* ``POST  /api/admin/moderation/public-checkins/{id}/approve``
* ``POST  /api/admin/moderation/public-checkins/{id}/reject``
* ``POST  /api/admin/moderation/public-checkins/{id}/unpublish``

All admin+ / super_admin / manager. Tenant-scoped.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from services.address_masker import mask_address
from utils import get_current_user, new_id, now_iso

router = APIRouter()

_MOD_ROLES = {"admin", "super_admin", "manager"}
_ALLOWED_STATES = {"pending_review", "approved", "rejected", "unpublished"}
_EDITABLE_FROM = {"pending_review", "approved"}


def _require_mod(user: Dict[str, Any]) -> None:
    if (user.get("role") or "").lower() not in _MOD_ROLES:
        raise HTTPException(403, {"error": "forbidden"})


async def _load_or_404(tenant_id: str, mod_id: str) -> Dict[str, Any]:
    row = await db.public_checkins.find_one(
        {"id": mod_id, "tenant_id": tenant_id},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(404, {"error": "not_found"})
    return row


async def _audit(caller: Dict[str, Any], event: str,
                   mod_id: str, details: str = "") -> None:
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "event": event,
            "email": caller.get("email"),
            "ip_address": None,
            "status": "success",
            "details": f"public_id={mod_id} {details}".strip(),
            "tenant_id": caller.get("tenant_id"),
            "created_at": now_iso(),
        })
    except Exception as e:                                              # noqa: BLE001
        logger.warning("audit_logs write failed (%s): %s", event, e)


# ─── LIST ───────────────────────────────────────────────────────────

@router.get("/admin/moderation/public-checkins",
             operation_id="publicCheckins.list")
async def list_public_checkins(
    state: str = "pending_review",
    limit: int = 50,
    offset: int = 0,
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = caller.get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(400, {"error": "missing_tenant"})
    limit = max(1, min(200, int(limit)))
    offset = max(0, int(offset))

    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if state != "all":
        if state not in _ALLOWED_STATES:
            raise HTTPException(422, {"error": "invalid_state"})
        q["state"] = state

    total = await db.public_checkins.count_documents(q)
    items: List[Dict[str, Any]] = []
    async for r in db.public_checkins.find(q, {"_id": 0}) \
                                       .sort("submitted_at", -1) \
                                       .skip(offset).limit(limit):
        items.append(r)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


# ─── DETAIL ─────────────────────────────────────────────────────────

@router.get("/admin/moderation/public-checkins/{mod_id}",
             operation_id="publicCheckins.detail")
async def get_public_checkin(mod_id: str,
                                caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant_id = caller.get("tenant_id") or ""
    return await _load_or_404(tenant_id, mod_id)


# ─── PATCH edit ─────────────────────────────────────────────────────

class PatchBody(BaseModel):
    service_name: Optional[str] = None
    service_category: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    photos: Optional[List[Dict[str, Any]]] = None


@router.patch("/admin/moderation/public-checkins/{mod_id}",
               operation_id="publicCheckins.patch")
async def patch_public_checkin(
    mod_id: str, body: PatchBody,
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = caller.get("tenant_id") or ""
    row = await _load_or_404(tenant_id, mod_id)
    if row["state"] not in _EDITABLE_FROM:
        raise HTTPException(
            409, {"error": "not_editable", "state": row["state"]})

    updates: Dict[str, Any] = {}
    for field in ("service_name", "service_category",
                    "description", "tags", "photos"):
        val = getattr(body, field)
        if val is not None:
            updates[field] = val
    if not updates:
        return row
    updates["updated_at"] = now_iso()

    await db.public_checkins.update_one(
        {"id": mod_id, "tenant_id": tenant_id},
        {"$set": updates},
    )
    return await _load_or_404(tenant_id, mod_id)


# ─── APPROVE ────────────────────────────────────────────────────────

class ApproveBody(BaseModel):
    reviewer_notes: Optional[str] = None


@router.post("/admin/moderation/public-checkins/{mod_id}/approve",
              operation_id="publicCheckins.approve")
async def approve_public_checkin(
    mod_id: str, body: ApproveBody,
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = caller.get("tenant_id") or ""
    row = await _load_or_404(tenant_id, mod_id)
    if row["state"] not in ("pending_review",):
        raise HTTPException(
            409, {"error": "not_pending", "state": row["state"]})

    masked = mask_address(row.get("raw_address"))
    now_ts = now_iso()
    updates = {
        "state": "approved",
        "masked_address": masked,
        "reviewed_by_user_id": caller.get("id"),
        "reviewed_at": now_ts,
        "reviewer_notes": body.reviewer_notes,
        "approved_at": now_ts,
        "approved_by_user_id": caller.get("id"),
        "updated_at": now_ts,
    }
    await db.public_checkins.update_one(
        {"id": mod_id, "tenant_id": tenant_id},
        {"$set": updates},
    )
    await _audit(caller, "public_checkin_approved", mod_id,
                   details=f"masked_street={masked['street_name']!r}")
    return await _load_or_404(tenant_id, mod_id)


# ─── REJECT ─────────────────────────────────────────────────────────

class RejectBody(BaseModel):
    reviewer_notes: str = Field(..., min_length=1)


@router.post("/admin/moderation/public-checkins/{mod_id}/reject",
              operation_id="publicCheckins.reject")
async def reject_public_checkin(
    mod_id: str, body: RejectBody,
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = caller.get("tenant_id") or ""
    row = await _load_or_404(tenant_id, mod_id)
    if row["state"] not in ("pending_review",):
        raise HTTPException(
            409, {"error": "not_pending", "state": row["state"]})

    now_ts = now_iso()
    await db.public_checkins.update_one(
        {"id": mod_id, "tenant_id": tenant_id},
        {"$set": {
            "state": "rejected",
            "reviewed_by_user_id": caller.get("id"),
            "reviewed_at": now_ts,
            "reviewer_notes": body.reviewer_notes,
            "updated_at": now_ts,
        }},
    )
    await _audit(caller, "public_checkin_rejected", mod_id)
    return await _load_or_404(tenant_id, mod_id)


# ─── UNPUBLISH ──────────────────────────────────────────────────────

@router.post("/admin/moderation/public-checkins/{mod_id}/unpublish",
              operation_id="publicCheckins.unpublish")
async def unpublish_public_checkin(
    mod_id: str,
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = caller.get("tenant_id") or ""
    row = await _load_or_404(tenant_id, mod_id)
    if row["state"] != "approved":
        raise HTTPException(
            409, {"error": "not_approved", "state": row["state"]})

    now_ts = now_iso()
    await db.public_checkins.update_one(
        {"id": mod_id, "tenant_id": tenant_id},
        {"$set": {
            "state": "unpublished",
            "unpublished_at": now_ts,
            "unpublished_by_user_id": caller.get("id"),
            "updated_at": now_ts,
        }},
    )
    await _audit(caller, "public_checkin_unpublished", mod_id)
    return await _load_or_404(tenant_id, mod_id)


# ═══════════════════════ MR-QoL · Feb-2026 — Bulk ══════════════════
# Bulk-approve / bulk-reject. Same semantics as the single-row
# variants above but batched. Hard-capped at 100 ids to keep the
# transaction small enough that a partial failure doesn't stall the
# admin UI.

_BULK_CAP = 100


class BulkApproveBody(BaseModel):
    ids: List[str] = Field(..., min_length=1)
    reviewer_notes: Optional[str] = None


class BulkRejectBody(BaseModel):
    ids: List[str] = Field(..., min_length=1)
    reviewer_notes: str = Field(..., min_length=1)


@router.post("/admin/moderation/public-checkins/bulk-approve",
              operation_id="publicCheckins.bulkApprove")
async def bulk_approve_public_checkins(
    body: BulkApproveBody,
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = caller.get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(400, {"error": "missing_tenant"})
    if len(body.ids) > _BULK_CAP:
        raise HTTPException(422, {"error": "too_many_ids",
                                     "max": _BULK_CAP})

    results: List[Dict[str, Any]] = []
    approved = 0
    skipped = 0
    for mod_id in body.ids:
        row = await db.public_checkins.find_one(
            {"id": mod_id, "tenant_id": tenant_id}, {"_id": 0})
        if not row:
            results.append({"id": mod_id, "status": "skipped",
                              "reason": "not_found"})
            skipped += 1
            continue
        if row["state"] != "pending_review":
            results.append({"id": mod_id, "status": "skipped",
                              "reason": f"state={row['state']}"})
            skipped += 1
            continue
        masked = mask_address(row.get("raw_address"))
        now_ts = now_iso()
        await db.public_checkins.update_one(
            {"id": mod_id, "tenant_id": tenant_id},
            {"$set": {
                "state": "approved",
                "masked_address": masked,
                "reviewed_by_user_id": caller.get("id"),
                "reviewed_at": now_ts,
                "reviewer_notes": body.reviewer_notes,
                "approved_at": now_ts,
                "approved_by_user_id": caller.get("id"),
                "updated_at": now_ts,
            }},
        )
        await _audit(caller, "public_checkin_approved", mod_id,
                       details="bulk")
        results.append({"id": mod_id, "status": "approved"})
        approved += 1
    return {"approved": approved, "skipped": skipped, "results": results}


@router.post("/admin/moderation/public-checkins/bulk-reject",
              operation_id="publicCheckins.bulkReject")
async def bulk_reject_public_checkins(
    body: BulkRejectBody,
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = caller.get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(400, {"error": "missing_tenant"})
    if len(body.ids) > _BULK_CAP:
        raise HTTPException(422, {"error": "too_many_ids",
                                     "max": _BULK_CAP})

    results: List[Dict[str, Any]] = []
    rejected = 0
    skipped = 0
    for mod_id in body.ids:
        row = await db.public_checkins.find_one(
            {"id": mod_id, "tenant_id": tenant_id}, {"_id": 0})
        if not row:
            results.append({"id": mod_id, "status": "skipped",
                              "reason": "not_found"})
            skipped += 1
            continue
        if row["state"] != "pending_review":
            results.append({"id": mod_id, "status": "skipped",
                              "reason": f"state={row['state']}"})
            skipped += 1
            continue
        now_ts = now_iso()
        await db.public_checkins.update_one(
            {"id": mod_id, "tenant_id": tenant_id},
            {"$set": {
                "state": "rejected",
                "reviewed_by_user_id": caller.get("id"),
                "reviewed_at": now_ts,
                "reviewer_notes": body.reviewer_notes,
                "updated_at": now_ts,
            }},
        )
        await _audit(caller, "public_checkin_rejected", mod_id,
                       details="bulk")
        results.append({"id": mod_id, "status": "rejected"})
        rejected += 1
    return {"rejected": rejected, "skipped": skipped, "results": results}
