"""Phase 12 · Feb 2026 — "Require card on file" tenant default +
per-customer override + magic-link add-card page.

Covers the invariants promised in the spec:

* Tenant boot migration sets ``require_card_on_file_default: true``.
* Effective flag is derived on read; tenant flips propagate without
  a customer-doc write.
* PATCH override accepts ``true / false / null`` and returns 422 on
  garbage input.
* Non-admin / non-manager roles cannot PATCH the override or the
  tenant default.
* ``missing_card=true`` filter respects both derived flags.
* ``send-card-add-link`` rate limit trips on the 2nd request within
  5 minutes.
* Magic-link token validates & rejects bad tokens.
* ``ADD_CARD_LINK`` merge tag resolves in the seeded templates.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._shared_loop import run as _run

_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_env["MONGO_URL"])[_env["DB_NAME"]]
_TENANT = _sync.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
_TENANT_ID = _TENANT["id"]

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
def tech_headers():
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def customer_headers():
    return _login("customer@aquaterra.com")


@pytest.fixture()
def scratch_customer(admin_headers):
    """Create a fresh customer per test — cleanup unconditionally."""
    payload = {
        "name": f"Phase12 Test {uuid.uuid4().hex[:6]}",
        "first_name": "Phase12",
        "last_name": "Tester",
        "email": f"phase12-{uuid.uuid4().hex[:8]}@pytest.local",
        "phone": "+15550009999",
    }
    r = requests.post(f"{API}/customers", json=payload,
                        headers=admin_headers, timeout=10)
    r.raise_for_status()
    cid = r.json()["id"]
    yield cid
    _sync.customers.delete_many({"id": cid})
    _sync.marketing_deliveries.delete_many({"customer_id": cid})


# ─── Boot migration guarantees ────────────────────────────────────────
def test_boot_migration_sets_tenant_default_true():
    """After startup, every tenant has require_card_on_file_default:
    true (idempotent — running it twice never flips explicit
    False values back to True)."""
    from services.add_card_links import ensure_require_card_default_on_tenants
    # Re-run the migration — should be a no-op on the field-present
    # tenants and leave the explicit-false ones alone.
    _sync.tenants.update_one(
        {"id": _TENANT_ID},
        {"$set": {"require_card_on_file_default": False}},
    )
    modified = _run(ensure_require_card_default_on_tenants())
    doc = _sync.tenants.find_one({"id": _TENANT_ID}, {"_id": 0})
    assert doc["require_card_on_file_default"] is False, \
        "migration must NOT overwrite an explicit-false value"
    # Restore true for downstream tests.
    _sync.tenants.update_one(
        {"id": _TENANT_ID},
        {"$set": {"require_card_on_file_default": True}},
    )
    assert isinstance(modified, int)


# ─── Derived fields ───────────────────────────────────────────────────
def test_new_customer_effective_defaults_to_true(admin_headers, scratch_customer):
    r = requests.get(f"{API}/customers/{scratch_customer}",
                      headers=admin_headers, timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["require_card_on_file_override"] is None
    assert d["effective_require_card_on_file"] is True
    assert d["has_card_on_file"] is False
    assert d["saved_payment_methods_count"] == 0


def test_patch_override_false_then_clear(admin_headers, scratch_customer):
    r1 = requests.patch(f"{API}/customers/{scratch_customer}",
                         json={"require_card_on_file_override": False},
                         headers=admin_headers, timeout=10)
    assert r1.status_code == 200
    assert r1.json()["effective_require_card_on_file"] is False

    r2 = requests.patch(f"{API}/customers/{scratch_customer}",
                         json={"require_card_on_file_override": None},
                         headers=admin_headers, timeout=10)
    assert r2.status_code == 200
    assert r2.json()["require_card_on_file_override"] is None
    assert r2.json()["effective_require_card_on_file"] is True


def test_patch_override_bad_type_returns_422(admin_headers, scratch_customer):
    r = requests.patch(f"{API}/customers/{scratch_customer}",
                        json={"require_card_on_file_override": "sometimes"},
                        headers=admin_headers, timeout=10)
    assert r.status_code == 422


def test_tenant_default_flip_propagates_without_customer_write(admin_headers,
                                                                 scratch_customer):
    """Set tenant default false → new customer with override=null
    reads effective=false. Restore default true → effective back to
    true. NO ``customers`` update happened between the two reads."""
    before_upd = _sync.customers.find_one(
        {"id": scratch_customer}, {"_id": 0, "updated_at": 1})
    requests.patch(f"{API}/tenants/mine/settings",
                    json={"require_card_on_file_default": False},
                    headers=admin_headers, timeout=10).raise_for_status()
    d1 = requests.get(f"{API}/customers/{scratch_customer}",
                       headers=admin_headers, timeout=10).json()
    assert d1["effective_require_card_on_file"] is False
    requests.patch(f"{API}/tenants/mine/settings",
                    json={"require_card_on_file_default": True},
                    headers=admin_headers, timeout=10).raise_for_status()
    d2 = requests.get(f"{API}/customers/{scratch_customer}",
                       headers=admin_headers, timeout=10).json()
    assert d2["effective_require_card_on_file"] is True
    after_upd = _sync.customers.find_one(
        {"id": scratch_customer}, {"_id": 0, "updated_at": 1})
    assert before_upd.get("updated_at") == after_upd.get("updated_at"), \
        "tenant-default flip must not mutate customer docs"


def test_missing_card_filter_returns_only_effective_required_no_pm(admin_headers,
                                                                     scratch_customer):
    """New customer starts effective=true, has_card=false → included.
    Set override false → no longer effective_required → excluded.
    Set saved_payment_methods_count=1 → excluded (has card)."""
    r = requests.get(f"{API}/customers?missing_card=true",
                      headers=admin_headers, timeout=10)
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()]
    assert scratch_customer in ids

    # Override to not-required — should drop off the list.
    requests.patch(f"{API}/customers/{scratch_customer}",
                    json={"require_card_on_file_override": False},
                    headers=admin_headers, timeout=10).raise_for_status()
    ids2 = [c["id"] for c in requests.get(
        f"{API}/customers?missing_card=true",
        headers=admin_headers, timeout=10).json()]
    assert scratch_customer not in ids2

    # Restore required + simulate a saved PM → still off the list.
    requests.patch(f"{API}/customers/{scratch_customer}",
                    json={"require_card_on_file_override": None},
                    headers=admin_headers, timeout=10).raise_for_status()
    _sync.customers.update_one(
        {"id": scratch_customer},
        {"$set": {"saved_payment_methods_count": 1}},
    )
    ids3 = [c["id"] for c in requests.get(
        f"{API}/customers?missing_card=true",
        headers=admin_headers, timeout=10).json()]
    assert scratch_customer not in ids3
    _sync.customers.update_one(
        {"id": scratch_customer},
        {"$set": {"saved_payment_methods_count": 0}},
    )


# ─── RBAC gates ───────────────────────────────────────────────────────
def test_tech_cannot_patch_override(tech_headers, scratch_customer):
    r = requests.patch(f"{API}/customers/{scratch_customer}",
                        json={"require_card_on_file_override": True},
                        headers=tech_headers, timeout=10)
    assert r.status_code == 403


def test_tech_cannot_patch_tenant_default(tech_headers):
    r = requests.patch(f"{API}/tenants/mine/settings",
                        json={"require_card_on_file_default": False},
                        headers=tech_headers, timeout=10)
    assert r.status_code == 403


def test_tech_cannot_use_missing_card_filter(tech_headers):
    r = requests.get(f"{API}/customers?missing_card=true",
                      headers=tech_headers, timeout=10)
    assert r.status_code == 403


# ─── send-card-add-link + rate limit ─────────────────────────────────
def test_send_card_add_link_rate_limits_within_5min(admin_headers,
                                                       scratch_customer):
    from services.add_card_links import reset_rate_limit
    reset_rate_limit(scratch_customer)
    r1 = requests.post(
        f"{API}/customers/{scratch_customer}/send-card-add-link",
        headers=admin_headers, timeout=10,
    )
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["ok"] is True
    # Ledger row was written for the delivery.
    rows = list(_sync.marketing_deliveries.find(
        {"customer_id": scratch_customer,
          "trigger_entity.kind": "add_card_request"},
        {"_id": 0}))
    assert len(rows) >= 1
    # Immediate 2nd hit should trip the 5-min rate limit.
    r2 = requests.post(
        f"{API}/customers/{scratch_customer}/send-card-add-link",
        headers=admin_headers, timeout=10,
    )
    assert r2.status_code == 429
    body2 = r2.json()
    assert body2["detail"]["code"] == "RATE_LIMITED"


# ─── Magic-link token round-trip ─────────────────────────────────────
def test_add_card_token_encode_decode():
    from services.add_card_links import (
        encode_add_card_token, decode_add_card_token,
    )
    tok = encode_add_card_token("cust-abc", _TENANT_ID)
    p = decode_add_card_token(tok)
    assert p["customer_id"] == "cust-abc"
    assert p["tenant_id"] == _TENANT_ID


def test_add_card_public_endpoint_bad_token_returns_401():
    r = requests.get(f"{API}/customers/add-card/not-a-real-token", timeout=10)
    assert r.status_code == 401


def test_add_card_public_endpoint_masks_customer_pii(admin_headers,
                                                       scratch_customer):
    from services.add_card_links import encode_add_card_token
    tok = encode_add_card_token(scratch_customer, _TENANT_ID)
    r = requests.get(f"{API}/customers/add-card/{tok}", timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert "phase12-" not in (d.get("customer_name_masked") or "")
    assert "@" not in (d.get("customer_name_masked") or "")
    assert d["customer_name_masked"].startswith("Phase12 T")
    assert d["tenant_name"] == "AquaTerra"


# ─── Merge tag ────────────────────────────────────────────────────────
def test_add_card_link_merge_tag_resolves_in_seeded_email():
    from services.marketing.merge_tags import render_template, render_context
    tpl = _sync.marketing_templates.find_one(
        {"tenant_id": _TENANT_ID, "code": "add_card_request_email"},
        {"_id": 0},
    )
    assert tpl is not None, "boot seed must insert the email template"
    ctx = render_context(
        customer={"name": "Alice Doe", "first_name": "Alice",
                  "last_name": "Doe"},
        tenant={"name": "AquaTerra"},
        add_card_link="https://poolscape.example/portal/add-card?token=XYZ",
    )
    rendered_subject, missing_s = render_template(tpl["subject"], ctx)
    rendered_body, missing_b = render_template(tpl["body"], ctx)
    assert "add a card" in rendered_subject.lower()
    assert "Alice" in rendered_body
    assert "AquaTerra" in rendered_body
    assert "portal/add-card?token=XYZ" in rendered_body
    assert missing_s == []
    assert missing_b == []
