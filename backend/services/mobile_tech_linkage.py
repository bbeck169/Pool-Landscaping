"""TD-tech-record-sync-and-fleet-enrollment · Feb-2026
=====================================================

Shared gate for mobile endpoints that must reject tech-role users
whose account has no corresponding ``technicians`` row.

Semantics
---------
A tech-role user (``role in {"technician", "tech"}``) is considered
linked to a technician record when EITHER of the following holds
and the matched tech row is live (``deleted_at`` null/missing):

* ``users.technician_id`` points at a tech row in the same tenant.
* ``technicians.find_one({"user_id": user.id, "tenant_id": tid})``
  returns a live row (reverse-stamp path).

If neither path finds a live tech row, the user is "orphan" — the
mobile offline bundle would silently return an empty job list, and
the mobile FE's generic "sync failed" toast would hide the real
cause. This helper raises a 409 with a documented
``technician_not_linked`` error code so the mobile FE can surface
"Account not linked — contact admin" instead.

Non-tech roles (admin, super_admin, manager, owner, dispatcher, …)
are returned unchanged — admins routinely diagnose by hitting
mobile endpoints with their own token.

The 409 shape mirrors the modern repo convention (see
``routers/time_off.py::L222``) — ``detail`` is a dict with
``error`` + human ``detail`` + ``tenant_id`` + ``user_id`` so
mobile logs always carry enough context for the admin to triage.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import HTTPException

from config import db

# Keep in sync with ``routers/fleet.py::_TECH_ROLES`` so the gate
# matches the fleet-code equivalence class the operator picked for
# the Pass-A/Pass-C role scope.
_TECH_ROLES = {"technician", "tech"}


def _not_deleted_clause() -> Dict[str, Any]:
    # Mirrors ``utils.not_deleted_filter`` without the import edge
    # — same shape: deleted_at missing OR null.
    return {"$or": [
        {"deleted_at": None},
        {"deleted_at": {"$exists": False}},
    ]}


async def assert_user_linked_to_technician(
    user: Dict[str, Any],
    tenant_id: str,
) -> None:
    """Raise ``409 technician_not_linked`` when a tech-role user is
    not linked to a live ``technicians`` row in ``tenant_id``.

    Returns ``None`` (and NEVER raises) for non-tech roles or when
    the user is linked via either side of the FK (``users
    .technician_id`` OR ``technicians.user_id``).
    """
    role = (user.get("role") or "").lower()
    if role not in _TECH_ROLES:
        return

    user_id = user.get("id")
    if not user_id:
        # Malformed principal — out of scope for this gate; let the
        # downstream handler surface a more precise error.
        return

    # Fast-path: users.technician_id → technicians.id.  We re-verify
    # the tech row is live so a soft-deleted tech can't keep a stale
    # user.technician_id as a free pass.
    linked_tech_id = user.get("technician_id")
    if linked_tech_id:
        row = await db.technicians.find_one(
            {
                "id": linked_tech_id,
                "tenant_id": tenant_id,
                "$and": [_not_deleted_clause()],
            },
            {"_id": 0, "id": 1},
        )
        if row:
            return

    # Reverse path: technicians.user_id → users.id.  Catches rows
    # created by the backfill CLI where both sides are stamped, and
    # legacy rows where the admin linked from the technicians side
    # (routers/admin_unlinked_techs.py::create_user_for_unlinked_tech)
    # but the user's JWT hasn't been refreshed yet.
    row = await db.technicians.find_one(
        {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "$and": [_not_deleted_clause()],
        },
        {"_id": 0, "id": 1},
    )
    if row:
        return

    raise HTTPException(
        status_code=409,
        detail={
            "error": "technician_not_linked",
            "detail": (
                f"User {user_id} has role=technician but is not linked "
                f"to a technician record. Contact your admin."
            ),
            "tenant_id": tenant_id,
            "user_id": user_id,
        },
    )


__all__ = ["assert_user_linked_to_technician"]
