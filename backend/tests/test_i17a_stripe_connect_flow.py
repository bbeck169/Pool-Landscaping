"""Phase I1.7.a · Feb-2026 — Stripe Connect OAuth flow lock.

Exercises the connect-link → callback pipeline end-to-end against
the live backend (localhost:8001) using ``requests`` — same
technique as ``test_i15a_tenant_theme_endpoint.py``. TestClient
would work for one test only because ``@app.on_event("startup")``
handlers cannot be re-invoked per-test in the same process.

Real Stripe OAuth exchange is mocked via ``STRIPE_TESTMODE_MOCK_
CONNECT=true`` (the pod default), which short-circuits the
``exchange_oauth_code`` call and persists a synthetic
``acct_test_...`` on the tenant.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API = "http://localhost:8001/api"
_sync = _shared_db()
def _login(email: str = "super@aquaterra.com",
             password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": password},
                        timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _get_tenant_id(tok: str) -> str:
    r = requests.get(f"{API}/tenants/current", headers=_hdrs(tok), timeout=15)
    r.raise_for_status()
    return r.json()["id"]


@pytest.fixture(autouse=True)
def _clean():
    yield
    _sync.oauth_pending.delete_many({"provider_key": "stripe"})


# ── connect-link ─────────────────────────────────────────────────
def test_i17a_connect_link_requires_auth():
    r = requests.get(f"{API}/integrations/stripe/connect-link", timeout=15)
    assert r.status_code == 403, r.text


def test_i17a_connect_link_persists_pending_state():
    tok = _login()
    r = requests.get(
        f"{API}/integrations/stripe/connect-link",
        headers=_hdrs(tok), timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] and body["url"]
    pending = _sync.oauth_pending.find_one({"state": body["state"]})
    assert pending is not None
    assert pending["provider_key"] == "stripe"
    # Expiry is 15 minutes in the future.
    assert pending["expires_at"] > datetime.now(timezone.utc).isoformat()


# ── callback ─────────────────────────────────────────────────────
def test_i17a_callback_unknown_state_redirects_to_error():
    r = requests.get(
        f"{API}/integrations/stripe/callback",
        params={"code": "abc", "state": "does-not-exist"},
        allow_redirects=False, timeout=15,
    )
    assert r.status_code == 302
    assert "connect=error" in r.headers["location"]
    assert "state_unknown" in r.headers["location"]


def test_i17a_callback_expired_state_redirects_to_error():
    state = uuid.uuid4().hex
    _sync.oauth_pending.insert_one({
        "id": state, "state": state, "provider_key": "stripe",
        "tenant_id": "any-tenant", "user_id": "u",
        "expires_at": (datetime.now(timezone.utc)
                         - timedelta(minutes=1)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    r = requests.get(
        f"{API}/integrations/stripe/callback",
        params={"code": "abc", "state": state},
        allow_redirects=False, timeout=15,
    )
    assert r.status_code == 302
    assert "state_expired" in r.headers["location"]
    assert _sync.oauth_pending.find_one({"state": state}) is None


def test_i17a_callback_mock_mode_stores_synthetic_connection():
    """When STRIPE_TESTMODE_MOCK_CONNECT=true, the callback stores a
    synthetic ``acct_test_...`` on the tenant + redirects to
    success."""
    assert os.environ.get("STRIPE_TESTMODE_MOCK_CONNECT", "").lower() in ("1", "true", "yes")
    tok = _login()
    tenant_id = _get_tenant_id(tok)
    # Wipe any residue for this tenant so the assert on connected
    # account id is unambiguous.
    _sync.tenant_secrets.delete_many({"tenant_id": tenant_id, "provider_key": "stripe"})

    # Get a state via the real connect-link so we don't rely on
    # a synthetic pending row (proves the round-trip).
    r0 = requests.get(f"{API}/integrations/stripe/connect-link",
                        headers=_hdrs(tok), timeout=15)
    assert r0.status_code == 200
    state = r0.json()["state"]

    r = requests.get(
        f"{API}/integrations/stripe/callback",
        params={"code": "mock_code_123", "state": state},
        allow_redirects=False, timeout=15,
    )
    assert r.status_code == 302, r.text
    assert "connect=success" in r.headers["location"]

    row = _sync.tenant_secrets.find_one({"tenant_id": tenant_id, "provider_key": "stripe"})
    assert row is not None
    assert row["connection_type"] == "oauth_stripe_connect"
    assert row["connected_account_id"].startswith("acct_test_")
    assert row["connected_status"] == "connected"
    assert _sync.oauth_pending.find_one({"state": state}) is None
    # Cleanup so downstream tests aren't polluted.
    _sync.tenant_secrets.delete_many({"tenant_id": tenant_id, "provider_key": "stripe"})
