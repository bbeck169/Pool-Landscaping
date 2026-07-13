"""Iteration 7 — Phase 4: Auto Billing (recurring plans) + Equipment Repair (tickets).

Covers:
- GET /api/billing-plans (admin-only, sorted by next_run)
- POST /api/billing-plans (customer_name resolved, next_run defaulted)
- PUT /api/billing-plans/{id} (toggle active, update fields)
- POST /api/billing-plans/{id}/run (creates unpaid invoice quote, advances next_run)
- GET /api/repairs (admin-only, optional ?status= filter)
- POST /api/repairs (customer_name + technician_name resolved)
- PUT /api/repairs/{id} (status change; technician assignment resolves technician_name)
- RBAC: 403 for technician + customer on /billing-plans, .../run, /repairs
"""
import os
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be set"

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}
CUST = {"email": "customer@aquaterra.com", "password": "password123"}

FREQ_DAYS = {"weekly": 7, "monthly": 30, "quarterly": 90}


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    body = r.json()
    return body["access_token"], body["user"]


@pytest.fixture(scope="module")
def admin_headers():
    tok, _ = _login(ADMIN)
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def tech_headers():
    tok, _ = _login(TECH)
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def customer_headers():
    tok, _ = _login(CUST)
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def any_customer(admin_headers):
    r = requests.get(f"{BASE_URL}/api/customers", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    lst = r.json()
    assert lst, "need at least one customer for tests"
    return lst[0]


@pytest.fixture(scope="module")
def any_technician(admin_headers):
    r = requests.get(f"{BASE_URL}/api/technicians", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    lst = r.json()
    assert lst, "need at least one technician for tests"
    return lst[0]


# ============================ Auto Billing ============================
class TestBillingPlansList:
    def test_list_admin_ok(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/billing-plans", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        # seeded 3 plans expected but be tolerant
        if data:
            required = {"id", "customer_id", "customer_name", "service",
                        "frequency", "amount", "next_run", "active"}
            missing = required - set(data[0].keys())
            assert not missing, f"missing fields on plan: {missing}"
            # sorted by next_run ascending (allow empty next_run gracefully)
            next_runs = [p.get("next_run") or "" for p in data]
            assert next_runs == sorted(next_runs), "plans must be sorted by next_run asc"
            # No mongo _id leak
            assert "_id" not in data[0]

    def test_list_rbac_tech_403(self, tech_headers):
        r = requests.get(f"{BASE_URL}/api/billing-plans", headers=tech_headers, timeout=15)
        assert r.status_code == 403

    def test_list_rbac_customer_403(self, customer_headers):
        r = requests.get(f"{BASE_URL}/api/billing-plans", headers=customer_headers, timeout=15)
        assert r.status_code == 403

    def test_list_no_auth_401(self):
        r = requests.get(f"{BASE_URL}/api/billing-plans", timeout=15)
        assert r.status_code in (401, 403)


class TestBillingPlanCreate:
    def test_create_resolves_customer_and_defaults_next_run(self, admin_headers, any_customer):
        payload = {
            "customer_id": any_customer["id"],
            "service": "TEST_Iter7 Monthly Cleaning",
            "frequency": "monthly",
            "amount": 199.99,
            "active": True,
        }
        r = requests.post(f"{BASE_URL}/api/billing-plans", headers=admin_headers, json=payload, timeout=15)
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["customer_name"] == any_customer["name"]
        assert p["service"] == payload["service"]
        assert p["frequency"] == "monthly"
        assert p["amount"] == 199.99
        assert p["active"] is True
        assert p.get("next_run"), "next_run should be defaulted when not provided"
        # next_run should be a valid ISO date
        datetime.fromisoformat(p["next_run"])
        assert "_id" not in p
        # persistence check
        lst = requests.get(f"{BASE_URL}/api/billing-plans", headers=admin_headers, timeout=15).json()
        assert any(x["id"] == p["id"] for x in lst)
        # stash for later tests
        pytest._iter7_plan_id = p["id"]
        pytest._iter7_plan_next_run = p["next_run"]

    def test_create_bad_customer_400(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/billing-plans", headers=admin_headers,
                          json={"customer_id": "nonexistent", "amount": 10}, timeout=15)
        assert r.status_code == 400

    def test_create_rbac_tech_403(self, tech_headers, any_customer):
        r = requests.post(f"{BASE_URL}/api/billing-plans", headers=tech_headers,
                          json={"customer_id": any_customer["id"], "amount": 10}, timeout=15)
        assert r.status_code == 403

    def test_create_rbac_customer_403(self, customer_headers, any_customer):
        r = requests.post(f"{BASE_URL}/api/billing-plans", headers=customer_headers,
                          json={"customer_id": any_customer["id"], "amount": 10}, timeout=15)
        assert r.status_code == 403


class TestBillingPlanUpdate:
    def test_toggle_active_and_update_amount(self, admin_headers):
        pid = getattr(pytest, "_iter7_plan_id", None)
        assert pid, "plan must be created first"
        r = requests.put(f"{BASE_URL}/api/billing-plans/{pid}", headers=admin_headers,
                         json={"active": False, "amount": 249.5}, timeout=15)
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["active"] is False
        assert p["amount"] == 249.5
        # toggle back on
        r2 = requests.put(f"{BASE_URL}/api/billing-plans/{pid}", headers=admin_headers,
                          json={"active": True}, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["active"] is True

    def test_update_rbac_tech_403(self, tech_headers):
        pid = getattr(pytest, "_iter7_plan_id", "x")
        r = requests.put(f"{BASE_URL}/api/billing-plans/{pid}", headers=tech_headers,
                        json={"active": False}, timeout=15)
        assert r.status_code == 403


class TestBillingPlanRun:
    def test_run_generates_unpaid_invoice_and_advances_next_run(self, admin_headers, any_customer):
        pid = getattr(pytest, "_iter7_plan_id", None)
        original_next_run = getattr(pytest, "_iter7_plan_next_run", None)
        assert pid and original_next_run, "plan must be created first"

        r = requests.post(f"{BASE_URL}/api/billing-plans/{pid}/run", headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("invoice_id")
        assert body.get("next_run")

        # next_run advanced by ~30 days (monthly)
        old_d = datetime.fromisoformat(original_next_run).date()
        new_d = datetime.fromisoformat(body["next_run"]).date()
        assert (new_d - old_d).days == FREQ_DAYS["monthly"], (
            f"expected +{FREQ_DAYS['monthly']} days but got {new_d - old_d}"
        )

        # invoice exists in customer's invoices with correct shape
        cust_id = any_customer["id"]
        cr = requests.get(f"{BASE_URL}/api/quotes?doc_type=invoice", headers=admin_headers, timeout=15)
        assert cr.status_code == 200, cr.text
        invs = [i for i in cr.json() if i.get("customer_id") == cust_id]
        inv = next((i for i in invs if i.get("id") == body["invoice_id"]), None)
        assert inv is not None, "generated invoice must show under customer invoices"
        assert inv["doc_type"] == "invoice"
        assert inv["payment_status"] == "unpaid"
        assert inv["customer_id"] == cust_id
        pytest._iter7_invoice_id = inv["id"]

    def test_unpaid_invoice_not_in_payments(self, admin_headers):
        inv_id = getattr(pytest, "_iter7_invoice_id", None)
        assert inv_id
        r = requests.get(f"{BASE_URL}/api/payments", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        pays = r.json()
        # /payments should list PAID invoices only, so our unpaid invoice must NOT be there
        assert not any(p.get("quote_id") == inv_id or p.get("id") == inv_id for p in pays), (
            "unpaid invoice should NOT appear in /payments"
        )

    def test_run_rbac_tech_403(self, tech_headers):
        pid = getattr(pytest, "_iter7_plan_id", "x")
        r = requests.post(f"{BASE_URL}/api/billing-plans/{pid}/run", headers=tech_headers, timeout=15)
        assert r.status_code == 403

    def test_run_rbac_customer_403(self, customer_headers):
        pid = getattr(pytest, "_iter7_plan_id", "x")
        r = requests.post(f"{BASE_URL}/api/billing-plans/{pid}/run", headers=customer_headers, timeout=15)
        assert r.status_code == 403

    def test_run_not_found_404(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/billing-plans/does-not-exist/run", headers=admin_headers, timeout=15)
        assert r.status_code == 404


# ============================ Equipment Repair ============================
class TestRepairsList:
    def test_list_admin_ok(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/repairs", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        if data:
            required = {"id", "customer_id", "customer_name", "equipment", "issue", "status", "created_at"}
            missing = required - set(data[0].keys())
            assert not missing, f"missing fields on repair: {missing}"
            assert "_id" not in data[0]
            # sorted by created_at desc
            ats = [r.get("created_at") or "" for r in data]
            assert ats == sorted(ats, reverse=True), "repairs must be sorted by created_at desc"

    def test_list_status_filter(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/repairs?status=open", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        for rep in r.json():
            assert rep["status"] == "open"

    def test_list_status_all_returns_everything(self, admin_headers):
        all_r = requests.get(f"{BASE_URL}/api/repairs", headers=admin_headers, timeout=15).json()
        alias = requests.get(f"{BASE_URL}/api/repairs?status=all", headers=admin_headers, timeout=15)
        assert alias.status_code == 200
        assert len(alias.json()) == len(all_r)

    def test_list_rbac_tech_403(self, tech_headers):
        r = requests.get(f"{BASE_URL}/api/repairs", headers=tech_headers, timeout=15)
        assert r.status_code == 403

    def test_list_rbac_customer_403(self, customer_headers):
        r = requests.get(f"{BASE_URL}/api/repairs", headers=customer_headers, timeout=15)
        assert r.status_code == 403


class TestRepairCreate:
    def test_create_resolves_customer_and_technician(self, admin_headers, any_customer, any_technician):
        payload = {
            "customer_id": any_customer["id"],
            "equipment": "Pool Pump",
            "issue": "TEST_Iter7 Pump humming, will not prime",
            "technician_id": any_technician["id"],
            "cost": 275.0,
            "status": "open",
        }
        r = requests.post(f"{BASE_URL}/api/repairs", headers=admin_headers, json=payload, timeout=15)
        assert r.status_code == 200, r.text
        rep = r.json()
        assert rep["customer_name"] == any_customer["name"]
        assert rep["technician_name"] == any_technician["name"]
        assert rep["equipment"] == "Pool Pump"
        assert rep["status"] == "open"
        assert rep["cost"] == 275.0
        assert "_id" not in rep
        pytest._iter7_repair_id = rep["id"]

    def test_create_bad_customer_400(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/repairs", headers=admin_headers,
                          json={"customer_id": "nope", "issue": "TEST_bad"}, timeout=15)
        assert r.status_code == 400

    def test_create_without_technician_null_name(self, admin_headers, any_customer):
        r = requests.post(f"{BASE_URL}/api/repairs", headers=admin_headers, json={
            "customer_id": any_customer["id"],
            "issue": "TEST_Iter7 no tech assigned yet",
            "equipment": "Salt Cell",
        }, timeout=15)
        assert r.status_code == 200, r.text
        rep = r.json()
        assert rep["technician_id"] is None
        assert rep["technician_name"] is None
        pytest._iter7_repair_id_unassigned = rep["id"]

    def test_create_rbac_tech_403(self, tech_headers, any_customer):
        r = requests.post(f"{BASE_URL}/api/repairs", headers=tech_headers,
                          json={"customer_id": any_customer["id"], "issue": "TEST"}, timeout=15)
        assert r.status_code == 403

    def test_create_rbac_customer_403(self, customer_headers, any_customer):
        r = requests.post(f"{BASE_URL}/api/repairs", headers=customer_headers,
                          json={"customer_id": any_customer["id"], "issue": "TEST"}, timeout=15)
        assert r.status_code == 403


class TestRepairUpdate:
    def test_change_status(self, admin_headers):
        rid = getattr(pytest, "_iter7_repair_id", None)
        assert rid
        r = requests.put(f"{BASE_URL}/api/repairs/{rid}", headers=admin_headers,
                         json={"status": "diagnosing"}, timeout=15)
        assert r.status_code == 200
        assert r.json()["status"] == "diagnosing"
        # persistence via list filter
        lst = requests.get(f"{BASE_URL}/api/repairs?status=diagnosing", headers=admin_headers, timeout=15).json()
        assert any(x["id"] == rid for x in lst)

    def test_assign_technician_resolves_name(self, admin_headers, any_technician):
        rid = getattr(pytest, "_iter7_repair_id_unassigned", None)
        assert rid
        r = requests.put(f"{BASE_URL}/api/repairs/{rid}", headers=admin_headers,
                         json={"technician_id": any_technician["id"]}, timeout=15)
        assert r.status_code == 200, r.text
        rep = r.json()
        assert rep["technician_id"] == any_technician["id"]
        assert rep["technician_name"] == any_technician["name"]

    def test_update_rbac_tech_403(self, tech_headers):
        rid = getattr(pytest, "_iter7_repair_id", "x")
        r = requests.put(f"{BASE_URL}/api/repairs/{rid}", headers=tech_headers,
                         json={"status": "repaired"}, timeout=15)
        assert r.status_code == 403

    def test_update_rbac_customer_403(self, customer_headers):
        rid = getattr(pytest, "_iter7_repair_id", "x")
        r = requests.put(f"{BASE_URL}/api/repairs/{rid}", headers=customer_headers,
                         json={"status": "repaired"}, timeout=15)
        assert r.status_code == 403
