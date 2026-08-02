"""Regression guard for the four seeded demo login credentials.

Motivation
----------
2026-08-08 saw a user-reported P0 "demo logins not working". Root cause
turned out to be a transient 502 during the backend boot pipeline (the
seed migrations take ~30s across ~110 tenants; Cloudflare serves a 502
shield until Uvicorn's ``Application startup complete`` fires). All
four credentials work at steady state.

This test locks that steady-state contract in place so any future
regression (password-hash migration bug, JWT secret rotation, role
enum tightening that rejects seed values, etc.) fails CI loudly.

Seed credentials are the ones documented in
``/app/memory/test_credentials.md`` and healed on every backend boot
by ``auto_heal_demo_passwords`` (see the backend startup logs —
"all 4 present demo users already authenticate with default").
"""
from __future__ import annotations

import os
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import dotenv_values

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_LOCAL_API = "http://localhost:8001/api"
_EXTERNAL_API = (
    (_ENV.get("REACT_APP_BACKEND_URL")
     or os.environ.get("REACT_APP_BACKEND_URL")
     or "").rstrip("/")
    + "/api"
) if (_ENV.get("REACT_APP_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL")) \
    else None
# Fallback: sniff the frontend .env directly so this test never silently
# skips the external path.
if not _EXTERNAL_API:
    _fe_env = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
    _fe_url = (_fe_env.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
    if _fe_url:
        _EXTERNAL_API = _fe_url + "/api"

JWT_SECRET = _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET") \
    or "dev-secret-change-me"
JWT_ALGO = _ENV.get("JWT_ALGO") or "HS256"


# (email, expected_role) — must remain in sync with
# /app/memory/test_credentials.md and the seed script.
_DEMO_CREDS = [
    ("super@aquaterra.com",       "password123", "super_admin"),
    ("manager@aquaterra.com",     "password123", "admin"),
    ("landscaper@aquaterra.com",  "password123", "technician"),
    ("customer@aquaterra.com",    "password123", "customer"),
]


def _assert_login_ok(base_api: str, email: str, password: str,
                      expected_role: str) -> None:
    r = requests.post(
        f"{base_api}/auth/login",
        json={"email": email, "password": password},
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    assert r.status_code == 200, (
        f"{email} @ {base_api} login failed: HTTP {r.status_code} "
        f"body={r.text[:400]}"
    )
    body = r.json()
    token = body.get("access_token") or body.get("token")
    assert token, f"no access_token in response for {email}: {body}"

    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    assert (payload.get("role") or "") == expected_role, (
        f"{email} JWT role mismatch: got {payload.get('role')!r}, "
        f"expected {expected_role!r}"
    )
    user_obj = body.get("user") or {}
    assert (user_obj.get("role") or "") == expected_role


# ── Localhost path (fast — asserts the backend process itself works)
@pytest.mark.parametrize("email,password,expected_role", _DEMO_CREDS)
def test_demo_login_returns_valid_jwt(email, password, expected_role):
    _assert_login_ok(_LOCAL_API, email, password, expected_role)


# ── External-ingress path (Cloudflare + ingress + FastAPI, end-to-end)
#    Extended in 2026-08-02 P0 investigation follow-up: catches
#    edge-only regressions (CF Worker rewrites, cert / TLS breaks,
#    origin allowlist drift) that the localhost test can't see.
@pytest.mark.parametrize("email,password,expected_role", _DEMO_CREDS)
def test_demo_login_via_external_ingress(email, password, expected_role):
    if not _EXTERNAL_API:
        pytest.skip("REACT_APP_BACKEND_URL not resolvable — external path skipped")
    _assert_login_ok(_EXTERNAL_API, email, password, expected_role)
