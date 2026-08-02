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
API = "http://localhost:8001/api"
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


@pytest.mark.parametrize("email,password,expected_role", _DEMO_CREDS)
def test_demo_login_returns_valid_jwt(email, password, expected_role):
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200, (
        f"{email} login failed: HTTP {r.status_code} body={r.text[:400]}"
    )
    body = r.json()
    token = body.get("access_token") or body.get("token")
    assert token, f"no access_token in response for {email}: {body}"

    # Decode with the pod's JWT_SECRET — a rotation or algorithm mismatch
    # would fail here even if the endpoint returned 200.
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    assert (payload.get("role") or "") == expected_role, (
        f"{email} role mismatch: JWT={payload.get('role')!r}, "
        f"expected={expected_role!r}"
    )

    # And the wrapped user object should agree with the JWT.
    user_obj = body.get("user") or {}
    assert (user_obj.get("role") or "") == expected_role, (
        f"{email} response.user.role={user_obj.get('role')!r}, "
        f"expected={expected_role!r}"
    )
