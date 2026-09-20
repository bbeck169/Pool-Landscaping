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
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import (
    get_current_user, hash_password, new_id, now_iso,
)

router = APIRouter(tags=["Admin Users"])

_ADMIN_ROLES = {"admin", "super_admin"}


# Feb-2026 · GET /api/users listing — powers the Dispatch Board tech
# dropdown and any admin surface that needs a filtered users list.
# The Team router already owns POST /api/users (create) so this GET
# cohabits at the same path via a distinct HTTP verb.
@router.get("/users", operation_id="adminUsers.list")
async def list_users(
    role: Optional[str] = None,
    active: Optional[bool] = True,
    limit: int = 100,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """List users for the caller's tenant.

    * Admin+ / super_admin only (403 otherwise).
    * ``role`` optional — case-insensitive exact match (e.g. ``technician``).
    * ``active`` default ``true`` — excludes soft-deleted rows. Pass
      ``active=false`` to see only soft-deleted users.
    * ``limit`` default 100, capped at 500.

    Returns ``{ users: [{ id, name, email, role, is_active, department }] }``.
    """
    if user.get("role") not in _ADMIN_ROLES:
        raise HTTPException(403, "Admin only")

    limit = max(1, min(500, int(limit)))
    q: Dict[str, Any] = {"tenant_id": user.get("tenant_id")}
    if role:
        q["role"] = str(role).strip().lower()
    if active is False:
        # Soft-deleted only.
        q["deleted_at"] = {"$ne": None}
    else:
        # Default: exclude soft-deleted rows.
        q["$or"] = [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]

    projection = {
        "_id": 0, "id": 1, "name": 1, "email": 1, "role": 1,
        "is_active": 1, "department": 1,
    }
    rows: list = []
    async for u in db.users.find(q, projection).limit(limit):
        rows.append({
            "id": u.get("id"),
            "name": u.get("name") or "",
            "email": u.get("email") or "",
            "role": u.get("role"),
            "department": u.get("department"),
            "is_active": bool(u.get("is_active"))
                          if u.get("is_active") is not None else True,
        })
    return {"users": rows, "count": len(rows)}
_STRONG_ALPHA = string.ascii_letters + string.digits + "!@#$%^*+-="

# Feb-2026 · Team page admin actions — permission matrix.
# A regular ``admin`` can only reset / delete "tech" targets. The brief
# lists ``pool_tech``/``landscape_tech``/``technician`` — this codebase
# models pool_tech and landscape_tech as ``role="technician"`` with
# ``department in {pool, landscaping}``, so treating any ``technician``
# row as a valid admin target matches the intent (and the visible
# labels on the Team page).
_TECH_ROLES = {"technician", "pool_tech", "landscape_tech"}


def _is_tech_target(target: Dict[str, Any]) -> bool:
    return (target or {}).get("role", "").lower() in _TECH_ROLES


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
    temp_password: str, login_url: str, locale: str = "en",
) -> str:
    """Body-fragment HTML for the admin-driven password reset email.

    Feb-2026 · Housekeeping Batch A — collapsed to a body fragment
    (was previously a full ``<!doctype html><html>...`` document).
    Callers route the output through
    :func:`services.email.theming.wrap_html_in_shell`, which provides
    the doctype / html / head / body scaffolding. Returning a full
    document here produced a double-``<html>`` structural defect —
    clients tolerated it but the markup was invalid.

    Phase D6.2 · Feb-2026 — customer-facing sentences resolved via
    the i18n catalog. Only HTML skeleton / brand colors stay
    hardcoded. TTL semantics of the password reset are unchanged
    (this composer never handled TTLs — those live in the caller).
    """
    from services.email_body_i18n import t_email_body
    heading = t_email_body(locale, "email.password_reset.heading")
    body_intro = t_email_body(
        locale, "email.password_reset.body_intro",
        target_name=target_name, actor_name=actor_name,
        company_name=company_name,
    )
    temp_pw_label = t_email_body(
        locale, "email.password_reset.temp_password_label",
    )
    cta_label = t_email_body(locale, "email.password_reset.cta_sign_in")
    security_line = t_email_body(
        locale, "email.password_reset.footer_security",
    )
    return f"""<div style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:12px;padding:28px 30px;box-shadow:0 1px 3px rgba(0,0,0,.06);color:#111827;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif">
  <h1 style="margin:0 0 12px 0;font-size:20px">{heading}</h1>
  <p style="margin:0 0 16px 0;line-height:1.55">
    {body_intro}
  </p>
  <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:14px 16px;margin:0 0 20px 0">
    <div style="font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:.4px;margin-bottom:4px">{temp_pw_label}</div>
    <div style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:15px;font-weight:600">{temp_password}</div>
  </div>
  <p style="text-align:center;margin:0 0 22px 0">
    <a href="{login_url}" style="background:#0f766e;color:#ffffff;padding:11px 22px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block">{cta_label}</a>
  </p>
  <p style="font-size:12px;color:#6b7280;margin:0">
    {security_line}
  </p>
</div>"""


async def _send_password_reset_email(
    *, tenant: Dict[str, Any], actor: Dict[str, Any],
    target: Dict[str, Any], temp_password: str,
) -> str:
    from services.email.resend_adapter import send as _resend_send
    from services.email.theming import wrap_html_in_shell
    from services.tenants.business_settings import (
        get_effective_business_settings,
    )
    from urllib.parse import urljoin

    settings = tenant.get("settings") or {}
    card = settings.get("business_card") or {}
    company_display = card.get("company_name") or tenant.get("name") or "AquaTerra"
    origin = os.environ.get("FRONTEND_BASE_URL") or "https://app.aquaterra.com"
    login_url = urljoin(origin.rstrip("/") + "/", "login")
    # Phase D6.2 · Feb-2026 — recipient locale resolution for the
    # subject line + body copy. Target user's ``locale`` wins over
    # the tenant default; falls back to ``en``. Token generation +
    # TTL are untouched — this migration is copy-only.
    from services.i18n.email_locale import resolve_email_locale
    from services.email_body_i18n import t_email_body
    _locale = resolve_email_locale(recipient=target, tenant=tenant)
    subject = t_email_body(
        _locale, "email.password_reset.subject",
        company_name=company_display,
    )
    inner_html = _password_reset_html(
        target_name=target.get("first_name") or target.get("name") or "there",
        actor_name=actor.get("name") or actor.get("email") or "An admin",
        company_name=company_display,
        temp_password=temp_password,
        login_url=login_url,
        locale=_locale,
    )
    # Feb-2026 · Email Base Template Theming + Housekeeping Batch A —
    # ``_password_reset_html`` now returns a body fragment; the shell
    # is the sole source of ``<!doctype html>`` / ``<html>`` /
    # ``<head>`` / ``<body>`` scaffolding. See tests
    # ``test_password_reset_shell_yields_single_html_tag`` +
    # ``test_portal_invite_shell_yields_single_html_tag`` in
    # ``test_email_theming.py`` — both assert exactly one ``<html``
    # occurrence in the rendered output.
    try:
        branding = await get_effective_business_settings(
            db, tenant.get("id") or "", absolutize=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"branding resolve failed, using defaults: {e}")
        branding = {}
    html = wrap_html_in_shell(inner_html, branding)
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
    # Feb-2026 · Team page admin actions — explicit auto-gen switch so
    # the frontend "Auto-generate temporary password" tab is
    # unambiguous in the request. When ``True`` any provided
    # ``new_password`` is IGNORED and the backend mints a 16-char
    # strong password. When ``False`` / ``None`` the existing behavior
    # is preserved (use ``new_password`` if provided, else auto-gen).
    auto_generate: Optional[bool] = None


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

    # Feb-2026 · Team page brief — admins may only reset TECH passwords.
    # Reset your own via profile settings, not this endpoint.
    caller_role = (user.get("role") or "").lower()
    if caller_role == "admin":
        if uid == user.get("id"):
            raise HTTPException(400,
                "Use profile settings to change your own password")
        if not _is_tech_target(target):
            raise HTTPException(403,
                "Admins can only reset passwords for technicians")

    # A regular admin cannot reset a super_admin. Only another
    # super_admin can. (Kept as-is for defense-in-depth even though the
    # tech-only rule above already blocks this case for admins.)
    if target.get("role") == "super_admin" and user.get("role") != "super_admin":
        raise HTTPException(403, "Only a super_admin can reset another super_admin's password")

    # Cross-tenant reset requires super_admin.
    if user.get("role") == "admin":
        if target.get("tenant_id") != user.get("tenant_id"):
            raise HTTPException(403, "Cross-tenant password reset requires super_admin")

    # Auto-generate branch — either explicit flag OR the caller left
    # ``new_password`` empty (backward compat).
    if body.auto_generate or not body.new_password:
        new_pw = _strong_password()
    else:
        new_pw = str(body.new_password)
        if len(new_pw) < 8:
            raise HTTPException(400, "new_password must be at least 8 chars")

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
    """Legacy soft-delete via HTTP DELETE. Kept for backwards compatibility
    with anything still hitting the DELETE verb (mobile, older clients).
    New clients should use ``POST /api/users/{uid}/soft-delete`` — same
    RBAC + same result payload."""
    return await _perform_soft_delete(uid, user)


@router.post("/users/{uid}/soft-delete",
              operation_id="adminUsers.softDelete")
async def soft_delete_user(
    uid: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Feb-2026 · Team page admin actions — POST-style soft delete.

    Mirrors ``DELETE /users/{uid}`` but under a distinct URL so the
    Team page RBAC + audit trail can key off a single verb-agnostic
    endpoint. Sets ``deleted_at``, ``deleted_by_user_id``,
    ``roster_hidden=true``, and stamps ``sessions_revoked_at`` so any
    downstream session-invalidation logic (when a session store lands)
    has an atomic pivot to key off. JWTs in this codebase are stateless
    — we cannot forcibly log the user out mid-session, but the
    permission checks on subsequent requests will refuse them once
    ``deleted_at`` is set (see ``utils.get_current_user``)."""
    return await _perform_soft_delete(uid, user)


@router.post("/users/{uid}/undelete",
              operation_id="adminUsers.undelete")
async def undelete_user(
    uid: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Feb-2026 · Team page admin actions — restore a soft-deleted user.

    super_admin only. Clears ``deleted_at``, ``deleted_by_user_id``,
    ``roster_hidden``. Idempotent — returns ``already_active=true`` if
    the row was never deleted. Audit row written on every actual
    restore."""
    _require_super_admin(user)
    target = await db.users.find_one({"id": uid}, {"_id": 0})
    if not target:
        raise HTTPException(404, "User not found")
    if not target.get("deleted_at"):
        return {"ok": True, "user_id": uid, "already_active": True}

    await db.users.update_one(
        {"id": uid},
        {"$set": {"deleted_at": None,
                    "deleted_by_user_id": None,
                    "roster_hidden": False,
                    "undeleted_at": now_iso(),
                    "undeleted_by_user_id": user.get("id")}},
    )
    try:
        await db.audit_log.insert_one({
            "id": new_id(),
            "tenant_id": target.get("tenant_id"),
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "action": "user.undelete",
            "target_user_id": uid,
            "changes": {"deleted_at": {"old": target.get("deleted_at"), "new": None}},
            "at": now_iso(),
        })
    except Exception as e:  # pragma: no cover — audit best-effort
        logger.warning(f"undelete_user audit failed: {e}")
    return {"ok": True, "user_id": uid, "restored_at": now_iso()}


def _check_soft_delete_permissions(
    user: Dict[str, Any], target: Dict[str, Any], live_supers: int,
) -> None:
    """Raise HTTPException if the caller cannot soft-delete ``target``.

    Extracted from ``_perform_soft_delete`` (Batch 2 · complexity
    refactor) so the permission matrix from the Feb-2026 Team page
    brief lives in one auditable place.
    """
    caller_role = (user.get("role") or "").lower()
    # Regular admin can only delete tech rows.
    if caller_role == "admin" and not _is_tech_target(target):
        raise HTTPException(
            403,
            "Admins can only delete technicians. Ask a super_admin "
            "to remove admins or managers.",
        )
    # Guardrail: block deletion of the last super_admin in a tenant.
    if target.get("role") == "super_admin" and live_supers <= 1:
        raise HTTPException(
            409, "Cannot delete the last super_admin in this tenant")
    # A regular admin cannot delete a super_admin.
    if target.get("role") == "super_admin" \
            and user.get("role") != "super_admin":
        raise HTTPException(
            403, "Only a super_admin can delete another super_admin")
    # Cross-tenant delete requires super_admin.
    if user.get("role") == "admin" \
            and target.get("tenant_id") != user.get("tenant_id"):
        raise HTTPException(
            403, "Cross-tenant delete requires super_admin")


async def _cascade_soft_delete_reassignments(
    uid: str, target: Dict[str, Any],
) -> List[str]:
    """Reassign in-flight jobs + cancel active route overrides that
    reference the deleted user. Returns the list of reassigned job ids
    for the audit trail. Extracted from ``_perform_soft_delete``."""
    unassigned_placeholder = "unassigned"
    reassigned_jobs: List[str] = []
    from utils import not_deleted_filter as _nd
    async for j in db.jobs.find({
        "tenant_id": target.get("tenant_id"),
        "$and": [
            {"$or": [{"technician_id": target.get("id")},
                      {"assigned_tech_id": target.get("id")}]},
            _nd(),
        ],
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
    return reassigned_jobs


async def _perform_soft_delete(uid: str, user: Dict[str, Any]) -> Dict[str, Any]:
    """Shared soft-delete implementation used by BOTH the legacy DELETE
    handler and the new POST /soft-delete endpoint. Enforces the full
    permission matrix from the Feb-2026 Team page brief (delegated to
    ``_check_soft_delete_permissions``) and cascades in-flight jobs +
    route overrides (delegated to
    ``_cascade_soft_delete_reassignments``).

    Sets ``deleted_at``, ``deleted_by_user_id``, ``roster_hidden=true``,
    ``sessions_revoked_at`` on the target and writes an audit row.
    """
    _require_admin(user)
    if uid == user.get("id"):
        raise HTTPException(400, "You cannot delete your own user")

    target = await db.users.find_one({"id": uid}, {"_id": 0})
    if not target:
        raise HTTPException(404, "User not found")
    if target.get("deleted_at"):
        return {"ok": True, "user_id": uid, "already_deleted": True}

    # Count live super_admins in the target tenant BEFORE permission
    # check so the last-super_admin guardrail can fire.
    live_supers = 0
    if target.get("role") == "super_admin":
        live_supers = await db.users.count_documents({
            "tenant_id": target.get("tenant_id"),
            "role": "super_admin",
            "$or": [{"deleted_at": None},
                     {"deleted_at": {"$exists": False}}],
        })
    _check_soft_delete_permissions(user, target, live_supers)

    reassigned_jobs = await _cascade_soft_delete_reassignments(uid, target)

    deleted_at = now_iso()
    await db.users.update_one(
        {"id": uid},
        {"$set": {"deleted_at": deleted_at,
                    "deleted_by_user_id": user.get("id"),
                    "roster_hidden": True,
                    "sessions_revoked_at": deleted_at}},
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
        "at": deleted_at,
    })

    return {
        "ok": True, "user_id": uid,
        "deleted_at": deleted_at,
        "deleted_by_user_id": user.get("id"),
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
      * Phase S1.4 · Feb-2026 — non-super_admin actors that somehow
        reach this route with a ``super_admin`` payload get the
        specific ``super_admin_role_not_assignable`` detail so the
        frontend can render a targeted toast.
    """
    new_role = (body.role or "").strip().lower()
    if new_role == "super_admin" \
       and (user.get("role") or "").lower() != "super_admin":
        raise HTTPException(
            status_code=403,
            detail="super_admin_role_not_assignable",
        )
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

