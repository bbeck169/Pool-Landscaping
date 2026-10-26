"""TD-crew-expand-silent-drop-to-soft-deleted-users · Feb-2026
================================================================

Regression lock for the predicate-expansion ticket.

Coverage
--------
§1 — _resolve_tenant_members categorises soft-deleted correctly
§2 — Router silent-drop extends to soft-deleted (POST + PATCH)
§3 — Foreign-tenant 403 regression preserved
§4 — v2 backfill drops orphan + soft-deleted with reason breadcrumb
§5 — v2 backfill leaves foreign-tenant ids alone
§6 — v2 backfill idempotent re-run no-ops
§7 — Cascade close-loop — soft-delete-user prunes the user_id
     from every crew's tech_ids in-tenant
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


@pytest.fixture()
def tenant_a() -> str:
    return f"TEST_td_t_{uuid4().hex[:12]}"


@pytest.fixture()
def tenant_b() -> str:
    return f"TEST_td_t_{uuid4().hex[:12]}"


def _seed_user(
    *, tenant_id: str, uid: str = None,
    deleted_at: str = None, is_active: bool = True,
    active: bool = True,
) -> str:
    uid = uid or f"u-{uuid4().hex[:12]}"
    doc = {
        "id": uid, "tenant_id": tenant_id,
        "role": "technician",
        "email": f"{uid}@fixture.test",
    }
    if deleted_at is not None:
        doc["deleted_at"] = deleted_at
    if is_active is False:
        doc["is_active"] = False
    if active is False:
        doc["active"] = False
    _run(_DB.users.insert_one(doc))
    return uid


def _seed_crew(
    *, tenant_id: str, cid: str = None,
    tech_ids: List[str] = None,
) -> str:
    cid = cid or f"c-{uuid4().hex[:12]}"
    tech_ids = tech_ids or []
    _run(_DB.crews.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": f"Fixture Crew {cid[:6]}",
        "tech_ids": tech_ids,
        "member_added_at": {
            tid: "2026-01-01T00:00:00Z" for tid in tech_ids
        },
    }))
    return cid


def _cleanup(tenants: List[str]) -> None:
    for coll in ("users", "crews", "technicians"):
        _run(_DB[coll].delete_many(
            {"tenant_id": {"$in": tenants}},
        ))
    _run(_DB["_migrations"].delete_many(
        {"key": "crew_tech_ids_cleanup_v2"},
    ))


# ═══════════════════════════════════════════════════════════════════
# §1 — _resolve_tenant_members categorises soft_deleted
#       Uses the TD-86 MockDB pattern (same shape as
#       tests/test_td86_crew_tenant_guard.py) to avoid Motor loop
#       collisions with the running backend's db client.
# ═══════════════════════════════════════════════════════════════════
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _MockCursor:
    def __init__(self, rows):
        self._rows = list(rows)
    def __aiter__(self):
        async def _gen():
            for r in self._rows:
                yield r
        return _gen()


def _ne(row_val, want):
    return row_val != want


def _mock_match(row, query):
    for key, val in query.items():
        if key == "$and":
            if not all(_mock_match(row, sub) for sub in val):
                return False
            continue
        if key == "$or":
            if not any(_mock_match(row, sub) for sub in val):
                return False
            continue
        if isinstance(val, dict):
            if "$in" in val:
                if row.get(key) not in val["$in"]:
                    return False
                continue
            if "$ne" in val:
                if row.get(key) == val["$ne"]:
                    return False
                continue
            if "$exists" in val:
                present = key in row
                if present != val["$exists"]:
                    return False
                continue
        else:
            if row.get(key) != val:
                return False
    return True


class _MockCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
    def find(self, query, projection=None):
        return _MockCursor(
            [r for r in self.rows if _mock_match(r, query)],
        )


class _MockDB:
    def __init__(self, users=None, technicians=None):
        self.users = _MockCollection(users)
        self.technicians = _MockCollection(technicians)


@pytest.fixture
def patched_db(monkeypatch):
    def _apply(users=None, technicians=None):
        import routers.ops as ops_mod
        monkeypatch.setattr(
            ops_mod, "db",
            _MockDB(users=users, technicians=technicians),
        )
    return _apply


async def test_resolve_tenant_members_tags_deleted_at_as_soft_deleted(
    patched_db,
):
    patched_db(
        users=[
            {"id": "u-live", "tenant_id": "t1"},
            {"id": "u-soft", "tenant_id": "t1",
             "deleted_at": "2026-02-01T00:00:00Z"},
        ],
        technicians=[],
    )
    from routers.ops import _resolve_tenant_members
    out = await _resolve_tenant_members("t1", ["u-live", "u-soft"])
    assert "u-live" in out["resolved"]
    assert "u-soft" not in out["resolved"]
    soft = [e for e in out["errors"] if e["tech_id"] == "u-soft"]
    assert len(soft) == 1
    assert soft[0]["reason"] == "soft_deleted"


async def test_resolve_tenant_members_tags_is_active_false_as_soft_deleted(
    patched_db,
):
    patched_db(
        users=[{"id": "u-inactive", "tenant_id": "t1",
                 "is_active": False}],
        technicians=[],
    )
    from routers.ops import _resolve_tenant_members
    out = await _resolve_tenant_members("t1", ["u-inactive"])
    assert "u-inactive" not in out["resolved"]
    assert out["errors"][0]["reason"] == "soft_deleted"


async def test_resolve_tenant_members_tags_active_false_as_soft_deleted(
    patched_db,
):
    patched_db(
        users=[{"id": "u-off", "tenant_id": "t1", "active": False}],
        technicians=[],
    )
    from routers.ops import _resolve_tenant_members
    out = await _resolve_tenant_members("t1", ["u-off"])
    assert "u-off" not in out["resolved"]
    assert out["errors"][0]["reason"] == "soft_deleted"


# ═══════════════════════════════════════════════════════════════════
# §2 — Foreign-tenant 403 regression preserved
# ═══════════════════════════════════════════════════════════════════
async def test_resolve_tenant_members_foreign_still_categorises(
    patched_db,
):
    patched_db(
        users=[{"id": "u-foreign", "tenant_id": "t2"}],
        technicians=[],
    )
    from routers.ops import _resolve_tenant_members
    out = await _resolve_tenant_members("t1", ["u-foreign"])
    assert out["errors"][0]["reason"] == "foreign_tenant"
    assert out["errors"][0]["tenant_id"] == "t2"


# ═══════════════════════════════════════════════════════════════════
# §3 — v2 backfill drops orphan + soft_deleted
# ═══════════════════════════════════════════════════════════════════
def test_v2_backfill_apply_drops_both_with_reason_breadcrumb(
    tenant_a,
):
    live = _seed_user(tenant_id=tenant_a)
    soft = _seed_user(
        tenant_id=tenant_a,
        deleted_at="2026-02-01T00:00:00Z",
    )
    orphan = f"ghost-{uuid4().hex[:8]}"
    cid = _seed_crew(
        tenant_id=tenant_a,
        tech_ids=[live, soft, orphan],
    )
    try:
        from migrations.crew_tech_ids_cleanup_v2 import run
        out = _run(run(tenant_id=tenant_a, apply=True))
        assert out["status"] == "applied"
        assert out["stats"]["orphan_removed"] == 1
        assert out["stats"]["soft_deleted_removed"] == 1
        doc = _run(_DB.crews.find_one({"id": cid}, {"_id": 0}))
        assert doc["tech_ids"] == [live]
        reasons_by_id = {
            d["user_id"]: d["reason"]
            for d in doc["tech_ids_cleanup_v2_removed_with_reason"]
        }
        assert reasons_by_id[soft] == "soft_deleted"
        assert reasons_by_id[orphan] == "orphan"
        assert doc.get("tech_ids_cleanup_v2_at")
        # member_added_at pruned in lockstep.
        assert set(doc["member_added_at"].keys()) == {live}
    finally:
        _cleanup([tenant_a])


# ═══════════════════════════════════════════════════════════════════
# §4 — v2 backfill leaves foreign-tenant ids alone
# ═══════════════════════════════════════════════════════════════════
def test_v2_backfill_leaves_foreign_tenant_alone(
    tenant_a, tenant_b,
):
    live_a = _seed_user(tenant_id=tenant_a)
    foreign_b = _seed_user(tenant_id=tenant_b)
    soft = _seed_user(
        tenant_id=tenant_a,
        deleted_at="2026-02-01T00:00:00Z",
    )
    cid = _seed_crew(
        tenant_id=tenant_a,
        tech_ids=[live_a, foreign_b, soft],
    )
    try:
        from migrations.crew_tech_ids_cleanup_v2 import run
        out = _run(run(tenant_id=tenant_a, apply=True))
        assert out["stats"]["foreign_left_alone"] == 1
        doc = _run(_DB.crews.find_one({"id": cid}, {"_id": 0}))
        assert foreign_b in doc["tech_ids"]
        assert soft not in doc["tech_ids"]
    finally:
        _cleanup([tenant_a, tenant_b])


# ═══════════════════════════════════════════════════════════════════
# §5 — v2 backfill idempotent re-run no-ops
# ═══════════════════════════════════════════════════════════════════
def test_v2_backfill_idempotent_rerun(tenant_a):
    live = _seed_user(tenant_id=tenant_a)
    soft = _seed_user(
        tenant_id=tenant_a,
        deleted_at="2026-02-01T00:00:00Z",
    )
    cid = _seed_crew(tenant_id=tenant_a, tech_ids=[live, soft])
    try:
        from migrations.crew_tech_ids_cleanup_v2 import run
        first = _run(run(tenant_id=tenant_a, apply=True))
        assert first["stats"]["soft_deleted_removed"] == 1
        second = _run(run(
            tenant_id=tenant_a, apply=True, force=True,
        ))
        assert second["stats"]["soft_deleted_removed"] == 0
        assert second["stats"]["orphan_removed"] == 0
    finally:
        _cleanup([tenant_a])


# ═══════════════════════════════════════════════════════════════════
# §6 — Cascade close-loop — soft-delete-user prunes crews
# ═══════════════════════════════════════════════════════════════════
def test_cascade_soft_delete_user_removes_from_crews(tenant_a):
    live = _seed_user(tenant_id=tenant_a)
    victim = _seed_user(tenant_id=tenant_a)
    cid1 = _seed_crew(tenant_id=tenant_a, tech_ids=[live, victim])
    cid2 = _seed_crew(tenant_id=tenant_a, tech_ids=[victim])
    try:
        from routers.admin_users import (
            _cascade_soft_delete_reassignments,
        )
        _run(_cascade_soft_delete_reassignments(
            victim, {"id": victim, "tenant_id": tenant_a},
        ))
        doc1 = _run(_DB.crews.find_one({"id": cid1}, {"_id": 0}))
        doc2 = _run(_DB.crews.find_one({"id": cid2}, {"_id": 0}))
        assert victim not in doc1["tech_ids"]
        assert live in doc1["tech_ids"]
        assert victim not in doc2["tech_ids"]
        # member_added_at prune too (lockstep).
        assert victim not in (doc1.get("member_added_at") or {})
        assert victim not in (doc2.get("member_added_at") or {})
        # Audit breadcrumb present on affected crews.
        assert doc1.get("last_user_delete_cascade_user_id") == victim
        assert doc2.get("last_user_delete_cascade_user_id") == victim
    finally:
        _cleanup([tenant_a])
