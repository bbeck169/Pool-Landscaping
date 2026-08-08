"""Phase 51a · Feb 2026 — Walkie channel resolution + tenant bootstrap.

Standard channels (``all_hands`` + one per department: ``pool`` /
``landscape``) are auto-provisioned on first read. Direct channels are
created explicitly via POST /api/walkie/channels/direct.

Recipient resolution
--------------------
Each of the three channel kinds expands to a live recipient set at
send-time. Membership is dynamic for standard channels so headcount
changes are reflected in unread counts even for historical messages.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


STAFF_ROLES = {"super_admin", "admin", "manager", "technician", "dispatcher", "owner"}
# Phase 51b · Feb 2026 — Broadcast permission gate.
# Only leadership roles can post to the tenant-wide ``all_hands``
# channel. Techs / dispatchers stay limited to their own department
# and their own directs. Enforced server-side on POST /messages.
BROADCAST_ROLES = {"super_admin", "admin", "manager"}
# Phase 51.5 · Feb 2026 — Pin permission gate.
# Same three leadership roles can pin exactly one message per channel.
# Techs / dispatchers cannot pin. Enforced server-side on the pin
# endpoints, mirrored client-side to hide the action.
PIN_ROLES = {"super_admin", "admin", "manager"}
DEPARTMENTS = ("pool", "landscape")

# Feb 2026 · Phase 51a — seeded user rows use ``department="landscaping"``
# whereas the brief locks the walkie ``department`` field to
# ``pool`` | ``landscape``. Normalize on read so a landscape technician
# gets routed to the ``landscape`` channel without a data migration.
_DEPARTMENT_ALIASES = {
    "pool": "pool",
    "landscape": "landscape",
    "landscaping": "landscape",
}


def _norm_dep(v: str | None) -> str | None:
    if not v:
        return None
    return _DEPARTMENT_ALIASES.get(v.strip().lower())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _staff_user_ids(db, tenant_id: str, *, department: str | None = None) -> list[str]:
    """Return every ACTIVE staff user_id for the tenant, optionally
    filtered to a department. Excludes customer/portal roles."""
    q: dict[str, Any] = {
        "tenant_id": tenant_id,
        "active": {"$ne": False},
        "role": {"$in": list(STAFF_ROLES)},
    }
    if department:
        # Include the alias (e.g. "landscape" also matches "landscaping").
        aliases = [k for k, v in _DEPARTMENT_ALIASES.items() if v == department]
        q["department"] = {"$in": aliases or [department]}
    docs = await db.users.find(q, {"_id": 0, "id": 1}).to_list(length=None)
    return [d["id"] for d in docs if d.get("id")]


async def resolve_recipients(channel: dict, sender_id: str, db) -> list[str]:
    """Expand a channel's live recipient set at send-time (excludes sender).

    Standard channels resolve dynamically from the users collection so
    headcount changes are reflected. Direct channels use the frozen
    ``member_user_ids`` list.
    """
    tid = channel.get("tenant_id") or ""
    kind = channel.get("kind")
    if kind == "all_hands":
        ids = await _staff_user_ids(db, tid)
    elif kind == "department":
        dep = channel.get("department")
        ids = await _staff_user_ids(db, tid, department=dep) if dep else []
    elif kind == "direct":
        ids = list(channel.get("member_user_ids") or [])
    else:
        ids = []
    return [uid for uid in ids if uid and uid != sender_id]


async def _visible_standard_channels(
    db, tenant_id: str, *, department: str | None,
) -> list[dict]:
    """Return the caller's standard channel set. Auto-provisions any
    missing rows so first-boot tenants get channels on first ``GET``.
    """
    out: list[dict] = []
    # all_hands
    ah = await db.walkie_channels.find_one(
        {"tenant_id": tenant_id, "kind": "all_hands"}, {"_id": 0},
    )
    if not ah:
        ah = _new_channel(tenant_id, kind="all_hands")
        await db.walkie_channels.insert_one(dict(ah))
    out.append(ah)
    # department channels — return the caller's department (staff), or
    # both when the caller is admin/manager (they see everything).
    deps = [department] if department in DEPARTMENTS else list(DEPARTMENTS)
    for dep in deps:
        row = await db.walkie_channels.find_one(
            {"tenant_id": tenant_id, "kind": "department", "department": dep},
            {"_id": 0},
        )
        if not row:
            row = _new_channel(tenant_id, kind="department", department=dep)
            await db.walkie_channels.insert_one(dict(row))
        out.append(row)
    return out


def _new_channel(
    tenant_id: str,
    *,
    kind: str,
    department: str | None = None,
    member_user_ids: list[str] | None = None,
) -> dict:
    import uuid
    now = _now_iso()
    return {
        "id": uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "kind": kind,
        "department": department,
        "member_user_ids": list(member_user_ids or []),
        "created_at": now,
        "updated_at": now,
    }


async def list_visible_channels_for_user(user: dict, db) -> list[dict]:
    """Return the caller's full visible channel set (standard + directs)."""
    tid = user.get("tenant_id") or ""
    role = (user.get("role") or "").lower()
    dep = _norm_dep(user.get("department")) or None
    if role in ("super_admin", "admin", "manager", "owner", "dispatcher"):
        standards = await _visible_standard_channels(db, tid, department=None)
    else:
        standards = await _visible_standard_channels(db, tid, department=dep)
    # Direct channels the caller is a member of.
    uid = user.get("id") or ""
    direct_rows = await db.walkie_channels.find(
        {"tenant_id": tid, "kind": "direct", "member_user_ids": uid},
        {"_id": 0},
    ).to_list(length=None)
    return standards + list(direct_rows)


async def is_channel_member(channel: dict, user: dict, db) -> bool:
    """Membership check — used for send + listen gating."""
    tid = user.get("tenant_id") or ""
    if channel.get("tenant_id") != tid:
        return False
    role = (user.get("role") or "").lower()
    if role in ("customer",):
        return False
    kind = channel.get("kind")
    uid = user.get("id") or ""
    if kind == "all_hands":
        return role in STAFF_ROLES
    if kind == "department":
        if role in ("super_admin", "admin", "manager", "owner", "dispatcher"):
            return True
        return (_norm_dep(user.get("department")) or "") == (channel.get("department") or "")
    if kind == "direct":
        return uid in (channel.get("member_user_ids") or [])
    return False


async def get_or_create_direct_channel(caller: dict, target_user_id: str, db) -> dict:
    """Idempotent 1:1 channel between caller and target."""
    tid = caller.get("tenant_id") or ""
    caller_id = caller.get("id") or ""
    if not target_user_id or target_user_id == caller_id:
        raise ValueError("target_user_id must differ from caller")
    target = await db.users.find_one(
        {"id": target_user_id, "tenant_id": tid, "active": {"$ne": False}},
        {"_id": 0, "id": 1, "role": 1},
    )
    if not target:
        raise LookupError("target user not found in tenant")
    if (target.get("role") or "").lower() == "customer":
        raise ValueError("walkie is staff-only")
    pair = sorted([caller_id, target_user_id])
    existing = await db.walkie_channels.find_one({
        "tenant_id": tid,
        "kind": "direct",
        "member_user_ids": {"$all": pair, "$size": 2},
    }, {"_id": 0})
    if existing:
        return existing
    row = _new_channel(tid, kind="direct", member_user_ids=pair)
    await db.walkie_channels.insert_one(dict(row))
    return row


async def bootstrap_standard_channels(db, tenant_id: str) -> dict:
    """Idempotent — create ``all_hands`` + the two department channels
    for a tenant if they don't already exist. Safe to re-run on every
    boot. Returns a small summary for logging."""
    created = 0
    if not await db.walkie_channels.find_one(
        {"tenant_id": tenant_id, "kind": "all_hands"}, {"_id": 1},
    ):
        await db.walkie_channels.insert_one(dict(_new_channel(tenant_id, kind="all_hands")))
        created += 1
    for dep in DEPARTMENTS:
        if not await db.walkie_channels.find_one(
            {"tenant_id": tenant_id, "kind": "department", "department": dep}, {"_id": 1},
        ):
            await db.walkie_channels.insert_one(
                dict(_new_channel(tenant_id, kind="department", department=dep)),
            )
            created += 1
    return {"tenant_id": tenant_id, "created": created}


async def ensure_indexes(db) -> None:
    """Create the required indexes for the three walkie collections.

    Includes the critical TTL index on ``walkie_messages.expires_at``
    (``expireAfterSeconds: 0``) so Mongo enforces 24h cleanup natively.
    Idempotent — Mongo skips index creation for identical specs.
    """
    await db.walkie_channels.create_index([("tenant_id", 1), ("kind", 1)])
    await db.walkie_channels.create_index([("tenant_id", 1), ("department", 1)])
    await db.walkie_channels.create_index([("tenant_id", 1), ("member_user_ids", 1)])
    await db.walkie_messages.create_index(
        [("tenant_id", 1), ("channel_id", 1), ("created_at", -1)],
    )
    await db.walkie_messages.create_index("expires_at", expireAfterSeconds=0)
    await db.walkie_receipts.create_index(
        [("tenant_id", 1), ("recipient_user_id", 1), ("listened_at", 1)],
    )
    await db.walkie_receipts.create_index("message_id")
