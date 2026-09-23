"""Phase P38 · Feb-2026 — backend tests for the ``scheduled_date``
backfill migration.

Six scenarios per the P38 brief:
  1. Dry-run performs zero writes but still reports the count.
  2. Execute populates ``scheduled_date`` from ``scheduled_start``
     in the tenant's local timezone.
  3. Execute preserves rows that already carry ``scheduled_date``.
  4. Idempotency — second execute reports 0 backfilled (marker path).
  5. Tenant filter — only the requested tenant is mutated; the marker
     is NOT stamped on tenant-scoped runs (so a follow-up full-scope
     run still fires).
  6. Missing-tz fallback — UTC + WARN + counted under
     ``backfilled_utc_fallback`` (row IS backfilled, not skipped).

Every test runs under ``tests._f7_loop_fixture.run_test`` so Motor
collections are loop-bound to the pytest coroutine's loop.  Test
data lives under scoped tenant IDs (``p38-test-*``) so we can wipe
cleanly between tests without touching real fixtures.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import pytest

from tests._f7_loop_fixture import run_test


# ═════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════
async def _wipe(db, tenant_ids: List[str]) -> None:
    """Clean the marker + jobs + tenants rows we seeded."""
    await db.migrations_applied.delete_one(
        {"name": "p38_backfill_scheduled_date"},
    )
    await db.jobs.delete_many({"tenant_id": {"$in": tenant_ids}})
    await db.tenants.delete_many({"id": {"$in": tenant_ids}})


async def _seed_tenant(
    db,
    tid: str,
    *,
    tz: str | None = "America/Phoenix",
) -> None:
    doc: Dict[str, Any] = {"id": tid, "name": f"p38-{tid}"}
    if tz is not None:
        doc["timezone"] = tz
    await db.tenants.insert_one(doc)


async def _seed_jobs_missing_date(
    db,
    tid: str,
    count: int,
    *,
    start_iso: str = "2026-02-15T18:30:00+00:00",
) -> List[str]:
    """Seed ``count`` jobs with ``scheduled_start`` set + no
    ``scheduled_date``.  Returns the list of job IDs."""
    ids: List[str] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for i in range(count):
        jid = f"p38-job-{tid}-{i}"
        ids.append(jid)
        await db.jobs.insert_one({
            "id": jid,
            "tenant_id": tid,
            "scheduled_start": start_iso,
            "created_at": now_iso,
        })
    return ids


async def _seed_job_with_date(
    db,
    tid: str,
    *,
    scheduled_date: str,
    start_iso: str = "2026-02-15T18:30:00+00:00",
) -> str:
    jid = f"p38-job-{tid}-pre"
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.jobs.insert_one({
        "id": jid,
        "tenant_id": tid,
        "scheduled_start": start_iso,
        "scheduled_date": scheduled_date,
        "created_at": now_iso,
    })
    return jid


# ═════════════════════════════════════════════════════════════════
# Tests
# ═════════════════════════════════════════════════════════════════
def test_backfill_dry_run_no_writes():
    """Item 1 — Dry-run reports the scan count but never writes."""
    from migrations.p38_backfill_scheduled_date import run as p38_run

    tid = "p38-test-dryrun"

    async def _go(db):
        await _wipe(db, [tid])
        await _seed_tenant(db, tid, tz="America/Phoenix")
        ids = await _seed_jobs_missing_date(db, tid, 5)

        summary = await p38_run(execute=False, tenant_id=tid)

        assert summary["dry_run"] is True
        assert summary["scanned"] == 5
        assert summary["backfilled"] == 5  # counted, but not written
        assert summary["executed_at"] is None

        # Zero DB mutations — every job still has NO scheduled_date.
        for jid in ids:
            row = await db.jobs.find_one({"id": jid})
            assert "scheduled_date" not in row or row["scheduled_date"] is None, (
                f"dry-run mutated {jid}: {row.get('scheduled_date')}"
            )

        # Marker MUST NOT be stamped by a dry-run.
        marker = await db.migrations_applied.find_one(
            {"name": "p38_backfill_scheduled_date"},
        )
        assert marker is None, "dry-run illegally stamped the marker"

        await _wipe(db, [tid])

    run_test(_go)


def test_backfill_execute_populates_from_scheduled_start():
    """Item 2 — Execute derives ``scheduled_date`` from
    ``scheduled_start`` in the tenant's local timezone."""
    from migrations.p38_backfill_scheduled_date import run as p38_run

    tid = "p38-test-execute"
    # 2026-02-15T18:30:00+00:00 in America/Phoenix (UTC-7, no DST)
    # is 2026-02-15T11:30:00, so calendar day = 2026-02-15.
    start_iso = "2026-02-15T18:30:00+00:00"

    async def _go(db):
        await _wipe(db, [tid])
        await _seed_tenant(db, tid, tz="America/Phoenix")
        ids = await _seed_jobs_missing_date(db, tid, 5, start_iso=start_iso)

        summary = await p38_run(execute=True, tenant_id=tid)

        assert summary["dry_run"] is False
        assert summary["scanned"] == 5
        assert summary["backfilled"] == 5
        assert summary["backfilled_utc_fallback"] == 0
        assert summary["executed_at"] is not None

        # Compute the expected local-tz date exactly the way the
        # migration does — sanity-check against a fresh derivation.
        expected = (
            datetime.fromisoformat(start_iso)
            .astimezone(ZoneInfo("America/Phoenix"))
            .date()
            .isoformat()
        )
        assert expected == "2026-02-15"

        for jid in ids:
            row = await db.jobs.find_one({"id": jid})
            assert row["scheduled_date"] == expected, (
                f"job {jid}: got {row.get('scheduled_date')!r} "
                f"expected {expected!r}"
            )

        await _wipe(db, [tid])

    run_test(_go)


def test_backfill_preserves_existing_scheduled_date():
    """Item 3 — Rows that already have ``scheduled_date`` are
    untouched by both the query filter and the update."""
    from migrations.p38_backfill_scheduled_date import run as p38_run

    tid = "p38-test-preserve"
    preserved_date = "2020-01-01"

    async def _go(db):
        await _wipe(db, [tid])
        await _seed_tenant(db, tid, tz="America/Phoenix")
        # Mix: 2 with pre-existing date, 3 missing.
        pre1 = await _seed_job_with_date(
            db, tid, scheduled_date=preserved_date,
        )
        # Second pre-existing row — separate insert so the ID differs.
        await db.jobs.insert_one({
            "id": f"{pre1}-2",
            "tenant_id": tid,
            "scheduled_start": "2026-02-15T18:30:00+00:00",
            "scheduled_date": preserved_date,
        })
        missing_ids = await _seed_jobs_missing_date(db, tid, 3)

        summary = await p38_run(execute=True, tenant_id=tid)

        # Only the 3 rows missing date should be counted / mutated.
        assert summary["scanned"] == 3
        assert summary["backfilled"] == 3

        # Preserved rows still carry the original date.
        preserved = await db.jobs.find_one({"id": pre1})
        assert preserved["scheduled_date"] == preserved_date
        preserved2 = await db.jobs.find_one({"id": f"{pre1}-2"})
        assert preserved2["scheduled_date"] == preserved_date

        # Missing rows got their derived date.
        for jid in missing_ids:
            row = await db.jobs.find_one({"id": jid})
            assert row.get("scheduled_date") == "2026-02-15", (
                f"missing job {jid} not backfilled"
            )

        await _wipe(db, [tid])

    run_test(_go)


def test_backfill_idempotent():
    """Item 4 — Second execute reports 0 backfilled (marker path).

    First execute stamps ``migrations_applied``; second execute
    short-circuits via the marker gate.
    """
    from migrations.p38_backfill_scheduled_date import run as p38_run

    tid = "p38-test-idempotent"

    async def _go(db):
        await _wipe(db, [tid])
        await _seed_tenant(db, tid, tz="America/Phoenix")
        await _seed_jobs_missing_date(db, tid, 3)

        # First execute — full scope (no --tenant so marker gets stamped).
        first = await p38_run(execute=True)
        assert first["skipped_by_marker"] is False
        # Scanned includes the seeded rows (may include prior test
        # residue if wipes aren't perfect, but backfilled_utc_fallback
        # + backfilled counts the real work).
        assert first["backfilled"] >= 3

        # Second execute — marker should short-circuit.
        second = await p38_run(execute=True)
        assert second["skipped_by_marker"] is True, (
            f"expected marker skip, got {second}"
        )
        assert second["scanned"] == 0
        assert second["backfilled"] == 0

        # ``--force`` bypasses the marker; scanned should be 0 now
        # (rows were backfilled on first pass) so backfilled stays 0.
        forced = await p38_run(execute=True, force=True)
        assert forced["skipped_by_marker"] is False
        assert forced["backfilled"] == 0

        await _wipe(db, [tid])

    run_test(_go)


def test_backfill_tenant_filter():
    """Item 5 — ``--tenant=A`` mutates only tenant A.  Marker is NOT
    stamped for tenant-scoped runs (a follow-up full-scope run must
    still fire)."""
    from migrations.p38_backfill_scheduled_date import run as p38_run

    tid_a = "p38-test-tenant-a"
    tid_b = "p38-test-tenant-b"

    async def _go(db):
        await _wipe(db, [tid_a, tid_b])
        await _seed_tenant(db, tid_a, tz="America/Phoenix")
        await _seed_tenant(db, tid_b, tz="America/Phoenix")
        ids_a = await _seed_jobs_missing_date(db, tid_a, 2)
        ids_b = await _seed_jobs_missing_date(db, tid_b, 2)

        summary = await p38_run(execute=True, tenant_id=tid_a)

        assert summary["tenant_filter"] == tid_a
        # Only tenant A's rows are scanned.
        assert summary["scanned"] == 2
        assert summary["backfilled"] == 2

        # Tenant A: backfilled.
        for jid in ids_a:
            row = await db.jobs.find_one({"id": jid})
            assert row.get("scheduled_date") == "2026-02-15"

        # Tenant B: untouched.
        for jid in ids_b:
            row = await db.jobs.find_one({"id": jid})
            assert row.get("scheduled_date") is None

        # Marker NOT stamped for tenant-scoped run.
        marker = await db.migrations_applied.find_one(
            {"name": "p38_backfill_scheduled_date"},
        )
        assert marker is None, (
            "tenant-scoped run illegally stamped the full-scope marker"
        )

        await _wipe(db, [tid_a, tid_b])

    run_test(_go)


def test_backfill_fallback_to_utc_when_no_tz(caplog):
    """Item 6 — Tenant with NO tz field → UTC fallback + WARN +
    counted under ``backfilled_utc_fallback``.  Row IS backfilled
    (not skipped)."""
    from migrations.p38_backfill_scheduled_date import run as p38_run

    tid = "p38-test-notz"
    # 2026-02-15T23:30:00Z — in Phoenix (UTC-7) that's 2026-02-15
    # local, but in UTC it's still 2026-02-15.  Pick a boundary
    # value that DIFFERS between UTC and Phoenix to prove the UTC
    # branch fired (2026-02-15T06:30:00Z is 2026-02-14T23:30 Phoenix
    # so Phoenix would say 2026-02-14 but UTC says 2026-02-15).
    start_iso = "2026-02-15T06:30:00+00:00"

    async def _go(db):
        await _wipe(db, [tid])
        # Seed tenant WITHOUT a timezone field at all.
        await db.tenants.insert_one({"id": tid, "name": "p38-notz"})
        ids = await _seed_jobs_missing_date(
            db, tid, 1, start_iso=start_iso,
        )

        with caplog.at_level(logging.WARNING):
            summary = await p38_run(execute=True, tenant_id=tid)

        assert summary["scanned"] == 1
        assert summary["backfilled"] == 1
        assert summary["backfilled_utc_fallback"] == 1

        # Row IS backfilled (not skipped) with UTC calendar day.
        row = await db.jobs.find_one({"id": ids[0]})
        assert row["scheduled_date"] == "2026-02-15", (
            f"UTC branch mis-derived date: {row.get('scheduled_date')}"
        )

        # WARN log present with the expected shape.
        warn_lines = [
            rec for rec in caplog.records
            if rec.levelno >= logging.WARNING
            and "[p38] utc fallback" in rec.getMessage()
        ]
        assert warn_lines, (
            "expected a `[p38] utc fallback` WARN log for the tz-less "
            f"tenant; saw: {[r.getMessage() for r in caplog.records]}"
        )

        await _wipe(db, [tid])

    run_test(_go)
