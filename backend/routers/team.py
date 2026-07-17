from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, EmailStr

from config import db, logger, EMERGENT_LLM_KEY
from routers.tenants import get_current_tenant
from routers.portal_admin import _random_password
from services.notifications import emit as notify_emit
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from models import *

router = APIRouter()

# Phase 57 / 56.3.B — valid department values on user docs.
#   None            → unassigned
#   "pool"          → pool-only tech
#   "landscaping"   → landscape-only tech
#   "both"          → union: user can access pool AND landscape checklists / nav.
#                    Valid for `technician` (Pool + Landscape tech) AND `admin`
#                    (Admin + full tech surface, i.e. the roster "All" option).
_DEPARTMENTS = {"pool", "landscaping", "both"}
# Phase 56.3.B — roles the admin roster widget may assign. `super_admin`
# is protected and can never be assigned or removed via this widget.
_ASSIGNABLE_ROLES = {"admin", "technician"}


# Phase 56.3.B (refined) — human-readable enum for the unified
# role/department picker in the roster UI. `admin + both` = "All":
# admin RBAC everywhere PLUS the union of pool + landscape tech surfaces.
_ROLE_DEPT_COMBOS = {
    ("technician", "pool"):        "Pool Tech",
    ("technician", "landscaping"): "Landscape Tech",
    ("admin", None):               "Admin",
    ("admin", "both"):             "All (Admin + Pool + Landscape)",
}
# Departments that are valid for a given role. Anything outside this
# whitelist → 400.
_VALID_DEPTS_BY_ROLE = {
    "technician": {"pool", "landscaping", None},
    "admin":      {"both", None},
}


class NewUserIn(BaseModel):
    """Phase 56.3.B — payload for `POST /api/users` (Add Team Member modal).
    Both first + last are required; the widget composes them into `name`.
    `phone` is optional and normalized to E.164 on write when possible.
    `role` + `department` must resolve to a valid combo per
    `_VALID_DEPTS_BY_ROLE`."""
    first_name: str
    last_name: str
    email: EmailStr
    phone: Optional[str] = ""
    role: str = "technician"
    department: Optional[str] = None
    send_invite_email: Optional[bool] = True


@router.post("/users")
async def create_team_user(body: NewUserIn,
                            actor: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    """Phase 56.3.B — Add Team Member endpoint powering the roster modal.

    • Admin + super_admin only (via `require_admin`).
    • Validates the (role, department) combo against `_VALID_DEPTS_BY_ROLE`.
    • Rejects `super_admin` role assignment (protected).
    • Rejects duplicate emails (case-insensitive) with 409.
    • Generates a temp password server-side and returns it ONCE in the
      response body so the admin can relay it manually (email delivery
      is MOCKED via `email_delivery_log`).
    • Emits Phase-55 notifications to the new user + all other admins.
    """
    first = (body.first_name or "").strip()
    last = (body.last_name or "").strip()
    if not first or not last:
        raise HTTPException(400, "first_name and last_name are required")

    email = (body.email or "").strip().lower()

    role = (body.role or "").strip().lower()
    if role not in _ASSIGNABLE_ROLES:
        raise HTTPException(400, f"role must be one of: {sorted(_ASSIGNABLE_ROLES)}")

    # Normalize department per role.
    dept_raw = body.department
    if dept_raw is None or dept_raw == "":
        new_dept = None
    else:
        new_dept = str(dept_raw).strip().lower()
        if new_dept not in _DEPARTMENTS:
            raise HTTPException(400, f"department must be one of: {sorted(_DEPARTMENTS)} or null")
    if new_dept not in _VALID_DEPTS_BY_ROLE.get(role, {None}):
        raise HTTPException(
            400,
            f"department '{new_dept}' is not valid for role '{role}' "
            f"(allowed: {sorted([d for d in _VALID_DEPTS_BY_ROLE[role] if d]) or ['null']})",
        )

    # Case-insensitive email duplicate check (across whole users collection).
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(409, "An account with this email already exists")

    # Optional E.164 normalization — best-effort; keep raw if it can't be normalized.
    phone_normalized = ""
    if body.phone:
        try:
            from routers.ringcentral import _normalize_phone_e164
            phone_normalized = _normalize_phone_e164(body.phone) or (body.phone or "").strip()
        except Exception:
            phone_normalized = (body.phone or "").strip()

    temp_password = _random_password()
    user_id = new_id()
    doc = {
        "id": user_id,
        "tenant_id": tenant["id"],
        "email": email,
        "name": f"{first} {last}".strip(),
        "first_name": first,
        "last_name": last,
        "phone": phone_normalized,
        "role": role,
        "department": new_dept,
        "password_hash": hash_password(temp_password),
        "created_at": now_iso(),
        "created_by_user_id": actor.get("id"),
    }
    # `technician_id` — the app's tech-lookup key is a separate ID column on
    # the user doc. Match the pattern used by seeds / create-login flow so
    # tech-specific joins keep working.
    if role == "technician":
        doc["technician_id"] = new_id()
    await db.users.insert_one(doc)

    # Audit log.
    await db.audit_log.insert_one({
        "id": new_id(),
        "tenant_id": tenant["id"],
        "actor_user_id": actor.get("id"),
        "actor_email": actor.get("email"),
        "action": "user.create",
        "target_user_id": user_id,
        "changes": {
            "role": {"old": None, "new": role},
            "department": {"old": None, "new": new_dept},
            "email": {"old": None, "new": email},
        },
        "at": now_iso(),
    })

    # MOCKED invite delivery — log to email_delivery_log so it shows up in
    # the admin's delivery report. Real email lands when Resend is wired.
    if body.send_invite_email:
        try:
            await db.email_delivery_log.insert_one({
                "id": new_id(),
                "tenant_id": tenant["id"],
                "to": email,
                "subject": "You have been added to the team",
                "template": "team_invite",
                "status": "mocked",
                "provider": "resend_fallback_mock",
                "sent_at": now_iso(),
                "meta": {"user_id": user_id, "role": role, "department": new_dept},
            })
        except Exception:
            pass

    # Phase 55 fan-out.
    try:
        await notify_emit(
            [user_id], kind="system_alert",
            title="Welcome to the team",
            body=f"Your {role} account was created. Sign in to get started.",
            href="/",
            tenant_id=tenant["id"], audience="internal",
            source_ref={"kind": "user_create", "id": user_id},
        )
        admins = await db.users.find(
            {"tenant_id": tenant["id"], "role": {"$in": ["admin", "super_admin"]},
             "id": {"$ne": actor.get("id")}},
            {"_id": 0, "id": 1},
        ).to_list(200)
        aids = [a["id"] for a in admins if a.get("id")]
        if aids:
            label = _ROLE_DEPT_COMBOS.get((role, new_dept), role.capitalize())
            await notify_emit(
                aids, kind="system_alert",
                title=f"New team member {doc['name']} added as {label}",
                body=f"{actor.get('name') or 'Admin'} added a new team member.",
                href="/team", tenant_id=tenant["id"], audience="internal",
                source_ref={"kind": "user_create", "id": user_id},
            )
    except Exception:
        pass

    return {
        "ok": True,
        "user_id": user_id,
        "email": email,
        "role": role,
        "department": new_dept,
        # Returned ONCE for the admin to relay — client should not persist.
        "temp_password": temp_password,
        "invite_email_status": "mocked" if body.send_invite_email else "skipped",
    }



@router.get("/team/role-options")
async def team_role_options(user: dict = Depends(require_admin)):
    """Return the canonical (role, department) → label mapping used by the
    roster picker on both surfaces. Keeps mobile / web / any future UI in
    lockstep with the backend enum."""
    return {
        "options": [
            {"role": r, "department": d, "label": lbl}
            for (r, d), lbl in _ROLE_DEPT_COMBOS.items()
        ],
        "departments": sorted(_DEPARTMENTS),
    }


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
    """Phase 57 / 56.3.B — role + department updates from the roster UI.

    Accepts (both optional in a single call):
      • ``department`` — one of `pool | landscaping | both | null`.
      • ``role``       — one of `admin | technician`. `super_admin`
                         cannot be assigned or removed via this endpoint.

    Guardrails:
      • Only admin / super_admin (via `require_admin`) can call.
      • `super_admin` targets are protected — 403 with a clean message.
      • Callers cannot change their own role (self-demotion attack).
      • Assigning `role = "admin"` clears `department` (admins have no
        department concept in this app).
      • Unknown fields → 400 so we don't silently accept e.g. `password`.
    Emits a Phase-55 notification to the target user AND all tenant
    admins, and writes an audit-log row.
    """
    target = await db.users.find_one({"id": user_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not target:
        raise HTTPException(404, "User not found")

    # Phase 56.3.B — super_admin is never assignable / demotable via this UI.
    if (target.get("role") or "").lower() == "super_admin":
        raise HTTPException(403, "super_admin accounts cannot be modified from the roster widget.")

    allowed_fields = {"department", "role"}
    unknown = set(body.keys()) - allowed_fields
    if unknown:
        raise HTTPException(400, f"unsupported fields: {sorted(unknown)}")

    updates: dict = {}
    audit_changes: dict = {}

    # Compute the *new* role first — department validation depends on it.
    new_role = None
    if "role" in body:
        # Self-demotion protection.
        if user_id == user.get("id"):
            raise HTTPException(403, "You cannot change your own role.")
        raw_role = str(body.get("role") or "").strip().lower()
        if raw_role not in _ASSIGNABLE_ROLES:
            raise HTTPException(400, f"role must be one of: {sorted(_ASSIGNABLE_ROLES)}")
        new_role = raw_role

    effective_role = new_role if new_role is not None else (target.get("role") or "").lower()

    if "department" in body:
        dept = body["department"]
        if dept is None or dept == "":
            new_dept = None
        else:
            dept_norm = str(dept).strip().lower()
            if dept_norm not in _DEPARTMENTS:
                raise HTTPException(
                    400,
                    f"department must be one of: {sorted(_DEPARTMENTS)} or null",
                )
            new_dept = dept_norm
        # Phase 56.3.B (refined) — enforce per-role department whitelist.
        # `admin` may only have department = "both" or null (unassigned).
        # `technician` may have "pool", "landscaping", or null.
        valid_for_role = _VALID_DEPTS_BY_ROLE.get(effective_role, {None})
        if new_dept not in valid_for_role:
            raise HTTPException(
                400,
                f"department '{new_dept}' is not valid for role '{effective_role}' "
                f"(allowed: {sorted([d for d in valid_for_role if d]) or ['null']})",
            )
        old_dept = target.get("department") or None
        if new_dept != old_dept:
            updates["department"] = new_dept
            audit_changes["department"] = {"old": old_dept, "new": new_dept}
    elif new_role is not None:
        # No department field in body but role changed — normalize stale
        # departments that are no longer valid for the new role.
        cur = target.get("department") or None
        allowed = _VALID_DEPTS_BY_ROLE.get(new_role, {None})
        if cur not in allowed:
            updates["department"] = None
            audit_changes["department"] = {"old": cur, "new": None}

    if new_role is not None and new_role != (target.get("role") or "").lower():
        updates["role"] = new_role
        audit_changes["role"] = {"old": target.get("role"), "new": new_role}

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
        parts = []
        if "role" in updates:
            parts.append(f"role → {updates['role']}")
        if "department" in updates:
            d = updates["department"]
            parts.append(f"department → {d.capitalize() if d else 'Unassigned'}")
        summary = ", ".join(parts) if parts else "profile updated"
        await notify_emit(
            [user_id], kind="system_alert",
            title="Your access was updated",
            body=f"An admin updated your account: {summary}.",
            href="/",
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
                title=f"{target.get('name') or target.get('email') or 'Team member'} — {summary}",
                body=f"{user.get('name') or 'Admin'} updated the roster.",
                href="/team", tenant_id=tenant["id"], audience="internal",
                source_ref={"kind": "user_update", "id": user_id},
            )
    except Exception:
        pass

    return {"ok": True, "user_id": user_id, "changes": audit_changes}



