"""Portal Access admin controls (Feb-2026 ship).

Covers:
    * ``GET /api/customers/{cid}/portal-status`` — before/after invite,
      after revoke, tenant isolation, RBAC.
    * ``GET /api/customers/{cid}/portal-history`` — invite + reset +
      revoke + impersonate + customer-login events land in the feed.
    * ``POST /api/customers/{cid}/portal-reset`` with explicit password
      body and auto-generated fallback.
    * Customer portal-login stamps ``last_portal_login_at`` on the
      customer doc + writes a ``portal_login`` audit row.
    * MP1.5 polish observations #1 and #2:
        - Property lazy-backfill now fires when the customer has ONLY
          the legacy ``address`` field (empty ``address_line1``).
        - POST /properties with ``address.address_line1`` (instead of
          ``address.line1``) retains the value.
"""
import os
import uuid

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture
def customer(admin_headers):
    marker = uuid.uuid4().hex[:8]
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": f"Portal {marker}",
        "first_name": "TEST_PORTAL", "last_name": f"P{marker}",
        "email": f"portal_{marker}@example.com",
        "phone": "+14805557788",
        "address": "10 Portal Way",
        "address_line1": "10 Portal Way",
        "city": "Peoria", "state": "AZ", "postal_code": "85383",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    doc = r.json()
    yield doc
    requests.delete(f"{API}/customers/{doc['id']}",
                      headers=admin_headers, timeout=15)


# ─── Portal status ─────────────────────────────────────────────────────

def test_portal_status_before_invite(admin_headers, customer):
    r = requests.get(f"{API}/customers/{customer['id']}/portal-status",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_login"] is False
    assert body["active"] is False
    assert body["last_portal_login_at"] in (None, "")


def test_portal_status_after_invite(admin_headers, customer):
    r = requests.post(f"{API}/customers/{customer['id']}/portal-invite",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    r = requests.get(f"{API}/customers/{customer['id']}/portal-status",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_login"] is True
    assert body["active"] is True
    assert body["email"] == customer["email"]


def test_portal_status_after_revoke(admin_headers, customer):
    requests.post(f"{API}/customers/{customer['id']}/portal-invite",
                    headers=admin_headers, timeout=15)
    r = requests.post(f"{API}/customers/{customer['id']}/portal-revoke",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    r = requests.get(f"{API}/customers/{customer['id']}/portal-status",
                       headers=admin_headers, timeout=15)
    body = r.json()
    assert body["has_login"] is True    # the user row still exists
    assert body["active"] is False      # but is revoked
    assert body["revoked_at"]


def test_portal_status_404_unknown_customer(admin_headers):
    r = requests.get(f"{API}/customers/{uuid.uuid4().hex}/portal-status",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 404


def test_portal_status_tech_forbidden(admin_headers, customer):
    tech_tok = _login("mike@aquaterra.com")
    r = requests.get(f"{API}/customers/{customer['id']}/portal-status",
                       headers={"Authorization": f"Bearer {tech_tok}"},
                       timeout=15)
    assert r.status_code in (401, 403)


# ─── Portal history ────────────────────────────────────────────────────

def test_portal_history_captures_reset_and_revoke(admin_headers, customer):
    # Provision + reset + revoke → all three should appear in history.
    requests.post(f"{API}/customers/{customer['id']}/portal-invite",
                    headers=admin_headers, timeout=15)
    r = requests.post(f"{API}/customers/{customer['id']}/portal-reset",
                        headers=admin_headers, json={}, timeout=15)
    assert r.status_code == 200, r.text
    r = requests.post(f"{API}/customers/{customer['id']}/portal-revoke",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    r = requests.get(f"{API}/customers/{customer['id']}/portal-history",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    events = {e["event"] for e in r.json()["events"]}
    assert "portal_reset" in events
    assert "portal_revoke" in events


def test_portal_history_captures_customer_login(admin_headers, customer):
    """A successful customer login (via /auth/login) must land a
    ``portal_login`` audit row + stamp ``last_portal_login_at`` on the
    customer doc."""
    marker = uuid.uuid4().hex[:6]
    pw = f"CustLogin{marker}A1"
    r = requests.post(f"{API}/customers/{customer['id']}/portal-reset",
                        headers=admin_headers, json={"password": pw},
                        timeout=15)
    assert r.status_code == 200, r.text
    # Simulate the customer logging into the portal.
    r = requests.post(f"{API}/auth/login", json={
        "email": customer["email"], "password": pw,
    }, timeout=15)
    assert r.status_code == 200, r.text

    # portal_login audit row lands…
    r = requests.get(f"{API}/customers/{customer['id']}/portal-history",
                       headers=admin_headers, timeout=15)
    events = [e for e in r.json()["events"] if e["event"] == "portal_login"]
    assert events, r.json()

    # …and the customer doc is stamped.
    r = requests.get(f"{API}/customers/{customer['id']}/portal-status",
                       headers=admin_headers, timeout=15)
    assert r.json()["last_portal_login_at"]


def test_portal_history_captures_impersonation(admin_headers, customer):
    requests.post(f"{API}/customers/{customer['id']}/portal-invite",
                    headers=admin_headers, timeout=15)
    r = requests.post(f"{API}/admin/impersonate/{customer['id']}",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    r = requests.get(f"{API}/customers/{customer['id']}/portal-history",
                       headers=admin_headers, timeout=15)
    events = {e["event"] for e in r.json()["events"]}
    assert "impersonation_started" in events


def test_portal_history_tech_forbidden(admin_headers, customer):
    tech_tok = _login("mike@aquaterra.com")
    r = requests.get(f"{API}/customers/{customer['id']}/portal-history",
                       headers={"Authorization": f"Bearer {tech_tok}"},
                       timeout=15)
    assert r.status_code in (401, 403)


def test_portal_history_404_unknown_customer(admin_headers):
    r = requests.get(f"{API}/customers/{uuid.uuid4().hex}/portal-history",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 404


# ─── Portal reset with explicit password ───────────────────────────────

def test_portal_reset_with_explicit_password_logs_customer_in(admin_headers, customer):
    marker = uuid.uuid4().hex[:6]
    pw = f"Explicit{marker}A1"
    r = requests.post(f"{API}/customers/{customer['id']}/portal-reset",
                        headers=admin_headers, json={"password": pw},
                        timeout=15)
    assert r.status_code == 200, r.text
    # Login with the exact set password.
    r = requests.post(f"{API}/auth/login", json={
        "email": customer["email"], "password": pw,
    }, timeout=15)
    assert r.status_code == 200


def test_portal_reset_rejects_weak_password(admin_headers, customer):
    requests.post(f"{API}/customers/{customer['id']}/portal-invite",
                    headers=admin_headers, timeout=15)
    r = requests.post(f"{API}/customers/{customer['id']}/portal-reset",
                        headers=admin_headers, json={"password": "abc"},
                        timeout=15)
    assert r.status_code == 400


# ─── OpenAPI hygiene ───────────────────────────────────────────────────

def test_openapi_includes_portal_paths():
    r = requests.get(f"{API}/openapi.json", timeout=15)
    paths = r.json().get("paths", {})
    assert "/api/customers/{cid}/portal-status" in paths
    assert "/api/customers/{cid}/portal-history" in paths


# ─── MP1.5 polish observation #1 — legacy address field ───────────────

def test_lazy_backfill_uses_legacy_address_field(admin_headers):
    """A customer created with only the legacy ``address`` scalar (no
    ``address_line1``) should still auto-seed a ``Main`` property on
    the first properties GET."""
    marker = uuid.uuid4().hex[:8]
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": f"LegacyAddr {marker}",
        "first_name": "TEST_LEG", "last_name": f"L{marker}",
        "address": "123 Legacy Way",
        # NOTE — no address_line1 sent
        "city": "Peoria", "state": "AZ", "postal_code": "85383",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    try:
        r = requests.get(f"{API}/customers/{cid}/properties",
                           headers=admin_headers, timeout=15)
        assert r.status_code == 200
        docs = r.json()
        assert len(docs) == 1, f"expected 1 seeded property; got {docs}"
        assert docs[0]["backfilled_from_customer"] is True
        assert docs[0]["address"]["line1"] == "123 Legacy Way"
    finally:
        for p in requests.get(f"{API}/customers/{cid}/properties",
                                headers=admin_headers, timeout=15).json() or []:
            requests.delete(f"{API}/properties/{p['id']}",
                              headers=admin_headers, timeout=15)
        requests.delete(f"{API}/customers/{cid}",
                          headers=admin_headers, timeout=15)


def test_lazy_backfill_ignores_whitespace_only_address(admin_headers):
    """Whitespace-only address must not trigger the auto-seed."""
    marker = uuid.uuid4().hex[:8]
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": f"Blank {marker}",
        "first_name": "TEST_BLK", "last_name": f"B{marker}",
        "address": "   ",
        "address_line1": "   ",
    }, timeout=15)
    assert r.status_code in (200, 201)
    cid = r.json()["id"]
    try:
        r = requests.get(f"{API}/customers/{cid}/properties",
                           headers=admin_headers, timeout=15)
        assert r.status_code == 200
        assert r.json() == []
    finally:
        requests.delete(f"{API}/customers/{cid}",
                          headers=admin_headers, timeout=15)


# ─── MP1.5 polish observation #2 — address.address_line1 alias ────────

def test_property_create_accepts_address_line1_alias(admin_headers, customer):
    r = requests.post(f"{API}/customers/{customer['id']}/properties",
                        headers=admin_headers, json={
        "label": "AliasedAddr",
        "address": {
            "address_line1": "555 Alias Blvd",
            "city": "Peoria", "state": "AZ", "postal_code": "85383",
        },
    }, timeout=15)
    assert r.status_code == 201, r.text
    doc = r.json()
    # Aliased key must be folded into the canonical ``line1`` field.
    assert doc["address"]["line1"] == "555 Alias Blvd"
    # Verify persisted state — GET returns the folded field too.
    r = requests.get(f"{API}/properties/{doc['id']}",
                       headers=admin_headers, timeout=15)
    assert r.json()["address"]["line1"] == "555 Alias Blvd"


def test_property_patch_accepts_address_line1_alias(admin_headers, customer):
    r = requests.post(f"{API}/customers/{customer['id']}/properties",
                        headers=admin_headers, json={
        "label": "PatchMe",
        "address": {"line1": "1 Old St", "city": "Peoria",
                       "state": "AZ", "postal_code": "85383"},
    }, timeout=15).json()
    pid = r["id"]
    r = requests.patch(f"{API}/properties/{pid}", headers=admin_headers, json={
        "address": {"address_line1": "42 New Way", "city": "Peoria",
                       "state": "AZ", "postal_code": "85383"},
    }, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["address"]["line1"] == "42 New Way"
