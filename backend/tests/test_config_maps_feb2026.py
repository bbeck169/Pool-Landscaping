"""Feb 2026 · Task B — ``/api/config/maps`` public endpoint contract.

The New Customer form pulls the Google Maps client key from this
endpoint (instead of embedding it in the webpack bundle). The
contract MUST:
  * be reachable without a JWT (public — no auth header),
  * return only ``google_maps_client_key`` (no other secrets),
  * mirror the server-side ``GOOGLE_MAPS_API_KEY`` env,
  * degrade to an empty string when the env is unset (so the
    client can fall back to manual entry cleanly).
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
from dotenv import dotenv_values

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
API = "http://localhost:8001/api"


def test_config_maps_is_public():
    r = requests.get(f"{API}/config/maps", timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    # Response shape is EXACTLY the client key — no other fields
    # leak by accident.
    assert set(body.keys()) == {"google_maps_client_key"}


def test_config_maps_mirrors_env():
    r = requests.get(f"{API}/config/maps", timeout=15)
    body = r.json()
    assert body["google_maps_client_key"] == (
        _ENV.get("GOOGLE_MAPS_API_KEY", "")
    )


def test_config_maps_returns_string_type():
    r = requests.get(f"{API}/config/maps", timeout=15)
    body = r.json()
    # Always a string — never None. Empty string == unavailable.
    assert isinstance(body["google_maps_client_key"], str)


def test_config_maps_no_server_side_secrets_leak():
    """The endpoint must NOT surface any of the sensitive server-side
    keys that live in ``backend/.env`` alongside the client key.
    """
    r = requests.get(f"{API}/config/maps", timeout=15)
    body = r.json()
    for secret_env in (
        "STRIPE_SECRET_KEY", "STRIPE_SECRET_KEY_LIVE",
        "STRIPE_SECRET_KEY_TEST", "SENDGRID_API_KEY",
        "MONGO_URL", "JWT_SECRET", "EMERGENT_LLM_KEY",
    ):
        val = _ENV.get(secret_env)
        if val and len(val) > 10:
            # Full-string match — no accidental echo.
            for v in body.values():
                assert val not in str(v), (
                    f"{secret_env} value leaked into /config/maps"
                )


def test_config_maps_endpoint_via_unit_call_returns_empty_when_env_unset():
    """Unit-level guarantee that clearing the env produces an empty
    string (the client-side fallback trigger)."""
    # Import at test time so the environment mutation takes effect.
    from routers.config import config_maps
    import asyncio
    with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": ""}, clear=False):
        body = asyncio.get_event_loop().run_until_complete(config_maps())
    assert body == {"google_maps_client_key": ""}
