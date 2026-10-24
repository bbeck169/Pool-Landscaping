"""TD-timeclock-tech-clock-out-flow · Feb-2026.

Contract tests for the LandscapingClockWidget pivot from
``/api/timeclock/*`` (``timeclock_punches``) onto
``/api/workforce/*`` (``time_entries``).  See ticket brief for the
write/read mismatch rationale.

Scope
    * ``POST /api/workforce/clock-in`` with ``job_id`` omitted or
      ``null`` persists a ``time_entries`` row shaped exactly like
      a job-attached shift except ``assigned_job_id`` / ``job_id``
      stay ``None`` and ``job_title`` is ``"General work"``.
    * ``POST /api/workforce/clock-in`` while another open shift
      exists → 400 ``already have an open shift``.
    * ``POST /api/workforce/clock-out`` closes the open entry,
      computes a positive ``duration_minutes`` and flips
      ``status`` to ``submitted``.
    * ``GET /api/workforce/open-shift`` returns the open row
      wrapped in ``{"entry": {...}}`` when one exists; returns
      ``{"entry": null}`` when none.
    * Tenant isolation — tech on tenant A cannot see tenant B's
      open shift via ``/open-shift``.
    * ``/auth/me`` projects ``effective_department`` +
      ``show_time_clock`` for landscape techs (smoke so the FE
      widget visibility contract stays locked).
"""
import os
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = (
    _FE_ENV.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = _BE_ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE_ENV.get("DB_NAME") or os.environ.get("DB_NAME")


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def tech_h():
    # ``landscaper@aquaterra.com`` is a seeded landscape tech
    # (``department = "landscaping"``) — matches the widget's
    # visibility contract.
    return {"Authorization": f"Bearer {_login('landscaper@aquaterra.com')}"}


@pytest.fixture(scope="module")
def pool_tech_h():
    # ``mike@aquaterra.com`` is a pool tech on a different tenant
    # scope -> used only for the tenant-isolation probe where we
    # need a SECOND tenant.  For same-tenant, we rely on
    # ``landscaper@aquaterra.com``.
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture(scope="module")
def sunbelt_tech_h():
    # Sunbelt tenant tech — used for cross-tenant isolation probe.
    # Seed suite guarantees ``tech@sunbelt.com``.
    try:
        return {"Authorization": f"Bearer {_login('tech@sunbelt.com')}"}
    except Exception:
        pytest.skip("sunbelt tech seed not present")


@pytest.fixture(autouse=True)
def _cleanup_open(db):
    # Clean the landscaper's open shift before + after each test
    # so cases don't bleed into each other.  We ONLY touch open
    # (clock_out_at None) rows; completed historical rows stay.
    uid_rows = list(db.users.find(
        {"email": {"$in": ["landscaper@aquaterra.com", "tech@sunbelt.com"]}},
        {"id": 1, "_id": 0},
    ))
    uids = [r["id"] for r in uid_rows]
    if uids:
        db.time_entries.delete_many({"user_id": {"$in": uids},
                                     "clock_out_at": None})
    yield
    if uids:
        db.time_entries.delete_many({"user_id": {"$in": uids},
                                     "clock_out_at": None})


# ─── Clock-in with no job (bare "General work") ────────────────────
def test_clock_in_with_null_job_id_creates_general_work_entry(tech_h, db):
    r = requests.post(f"{API}/workforce/clock-in",
                      headers=tech_h, json={"job_id": None,
                                            "lat": 33.70, "lng": -112.22},
                      timeout=20)
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["job_id"] is None
    assert row["job_title"] == "General work"
    assert row["customer_id"] is None
    assert row["clock_in_at"]
    assert row["clock_out_at"] is None
    assert row["status"] == "open"
    assert row["out_of_geofence"] is False  # no job to geofence against

    # Mongo row matches
    doc = db.time_entries.find_one({"id": row["id"]}, {"_id": 0})
    assert doc is not None
    assert doc["job_title"] == "General work"
    assert doc["job_id"] is None


def test_clock_in_body_without_job_id_key_at_all_is_accepted(tech_h):
    # Mobile clients that omit the key entirely (not just null) must
    # also succeed — Pydantic default handles this but we lock the
    # contract so it can't regress.
    r = requests.post(f"{API}/workforce/clock-in",
                      headers=tech_h, json={"lat": 33.70, "lng": -112.22},
                      timeout=20)
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["job_id"] is None
    assert row["job_title"] == "General work"


def test_clock_in_without_lat_lng_is_accepted(tech_h):
    # Geo may be denied; the widget still submits a null-geo punch.
    r = requests.post(f"{API}/workforce/clock-in",
                      headers=tech_h, json={}, timeout=20)
    assert r.status_code == 200, r.text


# ─── Double-clock-in → 400 ─────────────────────────────────────────
def test_double_clock_in_returns_400(tech_h):
    r1 = requests.post(f"{API}/workforce/clock-in",
                       headers=tech_h, json={}, timeout=20)
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/workforce/clock-in",
                       headers=tech_h, json={}, timeout=20)
    assert r2.status_code == 400
    assert "open shift" in r2.text.lower()


# ─── open-shift probe ─────────────────────────────────────────────
def test_open_shift_returns_entry_when_clocked_in(tech_h):
    requests.post(f"{API}/workforce/clock-in",
                  headers=tech_h, json={}, timeout=20)
    r = requests.get(f"{API}/workforce/open-shift",
                     headers=tech_h, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entry"] is not None
    assert body["entry"]["clock_out_at"] is None
    assert body["entry"]["job_title"] == "General work"


def test_open_shift_returns_null_when_not_clocked_in(tech_h):
    r = requests.get(f"{API}/workforce/open-shift",
                     headers=tech_h, timeout=20)
    assert r.status_code == 200, r.text
    assert r.json() == {"entry": None}


# ─── Clock-out closes entry + computes duration ───────────────────
def test_clock_out_closes_entry_and_computes_duration(tech_h, db):
    ci = requests.post(f"{API}/workforce/clock-in",
                       headers=tech_h, json={}, timeout=20)
    assert ci.status_code == 200
    entry_id = ci.json()["id"]

    # Rewind clock_in_at by 90 minutes so duration > 0 even when
    # the test runs in <1s wall-clock.
    db.time_entries.update_one(
        {"id": entry_id},
        {"$set": {"clock_in_at": _iso_minutes_ago(90)}},
    )
    co = requests.post(f"{API}/workforce/clock-out",
                       headers=tech_h,
                       json={"entry_id": entry_id,
                             "lat": 33.70, "lng": -112.22},
                       timeout=20)
    assert co.status_code == 200, co.text
    row = co.json()
    assert row["clock_out_at"]
    assert row["duration_minutes"] >= 89.0, row
    assert row["status"] == "submitted"

    # And open-shift probe now returns null.
    probe = requests.get(f"{API}/workforce/open-shift",
                         headers=tech_h, timeout=20)
    assert probe.json() == {"entry": None}


def _iso_minutes_ago(n: int) -> str:
    from datetime import datetime, timezone, timedelta
    return (datetime.now(timezone.utc) - timedelta(minutes=n)).isoformat()


# ─── Tenant isolation ─────────────────────────────────────────────
def test_open_shift_is_tenant_scoped(tech_h, sunbelt_tech_h):
    # Aquaterra landscaper clocks in …
    requests.post(f"{API}/workforce/clock-in",
                  headers=tech_h, json={}, timeout=20)
    # … Sunbelt tech probes `/open-shift` and sees nothing.
    r = requests.get(f"{API}/workforce/open-shift",
                     headers=sunbelt_tech_h, timeout=20)
    assert r.status_code == 200
    assert r.json() == {"entry": None}


# ─── /auth/me projects department (visibility smoke) ──────────────
def test_auth_me_projects_effective_department_and_show_time_clock(tech_h):
    r = requests.get(f"{API}/auth/me", headers=tech_h, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    # These two fields power the widget's visibility helper.
    assert "effective_department" in body
    assert "show_time_clock" in body
    assert body["show_time_clock"] is True
    assert (body["effective_department"] or "").lower() in (
        "landscaping", "landscape_tech", "landscaper", "both",
    )
