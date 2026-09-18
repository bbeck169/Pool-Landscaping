"""Feb 2026 · Sprint 2 · Section A — Admin "Unlinked Technicians" widget.

Surfaces every ``db.technicians`` doc where ``user_id`` is ``null``
(no login credentials attached) so admins can click-through to
create + link a matching ``db.users`` row with a random temporary
password and (optionally) an invite email.

Endpoints
---------
* ``GET /api/admin/technicians/unlinked``
    Admin + super_admin only. Returns unlinked technicians in the
    caller's tenant with ``{tech_id, name, email, phone, created_at,
    tenant_id}``.

* ``POST /api/admin/technicians/{tech_id}/create-user``
    Admin + super_admin only. Creates a matching ``db.users`` row
    (role=technician, department preserved from the tech doc if set,
    temporary bcrypt-hashed 12-char password, `must_reset_password`
    + `invited_at` flags), links ``technicians.user_id``, writes an
    audit-log row, and optionally sends an invite email via the
    existing team-invite template.

Guardrails
----------
* 409 ``email_already_in_use`` if a users row with that email
  already exists in the tenant (surfaces the existing user id so
  the admin can act on it).
* 409 ``already_linked`` if the technician already has a user_id.
* 400 ``email_required`` if the technician doc has no email.
* 400 (from the shared contrast validator) if the resolved default
  color fails the WCAG 3.0-vs-white check.
* Temp password returned ONCE in the response so the admin can
  copy + relay when the email invite is skipped / fails.
"""
from __future__ import annotations

import secrets
import string
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from config import db, logger
from constants.tech_colors import TECH_COLOR_PALETTE
from services.color import validate_color_hex_for_pin
from utils import (
    get_current_user, hash_password, new_id, now_iso,
)

router = APIRouter(tags=["Admin · Unlinked Technicians"])

_ADMIN_ROLES = {"admin", "super_admin"}
_TEMP_PASSWORD_LEN = 12
_TEMP_PASSWORD_ALPHA = string.ascii_letters + string.digits


def _require_admin(user: Dict[str, Any]) -> None:
    if (user or {}).get("role") not in _ADMIN_ROLES:
        raise HTTPException(403, "Admin only")


def _temp_password(n: int = _TEMP_PASSWORD_LEN) -> str:
    """Cryptographically-random 12-char alnum. Guaranteed to include
    at least one lower/upper/digit so downstream policies pass on the
    first roll."""
    while True:
        pw = "".join(secrets.choice(_TEMP_PASSWORD_ALPHA) for _ in range(n))
        if (any(c.islower() for c in pw)
                and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw)):
            return pw


def _split_name(full: Optional[str]) -> tuple[str, str]:
    """Split ``"First Last"`` into ``(first, last)``. Single-token
    names become ``(first, "")``. ``None`` / ``""`` → ``("", "")``."""
    s = (full or "").strip()
    if not s:
        return "", ""
    parts = s.split(None, 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _resolve_default_color(tech: Dict[str, Any]) -> str:
    """Pick a WCAG-passing default color for the new user.

    Preference order:
      1. ``technicians.display_color_hex`` if already set on the tech
         doc (validated through the shared contrast guard).
      2. Palette head (``#3B82F6`` — blue-500) — always passes the
         contrast guard by construction.
    """
    raw = (tech or {}).get("display_color_hex")
    if raw:
        try:
            return validate_color_hex_for_pin(raw)
        except HTTPException:
            # Bad color on the tech doc — fall through to palette head.
            pass
    return validate_color_hex_for_pin(TECH_COLOR_PALETTE[0][1])


def _serialize_unlinked(tech: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tech_id":    tech.get("id"),
        "name":       tech.get("name") or "",
        "email":      tech.get("email") or "",
        "phone":      tech.get("phone") or "",
        "created_at": tech.get("created_at") or "",
        "tenant_id":  tech.get("tenant_id") or "",
    }


@router.get(
    "/admin/technicians/unlinked",
    operation_id="adminUnlinkedTechs.list",
)
async def list_unlinked_technicians(
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return every technician doc in the caller's tenant whose
    ``user_id`` is null (unlinked, no login credentials yet).

    Admin + super_admin only (403 for any other role).
    """
    _require_admin(user)
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        # Users without a tenant id are misconfigured — surface it
        # explicitly rather than returning a spurious empty list.
        raise HTTPException(400, "caller has no tenant_id")

    # A ``user_id`` field may be absent OR explicitly null on legacy
    # docs — treat both as "unlinked".
    query = {
        "tenant_id": tenant_id,
        "$or": [{"user_id": None}, {"user_id": {"$exists": False}}],
    }
    rows: List[Dict[str, Any]] = []
    async for tech in db.technicians.find(query, {"_id": 0}):
        rows.append(_serialize_unlinked(tech))

    # Deterministic ordering (name asc, then created_at asc) so the
    # UI list is stable across renders.
    rows.sort(
        key=lambda r: ((r.get("name") or "").lower(), r.get("created_at") or ""),
    )
    return {"technicians": rows, "count": len(rows)}


async def _send_invite_best_effort(
    *, tenant_id: str, actor: Dict[str, Any],
    invitee: Dict[str, Any], temp_password: str,
) -> Dict[str, Any]:
    """Best-effort invite send. Returns ``{status, error}``; NEVER
    raises. When Resend or the ``send_team_invite_email`` helper isn't
    available in this deployment, returns ``{"status": "skipped",
    "error": None}``.
    """
    try:
        tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"unlinked-tech: tenant lookup failed: {e}")
        tenant = {}
    try:
        from routers.team import _send_team_invite_email  # type: ignore
    except Exception as e:  # noqa: BLE001
        logger.info(f"unlinked-tech: invite helper unavailable ({e}); skipping")
        return {"status": "skipped", "error": None}
    try:
        status = await _send_team_invite_email(
            tenant=tenant, actor=actor,
            invitee=invitee, temp_password=temp_password,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"unlinked-tech: invite send raised: {e}")
        return {"status": "failed", "error": str(e)}
    if status not in {"sent", "mocked", "suppressed", "skipped"}:
        return {"status": status or "failed",
                "error": "Invite email failed to send"}
    return {"status": status, "error": None}


@router.post(
    "/admin/technicians/{tech_id}/create-user",
    operation_id="adminUnlinkedTechs.createUser",
)
async def create_user_for_unlinked_tech(
    tech_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Create + link a ``users`` row for the given unlinked technician.

    * 404 if the technician isn't in the caller's tenant.
    * 409 ``already_linked`` if the tech already has a ``user_id``.
    * 400 ``email_required`` if the tech doc has no email.
    * 409 ``email_already_in_use`` if a users row with that email
      already exists in the tenant (surfaces the existing user id).
    * 200 on success with ``{user_id, email, temporary_password,
      invite_email_status}``.
    """
    _require_admin(user)
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "caller has no tenant_id")

    tech = await db.technicians.find_one(
        {"id": tech_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not tech:
        raise HTTPException(404, "Technician not found")

    if tech.get("user_id"):
        raise HTTPException(409, {
            "code": "already_linked",
            "message": "This technician is already linked to a user account.",
            "user_id": tech.get("user_id"),
        })

    email = (tech.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, {
            "code": "email_required",
            "message": (
                "The technician doc has no email. "
                "Set one first, then retry."
            ),
        })

    # Duplicate-email guard — case-insensitive, tenant-scoped so
    # cross-tenant emails don't spuriously block a link.
    existing = await db.users.find_one(
        {"tenant_id": tenant_id, "email": email}, {"_id": 0, "id": 1},
    )
    if existing:
        raise HTTPException(409, {
            "code": "email_already_in_use",
            "message": (
                "A user with this email already exists. "
                "Link manually or resolve the duplicate first."
            ),
            "user_id": existing.get("id"),
        })

    first, last = _split_name(tech.get("name"))
    color = _resolve_default_color(tech)
    temp_password = _temp_password()
    user_id = new_id()
    created_at = now_iso()

    user_doc: Dict[str, Any] = {
        "id":             user_id,
        "tenant_id":      tenant_id,
        "email":          email,
        "name":           tech.get("name") or f"{first} {last}".strip(),
        "first_name":     first,
        "last_name":      last,
        "phone":          (tech.get("phone") or "").strip(),
        "role":           "technician",
        "department":     tech.get("department"),
        "password_hash":  hash_password(temp_password),
        "must_reset_password": True,
        "invited_at":     created_at,
        "created_at":     created_at,
        "created_by_user_id": user.get("id"),
        "display_color_hex": color,
        "deleted_at":     None,
        "is_active":      True,
        # Preserve the original technician id on the user doc so
        # downstream tech-lookup joins can find the row from either
        # direction. Matches the convention used by the Team page's
        # ``create_team_user`` handler.
        "technician_id":  tech.get("id"),
    }
    await db.users.insert_one(user_doc)

    # Link the technician doc to the new user.
    await db.technicians.update_one(
        {"id": tech_id, "tenant_id": tenant_id},
        {"$set": {
            "user_id":            user_id,
            "linked_at":          created_at,
            "linked_by_user_id":  user.get("id"),
            "display_color_hex":  color,
        }},
    )

    # Audit log — mirrors the shape used by admin_users.py + team.py.
    await db.audit_log.insert_one({
        "id":              new_id(),
        "tenant_id":       tenant_id,
        "actor_user_id":   user.get("id"),
        "actor_email":     user.get("email"),
        "action":          "technician_user_created_and_linked",
        "target_user_id":  user_id,
        "target_tech_id":  tech_id,
        "changes": {
            "user_id":  {"old": None, "new": user_id},
            "email":    {"old": None, "new": email},
            "role":     {"old": None, "new": "technician"},
        },
        "at":              created_at,
    })

    invite_result = await _send_invite_best_effort(
        tenant_id=tenant_id, actor=user,
        invitee=user_doc, temp_password=temp_password,
    )

    return {
        "ok":                   True,
        "user_id":              user_id,
        "email":                email,
        "temporary_password":   temp_password,
        "invite_email_status":  invite_result.get("status"),
        "invite_email_error":   invite_result.get("error"),
    }
