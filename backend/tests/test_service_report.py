"""Phase 18B follow-up · Service Report backend tests."""
import os
from pathlib import Path
from datetime import datetime, timezone

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
import bcrypt
import uuid

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL")
        or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
        or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


def _login(email, password="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_user():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def admin_h(admin_user):
    return {"Authorization": f"Bearer {admin_user['access_token']}"}


@pytest.fixture(scope="module")
def tech_user():
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def tech_h(tech_user):
    return {"Authorization": f"Bearer {tech_user['access_token']}"}


@pytest.fixture(scope="module")
def customer_h():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def sunbelt_admin_h():
    return {"Authorization": f"Bearer {_login('admin@sunbelt.com')['access_token']}"}


def _make_job_direct(dbc, tenant_slug: str, tech_id_field: str, service_type: str,
                     customer_id: str = None) -> str:
    """Create a job doc directly in Mongo, scoped to the given tenant + tech."""
    tenant = dbc.tenants.find_one({"slug": tenant_slug})
    assert tenant, f"tenant {tenant_slug} missing"
    jid = str(uuid.uuid4())
    dbc.jobs.insert_one({
        "id": jid,
        "tenant_id": tenant["id"],
        "customer_id": customer_id,
        "customer_name": "TEST_ svc report cust",
        "title": service_type,
        "service_type": service_type,
        "job_type": service_type,
        "status": "scheduled",
        "technician_id": tech_id_field,
        "photos": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return jid


def _cleanup_job(dbc, jid: str):
    dbc.jobs.delete_one({"id": jid})
    dbc.service_reports.delete_many({"job_id": jid})


def test_get_service_report_pool_template(admin_h, tech_h, tech_user, dbc):
    tid = tech_user["user"].get("technician_id") or tech_user["user"]["id"]
    jid = _make_job_direct(dbc, "aquaterra", tid, "Weekly Pool Service")
    try:
        r = requests.get(f"{API}/jobs/{jid}/service-report", headers=tech_h, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["template"] == "pool"
        assert any(f["name"] == "pH" for f in data["chemical_readings"])
        assert len(data["checklist_items"]) >= 6
    finally:
        _cleanup_job(dbc, jid)


def test_get_service_report_landscape_template(tech_h, tech_user, dbc):
    tid = tech_user["user"].get("technician_id") or tech_user["user"]["id"]
    jid = _make_job_direct(dbc, "aquaterra", tid, "Monthly Landscaping")
    try:
        r = requests.get(f"{API}/jobs/{jid}/service-report", headers=tech_h, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["template"] == "landscape"
        assert data["chemical_readings"] == []
        assert len(data["checklist_items"]) >= 6
    finally:
        _cleanup_job(dbc, jid)


def test_get_service_report_generic_template(tech_h, tech_user, dbc):
    tid = tech_user["user"].get("technician_id") or tech_user["user"]["id"]
    jid = _make_job_direct(dbc, "aquaterra", tid, "Other")
    try:
        r = requests.get(f"{API}/jobs/{jid}/service-report", headers=tech_h, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["template"] == "generic"
        assert data["chemical_readings"] == []
    finally:
        _cleanup_job(dbc, jid)


def test_photo_cap_at_10(admin_h, tech_h, tech_user, dbc):
    tid = tech_user["user"].get("technician_id") or tech_user["user"]["id"]
    jid = _make_job_direct(dbc, "aquaterra", tid, "Pool cleaning")
    try:
        # bootstrap
        requests.get(f"{API}/jobs/{jid}/service-report", headers=tech_h, timeout=15)
        # Push 10 photos ok
        for i in range(10):
            r = requests.post(f"{API}/jobs/{jid}/photos", headers=tech_h, json={
                "data": "data:image/png;base64,iVBORw0KGgo=",
                "label": f"p{i}",
            }, timeout=15)
            assert r.status_code == 200, r.text
        # 11th blocked
        r = requests.post(f"{API}/jobs/{jid}/photos", headers=tech_h, json={
            "data": "data:image/png;base64,iVBORw0KGgo=",
        }, timeout=15)
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert detail["remaining_slots"] == 0
        assert "10-photo cap" in detail["msg"]
    finally:
        _cleanup_job(dbc, jid)


def test_autosave_patch_persists(tech_h, tech_user, dbc):
    tid = tech_user["user"].get("technician_id") or tech_user["user"]["id"]
    jid = _make_job_direct(dbc, "aquaterra", tid, "Pool service")
    try:
        requests.get(f"{API}/jobs/{jid}/service-report", headers=tech_h, timeout=15)
        r = requests.patch(f"{API}/jobs/{jid}/service-report", headers=tech_h, json={
            "chemical_readings": [{"name": "pH", "value": 7.4, "unit": "", "ts": None}],
            "notes": "TEST_ autosave",
        }, timeout=15)
        assert r.status_code == 200
        r2 = requests.get(f"{API}/jobs/{jid}/service-report", headers=tech_h, timeout=15).json()
        assert r2["notes"] == "TEST_ autosave"
        ph = next((x for x in r2["chemical_readings"] if x["name"] == "pH"), None)
        assert ph and float(ph["value"]) == 7.4
    finally:
        _cleanup_job(dbc, jid)


def test_submit_locks_report(tech_h, tech_user, dbc):
    tid = tech_user["user"].get("technician_id") or tech_user["user"]["id"]
    jid = _make_job_direct(dbc, "aquaterra", tid, "Pool weekly")
    try:
        requests.get(f"{API}/jobs/{jid}/service-report", headers=tech_h, timeout=15)
        r = requests.post(f"{API}/jobs/{jid}/service-report/submit",
                          headers=tech_h, timeout=15)
        assert r.status_code == 200 and r.json()["submitted_at"]
        # PATCH after submit → 409
        r2 = requests.patch(f"{API}/jobs/{jid}/service-report", headers=tech_h,
                            json={"notes": "should fail"}, timeout=15)
        assert r2.status_code == 409
        # Job status rolled forward
        job = dbc.jobs.find_one({"id": jid})
        assert job["status"] == "completed"
        assert job.get("service_report_submitted_at")
    finally:
        _cleanup_job(dbc, jid)


def test_tenant_isolation_and_customer_forbidden(tech_h, tech_user, sunbelt_admin_h,
                                                 customer_h, dbc):
    tid = tech_user["user"].get("technician_id") or tech_user["user"]["id"]
    jid = _make_job_direct(dbc, "aquaterra", tid, "Pool")
    try:
        # sunbelt admin sees 404 (leak-proof)
        r = requests.get(f"{API}/jobs/{jid}/service-report",
                         headers=sunbelt_admin_h, timeout=15)
        assert r.status_code == 404
        # customer role → 403
        r = requests.get(f"{API}/jobs/{jid}/service-report",
                         headers=customer_h, timeout=15)
        assert r.status_code in (403, 404)
    finally:
        _cleanup_job(dbc, jid)
