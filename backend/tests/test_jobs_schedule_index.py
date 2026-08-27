"""Feb 2026 · Task B — Schedule perf compound index.

Regression guard for the ``(tenant_id, scheduled_date)`` compound
index that ``routers.jobs.ensure_indexes`` registers at boot. Without
this index the schedule window query performs a tenant-wide
collection scan on prod-scale accounts (thousands of jobs).

We also assert that a schedule-window ``find`` uses the index via an
``explain`` plan check — an IXSCAN or FETCH-over-IXSCAN must win over
COLLSCAN.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _db():
    return AsyncIOMotorClient(
        os.environ["MONGO_URL"], io_loop=_LOOP,
    )[os.environ["DB_NAME"]]


def _run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture(scope="module", autouse=True)
def _ensure_index_registered():
    """Idempotently run the boot ensure_indexes so the test doesn't
    depend on server startup timing."""
    async def _go():
        import config as _cfg
        _cfg.db = _db()
        from routers import jobs as _jobs_mod
        _jobs_mod.db = _cfg.db
        await _jobs_mod.ensure_indexes()
    _run(_go())
    yield


def test_tenant_id_scheduled_date_index_exists_on_jobs():
    async def _go():
        db = _db()
        idxs = await db.jobs.list_indexes().to_list(50)
        names = {i.get("name") for i in idxs}
        keys = [i.get("key") for i in idxs]
        assert "tenant_id_1_scheduled_date_1" in names, (
            f"missing compound index; existing indexes: {names}"
        )
        # Ensure the key spec matches what we expect (order matters
        # for compound sort — tenant_id MUST be the prefix).
        target = None
        for k in keys:
            if k and list(k.items()) == [("tenant_id", 1), ("scheduled_date", 1)]:
                target = k
                break
        assert target is not None, (
            f"compound index key spec drifted: {keys}"
        )
    _run(_go())


def test_schedule_window_query_uses_index_not_collscan():
    """explain() on a schedule-shaped query must NOT resolve to a
    COLLSCAN — the new compound index (or an existing tech-scoped
    one) must win."""
    async def _go():
        db = _db()
        q = {
            "tenant_id": "any-tenant-id-fine-here",
            "scheduled_date": {"$gte": "2026-06-01", "$lte": "2026-12-01"},
            "$or": [{"deleted_at": None},
                     {"deleted_at": {"$exists": False}}],
        }
        exp = await db.command(
            "explain", {"find": "jobs", "filter": q},
            verbosity="queryPlanner",
        )
        winning = exp.get("queryPlanner", {}).get("winningPlan", {})
        # Recursively walk the plan looking for stage names.
        stages: list[str] = []
        def _walk(node):
            if not isinstance(node, dict):
                return
            s = node.get("stage")
            if s:
                stages.append(s)
            for k in ("inputStage", "innerStage", "outerStage"):
                if k in node:
                    _walk(node[k])
            for child in node.get("inputStages", []) or []:
                _walk(child)
        _walk(winning)
        # We require an index scan somewhere in the plan.
        assert "IXSCAN" in stages, (
            f"schedule window query should use an index; stages={stages}"
        )
        # And no full collection scan.
        assert "COLLSCAN" not in stages, (
            f"schedule window query fell back to COLLSCAN; stages={stages}"
        )
    _run(_go())
