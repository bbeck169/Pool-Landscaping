"""Feb-2026 · /api/timeclock/mine-today UTC day-rollover regression.

Covers the bug reported by production admins — Phoenix (UTC-7)
techs who clocked in at say 2 pm local (21:00 UTC) saw the UI
flip to "clocked out" at 5 pm local when UTC midnight rolled.
Root cause: ``/mine-today`` used a today-only UTC window so the
pre-5 pm "in" punch fell out of range and ``open_in`` resolved
to ``None``.  Fix mirrors the ``/mine-status`` endpoint's
Feb-2026 ``Day-boundary rollover`` patch — scan ``yesterday →
today`` for the open-shift detection while keeping the
``punches`` + ``seconds`` fields filtered to today only (UI's
"today timeline" semantics stay unchanged byte-for-byte).

Suite covers:

1. **Rollover** — tech clocks in yesterday UTC with no OUT;
   ``/mine-today`` MUST return ``clocked_in=True`` and surface the
   open punch's ``job_id`` as ``open_job_id``.
2. **`/mine-today` ↔ `/mine-status` parity** — both aggregators
   agree on ``clocked_in`` for the same seed state.  Prevents
   future drift between the two endpoints.
3. **Yesterday fully closed** — a tech with an IN+OUT pair
   yesterday and NO new activity today MUST read ``clocked_in=
   False`` and the ``punches`` list MUST be empty (today-only).
4. **Fresh tech** — no punches at all; empty response + no
   errors.
5. **Open punch today after rollover** — tech clocked in
   yesterday, OUT yesterday, IN again today, open; the today-
   only ``punches`` list carries the single IN and
   ``clocked_in=True``.
6. **Multiple open rows across the 2-day window** — the walker
   must settle on the LATEST open "in" (newest timestamp wins).
   Defensive — the schema theoretically prevents this but a bad
   migration could seed duplicates.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


# ─── Path shim mirroring sibling backend tests ───────────────────
_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"

# Preview seeds a landscaping-department tech used across other
# tests.  Password is the shared ``password123`` from
# ``/app/memory/test_credentials.md``.
_LANDSCAPER_EMAIL = "landscaper@aquaterra.com"
_LANDSCAPER_PW = "password123"


def _server_up() -> bool:
    try:
        r = requests.get(f"{API}/health", timeout=10)
        return r.status_code < 500
    except requests.RequestException:
        return False


def _login(email: str, pw: str) -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def _mongo():
    assert _MONGO_URL and _DB_NAME, "MONGO_URL / DB_NAME required"
    client = MongoClient(_MONGO_URL)
    yield client[_DB_NAME]
    client.close()


@pytest.fixture
def _tech(_mongo) -> Dict[str, Any]:
    """Resolve the landscaping tech user doc + a bearer token."""
    user = _mongo.users.find_one(
        {"email": _LANDSCAPER_EMAIL},
        {"_id": 0, "id": 1, "tenant_id": 1},
    )
    assert user, (
        f"missing seeded user {_LANDSCAPER_EMAIL} — this test "
        "depends on the standard preview seed")
    token = _login(_LANDSCAPER_EMAIL, _LANDSCAPER_PW)
    return {"id": user["id"], "tenant_id": user["tenant_id"],
             "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture
def _clean_punches(_mongo, _tech):
    """Wipe the tech's punches before + after each test so the
    rollover seeds don't bleed between cases."""
    _mongo.timeclock_punches.delete_many({"user_id": _tech["id"]})
    yield
    _mongo.timeclock_punches.delete_many({"user_id": _tech["id"]})


def _iso_yesterday_at(hour: int, minute: int = 0) -> str:
    """Yesterday-UTC timestamp at the given hour (``datetime.utc
    - 1 day``).  Easier to reason about than mocking ``date.today
    ()`` server-side."""
    base = datetime.now(timezone.utc) - timedelta(days=1)
    return base.replace(hour=hour, minute=minute, second=0,
                         microsecond=0).isoformat()


def _iso_today_at(hour: int, minute: int = 0) -> str:
    base = datetime.now(timezone.utc)
    return base.replace(hour=hour, minute=minute, second=0,
                         microsecond=0).isoformat()


def _insert_punch(mongo, tech, *, punch_type: str, timestamp: str,
                    job_id: str | None = None,
                    tag: str = "") -> None:
    mongo.timeclock_punches.insert_one({
        "id": f"test-rollover-{tag}-{punch_type}",
        "tenant_id": tech["tenant_id"],
        "user_id": tech["id"],
        "punch_type": punch_type,
        "timestamp": timestamp,
        "lat": 33.4, "lng": -112.0,
        "accuracy_m": 10, "source": "web",
        "geo_denied": False,
        "job_id": job_id,
    })


_needs_server = pytest.mark.skipif(not _server_up(),
                                     reason="backend not reachable on :8001")


# ───────────────────────────────────────────────────────────────
# 1. Rollover — open shift from yesterday UTC must still surface
# ───────────────────────────────────────────────────────────────
@_needs_server
def test_open_shift_from_yesterday_utc_surfaces(_mongo, _tech, _clean_punches):
    _insert_punch(_mongo, _tech,
                  punch_type="in",
                  timestamp=_iso_yesterday_at(23, 55),
                  job_id="job-rollover-1",
                  tag="yday")

    r = requests.get(f"{API}/timeclock/mine-today",
                      headers=_tech["headers"], timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["clocked_in"] is True, (
        "The open 'in' punch from yesterday UTC must surface as "
        "clocked_in=True. Pre-fix behavior returned False and the "
        "UI rendered the tech as 'auto-clocked-out'. Re-read "
        "``timeclock_landscaping.py::today`` and verify the yester"
        "day→today window.")
    assert body["open_job_id"] == "job-rollover-1", (
        "open_job_id must carry forward from the rollover punch "
        "so the UI's 'currently clocking in on job X' banner "
        "stays stable across the UTC day boundary.")
    # ``punches`` + ``seconds`` keep today-only semantics so the
    # UI's "today timeline" affordance is unchanged.
    assert body["punches"] == [], (
        "Today's punch list must stay empty when the only open "
        "punch is from yesterday — the UI shows yesterday's "
        "activity in a different panel.")
    assert body["seconds"] == 0


# ───────────────────────────────────────────────────────────────
# 2. mine-today ↔ mine-status parity
# ───────────────────────────────────────────────────────────────
@_needs_server
def test_mine_today_matches_mine_status_on_rollover(_mongo, _tech, _clean_punches):
    _insert_punch(_mongo, _tech,
                  punch_type="in",
                  timestamp=_iso_yesterday_at(23, 50),
                  tag="parity")

    today = requests.get(f"{API}/timeclock/mine-today",
                          headers=_tech["headers"], timeout=15).json()
    status = requests.get(f"{API}/timeclock/mine-status",
                           headers=_tech["headers"], timeout=15).json()
    assert today["clocked_in"] == status["clocked_in"] is True, (
        f"endpoint parity broken: /mine-today clocked_in="
        f"{today['clocked_in']} vs /mine-status clocked_in="
        f"{status['clocked_in']}. The two aggregators MUST agree "
        f"on the open-shift state — they're the regression guard "
        f"for the Feb-2026 Day-boundary rollover fix.")


# ───────────────────────────────────────────────────────────────
# 3. Yesterday fully closed — no stale carry-forward today
# ───────────────────────────────────────────────────────────────
@_needs_server
def test_yesterday_closed_shift_does_not_leak_to_today(
    _mongo, _tech, _clean_punches,
):
    _insert_punch(_mongo, _tech, punch_type="in",
                  timestamp=_iso_yesterday_at(14), tag="closed-y")
    _insert_punch(_mongo, _tech, punch_type="out",
                  timestamp=_iso_yesterday_at(22), tag="closed-y")

    r = requests.get(f"{API}/timeclock/mine-today",
                      headers=_tech["headers"], timeout=15)
    body = r.json()
    assert body["clocked_in"] is False, (
        "An IN+OUT pair fully contained in yesterday UTC must NOT "
        "leak into today's clocked_in state.")
    assert body["punches"] == []
    assert body["seconds"] == 0
    assert body["open_job_id"] is None


# ───────────────────────────────────────────────────────────────
# 4. Fresh tech — zero punches
# ───────────────────────────────────────────────────────────────
@_needs_server
def test_no_punches_ever_returns_empty_envelope(_mongo, _tech, _clean_punches):
    r = requests.get(f"{API}/timeclock/mine-today",
                      headers=_tech["headers"], timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "punches": [],
        "seconds": 0,
        "clocked_in": False,
        "open_job_id": None,
    }


# ───────────────────────────────────────────────────────────────
# 5. Clocked in TODAY after a yesterday round-trip
# ───────────────────────────────────────────────────────────────
@_needs_server
def test_open_punch_today_after_yesterday_round_trip(
    _mongo, _tech, _clean_punches,
):
    _insert_punch(_mongo, _tech, punch_type="in",
                  timestamp=_iso_yesterday_at(14), tag="roundtrip-y")
    _insert_punch(_mongo, _tech, punch_type="out",
                  timestamp=_iso_yesterday_at(22), tag="roundtrip-y")
    _insert_punch(_mongo, _tech, punch_type="in",
                  timestamp=_iso_today_at(8), tag="roundtrip-t",
                  job_id="job-today-7")

    r = requests.get(f"{API}/timeclock/mine-today",
                      headers=_tech["headers"], timeout=15)
    body = r.json()
    assert body["clocked_in"] is True
    assert body["open_job_id"] == "job-today-7"
    # Today's punches list carries the single IN that the UI's
    # "today timeline" renders.
    today_types = [p["punch_type"] for p in body["punches"]]
    assert today_types == ["in"], (
        f"today-only punches must contain exactly the one IN "
        f"from today; got {today_types}")


# ───────────────────────────────────────────────────────────────
# 6. Multiple open IN rows (defensive — latest-timestamp wins)
# ───────────────────────────────────────────────────────────────
@_needs_server
def test_multiple_open_ins_resolves_to_latest(_mongo, _tech, _clean_punches):
    _insert_punch(_mongo, _tech, punch_type="in",
                  timestamp=_iso_yesterday_at(14),
                  job_id="old-open", tag="dup-y")
    _insert_punch(_mongo, _tech, punch_type="in",
                  timestamp=_iso_today_at(9),
                  job_id="newer-open", tag="dup-t")

    r = requests.get(f"{API}/timeclock/mine-today",
                      headers=_tech["headers"], timeout=15)
    body = r.json()
    assert body["clocked_in"] is True
    # Walker iterates timestamp-ascending so the LATEST open 'in'
    # overwrites the earlier one — tech sees the current job, not
    # the stale one.
    assert body["open_job_id"] == "newer-open", (
        f"when the window has multiple orphaned IN rows the "
        f"latest timestamp must win; got {body['open_job_id']}")
