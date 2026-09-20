"""Phase T1.4 · Feb-2026 — admin routes to manage user memberships.

Super_admin-only surface — anything less returns 403
``insufficient_role_for_membership_mgmt``.

*   ``POST   /api/admin/users/{user_id}/memberships`` — add a
    (tenant_id, role) membership.  Idempotent.
*   ``DELETE /api/admin/users/{user_id}/memberships/{tenant_id}`` —
    remove a membership.  Refuses to remove the user's default
    ``tenant_id`` (must transfer default first — out of scope).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db
from utils import get_current_user

router = APIRouter(tags=["tenant-memberships"])


def _require_super_admin(user: Dict[str, Any]) -> None:
    if (user.get("role") or "").lower() != "super_admin":
        raise HTTPException(
            status_code=403,
            detail="insufficient_role_for_membership_mgmt",
        )


class _AddMembershipBody(BaseModel):
    tenant_id: str
    role:      str = "technician"


_VALID_ROLES = {"admin", "super_admin", "manager", "owner",
                "technician", "customer"}


@router.post("/admin/users/{user_id}/memberships")
async def add_membership(
    user_id: str,
    body: _AddMembershipBody,
    actor: Dict[str, Any] = Depends(get_current_user),
):
    _require_super_admin(actor)
    role = (body.role or "").strip().lower()
    if role not in _VALID_ROLES:
        raise HTTPException(400, detail="invalid_role")
    target = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(404, detail="user_not_found")
    tenant = await db.tenants.find_one(
        {"id": body.tenant_id, "active": True}, {"_id": 0, "id": 1})
    if not tenant:
        raise HTTPException(404, detail="tenant_not_found")

    memberships = target.get("tenant_memberships") or []
    if any(m.get("tenant_id") == body.tenant_id for m in memberships):
        return {"ok": True, "created": False, "memberships": memberships}

    entry = {
        "tenant_id":  body.tenant_id,
        "role":       role,
        "joined_at":  datetime.now(timezone.utc).isoformat(),
    }
    memberships.append(entry)
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"tenant_memberships": memberships}})
    return {"ok": True, "created": True, "memberships": memberships}


@router.delete("/admin/users/{user_id}/memberships/{tenant_id}")
async def remove_membership(
    user_id: str,
    tenant_id: str,
    actor: Dict[str, Any] = Depends(get_current_user),
):
    _require_super_admin(actor)
    target = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(404, detail="user_not_found")
    if target.get("tenant_id") == tenant_id:
        # TODO(T1.5+): expose a separate PATCH endpoint that transfers
        # the default before removing the last membership.  For now
        # we refuse to strip the user's default tenant so we never
        # end up with a userless-of-tenant record.
        raise HTTPException(
            status_code=400,
            detail="cannot_remove_default_tenant_membership",
        )
    memberships = target.get("tenant_memberships") or []
    new = [m for m in memberships if m.get("tenant_id") != tenant_id]
    if len(new) == len(memberships):
        return {"ok": True, "removed": False, "memberships": memberships}
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"tenant_memberships": new}})
    return {"ok": True, "removed": True, "memberships": new}
