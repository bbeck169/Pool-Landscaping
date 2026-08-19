"""Feb-2026 P0 · Portal "Add card on file" not-found regression guard.

Root cause: the frontend at ``PortalPaymentMethods.jsx`` was reading
``customer_id`` from the ``/api/me`` response — but ``/api/me``
returns the CUSTOMER doc (where ``id`` == the customer's own id and
there is no ``customer_id`` field). Every portal user hit the
"Your account isn't linked to a customer record" banner and the
payment-methods fetch went to ``.../payment-methods/undefined`` →
403 "Not allowed".

Backend was not the problem — this suite just asserts the
authenticated payment-methods endpoint returns 200 for a portal
customer's OWN id and 403 when the URL customer_id doesn't match
the JWT (the guard the "undefined" URL was tripping).
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

from utils import hash_password


API = "http://127.0.0.1:8001/api"
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")


def _warm_backend():
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


TENANT_ID = f"TEST_pm_{uuid.uuid4().hex[:6]}"
CUST_ID   = f"cust_pm_{uuid.uuid4().hex[:6]}"
USER_ID   = f"user_pm_{uuid.uuid4().hex[:6]}"
EMAIL     = f"pmtest_{uuid.uuid4().hex[:6]}@pmtest.example.com"


def _seed():
    async def _go():
        c = AsyncIOMotorClient(_ENV["MONGO_URL"])
        db = c[_ENV["DB_NAME"]]
        try:
            await db.tenants.delete_many({"id": TENANT_ID})
            await db.customers.delete_many({"id": CUST_ID})
            await db.users.delete_many({"id": USER_ID})
            await db.tenants.insert_one({"id": TENANT_ID, "name": "PM Test", "active": True})
            await db.customers.insert_one({
                "id": CUST_ID, "tenant_id": TENANT_ID,
                "name": "PM Tester", "email": EMAIL,
                "first_name": "PM", "last_name": "Tester",
            })
            await db.users.insert_one({
                "id": USER_ID, "tenant_id": TENANT_ID,
                "name": "PM Tester", "email": EMAIL,
                "password_hash": hash_password("password123"),
                "role": "customer", "customer_id": CUST_ID,
                "active": True, "failed_login_attempts": 0,
            })
        finally:
            c.close()
    _run(_go())


def _cleanup():
    async def _go():
        c = AsyncIOMotorClient(_ENV["MONGO_URL"])
        db = c[_ENV["DB_NAME"]]
        try:
            await db.tenants.delete_many({"id": TENANT_ID})
            await db.customers.delete_many({"id": CUST_ID})
            await db.users.delete_many({"id": USER_ID})
        finally:
            c.close()
    _run(_go())


def test_me_returns_customer_id_as_id_field():
    """``/api/me`` is the CUSTOMER endpoint — the id we need for the
    payment-methods URL lives at ``id`` (not ``customer_id``).
    Documenting the shape so the frontend patch cannot silently
    regress: the guard now reads ``id || customer_id``."""
    _seed()
    try:
        tok = requests.post(f"{API}/auth/login",
                              json={"email": EMAIL, "password": "password123"},
                              timeout=10).json()["access_token"]
        r = requests.get(f"{API}/me",
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == CUST_ID
        # This is the shape trap that produced the P0 — no
        # ``customer_id`` field on the customer doc.
        assert "customer_id" not in body
    finally:
        _cleanup()


def test_portal_user_can_list_own_payment_methods_via_own_id():
    """Using the id from ``/api/me`` (=== customer_id), the portal
    can list its own payment methods. Empty list is fine; the
    contract is a 200 with a ``payment_methods`` key."""
    _seed()
    try:
        tok = requests.post(f"{API}/auth/login",
                              json={"email": EMAIL, "password": "password123"},
                              timeout=10).json()["access_token"]
        r = requests.get(f"{API}/payments/stripe/payment-methods/{CUST_ID}",
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "payment_methods" in body
        assert body["customer_id"] == CUST_ID
    finally:
        _cleanup()


def test_undefined_customer_id_returns_403_not_500():
    """The pre-fix URL ``.../payment-methods/undefined`` MUST be
    rejected at the auth guard (never hit Stripe / never leak a
    stack trace). Confirms the "Not allowed" message the user saw
    is the correct auth denial — nothing further to fix on the
    backend for this pathology."""
    _seed()
    try:
        tok = requests.post(f"{API}/auth/login",
                              json={"email": EMAIL, "password": "password123"},
                              timeout=10).json()["access_token"]
        r = requests.get(f"{API}/payments/stripe/payment-methods/undefined",
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=10)
        assert r.status_code == 403
        assert r.json().get("detail") == "Not allowed"
    finally:
        _cleanup()
