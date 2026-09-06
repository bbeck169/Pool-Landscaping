"""Phase R1 · Feb-2026 — Index migration idempotency + sentinel tests.

Each test body is a single ``asyncio.run(...)`` invocation so
motor's internal loop reference stays consistent within the run
(motor caches its selector loop on first collection I/O — a
new-loop-per-call pattern crosses loops and errors out).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from dotenv import dotenv_values

from services.reporting.indexes import (
    MIGRATION_KEY,
    _R1_INDEXES,
    ensure_indexes,
    run,
)

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")


def _run_case(coro_fn):
    """Open a fresh motor client inside a single asyncio.run so
    the motor loop-binding stays consistent across every await
    in the case."""
    async def _wrapped():
        from motor.motor_asyncio import AsyncIOMotorClient
        c = AsyncIOMotorClient(_ENV["MONGO_URL"])
        db = c[_ENV["DB_NAME"]]
        try:
            return await coro_fn(db)
        finally:
            c.close()
    return asyncio.run(_wrapped())


class TestIdempotency:
    def test_second_run_creates_zero(self):
        async def _case(db):
            await ensure_indexes(db)
            s2 = await ensure_indexes(db)
            assert len(s2["created"]) == 0, (
                f"second run created {s2['created']}"
            )
            assert len(s2["already"]) == len(_R1_INDEXES)
            assert s2["failed"] == []
        _run_case(_case)

    def test_sentinel_written_and_survives_rerun(self):
        async def _case(db):
            await ensure_indexes(db)
            sentinel = await db.migration_status.find_one(
                {"_id": MIGRATION_KEY})
            assert sentinel is not None
            assert sentinel.get("completed_at")
            prior_ts = sentinel["completed_at"]
            s2 = await ensure_indexes(db)
            assert s2["sentinel_hit"] is True
            sentinel2 = await db.migration_status.find_one(
                {"_id": MIGRATION_KEY})
            assert sentinel2["completed_at"] == prior_ts, (
                "sentinel timestamp changed on hot rerun"
            )
        _run_case(_case)


class TestTiming:
    def test_hot_rerun_finishes_under_500ms(self):
        async def _case(db):
            await ensure_indexes(db)  # warm
            s = await ensure_indexes(db)
            assert s["elapsed_ms"] < 500, (
                f"hot rerun took {s['elapsed_ms']}ms — regression"
            )
        _run_case(_case)


class TestSelfHeal:
    def test_dropped_index_recreated_without_sentinel_overwrite(self):
        async def _case(db):
            await ensure_indexes(db)
            coll, _spec, name = _R1_INDEXES[-1]
            try:
                await db[coll].drop_index(name)
            except Exception:
                pytest.skip(f"index {name} not present to drop")
            s = await ensure_indexes(db)
            assert (coll, name) in s["created"], (
                "dropped index was NOT recreated"
            )
        _run_case(_case)


class TestPublicSurface:
    def test_run_and_ensure_indexes_equivalent(self):
        async def _case(db):
            a = await ensure_indexes(db)
            b = await run(db)
            assert set(a.keys()) == set(b.keys())
        _run_case(_case)
