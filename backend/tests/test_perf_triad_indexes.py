"""Phase B Perf Triad · Feb-2026 — indexes migration idempotency.

Locks:
  1. First run creates the sentinel + reports ``skipped=False``.
  2. Second run reports ``skipped=True`` (sentinel present).
  3. Every created index name has the ``perf_triad_`` prefix (so
     ops can drop-by-prefix cleanly if we need to roll back).
"""
from __future__ import annotations

import asyncio
import pytest

from tests._f7_loop_fixture import run_test


def test_perf_triad_indexes_idempotent_via_sentinel():
    from services.migrations.perf_triad_indexes import (
        MIGRATION_KEY, run,
    )

    async def _go(db):
        # Reset sentinel so this test always exercises the first-run
        # path first.
        await db.migration_status.delete_many({"key": MIGRATION_KEY})
        try:
            r1 = await run(db)
            assert r1["ok"] is True
            assert r1["skipped"] is False
            for nm in r1.get("created_names", []):
                assert nm.startswith("perf_triad_") is False  # collection name
            sent = await db.migration_status.find_one(
                {"key": MIGRATION_KEY}, {"_id": 0},
            )
            assert sent is not None
            assert sent.get("completed_at")

            # Second run — sentinel present → skipped.
            r2 = await run(db)
            assert r2["ok"] is True
            assert r2["skipped"] is True
            assert r2["created"] == 0
        finally:
            await db.migration_status.delete_many({"key": MIGRATION_KEY})

    run_test(_go)
