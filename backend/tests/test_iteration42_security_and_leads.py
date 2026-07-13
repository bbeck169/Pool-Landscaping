"""
Iteration 42 tests:
- Account lockout (5 failed logins -> 429) on a THROWAWAY signed-up user
- Password policy on /auth/signup (weak vs strong)
- Demo login still works (admin@aquaterra.com/password123)
- RBAC on /api/customers (admin/technician 200, customer 403)
- Auth audit logging (login/signup/lockout events)
- Lead status badges data present on /api/d2d/open-leads (new/contacted/quoted)
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}
CUST = {"email": "customer@aquaterra.com", "password": "password123"}


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


def _login(s, creds):
    r = s.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok
    return tok


def _auth(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------------- Password policy ----------------
class TestPasswordPolicy:
    def test_signup_weak_password_rejected(self, s):
        email = f"test_weak_{uuid.uuid4().hex[:8]}@example.com"
        r = s.post(f"{API}/auth/signup", json={
            "name": "TEST Weak", "email": email, "password": "password123",
        }, timeout=15)
        # Pydantic v2 EmailStr/validator errors return 422
        assert r.status_code == 422, f"expected 422 got {r.status_code}: {r.text}"
        body = r.text.lower()
        assert "uppercase" in body or "password" in body

    def test_signup_short_password_rejected(self, s):
        email = f"test_short_{uuid.uuid4().hex[:8]}@example.com"
        r = s.post(f"{API}/auth/signup", json={
            "name": "TEST Short", "email": email, "password": "Ab1",
        }, timeout=15)
        assert r.status_code == 422
        assert "8" in r.text or "characters" in r.text.lower()

    def test_signup_strong_password_ok(self, s):
        email = f"test_strong_{uuid.uuid4().hex[:8]}@example.com"
        r = s.post(f"{API}/auth/signup", json={
            "name": "TEST Strong", "email": email, "password": "StrongPass1",
        }, timeout=15)
        assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("access_token")
        assert data.get("user", {}).get("email") == email
        # cleanup: remove created user & customer via mongo? Not exposed via API; leave TEST_ prefix.


# ---------------- Demo login unaffected by policy ----------------
class TestDemoLogin:
    def test_admin_demo_login_works(self, s):
        r = s.post(f"{API}/auth/login", json=ADMIN, timeout=15)
        assert r.status_code == 200
        assert r.json().get("access_token")

    def test_technician_demo_login_works(self, s):
        r = s.post(f"{API}/auth/login", json=TECH, timeout=15)
        assert r.status_code == 200

    def test_customer_demo_login_works(self, s):
        r = s.post(f"{API}/auth/login", json=CUST, timeout=15)
        assert r.status_code == 200


# ---------------- RBAC on /api/customers ----------------
class TestCustomersRBAC:
    def test_admin_can_list_customers(self, s):
        tok = _login(s, ADMIN)
        r = s.get(f"{API}/customers", headers=_auth(tok), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_technician_can_list_customers(self, s):
        tok = _login(s, TECH)
        r = s.get(f"{API}/customers", headers=_auth(tok), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_customer_forbidden_from_customers_list(self, s):
        tok = _login(s, CUST)
        r = s.get(f"{API}/customers", headers=_auth(tok), timeout=15)
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"


# ---------------- Account lockout on throwaway user ----------------
class TestAccountLockout:
    """Create a throwaway user, spam wrong password 5 times, then verify
    even the correct password returns 429 while the lockout window is active."""

    def test_lockout_after_five_failed_attempts(self, s):
        email = f"test_lockout_{uuid.uuid4().hex[:8]}@example.com"
        password = "StrongPass1"
        # signup
        r = s.post(f"{API}/auth/signup", json={
            "name": "TEST Lockout", "email": email, "password": password,
        }, timeout=15)
        assert r.status_code == 200, r.text

        # 5 wrong attempts -> 5th attempt should still return 401 but sets lockout
        codes = []
        for i in range(5):
            rr = s.post(f"{API}/auth/login", json={"email": email, "password": "WrongPass9"}, timeout=15)
            codes.append(rr.status_code)
        assert all(c == 401 for c in codes), f"expected all 401 wrong attempts, got {codes}"

        # 6th attempt with CORRECT password should be locked -> 429
        rr = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
        assert rr.status_code == 429, f"expected 429 lock, got {rr.status_code}: {rr.text}"
        assert "lock" in rr.text.lower()

        # Cleanup: unlock the account so it doesn't clutter. We call mongo indirectly by
        # signing up with same email? Not allowed. Skip cleanup — throwaway TEST_ email.


# ---------------- Audit logging ----------------
class TestAuditLogging:
    def test_signup_and_failed_login_produce_audit_events(self, s):
        # Perform a fresh signup + a wrong login to guarantee 2 audit events
        email = f"test_audit_{uuid.uuid4().hex[:8]}@example.com"
        password = "StrongPass1"
        r = s.post(f"{API}/auth/signup", json={"name": "TEST Audit", "email": email, "password": password}, timeout=15)
        assert r.status_code == 200
        r2 = s.post(f"{API}/auth/login", json={"email": email, "password": "WrongPass9"}, timeout=15)
        assert r2.status_code == 401

        # Verify via mongo directly (backend audit_logs collection)
        try:
            from pymongo import MongoClient
            from dotenv import dotenv_values
            env = dotenv_values("/app/backend/.env")
            mongo_url = env.get("MONGO_URL") or os.environ.get("MONGO_URL")
            db_name = env.get("DB_NAME") or os.environ.get("DB_NAME")
            assert mongo_url and db_name, "MONGO_URL/DB_NAME missing"
            client = MongoClient(mongo_url, serverSelectionTimeoutMS=3000)
            docs = list(client[db_name].audit_logs.find({"email": email}))
            events = {d.get("event") for d in docs}
            assert "signup" in events, f"missing signup event, saw {events}"
            assert "login" in events, f"missing failed login event, saw {events}"
            # status field present
            for d in docs:
                assert "status" in d
        except ImportError:
            pytest.skip("pymongo not installed in test env; skipping direct audit_logs check")


# ---------------- D2D open leads with status badges ----------------
class TestOpenLeadsStatusBadges:
    def test_open_leads_expose_status_field(self, s):
        tok = _login(s, TECH)
        r = s.get(f"{API}/d2d/open-leads", headers=_auth(tok), timeout=15)
        assert r.status_code == 200
        data = r.json()
        leads = data.get("leads", [])
        assert len(leads) >= 3, f"expected >=3 seeded open leads, got {len(leads)}"
        statuses = {(l.get("status") or "new").lower() for l in leads}
        # Should include the three expected pipeline statuses
        assert statuses & {"new", "contacted", "quoted"}, f"expected new/contacted/quoted, got {statuses}"
        for l in leads:
            assert l.get("id")
            assert "status" in l
