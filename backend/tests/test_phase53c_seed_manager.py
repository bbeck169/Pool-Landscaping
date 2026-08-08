"""Phase 53c · Feb-2026 — demo-manager role-drift repair regression.

Locks the invariant surfaced during Phase 53b E2E verification:
``manager@aquaterra.com`` must resolve to ``role=manager`` in
``/api/auth/me``. Any migration that promotes the row is healed by
``seed_demo_manager()`` on the next boot.
"""
from __future__ import annotations

import os

import requests


API = os.environ.get("BACKEND_URL", "http://localhost:8001") + "/api"
TIMEOUT = 30


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pw}, timeout=TIMEOUT)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


def test_demo_manager_role_is_manager_via_auth_me():
    tok = _login("manager@aquaterra.com")
    r = requests.get(f"{API}/auth/me",
                     headers={"Authorization": f"Bearer {tok}"},
                     timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("email") == "manager@aquaterra.com"
    assert body.get("role") == "manager", \
        f"seed drift detected — expected role=manager, got role={body.get('role')!r}"
    assert body.get("active") is True
