"""Feb-2026 P0 · Customer portal identity + tenant isolation guard.

Regression coverage for two closely related security invariants:

1. **Bug 1 (identity leak)** — portal-home endpoints MUST scope by
   both ``tenant_id`` and ``customer_id`` derived from the JWT.
   Two customers signing in back-to-back must NEVER see each
   other's greeting name / balances / invoices / estimates.

2. **Bug 1 defense-in-depth** — ``/portal/home`` emits an
   ``identity_mismatch`` flag when the JWT ``email`` claim does
   not match the resolved customer's email. The frontend can then
   render a "please re-sign-in" banner instead of silently rendering
   another customer's data.

Uses the live-backend HTTP pattern already established in
``test_invoice_magic_view.py`` / ``test_add_card_magic_link.py``.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

from utils import hash_password


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


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


TENANT_ID = f"TEST_portalid_{uuid.uuid4().hex[:6]}"
CUST_A_ID = f"cust_A_{uuid.uuid4().hex[:6]}"
CUST_B_ID = f"cust_B_{uuid.uuid4().hex[:6]}"
USER_A_ID = f"user_A_{uuid.uuid4().hex[:6]}"
USER_B_ID = f"user_B_{uuid.uuid4().hex[:6]}"
USER_A_EMAIL = f"alice_{uuid.uuid4().hex[:6]}@identitytest.example.com"
USER_B_EMAIL = f"bob_{uuid.uuid4().hex[:6]}@identitytest.example.com"


def _seed():
    async def _go():
        client = AsyncIOMotorClient(_ENV["MONGO_URL"])
        db = client[_ENV["DB_NAME"]]
        try:
            await db.tenants.delete_many({"id": TENANT_ID})
            await db.customers.delete_many({"id": {"$in": [CUST_A_ID, CUST_B_ID]}})
            await db.users.delete_many({"id": {"$in": [USER_A_ID, USER_B_ID]}})
            await db.quotes.delete_many(
                {"customer_id": {"$in": [CUST_A_ID, CUST_B_ID]}})
            await db.jobs.delete_many(
                {"customer_id": {"$in": [CUST_A_ID, CUST_B_ID]}})
            await db.tenants.insert_one({
                "id": TENANT_ID, "name": "Identity Test Tenant", "active": True,
            })
            # Customer A — Alice Alpha
            await db.customers.insert_one({
                "id": CUST_A_ID, "tenant_id": TENANT_ID,
                "name": "Alice Alpha", "email": USER_A_EMAIL,
                "first_name": "Alice", "last_name": "Alpha",
            })
            await db.users.insert_one({
                "id": USER_A_ID, "tenant_id": TENANT_ID,
                "name": "Alice Alpha", "email": USER_A_EMAIL,
                "password_hash": hash_password("password123"),
                "role": "customer", "customer_id": CUST_A_ID,
                "active": True, "failed_login_attempts": 0,
            })
            # Customer B — Bob Bravo (distinctive balances so a leak is obvious)
            await db.customers.insert_one({
                "id": CUST_B_ID, "tenant_id": TENANT_ID,
                "name": "Bob Bravo", "email": USER_B_EMAIL,
                "first_name": "Bob", "last_name": "Bravo",
            })
            await db.users.insert_one({
                "id": USER_B_ID, "tenant_id": TENANT_ID,
                "name": "Bob Bravo", "email": USER_B_EMAIL,
                "password_hash": hash_password("password123"),
                "role": "customer", "customer_id": CUST_B_ID,
                "active": True, "failed_login_attempts": 0,
            })
            # Seed a signature invoice for each so we can assert
            # cross-scope isolation on the summary endpoint.
            await db.quotes.insert_many([
                {"id": f"inv_A_{uuid.uuid4().hex[:6]}", "tenant_id": TENANT_ID,
                 "customer_id": CUST_A_ID, "doc_type": "invoice",
                 "total": 111.11, "amount_paid": 0, "status": "sent"},
                {"id": f"inv_B_{uuid.uuid4().hex[:6]}", "tenant_id": TENANT_ID,
                 "customer_id": CUST_B_ID, "doc_type": "invoice",
                 "total": 222.22, "amount_paid": 0, "status": "sent"},
            ])
        finally:
            client.close()
    _run(_go())


def _cleanup():
    async def _go():
        client = AsyncIOMotorClient(_ENV["MONGO_URL"])
        db = client[_ENV["DB_NAME"]]
        try:
            await db.tenants.delete_many({"id": TENANT_ID})
            await db.customers.delete_many({"id": {"$in": [CUST_A_ID, CUST_B_ID]}})
            await db.users.delete_many({"id": {"$in": [USER_A_ID, USER_B_ID]}})
            await db.quotes.delete_many(
                {"customer_id": {"$in": [CUST_A_ID, CUST_B_ID]}})
        finally:
            client.close()
    _run(_go())


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def test_portal_home_scopes_by_authenticated_customer_only():
    """A and B log in back-to-back; each sees ONLY their own name +
    balance + invoices. Zero leakage of the other customer's data
    into either response."""
    _seed()
    try:
        # A
        tok_a = _login(USER_A_EMAIL)
        home_a = requests.get(f"{API}/portal/home",
                                headers={"Authorization": f"Bearer {tok_a}"},
                                timeout=10).json()
        assert home_a["customer"]["id"] == CUST_A_ID
        assert home_a["customer"]["name"] == "Alice Alpha"
        assert home_a["customer"]["email"] == USER_A_EMAIL
        sum_a = requests.get(f"{API}/customer-portal/summary",
                              headers={"Authorization": f"Bearer {tok_a}"},
                              timeout=10).json()
        assert round(sum_a["balance_due"], 2) == 111.11
        # B
        tok_b = _login(USER_B_EMAIL)
        home_b = requests.get(f"{API}/portal/home",
                                headers={"Authorization": f"Bearer {tok_b}"},
                                timeout=10).json()
        assert home_b["customer"]["id"] == CUST_B_ID
        assert home_b["customer"]["name"] == "Bob Bravo"
        assert home_b["customer"]["email"] == USER_B_EMAIL
        sum_b = requests.get(f"{API}/customer-portal/summary",
                              headers={"Authorization": f"Bearer {tok_b}"},
                              timeout=10).json()
        assert round(sum_b["balance_due"], 2) == 222.22
        # Cross-guard — Alice's name never appears in Bob's payload
        # and vice versa.
        assert "Alice" not in str(home_b)
        assert "Bob" not in str(home_a)
        # identity_mismatch is False in the happy path — user/customer
        # emails match.
        assert home_a["identity_mismatch"] is False
        assert home_b["identity_mismatch"] is False
    finally:
        _cleanup()


def test_portal_home_flags_identity_mismatch_when_emails_diverge():
    """Simulate the exact prod pathology reported by the user:
    ``users.customer_id`` points at a customer whose email differs
    from the JWT's ``email`` claim. The endpoint MUST still scope
    data to the customer_id the JWT points at (defense-in-depth is
    NOT to hard-block, since a legitimate rebind may exist), but it
    MUST surface ``identity_mismatch: True`` so the frontend
    renders a "please re-sign in" banner and ops can grep the
    warning."""
    _seed()
    try:
        # Rewrite user A's ``customer_id`` to point at Bob's customer
        # row — this mimics the reported cross-contamination.
        async def _rebind():
            c = AsyncIOMotorClient(_ENV["MONGO_URL"])
            db = c[_ENV["DB_NAME"]]
            try:
                await db.users.update_one(
                    {"id": USER_A_ID},
                    {"$set": {"customer_id": CUST_B_ID}},
                )
            finally:
                c.close()
        _run(_rebind())
        tok_a = _login(USER_A_EMAIL)
        home = requests.get(f"{API}/portal/home",
                              headers={"Authorization": f"Bearer {tok_a}"},
                              timeout=10).json()
        # Data reflects the customer_id the JWT points at (Bob), but
        # the mismatch flag is TRUE so the frontend can react.
        assert home["customer"]["id"] == CUST_B_ID
        assert home["identity_mismatch"] is True
    finally:
        _cleanup()


def test_portal_home_scopes_by_tenant_id():
    """Two tenants each with the same customer_id string would be
    astronomically unlikely (UUIDs) but the query MUST include
    ``tenant_id`` regardless. Assert the /portal/home Mongo lookup
    references tenant scoping in the query — inspection of the
    source ensures the guard cannot regress."""
    src = Path("/app/backend/routers/portal_admin.py").read_text()
    # customer / jobs / quotes(invoice) / quotes(quote) / communications
    for pat in [
        '{"id": cid, "tenant_id": tid}',
        '{"customer_id": cid, "tenant_id": tid}',
        '{"customer_id": cid, "tenant_id": tid, "doc_type": "invoice"}',
        '{"customer_id": cid, "tenant_id": tid, "doc_type": "quote"}',
    ]:
        assert pat in src, f"missing tenant-scoping pattern: {pat!r}"
