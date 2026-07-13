"""Iteration 35 — Admin impersonation ("View as customer") backend tests.

Covers:
- POST /api/admin/impersonate/{customer_id}: RBAC, 404 unknown, 400 no-login, happy path
- GET  /api/auth/me returns role=customer with is_impersonated=true under an impersonation token
- POST /api/auth/revert-impersonation: works with imp token, 403 with normal token
- Payment guardrails: /api/payments/setup-session + /api/payments/checkout/{qid}
  return 403 with impersonation token, and 200/redirect for a normal customer token
- PUT /api/customers/{id} persists new billing_address + avatar and preserves other fields
- GET /api/customers/{id} exposes payment method + billing/avatar fields
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://pool-app-mobile.preview.emergentagent.com"
API = BASE_URL.rstrip("/") + "/api"

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}
CUSTOMER = {"email": "customer@aquaterra.com", "password": "password123"}
CUSTOMER_ID = "fc1e3e5a-7b4e-4cf6-83b4-b7e5cb2f6cd6"  # Jennifer Carson


def _login(session: requests.Session, creds: dict) -> str:
    r = session.post(f"{API}/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def s():
    return requests.Session()


@pytest.fixture(scope="module")
def admin_token(s):
    return _login(s, ADMIN)


@pytest.fixture(scope="module")
def tech_token(s):
    return _login(s, TECH)


@pytest.fixture(scope="module")
def customer_token(s):
    return _login(s, CUSTOMER)


@pytest.fixture(scope="module")
def imp_token(s, admin_token):
    r = s.post(f"{API}/admin/impersonate/{CUSTOMER_ID}", headers=_h(admin_token), timeout=30)
    assert r.status_code == 200, f"impersonate failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


# ---- impersonate endpoint -------------------------------------------------

class TestImpersonateEndpoint:
    def test_admin_impersonate_returns_customer_token(self, s, admin_token):
        r = s.post(f"{API}/admin/impersonate/{CUSTOMER_ID}", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("impersonating") is True
        assert body.get("impersonator_name")
        assert "access_token" in body
        assert body["user"]["role"] == "customer"
        assert body["user"]["customer_id"] == CUSTOMER_ID

    def test_technician_cannot_impersonate(self, s, tech_token):
        r = s.post(f"{API}/admin/impersonate/{CUSTOMER_ID}", headers=_h(tech_token), timeout=30)
        assert r.status_code == 403

    def test_customer_cannot_impersonate(self, s, customer_token):
        r = s.post(f"{API}/admin/impersonate/{CUSTOMER_ID}", headers=_h(customer_token), timeout=30)
        assert r.status_code == 403

    def test_unauth_cannot_impersonate(self, s):
        r = s.post(f"{API}/admin/impersonate/{CUSTOMER_ID}", timeout=30)
        assert r.status_code in (401, 403)

    def test_unknown_customer_returns_404(self, s, admin_token):
        r = s.post(f"{API}/admin/impersonate/does-not-exist-xyz", headers=_h(admin_token), timeout=30)
        assert r.status_code == 404

    def test_customer_without_login_returns_400(self, s, admin_token):
        # Create a bare customer (no login user) then try to impersonate them
        cust = {"name": "TEST_ImpNoLogin", "email": "TEST_nologin@example.com", "phone": "", "address": ""}
        c = s.post(f"{API}/customers", headers=_h(admin_token), json=cust, timeout=30)
        assert c.status_code == 200, c.text
        cid = c.json()["id"]
        try:
            r = s.post(f"{API}/admin/impersonate/{cid}", headers=_h(admin_token), timeout=30)
            assert r.status_code == 400, r.text
        finally:
            s.delete(f"{API}/customers/{cid}", headers=_h(admin_token), timeout=30)


# ---- /auth/me + revert ---------------------------------------------------

class TestAuthMeAndRevert:
    def test_me_reports_impersonation(self, s, imp_token):
        r = s.get(f"{API}/auth/me", headers=_h(imp_token), timeout=30)
        assert r.status_code == 200, r.text
        me = r.json()
        assert me["role"] == "customer"
        assert me.get("is_impersonated") is True
        assert me.get("impersonator_id")

    def test_me_customer_normal_not_impersonated(self, s, customer_token):
        r = s.get(f"{API}/auth/me", headers=_h(customer_token), timeout=30)
        assert r.status_code == 200
        me = r.json()
        assert me["role"] == "customer"
        assert not me.get("is_impersonated")

    def test_revert_with_impersonation_token(self, s, admin_token):
        # Fresh imp token so we don't consume the module-scoped one
        r1 = s.post(f"{API}/admin/impersonate/{CUSTOMER_ID}", headers=_h(admin_token), timeout=30)
        tok = r1.json()["access_token"]
        r = s.post(f"{API}/auth/revert-impersonation", headers=_h(tok), timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user"]["role"] == "admin"
        assert body["user"]["email"] == ADMIN["email"]
        # Should be a plain admin token now (no impersonating flag)
        assert not body.get("impersonating")

    def test_revert_with_normal_token_forbidden(self, s, admin_token):
        r = s.post(f"{API}/auth/revert-impersonation", headers=_h(admin_token), timeout=30)
        assert r.status_code == 403

    def test_revert_with_customer_token_forbidden(self, s, customer_token):
        r = s.post(f"{API}/auth/revert-impersonation", headers=_h(customer_token), timeout=30)
        assert r.status_code == 403


# ---- payment guardrails --------------------------------------------------

def _unpaid_invoice_id(s: requests.Session, admin_token: str) -> str:
    r = s.get(f"{API}/payments/summary", headers=_h(admin_token), timeout=30)
    assert r.status_code == 200, r.text
    overdue = r.json().get("overdue") or []
    # Prefer one belonging to Jennifer Carson so both customer & impersonation tokens can see it
    for o in overdue:
        if o.get("customer_id") == CUSTOMER_ID:
            return o["id"]
    assert overdue, "no unpaid invoices in seed to test with"
    return overdue[0]["id"]


class TestPaymentGuardrails:
    def test_setup_session_forbidden_under_impersonation(self, s, imp_token):
        payload = {"return_url": "https://example.com/return"}
        r = s.post(f"{API}/payments/setup-session", headers=_h(imp_token), json=payload, timeout=30)
        assert r.status_code == 403, r.text

    def test_checkout_forbidden_under_impersonation(self, s, imp_token, admin_token):
        qid = _unpaid_invoice_id(s, admin_token)
        payload = {"success_url": "https://example.com/ok", "cancel_url": "https://example.com/cancel"}
        r = s.post(f"{API}/payments/checkout/{qid}", headers=_h(imp_token), json=payload, timeout=30)
        assert r.status_code == 403, r.text

    def test_setup_session_works_for_normal_customer(self, s, customer_token):
        payload = {"return_url": "https://example.com/return"}
        r = s.post(f"{API}/payments/setup-session", headers=_h(customer_token), json=payload, timeout=30)
        # 200 with Stripe url, or 502/503 only if Stripe is unreachable. Should NOT be 403.
        assert r.status_code != 403, r.text
        assert r.status_code in (200, 502, 503)

    def test_checkout_works_for_normal_customer(self, s, customer_token, admin_token):
        qid = _unpaid_invoice_id(s, admin_token)
        payload = {"success_url": "https://example.com/ok", "cancel_url": "https://example.com/cancel"}
        r = s.post(f"{API}/payments/checkout/{qid}", headers=_h(customer_token), json=payload, timeout=30)
        assert r.status_code != 403, r.text
        assert r.status_code in (200, 502, 503)


# ---- customer PUT + GET (billing_address, avatar, PM fields) -------------

class TestCustomerFields:
    def test_get_exposes_payment_method_and_extra_fields(self, s, admin_token):
        r = s.get(f"{API}/customers/{CUSTOMER_ID}", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200, r.text
        c = r.json()
        for k in ("billing_address", "avatar", "pm_brand", "pm_last4", "default_payment_method_id"):
            assert k in c, f"missing key {k} in customer GET response"

    def test_put_persists_billing_and_avatar_without_wiping(self, s, admin_token):
        # Snapshot original
        orig = s.get(f"{API}/customers/{CUSTOMER_ID}", headers=_h(admin_token), timeout=30).json()
        payload = {
            "name": orig.get("name") or "Jennifer Carson",
            "email": orig.get("email") or "",
            "phone": orig.get("phone") or "",
            "address": orig.get("address") or "",
            "billing_address": "TEST_123 Billing Way, Phoenix AZ",
            "gate_code": orig.get("gate_code") or "",
            "notes": orig.get("notes") or "",
            "avatar": "data:image/png;base64,TESTAVATARDATA==",
        }
        try:
            r = s.put(f"{API}/customers/{CUSTOMER_ID}", headers=_h(admin_token), json=payload, timeout=30)
            assert r.status_code == 200, r.text
            got = s.get(f"{API}/customers/{CUSTOMER_ID}", headers=_h(admin_token), timeout=30).json()
            assert got["billing_address"] == payload["billing_address"]
            assert got["avatar"] == payload["avatar"]
            # Preserved fields
            assert got["name"] == payload["name"]
            assert got["email"] == payload["email"]
            # Payment method fields must NOT be wiped by an admin edit
            for k in ("pm_brand", "pm_last4", "default_payment_method_id"):
                assert got.get(k) == orig.get(k), f"{k} was overwritten: {orig.get(k)} -> {got.get(k)}"
        finally:
            # Restore
            restore = {
                "name": orig.get("name") or "Jennifer Carson",
                "email": orig.get("email") or "",
                "phone": orig.get("phone") or "",
                "address": orig.get("address") or "",
                "billing_address": orig.get("billing_address") or "",
                "gate_code": orig.get("gate_code") or "",
                "notes": orig.get("notes") or "",
                "avatar": orig.get("avatar") or "",
            }
            s.put(f"{API}/customers/{CUSTOMER_ID}", headers=_h(admin_token), json=restore, timeout=30)
