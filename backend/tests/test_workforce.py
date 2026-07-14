"""Phase 16A · Workforce Ops tests — clock-in geofence, break math, overtime,
tenant isolation, CSV streaming.

Follows the existing suite convention: sync `requests` + `pymongo`, seeded
demo accounts (admin@aquaterra.com / mike@aquaterra.com), no async fixtures.
"""
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
import time

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
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


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


def _first_job(db, tenant_id: str) -> dict:
    job = db.jobs.find_one({"tenant_id": tenant_id})
    assert job, "expected at least one seeded job in aquaterra"
    # Give it fixed site coords for geofence math
    db.jobs.update_one({"id": job["id"]},
                       {"$set": {"site_lat": 33.7000, "site_lng": -112.2280}})
    return db.jobs.find_one({"id": job["id"]})


def _cleanup_open_entries(db, tenant_id):
    db.time_entries.delete_many({"tenant_id": tenant_id, "clock_out_at": None})


# ─── Test 1 · Inside geofence — full clock-in → break → clock-out flow ────
def test_clock_in_inside_geofence_and_flow(tech_h, admin_h, db, aquaterra_id):
    job = _first_job(db, aquaterra_id)
    _cleanup_open_entries(db, aquaterra_id)

    # Clock in at the exact site coords
    r = requests.post(f"{API}/workforce/clock-in", headers=tech_h,
                      json={"job_id": job["id"],
                            "lat": 33.70005, "lng": -112.22805, "accuracy": 5.0},
                      timeout=20)
    assert r.status_code == 200, r.text
    entry = r.json()
    assert entry["out_of_geofence"] is False
    assert entry["status"] == "open"
    entry_id = entry["id"]

    # Break start + end
    r = requests.post(f"{API}/workforce/break/start", headers=tech_h,
                      json={"entry_id": entry_id}, timeout=20)
    assert r.status_code == 200
    time.sleep(0.1)
    r = requests.post(f"{API}/workforce/break/end", headers=tech_h,
                      json={"entry_id": entry_id}, timeout=20)
    assert r.status_code == 200
    breaks = r.json()["breaks"]
    assert len(breaks) == 1 and breaks[0].get("end")

    # Clock out
    r = requests.post(f"{API}/workforce/clock-out", headers=tech_h,
                      json={"entry_id": entry_id,
                            "lat": 33.70005, "lng": -112.22805},
                      timeout=20)
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "submitted"
    assert out["clock_out_at"] is not None
    assert out["duration_minutes"] >= 0
    # Admin can approve
    r = requests.post(f"{API}/workforce/timesheets/{entry_id}/approve",
                      headers=admin_h, timeout=20)
    assert r.status_code == 200
    assert r.json()["status"] == "approved"


# ─── Test 2 · Outside geofence flags but does NOT block ───────────────────
def test_clock_in_outside_geofence_flag(tech_h, db, aquaterra_id):
    job = _first_job(db, aquaterra_id)
    _cleanup_open_entries(db, aquaterra_id)

    r = requests.post(f"{API}/workforce/clock-in", headers=tech_h,
                      json={"job_id": job["id"],
                            "lat": 33.7180, "lng": -112.2280},   # ~2km away
                      timeout=20)
    assert r.status_code == 200
    assert r.json()["out_of_geofence"] is True
    entry_id = r.json()["id"]
    # cleanup
    requests.post(f"{API}/workforce/clock-out", headers=tech_h,
                  json={"entry_id": entry_id, "lat": 33.7180, "lng": -112.2280},
                  timeout=20)


# ─── Test 3 · Tenant isolation on timesheets ──────────────────────────────
def test_tenant_isolation_on_timesheets(tech_h, sunbelt_admin_h):
    r1 = requests.get(f"{API}/workforce/timesheets", headers=tech_h, timeout=20)
    r2 = requests.get(f"{API}/workforce/timesheets", headers=sunbelt_admin_h, timeout=20)
    assert r1.status_code == 200 and r2.status_code == 200
    ids_a = {e["id"] for e in r1.json()}
    ids_b = {e["id"] for e in r2.json()}
    assert ids_a.isdisjoint(ids_b), "tenants must not share time_entries"


# ─── Test 4 · Overtime split 10h → 8 regular + 2 OT ───────────────────────
def test_overtime_daily_split(admin_h, db, aquaterra_id):
    user = db.users.find_one({"email": "mike@aquaterra.com"})
    uid = user["id"]
    base = datetime.now(timezone.utc) - timedelta(days=60)
    clock_in = base.replace(hour=8, minute=0, second=0, microsecond=0)
    clock_out = clock_in + timedelta(hours=10)
    doc = {
        "id": "TEST_OT_ENTRY_16A",
        "tenant_id": aquaterra_id,
        "user_id": uid,
        "user_name": user.get("name") or user.get("email"),
        "job_id": "TEST_JOB_16A",
        "job_title": "TEST_ overtime split",
        "clock_in_at": clock_in.isoformat(),
        "clock_out_at": clock_out.isoformat(),
        "breaks": [],
        "duration_minutes": 600,
        "mileage_miles": 0,
        "status": "submitted",
        "out_of_geofence": False,
        "created_at": clock_in.isoformat(),
    }
    db.time_entries.replace_one({"id": doc["id"]}, doc, upsert=True)
    try:
        frm = clock_in.date().isoformat()
        to = (clock_in.date() + timedelta(days=1)).isoformat()
        r = requests.get(
            f"{API}/workforce/timesheets?from={frm}&to={to}&user_id={uid}",
            headers=admin_h, timeout=20,
        )
        assert r.status_code == 200, r.text
        row = next((x for x in r.json() if x["id"] == doc["id"]), None)
        assert row is not None
        assert abs(row["hours"] - 10.0) < 0.01
        assert abs(row["regular_hours"] - 8.0) < 0.01
        assert abs(row["overtime_hours"] - 2.0) < 0.01
    finally:
        db.time_entries.delete_one({"id": doc["id"]})


# ─── Test 5 · CSV export streams text/csv ─────────────────────────────────
def test_csv_export_streams_text_csv(admin_h):
    frm = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    to = datetime.now(timezone.utc).date().isoformat()
    r = requests.get(
        f"{API}/workforce/export/timesheets.csv?from={frm}&to={to}",
        headers=admin_h, timeout=30,
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv"), r.headers
    assert "attachment" in r.headers.get("content-disposition", "").lower()
    body = r.text
    assert body.splitlines()[0].startswith("entry_id,user_id,")


# ─── Test 6 · Ping rate-limit ─────────────────────────────────────────────
def test_location_ping_rate_limit(tech_h):
    # Two pings within the 30s rate-limit floor → second must be dropped.
    p = {"lat": 33.70, "lng": -112.22}
    r1 = requests.post(f"{API}/workforce/location-ping", headers=tech_h, json=p, timeout=20)
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/workforce/location-ping", headers=tech_h, json=p, timeout=20)
    assert r2.status_code == 200
    # At least one of them (the second one) must have been rate-limited.
    assert (r2.json().get("accepted") is False) or (r1.json().get("accepted") is False)
