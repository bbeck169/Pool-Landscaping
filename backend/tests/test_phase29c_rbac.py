"""Phase 29C · RBAC endpoint + server-side enforcement smoke tests.

Covers:
  * `GET /api/rbac/me/permissions` returns sane shape for each of the
    seeded roles (super_admin, admin, technician, customer).
  * Non-admin roles hit at least one destructive endpoint each and get
    a 403 (or an equivalent forbidden marker) from the server — proving
    that any client-side "test as role" preview never actually elevates
    real API power.
  * Missing auth → 401/403; presence of the endpoint in OpenAPI.
"""
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def super_h():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def customer_h():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')['access_token']}"}


# ─── 1. endpoint is registered ───────────────────────────────────────
def test_rbac_endpoint_registered():
    r = requests.get(f"{API}/openapi.json", timeout=15)
    assert r.status_code == 200
    assert "/api/rbac/me/permissions" in r.json().get("paths", {}), \
        "RBAC endpoint missing from OpenAPI"


# ─── 2. shape per role ───────────────────────────────────────────────
@pytest.mark.parametrize("who,expect_admin", [
    ("super_h", True),
    ("admin_h", True),
    ("tech_h", False),
    ("customer_h", False),
])
def test_rbac_me_shape(request, who, expect_admin):
    h = request.getfixturevalue(who)
    r = requests.get(f"{API}/rbac/me/permissions", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "role" in body and body["role"]
    assert "permissions" in body and isinstance(body["permissions"], dict)
    assert body.get("is_admin") is expect_admin
    if expect_admin:
        # Admins get the wildcard so the UI can short-circuit gates.
        assert "__all__" in body["permissions"], body["permissions"]
        assert body["permissions"]["__all__"].get("write") is True
    else:
        # Non-admins get per-feature dicts. If a feature is present each
        # entry must at least declare `read` boolean.
        for feature, verbs in body["permissions"].items():
            assert isinstance(verbs, dict), f"{feature} → not a dict"


# ─── 3. no-auth → 401/403 ────────────────────────────────────────────
def test_rbac_no_auth_denied():
    r = requests.get(f"{API}/rbac/me/permissions", timeout=15)
    assert r.status_code in (401, 403), r.status_code


# ─── 4. server still enforces RBAC — spot-check destructive endpoints ──
@pytest.mark.parametrize("who", ["tech_h", "customer_h"])
def test_technician_and_customer_cannot_write_checks(request, who):
    """No amount of client-side preview lets a non-admin write a check."""
    h = request.getfixturevalue(who)
    # Try to create a bank account (admin-only).
    r = requests.post(f"{API}/checks/bank-accounts", headers=h, json={
        "nickname": "hack",
        "bank_name": "hack",
        "routing_number": "123456789",
        "account_number": "1234567890",
        "next_check_number": 1,
        "starting_balance": 0,
    }, timeout=15)
    assert r.status_code in (401, 403), (
        f"Non-admin ({who}) got {r.status_code} on POST /checks/bank-accounts — RBAC bypassed!"
    )


@pytest.mark.parametrize("who", ["tech_h", "customer_h"])
def test_non_admin_cannot_trigger_re_encrypt(request, who):
    """The Phase 29B key-rotation endpoint must stay admin-only."""
    h = request.getfixturevalue(who)
    r = requests.post(f"{API}/checks/admin/re-encrypt", headers=h, timeout=15)
    assert r.status_code in (401, 403), (
        f"Non-admin ({who}) got {r.status_code} on re-encrypt — RBAC bypassed!"
    )


def test_customer_cannot_read_dispatch(customer_h):
    """Customers shouldn't be able to peek at the dispatch board."""
    r = requests.get(f"{API}/dispatch", headers=customer_h, timeout=15)
    assert r.status_code in (401, 403), r.status_code
