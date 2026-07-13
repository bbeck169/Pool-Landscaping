"""Pool & Landscaping CRM — comprehensive API tests.

Covers: auth, dashboard (admin + tech), customers CRUD, technicians,
jobs (RBAC + status transitions), quotes/invoices (create, pay MOCKED).
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
if not BASE_URL:
    # Fallback to frontend/.env
    from pathlib import Path
    envf = Path("/app/frontend/.env").read_text().splitlines()
    for ln in envf:
        if ln.startswith("EXPO_PUBLIC_BACKEND_URL="):
            BASE_URL = ln.split("=", 1)[1].strip().strip('"')
            break
BASE_URL = BASE_URL.rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}


# --------------- Fixtures ---------------
@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{API}/auth/login", json=ADMIN, timeout=30)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def tech_token():
    r = requests.post(f"{API}/auth/login", json=TECH, timeout=30)
    assert r.status_code == 200, f"tech login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# --------------- Auth ---------------
class TestAuth:
    def test_login_admin(self):
        r = requests.post(f"{API}/auth/login", json=ADMIN, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["token_type"] == "bearer"
        assert d["user"]["role"] == "admin"
        assert d["user"]["email"] == ADMIN["email"]
        assert "access_token" in d and len(d["access_token"]) > 20

    def test_login_tech(self):
        r = requests.post(f"{API}/auth/login", json=TECH, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["user"]["role"] == "technician"
        assert d["user"].get("technician_id")

    def test_login_bad_password(self):
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN["email"], "password": "wrong"}, timeout=30)
        assert r.status_code == 401

    def test_me_admin(self, admin_token):
        r = requests.get(f"{API}/auth/me", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200
        assert r.json()["role"] == "admin"

    def test_me_no_token(self):
        r = requests.get(f"{API}/auth/me", timeout=30)
        assert r.status_code in (401, 403)


# --------------- Dashboard ---------------
class TestDashboard:
    def test_admin_dashboard(self, admin_token):
        r = requests.get(f"{API}/dashboard", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["role"] == "admin"
        for k in ["revenue", "outstanding", "active_jobs", "pending_jobs",
                  "completed_jobs", "total_customers", "total_technicians", "recent_jobs"]:
            assert k in d, f"missing {k}"
        assert isinstance(d["revenue"], (int, float))
        assert isinstance(d["recent_jobs"], list)

    def test_tech_dashboard(self, tech_token):
        r = requests.get(f"{API}/dashboard", headers=_h(tech_token), timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["role"] == "technician"
        for k in ["pending_jobs", "active_jobs", "completed_jobs", "upcoming_jobs"]:
            assert k in d


# --------------- RBAC ---------------
class TestRBAC:
    def test_tech_cannot_see_quotes(self, tech_token):
        r = requests.get(f"{API}/quotes", headers=_h(tech_token), timeout=30)
        assert r.status_code == 403

    def test_tech_cannot_create_customer(self, tech_token):
        r = requests.post(f"{API}/customers", headers=_h(tech_token),
                          json={"name": "TEST_should_fail"}, timeout=30)
        assert r.status_code == 403

    def test_tech_jobs_scoped(self, tech_token, admin_token):
        # tech user id from /auth/me
        me = requests.get(f"{API}/auth/me", headers=_h(tech_token), timeout=30).json()
        tid = me["technician_id"]
        r = requests.get(f"{API}/jobs", headers=_h(tech_token), timeout=30)
        assert r.status_code == 200
        for job in r.json():
            assert job["technician_id"] == tid


# --------------- Customers CRUD ---------------
class TestCustomers:
    created_id = None

    def test_list(self, admin_token):
        r = requests.get(f"{API}/customers", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert len(r.json()) >= 4  # seeded

    def test_create(self, admin_token):
        payload = {"name": "TEST_Customer_Alpha", "email": "test_a@example.com",
                   "phone": "555-0000", "address": "1 Test St", "notes": "test"}
        r = requests.post(f"{API}/customers", headers=_h(admin_token), json=payload, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["name"] == payload["name"]
        assert d["id"]
        TestCustomers.created_id = d["id"]

    def test_get_by_id_with_jobs(self, admin_token):
        assert TestCustomers.created_id
        r = requests.get(f"{API}/customers/{TestCustomers.created_id}", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["name"] == "TEST_Customer_Alpha"
        assert isinstance(d.get("jobs"), list)

    def test_update(self, admin_token):
        assert TestCustomers.created_id
        r = requests.put(f"{API}/customers/{TestCustomers.created_id}",
                         headers=_h(admin_token),
                         json={"name": "TEST_Customer_Alpha_Updated", "email": "x@y.z",
                               "phone": "", "address": "", "notes": ""}, timeout=30)
        assert r.status_code == 200
        assert r.json()["name"] == "TEST_Customer_Alpha_Updated"

    def test_zzz_cleanup(self, admin_token):
        if TestCustomers.created_id:
            r = requests.delete(f"{API}/customers/{TestCustomers.created_id}", headers=_h(admin_token), timeout=30)
            assert r.status_code == 200


# --------------- Technicians ---------------
class TestTechnicians:
    def test_list_with_active_jobs(self, admin_token):
        r = requests.get(f"{API}/technicians", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200
        techs = r.json()
        assert len(techs) >= 2
        for t in techs:
            assert "active_jobs" in t
            assert isinstance(t["active_jobs"], int)

    def test_get_by_id_with_jobs(self, admin_token):
        techs = requests.get(f"{API}/technicians", headers=_h(admin_token), timeout=30).json()
        tid = techs[0]["id"]
        r = requests.get(f"{API}/technicians/{tid}", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json().get("jobs"), list)


# --------------- Jobs ---------------
class TestJobs:
    created_id = None

    def test_admin_list(self, admin_token):
        r = requests.get(f"{API}/jobs", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200
        assert len(r.json()) >= 5

    def test_status_filter(self, admin_token):
        r = requests.get(f"{API}/jobs?status=completed", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200
        for j in r.json():
            assert j["status"] == "completed"

    def test_create_job(self, admin_token):
        customers = requests.get(f"{API}/customers", headers=_h(admin_token), timeout=30).json()
        techs = requests.get(f"{API}/technicians", headers=_h(admin_token), timeout=30).json()
        payload = {"title": "TEST_Job", "customer_id": customers[0]["id"],
                   "technician_id": techs[0]["id"], "service_type": "Pool Cleaning",
                   "scheduled_date": "2026-02-01", "price": 150.0, "status": "pending"}
        r = requests.post(f"{API}/jobs", headers=_h(admin_token), json=payload, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["customer_name"] == customers[0]["name"]
        assert d["technician_name"] == techs[0]["name"]
        TestJobs.created_id = d["id"]

    def test_status_transitions(self, admin_token):
        assert TestJobs.created_id
        # pending -> active
        r = requests.put(f"{API}/jobs/{TestJobs.created_id}", headers=_h(admin_token),
                         json={"status": "active"}, timeout=30)
        assert r.status_code == 200
        assert r.json()["status"] == "active"
        # active -> completed
        r = requests.put(f"{API}/jobs/{TestJobs.created_id}", headers=_h(admin_token),
                         json={"status": "completed"}, timeout=30)
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

    def test_assign_tech(self, admin_token):
        assert TestJobs.created_id
        techs = requests.get(f"{API}/technicians", headers=_h(admin_token), timeout=30).json()
        new_tid = techs[1]["id"]
        r = requests.put(f"{API}/jobs/{TestJobs.created_id}", headers=_h(admin_token),
                         json={"technician_id": new_tid}, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["technician_id"] == new_tid
        assert d["technician_name"] == techs[1]["name"]

    def test_tech_cannot_access_others_job(self, tech_token, admin_token):
        # Assigned to tech2 in previous test — mike shouldn't see it
        assert TestJobs.created_id
        r = requests.get(f"{API}/jobs/{TestJobs.created_id}", headers=_h(tech_token), timeout=30)
        assert r.status_code == 403


# --------------- Quotes / Invoices ---------------
class TestQuotes:
    quote_id = None
    invoice_id = None

    def test_list_all(self, admin_token):
        r = requests.get(f"{API}/quotes", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200
        assert len(r.json()) >= 3

    def test_list_invoice_filter(self, admin_token):
        r = requests.get(f"{API}/quotes?doc_type=invoice", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200
        for q in r.json():
            assert q["doc_type"] == "invoice"

    def test_create_quote_with_totals(self, admin_token):
        customers = requests.get(f"{API}/customers", headers=_h(admin_token), timeout=30).json()
        payload = {
            "customer_id": customers[0]["id"],
            "title": "TEST_Quote",
            "doc_type": "quote",
            "tax_rate": 10.0,
            "line_items": [
                {"description": "Item A", "quantity": 2, "unit_price": 50.0},
                {"description": "Item B", "quantity": 1, "unit_price": 100.0},
            ],
            "notes": "",
        }
        r = requests.post(f"{API}/quotes", headers=_h(admin_token), json=payload, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["subtotal"] == 200.0
        assert d["tax"] == 20.0
        assert d["total"] == 220.0
        TestQuotes.quote_id = d["id"]

    def test_create_invoice_and_pay_mocked(self, admin_token):
        customers = requests.get(f"{API}/customers", headers=_h(admin_token), timeout=30).json()
        payload = {
            "customer_id": customers[0]["id"],
            "title": "TEST_Invoice",
            "doc_type": "invoice",
            "tax_rate": 0.0,
            "line_items": [{"description": "Service", "quantity": 1, "unit_price": 300.0}],
        }
        r = requests.post(f"{API}/quotes", headers=_h(admin_token), json=payload, timeout=30)
        assert r.status_code == 200
        inv = r.json()
        TestQuotes.invoice_id = inv["id"]
        assert inv["payment_status"] == "unpaid"

        # MOCKED payment
        rp = requests.post(f"{API}/quotes/{inv['id']}/pay", headers=_h(admin_token), timeout=30)
        assert rp.status_code == 200
        paid = rp.json()
        assert paid["payment_status"] == "paid"
        assert paid["status"] == "accepted"
        assert paid.get("paid_at")

    def test_update_quote_status(self, admin_token):
        assert TestQuotes.quote_id
        r = requests.put(f"{API}/quotes/{TestQuotes.quote_id}/status?status=sent",
                         headers=_h(admin_token), timeout=30)
        assert r.status_code == 200
        assert r.json()["status"] == "sent"
