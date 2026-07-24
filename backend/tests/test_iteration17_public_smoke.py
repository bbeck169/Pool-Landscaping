"""Iteration 17 public URL smoke tests for auto-clockin + orphan-users + profile completion."""
import os
import requests
import pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://poolscape-audit.preview.emergentagent.com").rstrip("/")


def _login(email, password):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def super_token():
    # super_admin per /app/memory/test_credentials.md is super@aquaterra.com
    return _login("super@aquaterra.com", "password123")


@pytest.fixture(scope="module")
def admin_token():
    return _login("admin@aquaterra.com", "password123")


@pytest.fixture(scope="module")
def tech_token():
    return _login("mike@aquaterra.com", "password123")


@pytest.fixture(scope="module")
def customer_token():
    return _login("customer@aquaterra.com", "password123")


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_auth_me_customer_has_orphan_flag(customer_token):
    r = requests.get(f"{BASE}/api/auth/me", headers=_h(customer_token), timeout=30)
    assert r.status_code == 200
    body = r.json()
    # per review request, customer is intentionally orphaned in seed DB
    assert "customer_record_missing" in body
    print("customer_record_missing:", body.get("customer_record_missing"))


def test_auth_me_tech_has_auto_clockin(tech_token):
    r = requests.get(f"{BASE}/api/auth/me", headers=_h(tech_token), timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert "auto_clockin_enabled" in body


def test_orphan_list_super_admin(super_token):
    r = requests.get(f"{BASE}/api/admin/orphan-customer-users", headers=_h(super_token), timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    # response can be list or dict with items
    items = data if isinstance(data, list) else data.get("items", data.get("users", []))
    assert isinstance(items, list)
    print(f"orphan users returned: {len(items)}")


def test_orphan_list_admin_forbidden(admin_token):
    r = requests.get(f"{BASE}/api/admin/orphan-customer-users", headers=_h(admin_token), timeout=30)
    assert r.status_code in (401, 403), f"expected 401/403 for admin, got {r.status_code}"


def test_team_patch_auto_clockin_tech(admin_token, tech_token):
    # get mike's user id via /auth/me
    me = requests.get(f"{BASE}/api/auth/me", headers=_h(tech_token), timeout=30).json()
    uid = me["id"]
    # flip auto_clockin_enabled to True
    r = requests.patch(f"{BASE}/api/users/{uid}", headers=_h(admin_token),
                       json={"auto_clockin_enabled": True}, timeout=30)
    assert r.status_code == 200, r.text
    # verify via /auth/me for tech
    me2 = requests.get(f"{BASE}/api/auth/me", headers=_h(tech_token), timeout=30).json()
    assert me2.get("auto_clockin_enabled") is True


def test_complete_profile_customer_only_admin_forbidden(admin_token):
    r = requests.post(f"{BASE}/api/portal/complete-profile", headers=_h(admin_token),
                      json={"first_name": "x", "last_name": "y", "phone": "555", "service_address": "z"}, timeout=30)
    assert r.status_code in (401, 403), f"expected 401/403 for admin, got {r.status_code}"


def test_complete_profile_skip_endpoint(customer_token):
    r = requests.post(f"{BASE}/api/portal/complete-profile?skip=1", headers=_h(customer_token),
                      json={}, timeout=30)
    # accepts skip fire-and-forget
    assert r.status_code in (200, 202, 204), r.text
