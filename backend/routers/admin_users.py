"""Feb-2026 · Admin password + user lifecycle tools.

Endpoints:
* ``POST /api/users/{id}/reset-password`` — auto-generates (or accepts)
  a temp password, emails via Resend, flips
  ``users.must_change_password_on_next_login=true``. Admin + super_admin
  can reset any non-super_admin user; super_admin required to reset
  another super_admin.
* ``DELETE /api/users/{id}`` — soft-delete a team member. Blocks the
  last super_admin. Reassigns any actively-scheduled jobs owned by
  this user to an "Unassigned" placeholder and cancels active
  route_assignment_overrides involving this user.

Frontend surfaces (Team page reset/delete + Customer detail
"Reset password") consume these endpoints.
"""
from __future__ import annotations

import os
import secrets
import string
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import (
    get_current_user, hash_password, new_id, now_iso,
)

router = APIRouter(tags=["Admin Users"])

_ADMIN_ROLES = {"admin", "super_admin"}
_STRONG_ALPHA = string.ascii_letters + string.digits + "!@#$%^*+-="


def _strong_password(n: int = 16) -> str:
    """16-char cryptographically random password with mixed alphanum
    + safe symbols. Always includes at least one of each class so
    downstream password-policy checks pass."""
    while True:
        pw = "".join(secrets.choice(_STRONG_ALPHA) for _ in range(n))
        if (any(c.islower() for c in pw)
                and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw)
                and any(c in "!@#$%^*+-=" for c in pw)):
            return pw


def _require_admin(user: Dict[str, Any]) -> None:
    if user.get("role") not in _ADMIN_ROLES:
        raise HTTPException(403, "Admin only")


def _password_reset_html(
    *, target_name: str, actor_name: str, company_name: str,
    temp_password: str, login_url: str,
) -> str:
    return f"""<!doctype html>
<html><body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#f4f6f8;padding:24px 0;margin:0;color:#111827">
<div style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:12px;padding:28px 30px;box-shadow:0 1px 3px rgba(0,0,0,.06)">
  <h1 style="margin:0 0 12px 0;font-size:20px">Password reset by admin</h1>
  <p style="margin:0 0 16px 0;line-height:1.55">
    Hi {target_name}, {actor_name} reset your {company_name} password.
    Sign in with the temporary password below — you'll be asked to
    choose a new password immediately on first login.
  </p>
  <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:14px 16px;margin:0 0 20px 0">
    <div style="font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:.4px;margin-bottom:4px">Temporary password</div>
    <div style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:15px;font-weight:600">{temp_password}</div>
  </div>
  <p style="text-align:center;margin:0 0 22px 0">
    <a href="{login_url}" style="background:#0f766e;color:#ffffff;padding:11px 22px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block">Sign in</a>
  </p>
  <p style="font-size:12px;color:#6b7280;margin:0">
    If this wasn't you, contact your administrator immediately.
  </p>
</div>
</body></html>"""


async def _send_password_reset_email(
    *, tenant: Dict[str, Any], actor: Dict[str, Any],
    target: Dict[str, Any], temp_password: str,
) -> str:
    from services.email.resend_adapter import send as _resend_send
    from urllib.parse import urljoin

    settings = tenant.get("settings") or {}
    card = settings.get("business_card") or {}
    company_display = card.get("company_name") or tenant.get("name") or "AquaTerra"
    origin = os.environ.get("FRONTEND_BASE_URL") or "https://app.aquaterra.com"
    login_url = urljoin(origin.rstrip("/") + "/", "login")
    subject = f"Your {company_display} password was reset"
    html = _password_reset_html(
        target_name=target.get("first_name") or target.get("name") or "there",
        actor_name=actor.get("name") or actor.get("email") or "An admin",
        company_name=company_display,
        temp_password=temp_password,
        login_url=login_url,
    )
    result = await _resend_send(
        to=target["email"], subject=subject, html=html,
        category="transactional",
        idempotency_key=f"pwreset-{target['id']}-{new_id()}",
        tenant_id=tenant["id"],
    )
    status = result.get("provider_status") or "failed"
    try:
        await db.communications_log.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "channel": "email",
            "to": target["email"],
            "subject": subject,
            "template": "password_reset_by_admin_email",
            "status": status,
            "provider": result.get("provider") or "resend",
            "provider_response_id": result.get("provider_response_id"),
            "error": result.get("error"),
            "trigger_entity": {"kind": "password_reset_admin", "id": target["id"]},
            "created_at": now_iso(),
        })
        await db.marketing_deliveries.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "channel": "email",
            "recipient_address": target["email"],
            "template_code": "password_reset_by_admin_email",
            "subject": subject,
            "delivery_status": "sent" if status == "sent" else status,
            "provider_status": status,
            "trigger_kind": "password_reset_admin",
            "trigger_entity": {"kind": "password_reset_admin", "id": target["id"]},
            "created_at": now_iso(),
        })
    except Exception as e:
        logger.warning(f"password-reset comms log write failed: {e}")
    return status


class ResetPasswordIn(BaseModel):
    new_password: Optional[str] = None


@router.post("/users/{uid}/reset-password",
              operation_id="adminUsers.resetPassword")
async def reset_password(
    uid: str,
    body: ResetPasswordIn,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_admin(user)
    target = await db.users.find_one({"id": uid}, {"_id": 0})
    if not target:
        raise HTTPException(404, "User not found")

    # A regular admin cannot reset a super_admin. Only another
    # super_admin can.
    if target.get("role") == "super_admin" and user.get("role") != "super_admin":
        raise HTTPException(403, "Only a super_admin can reset another super_admin's password")

    # Cross-tenant reset requires super_admin.
    if user.get("role") == "admin":
        if target.get("tenant_id") != user.get("tenant_id"):
            raise HTTPException(403, "Cross-tenant password reset requires super_admin")

    if body.new_password:
        new_pw = str(body.new_password)
        if len(new_pw) < 8:
            raise HTTPException(400, "new_password must be at least 8 chars")
    else:
        new_pw = _strong_password()

    await db.users.update_one(
        {"id": uid},
        {"$set": {"password_hash": hash_password(new_pw),
                    "must_change_password_on_next_login": True,
                    "password_reset_at": now_iso(),
                    "password_reset_by_user_id": user.get("id")}},
    )

    tenant = await db.tenants.find_one(
        {"id": target.get("tenant_id")}, {"_id": 0},
    ) or {}
    email_status = await _send_password_reset_email(
        tenant=tenant, actor=user, target=target, temp_password=new_pw,
    )

    await db.audit_log.insert_one({
        "id": new_id(),
        "tenant_id": target.get("tenant_id"),
        "actor_user_id": user.get("id"),
        "actor_email": user.get("email"),
        "action": "user.password_reset",
        "target_user_id": uid,
        "changes": {"must_change_password_on_next_login": True},
        "at": now_iso(),
    })

    return {
        "ok": True,
        "user_id": uid,
        # Returned ONCE so the admin can copy + relay if the email
        # bounced. Client should not persist.
        "temporary_password": new_pw,
        "email_status": email_status,
    }


@router.delete("/users/{uid}", operation_id="adminUsers.delete")
async def delete_user(
    uid: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_admin(user)
    if uid == user.get("id"):
        raise HTTPException(400, "You cannot delete your own user")

    target = await db.users.find_one({"id": uid}, {"_id": 0})
    if not target:
        raise HTTPException(404, "User not found")
    if target.get("deleted_at"):
        return {"ok": True, "already_deleted": True}

    # Guardrail: block deletion of the last super_admin in a tenant.
    if target.get("role") == "super_admin":
        live_supers = await db.users.count_documents({
            "tenant_id": target.get("tenant_id"),
            "role": "super_admin",
            "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}],
        })
        if live_supers <= 1:
            raise HTTPException(409, "Cannot delete the last super_admin in this tenant")

    # A regular admin cannot delete a super_admin.
    if target.get("role") == "super_admin" and user.get("role") != "super_admin":
        raise HTTPException(403, "Only a super_admin can delete another super_admin")

    # Cross-tenant delete requires super_admin.
    if user.get("role") == "admin":
        if target.get("tenant_id") != user.get("tenant_id"):
            raise HTTPException(403, "Cross-tenant delete requires super_admin")

    # Cascade — reassign any scheduled jobs to an "Unassigned"
    # placeholder tech id so schedule + dispatch don't break.
    unassigned_placeholder = "unassigned"
    reassigned_jobs: list = []
    async for j in db.jobs.find({
        "tenant_id": target.get("tenant_id"),
        "$or": [{"technician_id": target.get("id")},
                 {"assigned_tech_id": target.get("id")}],
        "status": {"$in": ["scheduled", "active", "in_progress"]},
    }, {"_id": 0, "id": 1}):
        reassigned_jobs.append(j["id"])
    if reassigned_jobs:
        await db.jobs.update_many(
            {"id": {"$in": reassigned_jobs}},
            {"$set": {"technician_id": unassigned_placeholder,
                        "assigned_tech_id": unassigned_placeholder,
                        "reassigned_from_user_id": uid,
                        "reassigned_at": now_iso()}},
        )
    # Cancel active route_assignment_overrides involving the user.
    try:
        await db.route_assignment_overrides.update_many(
            {"tenant_id": target.get("tenant_id"),
             "$or": [{"source_tech_user_id": uid},
                     {"target_tech_user_id": uid}],
             "status": {"$in": ["active", "scheduled"]}},
            {"$set": {"status": "canceled",
                        "canceled_at": now_iso(),
                        "canceled_reason": "owner_deleted"}},
        )
    except Exception as e:
        logger.warning(f"delete_user override cancel failed: {e}")

    await db.users.update_one(
        {"id": uid},
        {"$set": {"deleted_at": now_iso(),
                    "deleted_by_user_id": user.get("id")}},
    )

    await db.audit_log.insert_one({
        "id": new_id(),
        "tenant_id": target.get("tenant_id"),
        "actor_user_id": user.get("id"),
        "actor_email": user.get("email"),
        "action": "user.delete",
        "target_user_id": uid,
        "changes": {"deleted_at": {"old": None, "new": True}},
        "notes": f"reassigned {len(reassigned_jobs)} job(s)",
        "at": now_iso(),
    })

    return {
        "ok": True, "user_id": uid,
        "reassigned_jobs": len(reassigned_jobs),
    }


# ─────────────────────────────────────────────────────────────────────
# Feb-2026 · Phase 26 Path B · super_admin ops endpoints
# ─────────────────────────────────────────────────────────────────────
# `POST /api/users/{uid}/unlock`   — clear a locked-out account so the
#     user can log in without waiting the 15-min lockout window. Fills
#     the gap between the admin password reset flow and the login-side
#     lockout enforcement (which the ``reset-password`` endpoint does
#     NOT auto-clear).
# `POST /api/users/{uid}/promote`  — change a user's role. Includes two
#     guardrails: no self-role-change and no demoting the last remaining
#     super_admin.
# Both endpoints are super_admin only.


_ASSIGNABLE_ROLE_SET = {"super_admin", "admin", "manager", "technician",
                          "customer"}


def _require_super_admin(user: Dict[str, Any]) -> None:
    if user.get("role") != "super_admin":
        raise HTTPException(403, "super_admin only")


@router.post("/users/{uid}/unlock",
              operation_id="adminUsers.unlock")
async def unlock_user(
    uid: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Clear ``failed_login_attempts`` + ``lockout_until`` on the target
    user's record so they can log in without waiting the auto-expiry.
    Idempotent — safe to call on an already-unlocked user.
    """
    _require_super_admin(user)
    target = await db.users.find_one({"id": uid}, {"_id": 0})
    if not target:
        raise HTTPException(400, "User not found")

    was_locked = bool(target.get("lockout_until")) or bool(
        target.get("failed_login_attempts"))

    cleared_at = now_iso()
    await db.users.update_one(
        {"id": uid},
        {"$set": {"failed_login_attempts": 0,
                    "lockout_until": None,
                    "unlocked_at": cleared_at,
                    "unlocked_by_user_id": user.get("id")}},
    )

    if was_locked:
        try:
            await db.audit_log.insert_one({
                "id": new_id(),
                "tenant_id": target.get("tenant_id"),
                "actor_user_id": user.get("id"),
                "actor_email": user.get("email"),
                "action": "user.unlock",
                "target_user_id": uid,
                "changes": {
                    "failed_login_attempts": {
                        "old": int(target.get("failed_login_attempts") or 0),
                        "new": 0,
                    },
                    "lockout_until": {
                        "old": target.get("lockout_until"),
                        "new": None,
                    },
                },
                "at": cleared_at,
            })
        except Exception as e:  # pragma: no cover — audit is best-effort
            logger.warning(f"unlock_user audit failed: {e}")

    return {
        "ok": True,
        "user_id": uid,
        "was_locked": was_locked,
        "cleared_at": cleared_at,
    }


class PromoteIn(BaseModel):
    role: str = Field(..., description="One of: super_admin, admin, manager, technician, customer")


@router.post("/users/{uid}/promote",
              operation_id="adminUsers.promote")
async def promote_user(
    uid: str,
    body: PromoteIn,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Change the target user's ``role`` field. super_admin only.

    Guardrails:
      * Callers cannot change their own role.
      * The last remaining ``super_admin`` in a tenant cannot be
        demoted (would lock the tenant out of super-admin-only
        surfaces).
      * Role must be one of the codebase's recognized roles.
    """
    _require_super_admin(user)
    new_role = (body.role or "").strip().lower()
    if new_role not in _ASSIGNABLE_ROLE_SET:
        raise HTTPException(400,
            f"Invalid role '{body.role}'. Allowed: "
            f"{sorted(_ASSIGNABLE_ROLE_SET)}")

    target = await db.users.find_one({"id": uid}, {"_id": 0})
    if not target:
        raise HTTPException(400, "User not found")

    if uid == user.get("id"):
        raise HTTPException(400, "You cannot change your own role")

    old_role = target.get("role")
    if old_role == new_role:
        return {"ok": True, "user_id": uid,
                "old_role": old_role, "new_role": new_role,
                "no_change": True}

    # Guardrail: refuse to demote the last remaining super_admin in the tenant.
    if old_role == "super_admin" and new_role != "super_admin":
        other_supers = await db.users.count_documents({
            "tenant_id": target.get("tenant_id"),
            "role": "super_admin",
            "id": {"$ne": uid},
            "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}],
        })
        if other_supers <= 0:
            raise HTTPException(400,
                "Cannot demote the last remaining super_admin in this tenant")

    changed_at = now_iso()
    await db.users.update_one(
        {"id": uid},
        {"$set": {"role": new_role,
                    "role_changed_at": changed_at,
                    "role_changed_by_user_id": user.get("id")}},
    )

    try:
        await db.audit_log.insert_one({
            "id": new_id(),
            "tenant_id": target.get("tenant_id"),
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "action": "user.role_change",
            "target_user_id": uid,
            "changes": {"role": {"old": old_role, "new": new_role}},
            "at": changed_at,
        })
    except Exception as e:  # pragma: no cover — audit is best-effort
        logger.warning(f"promote_user audit failed: {e}")

    return {
        "ok": True,
        "user_id": uid,
        "old_role": old_role,
        "new_role": new_role,
    }

