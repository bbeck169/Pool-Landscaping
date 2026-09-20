"""Phase T1 · Feb-2026 — multi-tenant membership helpers.

Two responsibilities:

*   :func:`get_user_tenants` — resolve the list of tenants a user
    belongs to, joined with the current tenant's display metadata
    so the top-nav switcher can render on the first paint.
*   :func:`token_active_tenant_id` — decide the effective tenant
    for a request given the JWT's ``active_tenant_id`` claim +
    the user's ``tenant_memberships``.  Raises the 403
    ``stale_tenant_membership`` when the claim points at a tenant
    the user is no longer a member of.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from config import db


def _memberships_for(user: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return an always-populated membership list — legacy users
    without ``tenant_memberships`` are synthesised from their
    single ``tenant_id`` field for backwards compatibility."""
    lst = user.get("tenant_memberships") or []
    if not lst and user.get("tenant_id"):
        return [{
            "tenant_id": user["tenant_id"],
            "role":      user.get("role") or "customer",
            "joined_at": user.get("created_at"),
        }]
    return list(lst)


def user_has_membership(user: Dict[str, Any], tenant_id: str) -> bool:
    # Phase S1 hotfix · Feb-2026 — super_admin acts cross-tenant.
    # Their operational contract (see ``/api/tenants/memberships/mine``)
    # already lists every active tenant, so ``user_has_membership``
    # must agree. The switch-tenant endpoint still validates that
    # the target tenant exists + is active before minting the new
    # JWT — this only widens the "in your set" check, it doesn't
    # bypass the S1.2 role gate (which still 403s any non-super
    # caller before reaching this function).
    if (user.get("role") or "").lower() == "super_admin":
        return True
    for m in _memberships_for(user):
        if m.get("tenant_id") == tenant_id:
            return True
    return False


def token_active_tenant_id(
    user: Dict[str, Any],
    *,
    claim: Optional[str],
) -> Optional[str]:
    """Resolve the effective tenant id for a request.

    *   ``claim`` — value of the ``active_tenant_id`` JWT claim
        (may be ``None`` on legacy tokens).
    *   Returns ``None`` when the token has no claim (caller falls
        back to ``user.tenant_id``).
    *   Raises HTTP 403 ``stale_tenant_membership`` when the claim
        references a tenant the user is no longer in.
    """
    if not claim:
        return None
    if not user_has_membership(user, claim):
        raise HTTPException(
            status_code=403, detail="stale_tenant_membership")
    return claim


async def get_user_tenants(user: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return ``[{id, name, slug, role, is_active_now}]`` for every
    tenant the user is a member of.

    ``is_active_now`` is set on the currently-selected tenant so the
    frontend switcher can highlight it. The value defaults to the
    user's persistent ``active_tenant_id`` (if any) else the legacy
    ``user.tenant_id``.

    Phase S1 hotfix · Feb-2026 — for ``super_admin`` this returns
    **every** active tenant on the platform (mirroring
    ``GET /api/tenants/memberships/mine``). Non-super roles still
    resolve strictly from ``user.tenant_memberships``. The S1.2
    role gate on ``POST /api/auth/switch-tenant`` still prevents
    anyone else from acting on this expanded list.
    """
    active_now = (user.get("active_tenant_id")
                    or user.get("tenant_id"))
    role = (user.get("role") or "").lower()

    if role == "super_admin":
        rows: List[Dict[str, Any]] = []
        async for t in db.tenants.find(
            {"active": True},
            {"_id": 0, "id": 1, "name": 1, "slug": 1},
        ).sort("name", 1):
            rows.append({
                "id":            t["id"],
                "name":          t.get("name") or t["id"],
                "slug":          t.get("slug"),
                "role":          "super_admin",
                "is_active_now": t["id"] == active_now,
            })
        return rows

    memberships = _memberships_for(user)
    if not memberships:
        return []
    ids = [m["tenant_id"] for m in memberships if m.get("tenant_id")]
    rows: List[Dict[str, Any]] = []
    if ids:
        async for t in db.tenants.find(
            {"id": {"$in": ids}, "active": True},
            {"_id": 0, "id": 1, "name": 1, "slug": 1},
        ):
            rows.append(t)
    tenant_by_id = {t["id"]: t for t in rows}

    out: List[Dict[str, Any]] = []
    for m in memberships:
        tid = m.get("tenant_id")
        info = tenant_by_id.get(tid)
        if not info:
            continue
        out.append({
            "id":            info["id"],
            "name":          info.get("name") or info["id"],
            "slug":          info.get("slug"),
            "role":          m.get("role"),
            "is_active_now": tid == active_now,
        })
    return out
