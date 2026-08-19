"""Feb-2026 · BUG 2 fix — portal add-card magic-link happy + stale paths.

Regression coverage for ``GET /api/customers/add-card/{token}``:
  1. Happy path: a fresh token for an existing customer returns 200
     with masked name + tenant metadata.
  2. Stale path: a valid JWT that points at a customer_id which no
     longer exists (typical after a preview DB reseed) returns 404
     with a structured ``detail`` object (``code=stale_add_card_link``
     + human ``message`` + ``tenant_exists`` probe).

Uses the live-backend HTTP pattern already established in
``test_invoice_magic_view.py`` so the endpoint is exercised through
the same routing stack the browser hits.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

from services.add_card_links import encode_add_card_token


API = "http://127.0.0.1:8001/api"
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")


def _warm_backend() -> None:
    import time
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            r = requests.get(f"{API}/config/public", timeout=5)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)


_warm_backend()


def _db_and_client():
    loop = asyncio.new_event_loop()
    client = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=loop)
    return client[_ENV["DB_NAME"]], client, loop


def _run(coro):
    """Run an async coroutine on a fresh loop and return the result."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


TENANT_ID = f"TEST_ac_{uuid.uuid4().hex[:6]}"
CUST_ID = f"cust_{uuid.uuid4().hex[:8]}"


def _seed():
    async def _go():
        client = AsyncIOMotorClient(_ENV["MONGO_URL"])
        db = client[_ENV["DB_NAME"]]
        try:
            await db.tenants.delete_many({"id": TENANT_ID})
            await db.customers.delete_many({"id": CUST_ID})
            await db.tenants.insert_one({
                "id": TENANT_ID, "name": "Magic Test Tenant",
                "support_phone": "555-000-1111",
            })
            await db.customers.insert_one({
                "id": CUST_ID, "tenant_id": TENANT_ID,
                "first_name": "Alex", "last_name": "Rivera",
                "name": "Alex Rivera",
            })
        finally:
            client.close()
    _run(_go())


def _cleanup(tenant_ids=None, customer_ids=None):
    async def _go():
        client = AsyncIOMotorClient(_ENV["MONGO_URL"])
        db = client[_ENV["DB_NAME"]]
        try:
            if tenant_ids:
                await db.tenants.delete_many({"id": {"$in": list(tenant_ids)}})
            if customer_ids:
                await db.customers.delete_many({"id": {"$in": list(customer_ids)}})
        finally:
            client.close()
    _run(_go())


def test_add_card_context_happy_path():
    """Fresh token for an existing customer → 200 with masked name."""
    _seed()
    try:
        tok = encode_add_card_token(CUST_ID, TENANT_ID)
        r = requests.get(f"{API}/customers/add-card/{tok}", timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["customer_name_masked"] == "Alex R."
        assert body["tenant_name"] == "Magic Test Tenant"
        assert body["tenant_support_phone"] == "555-000-1111"
    finally:
        _cleanup(tenant_ids=[TENANT_ID], customer_ids=[CUST_ID])


def test_add_card_context_stale_customer_returns_structured_detail():
    """Valid JWT but customer_id no longer exists → 404 with
    ``code=stale_add_card_link`` and a human ``message`` so the
    frontend can render a helpful banner instead of "Customer not
    found"."""
    tenant_id = f"TEST_ac_stale_{uuid.uuid4().hex[:6]}"
    async def _seed_tenant_only():
        client = AsyncIOMotorClient(_ENV["MONGO_URL"])
        db = client[_ENV["DB_NAME"]]
        try:
            await db.tenants.insert_one({"id": tenant_id, "name": "Stale"})
        finally:
            client.close()
    _run(_seed_tenant_only())
    try:
        # Customer never inserted → reproduces the reseeded-preview case.
        tok = encode_add_card_token("cust_ghost_never_inserted", tenant_id)
        r = requests.get(f"{API}/customers/add-card/{tok}", timeout=10)
        assert r.status_code == 404
        detail = r.json().get("detail")
        assert isinstance(detail, dict), f"expected dict, got {detail!r}"
        assert detail.get("code") == "stale_add_card_link"
        assert "no longer valid" in detail.get("message", "").lower()
        assert detail.get("tenant_exists") is True
    finally:
        _cleanup(tenant_ids=[tenant_id])


def test_add_card_context_stale_tenant_flag_false():
    """Valid JWT for a tenant that also doesn't exist (fully cross-
    env token) → ``tenant_exists=False`` in the detail probe. This
    is the strongest signal that the token is from a completely
    different environment / reseeded DB."""
    tenant_id = f"tnt_ghost_{uuid.uuid4().hex[:6]}"
    tok = encode_add_card_token(f"cust_ghost_{uuid.uuid4().hex[:6]}", tenant_id)
    r = requests.get(f"{API}/customers/add-card/{tok}", timeout=10)
    assert r.status_code == 404
    detail = r.json().get("detail")
    assert detail.get("code") == "stale_add_card_link"
    assert detail.get("tenant_exists") is False
