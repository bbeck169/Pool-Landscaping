"""Iteration 3 backend tests — Customer 'Request a Service' feature.

Covers:
- POST /api/service-requests (customer-only) creates unassigned status='requested' job
- 403 for technician and admin
- Admin GET /api/jobs?status=requested returns requested jobs
- Customer GET /api/jobs shows their own requested job
- Admin GET /api/dashboard includes requested_jobs count
- Admin PUT /api/jobs/{id} status=pending approves; assign technician works
"""
import os
import uuid
import pytest
import requests
from pathlib import Path


def _load_base_url():
    url = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
    if not url:
        for ln in Path("/app/frontend/.env").read_text().splitlines():
            if ln.startswith("EXPO_PUBLIC_BACKEND_URL="):
                url = ln.split("=", 1)[1].strip().strip('"')
                break
    return (url or "").rstrip("/")


BASE_URL = _load_base_url()
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}
CUSTOMER = {"email": "customer@aquaterra.com", "password": "password123"}


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="session")
def admin_token():
    return _login(ADMIN)["access_token"]


@pytest.fixture(scope="session")
def tech_token():
    return _login(TECH)["access_token"]


@pytest.fixture(scope="session")
def customer_auth():
    return _login(CUSTOMER)


class TestServiceRequestCreate:
    def test_customer_creates_service_request(self, customer_auth):
        tok = customer_auth["access_token"]
        cid = customer_auth["user"]["customer_id"]
        payload = {
            "service_type": "Pool Cleaning",
            "title": f"TEST_Req_{uuid.uuid4().hex[:6]}",
            "scheduled_date": "2026-02-15",
            "notes": "Water is cloudy",
        }
        r = requests.post(f"{API}/service-requests", headers=_h(tok), json=payload, timeout=30)
        assert r.status_code == 200, r.text
        job = r.json()
        assert job["status"] == "requested"
        assert job["customer_id"] == cid
        assert job["customer_name"]
        assert job["technician_id"] is None
        assert job["technician_name"] is None
        assert job["price"] == 0 or job["price"] == 0.0
        assert job["service_type"] == "Pool Cleaning"
        assert job["title"] == payload["title"]
        assert "id" in job

        # Verify persistence via customer GET /jobs
        r2 = requests.get(f"{API}/jobs", headers=_h(tok), timeout=30)
        assert r2.status_code == 200
        ids = [j["id"] for j in r2.json()]
        assert job["id"] in ids

    def test_customer_default_title_when_empty(self, customer_auth):
        tok = customer_auth["access_token"]
        r = requests.post(f"{API}/service-requests", headers=_h(tok),
                          json={"service_type": "Repair", "notes": "leak"}, timeout=30)
        assert r.status_code == 200
        job = r.json()
        assert job["status"] == "requested"
        # default title format
        assert "Repair" in job["title"]

    def test_technician_cannot_create_service_request(self, tech_token):
        r = requests.post(f"{API}/service-requests", headers=_h(tech_token),
                          json={"service_type": "Pool Cleaning"}, timeout=30)
        assert r.status_code == 403

    def test_admin_cannot_create_service_request(self, admin_token):
        r = requests.post(f"{API}/service-requests", headers=_h(admin_token),
                          json={"service_type": "Pool Cleaning"}, timeout=30)
        assert r.status_code == 403


class TestServiceRequestListing:
    def test_admin_lists_requested_jobs(self, admin_token, customer_auth):
        # Ensure at least one requested job
        tok = customer_auth["access_token"]
        payload = {"service_type": "Inspection", "title": "TEST_ReqList_Admin"}
        cr = requests.post(f"{API}/service-requests", headers=_h(tok), json=payload, timeout=30)
        assert cr.status_code == 200
        new_id = cr.json()["id"]

        r = requests.get(f"{API}/jobs?status=requested", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200
        jobs = r.json()
        assert len(jobs) >= 1
        for j in jobs:
            assert j["status"] == "requested"
        ids = [j["id"] for j in jobs]
        assert new_id in ids

    def test_customer_sees_own_requested_job(self, customer_auth):
        tok = customer_auth["access_token"]
        cid = customer_auth["user"]["customer_id"]
        payload = {"service_type": "Landscaping", "title": "TEST_ReqList_Cust"}
        cr = requests.post(f"{API}/service-requests", headers=_h(tok), json=payload, timeout=30)
        assert cr.status_code == 200
        new_id = cr.json()["id"]

        r = requests.get(f"{API}/jobs?status=requested", headers=_h(tok), timeout=30)
        assert r.status_code == 200
        jobs = r.json()
        assert len(jobs) >= 1
        for j in jobs:
            assert j["customer_id"] == cid
            assert j["status"] == "requested"
        assert new_id in [j["id"] for j in jobs]


class TestDashboardRequestedCount:
    def test_admin_dashboard_has_requested_jobs(self, admin_token, customer_auth):
        # Create a request to guarantee count > 0
        tok = customer_auth["access_token"]
        requests.post(f"{API}/service-requests", headers=_h(tok),
                      json={"service_type": "Pool Cleaning", "title": "TEST_DashReq"}, timeout=30)
        r = requests.get(f"{API}/dashboard", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "requested_jobs" in d
        assert isinstance(d["requested_jobs"], int)
        assert d["requested_jobs"] >= 1


class TestApproveAndAssign:
    def test_admin_approve_moves_to_pending(self, admin_token, customer_auth):
        # Create a requested job
        tok = customer_auth["access_token"]
        cr = requests.post(f"{API}/service-requests", headers=_h(tok),
                           json={"service_type": "Pool Cleaning", "title": "TEST_Approve"}, timeout=30)
        assert cr.status_code == 200
        jid = cr.json()["id"]

        # Approve → pending
        upd = requests.put(f"{API}/jobs/{jid}", headers=_h(admin_token),
                           json={"status": "pending"}, timeout=30)
        assert upd.status_code == 200
        assert upd.json()["status"] == "pending"

        # Verify persistence
        got = requests.get(f"{API}/jobs/{jid}", headers=_h(admin_token), timeout=30)
        assert got.status_code == 200
        assert got.json()["status"] == "pending"

    def test_admin_can_assign_technician(self, admin_token, customer_auth):
        tok = customer_auth["access_token"]
        cr = requests.post(f"{API}/service-requests", headers=_h(tok),
                           json={"service_type": "Repair", "title": "TEST_Assign"}, timeout=30)
        assert cr.status_code == 200
        jid = cr.json()["id"]

        # Get a technician id
        techs = requests.get(f"{API}/technicians", headers=_h(admin_token), timeout=30).json()
        assert techs
        tid = techs[0]["id"]
        tname = techs[0]["name"]

        # Approve + assign
        upd = requests.put(f"{API}/jobs/{jid}", headers=_h(admin_token),
                           json={"status": "pending", "technician_id": tid}, timeout=30)
        assert upd.status_code == 200
        job = upd.json()
        assert job["status"] == "pending"
        assert job["technician_id"] == tid
        assert job["technician_name"] == tname


# --- Regression sanity — core prior flows still work ---
class TestRegression:
    def test_admin_dashboard_shape(self, admin_token):
        r = requests.get(f"{API}/dashboard", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200
        d = r.json()
        for k in ["revenue", "outstanding", "active_jobs", "pending_jobs",
                  "completed_jobs", "requested_jobs", "revenue_series"]:
            assert k in d
        assert len(d["revenue_series"]) == 6

    def test_technician_scoping_still_works(self, tech_token):
        r = requests.get(f"{API}/jobs", headers=_h(tech_token), timeout=30)
        assert r.status_code == 200
        me = requests.get(f"{API}/auth/me", headers=_h(tech_token), timeout=30).json()
        for j in r.json():
            assert j["technician_id"] == me["technician_id"]

    def test_technician_forbidden_on_quotes(self, tech_token):
        r = requests.get(f"{API}/quotes", headers=_h(tech_token), timeout=30)
        assert r.status_code == 403

    def test_customer_pay_via_stripe_checkout(self, admin_token, customer_auth):
        tok = customer_auth["access_token"]
        cid = customer_auth["user"]["customer_id"]
        r = requests.post(f"{API}/quotes", headers=_h(admin_token), json={
            "customer_id": cid, "title": "TEST_Iter3_Inv", "doc_type": "invoice",
            "tax_rate": 0.0,
            "line_items": [{"description": "T", "quantity": 1, "unit_price": 10.0}],
        }, timeout=30)
        assert r.status_code == 200
        inv_id = r.json()["id"]
        # Manual /pay is admin-only now
        assert requests.post(f"{API}/quotes/{inv_id}/pay", headers=_h(tok), timeout=30).status_code == 403
        # Customer starts a Stripe Checkout session instead
        chk = requests.post(f"{API}/payments/checkout/{inv_id}", headers=_h(tok),
                            json={"success_url": "https://example.com/ok",
                                  "cancel_url": "https://example.com/cancel"}, timeout=30)
        assert chk.status_code == 200, chk.text
        assert chk.json().get("session_id")
