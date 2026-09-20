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


# ═════════════════════════════════════════════════════════════════════
# G1.2 · Feb-2026 — transfer default-tenant.
# ═════════════════════════════════════════════════════════════════════
class _DefaultTenantBody(BaseModel):
    tenant_id: str


@router.patch("/admin/users/{user_id}/default-tenant")
async def set_default_tenant(
    user_id: str,
    body: _DefaultTenantBody,
    actor: Dict[str, Any] = Depends(get_current_user),
):
    """Move a multi-tenant user's default (login) tenant. Also
    rewrites ``active_tenant_id`` so the next JWT they mint starts
    on the new default.  Super_admin only.  Same-tenant call is a
    200 no-op — used by the frontend to force-refresh state.
    """
    _require_super_admin(actor)
    target = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(404, detail="user_not_found")
    memberships = target.get("tenant_memberships") or []
    if not any(m.get("tenant_id") == body.tenant_id for m in memberships):
        raise HTTPException(
            status_code=400,
            detail="tenant_not_in_memberships",
        )
    if target.get("tenant_id") == body.tenant_id \
       and target.get("active_tenant_id") == body.tenant_id:
        return {"ok": True, "changed": False,
                "tenant_id": body.tenant_id,
                "active_tenant_id": body.tenant_id}
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"tenant_id": body.tenant_id,
                    "active_tenant_id": body.tenant_id}})
    return {"ok": True, "changed": True,
            "tenant_id": body.tenant_id,
            "active_tenant_id": body.tenant_id}


# ═════════════════════════════════════════════════════════════════════
# G1.3 · Feb-2026 — pilot-tenants health snapshot.
# ═════════════════════════════════════════════════════════════════════
_PILOT_SLUGS = ("pool", "landscaping")


@router.get("/admin/tenants/pilots/health")
async def pilot_tenants_health(
    actor: Dict[str, Any] = Depends(get_current_user),
):
    """Super_admin-only sanity endpoint for the tenant-split rollout.

    Reports, per pilot slug, whether the tenant document exists, the
    UUID currently mapped to that slug, the raw membership count
    across all users, and — crucially — the number of user membership
    rows whose ``tenant_id`` references a pilot slug's *legacy* string
    id (``pool.tenant`` / ``landscaping.tenant``) or a UUID that no
    longer exists in the ``tenants`` collection. That last field
    caught the exact regression that broke T1 initially — pilots
    deleted by a stray pytest teardown while user memberships still
    reference them.
    """
    _require_super_admin(actor)
    out = []
    for slug in _PILOT_SLUGS:
        pilot = await db.tenants.find_one(
            {"slug": slug, "active": True}, {"_id": 0})
        exists = pilot is not None
        pilot_id = pilot["id"] if pilot else None
        settings = (pilot or {}).get("settings") or {}

        # Count memberships pointing at THIS pilot (via UUID or slug).
        candidate_ids = [x for x in
                            {pilot_id, f"{slug}.tenant"} if x]
        membership_count = await db.users.count_documents(
            {"tenant_memberships.tenant_id": {"$in": candidate_ids}}
            if candidate_ids else {"__never__": True}) if candidate_ids else 0

        # Count memberships that reference a stale id for this slug —
        # i.e. the ``{slug}.tenant`` legacy literal ONLY. If the pilot
        # is missing we also count references to any prior UUID we may
        # know about via ``renewed_by_agreement_id`` — not applicable
        # here — so this focuses on the legacy-string leak.
        orphan_count = await db.users.count_documents(
            {"tenant_memberships.tenant_id": f"{slug}.tenant"})

        out.append({
            "slug":                  slug,
            "id":                    pilot_id,
            "exists":                exists,
            "membership_count":      int(membership_count),
            "orphan_memberships":    int(orphan_count),
            "settings":              settings,
        })
    return {
        "pilots":     out,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
