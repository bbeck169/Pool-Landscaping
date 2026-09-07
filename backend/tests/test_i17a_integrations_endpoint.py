"""Phase I1.7.a · Feb-2026 — Integrations router contract lock.

Covers:
  1. GET /tenants/me/integrations — role gating + safe shape (no
     plaintext leaks in the response).
  2. POST /tenants/me/integrations/{key}/test — provider probe.
  3. DELETE /tenants/me/integrations/{key} — removal + idempotency.
  4. Unknown provider_key → 404 (test) or graceful (delete).

Uses ``requests`` against the live backend (localhost:8001).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


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


def _seed_tech_user() -> str:
    from utils import hash_password
    tok = _login()
    tid = _get_tenant_id(tok)
    email = f"i17a-tech-{uuid.uuid4().hex[:8]}@example.com"
    _sync.users.insert_one({
        "id": uuid.uuid4().hex, "email": email, "name": "I17a Tech",
        "role": "tech", "tenant_id": tid,
        "password_hash": hash_password("Password123!"),
    })
    return email


@pytest.fixture(autouse=True)
def _clean():
    yield
    _sync.users.delete_many({"email": {"$regex": "^i17a-tech-"}})


def _seed_stripe_secret(tenant_id: str, plaintext: str, acct: str) -> None:
    from services.secrets import put_secret
    from services.secrets.models import ConnectionType
    async def _seed():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        try:
            await put_secret(
                tenant_id, "stripe", plaintext,
                connection_type=ConnectionType.OAUTH_STRIPE_CONNECT,
                connected_account_id=acct,
                db=client[os.environ["DB_NAME"]],
            )
        finally:
            client.close()
    asyncio.run(_seed())


# ── GET list ─────────────────────────────────────────────────────
def test_i17a_list_requires_auth():
    r = requests.get(f"{API}/tenants/me/integrations", timeout=15)
    assert r.status_code == 403


def test_i17a_list_returns_empty_when_no_secrets():
    tok = _login()
    tid = _get_tenant_id(tok)
    _sync.tenant_secrets.delete_many({"tenant_id": tid})
    r = requests.get(f"{API}/tenants/me/integrations",
                       headers=_hdrs(tok), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == tid
    assert body["integrations"] == []


def test_i17a_list_returns_masked_summary_never_plaintext():
    tok = _login()
    tid = _get_tenant_id(tok)
    _sync.tenant_secrets.delete_many({"tenant_id": tid})
    plaintext = "sk_test_ThisIsThePlaintextAccessToken_deadbeef"
    _seed_stripe_secret(tid, plaintext, "acct_test_summary_probe_123")
    try:
        r = requests.get(f"{API}/tenants/me/integrations",
                           headers=_hdrs(tok), timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert len(body["integrations"]) == 1
        s = body["integrations"][0]
        assert s["provider_key"] == "stripe"
        assert s["connected"] is True
        assert "…" in (s["connected_account_id_masked"] or "")
        assert s["last_4"] == "beef"
        # Nothing in the response body may contain the plaintext.
        import json as _j
        blob = _j.dumps(body)
        assert "ThisIsThePlaintextAccessToken" not in blob
        assert "sk_test_ThisIsThe" not in blob
    finally:
        _sync.tenant_secrets.delete_many({"tenant_id": tid})


# ── test-connection ──────────────────────────────────────────────
def test_i17a_test_unknown_provider_returns_404():
    tok = _login()
    r = requests.post(f"{API}/tenants/me/integrations/nope/test",
                        headers=_hdrs(tok), timeout=15)
    assert r.status_code == 404


def test_i17a_test_stripe_no_connection_returns_ok_false():
    tok = _login()
    tid = _get_tenant_id(tok)
    _sync.tenant_secrets.delete_many({"tenant_id": tid, "provider_key": "stripe"})
    r = requests.post(f"{API}/tenants/me/integrations/stripe/test",
                        headers=_hdrs(tok), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider_key"] == "stripe"
    assert body["ok"] is False
    assert "No Stripe connection" in body["message"]


# ── delete ───────────────────────────────────────────────────────
def test_i17a_delete_removes_secret_idempotent():
    tok = _login()
    tid = _get_tenant_id(tok)
    _seed_stripe_secret(tid, "will-be-deleted-token-xxxx", "acct_test_del")
    r = requests.delete(f"{API}/tenants/me/integrations/stripe",
                          headers=_hdrs(tok), timeout=15)
    assert r.status_code == 200
    assert r.json() == {"removed": True, "provider_key": "stripe"}
    r2 = requests.delete(f"{API}/tenants/me/integrations/stripe",
                           headers=_hdrs(tok), timeout=15)
    assert r2.json()["removed"] is False


# ── role gating ──────────────────────────────────────────────────
def test_i17a_tech_cannot_list_test_delete_or_connect():
    email = _seed_tech_user()
    tok = _login(email, "Password123!")
    r1 = requests.get(f"{API}/tenants/me/integrations",
                        headers=_hdrs(tok), timeout=15)
    r2 = requests.post(f"{API}/tenants/me/integrations/stripe/test",
                         headers=_hdrs(tok), timeout=15)
    r3 = requests.delete(f"{API}/tenants/me/integrations/stripe",
                           headers=_hdrs(tok), timeout=15)
    r4 = requests.get(f"{API}/integrations/stripe/connect-link",
                        headers=_hdrs(tok), timeout=15)
    assert r1.status_code == 403
    assert r2.status_code == 403
    assert r3.status_code == 403
    assert r4.status_code == 403
