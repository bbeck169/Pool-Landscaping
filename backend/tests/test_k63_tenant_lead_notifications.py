"""Phase K63 · Feb-2026 — tenant lead-notifications settings API.

Pins the contract for the per-tenant recipient CRUD:

  * GET  /api/tenants/{tid}/settings/lead-notifications
  * PUT  /api/tenants/{tid}/settings/lead-notifications

Guardrails covered:
  1. Admin + super-admin can read + write.
  2. Manager / technician / customer → 403.
  3. Cross-tenant PUT (tid mismatch) → 403.
  4. Recipient cap (10) enforced on PUT.
  5. Malformed email / phone rejected with 400.
  6. SMS/email opt-in without target field rejected with 400.
  7. Phone normalisation (US 10-digit → +1XXXXXXXXXX).
  8. Round-trip: PUT then GET returns the persisted rows with server-assigned ids.
"""
from __future__ import annotations

import pytest
import requests


API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=10)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin_headers():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def super_headers():
    return _login("super@aquaterra.com")


@pytest.fixture(scope="module")
def manager_headers():
    return _login("manager@aquaterra.com")


@pytest.fixture(scope="module")
def tech_headers():
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def tid(admin_headers) -> str:
    r = requests.get(f"{API}/tenants/current", headers=admin_headers, timeout=10)
    r.raise_for_status()
    return r.json()["id"]


# ─── Role gate ──────────────────────────────────────────────────────

def test_get_admin_ok(admin_headers, tid):
    r = requests.get(
        f"{API}/tenants/{tid}/settings/lead-notifications",
        headers=admin_headers, timeout=10,
    )
    assert r.status_code == 200
    body = r.json()
    assert "recipients" in body
    assert isinstance(body["recipients"], list)


def test_get_super_admin_ok(super_headers, tid):
    r = requests.get(
        f"{API}/tenants/{tid}/settings/lead-notifications",
        headers=super_headers, timeout=10,
    )
    assert r.status_code == 200


def test_get_manager_forbidden(manager_headers, tid):
    r = requests.get(
        f"{API}/tenants/{tid}/settings/lead-notifications",
        headers=manager_headers, timeout=10,
    )
    assert r.status_code == 403


def test_get_tech_forbidden(tech_headers, tid):
    r = requests.get(
        f"{API}/tenants/{tid}/settings/lead-notifications",
        headers=tech_headers, timeout=10,
    )
    assert r.status_code == 403


# ─── Cross-tenant scoping ───────────────────────────────────────────

def test_put_tid_mismatch_403(admin_headers):
    r = requests.put(
        f"{API}/tenants/some-other-tid/settings/lead-notifications",
        headers=admin_headers,
        json={"recipients": []}, timeout=10,
    )
    assert r.status_code == 403


# ─── Validation ─────────────────────────────────────────────────────

def test_put_recipient_cap_enforced(admin_headers, tid):
    over = [{
        "name": f"R{i}",
        "email": f"r{i}@example.com",
        "phone": "",
        "email_opt_in": True,
        "sms_opt_in": False,
    } for i in range(11)]
    r = requests.put(
        f"{API}/tenants/{tid}/settings/lead-notifications",
        headers=admin_headers,
        json={"recipients": over}, timeout=10,
    )
    assert r.status_code == 400
    assert "10" in (r.json().get("detail") or "").lower() or \
             "10" in (r.text or "")


def test_put_invalid_email_rejected(admin_headers, tid):
    r = requests.put(
        f"{API}/tenants/{tid}/settings/lead-notifications",
        headers=admin_headers,
        json={"recipients": [{
            "name": "Bad", "email": "not-an-email",
            "phone": "", "email_opt_in": True, "sms_opt_in": False,
        }]}, timeout=10,
    )
    assert r.status_code == 400
    assert "email" in (r.json().get("detail") or "").lower()


def test_put_invalid_phone_rejected(admin_headers, tid):
    r = requests.put(
        f"{API}/tenants/{tid}/settings/lead-notifications",
        headers=admin_headers,
        json={"recipients": [{
            "name": "Bad", "email": "",
            "phone": "abc123", "email_opt_in": False, "sms_opt_in": True,
        }]}, timeout=10,
    )
    assert r.status_code == 400


def test_put_sms_optin_requires_phone(admin_headers, tid):
    r = requests.put(
        f"{API}/tenants/{tid}/settings/lead-notifications",
        headers=admin_headers,
        json={"recipients": [{
            "name": "Bad", "email": "someone@example.com",
            "phone": "", "email_opt_in": False, "sms_opt_in": True,
        }]}, timeout=10,
    )
    assert r.status_code == 400


def test_put_email_optin_requires_email(admin_headers, tid):
    r = requests.put(
        f"{API}/tenants/{tid}/settings/lead-notifications",
        headers=admin_headers,
        json={"recipients": [{
            "name": "Bad", "email": "",
            "phone": "+15551234567",
            "email_opt_in": True, "sms_opt_in": False,
        }]}, timeout=10,
    )
    assert r.status_code == 400


# ─── Happy path — round-trip + phone normalisation ─────────────────

def test_put_then_get_roundtrip_and_phone_normalization(admin_headers, tid):
    # Snapshot existing so we can restore afterwards + not stomp on
    # any live seed the tenant already has.
    existing = requests.get(
        f"{API}/tenants/{tid}/settings/lead-notifications",
        headers=admin_headers, timeout=10,
    ).json().get("recipients", [])
    try:
        put_body = {"recipients": [{
            "name": "K63 Test",
            "email": "K63.Test@Example.COM",
            "phone": "602-887-4400",  # legacy US format → +16028874400
            "email_opt_in": True,
            "sms_opt_in": True,
        }]}
        r = requests.put(
            f"{API}/tenants/{tid}/settings/lead-notifications",
            headers=admin_headers, json=put_body, timeout=10,
        )
        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload["ok"] is True
        rec = payload["recipients"][0]
        assert rec["email"] == "k63.test@example.com"
        assert rec["phone"] == "+16028874400"
        assert rec["id"], "server must assign an id"

        # GET returns the same shape.
        g = requests.get(
            f"{API}/tenants/{tid}/settings/lead-notifications",
            headers=admin_headers, timeout=10,
        ).json()
        assert any(
            r2.get("email") == "k63.test@example.com"
            and r2.get("phone") == "+16028874400"
            for r2 in g["recipients"]
        )
    finally:
        # Restore.
        requests.put(
            f"{API}/tenants/{tid}/settings/lead-notifications",
            headers=admin_headers,
            json={"recipients": existing}, timeout=10,
        )
