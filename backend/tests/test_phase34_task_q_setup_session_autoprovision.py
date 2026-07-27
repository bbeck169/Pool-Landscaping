"""Phase 34 · Task Q · Feb-2026 — auto-provision self-heal for the
``/payments/setup-session`` endpoint.

Pins the regression the PLOFV owner hit on
``/portal/payment-method``: hitting Stripe SetupIntent as an
authenticated portal user whose ``users.customer_id`` was never
linked to a ``customers`` row used to raise
``HTTPException(404, "Customer not found")`` and hard-block the
add-a-card flow. The fix (see ``routers/payments.py``:
``_auto_provision_customer_for_user`` +
``_get_or_create_stripe_customer(fallback_user=...)``) self-heals by
either reusing an existing customer row that matches the auth-user
email in the same tenant, or minting a fresh one — then back-links
``users.customer_id`` so subsequent lookups short-circuit.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch, MagicMock


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeCollection:
    def __init__(self):
        self.docs: list[dict] = []

    async def find_one(self, query, projection=None):  # noqa: ARG002
        for d in self.docs:
            if self._matches(d, query):
                return dict(d)
        return None

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return MagicMock(inserted_id="fake")

    async def update_one(self, query, update):
        for d in self.docs:
            if self._matches(d, query):
                d.update((update.get("$set") or {}))
                return MagicMock(modified_count=1)
        return MagicMock(modified_count=0)

    @staticmethod
    def _matches(doc: dict, query: dict) -> bool:
        for k, v in query.items():
            if k == "$or":
                if not any(_FakeCollection._matches(doc, c) for c in v):
                    return False
                continue
            if isinstance(v, dict) and "$regex" in v:
                import re
                pat = v["$regex"]
                flags = re.IGNORECASE if "i" in (v.get("$options") or "") else 0
                if not re.search(pat, str(doc.get(k, "")), flags):
                    return False
            elif doc.get(k) != v:
                return False
        return True


class _FakeDB:
    def __init__(self):
        self.users = _FakeCollection()
        self.customers = _FakeCollection()


def test_setup_session_auto_provisions_missing_customer(monkeypatch):
    """Auth-user has NO linked customer row — the endpoint must
    auto-provision one and return a valid Stripe URL, never a 404."""
    from routers import payments as _pay

    fake_db = _FakeDB()
    _run(fake_db.users.insert_one({
        "id": "user-abc",
        "email": "orphan@example.com",
        "tenant_id": "tenant-xyz",
        "name": "Orphan Owner",
        "role": "super_admin",
    }))

    monkeypatch.setattr(_pay, "db", fake_db)
    # Stripe.Customer.create + checkout.Session.create both stubbed.
    monkeypatch.setattr(_pay.stripe, "api_key", "sk_test_fake")
    monkeypatch.setattr(_pay.stripe, "Customer", MagicMock(
        create=MagicMock(return_value=MagicMock(id="cus_fake_123")),
    ))
    fake_session = MagicMock(id="cs_fake_456", url="https://checkout.stripe.com/c/pay/cs_fake_456")
    monkeypatch.setattr(_pay.stripe.checkout, "Session", MagicMock(
        create=MagicMock(return_value=fake_session),
    ))
    # ``asyncio.to_thread`` shortcut for tests.
    async def _to_thread(fn, *a, **kw):
        return fn(*a, **kw)
    monkeypatch.setattr(_pay.asyncio, "to_thread", _to_thread)

    body = MagicMock(customer_id=None, return_url="https://x/y")
    user = _run(fake_db.users.find_one({"id": "user-abc"}))
    resp = _run(_pay.create_setup_session(body=body, user=user))

    assert resp["url"] == "https://checkout.stripe.com/c/pay/cs_fake_456"
    assert resp["session_id"] == "cs_fake_456"

    # The self-heal created a customer row AND back-linked users.customer_id.
    cust = _run(fake_db.customers.find_one({"email": "orphan@example.com"}))
    assert cust is not None
    assert cust["user_id"] == "user-abc"
    assert cust["stripe_customer_id"] == "cus_fake_123"
    updated_user = _run(fake_db.users.find_one({"id": "user-abc"}))
    assert updated_user["customer_id"] == cust["id"]


def test_setup_session_relinks_existing_customer_by_email(monkeypatch):
    """Auth-user has NO ``customer_id`` back-link, but a customers row
    with matching email already exists in the same tenant (the Brian
    case). The endpoint must reuse the row + back-link, NOT create a
    duplicate."""
    from routers import payments as _pay

    fake_db = _FakeDB()
    _run(fake_db.users.insert_one({
        "id": "user-brian",
        "email": "brian@plofv.com",
        "tenant_id": "tenant-plofv",
        "name": "Brian",
        "role": "super_admin",
    }))
    _run(fake_db.customers.insert_one({
        "id": "cust-brian-legacy",
        "tenant_id": "tenant-plofv",
        "email": "brian@plofv.com",
        "name": "brian beckman",
    }))

    monkeypatch.setattr(_pay, "db", fake_db)
    monkeypatch.setattr(_pay.stripe, "api_key", "sk_test_fake")
    monkeypatch.setattr(_pay.stripe, "Customer", MagicMock(
        create=MagicMock(return_value=MagicMock(id="cus_brian_stripe")),
    ))
    fake_session = MagicMock(id="cs_brian", url="https://checkout.stripe.com/c/pay/cs_brian")
    monkeypatch.setattr(_pay.stripe.checkout, "Session", MagicMock(
        create=MagicMock(return_value=fake_session),
    ))
    async def _to_thread(fn, *a, **kw):
        return fn(*a, **kw)
    monkeypatch.setattr(_pay.asyncio, "to_thread", _to_thread)

    body = MagicMock(customer_id=None, return_url="https://x/y")
    user = _run(fake_db.users.find_one({"id": "user-brian"}))
    resp = _run(_pay.create_setup_session(body=body, user=user))

    assert resp["url"].startswith("https://checkout.stripe.com")
    # Existing row was reused — no duplicate.
    all_brian_rows = [d for d in fake_db.customers.docs
                       if d.get("email") == "brian@plofv.com"]
    assert len(all_brian_rows) == 1
    assert all_brian_rows[0]["id"] == "cust-brian-legacy"
    # And it got back-linked to the auth-user.
    assert all_brian_rows[0]["user_id"] == "user-brian"
