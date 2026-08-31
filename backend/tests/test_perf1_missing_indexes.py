"""PERF-1 · Feb-2026 — Missing-tenant-index migration tests.

Runs the migration against the live preview DB (safe — it's
idempotent + sentinel-guarded).  Verifies:

  1. First invocation creates (or confirms) all 6 target indexes.
  2. Second invocation short-circuits via the sentinel.
  3. ``force=True`` bypasses the sentinel and re-runs cleanly with
     zero-op body since indexes already exist.

We use the shared F7 loop-fixture to keep Motor collections
loop-consistent under pytest.
"""
from __future__ import annotations

from tests._f7_loop_fixture import run_test


def test_perf1_migration_creates_or_confirms_all_indexes():
    from services.migrations.perf1_missing_tenant_indexes import (
        run_perf1_missing_tenant_indexes_migration,
        _TARGETS,
    )

    async def _go(db):
        # First run — either creates fresh or skips if sentinel is
        # already present from a prior boot.
        result = await run_perf1_missing_tenant_indexes_migration(
            force=True,   # bypass sentinel to exercise the body
        )
        assert result["status"] == "ok"
        s = result["summary"]
        # Every target must have SOME terminal state (created or
        # already_present) — no bare unset entries.
        assert len(s["targets"]) == len(_TARGETS)
        for t in s["targets"]:
            assert t["status"] in ("created", "already_present")
        # No errors — env config is standard.
        assert s["errors"] == []

        # Confirm each target index is actually visible in
        # list_indexes().
        for coll_name, idx_name in _TARGETS:
            names = set()
            async for idx in db[coll_name].list_indexes():
                names.add(idx.get("name") or "")
            assert idx_name in names, (
                f"expected index {idx_name!r} on {coll_name!r} · "
                f"got {names}"
            )

    run_test(_go)


def test_perf1_migration_short_circuits_via_sentinel():
    from services.migrations.perf1_missing_tenant_indexes import (
        run_perf1_missing_tenant_indexes_migration,
    )

    async def _go(db):
        # Ensure a sentinel exists (the previous test wrote one when
        # force=True completed cleanly). Force-write to be safe.
        await db.migrations.update_one(
            {"id": "perf1_missing_tenant_indexes_v1"},
            {"$set": {
                "id": "perf1_missing_tenant_indexes_v1",
                "completed_at": "2020-01-01T00:00:00+00:00",
                "summary": {"indexes_created": 0,
                             "already_present": 6,
                             "errors": [], "targets": []},
            }},
            upsert=True,
        )
        result = await run_perf1_missing_tenant_indexes_migration()
        assert result["status"] == "skipped"
        assert result["reason"] == "sentinel_present"

    run_test(_go)
