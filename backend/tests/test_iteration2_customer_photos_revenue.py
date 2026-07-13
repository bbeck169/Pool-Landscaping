"""Iteration 2 backend tests — customer role, job photos, revenue trend.

Covers:
- POST /api/auth/signup (public customer self-signup)
- POST /api/customers/{id}/create-login (admin-only)
- Customer scoping for jobs, quotes, invoices, dashboard
- POST /api/jobs/{id}/photos + DELETE /api/jobs/{id}/photos/{pid}
- Revenue trend (6 buckets) on admin dashboard
"""
import os
import uuid
import time
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
    return _login(CUSTOMER)  # {access_token, user}


# --------------- Signup ---------------
class TestSignup:
    def test_public_signup_creates_customer(self):
        email = f"test_signup_{uuid.uuid4().hex[:8]}@example.com"
        payload = {"name": "TEST Signup User", "email": email, "password": "password123",
                   "phone": "555-1234", "address": "1 Test Ln"}
        r = requests.post(f"{API}/auth/signup", json=payload, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["token_type"] == "bearer"
        assert data["access_token"]
        assert data["user"]["role"] == "customer"
        assert data["user"]["email"] == email
        assert data["user"]["customer_id"]

        # verify token works and /auth/me returns customer role
        me = requests.get(f"{API}/auth/me", headers=_h(data["access_token"]), timeout=30)
        assert me.status_code == 200
        assert me.json()["role"] == "customer"

    def test_signup_duplicate_email(self):
        # existing seeded customer email
        payload = {"name": "Dup", "email": "customer@aquaterra.com", "password": "password123"}
        r = requests.post(f"{API}/auth/signup", json=payload, timeout=30)
        assert r.status_code == 400


# --------------- Admin create-login for customer ---------------
class TestCreateLogin:
    def test_admin_creates_customer_login(self, admin_token):
        # Create a fresh customer without login
        cust_email_orig = f"nolog_{uuid.uuid4().hex[:6]}@example.com"
        r = requests.post(f"{API}/customers", headers=_h(admin_token),
                          json={"name": "TEST_NoLoginCust", "email": cust_email_orig}, timeout=30)
        assert r.status_code == 200
        cid = r.json()["id"]

        # Create login as admin
        new_login_email = f"login_{uuid.uuid4().hex[:6]}@example.com"
        r = requests.post(f"{API}/customers/{cid}/create-login", headers=_h(admin_token),
                          json={"email": new_login_email, "password": "password123"}, timeout=30)
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # New user can log in
        r = requests.post(f"{API}/auth/login",
                          json={"email": new_login_email, "password": "password123"}, timeout=30)
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "customer"
        assert r.json()["user"]["customer_id"] == cid

        # Cleanup
        requests.delete(f"{API}/customers/{cid}", headers=_h(admin_token), timeout=30)

    def test_create_login_non_admin_forbidden(self, tech_token, admin_token):
        # Need a valid customer id
        customers = requests.get(f"{API}/customers", headers=_h(admin_token), timeout=30).json()
        cid = customers[0]["id"]
        r = requests.post(f"{API}/customers/{cid}/create-login", headers=_h(tech_token),
                          json={"email": "x@y.com", "password": "password123"}, timeout=30)
        assert r.status_code == 403

    def test_create_login_duplicate_email(self, admin_token):
        customers = requests.get(f"{API}/customers", headers=_h(admin_token), timeout=30).json()
        cid = customers[0]["id"]
        # admin@aquaterra.com already exists
        r = requests.post(f"{API}/customers/{cid}/create-login", headers=_h(admin_token),
                          json={"email": "admin@aquaterra.com", "password": "password123"}, timeout=30)
        assert r.status_code == 400


# --------------- Customer scoping ---------------
class TestCustomerScoping:
    def test_customer_jobs_scoped(self, customer_auth):
        tok = customer_auth["access_token"]
        cid = customer_auth["user"]["customer_id"]
        r = requests.get(f"{API}/jobs", headers=_h(tok), timeout=30)
        assert r.status_code == 200
        jobs = r.json()
        assert len(jobs) >= 1
        for j in jobs:
            assert j["customer_id"] == cid

    def test_customer_cannot_read_other_job(self, customer_auth, admin_token):
        tok = customer_auth["access_token"]
        cid = customer_auth["user"]["customer_id"]
        # Find a job belonging to a different customer via admin
        all_jobs = requests.get(f"{API}/jobs", headers=_h(admin_token), timeout=30).json()
        other = next((j for j in all_jobs if j["customer_id"] != cid), None)
        assert other, "expected at least one other-customer job in seed"
        r = requests.get(f"{API}/jobs/{other['id']}", headers=_h(tok), timeout=30)
        assert r.status_code == 403

    def test_customer_quotes_scoped(self, customer_auth):
        tok = customer_auth["access_token"]
        cid = customer_auth["user"]["customer_id"]
        r = requests.get(f"{API}/quotes", headers=_h(tok), timeout=30)
        assert r.status_code == 200
        for q in r.json():
            assert q["customer_id"] == cid

    def test_technician_still_forbidden_on_quotes(self, tech_token):
        r = requests.get(f"{API}/quotes", headers=_h(tech_token), timeout=30)
        assert r.status_code == 403

    def test_customer_get_own_invoice_and_checkout(self, customer_auth, admin_token):
        tok = customer_auth["access_token"]
        cid = customer_auth["user"]["customer_id"]

        # Create an unpaid invoice for the customer as admin
        r = requests.post(f"{API}/quotes", headers=_h(admin_token), json={
            "customer_id": cid, "title": "TEST_Cust_Invoice", "doc_type": "invoice",
            "tax_rate": 0.0,
            "line_items": [{"description": "TEST", "quantity": 1, "unit_price": 100.0}],
        }, timeout=30)
        assert r.status_code == 200
        inv_id = r.json()["id"]

        # Customer GET own invoice
        r = requests.get(f"{API}/quotes/{inv_id}", headers=_h(tok), timeout=30)
        assert r.status_code == 200
        assert r.json()["customer_id"] == cid

        # Customer CANNOT mark it paid directly (manual /pay is admin-only now)
        r = requests.post(f"{API}/quotes/{inv_id}/pay", headers=_h(tok), timeout=30)
        assert r.status_code == 403

        # Customer CAN start a real Stripe Checkout session for own invoice
        r = requests.post(f"{API}/payments/checkout/{inv_id}", headers=_h(tok),
                          json={"success_url": "https://example.com/ok",
                                "cancel_url": "https://example.com/cancel"}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("url", "").startswith("https://")
        assert body.get("session_id")

        # Admin records a manual/offline payment -> paid
        r = requests.post(f"{API}/quotes/{inv_id}/pay", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200
        assert r.json()["payment_status"] == "paid"

    def test_customer_cannot_pay_other_invoice(self, customer_auth, admin_token):
        tok = customer_auth["access_token"]
        cid = customer_auth["user"]["customer_id"]
        # Find an invoice belonging to a different customer
        all_q = requests.get(f"{API}/quotes", headers=_h(admin_token), timeout=30).json()
        other = next((q for q in all_q if q["customer_id"] != cid and q["doc_type"] == "invoice"), None)
        assert other, "expected an invoice for another customer in seed"
        # manual /pay is admin-only -> 403 for customer
        r = requests.post(f"{API}/quotes/{other['id']}/pay", headers=_h(tok), timeout=30)
        assert r.status_code == 403
        # GET should be 403
        r = requests.get(f"{API}/quotes/{other['id']}", headers=_h(tok), timeout=30)
        assert r.status_code == 403
        # Stripe checkout for another customer's invoice -> 403
        r = requests.post(f"{API}/payments/checkout/{other['id']}", headers=_h(tok),
                          json={"success_url": "https://example.com/ok",
                                "cancel_url": "https://example.com/cancel"}, timeout=30)
        assert r.status_code == 403

    def test_customer_dashboard_shape(self, customer_auth):
        tok = customer_auth["access_token"]
        r = requests.get(f"{API}/dashboard", headers=_h(tok), timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["role"] == "customer"
        for k in ["active_jobs", "completed_jobs", "outstanding", "unpaid_invoices"]:
            assert k in d
        assert isinstance(d["outstanding"], (int, float))


# --------------- Job photos ---------------
# 1x1 transparent PNG base64
TINY_PNG = ("data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")


class TestJobPhotos:
    def test_admin_add_and_delete_photo(self, admin_token):
        # Find any job
        jobs = requests.get(f"{API}/jobs", headers=_h(admin_token), timeout=30).json()
        jid = jobs[0]["id"]
        r = requests.post(f"{API}/jobs/{jid}/photos", headers=_h(admin_token),
                          json={"data": TINY_PNG, "label": "before"}, timeout=30)
        assert r.status_code == 200
        job = r.json()
        photos = job.get("photos", [])
        assert any(p.get("label") == "before" for p in photos)
        added = next(p for p in photos if p.get("label") == "before")
        pid = added["id"]

        # Delete
        r = requests.delete(f"{API}/jobs/{jid}/photos/{pid}", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200
        # Ensure removed
        assert not any(p["id"] == pid for p in r.json().get("photos", []))

    def test_technician_can_add_photo_for_own_job(self, tech_token, admin_token):
        me = requests.get(f"{API}/auth/me", headers=_h(tech_token), timeout=30).json()
        tid = me["technician_id"]
        my_jobs = [j for j in requests.get(f"{API}/jobs", headers=_h(tech_token), timeout=30).json()
                   if j["technician_id"] == tid]
        assert my_jobs, "tech has no jobs"
        jid = my_jobs[0]["id"]
        r = requests.post(f"{API}/jobs/{jid}/photos", headers=_h(tech_token),
                          json={"data": TINY_PNG, "label": "after"}, timeout=30)
        assert r.status_code == 200
        job = r.json()
        pid = next(p["id"] for p in job["photos"] if p["label"] == "after")
        # cleanup
        requests.delete(f"{API}/jobs/{jid}/photos/{pid}", headers=_h(admin_token), timeout=30)

    def test_customer_cannot_add_photo(self, customer_auth):
        tok = customer_auth["access_token"]
        # Get a job scoped to customer
        jobs = requests.get(f"{API}/jobs", headers=_h(tok), timeout=30).json()
        assert jobs
        jid = jobs[0]["id"]
        r = requests.post(f"{API}/jobs/{jid}/photos", headers=_h(tok),
                          json={"data": TINY_PNG, "label": "before"}, timeout=30)
        assert r.status_code == 403


# --------------- Revenue trend ---------------
class TestRevenueTrend:
    def test_admin_dashboard_has_revenue_series(self, admin_token):
        r = requests.get(f"{API}/dashboard", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "revenue_series" in d
        series = d["revenue_series"]
        assert isinstance(series, list)
        assert len(series) == 6, f"expected 6 buckets, got {len(series)}"
        for point in series:
            assert "label" in point and isinstance(point["label"], str)
            assert "value" in point and isinstance(point["value"], (int, float))
        # At least one non-zero value from seeded historical paid invoices
        assert any(p["value"] > 0 for p in series), "expected some paid revenue in last 6 months"
        # outstanding present
        assert "outstanding" in d
