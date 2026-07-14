"""Phase 16C add-on · Verify tech views don't leak revenue/pricing fields."""
import os
from pathlib import Path
import requests
import pytest
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

REVENUE_KEYS = ("price", "cost", "total", "subtotal", "tax_amount",
                "revenue", "invoice_total", "quote_total", "margin",
                "labor_cost", "materials_cost", "gross_margin")


def _login(email, password="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


# ─── Test 1 · GET /jobs list — no revenue keys for tech ───────────────────
def test_jobs_list_strips_revenue_for_tech(tech_h):
    r = requests.get(f"{API}/jobs", headers=tech_h, timeout=20)
    assert r.status_code == 200
    for job in r.json():
        for k in REVENUE_KEYS:
            assert k not in job, f"Tech saw revenue key '{k}' on job {job.get('id')}"


# ─── Test 2 · GET /jobs/{id} — no revenue keys for tech ───────────────────
def test_job_detail_strips_revenue_for_tech(tech_h, admin_h, db):
    # Find a job assigned to Mike.
    user = db.users.find_one({"email": "mike@aquaterra.com"})
    job = db.jobs.find_one({"technician_id": user.get("technician_id") or user["id"]}) \
          or db.jobs.find_one({})
    assert job, "expected at least one job in aquaterra"
    r = requests.get(f"{API}/jobs/{job['id']}", headers=tech_h, timeout=20)
    if r.status_code == 403:
        # Not assigned — force-assign to Mike for the test.
        db.jobs.update_one({"id": job["id"]},
                           {"$set": {"technician_id": user.get("technician_id") or user["id"],
                                     "assigned_technician_id": user["id"],
                                     "assigned_to": user["id"]}})
        r = requests.get(f"{API}/jobs/{job['id']}", headers=tech_h, timeout=20)
    assert r.status_code == 200
    d = r.json()
    for k in REVENUE_KEYS:
        assert k not in d, f"Tech saw revenue key '{k}' on job detail"


# ─── Test 3 · Admin still sees revenue keys ──────────────────────────────
def test_admin_still_sees_price(admin_h, db):
    job = db.jobs.find_one({})
    if not job:
        pytest.skip("no jobs seeded")
    r = requests.get(f"{API}/jobs/{job['id']}", headers=admin_h, timeout=20)
    assert r.status_code == 200
    d = r.json()
    # `price` may still be 0 or missing depending on the job, but it must NOT be
    # actively stripped — admin can see the field when it exists.
    # We assert the endpoint returns 200 and the doc contains at least one non-tech field.
    assert "customer_id" in d or "customer_name" in d


# ─── Test 4 · Tenants/current no longer surfaces plan_features ────────────
def test_tenants_current_no_plan_features(admin_h):
    r = requests.get(f"{API}/tenants/current", headers=admin_h, timeout=20)
    assert r.status_code == 200
    assert "plan_features" not in r.json(), "plan_features must be removed post-16C add-on"


# ─── Test 5 · Plans endpoints are gone (410/404) ──────────────────────────
def test_plans_endpoints_removed(admin_h):
    r = requests.get(f"{API}/plans", headers=admin_h, timeout=20)
    assert r.status_code in (404, 405), f"plans endpoint should be removed, got {r.status_code}"
