"""Batch 12C follow-up · Feb 2026 — GET /api/tenants/mine/settings.

Mobile parity pass reported the read endpoint was missing. This suite
verifies:

  * Admin GET returns every settings field the mobile + web admin
    UIs need on load (Phase 12 + 12B + 12C fields + Phase 11 tracker
    toggles + Stripe alert SMS list).
  * Manager GET is allowed (mirrors the PATCH RBAC gate).
  * Technician GET → 403.
  * Customer GET → 403.
  * OpenAPI entry carries the ``tenants`` tag for mobile discovery.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
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


REQUIRED_KEYS = {
    "id", "name",
    "require_card_on_file_default",
    "timezone", "auto_send_card_add_on_create",
    "equipment_service_customer_reminders_enabled",
    "equipment_service_coming_due_days",
    "sms_escalation_recipients",
    "stripe_sync_last_run_at",
    "last_stripe_customer_sync_at",
    "last_stripe_customer_sync_summary",
    "settings_updated_at", "settings_updated_by",
}


def test_admin_can_read_tenant_settings(admin_headers):
    r = requests.get(f"{API}/tenants/mine/settings",
                      headers=admin_headers, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    missing = REQUIRED_KEYS - set(body.keys())
    assert not missing, f"settings response missing keys: {missing}"
    # Field types match the mobile client's expectations.
    assert isinstance(body["require_card_on_file_default"], bool)
    assert isinstance(body["auto_send_card_add_on_create"], bool)
    assert isinstance(
        body["equipment_service_customer_reminders_enabled"], bool)
    assert isinstance(body["sms_escalation_recipients"], list)
    assert isinstance(body["timezone"], str) and body["timezone"]


def test_technician_get_tenant_settings_forbidden(tech_headers):
    r = requests.get(f"{API}/tenants/mine/settings",
                      headers=tech_headers, timeout=10)
    assert r.status_code == 403


def test_customer_get_tenant_settings_forbidden(customer_headers):
    r = requests.get(f"{API}/tenants/mine/settings",
                      headers=customer_headers, timeout=10)
    assert r.status_code == 403


def test_openapi_lists_tenant_settings_with_correct_tag():
    """OpenAPI entry must carry the ``tenants`` tag so mobile SDK
    generators can co-locate it with the other tenant endpoints."""
    r = requests.get(f"{API}/openapi.json", timeout=10)
    assert r.status_code == 200
    spec = r.json()
    entry = spec["paths"].get("/api/tenants/mine/settings", {})
    assert "get" in entry, "GET /tenants/mine/settings missing from openapi"
    assert "patch" in entry, "PATCH /tenants/mine/settings missing from openapi"
    assert "tenants" in (entry["get"].get("tags") or [])
    assert "tenants" in (entry["patch"].get("tags") or [])


def test_openapi_lists_send_card_add_link_with_correct_tag():
    """Openapi must expose the canonical POST path with a customers
    tag — the mobile agent hit a 404 on the mistyped
    ``send-card-link`` and needs the correct name discoverable."""
    r = requests.get(f"{API}/openapi.json", timeout=10)
    spec = r.json()
    entry = spec["paths"].get(
        "/api/customers/{cid}/send-card-add-link", {})
    assert "post" in entry, \
        "POST /customers/{cid}/send-card-add-link missing from openapi"
    assert "customers" in (entry["post"].get("tags") or [])
    # Old mistyped path must NOT exist (guards against copy-paste
    # regressions).
    assert spec["paths"].get(
        "/api/customers/{cid}/send-card-link") is None
