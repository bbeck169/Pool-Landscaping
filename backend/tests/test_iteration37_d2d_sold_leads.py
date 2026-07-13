"""D2D Sold Leads (Zillow via OpenWeb Ninja) — backend tests.

Covers:
- GET /api/d2d/sold-leads returns properties with lat/lng/price/date_sold
- Auth: 403 for customer role, 401/403 for no auth, works for admin & technician
- Validation: non 5-digit ZIP returns 400
- logged flag: after POST /api/d2d/knocks {zpid,...}, that property has logged=true
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
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"no token in login response: {r.json()}"
    sess.headers.update({"Authorization": f"Bearer {tok}"})
    return r.json()


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    _login(s, ADMIN)
    return s


@pytest.fixture(scope="module")
def tech_session():
    s = requests.Session()
    _login(s, TECH)
    return s


@pytest.fixture(scope="module")
def customer_session():
    s = requests.Session()
    _login(s, CUST)
    return s


@pytest.fixture(scope="module")
def anon_session():
    return requests.Session()


class TestSoldLeadsAuth:
    def test_no_auth_returns_401_or_403(self, anon_session):
        r = anon_session.get(f"{API}/d2d/sold-leads", params={"zip": "85387", "days": 30}, timeout=30)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code} {r.text}"

    def test_customer_returns_403(self, customer_session):
        r = customer_session.get(f"{API}/d2d/sold-leads", params={"zip": "85387", "days": 30}, timeout=30)
        assert r.status_code == 403, f"expected 403 for customer, got {r.status_code} {r.text}"

    def test_admin_ok(self, admin_session):
        r = admin_session.get(f"{API}/d2d/sold-leads", params={"zip": "85387", "days": 30}, timeout=60)
        assert r.status_code == 200, f"admin request failed: {r.status_code} {r.text}"

    def test_technician_ok(self, tech_session):
        r = tech_session.get(f"{API}/d2d/sold-leads", params={"zip": "85387", "days": 30}, timeout=60)
        assert r.status_code == 200, f"technician request failed: {r.status_code} {r.text}"


class TestSoldLeadsValidation:
    def test_invalid_zip_letters(self, admin_session):
        r = admin_session.get(f"{API}/d2d/sold-leads", params={"zip": "abc", "days": 30}, timeout=30)
        assert r.status_code == 400, f"expected 400 for zip=abc, got {r.status_code} {r.text}"

    def test_invalid_zip_short(self, admin_session):
        r = admin_session.get(f"{API}/d2d/sold-leads", params={"zip": "123", "days": 30}, timeout=30)
        assert r.status_code == 400

    def test_invalid_zip_long(self, admin_session):
        r = admin_session.get(f"{API}/d2d/sold-leads", params={"zip": "123456", "days": 30}, timeout=30)
        assert r.status_code == 400


class TestSoldLeadsPayload:
    def test_shape_and_count(self, admin_session):
        r = admin_session.get(f"{API}/d2d/sold-leads", params={"zip": "85387", "days": 30}, timeout=60)
        assert r.status_code == 200
        data = r.json()
        assert data.get("zip") == "85387"
        assert data.get("days") == 30
        assert isinstance(data.get("properties"), list)
        assert data.get("count") == len(data["properties"])
        assert data["count"] > 0, "expected recent sold homes in 85387 (last 30d)"

        p = data["properties"][0]
        # spot-check the normalized shape
        for key in ("zpid", "address", "lat", "lng", "price", "date_sold", "logged"):
            assert key in p, f"missing key {key} in property {p}"
        # lat/lng should be non-null (filter enforced server-side)
        assert p["lat"] is not None and p["lng"] is not None


class TestLoggedFlag:
    def test_knock_marks_property_logged(self, admin_session):
        # 1) fetch sold leads for zip
        r = admin_session.get(f"{API}/d2d/sold-leads", params={"zip": "85387", "days": 30}, timeout=60)
        assert r.status_code == 200
        props = r.json()["properties"]
        # pick a property that isn't already logged (to prove state changes)
        target = next((p for p in props if not p.get("logged")), props[0])
        zpid = target["zpid"]
        assert zpid, "no zpid on target property"

        # 2) create a knock referencing that zpid
        payload = {
            "address": target.get("address") or "TEST_ADDRESS",
            "name": "TEST_D2D_Owner",
            "phone": "",
            "disposition": "not_home",
            "notes": "TEST_ auto sold-lead knock",
            "lat": target.get("lat"),
            "lng": target.get("lng"),
            "zpid": zpid,
            "sold_price": target.get("price"),
        }
        kr = admin_session.post(f"{API}/d2d/knocks", json=payload, timeout=30)
        assert kr.status_code == 200, f"create knock failed: {kr.status_code} {kr.text}"
        knock = kr.json()
        assert knock.get("zpid") == zpid
        kid = knock["id"]

        try:
            # 3) re-fetch sold leads — the target zpid should now be logged=true
            r2 = admin_session.get(f"{API}/d2d/sold-leads", params={"zip": "85387", "days": 30}, timeout=60)
            assert r2.status_code == 200
            props2 = r2.json()["properties"]
            match = next((p for p in props2 if p.get("zpid") == zpid), None)
            assert match is not None, f"zpid {zpid} not present in refetched sold-leads"
            assert match.get("logged") is True, f"expected logged=True for zpid {zpid}, got {match}"
        finally:
            # cleanup
            admin_session.delete(f"{API}/d2d/knocks/{kid}", timeout=30)
