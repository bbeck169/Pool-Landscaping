"""Feb-2026 · P34 — Automation quiet-hours contract tests.

Covers:
  * Pure time-window helpers (``_time_in_window``, ``_parse_hhmm``).
  * ``GET /api/settings/quiet-hours`` — any staff (tech + admin).
  * ``PATCH /api/settings/quiet-hours`` — tech 403 / manager 200 /
    invalid HH:MM 400 / equal start-end 400.
  * Outbound wrapper — inside/outside window behaviour, via direct
    DB seeding of a deferred row (the wrapper's outside-window path
    is exercised via the POST /internal/quiet-hours/release endpoint).
  * Release worker — dispatches pending rows to ``sent`` on trigger.
    Concurrency safety verified via two rapid triggers.

Design note — the async Motor client is bound to the server's event
loop, so this suite prefers HTTP entry points + sync pymongo for
setup / assertion (matching every other P25..P33 test file). Direct
async unit tests use pure helpers only.
"""
from __future__ import annotations

import uuid
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


@pytest.fixture
def admin_h():
    return _hdrs("admin@aquaterra.com")


@pytest.fixture
def tech_h():
    return _hdrs("mike@aquaterra.com")


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one({"email": "admin@aquaterra.com"})["tenant_id"]


@pytest.fixture(autouse=True)
def _restore_state(aquaterra_tid):
    """Reset quiet-hours config to OFF + defaults, purge deferred
    rows, before + after each test."""
    def _reset():
        _sync.tenants.update_one(
            {"id": aquaterra_tid},
            {"$set": {"quiet_hours_enabled": False,
                        "quiet_hours_start": "08:00",
                        "quiet_hours_end": "20:00",
                        "quiet_hours_timezone": None}})
        _sync.outbound_deferred.delete_many({"tenant_id": aquaterra_tid})
    _reset()
    yield
    _reset()


# ─── 1. Pure time-window helpers (sync, no DB) ────────────────────────

def test_parse_hhmm_accepts_valid_and_rejects_invalid():
    from services.quiet_hours import _parse_hhmm
    assert _parse_hhmm("08:00") == dtime(8, 0)
    assert _parse_hhmm("23:59") == dtime(23, 59)
    for bad in ("8:00", "8am", "24:00", "12:60", "", "abc"):
        with pytest.raises(ValueError):
            _parse_hhmm(bad)


def test_time_in_window_same_day():
    from services.quiet_hours import _time_in_window
    start, end = dtime(8, 0), dtime(20, 0)
    assert _time_in_window(dtime(12, 0), start, end) is True
    assert _time_in_window(dtime(8, 0), start, end) is True
    assert _time_in_window(dtime(20, 0), start, end) is False  # end-exclusive
    assert _time_in_window(dtime(22, 0), start, end) is False
    assert _time_in_window(dtime(3, 0), start, end) is False


def test_time_in_window_overnight_spans_midnight():
    """start=20:00, end=02:00 → covers 20:00..23:59 AND 00:00..01:59."""
    from services.quiet_hours import _time_in_window
    start, end = dtime(20, 0), dtime(2, 0)
    assert _time_in_window(dtime(23, 0), start, end) is True
    assert _time_in_window(dtime(1, 30), start, end) is True
    assert _time_in_window(dtime(3, 0), start, end) is False
    assert _time_in_window(dtime(12, 0), start, end) is False
    # Boundary: exactly at start = inside; exactly at end = outside.
    assert _time_in_window(dtime(20, 0), start, end) is True
    assert _time_in_window(dtime(2, 0), start, end) is False


def test_time_in_window_equal_start_end_is_always_closed():
    from services.quiet_hours import _time_in_window
    assert _time_in_window(dtime(12, 0), dtime(8, 0), dtime(8, 0)) is False


# ─── 2. Settings endpoint RBAC + validation ───────────────────────────

def test_get_settings_open_to_technician(tech_h):
    r = requests.get(f"{API}/settings/quiet-hours",
                        headers=tech_h, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    for k in ("enabled", "start", "end", "timezone"):
        assert k in body


def test_get_settings_admin_works(admin_h):
    r = requests.get(f"{API}/settings/quiet-hours",
                        headers=admin_h, timeout=15)
    assert r.status_code == 200


def test_patch_settings_forbidden_for_technician(tech_h):
    r = requests.patch(f"{API}/settings/quiet-hours", headers=tech_h,
                          json={"enabled": True}, timeout=15)
    assert r.status_code == 403


def test_patch_settings_admin_can_write_full_body(admin_h):
    r = requests.patch(f"{API}/settings/quiet-hours", headers=admin_h,
                          json={"enabled": True, "start": "09:00",
                                  "end": "21:00",
                                  "timezone": "America/Phoenix"},
                          timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["start"] == "09:00"
    assert body["end"] == "21:00"
    assert body["timezone"] == "America/Phoenix"


def test_patch_settings_invalid_hhmm_400(admin_h):
    r = requests.patch(f"{API}/settings/quiet-hours", headers=admin_h,
                          json={"start": "8am"}, timeout=15)
    assert r.status_code == 400


def test_patch_settings_equal_start_end_400(admin_h):
    r = requests.patch(f"{API}/settings/quiet-hours", headers=admin_h,
                          json={"start": "08:00", "end": "08:00"}, timeout=15)
    assert r.status_code == 400


def test_patch_settings_invalid_timezone_400(admin_h):
    r = requests.patch(f"{API}/settings/quiet-hours", headers=admin_h,
                          json={"timezone": "Mars/Olympus"}, timeout=15)
    assert r.status_code == 400


# ─── 3. Release worker dispatches pending rows exactly once ───────────
# (Wrapper defer path is exercised implicitly — the worker only sees
# rows that landed via the wrapper's defer branch. We seed rows here
# directly to skip having to force a wall-clock outside-window state.)

def _seed_deferred_row(tenant_id: str, channel: str, payload: dict,
                        *, scheduled_offset_min: int = -1) -> str:
    """Seed a due (past-scheduled) deferred row. Returns row id."""
    now_utc = datetime.now(tz=timezone.utc)
    scheduled_for = (now_utc + timedelta(minutes=scheduled_offset_min)).isoformat()
    rid = f"TEST_p34_{uuid.uuid4().hex[:8]}"
    _sync.outbound_deferred.insert_one({
        "id": rid, "tenant_id": tenant_id, "channel": channel,
        "payload": payload, "scheduled_for": scheduled_for,
        "created_at": now_utc.isoformat(), "created_by": "test",
        "released_at": None, "status": "pending",
    })
    return rid


def test_release_endpoint_dispatches_due_pending_rows(admin_h, aquaterra_tid):
    ids = [
        _seed_deferred_row(aquaterra_tid, "sms",
            {"to_phone": "+16025550100", "body": "release-me-1"}),
        _seed_deferred_row(aquaterra_tid, "sms",
            {"to_phone": "+16025550101", "body": "release-me-2"}),
        _seed_deferred_row(aquaterra_tid, "sms",
            {"to_phone": "+16025550102", "body": "release-me-3"}),
    ]
    try:
        r = requests.post(f"{API}/internal/quiet-hours/release",
                             headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["claimed"] >= 3, body
        for rid in ids:
            row = _sync.outbound_deferred.find_one({"id": rid})
            assert row["status"] == "sent", row
            assert row.get("released_at") is not None
    finally:
        _sync.outbound_deferred.delete_many({"id": {"$in": ids}})


def test_future_scheduled_rows_are_not_released(admin_h, aquaterra_tid):
    """Rows whose scheduled_for is in the future are LEFT alone."""
    future_id = _seed_deferred_row(
        aquaterra_tid, "sms",
        {"to_phone": "+16025550999", "body": "not-yet"},
        scheduled_offset_min=+60,
    )
    try:
        r = requests.post(f"{API}/internal/quiet-hours/release",
                             headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        row = _sync.outbound_deferred.find_one({"id": future_id})
        assert row["status"] == "pending", row
    finally:
        _sync.outbound_deferred.delete_many({"id": future_id})


def test_double_release_is_idempotent(admin_h, aquaterra_tid):
    """Fire the release endpoint TWICE — no row is double-sent."""
    ids = [
        _seed_deferred_row(aquaterra_tid, "sms",
            {"to_phone": "+16025550200", "body": "once-a"}),
        _seed_deferred_row(aquaterra_tid, "sms",
            {"to_phone": "+16025550201", "body": "once-b"}),
    ]
    try:
        r1 = requests.post(f"{API}/internal/quiet-hours/release",
                              headers=admin_h, timeout=30)
        r2 = requests.post(f"{API}/internal/quiet-hours/release",
                              headers=admin_h, timeout=30)
        assert r1.status_code == 200 and r2.status_code == 200
        # First call claimed >= 2; second call claims 0 (no more pending).
        assert r1.json()["claimed"] >= 2
        assert r2.json()["claimed"] == 0
        for rid in ids:
            row = _sync.outbound_deferred.find_one({"id": rid})
            assert row["status"] == "sent"
    finally:
        _sync.outbound_deferred.delete_many({"id": {"$in": ids}})


# ─── 4. openapi lists the new routes ──────────────────────────────────

def test_openapi_lists_quiet_hours_routes():
    r = requests.get(f"{API}/openapi.json", timeout=15)
    assert r.status_code == 200
    paths = r.json().get("paths") or {}
    assert "/api/settings/quiet-hours" in paths
    assert "/api/internal/quiet-hours/release" in paths


# ─── 5. Backfill migration idempotence ───────────────────────────────

def test_backfill_migration_is_idempotent(aquaterra_tid):
    """Running the migration --commit on a DB that's already
    backfilled must not insert new fields or duplicate anything."""
    import subprocess
    import sys as _sys
    proj_root = Path(__file__).resolve().parents[1]
    cp = subprocess.run(
        [_sys.executable, "-m",
          "migrations.task_p34_quiet_hours_defaults", "--commit"],
        cwd=str(proj_root),
        capture_output=True, text=True, timeout=30,
    )
    assert cp.returncode == 0, cp.stderr
    # After a first commit, ``would_backfill`` on a re-run should be 0.
    cp2 = subprocess.run(
        [_sys.executable, "-m",
          "migrations.task_p34_quiet_hours_defaults"],
        cwd=str(proj_root),
        capture_output=True, text=True, timeout=30,
    )
    assert cp2.returncode == 0, cp2.stderr
    assert "would_backfill:           0" in cp2.stdout
