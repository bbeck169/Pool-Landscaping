from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel

from config import db, logger, EMERGENT_LLM_KEY
from routers.tenants import get_current_tenant
from services.notifications import emit as notify_emit
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from models import *

router = APIRouter()

# Phase 57 — valid department values on user docs. `None` = unassigned.
_DEPARTMENTS = {"pool", "landscaping"}


# ----------------------- Team -----------------------
@router.get("/team")
async def list_team(user: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    users = await db.users.find(
        {"role": {"$in": ["admin", "technician"]}, "tenant_id": tenant["id"]},
        {"_id": 0, "password_hash": 0},
    ).to_list(1000)
    for u in users:
        if u.get("technician_id"):
            u["active_jobs"] = await db.jobs.count_documents({
                "technician_id": u["technician_id"],
                "status": {"$in": ["pending", "active"]},
            })
    return users


class UserPatch(BaseModel):
    """Phase 57 · PATCH payload for /users/{id}. ``department`` is
    ``"pool" | "landscaping" | None`` — ``None`` unassigns. Any other
    value → 400."""
    department: Optional[str] = None
    department_set: bool = True  # mark that department was intentionally sent


@router.get("/users/{user_id}")
async def get_user(user_id: str,
                    user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant)):
    """Phase 57.d — single-user read. Admin/super_admin can read anyone
    in the tenant; every other role can read only themselves."""
    role = (user or {}).get("role") or ""
    if role not in ("admin", "super_admin") and user_id != user.get("id"):
        raise HTTPException(403, "Not authorized")
    doc = await db.users.find_one({"id": user_id, "tenant_id": tenant["id"]},
                                    {"_id": 0, "password_hash": 0}) or None
    if not doc:
        raise HTTPException(404, "User not found")
    return doc


@router.patch("/users/{user_id}")
async def update_user(user_id: str, body: dict,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    """Phase 57 — currently limited to setting ``department`` on
    technician users. Everything else is rejected so we don't
    inadvertently expose sensitive fields (role, password, email)
    through a permissive PATCH. Emits a Phase-55 notification to the
    target user AND all tenant admins, and writes an audit-log row.
    """
    target = await db.users.find_one({"id": user_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not target:
        raise HTTPException(404, "User not found")

    allowed_fields = {"department"}
    unknown = set(body.keys()) - allowed_fields
    if unknown:
        raise HTTPException(400, f"unsupported fields: {sorted(unknown)}")

    updates: dict = {}
    audit_changes: dict = {}

    if "department" in body:
        role = (target.get("role") or "").lower()
        if role not in ("technician", "landscape_tech"):
            raise HTTPException(400, "department can only be set on technician users")
        dept = body["department"]
        if dept is None or dept == "":
            new_dept = None
        else:
            dept_norm = str(dept).strip().lower()
            if dept_norm not in _DEPARTMENTS:
                raise HTTPException(400, "department must be one of: pool, landscaping, null")
            new_dept = dept_norm
        old_dept = target.get("department") or None
        if new_dept != old_dept:
            updates["department"] = new_dept
            audit_changes["department"] = {"old": old_dept, "new": new_dept}

    if not updates:
        return {"ok": True, "unchanged": True, "user_id": user_id}

    await db.users.update_one(
        {"id": user_id, "tenant_id": tenant["id"]},
        {"$set": {**updates, "updated_at": now_iso()}},
    )

    # Audit log.
    await db.audit_log.insert_one({
        "id": new_id(),
        "tenant_id": tenant["id"],
        "actor_user_id": user.get("id"),
        "actor_email": user.get("email"),
        "action": "user.update",
        "target_user_id": user_id,
        "changes": audit_changes,
        "at": now_iso(),
    })

    # Phase-55 notification fan-out.
    try:
        if "department" in updates:
            new_dept = updates["department"]
            dept_label = new_dept.capitalize() if new_dept else "Unassigned"
            body_txt = (f"Your department has been set to {dept_label}." if new_dept
                         else "Your department was cleared. Contact your admin for reassignment.")
            await notify_emit(
                [user_id], kind="system_alert",
                title="Department updated",
                body=body_txt, href="/",
                tenant_id=tenant["id"], audience="internal",
                source_ref={"kind": "user_update", "id": user_id},
            )
            # Also inform other admins so the roster stays visible.
            admins = await db.users.find(
                {"tenant_id": tenant["id"], "role": {"$in": ["admin", "super_admin"]},
                 "id": {"$ne": user.get("id")}},
                {"_id": 0, "id": 1},
            ).to_list(200)
            aids = [a["id"] for a in admins if a.get("id")]
            if aids:
                await notify_emit(
                    aids, kind="system_alert",
                    title=f"{target.get('name') or target.get('email') or 'Tech'} → {dept_label}",
                    body=f"{user.get('name') or 'Admin'} updated the department.",
                    href="/team", tenant_id=tenant["id"], audience="internal",
                    source_ref={"kind": "user_update", "id": user_id},
                )
    except Exception:
        pass

    return {"ok": True, "user_id": user_id, "changes": audit_changes}



