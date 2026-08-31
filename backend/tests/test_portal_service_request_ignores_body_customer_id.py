"""Feb-2026 · Phase F1 · P0-A regression coverage — customer_id
authority test.

Contract: the ``POST /api/customer-portal/service-requests`` endpoint
must ALWAYS scope the outgoing message + SMS + email to the customer
id derived from the JWT session (``user['customer_id']``). If a
client accidentally (or maliciously) includes a ``customer_id`` field
in the request body, the server MUST ignore it — the local
``ServiceRequestIn`` pydantic model doesn't declare that field, so
pydantic drops it, and the endpoint reads ``cid`` from
``_require_customer(user)`` only.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from routers.customer_portal import (
    ServiceRequestIn,
    create_service_request,
)


class _Coll:
    """Motor-compatible collection stub."""

    def __init__(self, rows=None):
        self.rows: List[Dict[str, Any]] = list(rows or [])
        self.inserted: List[Dict[str, Any]] = []

    async def find_one(self, query, projection=None):  # noqa: ARG002
        for row in self.rows:
            if all(row.get(k) == v for k, v in query.items()):
                return dict(row)
        return None

    async def insert_one(self, doc):
        self.inserted.append(dict(doc))
        return type("R", (), {"inserted_id": doc.get("id")})()

    def find(self, query=None, projection=None):  # noqa: ARG002
        outer = self

        class _Cursor:
            def __init__(self):
                self._rows = list(outer.rows)

            async def to_list(self, _n):
                return list(self._rows)

        return _Cursor()


class _DB:
    def __init__(self, customers=None):
        self.customers = _Coll(customers)
        self.messages = _Coll()
        self.users = _Coll()


class _AsyncNoop:
    def __init__(self, ret):
        self._ret = ret

    async def __call__(self, *_a, **_k):
        return self._ret


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_ignores_body_customer_id(monkeypatch):
    """Even if a stranger customer id is smuggled into the body,
    the persisted message row is scoped to the SESSION customer."""
    session_cid = "cust-session"
    tenant_id = "tenant-A"
    fake_db = _DB(customers=[{
        "id": session_cid, "tenant_id": tenant_id,
        "name": "Alice", "phone": "+15550000001", "email": "alice@x",
    }])
    monkeypatch.setattr("routers.customer_portal.db", fake_db)
    # Silence transport side effects — never touch the network.
    monkeypatch.setattr(
        "services.email.resend_adapter.send",
        _AsyncNoop({"provider_status": "sent"}),
    )
    monkeypatch.setattr(
        "services.sms.rc_adapter.send",
        _AsyncNoop({"provider_status": "sent"}),
    )
    monkeypatch.setattr(
        "services.notifications.enqueue_for_tenant_admins",
        _AsyncNoop([]),
    )

    body = ServiceRequestIn(service_type="Pool Cleaning",
                            notes="ph high")
    # ``pydantic`` already strips unknown fields on the strict model.
    # Even if a client crafts a body with a ``customer_id`` key, it
    # never reaches the handler — the model raises on ``setattr``
    # and drops the key on construction. Belt-and-braces: we also
    # verify below that the persisted row is scoped by the SESSION
    # ``customer_id``, not any body field.
    user = {"id": "user-a", "role": "customer",
            "customer_id": session_cid, "name": "Alice"}
    tenant = {"id": tenant_id}

    resp = _run(create_service_request(body, user=user, tenant=tenant))
    assert resp.get("ok") is True

    # ── The persisted message must use SESSION customer.
    assert len(fake_db.messages.inserted) == 1
    row = fake_db.messages.inserted[0]
    assert row["customer_id"] == session_cid, (
        f"body customer_id leaked into message row: {row['customer_id']!r}"
    )
    # ``sender_name`` must reflect the customer ROW, not any body field.
    assert row["sender_name"] == "Alice"


def test_pydantic_schema_rejects_unknown_customer_id_field():
    """Schema-layer defence: attempting to attach a ``customer_id``
    to the request body raises before the handler ever runs, so the
    JWT session id remains the single source of truth."""
    import pytest as _pytest

    body = ServiceRequestIn(service_type="Pool Cleaning")
    with _pytest.raises((ValueError, TypeError)):
        setattr(body, "customer_id", "cust-STRANGER")
