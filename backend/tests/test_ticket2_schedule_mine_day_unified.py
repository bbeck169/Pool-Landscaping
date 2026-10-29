"""Ticket 2 · Feb-2026 — ``/api/schedule/mine-day`` unified clock-state
read.

Pre-ticket, ``routers/schedule.py::mine-day`` read ``clocked_in``
+ ``hours_logged_today`` from ``db.time_entries`` only, so a
landscape tech who clocked in via the Time Clock page (writes
``db.timeclock_punches`` only) saw a stale "Off the clock" chip
+ 0 hours on the schedule header — even though the Time Clock
page itself (post-TC-C1 unified read) correctly reflected the
open shift.

This suite locks the four-way invariant from the pre-audit:

  F1 — landscape tech with ONLY a ``timeclock_punches`` IN punch
       → ``clocked_in: True`` + hours from the punch pair.
  F2 — landscape tech with ONLY a ``time_entries`` open shift
       → ``clocked_in: True`` + hours from the closed shift (if
       the shift has already closed by the time of the probe).
  F3 — landscape tech with BOTH an open ``timeclock_punches`` IN
       AND a closed ``time_entries`` shift earlier the same day
       → ``clocked_in: True`` + hours = sum of BOTH closed pairs
       (no double-counting of the OPEN punch).
  F4 — POOL tech (writes only to ``time_entries``) regression
       lock → identical response shape + values vs pre-ticket.

Harness mirrors ``test_tc_timeclock_unified_read.py``: direct
Mongo seed + signed JWTs, live-curl against ``localhost:8001``.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import dotenv_values

from tests._shared_mongo import shared_db as _shared_db


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_db = _shared_db()
API = "http://localhost:8001/api"

JWT_SECRET = (
    _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
    or "dev-secret-change-me"
)
JWT_ALGO = _ENV.get("JWT_ALGO") or "HS256"


def _tok(user_id, email, role, tenant_id):
    payload = {
        "sub": user_id, "email": email, "role": role,
        "tenant_id": tenant_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def _seed_user(tenant_id, role, *, department=None):
    uid = f"{role}-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@mineday.test"
    _db.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": f"MD {role} {uid[-4:]}", "email": email,
        "department": department,
        "technician_id": uid,  # Keep ids aligned so job-matching
                                # doesn't matter for this suite.
    })
    return {
        "id": uid, "email": email, "role": role,
        "department": department, "tenant_id": tenant_id,
        "token": _tok(uid, email, role, tenant_id),
    }


def _seed_tc_punch(tenant_id, user_id, *, punch_type, ts_utc):
    pid = f"p-{uuid.uuid4().hex[:10]}"
    _db.timeclock_punches.insert_one({
        "id": pid, "tenant_id": tenant_id, "user_id": user_id,
        "punch_type": punch_type,
        "timestamp": ts_utc.isoformat(),
        "lat": 33.5, "lng": -112.1, "accuracy_m": 10.0,
        "source": "web", "geo_denied": False, "job_id": None,
    })
    return pid


def _seed_te_shift(tenant_id, user_id, *, clock_in, clock_out=None):
    eid = f"e-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": eid, "tenant_id": tenant_id, "user_id": user_id,
        "user_name": f"MD tech {user_id[-4:]}",
        "job_id": None, "job_title": "General work",
        "customer_id": None,
        "clock_in_at": clock_in.isoformat(),
        "clock_out_at": clock_out.isoformat() if clock_out else None,
        "clock_in_geo": {"lat": 33.5, "lng": -112.1, "accuracy": 10.0},
        "clock_out_geo": ({"lat": 33.5, "lng": -112.1}
                            if clock_out else None),
        "out_of_geofence": False, "photo_url": None, "breaks": [],
        "duration_minutes": (
            int((clock_out - clock_in).total_seconds() / 60)
            if clock_out else 0
        ),
        "mileage_miles": 0,
        "status": "closed" if clock_out else "open",
        "notes": "", "created_at": clock_in.isoformat(),
    }
    _db.time_entries.insert_one(doc)
    return eid


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _today_at(hour, minute=0):
    today_d = date.today()
    return datetime(today_d.year, today_d.month, today_d.day,
                     hour, minute, tzinfo=timezone.utc)


@pytest.fixture
def ctx():
    tid = f"md-{uuid.uuid4().hex[:8]}"
    _db.tenants.insert_one({
        "id": tid, "name": f"MD {tid}", "slug": f"md-{tid}",
        "active": True, "widget_allowed_domains": [],
    })
    yield {"tid": tid}
    _db.timeclock_punches.delete_many({"tenant_id": tid})
    _db.time_entries.delete_many({"tenant_id": tid})
    _db.users.delete_many({"tenant_id": tid})
    _db.jobs.delete_many({"tenant_id": tid})
    _db.tenants.delete_many({"id": tid})


def _hit_mine_day(token):
    # The endpoint is ``/schedule/today`` (``/schedule/day`` is an
    # alias). My pre-audit used ``mine-day`` as shorthand for the
    # tech-facing day-timeline; this suite probes the canonical
    # route.
    r = requests.get(f"{API}/schedule/today", headers=_auth(token),
                      timeout=30)
    assert r.status_code == 200, (
        f"/schedule/today returned {r.status_code}: {r.text[:400]}"
    )
    body = r.json()
    assert "summary" in body
    return body["summary"]


# ─────────────────────────────────────────────────────────────────
# F1 — landscape tech with ONLY a timeclock_punches IN
# ─────────────────────────────────────────────────────────────────
def test_f1_landscape_punches_only_open_shift(ctx):
    tech = _seed_user(ctx["tid"], "technician", department="landscaping")
    _seed_tc_punch(ctx["tid"], tech["id"],
                   punch_type="in", ts_utc=_today_at(8, 0))

    summary = _hit_mine_day(tech["token"])
    assert summary["clocked_in"] is True, (
        "unified read must reflect an open timeclock_punches IN as "
        f"clocked_in=True; got summary={summary!r}"
    )
    # Open shift — no closed pair yet, hours stays 0.0.
    assert summary["hours_logged_today"] == 0.0


# ─────────────────────────────────────────────────────────────────
# F1b — landscape tech with timeclock_punches IN + OUT (closed shift)
# → hours > 0, clocked_in=False
# ─────────────────────────────────────────────────────────────────
def test_f1b_landscape_punches_closed_shift(ctx):
    tech = _seed_user(ctx["tid"], "technician", department="landscaping")
    _seed_tc_punch(ctx["tid"], tech["id"],
                   punch_type="in", ts_utc=_today_at(8, 0))
    _seed_tc_punch(ctx["tid"], tech["id"],
                   punch_type="out", ts_utc=_today_at(10, 0))

    summary = _hit_mine_day(tech["token"])
    assert summary["clocked_in"] is False
    # 2h closed pair → 2.0 h.
    assert abs(summary["hours_logged_today"] - 2.0) < 0.01, (
        f"expected ~2.0 h from the timeclock_punches pair; "
        f"got {summary['hours_logged_today']}"
    )


# ─────────────────────────────────────────────────────────────────
# F2 — landscape tech with ONLY a time_entries open shift
# ─────────────────────────────────────────────────────────────────
def test_f2_landscape_time_entries_only_open_shift(ctx):
    tech = _seed_user(ctx["tid"], "technician", department="landscaping")
    _seed_te_shift(ctx["tid"], tech["id"], clock_in=_today_at(8, 0))

    summary = _hit_mine_day(tech["token"])
    assert summary["clocked_in"] is True
    # Open shift — no completed pair yet.
    assert summary["hours_logged_today"] == 0.0


# ─────────────────────────────────────────────────────────────────
# F3 — landscape tech with BOTH an open timeclock_punches IN AND a
# closed time_entries shift earlier the same day
# ─────────────────────────────────────────────────────────────────
def test_f3_landscape_both_collections_mixed(ctx):
    tech = _seed_user(ctx["tid"], "technician", department="landscaping")
    # Earlier closed shift via time_entries (07:00-08:00 = 1 h).
    _seed_te_shift(ctx["tid"], tech["id"],
                   clock_in=_today_at(7, 0),
                   clock_out=_today_at(8, 0))
    # Current open shift via timeclock_punches (09:00, no OUT yet).
    _seed_tc_punch(ctx["tid"], tech["id"],
                   punch_type="in", ts_utc=_today_at(9, 0))

    summary = _hit_mine_day(tech["token"])
    # Latest event is the open IN → clocked_in: True.
    assert summary["clocked_in"] is True
    # Only the earlier closed pair counts toward hours (the open
    # IN has no close yet; _sum_shifts ignores open shifts).
    # No double-counting.
    assert abs(summary["hours_logged_today"] - 1.0) < 0.01, (
        f"expected ~1.0 h (only the closed TE shift counts); "
        f"got {summary['hours_logged_today']}"
    )


# ─────────────────────────────────────────────────────────────────
# F4 — POOL tech regression lock
# ─────────────────────────────────────────────────────────────────
def test_f4_pool_tech_time_entries_only_regression_lock(ctx):
    tech = _seed_user(ctx["tid"], "technician", department="pool")
    # Closed shift via time_entries only (pool techs don't write
    # timeclock_punches). 2 h closed pair.
    _seed_te_shift(ctx["tid"], tech["id"],
                   clock_in=_today_at(8, 0),
                   clock_out=_today_at(10, 0))

    summary = _hit_mine_day(tech["token"])
    # Unified read on a pool tech must yield IDENTICAL values to
    # the legacy time_entries-only path. 2 h closed pair → 2.0.
    assert summary["clocked_in"] is False
    assert abs(summary["hours_logged_today"] - 2.0) < 0.01


def test_f4b_pool_tech_open_shift_regression_lock(ctx):
    tech = _seed_user(ctx["tid"], "technician", department="pool")
    _seed_te_shift(ctx["tid"], tech["id"], clock_in=_today_at(8, 0))

    summary = _hit_mine_day(tech["token"])
    # Open shift via time_entries → clocked_in: True; hours: 0.0.
    # Unchanged from the pre-ticket behavior.
    assert summary["clocked_in"] is True
    assert summary["hours_logged_today"] == 0.0
    # ``open_entry_id`` still populated from the open time_entries
    # row (preserved from legacy path).
    assert summary["open_entry_id"] is not None
