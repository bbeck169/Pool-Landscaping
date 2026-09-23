"""Phase P38.1 · Feb-2026 — reverse backfill tests.

Mirrors P38's structure but for the inverse migration.  Seven tests:

  1. test_reverse_backfill_dry_run_no_writes
  2. test_reverse_backfill_execute_populates_start_at_default_time
  3. test_reverse_backfill_preserves_existing_scheduled_start
  4. test_reverse_backfill_idempotent_via_marker
  5. test_reverse_backfill_tenant_filter_bypasses_marker
  6. test_reverse_backfill_utc_fallback_when_no_tz
  7. test_reverse_backfill_custom_time_via_env
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import pytest

from tests._f7_loop_fixture import run_test


# ═════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════
async def _wipe(db, tenant_ids: List[str]) -> None:
    await db.migrations_applied.delete_one(
        {"name": "p38_1_reverse_backfill_scheduled_start"},
    )
    await db.jobs.delete_many({"tenant_id": {"$in": tenant_ids}})
    await db.tenants.delete_many({"id": {"$in": tenant_ids}})


async def _seed_tenant(db, tid: str, *, tz: str | None = "America/Phoenix") -> None:
    doc: Dict[str, Any] = {"id": tid, "name": f"p38.1-{tid}"}
    if tz is not None:
        doc["timezone"] = tz
    await db.tenants.insert_one(doc)


async def _seed_jobs_missing_start(
    db, tid: str, count: int, *, sched_date: str = "2026-02-15",
) -> List[str]:
    ids: List[str] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for i in range(count):
        jid = f"p38.1-job-{tid}-{i}"
        ids.append(jid)
        await db.jobs.insert_one({
            "id": jid,
            "tenant_id": tid,
            "scheduled_date": sched_date,
            "created_at": now_iso,
        })
    return ids


# ═════════════════════════════════════════════════════════════════
# 1. Dry-run performs zero writes but reports the count
# ═════════════════════════════════════════════════════════════════
def test_reverse_backfill_dry_run_no_writes():
    from migrations.p38_1_reverse_backfill_scheduled_start import run as p38_1_run

    tid = "p38.1-test-dryrun"

    async def _go(db):
        await _wipe(db, [tid])
        await _seed_tenant(db, tid, tz="America/Phoenix")
        ids = await _seed_jobs_missing_start(db, tid, 5)

        summary = await p38_1_run(execute=False, tenant_id=tid)

        assert summary["dry_run"] is True
        assert summary["scanned"] == 5
        assert summary["backfilled"] == 5
        assert summary["executed_at"] is None

        for jid in ids:
            row = await db.jobs.find_one({"id": jid})
            assert "scheduled_start" not in row or row["scheduled_start"] is None, (
                f"dry-run mutated {jid}: {row.get('scheduled_start')}"
            )
        marker = await db.migrations_applied.find_one(
            {"name": "p38_1_reverse_backfill_scheduled_start"},
        )
        assert marker is None, "dry-run illegally stamped the marker"

        await _wipe(db, [tid])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 2. Execute populates scheduled_start at default time in tenant tz
# ═════════════════════════════════════════════════════════════════
def test_reverse_backfill_execute_populates_start_at_default_time(monkeypatch):
    from migrations.p38_1_reverse_backfill_scheduled_start import run as p38_1_run

    tid = "p38.1-test-execute"
    monkeypatch.delenv("P38_1_DEFAULT_START_TIME", raising=False)

    async def _go(db):
        await _wipe(db, [tid])
        await _seed_tenant(db, tid, tz="America/Phoenix")
        ids = await _seed_jobs_missing_start(db, tid, 5, sched_date="2026-02-15")

        summary = await p38_1_run(execute=True, tenant_id=tid)
        assert summary["dry_run"] is False
        assert summary["backfilled"] == 5
        assert summary["backfilled_utc_fallback"] == 0
        assert summary["default_time"] == "08:00"

        expected = datetime(
            2026, 2, 15, 8, 0, tzinfo=ZoneInfo("America/Phoenix"),
        ).isoformat()

        for jid in ids:
            row = await db.jobs.find_one({"id": jid})
            assert row["scheduled_start"] == expected, (
                f"job {jid}: got {row.get('scheduled_start')!r} "
                f"expected {expected!r}"
            )
        await _wipe(db, [tid])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 3. Preserve rows that already have scheduled_start
# ═════════════════════════════════════════════════════════════════
def test_reverse_backfill_preserves_existing_scheduled_start():
    from migrations.p38_1_reverse_backfill_scheduled_start import run as p38_1_run

    tid = "p38.1-test-preserve"
    preserved = "2020-01-01T12:34:56+00:00"

    async def _go(db):
        await _wipe(db, [tid])
        await _seed_tenant(db, tid, tz="America/Phoenix")
        # Row with BOTH — must be untouched.
        await db.jobs.insert_one({
            "id": "pre-1", "tenant_id": tid,
            "scheduled_date": "2026-02-15",
            "scheduled_start": preserved,
        })
        # Rows missing scheduled_start.
        missing = await _seed_jobs_missing_start(db, tid, 3)

        summary = await p38_1_run(execute=True, tenant_id=tid)
        assert summary["scanned"] == 3
        assert summary["backfilled"] == 3

        row = await db.jobs.find_one({"id": "pre-1"})
        assert row["scheduled_start"] == preserved

        expected = datetime(
            2026, 2, 15, 8, 0, tzinfo=ZoneInfo("America/Phoenix"),
        ).isoformat()
        for jid in missing:
            row = await db.jobs.find_one({"id": jid})
            assert row["scheduled_start"] == expected

        await _wipe(db, [tid])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 4. Idempotent via marker
# ═════════════════════════════════════════════════════════════════
def test_reverse_backfill_idempotent_via_marker():
    from migrations.p38_1_reverse_backfill_scheduled_start import run as p38_1_run

    tid = "p38.1-test-idempotent"

    async def _go(db):
        await _wipe(db, [tid])
        await _seed_tenant(db, tid, tz="America/Phoenix")
        await _seed_jobs_missing_start(db, tid, 3)

        first = await p38_1_run(execute=True)
        assert first["skipped_by_marker"] is False
        assert first["backfilled"] >= 3

        second = await p38_1_run(execute=True)
        assert second["skipped_by_marker"] is True
        assert second["scanned"] == 0
        assert second["backfilled"] == 0

        forced = await p38_1_run(execute=True, force=True)
        assert forced["skipped_by_marker"] is False
        assert forced["backfilled"] == 0  # rows already carry scheduled_start

        await _wipe(db, [tid])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 5. --tenant bypasses marker AND does NOT stamp
# ═════════════════════════════════════════════════════════════════
def test_reverse_backfill_tenant_filter_bypasses_marker():
    from migrations.p38_1_reverse_backfill_scheduled_start import run as p38_1_run

    tid_a = "p38.1-tenant-a"
    tid_b = "p38.1-tenant-b"

    async def _go(db):
        await _wipe(db, [tid_a, tid_b])
        await _seed_tenant(db, tid_a, tz="America/Phoenix")
        await _seed_tenant(db, tid_b, tz="America/Phoenix")
        ids_a = await _seed_jobs_missing_start(db, tid_a, 2)
        ids_b = await _seed_jobs_missing_start(db, tid_b, 2)

        summary = await p38_1_run(execute=True, tenant_id=tid_a)
        assert summary["tenant_filter"] == tid_a
        assert summary["backfilled"] == 2

        # Tenant B untouched.
        for jid in ids_b:
            row = await db.jobs.find_one({"id": jid})
            assert row.get("scheduled_start") is None

        # Marker NOT stamped for tenant-scoped run.
        marker = await db.migrations_applied.find_one(
            {"name": "p38_1_reverse_backfill_scheduled_start"},
        )
        assert marker is None

        await _wipe(db, [tid_a, tid_b])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 6. UTC fallback when tenant has no tz field
# ═════════════════════════════════════════════════════════════════
def test_reverse_backfill_utc_fallback_when_no_tz(caplog):
    from migrations.p38_1_reverse_backfill_scheduled_start import run as p38_1_run

    tid = "p38.1-test-notz"

    async def _go(db):
        await _wipe(db, [tid])
        # Seed tenant WITHOUT a timezone field.
        await db.tenants.insert_one({"id": tid, "name": "p38.1-notz"})
        ids = await _seed_jobs_missing_start(db, tid, 1, sched_date="2026-02-15")

        with caplog.at_level(logging.WARNING):
            summary = await p38_1_run(execute=True, tenant_id=tid)

        assert summary["backfilled"] == 1
        assert summary["backfilled_utc_fallback"] == 1

        row = await db.jobs.find_one({"id": ids[0]})
        expected = datetime(
            2026, 2, 15, 8, 0, tzinfo=timezone.utc,
        ).isoformat()
        assert row["scheduled_start"] == expected

        warn_lines = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING
            and "[p38.1] utc fallback" in r.getMessage()
        ]
        assert warn_lines, (
            "expected a `[p38.1] utc fallback` WARN log for the tz-less "
            f"tenant; saw: {[r.getMessage() for r in caplog.records]}"
        )

        await _wipe(db, [tid])

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 7. P38_1_DEFAULT_START_TIME=07:30 overrides the default
# ═════════════════════════════════════════════════════════════════
def test_reverse_backfill_custom_time_via_env(monkeypatch):
    from migrations.p38_1_reverse_backfill_scheduled_start import run as p38_1_run

    tid = "p38.1-test-custom-time"
    monkeypatch.setenv("P38_1_DEFAULT_START_TIME", "07:30")

    async def _go(db):
        await _wipe(db, [tid])
        await _seed_tenant(db, tid, tz="America/Phoenix")
        ids = await _seed_jobs_missing_start(db, tid, 1, sched_date="2026-02-15")

        summary = await p38_1_run(execute=True, tenant_id=tid)
        assert summary["default_time"] == "07:30"
        assert summary["backfilled"] == 1

        row = await db.jobs.find_one({"id": ids[0]})
        expected = datetime(
            2026, 2, 15, 7, 30, tzinfo=ZoneInfo("America/Phoenix"),
        ).isoformat()
        assert row["scheduled_start"] == expected

        await _wipe(db, [tid])

    run_test(_go)
