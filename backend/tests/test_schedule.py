"""Phase 16C · /api/schedule/today tests — role scoping, tenant isolation,
shift/break inclusion, route-leg cache."""
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = (_FE_ENV.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = _BE_ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE_ENV.get("DB_NAME") or os.environ.get("DB_NAME")


def _login(email, password="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture(scope="module")
def sunbelt_admin_h():
    return {"Authorization": f"Bearer {_login('admin@sunbelt.com')}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def aquaterra_id(db):
    return db.tenants.find_one({"slug": "aquaterra"})["id"]


@pytest.fixture(scope="module")
def sunbelt_id(db):
    return db.tenants.find_one({"slug": "sunbelt"})["id"]


def _cleanup_test_jobs(db, tenant_id, prefix="TEST_SCHED"):
    db.jobs.delete_many({"tenant_id": tenant_id, "title": {"$regex": f"^{prefix}"}})
    db.time_entries.delete_many({"tenant_id": tenant_id, "id": {"$regex": f"^{prefix}"}})


# ─── Test 1 · Returns a well-shaped payload for today ─────────────────────
def test_schedule_today_shape(tech_h):
    r = requests.get(f"{API}/schedule/today", headers=tech_h, timeout=20)
    assert r.status_code == 200
    d = r.json()
    assert "date" in d and "tz" in d
    assert isinstance(d["items"], list)
    assert isinstance(d["route_legs"], list)
    assert isinstance(d["summary"], dict)


# ─── Test 2 · Tenant isolation ────────────────────────────────────────────
def test_schedule_today_tenant_isolation(tech_h, sunbelt_admin_h, db, sunbelt_id):
    """Aquaterra tech must not see a job we insert into sunbelt."""
    # Insert a sunbelt job assigned to a fake user id
    _cleanup_test_jobs(db, sunbelt_id)
    now = datetime.now(timezone.utc)
    db.jobs.insert_one({
        "id": "TEST_SCHED_SUNBELT_JOB_1",
        "tenant_id": sunbelt_id,
        "title": "TEST_SCHED sunbelt job",
        "assigned_technician_id": "sunbelt-fake-tech",
        "assigned_to": "sunbelt-fake-tech",
        "technician_id": "sunbelt-fake-tech",
        "scheduled_date": now.isoformat(),
        "site_lat": 30.2672, "site_lng": -97.7431,
        "status": "pending",
    })
    r = requests.get(f"{API}/schedule/today", headers=tech_h, timeout=20)
    ids = [it.get("id") for it in r.json()["items"] if it.get("type") == "job"]
    assert "TEST_SCHED_SUNBELT_JOB_1" not in ids
    # cleanup
    _cleanup_test_jobs(db, sunbelt_id)


# ─── Test 3 · Only jobs assigned to *the caller* appear ───────────────────
def test_schedule_today_scoped_to_current_user(tech_h, db, aquaterra_id):
    """Insert 2 jobs for today — one for our tech, one for someone else — and
    confirm only ours shows up."""
    _cleanup_test_jobs(db, aquaterra_id)
    user = db.users.find_one({"email": "mike@aquaterra.com"})
    now = datetime.now(timezone.utc)
    mine_iso = now.replace(hour=10, minute=0, second=0, microsecond=0).isoformat()
    theirs_iso = now.replace(hour=11, minute=0, second=0, microsecond=0).isoformat()
    db.jobs.insert_many([
        {"id": "TEST_SCHED_MINE", "tenant_id": aquaterra_id,
         "title": "TEST_SCHED my job",
         "assigned_technician_id": user["id"],
         "technician_id": user["id"], "assigned_to": user["id"],
         "scheduled_date": mine_iso, "status": "pending"},
        {"id": "TEST_SCHED_THEIRS", "tenant_id": aquaterra_id,
         "title": "TEST_SCHED other-tech job",
         "assigned_technician_id": "someone-else",
         "technician_id": "someone-else", "assigned_to": "someone-else",
         "scheduled_date": theirs_iso, "status": "pending"},
    ])
    try:
        r = requests.get(f"{API}/schedule/today", headers=tech_h, timeout=20)
        assert r.status_code == 200
        job_ids = [it["id"] for it in r.json()["items"] if it.get("type") == "job"]
        assert "TEST_SCHED_MINE" in job_ids
        assert "TEST_SCHED_THEIRS" not in job_ids
    finally:
        _cleanup_test_jobs(db, aquaterra_id)


# ─── Test 4 · Shifts + breaks show up when time_entries exist for today ──
def test_schedule_today_includes_shift_and_break(tech_h, db, aquaterra_id):
    user = db.users.find_one({"email": "mike@aquaterra.com"})
    now = datetime.now(timezone.utc)
    entry = {
        "id": "TEST_SCHED_ENTRY_1",
        "tenant_id": aquaterra_id,
        "user_id": user["id"],
        "job_id": "TEST_SCHED_MINE_JOB",
        "job_title": "TEST_SCHED job for entry",
        "clock_in_at": now.replace(hour=9).isoformat(),
        "clock_out_at": now.replace(hour=10, minute=30).isoformat(),
        "breaks": [{"start": now.replace(hour=9, minute=30).isoformat(),
                    "end": now.replace(hour=9, minute=45).isoformat()}],
        "duration_minutes": 75,
        "mileage_miles": 4.2,
        "status": "submitted",
        "out_of_geofence": False,
    }
    db.time_entries.replace_one({"id": entry["id"]}, entry, upsert=True)
    try:
        r = requests.get(f"{API}/schedule/today", headers=tech_h, timeout=20)
        items = r.json()["items"]
        assert any(it.get("type") == "shift" and it.get("entry_id") == entry["id"] for it in items)
        assert any(it.get("type") == "break" and it.get("entry_id") == entry["id"] for it in items)
    finally:
        db.time_entries.delete_one({"id": entry["id"]})


# ─── Test 5 · Route-leg cache round-trip ──────────────────────────────────
def test_route_leg_cache_roundtrip(tech_h, db, aquaterra_id):
    leg = {
        "from_lat": 33.7005, "from_lng": -112.2280,
        "to_lat": 33.6503, "to_lng": -112.3320,
        "distance_meters": 15300.0, "duration_seconds": 940.0,
    }
    r = requests.post(f"{API}/schedule/route-leg", headers=tech_h,
                      json={"legs": [leg]}, timeout=20)
    assert r.status_code == 200 and r.json()["written"] == 1
    from routers.schedule import _cache_key  # type: ignore
    key = _cache_key(leg["from_lat"], leg["from_lng"], leg["to_lat"], leg["to_lng"])
    doc = db.distance_matrix_cache.find_one({"key": key})
    assert doc is not None
    assert doc["distance_meters"] == 15300.0
    assert doc["duration_seconds"] == 940.0
    # cleanup
    db.distance_matrix_cache.delete_one({"key": key})
