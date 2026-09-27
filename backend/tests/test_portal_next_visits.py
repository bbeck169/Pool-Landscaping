"""Feb-2026 · Pool Service PS-D — portal next-visits endpoint tests.

Covers the eligibility matrix (subscription active/inactive) ×
(future job yes/no) across pool / landscape / filter_cleaning +
tenant isolation, customer isolation, empty-subscription fallback,
"soonest" selection when multiple future jobs exist for the same
category, and tech-name resolution.

Uses live HTTP against localhost:8001 (matches the pattern from
tests/test_service_report_tech_edit.py + tests/test_service_report.py).
The endpoint is JWT-scoped to customers, so a portal-role login is
required — we bootstrap a dedicated customer user on the seeded
aquaterra tenant per-test to keep row-hygiene tight.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
# Feb-2026 · PS-D — hit the LOCAL supervisor-managed backend
# directly so per-test seed rows we write to the LOCAL Mongo
# instance are visible to the same process serving the endpoint.
# (Preview URL points at a separate deployment with its own DB;
# our seeded ad-hoc users don't exist there.)
BASE = "http://localhost:8001"
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME  = _BE.get("DB_NAME")  or os.environ.get("DB_NAME")


def _login(email, password="password123"):
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": password},
                        timeout=20)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def aquaterra_tenant_id(dbc):
    t = dbc.tenants.find_one({"slug": "aquaterra"})
    assert t, "aquaterra tenant not seeded"
    return t["id"]


@pytest.fixture()
def portal_customer(dbc, aquaterra_tenant_id):
    """Bootstrap a portal-role customer user with a matching
    customer row + a fresh JWT.  Cleaned up on teardown so the
    test isolation stays clean."""
    tid = aquaterra_tenant_id
    cid = f"ps-d-cust-{uuid.uuid4().hex[:8]}"
    email = f"psd-{uuid.uuid4().hex[:8]}@example.com"
    # Customer row.
    dbc.customers.insert_one({
        "id": cid, "tenant_id": tid,
        "name": "PS-D Customer",
        "email": email,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Portal user with a bcrypt-hashed password matching test-cred
    # helpers used elsewhere.
    ph = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode()
    uid = f"ps-d-user-{uuid.uuid4().hex[:8]}"
    dbc.users.insert_one({
        "id": uid, "tenant_id": tid,
        "email": email, "password_hash": ph,
        "role": "customer",
        "customer_id": cid,
        "name": "PS-D Portal User",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    login = _login(email, "password123")
    yield {
        "tenant_id": tid,
        "customer_id": cid,
        "user_id": uid,
        "token": login["access_token"],
        "headers": {
            "Authorization": f"Bearer {login['access_token']}",
        },
    }
    # Teardown — kill customer, user, jobs, billing_plans.
    dbc.customers.delete_one({"id": cid})
    dbc.users.delete_one({"id": uid})
    dbc.jobs.delete_many({"customer_id": cid})
    dbc.billing_plans.delete_many({"customer_id": cid})


def _add_subscription(dbc, tenant_id, customer_id,
                        service_label, active=True):
    dbc.billing_plans.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "service": service_label,
        "amount": 100.0,
        "cadence": "monthly",
        "active": active,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


def _add_job(dbc, tenant_id, customer_id, *, service_type,
              days_ahead=3, status="scheduled",
              technician_id=None, hour=9):
    when = datetime.now(timezone.utc) + timedelta(days=days_ahead,
                                                        hours=hour - 12)
    when_iso = when.isoformat().replace("+00:00", "Z")
    job_id = str(uuid.uuid4())
    dbc.jobs.insert_one({
        "id": job_id,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "customer_name": "PS-D Customer",
        "title": f"PS-D {service_type}",
        "service_type": service_type,
        "job_type": service_type,
        "status": status,
        "scheduled_at": when_iso,
        "scheduled_date": when.date().isoformat(),
        "technician_id": technician_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return job_id


# ═══════════════════════════════════════════════════════════════════
# 1. No subscriptions at all → empty array.
# ═══════════════════════════════════════════════════════════════════
def test_no_subscriptions_returns_empty(portal_customer):
    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers=portal_customer["headers"], timeout=20)
    assert r.status_code == 200, r.text
    assert r.json() == {"next_visits": []}


# ═══════════════════════════════════════════════════════════════════
# 2. Active pool subscription + future pool job → tile returned.
# ═══════════════════════════════════════════════════════════════════
def test_pool_eligible_returns_pool_tile(dbc, portal_customer):
    _add_subscription(dbc, portal_customer["tenant_id"],
                       portal_customer["customer_id"],
                       "Weekly Pool Cleaning", active=True)
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Weekly Pool Service", days_ahead=5)
    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers=portal_customer["headers"], timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["next_visits"]) == 1
    row = body["next_visits"][0]
    assert row["service_type"] == "pool"
    assert row["next_visit_at"] is not None
    assert row["visit_id"] is not None
    # No tech assigned in this test.
    assert row["tech_name"] is None


# ═══════════════════════════════════════════════════════════════════
# 3. Active subscription but NO future job → tile hidden.
# ═══════════════════════════════════════════════════════════════════
def test_subscription_active_but_no_future_job_hides_tile(dbc, portal_customer):
    _add_subscription(dbc, portal_customer["tenant_id"],
                       portal_customer["customer_id"],
                       "Weekly Pool Service", active=True)
    # PAST job — should not surface.
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Weekly Pool Service", days_ahead=-3)
    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers=portal_customer["headers"], timeout=20)
    assert r.status_code == 200
    assert r.json() == {"next_visits": []}


# ═══════════════════════════════════════════════════════════════════
# 4. Inactive subscription + future job → tile hidden.
# ═══════════════════════════════════════════════════════════════════
def test_inactive_subscription_hides_tile(dbc, portal_customer):
    _add_subscription(dbc, portal_customer["tenant_id"],
                       portal_customer["customer_id"],
                       "Weekly Pool Service", active=False)
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Weekly Pool Service", days_ahead=5)
    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers=portal_customer["headers"], timeout=20)
    assert r.status_code == 200
    assert r.json() == {"next_visits": []}


# ═══════════════════════════════════════════════════════════════════
# 5. Mixed — pool eligible + landscape ineligible + filter
# eligible → returns pool + filter tiles in canonical order.
# ═══════════════════════════════════════════════════════════════════
def test_mixed_eligibility_returns_only_eligible_in_order(dbc, portal_customer):
    # Pool: active + future job.
    _add_subscription(dbc, portal_customer["tenant_id"],
                       portal_customer["customer_id"],
                       "Weekly Pool Cleaning", active=True)
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Weekly Pool Service", days_ahead=5)
    # Landscape: active BUT no future job — tile hidden.
    _add_subscription(dbc, portal_customer["tenant_id"],
                       portal_customer["customer_id"],
                       "Monthly Landscape Package", active=True)
    # Filter Cleaning: active + future job.
    _add_subscription(dbc, portal_customer["tenant_id"],
                       portal_customer["customer_id"],
                       "Quarterly Filter Cleaning", active=True)
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Filter Cleaning", days_ahead=10)

    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers=portal_customer["headers"], timeout=20)
    body = r.json()
    keys = [row["service_type"] for row in body["next_visits"]]
    # Pool listed BEFORE filter_cleaning (canonical order).
    assert keys == ["pool", "filter_cleaning"]


# ═══════════════════════════════════════════════════════════════════
# 6. Multiple future jobs for same category → returns the SOONEST.
# ═══════════════════════════════════════════════════════════════════
def test_multiple_future_jobs_returns_soonest(dbc, portal_customer):
    _add_subscription(dbc, portal_customer["tenant_id"],
                       portal_customer["customer_id"],
                       "Weekly Pool Service", active=True)
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Pool Service", days_ahead=20)  # far
    soonest = _add_job(dbc, portal_customer["tenant_id"],
                          portal_customer["customer_id"],
                          service_type="Pool Service", days_ahead=3)   # near
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Pool Service", days_ahead=10)  # mid

    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers=portal_customer["headers"], timeout=20)
    body = r.json()
    assert len(body["next_visits"]) == 1
    assert body["next_visits"][0]["visit_id"] == soonest


# ═══════════════════════════════════════════════════════════════════
# 7. Tech name resolves when technician_id populated.
# ═══════════════════════════════════════════════════════════════════
def test_tech_name_resolves_when_technician_assigned(dbc, portal_customer):
    tid = portal_customer["tenant_id"]
    # Seed a technician row on the tenant.
    tech_id = f"ps-d-tech-{uuid.uuid4().hex[:6]}"
    dbc.technicians.insert_one({
        "id": tech_id, "tenant_id": tid,
        "name": "Mike Rodriguez",
        "active": True,
    })
    try:
        _add_subscription(dbc, tid, portal_customer["customer_id"],
                           "Weekly Pool Service", active=True)
        _add_job(dbc, tid, portal_customer["customer_id"],
                  service_type="Pool Service", days_ahead=5,
                  technician_id=tech_id)
        r = requests.get(f"{API}/portal/dashboard/next-visits",
                            headers=portal_customer["headers"],
                            timeout=20)
        row = r.json()["next_visits"][0]
        assert row["tech_name"] == "Mike Rodriguez"
    finally:
        dbc.technicians.delete_one({"id": tech_id})


# ═══════════════════════════════════════════════════════════════════
# 8. Cross-customer read isolation — customer A CANNOT see
# customer B's future visits.
# ═══════════════════════════════════════════════════════════════════
def test_cross_customer_isolation(dbc, portal_customer):
    other_cid = f"ps-d-other-{uuid.uuid4().hex[:8]}"
    try:
        _add_subscription(dbc, portal_customer["tenant_id"], other_cid,
                           "Weekly Pool Service", active=True)
        _add_job(dbc, portal_customer["tenant_id"], other_cid,
                  service_type="Pool Service", days_ahead=5)
        # portal_customer is authenticated as themselves — endpoint
        # scopes to JWT.customer_id, not any body/query param, so
        # they see NOTHING (their own subs/jobs are empty).
        r = requests.get(f"{API}/portal/dashboard/next-visits",
                            headers=portal_customer["headers"], timeout=20)
        assert r.status_code == 200
        assert r.json() == {"next_visits": []}
    finally:
        dbc.billing_plans.delete_many({"customer_id": other_cid})
        dbc.jobs.delete_many({"customer_id": other_cid})


# ═══════════════════════════════════════════════════════════════════
# 9. Non-customer role (admin) → 403.
# ═══════════════════════════════════════════════════════════════════
def test_admin_role_forbidden():
    admin = _login("admin@aquaterra.com")
    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers={"Authorization":
                                 f"Bearer {admin['access_token']}"},
                        timeout=20)
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "Customers only"
