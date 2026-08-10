"""Aug-2026 · Autobilling Runs soft-delete — backend contract.

Exercises the four endpoints landed in Fix #5:
  * ``GET  /api/autobilling-runs?include_deleted=true`` — filter flag.
  * ``POST /api/autobilling/runs/bulk-delete``           — bulk soft-delete.
  * ``DELETE /api/autobilling/runs/{id}``                — per-row soft-delete.
  * ``POST /api/autobilling/runs/{id}/restore``          — restore.

Role contract (per user spec):
  * admin + super_admin + owner — can hit every endpoint, no state guards.
  * manager / technician / customer — 403 on writes; the include_deleted
    query flag is a no-op for reads (list endpoint is already
    admin-gated by ``require_admin``, so non-admin roles never reach
    the flag).

All tests run in-process against ``services.marketing.merge_tags``-style
pure logic — the endpoint handlers are called directly with mocked
``db.autobilling_runs`` operations to avoid the Motor cross-loop issue
Backlog #3 is chasing.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest


# ─── Fake db helpers ────────────────────────────────────────────────────
class _FakeCollection:
    """Minimal Motor-style async collection stub that keeps documents in
    a Python list. Sufficient for the four endpoints' happy-path +
    edge-cases."""

    def __init__(self, docs: List[Dict[str, Any]] | None = None):
        self.docs: List[Dict[str, Any]] = list(docs or [])
        self.writes: List[tuple] = []  # audit log of update ops

    async def find_one(self, q: Dict[str, Any], projection=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return dict(d)
        return None

    async def update_one(self, q: Dict[str, Any], upd: Dict[str, Any]):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                if "$set" in upd:
                    for k, v in upd["$set"].items():
                        d[k] = v
                if "$unset" in upd:
                    for k in upd["$unset"]:
                        d.pop(k, None)
                self.writes.append((dict(q), upd))
                return
        raise AssertionError(f"no match for {q!r}")

    def find(self, q: Dict[str, Any], projection=None):
        # Return a chainable cursor that supports .sort(...).to_list(...).
        matches = []
        for d in self.docs:
            ok = True
            for k, v in q.items():
                dv = d.get(k)
                if isinstance(v, dict) and "$in" in v:
                    if dv not in v["$in"]:
                        ok = False; break
                elif isinstance(v, dict) and "$gte" in v:
                    if dv is None or dv < v["$gte"]:
                        ok = False; break
                elif dv != v:
                    ok = False; break
            if ok:
                matches.append(dict(d))
        return _FakeCursor(matches)


class _FakeCursor:
    def __init__(self, docs): self.docs = docs
    def sort(self, key, direction=-1):
        rev = (direction == -1)
        self.docs = sorted(self.docs, key=lambda d: d.get(key) or "", reverse=rev)
        return self
    async def to_list(self, cap): return self.docs[:cap]


@pytest.fixture
def fake_db(monkeypatch):
    """Swap ``config.db.autobilling_runs`` and ``.audits`` for
    in-memory fakes. Every test starts with a fresh collection."""
    from config import db as _real_db
    coll = _FakeCollection()
    audits = _FakeCollection()
    monkeypatch.setattr(_real_db, "autobilling_runs", coll, raising=False)
    monkeypatch.setattr(_real_db, "audits", audits, raising=False)
    return {"runs": coll, "audits": audits}


TENANT = {"id": "tenant-A", "name": "Vistancia"}
ADMIN = {"id": "u-admin", "email": "admin@x", "role": "admin"}
SUPER = {"id": "u-super", "email": "super@x", "role": "super_admin"}
OWNER = {"id": "u-owner", "email": "owner@x", "role": "owner"}
MANAGER = {"id": "u-mgr", "email": "m@x", "role": "manager"}
TECH = {"id": "u-tech", "email": "t@x", "role": "technician"}
CUSTOMER = {"id": "u-cust", "email": "c@x", "role": "customer"}


# ─── require_admin gate ─────────────────────────────────────────────────
@pytest.mark.parametrize("user", [ADMIN, SUPER, OWNER])
def test_require_admin_lets_admin_super_owner_through(user):
    from utils import require_admin
    assert require_admin(user)["id"] == user["id"]


@pytest.mark.parametrize("user", [MANAGER, TECH, CUSTOMER])
def test_require_admin_rejects_manager_tech_customer(user):
    from utils import require_admin
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ex:
        require_admin(user)
    assert ex.value.status_code == 403


# ─── bulk_delete endpoint ───────────────────────────────────────────────
def _make_run(rid: str, **overrides) -> Dict[str, Any]:
    return {
        "id": rid,
        "tenant_id": TENANT["id"],
        "ts": "2026-08-10T00:00:00",
        "status": overrides.get("status", "fired"),
        "plan_id": overrides.get("plan_id", "plan-1"),
        "message": overrides.get("message", "ok"),
        **{k: v for k, v in overrides.items() if k not in {"status", "plan_id", "message"}},
    }


def test_admin_can_bulk_soft_delete_regardless_of_run_status(fake_db):
    import asyncio
    async def _run():
        """No 'running soon' guard — admin can hide ANY status, even a
        freshly-fired one."""
        from routers.finances import (
            bulk_delete_autobilling_runs, _AutobillingRunsBulkDeleteIn,
        )
        fake_db["runs"].docs = [
            _make_run("r1", status="fired"),
            _make_run("r2", status="scheduled"),
            _make_run("r3", status="late_missed"),
        ]
        body = _AutobillingRunsBulkDeleteIn(ids=["r1", "r2", "r3"])
        res = await bulk_delete_autobilling_runs(body, user=ADMIN, tenant=TENANT)
        assert res["deleted"] == 3
        assert res["skipped"] == 0
        for d in fake_db["runs"].docs:
            assert d.get("deleted_at"), f"row {d['id']} missing deleted_at"
            assert d.get("deleted_by_user_id") == ADMIN["id"]


    asyncio.run(_run())

def test_super_admin_can_bulk_soft_delete(fake_db):
    import asyncio
    async def _run():
        from routers.finances import (
            bulk_delete_autobilling_runs, _AutobillingRunsBulkDeleteIn,
        )
        fake_db["runs"].docs = [_make_run("r1"), _make_run("r2")]
        res = await bulk_delete_autobilling_runs(
            _AutobillingRunsBulkDeleteIn(ids=["r1", "r2"]),
            user=SUPER, tenant=TENANT,
        )
        assert res["deleted"] == 2
        assert all(d.get("deleted_by_user_id") == SUPER["id"]
                    for d in fake_db["runs"].docs)


    asyncio.run(_run())

def test_bulk_delete_is_idempotent_returns_already_deleted(fake_db):
    import asyncio
    async def _run():
        from routers.finances import (
            bulk_delete_autobilling_runs, _AutobillingRunsBulkDeleteIn,
        )
        fake_db["runs"].docs = [
            _make_run("r1", deleted_at="2026-08-09T00:00:00"),
        ]
        res = await bulk_delete_autobilling_runs(
            _AutobillingRunsBulkDeleteIn(ids=["r1"]),
            user=ADMIN, tenant=TENANT,
        )
        assert res["deleted"] == 0
        assert res["skipped"] == 1
        assert res["results"][0]["reason"] == "already_deleted"


    asyncio.run(_run())

def test_bulk_delete_unknown_id_returns_not_found(fake_db):
    import asyncio
    async def _run():
        from routers.finances import (
            bulk_delete_autobilling_runs, _AutobillingRunsBulkDeleteIn,
        )
        fake_db["runs"].docs = [_make_run("r1")]
        res = await bulk_delete_autobilling_runs(
            _AutobillingRunsBulkDeleteIn(ids=["r-missing"]),
            user=ADMIN, tenant=TENANT,
        )
        assert res["deleted"] == 0
        assert res["results"][0]["reason"] == "not_found"


    asyncio.run(_run())

def test_bulk_delete_5_ids_marks_all(fake_db):
    import asyncio
    async def _run():
        from routers.finances import (
            bulk_delete_autobilling_runs, _AutobillingRunsBulkDeleteIn,
        )
        fake_db["runs"].docs = [_make_run(f"r{i}") for i in range(1, 6)]
        res = await bulk_delete_autobilling_runs(
            _AutobillingRunsBulkDeleteIn(ids=[f"r{i}" for i in range(1, 6)]),
            user=ADMIN, tenant=TENANT,
        )
        assert res["deleted"] == 5
        for d in fake_db["runs"].docs:
            assert d.get("deleted_at")


    asyncio.run(_run())

def test_bulk_delete_empty_ids_400(fake_db):
    import asyncio
    async def _run():
        from routers.finances import (
            bulk_delete_autobilling_runs, _AutobillingRunsBulkDeleteIn,
        )
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as ex:
            await bulk_delete_autobilling_runs(
                _AutobillingRunsBulkDeleteIn(ids=[]),
                user=ADMIN, tenant=TENANT,
            )
        assert ex.value.status_code == 400


    asyncio.run(_run())

# ─── DELETE /autobilling/runs/{id} per-row ──────────────────────────────
def test_per_row_soft_delete_happy_path(fake_db):
    import asyncio
    async def _run():
        from routers.finances import soft_delete_autobilling_run
        fake_db["runs"].docs = [_make_run("r1")]
        res = await soft_delete_autobilling_run("r1", user=ADMIN, tenant=TENANT)
        assert res["ok"] is True
        assert res["id"] == "r1"
        assert fake_db["runs"].docs[0].get("deleted_at")


    asyncio.run(_run())

def test_per_row_soft_delete_404_when_not_found(fake_db):
    import asyncio
    async def _run():
        from routers.finances import soft_delete_autobilling_run
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as ex:
            await soft_delete_autobilling_run("r-x", user=ADMIN, tenant=TENANT)
        assert ex.value.status_code == 404


    asyncio.run(_run())

# ─── POST /autobilling/runs/{id}/restore ────────────────────────────────
def test_restore_flips_deleted_at_back_to_none(fake_db):
    import asyncio
    async def _run():
        from routers.finances import restore_autobilling_run
        fake_db["runs"].docs = [
            _make_run("r1", deleted_at="2026-08-09T00:00:00",
                        deleted_by_user_id="u-admin"),
        ]
        res = await restore_autobilling_run("r1", user=ADMIN, tenant=TENANT)
        assert res["restored"] is True
        row = fake_db["runs"].docs[0]
        assert row["deleted_at"] is None
        assert "deleted_by_user_id" not in row
        assert row.get("restored_at")
        assert row.get("restored_by_user_id") == ADMIN["id"]


    asyncio.run(_run())

def test_restore_no_op_when_row_not_deleted(fake_db):
    import asyncio
    async def _run():
        from routers.finances import restore_autobilling_run
        fake_db["runs"].docs = [_make_run("r1")]  # not deleted
        res = await restore_autobilling_run("r1", user=SUPER, tenant=TENANT)
        assert res.get("already_active") is True


    asyncio.run(_run())

def test_restore_404_when_not_found(fake_db):
    import asyncio
    async def _run():
        from routers.finances import restore_autobilling_run
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as ex:
            await restore_autobilling_run("r-x", user=ADMIN, tenant=TENANT)
        assert ex.value.status_code == 404


    asyncio.run(_run())

# ─── GET /autobilling-runs?include_deleted ──────────────────────────────
def test_list_hides_deleted_by_default(fake_db):
    import asyncio
    async def _run():
        from routers.finances import list_autobilling_runs
        fake_db["runs"].docs = [
            _make_run("r1"),
            _make_run("r2", deleted_at="2026-08-09T00:00:00"),
        ]
        rows = await list_autobilling_runs(
            plan_id=None, status=None, since=None,
            include_deleted=False, user=ADMIN, tenant=TENANT,
        )
        ids = [r["id"] for r in rows]
        assert "r1" in ids
        assert "r2" not in ids


    asyncio.run(_run())

def test_list_includes_deleted_when_flag_true(fake_db):
    import asyncio
    async def _run():
        from routers.finances import list_autobilling_runs
        fake_db["runs"].docs = [
            _make_run("r1"),
            _make_run("r2", deleted_at="2026-08-09T00:00:00"),
        ]
        rows = await list_autobilling_runs(
            plan_id=None, status=None, since=None,
            include_deleted=True, user=ADMIN, tenant=TENANT,
        )
        ids = [r["id"] for r in rows]
        assert "r1" in ids and "r2" in ids

    asyncio.run(_run())
