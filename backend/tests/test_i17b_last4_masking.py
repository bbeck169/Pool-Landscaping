"""Phase I1.7.b.fix · Feb-2026 — ``last_4`` masking bug regression.

Before the fix, ``last_4`` was computed off the JSON-blob tail so
Twilio rows displayed ``"}"``, Resend rows displayed ``m\"}``, etc.
After the fix, each provider declares ``primary_secret_field`` and
the display mask uses the last 4 chars of THAT field's plaintext.

This suite locks the new behaviour end-to-end (HTTP contract) using
the live backend on ``localhost:8001``.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _login(email="super@aquaterra.com", password="password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _tenant_id(tok: str) -> str:
    r = requests.get(f"{API}/tenants/current", headers=_hdrs(tok), timeout=15)
    r.raise_for_status()
    return r.json()["id"]


@pytest.fixture
def admin_ctx():
    tok = _login()
    tid = _tenant_id(tok)
    # Wipe any leftover rows from previous runs.
    _sync.tenant_secrets.delete_many({"tenant_id": tid, "provider_key": {"$ne": "stripe"}})
    yield tok, tid
    _sync.tenant_secrets.delete_many({"tenant_id": tid, "provider_key": {"$ne": "stripe"}})


# One end-to-end case per provider: seed a config where the primary
# secret field ends in a distinctive 4-char tail, then read back
# ``last_4`` via the public list endpoint and assert it matches.
_CASES = [
    ("twilio", "auth_token", "ABCDEFabcdefTAIL", "TAIL",
        {"account_sid": "ACxxxxxxxxxxxxxxxxxxxxxxxx",
         "auth_token": "ABCDEFabcdefTAIL",
         "from_number": "+15551234567"}),
    ("textmagic", "api_key", "textmagic-api-key-Z9Q1", "Z9Q1",
        {"username": "tenant_user",
         "api_key": "textmagic-api-key-Z9Q1"}),
    ("ringcentral", "jwt_token", "rc-jwt-token-D3F4", "D3F4",
        {"server_url": "https://platform.ringcentral.com",
         "client_id": "cid", "client_secret": "csecret",
         "jwt_token": "rc-jwt-token-D3F4",
         "from_number": "+15551234567"}),
    ("resend", "api_key", "re_test_key_5X7B", "5X7B",
        {"api_key": "re_test_key_5X7B",
         "from_addr": "hello@example.com"}),
    ("sendgrid", "api_key", "SG.test.9M8N", "9M8N",
        {"api_key": "SG.test.9M8N",
         "from_addr": "hello@example.com"}),
    ("postmark", "server_token", "pm-token-K7L2", "K7L2",
        {"server_token": "pm-token-K7L2",
         "from_addr": "hello@example.com"}),
    ("mailgun", "api_key", "key-mailgun-Q1W2", "Q1W2",
        {"api_key": "key-mailgun-Q1W2",
         "domain": "mg.example.com",
         "from_addr": "hello@example.com"}),
    ("smtp", "password", "super-sneaky-pw-P4S5", "P4S5",
        {"host": "smtp.example.com", "port": 587,
         "username": "hello@example.com",
         "password": "super-sneaky-pw-P4S5",
         "from_addr": "hello@example.com"}),
]


@pytest.mark.parametrize("provider_key,field,plaintext,expected_last4,config", _CASES)
def test_i17b_fix_last4_reflects_primary_secret_field(
    admin_ctx, provider_key, field, plaintext, expected_last4, config,
):
    tok, tid = admin_ctx
    r = requests.put(
        f"{API}/tenants/me/integrations/{provider_key}",
        headers=_hdrs(tok), timeout=15,
        json={"config": config},
    )
    assert r.status_code == 200, r.text
    lst = requests.get(f"{API}/tenants/me/integrations",
                          headers=_hdrs(tok), timeout=15).json()
    row = next((x for x in lst["integrations"] if x["provider_key"] == provider_key), None)
    assert row is not None, f"{provider_key} row missing"
    got_last4 = row.get("last_4")
    assert got_last4 == expected_last4, (
        f"expected last_4={expected_last4!r} for {provider_key} "
        f"(field={field}), got={got_last4!r}"
    )
    # Belt-and-braces: the plaintext must not appear anywhere in
    # the public response.
    import json as _j
    assert plaintext not in _j.dumps(lst), \
        f"plaintext leaked into public list response for {provider_key}"


def test_i17b_fix_stripe_last4_unchanged_by_regression(admin_ctx):
    """Legacy behaviour for single-string secrets (Stripe access
    tokens) still works — last-4 is the tail of the plaintext itself
    because there is no ``primary_secret_field``."""
    tok, tid = admin_ctx
    # Seed a stripe row directly via the internal API so we don't
    # need to run a real OAuth exchange. Use a fresh Motor client
    # bound to the current event loop to avoid the ``Future attached
    # to a different loop`` error that hits the module-level default.
    from services.secrets import put_secret as _put
    from services.secrets.models import ConnectionType
    from motor.motor_asyncio import AsyncIOMotorClient
    import asyncio
    plaintext = "sk_live_1234567890BEEF"
    async def _seed():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        try:
            db = client[os.environ["DB_NAME"]]
            await _put(tid, "stripe", plaintext,
                          connection_type=ConnectionType.OAUTH_STRIPE_CONNECT,
                          connected_account_id="acct_test_9abc",
                          db=db)
        finally:
            client.close()
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_seed())
    finally:
        loop.close()
    lst = requests.get(f"{API}/tenants/me/integrations",
                          headers=_hdrs(tok), timeout=15).json()
    row = next((x for x in lst["integrations"] if x["provider_key"] == "stripe"), None)
    assert row is not None
    assert row["last_4"] == "BEEF"
    import json as _j
    assert plaintext not in _j.dumps(lst)
