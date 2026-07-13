"""Iteration 41 — POST /api/leads/{lid}/convert role & payload behavior.

Covers:
- Technician (and admin) can convert; customer role -> 403; no-auth -> 401/403
- Converting creates/links a customer (copies name/phone/email/address/lat/lng)
- Lead status becomes 'won' after conversion
- Converting an already-converted lead reuses the existing customer (idempotent-ish)

Note: converting a real seeded lead removes it from open-leads. To keep the seed
intact for the frontend test, this suite creates its OWN throwaway leads via
POST /api/leads (admin) and converts those. It also verifies technician auth
against a fresh lead.
"""
import os
import pytest
import requests
from pathlib import Path
from dotenv import dotenv_values

_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = (_ENV.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL", "")).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}
CUST = {"email": "customer@aquaterra.com", "password": "password123"}


def _login(sess, creds):
    r = sess.post(f"{API}/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login {creds['email']}: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok
    sess.headers.update({"Authorization": f"Bearer {tok}"})
    return sess


@pytest.fixture(scope="module")
def admin_session():
    return _login(requests.Session(), ADMIN)


@pytest.fixture(scope="module")
def tech_session():
    return _login(requests.Session(), TECH)


@pytest.fixture(scope="module")
def customer_session():
    return _login(requests.Session(), CUST)


def _make_lead(sess, name_suffix="A", phone_suffix="0001"):
    body = {
        "name": f"TEST_ConvertLead {name_suffix}",
        "email": f"test_convert_{name_suffix.lower()}@example.com",
        "phone": f"+16025550{phone_suffix}",
        "address": "1234 W Happy Valley Rd, Peoria, AZ 85383",
        "lat": 33.7150,
        "lng": -112.2456,
        "source": "d2d",
        "status": "new",
        "notes": "TEST_ lead for convert",
    }
    r = sess.post(f"{API}/leads", json=body, timeout=30)
    assert r.status_code == 200, f"create lead: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="module")
def created_lead_ids(admin_session):
    """Track lead ids created here so we can clean them up."""
    ids = []
    yield ids
    # Cleanup: delete leads + any customers created from them
    for lid in ids:
        try:
            admin_session.delete(f"{API}/leads/{lid}", timeout=15)
        except Exception:
            pass


class TestConvertAuth:
    def test_no_auth_401_or_403(self, admin_session, created_lead_ids):
        lead = _make_lead(admin_session, "NoAuth", "1001")
        created_lead_ids.append(lead["id"])
        r = requests.post(f"{API}/leads/{lead['id']}/convert", timeout=15)
        assert r.status_code in (401, 403), f"{r.status_code} {r.text}"

    def test_customer_forbidden(self, admin_session, customer_session, created_lead_ids):
        lead = _make_lead(admin_session, "Cust403", "1002")
        created_lead_ids.append(lead["id"])
        r = customer_session.post(f"{API}/leads/{lead['id']}/convert", timeout=15)
        assert r.status_code == 403, f"expected 403 for customer; got {r.status_code} {r.text}"


class TestConvertTechnician:
    def test_technician_can_convert(self, admin_session, tech_session, created_lead_ids):
        lead = _make_lead(admin_session, "TechConvert", "1003")
        created_lead_ids.append(lead["id"])
        r = tech_session.post(f"{API}/leads/{lead['id']}/convert", timeout=30)
        assert r.status_code == 200, f"tech convert: {r.status_code} {r.text}"
        cust = r.json()
        # Customer fields copied from lead
        assert cust["name"] == lead["name"]
        assert cust["phone"] == lead["phone"]
        assert cust["email"] == lead["email"]
        assert cust["address"] == lead["address"]
        assert cust["lat"] == lead["lat"]
        assert cust["lng"] == lead["lng"]
        assert "id" in cust and cust["id"]
        assert "_id" not in cust

        # Verify customer persisted via GET
        gr = admin_session.get(f"{API}/customers/{cust['id']}", timeout=15)
        assert gr.status_code == 200, f"customer GET after convert: {gr.status_code} {gr.text}"
        assert gr.json()["id"] == cust["id"]

    def test_lead_status_becomes_won(self, admin_session, tech_session, created_lead_ids):
        lead = _make_lead(admin_session, "StatusWon", "1004")
        created_lead_ids.append(lead["id"])
        r = tech_session.post(f"{API}/leads/{lead['id']}/convert", timeout=30)
        assert r.status_code == 200
        # Fetch leads list (admin) and find our lead
        lr = admin_session.get(f"{API}/leads", timeout=15)
        assert lr.status_code == 200
        match = next((x for x in lr.json() if x.get("id") == lead["id"]), None)
        assert match, "converted lead not found in /api/leads"
        assert match["status"] == "won", f"expected status=won; got {match['status']}"
        assert match.get("converted", {}).get("type") == "customer"
        assert match.get("converted", {}).get("id"), "converted.id missing"


class TestConvertAdminAndIdempotency:
    def test_admin_can_convert(self, admin_session, created_lead_ids):
        lead = _make_lead(admin_session, "AdminConvert", "1005")
        created_lead_ids.append(lead["id"])
        r = admin_session.post(f"{API}/leads/{lead['id']}/convert", timeout=30)
        assert r.status_code == 200, f"admin convert: {r.status_code} {r.text}"
        cust = r.json()
        assert cust["name"] == lead["name"]
        assert cust["address"] == lead["address"]

    def test_convert_missing_lead_404(self, tech_session):
        r = tech_session.post(f"{API}/leads/does-not-exist-xyz/convert", timeout=15)
        assert r.status_code == 404, f"{r.status_code} {r.text}"

    def test_reconvert_reuses_customer(self, admin_session, tech_session, created_lead_ids):
        lead = _make_lead(admin_session, "Reuse", "1006")
        created_lead_ids.append(lead["id"])
        r1 = tech_session.post(f"{API}/leads/{lead['id']}/convert", timeout=30)
        assert r1.status_code == 200
        cust1 = r1.json()
        # Re-convert the same lead (or a duplicate with same phone) should reuse
        r2 = tech_session.post(f"{API}/leads/{lead['id']}/convert", timeout=30)
        assert r2.status_code == 200
        cust2 = r2.json()
        assert cust1["id"] == cust2["id"], "expected same customer on repeat convert"
