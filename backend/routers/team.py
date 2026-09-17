# ruff: noqa: F401
from fastapi import APIRouter, HTTPException, Depends, Query
import os
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, EmailStr

from config import db, logger, EMERGENT_LLM_KEY
from routers.tenants import get_current_tenant
from routers.portal_admin import _random_password
from services.notifications import emit as notify_emit
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
# Feb-2026 · P5 — wildcard ``from models import *`` dropped. Router
# only references ``Any / List / Optional / BaseModel / EmailStr / re``,
# each of which is already imported from typing / pydantic / stdlib
# above. No model classes are consumed here so no explicit
# ``from models`` line is needed.

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
    # Feb-2026 · Cross-trained technician (pool + landscape). Distinct
    # from ("admin","both") below — this combo has ZERO admin RBAC;
    # it's just a tech who works both service lines. Parity with the
    # ``AdminUsersList`` / mobile ``/team`` pickers which have offered
    # "Both" via the modern-enum PUT /admin/users/{id}/department for
    # a while — the /team unified picker was the missing surface.
    ("technician", "both"):        "Tech (Both)",
    ("admin", None):               "Admin",
    ("admin", "both"):             "All (Admin + Pool + Landscape)",
}
# Departments that are valid for a given role. Anything outside this
# whitelist → 400.
_VALID_DEPTS_BY_ROLE = {
    # Feb-2026 · "both" now allowed for technicians (cross-trained
    # pool + landscape). Downstream gates already accept "both" — see
    # ``routers/timeclock_landscaping.py::_require_landscaping`` which
    # allows ``dept in ("landscaping", "both")``. There is no pool-only
    # timeclock gate today (audit Feb-2026).
    "technician": {"pool", "landscaping", "both", None},
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

    # BUG A fix (Feb-2026) — REAL Resend send. No more mock stub.
    # If Resend key is missing we STILL log a failed row + surface the
    # error to the admin UI; we do NOT silently return "mocked" ok.
    invite_email_status = "skipped"
    invite_email_error = None
    if body.send_invite_email:
        invite_email_status = await _send_team_invite_email(
            tenant=tenant, actor=actor, invitee=doc,
            temp_password=temp_password,
        )
        # Read back the last error the adapter logged for this call
        # so the UI can toast it if the send failed.
        if invite_email_status not in ("sent", "mocked", "suppressed"):
            invite_email_error = "Invite email failed to send. Check Resend configuration."

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
        "invite_email_status": invite_email_status,
        "invite_email_error": invite_email_error,
    }


# ─────────────────────────────────────────────────────────────
# BUG A fix (Feb-2026) — real team-invite email via Resend
# ─────────────────────────────────────────────────────────────
def _team_invite_html(
    *, invitee_name: str, inviter_name: str,
    company_name: str, invite_accept_url: str, temporary_password: str,
) -> str:
    """Minimal but branded HTML — same style as the existing
    ``password_reset`` template so we don't need a third-party template
    editor. Merge tags: {{invitee_name}}, {{inviter_name}},
    {{company_name}}, {{invite_accept_url}}, {{temporary_password}}."""
    return f"""<!doctype html>
<html><body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#f4f6f8;padding:24px 0;margin:0;color:#111827">
<div style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:12px;padding:28px 30px;box-shadow:0 1px 3px rgba(0,0,0,.06)">
  <h1 style="margin:0 0 12px 0;font-size:20px">Welcome to {company_name}, {invitee_name} 👋</h1>
  <p style="margin:0 0 16px 0;line-height:1.55">
    {inviter_name} added you to the team. You can sign in now with the
    temporary credentials below — you'll be asked to change your password
    on first login.
  </p>
  <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:14px 16px;margin:0 0 20px 0">
    <div style="font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:.4px;margin-bottom:4px">Temporary password</div>
    <div style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:15px;font-weight:600">{temporary_password}</div>
  </div>
  <p style="text-align:center;margin:0 0 22px 0">
    <a href="{invite_accept_url}" style="background:#0f766e;color:#ffffff;padding:11px 22px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block">Sign in to the platform</a>
  </p>
  <p style="font-size:12px;color:#6b7280;margin:0">
    If you weren't expecting this invite, ignore this email or reply to let us know.
  </p>
</div>
</body></html>"""


async def _send_team_invite_email(
    *, tenant: dict, actor: dict, invitee: dict, temp_password: str,
) -> str:
    """Send the invite via Resend. Persists the send to
    ``communications_log`` (trigger_entity.kind='team_invite') and
    also mirrors into ``email_delivery_log`` for the admin delivery
    report. Returns the provider_status string ("sent"|"mocked"|
    "failed"|"suppressed") the endpoint hands back to the UI.

    NEVER silently succeeds on real errors — a failure returns
    "failed" and inserts a status="failed" row into both logs."""
    from services.email.resend_adapter import send as _resend_send
    from urllib.parse import urljoin

    company = tenant.get("name") or "Pool & Landscaping of Vistancia"
    settings = tenant.get("settings") or {}
    card = settings.get("business_card") or {}
    company_display = card.get("company_name") or company
    origin = os.environ.get("FRONTEND_BASE_URL") or "https://app.plofv.com"
    accept_url = urljoin(origin.rstrip("/") + "/", "login")

    html = _team_invite_html(
        invitee_name=invitee.get("first_name") or invitee.get("name") or "there",
        inviter_name=actor.get("name") or actor.get("email") or "The team",
        company_name=company_display,
        invite_accept_url=accept_url,
        temporary_password=temp_password,
    )
    subject = f"Welcome to {company_display} — you've been added to the team"

    result = await _resend_send(
        to=invitee["email"], subject=subject, html=html,
        category="transactional",
        idempotency_key=f"team-invite-{invitee['id']}",
        tenant_id=tenant["id"],
    )
    status = result.get("provider_status") or "failed"
    provider_id = result.get("provider_response_id")

    # Delivery report row (legacy — kept so existing admin views work).
    try:
        await db.email_delivery_log.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "to": invitee["email"],
            "subject": subject,
            "template": "team_invite_email",
            "status": status,
            "provider": result.get("provider") or "resend",
            "provider_response_id": provider_id,
            "error": result.get("error"),
            "sent_at": now_iso(),
            "meta": {"user_id": invitee["id"], "role": invitee.get("role"),
                       "department": invitee.get("department")},
        })
    except Exception as e:
        logger.warning(f"team-invite: email_delivery_log write failed: {e}")

    # Comms log (spec-required: trigger_entity.kind='team_invite').
    try:
        await db.communications_log.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "channel": "email",
            "to": invitee["email"],
            "subject": subject,
            "template": "team_invite_email",
            "status": status,
            "provider": result.get("provider") or "resend",
            "provider_response_id": provider_id,
            "error": result.get("error"),
            "trigger_entity": {"kind": "team_invite", "id": invitee["id"]},
            "created_at": now_iso(),
        })
    except Exception as e:
        logger.warning(f"team-invite: communications_log write failed: {e}")

    # BUG A follow-up — the admin ``/api/communications-log`` endpoint
    # reads from ``marketing_deliveries``. Mirror the send there so
    # admins actually see the row in the UI.
    try:
        await db.marketing_deliveries.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "channel": "email",
            "recipient_address": invitee["email"],
            "template_code": "team_invite_email",
            "subject": subject,
            "delivery_status": status,
            "provider_status": status,
            "trigger_kind": "team_invite",
            "trigger_entity": {"kind": "team_invite", "id": invitee["id"]},
            "created_at": now_iso(),
        })
    except Exception as e:
        logger.warning(f"team-invite: marketing_deliveries write failed: {e}")

    return status



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
                     tenant: dict = Depends(get_current_tenant),
                     include_deleted: bool = False):
    """Feb-2026 · Team page admin actions — soft-delete filter.

    By default the roster hides users with ``deleted_at`` set. A
    ``super_admin`` may pass ``?include_deleted=true`` to view (and
    later undelete) previously-removed rows. Regular admins that pass
    the flag are silently ignored (defense in depth) — the response
    still hides deleted rows for them.

    Feb-2026 self-visibility fix — the role filter now includes
    ``super_admin`` and ``manager`` so the caller's own row is
    returned rather than silently filtered out. The frontend renders
    it with the kebab suppressed (per the permission matrix — no
    self-serve reset/delete) plus a small "(you)" label.
    """
    q: dict = {"role": {"$in": ["admin", "technician", "tech",
                                    "super_admin", "manager"]},
                "tenant_id": tenant["id"]}
    is_super = (user.get("role") or "").lower() == "super_admin"
    if not (include_deleted and is_super):
        q["$or"] = [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]
    users = await db.users.find(q, {"_id": 0, "password_hash": 0}).to_list(1000)
    for u in users:
        if u.get("technician_id"):
            _base_q = {
                "technician_id": u["technician_id"],
                "status": {"$in": ["pending", "active"]},
            }
            u["active_jobs"] = await db.jobs.count_documents(_base_q)
            # Feb 2026 · Work-class counter split. Same subtraction
            # trick as ``routers/technicians.py`` — legacy jobs land in
            # the service bucket automatically.
            u["active_jobs_repair"] = await db.jobs.count_documents(
                {**_base_q, "work_class": "repair"},
            )
            u["active_jobs_service"] = max(
                0, u["active_jobs"] - u["active_jobs_repair"],
            )
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

    allowed_fields = {"department", "role", "display_color_hex", "auto_clockin_enabled"}
    unknown = set(body.keys()) - allowed_fields
    if unknown:
        raise HTTPException(400, f"unsupported fields: {sorted(unknown)}")

    updates: dict = {}
    audit_changes: dict = {}

    # Feb-2026 · mobile-flagged gap — per-user Auto Clock-In enable flag.
    # Admin (and super_admin) can toggle for any technician; a self-PATCH
    # variant lives at ``PATCH /users/me`` for the user's own account.
    if "auto_clockin_enabled" in body:
        val = body["auto_clockin_enabled"]
        if not isinstance(val, bool):
            raise HTTPException(400, "auto_clockin_enabled must be a boolean")
        old_val = target.get("auto_clockin_enabled")
        if val != old_val:
            updates["auto_clockin_enabled"] = val
            audit_changes["auto_clockin_enabled"] = {"old": old_val, "new": val}

    # Phase 21 · Feb 2026 · Addition B — per-user display color for the
    # Schedule / dispatch calendar. Validated as `#RRGGBB`; null clears
    # the field and reverts to the deterministic hashed fallback.
    if "display_color_hex" in body:
        raw = body["display_color_hex"]
        if raw is None or raw == "":
            new_color = None
        else:
            # Feb-2026 · Global Color Picker · relaxed the earlier
            # 12-color palette lock. Callers may now save ANY hex,
            # but the color MUST clear WCAG contrast ≥ 3.0 against
            # white so the pin's white inner disc keeps the label
            # legible.  Validator canonicalises to upper-case
            # ``#RRGGBB`` shape.
            from services.color import validate_color_hex_for_pin
            new_color = validate_color_hex_for_pin(raw)
        old_color = target.get("display_color_hex")
        if new_color != old_color:
            updates["display_color_hex"] = new_color
            audit_changes["display_color_hex"] = {"old": old_color, "new": new_color}

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



