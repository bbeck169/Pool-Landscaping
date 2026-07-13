"""Iteration 40 — D2D Open Leads endpoint.

Covers:
- GET /api/d2d/open-leads returns {count, leads:[...]} for admin/technician
- Customer gets 403, no-auth gets 401/403
- Response includes expected lead fields (id, name, address, lat, lng, phone, status)
- Leads with status won/lost are excluded
- Seeded leads (Tom Harker, Diana Cruz, Kevin Lee) are present with coordinates
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


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session(); _login(s, ADMIN); return s


@pytest.fixture(scope="module")
def tech_session():
    s = requests.Session(); _login(s, TECH); return s


@pytest.fixture(scope="module")
def customer_session():
    s = requests.Session(); _login(s, CUST); return s


class TestOpenLeadsAuth:
    def test_no_auth_401_or_403(self):
        r = requests.get(f"{API}/d2d/open-leads", timeout=15)
        assert r.status_code in (401, 403), f"{r.status_code} {r.text}"

    def test_customer_403(self, customer_session):
        r = customer_session.get(f"{API}/d2d/open-leads", timeout=15)
        assert r.status_code == 403, f"{r.status_code} {r.text}"


class TestOpenLeadsResponse:
    def test_admin_ok(self, admin_session):
        r = admin_session.get(f"{API}/d2d/open-leads", timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        data = r.json()
        assert "count" in data and "leads" in data
        assert isinstance(data["leads"], list)
        assert data["count"] == len(data["leads"])
        assert data["count"] >= 3, f"expected at least 3 open leads (Tom/Diana/Kevin); got {data['count']}"

    def test_technician_ok(self, tech_session):
        r = tech_session.get(f"{API}/d2d/open-leads", timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        data = r.json()
        assert data["count"] >= 3

    def test_lead_shape(self, admin_session):
        r = admin_session.get(f"{API}/d2d/open-leads", timeout=30)
        leads = r.json()["leads"]
        assert leads, "no leads returned"
        lead = leads[0]
        for k in ("id", "name", "address", "lat", "lng", "phone", "status", "source"):
            assert k in lead, f"missing field {k} in lead"
        # ensure MongoDB _id is stripped
        assert "_id" not in lead

    def test_seeded_leads_present(self, admin_session):
        r = admin_session.get(f"{API}/d2d/open-leads", timeout=30)
        leads = r.json()["leads"]
        names = {l.get("name", "").lower() for l in leads}
        expected = {"tom harker", "diana cruz", "kevin lee"}
        missing = expected - names
        assert not missing, f"missing seeded leads: {missing}. Got names: {names}"

    def test_seeded_leads_have_coords(self, admin_session):
        r = admin_session.get(f"{API}/d2d/open-leads", timeout=30)
        leads = r.json()["leads"]
        for expected in ("Tom Harker", "Diana Cruz", "Kevin Lee"):
            match = next((l for l in leads if l.get("name", "").lower() == expected.lower()), None)
            assert match, f"{expected} not returned"
            assert match["lat"] is not None and match["lng"] is not None, \
                f"{expected} missing coordinates: lat={match.get('lat')} lng={match.get('lng')}"
            assert match["address"], f"{expected} missing address"

    def test_excludes_won_lost(self, admin_session):
        r = admin_session.get(f"{API}/d2d/open-leads", timeout=30)
        leads = r.json()["leads"]
        for l in leads:
            assert l["status"] not in ("won", "lost"), f"lead {l['id']} has terminal status {l['status']}"
