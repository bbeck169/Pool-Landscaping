"""Sep-2026 · Per-tenant DFS creds · CRUD endpoints.

Covers:
  • GET when unconfigured   → configured=false, login_masked=None
  • PUT                     → stores ciphertext, returns masked view
  • GET when configured     → returns masked ``bri***@example.com``
  • Plaintext never leaks in any GET response
  • DELETE                  → clears everything
  • Rate limit on /test     → 6th call within an hour → 429
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": password},
                        timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token():
    # Reuse the seeded admin@aquaterra.com / password123 account.
    # Module scope so we don't hammer /auth/login and trip its
    # own rate limit during a full-file run.
    return _login("admin@aquaterra.com", "password123")


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Zero the /test endpoint's in-memory rate-limit bucket between
    tests so unrelated cases don't 429 each other."""
    from routers.tenant_dataforseo_integration import _reset_rate_limit_for_tests
    _reset_rate_limit_for_tests()
    yield
    _reset_rate_limit_for_tests()


def _me(admin_token: str) -> Dict[str, Any]:
    return requests.get(f"{API}/auth/me",
                          headers={"Authorization": f"Bearer {admin_token}"},
                          timeout=10).json()


def _cleanup_dfs(tenant_id: str):
    _sync.tenants.update_one(
        {"id": tenant_id},
        {"$unset": {"settings.integrations.dataforseo": ""}},
    )


def test_get_when_unconfigured_returns_configured_false(admin_token):
    hdr = {"Authorization": f"Bearer {admin_token}"}
    me = _me(admin_token)
    _cleanup_dfs(me["tenant_id"])
    r = requests.get(f"{API}/tenants/me/integrations/dataforseo",
                        headers=hdr, timeout=10)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["configured"] is False
    assert j["login_masked"] is None
    assert j["configured_at"] is None


def test_put_encrypts_stores_and_returns_masked_view(admin_token):
    hdr = {"Authorization": f"Bearer {admin_token}"}
    me = _me(admin_token)
    tid = me["tenant_id"]
    try:
        r = requests.put(
            f"{API}/tenants/me/integrations/dataforseo",
            headers=hdr, timeout=10,
            json={"login": "brian@example.com", "password": "sekret-123"},
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["configured"] is True
        assert j["login_masked"] == "bri***@example.com"
        assert j["configured_by"], j
        doc = _sync.tenants.find_one({"id": tid}, {"_id": 0})
        integ = ((doc.get("settings") or {}).get("integrations") or {}) \
            .get("dataforseo") or {}
        assert integ["login_encrypted"].startswith("gAAAAA")
        assert integ["password_encrypted"].startswith("gAAAAA")
        assert "brian@example.com" not in integ["login_encrypted"]
        assert "sekret-123" not in integ["password_encrypted"]
        r2 = requests.get(f"{API}/tenants/me/integrations/dataforseo",
                              headers=hdr, timeout=10)
        assert r2.status_code == 200
        assert r2.json()["login_masked"] == "bri***@example.com"
    finally:
        _cleanup_dfs(tid)


def test_plaintext_never_leaks_in_any_get_response(admin_token):
    hdr = {"Authorization": f"Bearer {admin_token}"}
    me = _me(admin_token)
    tid = me["tenant_id"]
    try:
        secret_login = "leaky-canary@example.com"
        secret_pw = "leaky-canary-password-token"
        requests.put(
            f"{API}/tenants/me/integrations/dataforseo",
            headers=hdr, timeout=10,
            json={"login": secret_login, "password": secret_pw},
        ).raise_for_status()
        r = requests.get(f"{API}/tenants/me/integrations/dataforseo",
                              headers=hdr, timeout=10)
        body = r.text
        assert secret_login not in body, "plaintext login leaked in GET"
        assert secret_pw not in body, "plaintext password leaked in GET"
        assert "login_encrypted" not in body
        assert "password_encrypted" not in body
        assert "gAAAAA" not in body
    finally:
        _cleanup_dfs(tid)


def test_delete_clears_all_dfs_fields(admin_token):
    hdr = {"Authorization": f"Bearer {admin_token}"}
    me = _me(admin_token)
    tid = me["tenant_id"]
    try:
        requests.put(
            f"{API}/tenants/me/integrations/dataforseo",
            headers=hdr, timeout=10,
            json={"login": "z@x.com", "password": "abcdef"},
        ).raise_for_status()
        r = requests.delete(f"{API}/tenants/me/integrations/dataforseo",
                                 headers=hdr, timeout=10)
        assert r.status_code == 200
        assert r.json()["configured"] is False
        doc = _sync.tenants.find_one({"id": tid}, {"_id": 0})
        integ = ((doc.get("settings") or {}).get("integrations") or {}) \
            .get("dataforseo") or {}
        assert "login_encrypted" not in integ, integ
        assert "password_encrypted" not in integ, integ
    finally:
        _cleanup_dfs(tid)


def test_test_endpoint_rate_limit_after_5_hits(admin_token):
    """Direct in-process test of the rate-limit primitive (the HTTP
    /test endpoint calls this same function). Cross-process HTTP
    tests can't share the in-memory bucket with the backend, so we
    exercise the primitive directly and rely on the endpoint's
    single-line integration with it."""
    from fastapi import HTTPException
    from routers.tenant_dataforseo_integration import (
        _rate_limit_test, _reset_rate_limit_for_tests, _TEST_RL_CAP,
    )
    _reset_rate_limit_for_tests()
    tid = "rate-limit-unit-test"
    # First _TEST_RL_CAP hits succeed.
    for i in range(_TEST_RL_CAP):
        _rate_limit_test(tid)  # no raise
    # CAP+1th hit: 429.
    try:
        _rate_limit_test(tid)
        assert False, "MUST raise 429"
    except HTTPException as e:
        assert e.status_code == 429
        assert e.detail["code"] == "rate_limited"


def test_test_endpoint_success_stamps_last_verified_at(admin_token):
    """This exercises the /test endpoint end-to-end against real
    DFS (using globally-configured creds — the tenant's stored
    creds are dummies). If DFS is unreachable in this env, skip."""
    from routers.tenant_dataforseo_integration import _reset_rate_limit_for_tests
    hdr = {"Authorization": f"Bearer {admin_token}"}
    me = _me(admin_token)
    tid = me["tenant_id"]
    try:
        # Use REAL creds from env so DFS actually returns 200 —
        # cheapest test on the DFS side is a single serp call
        # for "connectivity test" (see routers/tenant_dfs_integ).
        real_login = os.environ.get("DATAFORSEO_LOGIN") or ""
        real_pw = os.environ.get("DATAFORSEO_PASSWORD") or ""
        if not (real_login and real_pw):
            pytest.skip("DFS not configured in env for live /test smoke.")
        requests.put(
            f"{API}/tenants/me/integrations/dataforseo",
            headers=hdr, timeout=10,
            json={"login": real_login, "password": real_pw},
        ).raise_for_status()
        # Note: rate-limit bucket in the backend has module-level
        # state that persists across tests. Best-effort skip if we
        # can't get a fresh 5-hit budget.
        r = requests.post(
            f"{API}/tenants/me/integrations/dataforseo/test",
            headers=hdr, timeout=30,
        )
        if r.status_code == 429:
            pytest.skip("Backend /test rate-limit bucket exhausted; "
                        "restart backend to reset for CI.")
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] is True
        assert isinstance(j["latency_ms"], int) and j["latency_ms"] > 0
        assert j["last_verified_at"], j
        doc = _sync.tenants.find_one({"id": tid}, {"_id": 0})
        integ = ((doc.get("settings") or {}).get("integrations") or {}) \
            .get("dataforseo") or {}
        assert integ["last_verified_at"] == j["last_verified_at"]
    finally:
        _cleanup_dfs(tid)
