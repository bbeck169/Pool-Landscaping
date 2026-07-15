"""Phase 28.1 · Warranty portal tests."""
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"


def _login(e, pw="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": e, "password": pw},
                       timeout=15); r.raise_for_status(); return r.json()


@pytest.fixture(scope="module")
def dbc(): return MongoClient(_BE["MONGO_URL"])[_BE["DB_NAME"]]

@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def customer_h():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}


@pytest.fixture
def a_plan(admin_h, dbc):
    r = requests.post(f"{API}/warranties/plans", headers=admin_h, json={
        "name": "Test Warranty " + str(int(time.time())),
        "kind": "warranty", "duration_months": 12,
        "coverage_summary": "test", "price": 199,
    }, timeout=15).json()
    yield r
    dbc.warranty_plans.delete_one({"id": r["id"]})


def test_plan_crud_and_role_gating(admin_h, customer_h, dbc):
    # Customer cannot create
    r = requests.post(f"{API}/warranties/plans", headers=customer_h,
                        json={"name": "X", "kind": "warranty",
                                "duration_months": 12}, timeout=10)
    assert r.status_code == 403
    # Admin can
    r = requests.post(f"{API}/warranties/plans", headers=admin_h, json={
        "name": "CRUD Test " + str(int(time.time())),
        "kind": "warranty", "duration_months": 6,
    }, timeout=15).json()
    pid = r["id"]
    up = requests.patch(f"{API}/warranties/plans/{pid}", headers=admin_h,
                         json={"price": 99}, timeout=10).json()
    assert up["price"] == 99
    d = requests.delete(f"{API}/warranties/plans/{pid}", headers=admin_h,
                          timeout=10).json()
    assert d["deleted"]


def test_contract_end_date_auto_computed(admin_h, a_plan, dbc):
    cust = dbc.customers.find_one({"tenant_id": a_plan["tenant_id"]}
                                     if "tenant_id" in a_plan
                                     else dbc.tenants.find_one(
                                         {"slug": "aquaterra"}))
    t = dbc.tenants.find_one({"slug": "aquaterra"})
    cust = dbc.customers.find_one({"tenant_id": t["id"]})
    r = requests.post(f"{API}/warranties/contracts", headers=admin_h, json={
        "plan_id": a_plan["id"], "customer_id": cust["id"],
        "start_date": "2026-01-15", "notes": "test",
    }, timeout=15).json()
    assert r["end_date"] == "2027-01-15"  # +12 months
    assert r["status"] == "active"
    dbc.warranty_contracts.delete_one({"id": r["id"]})


def test_contract_cancel(admin_h, a_plan, dbc):
    t = dbc.tenants.find_one({"slug": "aquaterra"})
    cust = dbc.customers.find_one({"tenant_id": t["id"]})
    c = requests.post(f"{API}/warranties/contracts", headers=admin_h, json={
        "plan_id": a_plan["id"], "customer_id": cust["id"],
        "start_date": "2026-01-01",
    }, timeout=15).json()
    r = requests.post(f"{API}/warranties/contracts/{c['id']}/cancel",
                        headers=admin_h, json={"reason": "test cancel"},
                        timeout=15).json()
    assert r["status"] == "cancelled"
    assert r["cancel_reason"] == "test cancel"
    dbc.warranty_contracts.delete_one({"id": c["id"]})


def test_admin_files_claim(admin_h, a_plan, dbc):
    t = dbc.tenants.find_one({"slug": "aquaterra"})
    cust = dbc.customers.find_one({"tenant_id": t["id"]})
    c = requests.post(f"{API}/warranties/contracts", headers=admin_h, json={
        "plan_id": a_plan["id"], "customer_id": cust["id"],
        "start_date": "2026-01-01",
    }, timeout=15).json()
    claim = requests.post(
        f"{API}/warranties/contracts/{c['id']}/file-claim", headers=admin_h,
        json={"description": "Pump fails", "issue_type": "equipment"},
        timeout=15).json()
    assert claim["status"] == "submitted"
    assert claim["filed_by_role"] == "admin"
    # Contract flipped to claim_pending
    contract = dbc.warranty_contracts.find_one({"id": c["id"]})
    assert contract["status"] == "claim_pending"
    dbc.warranty_claims.delete_one({"id": claim["id"]})
    dbc.warranty_contracts.delete_one({"id": c["id"]})


def test_customer_portal_flow(admin_h, customer_h, a_plan, dbc):
    """Customer can list own contracts + file claim on own contract."""
    t = dbc.tenants.find_one({"slug": "aquaterra"})
    cust_user = dbc.users.find_one({"email": "customer@aquaterra.com"})
    customer_id = cust_user.get("customer_id") or cust_user["id"]
    c = requests.post(f"{API}/warranties/contracts", headers=admin_h, json={
        "plan_id": a_plan["id"], "customer_id": customer_id,
        "start_date": "2026-01-01",
    }, timeout=15).json()
    # Customer sees the contract
    listed = requests.get(f"{API}/portal/warranties", headers=customer_h,
                             timeout=10).json()
    assert any(x["id"] == c["id"] for x in listed["items"])
    # Customer files a claim
    claim = requests.post(
        f"{API}/portal/warranties/{c['id']}/file-claim",
        headers=customer_h,
        json={"description": "Broken heater", "issue_type": "equipment"},
        timeout=15).json()
    assert claim["filed_by_role"] == "customer"
    # Claim shows up in the customer's list
    ml = requests.get(f"{API}/portal/warranties/{c['id']}/claims",
                        headers=customer_h, timeout=10).json()
    assert any(x["id"] == claim["id"] for x in ml["items"])
    dbc.warranty_claims.delete_one({"id": claim["id"]})
    dbc.warranty_contracts.delete_one({"id": c["id"]})


def test_expiration_reminder_and_idempotency(admin_h, a_plan, dbc):
    """Contract ending in 7 days triggers stage-7 reminder; second scan
    doesn't dupe."""
    t = dbc.tenants.find_one({"slug": "aquaterra"})
    cust = dbc.customers.find_one({"tenant_id": t["id"]})
    target = (datetime.now(timezone.utc).date()
                + timedelta(days=7)).isoformat()
    c = requests.post(f"{API}/warranties/contracts", headers=admin_h, json={
        "plan_id": a_plan["id"], "customer_id": cust["id"],
        "start_date": "2025-01-01", "custom_end_date": target,
    }, timeout=15).json()
    try:
        # First scan → sends stage 7 reminder
        r1 = requests.post(f"{API}/warranties/_test/run-scan-now",
                             headers=admin_h, timeout=25).json()
        r1_count = dbc.warranty_reminders_sent.count_documents(
            {"tenant_id": t["id"], "contract_id": c["id"], "stage": 7})
        assert r1_count == 1, f"expected 1 stage-7 reminder, got {r1_count}"
        # Second scan → idempotent, still 1
        requests.post(f"{API}/warranties/_test/run-scan-now",
                        headers=admin_h, timeout=25)
        r2_count = dbc.warranty_reminders_sent.count_documents(
            {"tenant_id": t["id"], "contract_id": c["id"], "stage": 7})
        assert r2_count == 1, f"scan not idempotent: got {r2_count}"
    finally:
        dbc.warranty_reminders_sent.delete_many({"contract_id": c["id"]})
        dbc.warranty_contracts.delete_one({"id": c["id"]})


def test_tech_and_customer_forbidden_from_admin_endpoints(tech_h, customer_h):
    for h in (tech_h, customer_h):
        r = requests.get(f"{API}/warranties/contracts", headers=h,
                           timeout=10)
        assert r.status_code == 403
        r2 = requests.get(f"{API}/warranties/claims", headers=h, timeout=10)
        assert r2.status_code == 403
