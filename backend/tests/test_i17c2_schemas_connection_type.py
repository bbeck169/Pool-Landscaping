"""Cleanup C2 · Feb-2026 — Explicit ``connection_type`` on every
provider entry returned by ``GET /api/tenants/me/integrations/schemas``.

Frontends should no longer have to *infer* whether a provider uses a
long-lived API key or a 3-legged OAuth flow — the schema now declares
it explicitly. Values:

    "api_key"       → SMS, Email, AI, Maps, CalDAV-style calendars
    "oauth"         → Google Calendar, Outlook Calendar
    "oauth_connect" → (reserved for Stripe Connect / I1.7.d payments)

One assertion per provider family — additive to the existing suites.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API = "http://localhost:8001/api"

_VALID = {"api_key", "oauth", "oauth_connect"}


def _login(email="super@aquaterra.com", password="password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _fetch_schemas() -> dict:
    tok = _login()
    r = requests.get(f"{API}/tenants/me/integrations/schemas",
                       headers=_hdrs(tok), timeout=15)
    r.raise_for_status()
    return r.json()


# ── One consolidated case (per brief) ────────────────────────────
def test_schemas_declares_connection_type_per_provider():
    body = _fetch_schemas()

    # ── SMS ── every entry must be explicit api_key
    assert body.get("sms"), "sms schemas missing"
    for entry in body["sms"]:
        assert "connection_type" in entry, f"sms/{entry['provider_key']} missing connection_type"
        assert entry["connection_type"] in _VALID
        assert entry["connection_type"] == "api_key", (
            f"sms/{entry['provider_key']} expected api_key, got {entry['connection_type']}"
        )

    # ── Email ──
    assert body.get("email"), "email schemas missing"
    for entry in body["email"]:
        assert entry["connection_type"] == "api_key", entry

    # ── AI ──
    assert body.get("ai"), "ai schemas missing"
    for entry in body["ai"]:
        assert entry["connection_type"] == "api_key", entry

    # ── Maps ──
    assert body.get("maps"), "maps schemas missing"
    for entry in body["maps"]:
        assert entry["connection_type"] == "api_key", entry

    # ── Calendars ── google + outlook must be oauth
    assert body.get("calendars"), "calendars schemas missing"
    cal_by_key = {e["provider_key"]: e for e in body["calendars"]}
    assert cal_by_key.get("calendars_google", {}).get("connection_type") == "oauth"
    assert cal_by_key.get("calendars_outlook", {}).get("connection_type") == "oauth"
    # Any additional calendar entries must at least declare a valid value.
    for entry in body["calendars"]:
        assert entry["connection_type"] in _VALID, entry
