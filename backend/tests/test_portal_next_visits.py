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


def _set_service_category(dbc, customer_id, value):
    """Feb-2026 hybrid-gate helper — stamp
    ``customers.service_category`` on the per-test customer so the
    endpoint's fallback step can derive eligibility from it."""
    dbc.customers.update_one(
        {"id": customer_id},
        {"$set": {"service_category": value}},
    )


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
def test_subscription_active_but_no_future_job_surfaces_placeholder(
        dbc, portal_customer):
    """β1 ruling reversal (Feb-2026 Portal) — a subscribed service
    with no future job no longer fail-quiets; it surfaces a
    placeholder row with ``next_visit_at: null`` so the FE can
    render a "No visit scheduled" tile."""
    _add_subscription(dbc, portal_customer["tenant_id"],
                       portal_customer["customer_id"],
                       "Weekly Pool Service", active=True)
    # PAST job — should NOT populate the tile, but a placeholder
    # row for the eligible service still surfaces.
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Weekly Pool Service", days_ahead=-3)
    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers=portal_customer["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert len(body["next_visits"]) == 1
    row = body["next_visits"][0]
    assert row == {
        "service_type":  "pool",
        "next_visit_at": None,
        "tech_name":     None,
        "visit_id":      None,
    }


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
# 5. Mixed — pool eligible with future job, landscape eligible
# WITHOUT future job (placeholder), filter eligible with future
# job → returns all three tiles in canonical order per β1 ruling.
# ═══════════════════════════════════════════════════════════════════
def test_mixed_eligibility_returns_all_eligible_in_order(dbc, portal_customer):
    # Pool: active + future job.
    _add_subscription(dbc, portal_customer["tenant_id"],
                       portal_customer["customer_id"],
                       "Weekly Pool Cleaning", active=True)
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Weekly Pool Service", days_ahead=5)
    # Landscape: active BUT no future job — β1 surfaces a
    # placeholder tile with ``next_visit_at: null``.
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
    # Canonical order preserved: pool → landscape → filter_cleaning.
    assert keys == ["pool", "landscape", "filter_cleaning"]
    # Landscape row is the placeholder.
    landscape = next(r for r in body["next_visits"]
                      if r["service_type"] == "landscape")
    assert landscape["next_visit_at"] is None
    assert landscape["tech_name"] is None
    assert landscape["visit_id"] is None
    # Pool + filter_cleaning rows have real datetimes.
    pool = next(r for r in body["next_visits"]
                 if r["service_type"] == "pool")
    assert pool["next_visit_at"] is not None


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



# ═══════════════════════════════════════════════════════════════════
# β1 · Feb-2026 — placeholder-row contract covering the three
# operator-dispatched spec cases that weren't locked by the
# pre-shipped suite.
# ═══════════════════════════════════════════════════════════════════
def test_b1_filter_cleaning_only_no_future_job_placeholder(
        dbc, portal_customer):
    """β1 — single filter_cleaning subscription, no future job
    → single placeholder tile with ``next_visit_at: null``."""
    _add_subscription(dbc, portal_customer["tenant_id"],
                       portal_customer["customer_id"],
                       "Quarterly Filter Cleaning", active=True)
    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers=portal_customer["headers"], timeout=20)
    body = r.json()
    assert len(body["next_visits"]) == 1
    row = body["next_visits"][0]
    assert row == {
        "service_type":  "filter_cleaning",
        "next_visit_at": None,
        "tech_name":     None,
        "visit_id":      None,
    }


def test_b1_pool_and_landscape_only_pool_has_job(dbc, portal_customer):
    """β1 — two subscriptions (pool + landscape), ONE future job
    (pool) → two tiles, pool populated, landscape placeholder."""
    _add_subscription(dbc, portal_customer["tenant_id"],
                       portal_customer["customer_id"],
                       "Weekly Pool Cleaning", active=True)
    _add_subscription(dbc, portal_customer["tenant_id"],
                       portal_customer["customer_id"],
                       "Monthly Landscape Package", active=True)
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Weekly Pool Service", days_ahead=5)
    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers=portal_customer["headers"], timeout=20)
    body = r.json()
    assert [r["service_type"] for r in body["next_visits"]] == [
        "pool", "landscape",
    ]
    pool = body["next_visits"][0]
    assert pool["next_visit_at"] is not None
    assert pool["visit_id"] is not None
    landscape = body["next_visits"][1]
    assert landscape["next_visit_at"] is None
    assert landscape["tech_name"] is None
    assert landscape["visit_id"] is None


def test_b1_canonical_order_all_three_placeholders(dbc, portal_customer):
    """β1 regression — ordering must stay pool → landscape →
    filter_cleaning even when ALL three slots are placeholders
    (subscriptions planted in reverse order to confirm the sort
    is not seed-order sensitive)."""
    _add_subscription(dbc, portal_customer["tenant_id"],
                       portal_customer["customer_id"],
                       "Quarterly Filter Cleaning", active=True)
    _add_subscription(dbc, portal_customer["tenant_id"],
                       portal_customer["customer_id"],
                       "Monthly Landscape Package", active=True)
    _add_subscription(dbc, portal_customer["tenant_id"],
                       portal_customer["customer_id"],
                       "Weekly Pool Cleaning", active=True)
    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers=portal_customer["headers"], timeout=20)
    body = r.json()
    keys = [row["service_type"] for row in body["next_visits"]]
    assert keys == ["pool", "landscape", "filter_cleaning"]
    for row in body["next_visits"]:
        assert row["next_visit_at"] is None
        assert row["tech_name"] is None
        assert row["visit_id"] is None


# ═══════════════════════════════════════════════════════════════════
# Feb-2026 · HYBRID FALLBACK — ``customers.service_category`` acts
# as a secondary eligibility gate when a customer hasn't had their
# billing_plans fully seeded.  Preserves β1 shape (placeholder tile
# per eligible service when no future job exists) + canonical order.
# ═══════════════════════════════════════════════════════════════════
def test_hybrid_fallback_pool_service_category_no_plans(
        dbc, portal_customer):
    """No active billing_plans + ``service_category='pool'`` →
    one placeholder pool tile with ``next_visit_at: null``."""
    _set_service_category(dbc, portal_customer["customer_id"], "pool")
    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers=portal_customer["headers"], timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["next_visits"]) == 1
    assert body["next_visits"][0] == {
        "service_type":  "pool",
        "next_visit_at": None,
        "tech_name":     None,
        "visit_id":      None,
    }


def test_hybrid_fallback_landscaping_service_category_no_plans(
        dbc, portal_customer):
    """No active billing_plans + ``service_category='landscaping'`` →
    one placeholder landscape tile."""
    _set_service_category(
        dbc, portal_customer["customer_id"], "landscaping",
    )
    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers=portal_customer["headers"], timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["next_visits"]) == 1
    assert body["next_visits"][0] == {
        "service_type":  "landscape",
        "next_visit_at": None,
        "tech_name":     None,
        "visit_id":      None,
    }


def test_hybrid_fallback_both_service_category_no_plans(
        dbc, portal_customer):
    """No active billing_plans + ``service_category='both'`` →
    pool AND landscape placeholder tiles in canonical order."""
    _set_service_category(dbc, portal_customer["customer_id"], "both")
    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers=portal_customer["headers"], timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    keys = [row["service_type"] for row in body["next_visits"]]
    assert keys == ["pool", "landscape"]
    for row in body["next_visits"]:
        assert row["next_visit_at"] is None
        assert row["tech_name"] is None
        assert row["visit_id"] is None


def test_hybrid_fallback_null_service_category_no_plans(
        dbc, portal_customer):
    """No active billing_plans + ``service_category`` explicitly
    null → empty tiles array (no fallback addition)."""
    _set_service_category(dbc, portal_customer["customer_id"], None)
    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers=portal_customer["headers"], timeout=20)
    assert r.status_code == 200, r.text
    assert r.json() == {"next_visits": []}


def test_hybrid_fallback_plan_and_service_category_union(
        dbc, portal_customer):
    """Active pool plan (with future pool job) + ``service_category=
    'both'`` → UNION: pool tile populated from the plan, landscape
    tile placeholder from the fallback.  Canonical order preserved."""
    _set_service_category(dbc, portal_customer["customer_id"], "both")
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
    keys = [row["service_type"] for row in body["next_visits"]]
    assert keys == ["pool", "landscape"]
    pool = body["next_visits"][0]
    assert pool["next_visit_at"] is not None
    assert pool["visit_id"] is not None
    landscape = body["next_visits"][1]
    assert landscape["next_visit_at"] is None
    assert landscape["tech_name"] is None
    assert landscape["visit_id"] is None
