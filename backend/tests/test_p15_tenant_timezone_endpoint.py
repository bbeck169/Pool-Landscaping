"""Phase P15 · Feb-2026 — Permanent Tenant Timezone Setting.

Locks in the backend contract for the new curated allowed-tz
whitelist:

  1. ``GET /api/tenants/timezones`` returns exactly the 7 curated
     entries in the exact spec order (ET → CT → MT → PT → Alaska
     → Arizona → Hawaii).
  2. ``PATCH /api/tenants/mine/settings`` accepts every one of
     those 7 values as a valid tz.
  3. ``PATCH /api/tenants/mine/settings`` rejects any IANA name
     NOT in the curated list (``Europe/Paris`` is the canary) with
     400 + a helpful ``allowed`` list.
"""
from __future__ import annotations

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
def admin_h() -> dict:
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def tech_h() -> dict:
    """Non-admin auth — the timezones list endpoint is not gated
    beyond ``get_current_user``, so any authenticated tenant user
    can read it."""
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}


# ═════════════════════════════════════════════════════════════════════
# Expected canonical response.
# ═════════════════════════════════════════════════════════════════════
EXPECTED_TIMEZONES = [
    {"value": "America/New_York",    "label": "Eastern Time (ET)"},
    {"value": "America/Chicago",     "label": "Central Time (CT)"},
    {"value": "America/Denver",      "label": "Mountain Time (MT)"},
    {"value": "America/Los_Angeles", "label": "Pacific Time (PT)"},
    {"value": "America/Anchorage",   "label": "Alaska Time"},
    {"value": "America/Phoenix",     "label": "Arizona (No DST)"},
    {"value": "Pacific/Honolulu",    "label": "Hawaii (No DST)"},
]


# ═════════════════════════════════════════════════════════════════════
# GET /api/tenants/timezones
# ═════════════════════════════════════════════════════════════════════
def test_get_timezones_returns_exact_seven_entries_in_order(admin_h):
    r = requests.get(f"{API}/tenants/timezones",
                      headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "timezones" in body
    assert body["timezones"] == EXPECTED_TIMEZONES


def test_get_timezones_available_to_non_admin_user(tech_h):
    """The picker is fetched by any authenticated tenant user —
    mobile / read-only shells rely on it too. No admin gate."""
    r = requests.get(f"{API}/tenants/timezones",
                      headers=tech_h, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["timezones"] == EXPECTED_TIMEZONES


def test_get_timezones_requires_auth():
    r = requests.get(f"{API}/tenants/timezones", timeout=15)
    # Missing bearer → 401/403 depending on the middleware stack.
    assert r.status_code in (401, 403), r.text


# ═════════════════════════════════════════════════════════════════════
# PATCH /api/tenants/mine/settings — every whitelisted value accepted.
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture
def _tenant_tz_restore(admin_h):
    """Snapshot the tenant's current timezone before this test and
    restore it after so we don't leave the demo tenant on a random
    zone."""
    r = requests.get(f"{API}/tenants/mine/settings",
                      headers=admin_h, timeout=15)
    r.raise_for_status()
    prev = r.json().get("timezone") or "America/Phoenix"
    yield prev
    # Restore. If it was already an allowed value, PATCH works.
    # If it was a legacy value, PATCH will now 400 — in that case
    # we drop back to Phoenix which is always allowed.
    restore = prev
    allowed = {e["value"] for e in EXPECTED_TIMEZONES}
    if restore not in allowed:
        restore = "America/Phoenix"
    requests.patch(f"{API}/tenants/mine/settings",
                    headers=admin_h,
                    json={"timezone": restore}, timeout=15)


@pytest.mark.parametrize("tz_value", [e["value"] for e in EXPECTED_TIMEZONES])
def test_patch_accepts_every_whitelisted_timezone(
    admin_h, tz_value, _tenant_tz_restore,
):
    r = requests.patch(f"{API}/tenants/mine/settings",
                        headers=admin_h,
                        json={"timezone": tz_value}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("timezone") == tz_value


# ═════════════════════════════════════════════════════════════════════
# PATCH — non-whitelisted values are rejected with 400.
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("bad_value", [
    "Europe/Paris",
    "Asia/Tokyo",
    "UTC",                # was allowed pre-P15; now off-list
    "America/Toronto",
    "Antarctica/McMurdo",
    "not-a-timezone",
    "",
])
def test_patch_rejects_non_whitelisted_timezone(
    admin_h, bad_value, _tenant_tz_restore,
):
    r = requests.patch(f"{API}/tenants/mine/settings",
                        headers=admin_h,
                        json={"timezone": bad_value}, timeout=15)
    assert r.status_code == 400, (bad_value, r.status_code, r.text)
    detail = r.json().get("detail")
    assert isinstance(detail, dict), (bad_value, detail)
    assert detail.get("code") == "INVALID_TIMEZONE"
    # Helpful message + allowed list surfaced so admins can debug.
    assert "allowed" in detail
    assert set(detail["allowed"]) == {e["value"] for e in EXPECTED_TIMEZONES}
    assert isinstance(detail.get("message"), str)
    assert detail.get("message")


def test_patch_ignores_missing_timezone_key(
    admin_h, _tenant_tz_restore,
):
    """Sanity: sending a different settings field without ``timezone``
    still succeeds and does not accidentally hit the tz validator."""
    r = requests.patch(f"{API}/tenants/mine/settings",
                        headers=admin_h,
                        json={"require_card_on_file_default": True},
                        timeout=15)
    assert r.status_code == 200, r.text
