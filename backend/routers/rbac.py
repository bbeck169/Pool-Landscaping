"""Phase 29C · RBAC endpoint for the currently authenticated user.

Exposes `GET /api/rbac/me/permissions` — a compact "who am I / what can I do"
view that the web UI consumes so it doesn't have to reconstruct the full
per-role matrix client-side. Tenant-scoped: reads the tenant's active
permissions matrix (if the tenant has an override) or falls back to the
global seeded matrix.

Nothing here mutates state. Nothing here bypasses server-side RBAC —
permission gates elsewhere still verify the JWT owner's real role. This
endpoint is purely informative.
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends

from config import db
from utils import get_current_user

router = APIRouter()


# The seeded default matrix (mirrors what /api/permissions returns when no
# tenant override exists). Kept here — deliberately not imported from
# ai_ops — so this small router can serve requests even if ai_ops changes.
_DEFAULT_MATRIX: Dict[str, Dict[str, str]] = {
    "super_admin": {"__all__": "write"},
    "admin": {"__all__": "write"},
    "technician": {"Jobs": "write", "Customers": "read"},
    "customer": {"Portal": "write"},
    "marketer": {"Marketing": "write", "SEO": "write", "GBP": "write"},
    "sales": {"Customers": "write", "Jobs": "read", "Quotes": "write"},
}


def _normalize_actions(v: Any) -> Dict[str, bool]:
    """Convert a matrix value ("write", "read", ["read","write"]) into an
    action-flag dict so the frontend can index by verb without guessing."""
    if isinstance(v, list):
        acts = {a: True for a in v if isinstance(a, str)}
    elif isinstance(v, str):
        if v == "write":
            acts = {"read": True, "write": True}
        elif v == "publish":
            acts = {"read": True, "write": True, "publish": True}
        elif v == "approve":
            acts = {"read": True, "write": True, "approve": True}
        else:
            acts = {v: True}
    else:
        acts = {}
    return acts


@router.get("/rbac/me/permissions")
async def me_permissions(user: dict = Depends(get_current_user)):
    """Return `{ role, permissions: { feature: {read: bool, write: bool, ...} } }`
    for the caller. Admin / super-admin roles always report an `__all__` flag
    so the UI can short-circuit gates instead of matrix-diving every render.
    """
    role = (user or {}).get("role") or "customer"
    tenant_id = (user or {}).get("tenant_id")

    matrix: Dict[str, Any] = {}
    if tenant_id:
        tenant_doc = await db.settings.find_one(
            {"id": "permissions_matrix", "tenant_id": tenant_id},
            {"_id": 0, "matrix": 1},
        )
        if tenant_doc and isinstance(tenant_doc.get("matrix"), dict):
            matrix = tenant_doc["matrix"]

    if not matrix:
        global_doc = await db.settings.find_one(
            {"id": "permissions_matrix"}, {"_id": 0, "matrix": 1},
        )
        if global_doc and isinstance(global_doc.get("matrix"), dict):
            matrix = global_doc["matrix"]

    if not matrix:
        matrix = _DEFAULT_MATRIX

    role_map = matrix.get(role, {}) or {}
    # Admin/super-admin: publish the wildcard so the client can skip
    # per-feature checks entirely. This is only advisory — the server still
    # enforces per-endpoint gates.
    if role in ("admin", "super_admin"):
        return {
            "role": role,
            "permissions": {"__all__": {"read": True, "write": True}},
            "is_admin": True,
            "tenant_id": tenant_id,
        }

    permissions = {
        feature: _normalize_actions(val) for feature, val in role_map.items()
    }
    return {
        "role": role,
        "permissions": permissions,
        "is_admin": False,
        "tenant_id": tenant_id,
    }
