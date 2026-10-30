"""Feb-2026 · Pool Service PS-D — portal next-visits endpoint tests.

Covers the SIMPLIFIED jobs-driven eligibility gate: any job on the
customer (past, present, future, any status) marks its canonical
category as eligible.  Future scheduled jobs populate the tile;
eligible categories without a future job surface a null-dated
placeholder.  Replaces the retired β1 ``billing_plans.active`` +
``customers.service_category`` hybrid gate (cross-ref: this commit's
SHA; earlier hybrid SHA 3a618bc5e is logically superseded by this
file's rewrite).

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
    dbc.customers.insert_one({
        "id": cid, "tenant_id": tid,
        "name": "PS-D Customer",
        "email": email,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
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
    dbc.customers.delete_one({"id": cid})
    dbc.users.delete_one({"id": uid})
    dbc.jobs.delete_many({"customer_id": cid})
    dbc.billing_plans.delete_many({"customer_id": cid})


def _add_job(dbc, tenant_id, customer_id, *, service_type,
              days_ahead=3, status="scheduled",
              technician_id=None, hour=9):
    """Seed a job for the test customer.  ``days_ahead`` may be
    negative (past job) or positive (future job).  Status defaults
    to ``scheduled`` but may be overridden to simulate a completed /
    draft job that still marks the category eligible under the new
    jobs-driven gate."""
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
# Feb-2026 · JOBS-DRIVEN GATE — eligibility is derived purely from
# the customer's job history. These 9 cases replace the retired β1
# ``billing_plans.active`` + ``customers.service_category`` hybrid
# suite; the FE null-dated placeholder render-path contract is
# preserved byte-identical.
# ═══════════════════════════════════════════════════════════════════

# 1. Past pool job + no future pool job → one placeholder pool tile.
def test_past_pool_job_only_surfaces_placeholder(dbc, portal_customer):
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Weekly Pool Service", days_ahead=-14,
              status="completed")
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


# 2. Past landscape job + future landscape job → populated tile.
def test_past_and_future_landscape_jobs_populate_tile(
        dbc, portal_customer):
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Monthly Landscape Maintenance",
              days_ahead=-30, status="completed")
    future_id = _add_job(dbc, portal_customer["tenant_id"],
                           portal_customer["customer_id"],
                           service_type="Monthly Landscape Maintenance",
                           days_ahead=7)
    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers=portal_customer["headers"], timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["next_visits"]) == 1
    row = body["next_visits"][0]
    assert row["service_type"] == "landscape"
    assert row["next_visit_at"] is not None
    assert row["visit_id"] == future_id


# 3. Three categories (pool, landscape, filter_cleaning) across any
#    mix of past + future jobs → three tiles in canonical order.
def test_three_categories_across_mixed_jobs_emit_three_tiles(
        dbc, portal_customer):
    # Pool: past + future.
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Pool Service", days_ahead=-7,
              status="completed")
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Pool Service", days_ahead=5)
    # Landscape: past only (placeholder).
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Landscape Package", days_ahead=-10,
              status="completed")
    # Filter cleaning: future only.
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Cartridge Cleaning", days_ahead=12)
    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers=portal_customer["headers"], timeout=20)
    body = r.json()
    keys = [row["service_type"] for row in body["next_visits"]]
    # Canonical ordering locked.
    assert keys == ["pool", "landscape", "filter_cleaning"]
    rows_by_key = {r["service_type"]: r for r in body["next_visits"]}
    assert rows_by_key["pool"]["next_visit_at"] is not None
    assert rows_by_key["landscape"]["next_visit_at"] is None
    assert rows_by_key["filter_cleaning"]["next_visit_at"] is not None


# 4. No jobs at all → empty tiles array.
def test_no_jobs_returns_empty(portal_customer):
    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers=portal_customer["headers"], timeout=20)
    assert r.status_code == 200, r.text
    assert r.json() == {"next_visits": []}


# 5. Jobs exist but all land outside the canonical category set →
#    empty tiles (don't invent a category).
def test_jobs_in_unmatched_categories_return_empty(
        dbc, portal_customer):
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Fence Painting", days_ahead=5)
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Driveway Sealing", days_ahead=-10,
              status="completed")
    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers=portal_customer["headers"], timeout=20)
    assert r.status_code == 200, r.text
    assert r.json() == {"next_visits": []}


# 6. Ordering preserved regardless of seed order:
#    pool → landscape → filter_cleaning.
def test_canonical_ordering_regardless_of_seed_order(
        dbc, portal_customer):
    # Seed in REVERSE canonical order.
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Filter Cleaning", days_ahead=15)
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Landscape Maintenance", days_ahead=8)
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Pool Service", days_ahead=2)
    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers=portal_customer["headers"], timeout=20)
    body = r.json()
    keys = [row["service_type"] for row in body["next_visits"]]
    assert keys == ["pool", "landscape", "filter_cleaning"]


# 7. Future job wins over past job for the SAME category — tile is
#    populated with the future row, not null-dated.
def test_future_job_wins_over_past_job_for_same_category(
        dbc, portal_customer):
    _add_job(dbc, portal_customer["tenant_id"],
              portal_customer["customer_id"],
              service_type="Pool Service", days_ahead=-7,
              status="completed")
    future_id = _add_job(dbc, portal_customer["tenant_id"],
                           portal_customer["customer_id"],
                           service_type="Pool Service", days_ahead=4)
    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers=portal_customer["headers"], timeout=20)
    body = r.json()
    assert len(body["next_visits"]) == 1
    row = body["next_visits"][0]
    assert row["service_type"] == "pool"
    assert row["next_visit_at"] is not None
    assert row["visit_id"] == future_id


# 8. Cross-customer isolation — customer A sees nothing of B's jobs.
#    Regression lock preserved from β1.
def test_cross_customer_isolation(dbc, portal_customer):
    other_cid = f"ps-d-other-{uuid.uuid4().hex[:8]}"
    try:
        _add_job(dbc, portal_customer["tenant_id"], other_cid,
                  service_type="Pool Service", days_ahead=5)
        _add_job(dbc, portal_customer["tenant_id"], other_cid,
                  service_type="Pool Service", days_ahead=-10,
                  status="completed")
        r = requests.get(f"{API}/portal/dashboard/next-visits",
                            headers=portal_customer["headers"],
                            timeout=20)
        assert r.status_code == 200
        assert r.json() == {"next_visits": []}
    finally:
        dbc.jobs.delete_many({"customer_id": other_cid})


# 9. Admin role → 403.  Regression lock preserved from β1.
def test_admin_role_forbidden():
    admin = _login("admin@aquaterra.com")
    r = requests.get(f"{API}/portal/dashboard/next-visits",
                        headers={"Authorization":
                                 f"Bearer {admin['access_token']}"},
                        timeout=20)
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "Customers only"
