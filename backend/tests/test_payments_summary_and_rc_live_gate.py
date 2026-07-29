"""Feb-2026 · Tests for ``GET /api/payments/summary`` + RC live-events gate."""
from __future__ import annotations

import os
from pathlib import Path

import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = MongoClient(_MONGO_URL)[_DB_NAME]

_REACT_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_REACT = dotenv_values(_REACT_ENV) if _REACT_ENV.is_file() else {}
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL") or os.environ.get(
    "REACT_APP_BACKEND_URL")
API = os.environ.get("BACKEND_API_URL") or (
    (_PUBLIC_URL.rstrip("/") + "/api") if _PUBLIC_URL else
    "http://localhost:8001/api"
)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _super_headers() -> dict:
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


def _tech_headers() -> dict:
    tech = _sync.users.find_one({"role": "technician",
                                 "email": {"$exists": True, "$ne": None}})
    return {"Authorization": f"Bearer {_login(tech['email'])}"}


def _customer_headers() -> dict:
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


# ─── /payments/summary ──────────────────────────────────────────────

def test_payments_summary_shape_and_status():
    r = requests.get(f"{API}/payments/summary",
                     headers=_super_headers(), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("month_label", "collected_this_month",
                "outstanding_total", "outstanding_count", "overdue"):
        assert key in body, f"missing key {key}: {body}"
    assert isinstance(body["month_label"], str) and body["month_label"]
    assert isinstance(body["collected_this_month"], (int, float))
    assert isinstance(body["outstanding_total"], (int, float))
    assert isinstance(body["outstanding_count"], int)
    assert isinstance(body["overdue"], list)
    # Row shape (if any)
    for row in body["overdue"]:
        for k in ("id", "invoice_number", "customer_id", "customer_name",
                  "total", "balance", "due_date", "status"):
            assert k in row, f"overdue row missing {k}: {row}"


def test_payments_summary_customer_forbidden():
    r = requests.get(f"{API}/payments/summary",
                     headers=_customer_headers(), timeout=15)
    assert r.status_code == 403, r.text


def test_payments_summary_tech_forbidden():
    r = requests.get(f"{API}/payments/summary",
                     headers=_tech_headers(), timeout=15)
    assert r.status_code == 403, r.text


def test_payments_summary_anon_forbidden():
    r = requests.get(f"{API}/payments/summary", timeout=15)
    assert r.status_code in (401, 403), r.text


# ─── /ringcentral/settings/live-events + /ringcentral/health ────────

def test_rc_live_events_gate_default_false():
    """Health should surface the ``live_events_enabled`` flag."""
    # Ensure clean-slate: remove any override so we test default.
    _sync.rc_settings.delete_one({"key": "live_events_enabled"})
    r = requests.get(f"{API}/ringcentral/health",
                     headers=_super_headers(), timeout=15)
    # Health may 503 if outbound is on and RC auth fails — flag still present.
    body = r.json() if r.status_code == 200 else r.json().get("detail", {})
    assert "live_events_enabled" in body, body
    assert body["live_events_enabled"] is False


def test_rc_live_events_toggle_admin_can_flip():
    tok = _login("super@aquaterra.com")
    h = {"Authorization": f"Bearer {tok}"}
    try:
        r1 = requests.post(f"{API}/ringcentral/settings/live-events",
                            headers=h, json={"enabled": True}, timeout=15)
        assert r1.status_code == 200, r1.text
        assert r1.json()["live_events_enabled"] is True

        # Health reflects it now.
        h2 = requests.get(f"{API}/ringcentral/health",
                           headers=h, timeout=15)
        body = h2.json() if h2.status_code == 200 else h2.json().get("detail", {})
        assert body["live_events_enabled"] is True

        # Flip back
        r2 = requests.post(f"{API}/ringcentral/settings/live-events",
                            headers=h, json={"enabled": False}, timeout=15)
        assert r2.status_code == 200, r2.text
        assert r2.json()["live_events_enabled"] is False
    finally:
        _sync.rc_settings.delete_one({"key": "live_events_enabled"})


def test_rc_live_events_toggle_customer_forbidden():
    r = requests.post(f"{API}/ringcentral/settings/live-events",
                       headers=_customer_headers(),
                       json={"enabled": True}, timeout=15)
    assert r.status_code in (401, 403), r.text
