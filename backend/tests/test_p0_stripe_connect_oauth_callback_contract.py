"""P0 · Feb-2026 — Stripe Connect OAuth callback contract guards.

Complementary to ``test_i17a_stripe_connect_flow.py`` — these tests
harden the specific claims flagged during the Feb-2026 bulk-charge
P0 incident:

1. **No authed session required on callback.** OAuth callbacks come
   from Stripe (or the mock), NOT from an authed browser session.
   Any regression that adds ``Depends(require_admin)`` or similar
   auth on the callback will 403 every OAuth attempt.

2. **State replay + tampering rejected.** Once a state has been
   consumed by a successful callback, replaying the same state
   MUST NOT succeed (single-use).

3. **Redirect URI is env-driven when ``STRIPE_CONNECT_REDIRECT_URI``
   is set** — allows ops to pin the callback to the canonical
   production host when the request-derived value lands on a
   preview / emergentcf.cloud pod that has proxy-level auth.

All tests hit the live backend (``localhost:8001``) via ``requests``
— same pattern as ``test_i17a_stripe_connect_flow.py``.
"""
from __future__ import annotations

import os
import subprocess
import time
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


# ─────────────────────────────────────────────────────────────────
# 1. No authed session required on callback.
# ─────────────────────────────────────────────────────────────────
def test_stripe_connect_oauth_callback_does_not_require_authed_session():
    """Callback MUST accept unauthenticated GETs (state validates
    the request). Any regression that adds ``Depends`` auth on this
    route will 403 every real OAuth flow (Stripe → callback URL
    presents no session cookie)."""
    # Deliberately use ``requests.Session()`` with no auth header /
    # no cookies. Response MUST be a 302 redirect (either success or
    # error), NEVER a 401/403.
    sess = requests.Session()
    r = sess.get(
        f"{API}/integrations/stripe/callback",
        params={"code": "any", "state": "does-not-exist"},
        allow_redirects=False, timeout=15,
    )
    assert r.status_code == 302, (
        f"Callback returned {r.status_code} for an unauthenticated GET. "
        f"OAuth callbacks arrive from Stripe with no session cookie — "
        f"an auth gate here breaks the entire Connect flow. "
        f"Body head: {r.text[:200]!r}"
    )
    # Round-trip: ``connect=error`` for unknown state is fine — the
    # important thing is that we got a 302 not a 401/403.
    assert "connect=error" in r.headers["location"]


# ─────────────────────────────────────────────────────────────────
# 2. State replay + tampering rejected.
# ─────────────────────────────────────────────────────────────────
def test_stripe_connect_oauth_state_replay_and_tampering_rejected():
    """Once a state has been consumed by a successful callback the
    row is deleted from ``oauth_pending`` (see
    ``routers/tenant_integrations.py`` — the callback deletes on
    both success and expiry paths). Replaying the same state MUST
    surface as ``state_unknown``.

    Also asserts a state that doesn't decode / doesn't exist
    (tampering) is rejected the same way — the code never blindly
    trusts the query param.
    """
    tok = _login()
    tenant_id = _get_tenant_id(tok)
    _sync.tenant_secrets.delete_many({"tenant_id": tenant_id, "provider_key": "stripe"})

    r0 = requests.get(f"{API}/integrations/stripe/connect-link",
                        headers=_hdrs(tok), timeout=15)
    assert r0.status_code == 200
    state = r0.json()["state"]

    # First callback → consumes state.
    r1 = requests.get(
        f"{API}/integrations/stripe/callback",
        params={"code": "mock_code", "state": state},
        allow_redirects=False, timeout=15,
    )
    assert r1.status_code == 302, r1.text
    assert "connect=success" in r1.headers["location"]

    # Replay the same state → MUST be rejected.
    r2 = requests.get(
        f"{API}/integrations/stripe/callback",
        params={"code": "mock_code", "state": state},
        allow_redirects=False, timeout=15,
    )
    assert r2.status_code == 302
    assert "connect=error" in r2.headers["location"]
    assert "state_unknown" in r2.headers["location"], (
        f"Replay of consumed state was not rejected as state_unknown. "
        f"Location: {r2.headers.get('location')!r}"
    )

    # Tampered state (never issued) → same rejection path.
    r3 = requests.get(
        f"{API}/integrations/stripe/callback",
        params={"code": "mock_code", "state": "not-a-real-state-" + uuid.uuid4().hex},
        allow_redirects=False, timeout=15,
    )
    assert r3.status_code == 302
    assert "state_unknown" in r3.headers["location"]

    # Cleanup.
    _sync.tenant_secrets.delete_many({"tenant_id": tenant_id, "provider_key": "stripe"})


# ─────────────────────────────────────────────────────────────────
# 3. Redirect URI is env-driven not derived from request.
#
#    This is a static/source-level assertion — full end-to-end
#    verification of env override requires restarting uvicorn with
#    the env var set, which is out of scope for the fast test tier.
#    We instead assert:
#      (a) the connect-link handler reads ``STRIPE_CONNECT_REDIRECT_URI``
#          from ``os.environ`` before falling back to ``request.base_url``
#      (b) with env unset, the default derivation still holds (i.e.
#          the old behaviour is preserved for preview/mock).
# ─────────────────────────────────────────────────────────────────
def test_stripe_connect_oauth_callback_redirect_uri_is_env_driven_not_derived_from_request():
    """The connect-link handler MUST honour ``STRIPE_CONNECT_REDIRECT_URI``
    when set. If it doesn't, ops cannot pin the callback to the
    canonical prod host (``https://app.plofv.com/api/integrations/
    stripe/callback``) when the request-derived value lands on a
    preview / emergentcf.cloud pod with proxy-level 403.
    """
    # Source-level assertion — cheap + deterministic.
    src = Path(__file__).resolve().parents[1] / "routers" / "tenant_integrations.py"
    text = src.read_text()
    assert 'STRIPE_CONNECT_REDIRECT_URI' in text, (
        "connect-link handler does not read STRIPE_CONNECT_REDIRECT_URI. "
        "Ops cannot pin the callback to the prod host when the request-"
        "derived value lands on a preview pod."
    )
    # Assert the fallback (``request.base_url``) is still present so
    # mock preview flows keep working when the env var is unset.
    assert "request.base_url" in text, (
        "connect-link handler no longer falls back to request.base_url — "
        "preview mock flows will break."
    )
    # Assert both are visible in the same function scope.
    connect_link_body = text.split("async def stripe_connect_link(")[1].split("\nasync def ")[0]
    assert 'STRIPE_CONNECT_REDIRECT_URI' in connect_link_body
    assert 'request.base_url' in connect_link_body

    # Also live-verify that with env UNSET (current pod state), the
    # generated connect-link URL contains a redirect_uri pointing at
    # the request host — i.e. the fallback branch is exercised.
    override = (os.environ.get("STRIPE_CONNECT_REDIRECT_URI") or "").strip()
    if override:
        pytest.skip(f"STRIPE_CONNECT_REDIRECT_URI is currently set to {override!r} — "
                    "cannot assert fallback branch. Skipping fallback verification.")

    tok = _login()
    r = requests.get(f"{API}/integrations/stripe/connect-link",
                       headers=_hdrs(tok), timeout=15)
    assert r.status_code == 200
    url = r.json()["url"]
    # Mock URL has shape ``<base>/api/integrations/stripe/callback?code=mock_...&state=...``
    assert "/api/integrations/stripe/callback" in url, (
        f"Generated URL missing callback path: {url!r}"
    )
    # In mock mode the URL host is the same as request host — i.e.
    # ``localhost:8001`` (or the preview host). NOT the prod host.
    assert "localhost:8001" in url or ".preview.emergentagent.com" in url, (
        f"Fallback branch produced unexpected redirect host: {url!r}"
    )
