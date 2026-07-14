"""GPS-based auto clock-in + auto clock-out on service-report submit."""
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL")
        or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
        or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


def _login(email, password="password123"):
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def tech_user():
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def tech_h(tech_user):
    return {"Authorization": f"Bearer {tech_user['access_token']}"}


@pytest.fixture(scope="module")
def sunbelt_tech_h():
    # Sunbelt seed uses `tech@sunbelt.com` — see test_credentials.md
    try:
        return {"Authorization": f"Bearer {_login('tech@sunbelt.com')['access_token']}"}
    except Exception:
        pytest.skip("tech@sunbelt.com not seeded")


@pytest.fixture(autouse=True)
def _reset_ratelimit(tech_h):
    """Test-only hook: clear the in-memory autoclock rate limit for mike.
    Requires backend running with ALLOW_TEST_HOOKS=1."""
    try:
        requests.post(f"{API}/workforce/_test/reset-autoclock",
                      headers=tech_h, timeout=5)
    except Exception:
        pass
    yield


def _cleanup_entries(dbc, user_email):
    u = dbc.users.find_one({"email": user_email})
    if u:
        dbc.time_entries.delete_many({"user_id": u["id"]})


def _seed_job(dbc, tenant_slug: str, tech_email: str,
              site_lat: float, site_lng: float,
              minutes_from_now: int = 0):
    tenant = dbc.tenants.find_one({"slug": tenant_slug})
    user = dbc.users.find_one({"email": tech_email})
    assert tenant and user
    jid = str(uuid.uuid4())
    scheduled = (datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)).isoformat()
    dbc.jobs.insert_one({
        "id": jid,
        "tenant_id": tenant["id"],
        "customer_name": "TEST_ auto-clockin",
        "title": "Weekly Pool Service (auto-clockin test)",
        "service_type": "Weekly Pool Service",
        "job_type": "Weekly Pool Service",
        "status": "scheduled",
        "technician_id": user["id"],
        "site_lat": site_lat,
        "site_lng": site_lng,
        "scheduled_start": scheduled,
        "photos": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return jid


def _cleanup_job(dbc, jid):
    dbc.jobs.delete_one({"id": jid})
    dbc.service_reports.delete_many({"job_id": jid})


# ═══════════════════════════════════════════════════════════════════════════
# Happy path — inside geofence + within window
# ═══════════════════════════════════════════════════════════════════════════
def test_auto_clockin_inside_geofence(tech_h, dbc):
    _cleanup_entries(dbc, "mike@aquaterra.com")
    # Wait past prior rate-limit window (previous test may have called endpoint).
    # ratelimit cleared by _reset_ratelimit fixture
    jid = _seed_job(dbc, "aquaterra", "mike@aquaterra.com",
                    site_lat=33.6, site_lng=-112.2, minutes_from_now=15)
    try:
        r = requests.post(f"{API}/workforce/auto-clock-in", headers=tech_h,
                          json={"lat": 33.6000, "lng": -112.2000, "accuracy": 10}, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["clocked_in"] is True
        assert data["job_id"] == jid
        assert data["distance_m"] < 10
        entry_id = data["entry_id"]
        # Entry in DB has origin=gps_auto
        e = dbc.time_entries.find_one({"id": entry_id})
        assert e["origin"] == "gps_auto"
        assert e["clock_out_at"] is None
    finally:
        _cleanup_entries(dbc, "mike@aquaterra.com")
        _cleanup_job(dbc, jid)


def test_auto_clockin_outside_geofence(tech_h, dbc):
    _cleanup_entries(dbc, "mike@aquaterra.com")
    # ratelimit cleared by _reset_ratelimit fixture
    jid = _seed_job(dbc, "aquaterra", "mike@aquaterra.com",
                    site_lat=33.6, site_lng=-112.2, minutes_from_now=15)
    try:
        # 1 km north
        r = requests.post(f"{API}/workforce/auto-clock-in", headers=tech_h,
                          json={"lat": 33.6100, "lng": -112.2000, "accuracy": 10}, timeout=15)
        assert r.status_code == 200
        assert r.json() == {"clocked_in": False, "reason": "not_at_any_scheduled_site"}
    finally:
        _cleanup_job(dbc, jid)


def test_auto_clockin_low_accuracy(tech_h, dbc):
    _cleanup_entries(dbc, "mike@aquaterra.com")
    # ratelimit cleared by _reset_ratelimit fixture
    jid = _seed_job(dbc, "aquaterra", "mike@aquaterra.com",
                    site_lat=33.6, site_lng=-112.2, minutes_from_now=15)
    try:
        r = requests.post(f"{API}/workforce/auto-clock-in", headers=tech_h,
                          json={"lat": 33.6, "lng": -112.2, "accuracy": 250}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["clocked_in"] is False and d["reason"] == "low_accuracy"
    finally:
        _cleanup_job(dbc, jid)


def test_auto_clockin_already_clocked_in(tech_h, dbc):
    _cleanup_entries(dbc, "mike@aquaterra.com")
    # ratelimit cleared by _reset_ratelimit fixture
    # Create a pre-existing open entry
    u = dbc.users.find_one({"email": "mike@aquaterra.com"})
    tenant = dbc.tenants.find_one({"slug": "aquaterra"})
    dbc.time_entries.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": tenant["id"],
        "user_id": u["id"],
        "job_id": "existing-job",
        "clock_in_at": datetime.now(timezone.utc).isoformat(),
        "clock_out_at": None,
        "origin": "manual",
        "status": "open",
        "breaks": [],
    })
    jid = _seed_job(dbc, "aquaterra", "mike@aquaterra.com",
                    site_lat=33.6, site_lng=-112.2, minutes_from_now=15)
    try:
        r = requests.post(f"{API}/workforce/auto-clock-in", headers=tech_h,
                          json={"lat": 33.6, "lng": -112.2, "accuracy": 10}, timeout=15)
        assert r.status_code == 200
        assert r.json()["clocked_in"] is False
        assert r.json()["reason"] == "already_clocked_in"
    finally:
        _cleanup_entries(dbc, "mike@aquaterra.com")
        _cleanup_job(dbc, jid)


def test_auto_clockin_rate_limit_429(tech_h, dbc):
    _cleanup_entries(dbc, "mike@aquaterra.com")
    # NOTE: this test intentionally does NOT reset the rate-limit hook between
    # its two endpoint calls — that's the behaviour under test.
    r1 = requests.post(f"{API}/workforce/auto-clock-in", headers=tech_h,
                      json={"lat": 0, "lng": 0, "accuracy": 10}, timeout=15)
    assert r1.status_code == 200  # returns reason: not_at_any_scheduled_site
    # Second call within 60s → 429
    r2 = requests.post(f"{API}/workforce/auto-clock-in", headers=tech_h,
                      json={"lat": 0, "lng": 0, "accuracy": 10}, timeout=15)
    assert r2.status_code == 429


def test_cancel_within_grace_window(tech_h, dbc):
    _cleanup_entries(dbc, "mike@aquaterra.com")
    # ratelimit cleared by _reset_ratelimit fixture
    jid = _seed_job(dbc, "aquaterra", "mike@aquaterra.com",
                    site_lat=33.6, site_lng=-112.2, minutes_from_now=15)
    try:
        r = requests.post(f"{API}/workforce/auto-clock-in", headers=tech_h,
                          json={"lat": 33.6, "lng": -112.2, "accuracy": 10}, timeout=15)
        assert r.status_code == 200 and r.json()["clocked_in"]
        eid = r.json()["entry_id"]
        # Cancel immediately
        rc = requests.post(f"{API}/workforce/cancel-auto-clock-in/{eid}",
                           headers=tech_h, timeout=15)
        assert rc.status_code == 200
        # Entry gone
        assert dbc.time_entries.find_one({"id": eid}) is None
    finally:
        _cleanup_entries(dbc, "mike@aquaterra.com")
        _cleanup_job(dbc, jid)


def test_cancel_after_grace_window_400(tech_h, dbc):
    _cleanup_entries(dbc, "mike@aquaterra.com")
    # ratelimit cleared by _reset_ratelimit fixture
    u = dbc.users.find_one({"email": "mike@aquaterra.com"})
    tenant = dbc.tenants.find_one({"slug": "aquaterra"})
    old_iso = (datetime.now(timezone.utc) - timedelta(seconds=45)).isoformat()
    eid = str(uuid.uuid4())
    dbc.time_entries.insert_one({
        "id": eid, "tenant_id": tenant["id"], "user_id": u["id"],
        "job_id": "j-old", "clock_in_at": old_iso, "clock_out_at": None,
        "origin": "gps_auto", "status": "open", "breaks": [],
    })
    try:
        r = requests.post(f"{API}/workforce/cancel-auto-clock-in/{eid}",
                          headers=tech_h, timeout=15)
        assert r.status_code == 400 and "grace window" in r.text.lower()
    finally:
        _cleanup_entries(dbc, "mike@aquaterra.com")


def test_submit_report_mandates_clockout_on_auto(tech_h, dbc):
    _cleanup_entries(dbc, "mike@aquaterra.com")
    # ratelimit cleared by _reset_ratelimit fixture
    jid = _seed_job(dbc, "aquaterra", "mike@aquaterra.com",
                    site_lat=33.6, site_lng=-112.2, minutes_from_now=15)
    try:
        # auto-clock-in
        r = requests.post(f"{API}/workforce/auto-clock-in", headers=tech_h,
                          json={"lat": 33.6, "lng": -112.2, "accuracy": 10}, timeout=15)
        eid = r.json()["entry_id"]
        # bootstrap the report
        requests.get(f"{API}/jobs/{jid}/service-report", headers=tech_h, timeout=15)
        # submit
        rr = requests.post(f"{API}/jobs/{jid}/service-report/submit",
                           headers=tech_h, timeout=15)
        assert rr.status_code == 200, rr.text
        data = rr.json()
        assert "clock_out_summary" in data
        assert data["clock_out_summary"]["origin"] == "gps_auto"
        # Entry closed
        e = dbc.time_entries.find_one({"id": eid})
        assert e["clock_out_at"] is not None
        assert e.get("closed_by_report") is True
    finally:
        _cleanup_entries(dbc, "mike@aquaterra.com")
        _cleanup_job(dbc, jid)


def test_tenant_isolation_no_cross_match(tech_h, dbc, sunbelt_tech_h):
    """Aquaterra tech's coords must not resolve to a sunbelt job."""
    _cleanup_entries(dbc, "mike@aquaterra.com")
    _cleanup_entries(dbc, "tech@sunbelt.com")
    # ratelimit cleared by _reset_ratelimit fixture
    # Seed a sunbelt job at exact same coords Mike will report.
    _seed_job(dbc, "sunbelt", "tech@sunbelt.com",
              site_lat=44.0, site_lng=-93.0, minutes_from_now=10)
    try:
        r = requests.post(f"{API}/workforce/auto-clock-in", headers=tech_h,
                          json={"lat": 44.0, "lng": -93.0, "accuracy": 10}, timeout=15)
        assert r.status_code == 200
        # Mike (aquaterra) sees the sunbelt job as invisible → no match
        assert r.json()["clocked_in"] is False
    finally:
        _cleanup_entries(dbc, "mike@aquaterra.com")
        _cleanup_entries(dbc, "tech@sunbelt.com")
        dbc.jobs.delete_many({"customer_name": "TEST_ auto-clockin"})
