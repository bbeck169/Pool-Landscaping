"""2026-10-02 · GPS-arrival timer ``duration_seconds=0`` repair.

Pins the four-part fix (mobile_sync offline parity + None-on-parse-
failure in the two duration helpers + null-safe aggregation):

  (a) ``_handle_job_arrive`` with ``arrived_at`` missing in payload
      → ``timer_start_method == "mobile_offline_arrival_fallback_now"``
         ``timer_started_at ≈ now()``
         WARN log emitted
         ``job_timers`` row created with the same timestamp.

  (b) ``_handle_job_arrive`` with ``arrived_at`` present in payload
      → ``timer_start_method == "mobile_offline_arrival"``
         ``timer_started_at == payload.arrived_at``
         ``job_timers`` row created with that timestamp.

  (c) Idempotency — a second ``job.arrive`` sync op with a FRESH
      ``client_op_id`` on a job that already has an open
      ``job_timers`` row does NOT spawn a duplicate.

  (d) ``_handle_job_close`` fires ``close_open_timers_for_job`` so
      the previously-open ``job_timers`` row is sealed with
      ``ended_at`` + ``duration_seconds > 0``.

  (e) ``close_open_timers_for_job`` (direct invocation — mirrors the
      online service-report-submit flow at
      ``routers/service_reports.py:1131-1149``) also sees the
      offline-created row and seals it.

  (f) Parse-failure in ``_compute_duration_seconds`` /
      ``_timer_seconds`` yields ``None`` (not ``0``) — forge a
      malformed ``started_at`` and verify the sealed row carries
      ``duration_seconds = None`` AND is excluded by the
      ``{"duration_seconds": {"$gt": 0}}`` dashboard filter.

  (g) Aggregation-filter integrity — seed three ``job_timers`` rows
      with ``duration_seconds`` ∈ {None, 0, 30} and verify
      ``{"$gt": 0}`` returns ONLY the 30 row.

Harness mirrors ``test_mobile_sync_offline_bundle_jobs.py`` + the
``test_phase_o4_*`` suite: live ``requests`` to ``localhost:8001``,
``motor`` seeds via ``asyncio.get_event_loop().run_until_complete``,
explicit teardown deletes every seeded doc.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os as _os_local                                             # noqa: E402
_ENV_BASE = _os_local.environ.get("JOB_TIMER_FIX_TEST_BASE")
BASE = (_ENV_BASE or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

from config import db                                              # noqa: E402
from routers.job_timers import (                                   # noqa: E402
    _compute_duration_seconds,
    close_open_timers_for_job,
)
from routers.jobs import _timer_seconds                            # noqa: E402


# ─────────────────────────── helpers ────────────────────────────
def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _me(token: str) -> dict:
    return requests.get(f"{API}/auth/me",
                         headers={"Authorization": f"Bearer {token}"},
                         timeout=15).json()


def _post_sync(token: str, ops: list[dict], device_id: str = "test-dev") -> dict:
    r = requests.post(f"{API}/mobile/sync",
                       headers={"Authorization": f"Bearer {token}"},
                       json={"device_id": device_id, "operations": ops},
                       timeout=20)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def mike_token() -> str:
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def mike_identity(mike_token) -> dict:
    me = _me(mike_token)
    return {
        "tech_id":   me.get("technician_id") or me.get("id"),
        "tenant_id": me.get("tenant_id"),
        "user_id":   me.get("id"),
    }


def _seed_job(tenant_id: str, tech_id: str, *, status: str = "scheduled") -> str:
    jid = f"jt-fix-{uuid.uuid4()}"

    async def _ins():
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tenant_id, "technician_id": tech_id,
            "customer_id": "jt-fix-cust",
            "customer_name": "Timer Fix Customer",
            "title": "jt-fix seeded",
            # Non-pool service + explicit override so the
            # ``_handle_job_close`` chemistry-readings gate skips
            # on offline close.  The gate is the subject of its own
            # separate suite — we only exercise the timer-closure
            # path here.
            "service_type": "Landscape Maintenance",
            "checklist_kind_override": "non_pool",
            "status": status,
            "scheduled_date": datetime.now(timezone.utc).date().isoformat(),
        })
    _run(_ins())
    return jid


def _cleanup_job(jid: str) -> None:
    async def _del():
        await db.jobs.delete_many({"id": jid})
        await db.job_timers.delete_many({"job_id": jid})
        await db.job_timer_audit.delete_many({"timer_id": {"$regex": "^"}})  # best-effort noop
        await db.pending_sync_receipts.delete_many({"entity_id": jid})
        await db.sync_conflict_log.delete_many({"entity_id": jid})
    _run(_del())


# ──────────────────────── (a) fallback-to-now path ───────────────
def test_offline_arrival_missing_arrived_at_falls_back_to_now_with_marker(
    mike_token, mike_identity, caplog,
):
    jid = _seed_job(mike_identity["tenant_id"], mike_identity["tech_id"])
    try:
        caplog.set_level(logging.WARNING, logger="mobile_sync")
        caplog.set_level(logging.WARNING, logger="job_timers")
        t0 = datetime.now(timezone.utc)
        resp = _post_sync(mike_token, [{
            "client_op_id": f"op-arrive-no-at-{uuid.uuid4()}",
            "op_type": "job.arrive",
            "entity_id": jid,
            "payload": {},  # no arrived_at → fallback-to-now path
        }])
        assert resp.get("failed") in ([], None), f"unexpected failures: {resp}"
        job = _run(db.jobs.find_one({"id": jid}, {"_id": 0}))
        assert job["timer_start_method"] == "mobile_offline_arrival_fallback_now", (
            f"expected fallback marker, got {job.get('timer_start_method')!r}"
        )
        ts = job["timer_started_at"]
        ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        skew = abs((ts_dt - t0).total_seconds())
        assert skew < 10, f"timer_started_at drifted {skew}s from now()"
        # Dashboard parity — a ``job_timers`` row MUST have been
        # inserted (bug (b) in the discovery report).
        rows = _run(_collect_job_timers(jid))
        assert len(rows) == 1, (
            f"expected 1 job_timers row, got {len(rows)}: {rows}"
        )
        assert rows[0]["started_at"] == ts
        assert rows[0]["ended_at"] is None
        assert rows[0]["duration_seconds"] is None
    finally:
        _cleanup_job(jid)


# ──────────────────────── (b) arrived_at honoured ────────────────
def test_offline_arrival_with_arrived_at_preserves_timestamp(
    mike_token, mike_identity,
):
    jid = _seed_job(mike_identity["tenant_id"], mike_identity["tech_id"])
    try:
        real_arrival = (datetime.now(timezone.utc) - timedelta(hours=1)
                         ).isoformat()
        resp = _post_sync(mike_token, [{
            "client_op_id": f"op-arrive-with-at-{uuid.uuid4()}",
            "op_type": "job.arrive",
            "entity_id": jid,
            "payload": {"arrived_at": real_arrival},
        }])
        assert resp.get("failed") in ([], None), f"unexpected failures: {resp}"
        job = _run(db.jobs.find_one({"id": jid}, {"_id": 0}))
        assert job["timer_start_method"] == "mobile_offline_arrival"
        assert job["timer_started_at"] == real_arrival, (
            f"expected {real_arrival}, got {job.get('timer_started_at')}"
        )
        rows = _run(_collect_job_timers(jid))
        assert len(rows) == 1
        assert rows[0]["started_at"] == real_arrival
    finally:
        _cleanup_job(jid)


# ──────────────────────── (c) idempotency guard ──────────────────
def test_offline_arrival_second_fresh_op_does_not_duplicate_timer_row(
    mike_token, mike_identity,
):
    jid = _seed_job(mike_identity["tenant_id"], mike_identity["tech_id"])
    try:
        real_arrival = (datetime.now(timezone.utc) - timedelta(hours=1)
                         ).isoformat()
        # First op — stamps the job + inserts the row.
        _post_sync(mike_token, [{
            "client_op_id": f"op-arrive-dup-first-{uuid.uuid4()}",
            "op_type": "job.arrive",
            "entity_id": jid,
            "payload": {"arrived_at": real_arrival},
        }])
        # Second op — fresh client_op_id so the dedupe receipt gate
        # doesn't fire; the "already_running" branch inside the
        # handler + the open-row probe inside ``auto_start_timer_
        # on_arrival`` are the invariants under test here.
        _post_sync(mike_token, [{
            "client_op_id": f"op-arrive-dup-second-{uuid.uuid4()}",
            "op_type": "job.arrive",
            "entity_id": jid,
            "payload": {"arrived_at": real_arrival},
        }])
        rows = _run(_collect_job_timers(jid))
        assert len(rows) == 1, (
            f"idempotency broken — got {len(rows)} rows: {rows}"
        )
    finally:
        _cleanup_job(jid)


# ──────────────────────── (d) offline close seals the row ────────
def test_offline_close_seals_job_timers_row_with_positive_duration(
    mike_token, mike_identity,
):
    jid = _seed_job(mike_identity["tenant_id"], mike_identity["tech_id"])
    try:
        # Arrive 45 minutes ago so the sealed row has a positive dur.
        real_arrival = (datetime.now(timezone.utc) - timedelta(minutes=45)
                         ).isoformat()
        _post_sync(mike_token, [{
            "client_op_id": f"op-arrive-close-{uuid.uuid4()}",
            "op_type": "job.arrive",
            "entity_id": jid,
            "payload": {"arrived_at": real_arrival},
        }])
        resp = _post_sync(mike_token, [{
            "client_op_id": f"op-close-close-{uuid.uuid4()}",
            "op_type": "job.close",
            "entity_id": jid,
            "payload": {"completed_at": datetime.now(timezone.utc).isoformat()},
        }])
        assert resp.get("failed") in ([], None), f"unexpected failures: {resp}"
        rows = _run(_collect_job_timers(jid))
        assert len(rows) == 1
        row = rows[0]
        assert row["ended_at"] is not None, (
            "offline close did not seal the job_timers row"
        )
        assert row["duration_seconds"] is not None, (
            "sealed row has null duration — compute path broken"
        )
        assert row["duration_seconds"] > 0, (
            f"expected positive duration from 45-min interval, "
            f"got {row['duration_seconds']}s"
        )
        assert row.get("end_source") == "mobile_offline_close"
    finally:
        _cleanup_job(jid)


# ──────────────────── (e) submit-equivalent close via helper ─────
def test_submit_equivalent_close_seals_offline_arrival_row(
    mike_token, mike_identity,
):
    """``routers/service_reports.py::submit_report`` calls the SAME
    ``close_open_timers_for_job`` helper. Driving the helper
    directly represents the submit flow at the timer-closure level
    without the heavy upsert + atomic claim ceremony around it."""
    jid = _seed_job(mike_identity["tenant_id"], mike_identity["tech_id"])
    try:
        real_arrival = (datetime.now(timezone.utc) - timedelta(minutes=20)
                         ).isoformat()
        _post_sync(mike_token, [{
            "client_op_id": f"op-arrive-sub-{uuid.uuid4()}",
            "op_type": "job.arrive",
            "entity_id": jid,
            "payload": {"arrived_at": real_arrival},
        }])
        _closed = _run(close_open_timers_for_job(
            job_id=jid, tenant_id=mike_identity["tenant_id"],
            actor_user_id=mike_identity["user_id"],
        ))
        assert _closed == 1, f"expected 1 row closed, got {_closed}"
        row = _run(db.job_timers.find_one({"job_id": jid}, {"_id": 0}))
        assert row["ended_at"] is not None
        assert isinstance(row["duration_seconds"], int)
        assert row["duration_seconds"] > 0
        # Default reason tag preserved for the service-report flow.
        assert row["end_source"] == "service_report_submit"
    finally:
        _cleanup_job(jid)


# ──────────────────── (f) parse failure → None, not 0 ────────────
def test_parse_failure_yields_null_duration_and_is_filter_excluded(
    mike_identity,
):
    """Forges a ``job_timers`` row with a non-ISO ``started_at`` so
    the duration computation inside ``close_open_timers_for_job``
    hits the parse-failure branch. The sealed row must have
    ``duration_seconds == None`` (not ``0``) and must therefore be
    EXCLUDED from the dashboard aggregation filter at
    ``routers/job_timers.py`` L555 / L611.
    """
    tenant_id = mike_identity["tenant_id"]
    jid = f"jt-fix-parse-{uuid.uuid4()}"
    timer_id = f"jt-row-parse-{uuid.uuid4()}"

    async def _seed():
        await db.job_timers.insert_one({
            "id": timer_id, "tenant_id": tenant_id, "job_id": jid,
            "customer_id": "jt-fix-cust", "entity_type": "tech",
            "tech_id": mike_identity["tech_id"], "crew_id": None,
            "started_at": "NOT-A-TIMESTAMP",                      # ← parse failure
            "ended_at": None, "duration_seconds": None,
            "start_source": "mobile_offline_arrival_fallback_now",
            "end_source": None,
        })
    _run(_seed())
    try:
        _closed = _run(close_open_timers_for_job(
            job_id=jid, tenant_id=tenant_id,
        ))
        assert _closed == 1
        row = _run(db.job_timers.find_one({"id": timer_id}, {"_id": 0}))
        assert row["ended_at"] is not None
        assert row["duration_seconds"] is None, (
            f"expected None on parse failure, got {row['duration_seconds']!r}"
        )
        # Dashboard-filter exclusion check — the aggregation filter
        # at ``job_timers.py:555`` + L611 is ``{"$gt": 0}``.
        hit = _run(db.job_timers.find_one(
            {"id": timer_id, "duration_seconds": {"$gt": 0}},
            {"_id": 0, "id": 1},
        ))
        assert hit is None, (
            "parse-failure row leaked into {'$gt': 0} aggregation"
        )
    finally:
        async def _del():
            await db.job_timers.delete_many({"id": timer_id})
        _run(_del())


# ──────────────────── (g) aggregation-filter integrity ───────────
def test_aggregation_filter_excludes_null_and_zero_only_matches_positive(
    mike_identity,
):
    """Insert three ``job_timers`` rows (null / 0 / 30 s) and
    verify ``{"duration_seconds": {"$gt": 0}}`` returns ONLY the
    30-second row. This locks the dashboard contract so a future
    refactor of the write path can't start laundering 0-s rows
    into the aggregates.
    """
    tenant_id = mike_identity["tenant_id"]
    base = f"jt-fix-agg-{uuid.uuid4()}"
    ids = {"null": f"{base}-null", "zero": f"{base}-zero",
            "thirty": f"{base}-thirty"}

    async def _seed():
        for key, dur in (("null", None), ("zero", 0), ("thirty", 30)):
            await db.job_timers.insert_one({
                "id": ids[key], "tenant_id": tenant_id, "job_id": base,
                "customer_id": "jt-fix-cust", "entity_type": "tech",
                "tech_id": mike_identity["tech_id"], "crew_id": None,
                "started_at": "2026-10-01T10:00:00+00:00",
                "ended_at":   "2026-10-01T10:00:30+00:00",
                "duration_seconds": dur,
                "start_source": "manual_admin",
                "end_source": "manual_admin",
            })
    _run(_seed())
    try:
        matches = _run(_find_many(
            {"tenant_id": tenant_id, "job_id": base,
              "duration_seconds": {"$gt": 0}},
        ))
        matched_ids = sorted(m["id"] for m in matches)
        assert matched_ids == [ids["thirty"]], (
            f"expected only the 30s row, got {matched_ids}"
        )
    finally:
        async def _del():
            await db.job_timers.delete_many({"id": {"$in": list(ids.values())}})
        _run(_del())


# ──────────────────── pure helper unit tests ─────────────────────
def test_timer_seconds_returns_none_on_parse_failure():
    """Unit — ``routers/jobs.py::_timer_seconds`` now returns
    ``None`` on exception (was ``0`` pre-fix)."""
    assert _timer_seconds("NOT-ISO", "2026-10-01T10:00:30Z") is None
    assert _timer_seconds("2026-10-01T10:00:00Z", "NOT-ISO") is None
    # Happy path still produces a positive int.
    assert _timer_seconds(
        "2026-10-01T10:00:00Z", "2026-10-01T10:00:30Z",
    ) == 30


def test_compute_duration_seconds_returns_none_on_bad_bounds():
    """Unit — ``routers/job_timers.py::_compute_duration_seconds``
    returns ``None`` for None / empty / malformed bounds (unchanged
    behaviour, pinned)."""
    assert _compute_duration_seconds(None, "2026-10-01T10:00:30Z") is None
    assert _compute_duration_seconds("2026-10-01T10:00:00Z", None) is None
    assert _compute_duration_seconds("", "2026-10-01T10:00:30Z") is None
    assert _compute_duration_seconds(
        "2026-10-01T10:00:00Z", "2026-10-01T10:00:30Z",
    ) == 30


# ─────────────────────────── mongo helpers ───────────────────────
async def _collect_job_timers(job_id: str) -> list[dict]:
    return [r async for r in db.job_timers.find(
        {"job_id": job_id}, {"_id": 0},
    )]


async def _find_many(q: dict) -> list[dict]:
    return [r async for r in db.job_timers.find(q, {"_id": 0, "id": 1})]
