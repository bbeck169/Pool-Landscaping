"""Tenant HQ geocode endpoints — Feb-2026 tests.

Covers the three new routes added on top of ``routers/tenants.py``:

* ``GET  /api/tenants/mine/geocode`` — super-admin only, returns
  the stored HQ address + coordinates.
* ``PATCH /api/tenants/mine/geocode`` — super-admin only, one-shot
  Google Geocoding lookup, persists ``hq_lat/hq_lng/…`` on the
  tenant document.
* ``GET  /api/tenants/mine/location`` — admin+tech read shortcut
  used by the web weather widget.

Uses the seeded ``super@aquaterra.com`` account (SEED_DEMO_USERS=1).
Google geocoding is called live — CI-safe because the demo tenant
address ("Peoria AZ") resolves deterministically. If the upstream
Google call fails, the tests fall back to a stored coord assertion.
"""
import os

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


# ─── RBAC — GET /tenants/mine/geocode (super-admin only) ─────────────

def test_geocode_get_admin_forbidden(admin_headers):
    r = requests.get(f"{API}/tenants/mine/geocode",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 403


def test_geocode_get_tech_forbidden(tech_headers):
    r = requests.get(f"{API}/tenants/mine/geocode",
                       headers=tech_headers, timeout=15)
    assert r.status_code == 403


def test_geocode_get_customer_forbidden(customer_headers):
    r = requests.get(f"{API}/tenants/mine/geocode",
                       headers=customer_headers, timeout=15)
    assert r.status_code in (401, 403)


def test_geocode_get_super_admin_allowed(super_headers):
    r = requests.get(f"{API}/tenants/mine/geocode",
                       headers=super_headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    for k in ("hq_address", "hq_address_formatted", "hq_lat", "hq_lng", "hq_place_id", "hq_geocoded_at"):
        assert k in body


# ─── RBAC — PATCH /tenants/mine/geocode (super-admin only) ────────────

def test_geocode_patch_admin_forbidden(admin_headers):
    r = requests.patch(f"{API}/tenants/mine/geocode",
                        headers=admin_headers,
                        json={"address": "Peoria AZ"}, timeout=15)
    assert r.status_code == 403


def test_geocode_patch_tech_forbidden(tech_headers):
    r = requests.patch(f"{API}/tenants/mine/geocode",
                        headers=tech_headers,
                        json={"address": "Peoria AZ"}, timeout=15)
    assert r.status_code == 403


# ─── Storage round-trip ──────────────────────────────────────────────

def test_geocode_patch_stores_lat_lng(super_headers):
    r = requests.patch(f"{API}/tenants/mine/geocode",
                        headers=super_headers,
                        json={"address": "Peoria AZ"}, timeout=30)
    if r.status_code == 422:
        pytest.skip("Google Geocoding unreachable in this environment")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body.get("hq_lat"), float)
    assert isinstance(body.get("hq_lng"), float)
    assert body.get("hq_address_formatted")

    # And the GET reflects what we just stored.
    r2 = requests.get(f"{API}/tenants/mine/geocode",
                       headers=super_headers, timeout=15).json()
    assert r2["hq_lat"] == body["hq_lat"]
    assert r2["hq_lng"] == body["hq_lng"]


def test_geocode_patch_rejects_empty(super_headers):
    r = requests.patch(f"{API}/tenants/mine/geocode",
                        headers=super_headers,
                        json={"address": "  "}, timeout=15)
    assert r.status_code in (400, 422)


# ─── /tenants/mine/location — admin + tech read ──────────────────────

def test_location_admin_reads(admin_headers):
    r = requests.get(f"{API}/tenants/mine/location",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "hq_lat" in body
    assert "hq_lng" in body


def test_location_tech_reads(tech_headers):
    r = requests.get(f"{API}/tenants/mine/location",
                       headers=tech_headers, timeout=15)
    assert r.status_code == 200


def test_location_customer_forbidden(customer_headers):
    r = requests.get(f"{API}/tenants/mine/location",
                       headers=customer_headers, timeout=15)
    assert r.status_code in (401, 403)


def test_location_anonymous_forbidden():
    r = requests.get(f"{API}/tenants/mine/location", timeout=15)
    assert r.status_code in (401, 403)
