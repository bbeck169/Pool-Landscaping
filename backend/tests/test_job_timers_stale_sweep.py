"""Feb-2026 · Job Timers stale-sweep tests (Ask 3).

Covers the single-concern BE commit: ``services/job_timers_stale_
sweep.py::sweep_stale_job_timers`` closes open ``job_timers``
rows older than the threshold, writes correlation audit crumbs,
preserves multi-tenant isolation, and is idempotent on re-run.

Harness mirrors ``tests/test_job_timer_arrival_close.py`` — reuse
the shipped ``config.db`` Motor client (bound to the pytest shared
loop) via ``asyncio.get_event_loop().run_until_complete`` so Motor
futures stay on the same loop that owns them.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import db                                              # noqa: E402


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def test_tenant_ids():
    """Seed two fresh tenants and clean them up on teardown so the
    sweep's multi-tenant iteration has deterministic rows regardless
    of what's in the shared dev Mongo."""
    tid_a = f"sweep-test-tenant-a-{uuid.uuid4().hex[:8]}"
    tid_b = f"sweep-test-tenant-b-{uuid.uuid4().hex[:8]}"

    async def _seed():
        for tid in (tid_a, tid_b):
            await db.tenants.insert_one({
                "id": tid, "slug": tid, "name": tid, "active": True,
            })

    async def _cleanup():
        for tid in (tid_a, tid_b):
            await db.tenants.delete_one({"id": tid})
            await db.job_timers.delete_many({"tenant_id": tid})
            await db.job_timer_audit.delete_many({"tenant_id": tid})

    _run(_seed())
    yield tid_a, tid_b
    _run(_cleanup())


async def _insert_open_timer(*, tenant_id: str,
                               started_hours_ago: int,
                               tech_id: str = "tech-1",
                               job_id: str | None = None) -> str:
    """Seed an open (no ``ended_at``) ``job_timers`` row with a
    ``started_at`` ``started_hours_ago`` in the past."""
    jid = job_id or f"job-{uuid.uuid4().hex[:8]}"
    row_id = str(uuid.uuid4())
    started = (datetime.now(timezone.utc)
                 - timedelta(hours=started_hours_ago))
    await db.job_timers.insert_one({
        "id": row_id,
        "tenant_id": tenant_id,
        "job_id": jid,
        "customer_id": "cust-1",
        "entity_type": "tech",
        "tech_id": tech_id,
        "crew_id": None,
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "ended_at": None,
        "duration_seconds": None,
        "start_source": "gps_arrival",
        "end_source": None,
        "created_at": started.isoformat().replace("+00:00", "Z"),
        "updated_at": started.isoformat().replace("+00:00", "Z"),
    })
    return row_id


# ═══════════════════════════════════════════════════════════════════
# Feb-2026 · STALE SWEEP — 5-case suite covering the ops shape.
# ═══════════════════════════════════════════════════════════════════
def test_timer_younger_than_threshold_is_untouched(test_tenant_ids):
    """A 4h-old open timer stays open after a sweep run."""
    tid_a, _tid_b = test_tenant_ids
    row_id = _run(_insert_open_timer(
        tenant_id=tid_a, started_hours_ago=4,
    ))
    from services.job_timers_stale_sweep import sweep_stale_job_timers
    _run(sweep_stale_job_timers())
    row = _run(db.job_timers.find_one({"id": row_id}))
    assert row["ended_at"] is None, (
        "4h-old row should remain open after sweep"
    )
    assert row["end_source"] is None


def test_timer_older_than_threshold_is_closed_with_crumbs(
        test_tenant_ids):
    """A 20h-old open timer is closed with ``end_source =
    'stale_sweep'`` and the sweep writes a supplementary audit
    crumb carrying ``threshold_hours`` + ``sweep_run_id``."""
    tid_a, _tid_b = test_tenant_ids
    row_id = _run(_insert_open_timer(
        tenant_id=tid_a, started_hours_ago=20,
    ))
    from services.job_timers_stale_sweep import sweep_stale_job_timers
    summary = _run(sweep_stale_job_timers())
    assert summary["closed"] >= 1
    row = _run(db.job_timers.find_one({"id": row_id}))
    assert row["ended_at"] is not None, "20h-old row must be closed"
    assert row["end_source"] == "stale_sweep"
    assert row["duration_seconds"] is not None
    assert row["duration_seconds"] > 0
    # Base helper crumb written with event="auto_close".
    base_crumb = _run(db.job_timer_audit.find_one(
        {"timer_id": row_id, "event": "auto_close"},
    ))
    assert base_crumb is not None
    assert base_crumb["payload"]["reason"] == "stale_sweep"
    # Supplementary sweep crumb with run_id correlation metadata.
    sweep_crumb = _run(db.job_timer_audit.find_one(
        {"timer_id": row_id, "event": "stale_sweep"},
    ))
    assert sweep_crumb is not None
    assert sweep_crumb["payload"]["threshold_hours"] == 16
    assert sweep_crumb["payload"]["sweep_run_id"] == summary["run_id"]
    assert sweep_crumb["payload"]["reason"] == "stale_sweep"


def test_multi_tenant_isolation(test_tenant_ids):
    """A single sweep run closes stale rows on both test tenants,
    but each row's crumbs reference only its own tenant_id — no
    cross-tenant drift."""
    tid_a, tid_b = test_tenant_ids
    row_a = _run(_insert_open_timer(
        tenant_id=tid_a, started_hours_ago=22,
    ))
    row_b = _run(_insert_open_timer(
        tenant_id=tid_b, started_hours_ago=22,
    ))
    from services.job_timers_stale_sweep import sweep_stale_job_timers
    _run(sweep_stale_job_timers())
    doc_a = _run(db.job_timers.find_one({"id": row_a}))
    doc_b = _run(db.job_timers.find_one({"id": row_b}))
    assert doc_a["ended_at"] is not None
    assert doc_b["ended_at"] is not None
    crumb_a = _run(db.job_timer_audit.find_one(
        {"timer_id": row_a, "event": "stale_sweep"},
    ))
    crumb_b = _run(db.job_timer_audit.find_one(
        {"timer_id": row_b, "event": "stale_sweep"},
    ))
    assert crumb_a is not None and crumb_a["tenant_id"] == tid_a
    assert crumb_b is not None and crumb_b["tenant_id"] == tid_b
    assert crumb_a["payload"]["sweep_run_id"] \
        == crumb_b["payload"]["sweep_run_id"], (
        "both tenants' crumbs within one run share the same run_id"
    )


def test_idempotent_second_run_does_not_double_close(test_tenant_ids):
    """Re-running the sweep is a no-op — the row's ``ended_at`` is
    the first-run value and no additional ``stale_sweep`` crumb is
    emitted on the second run."""
    tid_a, _tid_b = test_tenant_ids
    row_id = _run(_insert_open_timer(
        tenant_id=tid_a, started_hours_ago=20,
    ))
    from services.job_timers_stale_sweep import sweep_stale_job_timers
    first = _run(sweep_stale_job_timers())
    first_ended_at = _run(db.job_timers.find_one(
        {"id": row_id}))["ended_at"]
    first_crumb_count = _run(db.job_timer_audit.count_documents(
        {"timer_id": row_id, "event": "stale_sweep"},
    ))
    assert first_crumb_count == 1
    second = _run(sweep_stale_job_timers())
    second_ended_at = _run(db.job_timers.find_one(
        {"id": row_id}))["ended_at"]
    second_crumb_count = _run(db.job_timer_audit.count_documents(
        {"timer_id": row_id, "event": "stale_sweep"},
    ))
    assert first_ended_at == second_ended_at, (
        "second sweep run must not re-touch ``ended_at``"
    )
    assert second_crumb_count == 1, (
        "second sweep run must not emit a second stale_sweep crumb"
    )
    assert first["closed"] >= 1
    assert first["run_id"] != second["run_id"]


def test_zero_rows_no_op(test_tenant_ids):
    """With no open stale rows on the test tenants, the sweep exits
    cleanly with a valid summary payload and leaves the only seeded
    (non-stale) row untouched."""
    tid_a, _tid_b = test_tenant_ids
    row_id = _run(_insert_open_timer(
        tenant_id=tid_a, started_hours_ago=2,
    ))
    from services.job_timers_stale_sweep import sweep_stale_job_timers
    summary = _run(sweep_stale_job_timers())
    row = _run(db.job_timers.find_one({"id": row_id}))
    assert row["ended_at"] is None, "2h-old row stays open"
    assert "run_id" in summary
    assert summary["threshold_hours"] == 16
    assert summary["tenants"] >= 2  # at least our two test tenants
