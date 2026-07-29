"""Admin check-in overrides · Feb-2026.

Admin-only endpoints that let a manager check a tech in/out on their
behalf (or wipe a mistaken check-in). Writes into the same
``db.checkins`` collection the admin ``/checkins`` list page reads,
and records every action into ``db.admin_audit`` for compliance.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter()


def _require_admin(user: dict) -> None:
    if (user or {}).get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "admin_only")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _write_audit(*, action_type: str, admin: dict, target_user_id: str,
                        job_id: str, override_note: Optional[str],
                        previous_state: Any, tenant_id: str) -> str:
    audit_id = str(uuid.uuid4())
    await db.admin_audit.insert_one({
        "id": audit_id,
        "action_type": action_type,
        "admin_user_id": admin.get("id"),
        "admin_user_email": admin.get("email"),
        "target_user_id": target_user_id,
        "job_id": job_id,
        "timestamp": _now(),
        "override_note": override_note,
        "previous_state": previous_state,
        "tenant_id": tenant_id,
    })
    return audit_id


class AdminCheckinBody(BaseModel):
    user_id: str
    checked_in_at: Optional[str] = None
    notes: Optional[str] = None


class AdminCheckoutBody(BaseModel):
    user_id: str
    checked_out_at: Optional[str] = None
    notes: Optional[str] = None


class AdminResetBody(BaseModel):
    user_id: str
    reason: str


async def _load_job(job_id: str, tenant_id: str) -> Dict[str, Any]:
    job = await db.jobs.find_one(
        {"id": job_id, "tenant_id": tenant_id}, {"_id": 0})
    if not job:
        raise HTTPException(404, "job_not_found")
    return job


# ═════════════════════════════════════════════════════════════════════
# POST /jobs/{job_id}/checkins/admin-checkin
# ═════════════════════════════════════════════════════════════════════
@router.post("/jobs/{job_id}/checkins/admin-checkin")
async def admin_checkin(
    job_id: str,
    body: AdminCheckinBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    tenant_id = tenant["id"]
    await _load_job(job_id, tenant_id)

    ts = body.checked_in_at or _now().isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "job_id": job_id,
        "user_id": body.user_id,
        "event": "admin_checkin",
        "checked_in_at": ts,
        "checked_out_at": None,
        "created_at": ts,
        "overridden_by_admin": True,
        "override_admin_id": user.get("id"),
        "override_note": body.notes,
    }
    await db.checkins.insert_one(dict(doc))
    doc.pop("_id", None)
    audit_id = await _write_audit(
        action_type="admin_checkin",
        admin=user,
        target_user_id=body.user_id,
        job_id=job_id,
        override_note=body.notes,
        previous_state=None,
        tenant_id=tenant_id,
    )
    return {"ok": True, "checkin": doc, "audit_id": audit_id}


# ═════════════════════════════════════════════════════════════════════
# POST /jobs/{job_id}/checkins/admin-checkout
# ═════════════════════════════════════════════════════════════════════
@router.post("/jobs/{job_id}/checkins/admin-checkout")
async def admin_checkout(
    job_id: str,
    body: AdminCheckoutBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    tenant_id = tenant["id"]
    await _load_job(job_id, tenant_id)

    open_ci = await db.checkins.find_one(
        {"tenant_id": tenant_id, "job_id": job_id,
          "user_id": body.user_id, "checked_out_at": None},
        {"_id": 0}, sort=[("created_at", -1)],
    )
    if not open_ci:
        raise HTTPException(404, "no_open_checkin")

    ts = body.checked_out_at or _now().isoformat()
    upd = {
        "checked_out_at": ts,
        "overridden_by_admin": True,
        "override_admin_id": user.get("id"),
        "override_note": body.notes,
    }
    await db.checkins.update_one({"id": open_ci["id"]}, {"$set": upd})
    audit_id = await _write_audit(
        action_type="admin_checkout",
        admin=user,
        target_user_id=body.user_id,
        job_id=job_id,
        override_note=body.notes,
        previous_state={"checkin_id": open_ci["id"],
                        "checked_in_at": open_ci.get("checked_in_at")},
        tenant_id=tenant_id,
    )
    updated = await db.checkins.find_one({"id": open_ci["id"]}, {"_id": 0})
    return {"ok": True, "checkin": updated, "audit_id": audit_id}


# ═════════════════════════════════════════════════════════════════════
# POST /jobs/{job_id}/checkins/admin-reset
# ═════════════════════════════════════════════════════════════════════
@router.post("/jobs/{job_id}/checkins/admin-reset")
async def admin_reset(
    job_id: str,
    body: AdminResetBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    if not (body.reason or "").strip():
        raise HTTPException(400, "reason_required")
    tenant_id = tenant["id"]
    await _load_job(job_id, tenant_id)

    existing = await db.checkins.find(
        {"tenant_id": tenant_id, "job_id": job_id, "user_id": body.user_id},
        {"_id": 0},
    ).to_list(500)
    if not existing:
        # Idempotent — nothing to reset but still audit-log the attempt.
        audit_id = await _write_audit(
            action_type="admin_reset",
            admin=user, target_user_id=body.user_id, job_id=job_id,
            override_note=body.reason, previous_state=[],
            tenant_id=tenant_id,
        )
        return {"ok": True, "cleared": 0, "audit_id": audit_id}

    r = await db.checkins.delete_many(
        {"tenant_id": tenant_id, "job_id": job_id, "user_id": body.user_id})
    audit_id = await _write_audit(
        action_type="admin_reset",
        admin=user, target_user_id=body.user_id, job_id=job_id,
        override_note=body.reason,
        previous_state=existing,
        tenant_id=tenant_id,
    )
    return {"ok": True, "cleared": r.deleted_count, "audit_id": audit_id}


# ═════════════════════════════════════════════════════════════════════
# GET /jobs/{job_id}/checkins  (admin — used by the row buttons)
# ═════════════════════════════════════════════════════════════════════
@router.get("/jobs/{job_id}/checkins")
async def get_job_checkins(
    job_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    tenant_id = tenant["id"]
    rows = await db.checkins.find(
        {"tenant_id": tenant_id, "job_id": job_id}, {"_id": 0},
    ).sort("created_at", -1).to_list(500)
    return {"items": rows, "total": len(rows)}
