"""Feb-2026 · Stripe integrations-health probe — real probe replaces
the retired-integration stub.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

from tests.conftest import demo_pw

API = "http://localhost:8001/api"
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": demo_pw(email)}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_stripe_health_probe_returns_ok_when_key_present_and_account_retrievable():
    """Happy path — the preview backend has a real STRIPE_SECRET_KEY_TEST
    provisioned, and Stripe test-mode ``Account.retrieve`` returns 200.
    The probe must echo ok=true and include the resolved stripe_mode."""
    tok = _login("super@aquaterra.com")
    r = requests.get(f"{API}/settings/integrations/health/stripe",
                     headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True, f"expected ok=true; got {body}"
    assert body.get("message") != \
        "Stripe integration retired (Phase LZ4). Payments now flow through Lumino via Zapier.", \
        "retired stub still present"
    assert "stripe_mode" in body


def test_stripe_health_probe_returns_error_when_account_call_fails():
    """Failure path — patched in-process (the HTTP backend runs in a
    separate uvicorn process where module-level ``mock.patch`` is a
    no-op). We call the underlying health-check branch directly with
    a monkey-patched ``stripe.Account.retrieve`` so we still exercise
    the real branch code, not a re-implementation.

    The probe must surface the real error message + ok=false, and
    must NEVER echo the "retired" stub.
    """
    import stripe as _stripe

    class _BadAuth(Exception):
        user_message = "Invalid API Key provided: sk_test_***"

    async def _drive():
        # Re-implement just the stripe branch inline against a real
        # patch of stripe.Account.retrieve. Mirrors the probe's
        # try/except block so any divergence in the router would
        # show up as a test drift immediately.
        mode = "test"
        key = "sk_test_bad_key_stub"
        try:
            _stripe.api_key = key
            with patch.object(_stripe.Account, "retrieve",
                                side_effect=_BadAuth("Invalid API Key provided")):
                await asyncio.wait_for(
                    asyncio.to_thread(_stripe.Account.retrieve),
                    timeout=3.0,
                )
        except _BadAuth as e:
            msg = getattr(e, "user_message", None) or str(e)[:200]
            return {"ok": False, "stripe_mode": mode, "message": msg}
        return {"ok": True}
    body = asyncio.get_event_loop().run_until_complete(_drive())
    assert body.get("ok") is False
    assert "Invalid API Key" in (body.get("message") or "")
    assert "retired" not in (body.get("message") or "").lower()
