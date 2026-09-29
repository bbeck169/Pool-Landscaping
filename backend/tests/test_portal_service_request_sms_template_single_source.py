"""Feb-2026 · Phase F1 · P0-A regression coverage — SMS single source
of truth.

Contract: the outgoing SMS + email fired by
``POST /api/customer-portal/service-requests`` MUST pull the
customer's **name** and **phone** strictly from the customers-table
row (``db.customers`` scoped by ``session customer_id``). It must
NEVER fall back to the JWT session (``user.name``, ``user.phone``)
because a stale session paired with a fresh customer row produces
the P0-A crosswire (right phone, wrong name — or vice versa).

The endpoint also raises HTTP 500 when the session
``customer_id`` diverges from the resolved row's ``id`` — that is an
internal invariant violation, not a user error.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException

from routers.customer_portal import (
    ServiceRequestIn,
    create_service_request,
)


class _Coll:
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


class _Capture:
    """Async callable that records every call."""

    def __init__(self, ret=None):
        self.calls: List[Dict[str, Any]] = []
        self._ret = ret or {"provider_status": "sent"}

    async def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return self._ret


class _AsyncNoop:
    def __init__(self, ret=None):
        self._ret = ret

    async def __call__(self, *_a, **_k):
        return self._ret


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def wire_transports(monkeypatch):
    sms = _Capture()
    email = _Capture()
    monkeypatch.setattr("services.sms.rc_adapter.send", sms)
    monkeypatch.setattr("services.email.resend_adapter.send", email)
    monkeypatch.setattr(
        "services.notifications.enqueue_for_tenant_admins",
        _AsyncNoop([]),
    )
    return {"sms": sms, "email": email}


def test_sms_body_uses_customer_row_name_and_phone(monkeypatch, wire_transports):
    """Even when the session's ``user.name`` differs from the
    customer row (stale token / long-running session), the SMS must
    carry the CUSTOMER ROW's name and phone."""
    tenant_id = "t1"
    cid = "cust-1"
    fake_db = _DB(customers=[{
        "id": cid, "tenant_id": tenant_id,
        "name": "Alice Row", "phone": "+15550001111",
        "email": "alice@row",
    }])
    monkeypatch.setattr("routers.customer_portal.db", fake_db)

    user = {"id": "u1", "role": "customer", "customer_id": cid,
            "name": "STALE_NAME", "phone": "+15559999999"}
    body = ServiceRequestIn(service_type="Pool Cleaning",
                            request_details="ph high")

    resp = _run(create_service_request(
        body, user=user, tenant={
            "id": tenant_id,
            "settings": {
                "notifications": {
                    # PHONE-PURGE · Feb-2026 — tests must seed the
                    # tenant-configured SMS recipient explicitly; the
                    # source no longer falls back to a hardcoded
                    # plofv-internal number.  ``+15555550100`` is an
                    # RFC-5735 reserved fictional US number.
                    "service_request_sms": "+15555550100",
                },
            },
        },
    ))
    assert resp.get("ok") is True

    # ── SMS body must reflect the customer row, not the session.
    sms_calls = wire_transports["sms"].calls
    assert len(sms_calls) == 1, "sms adapter must be invoked exactly once"
    sms_body = sms_calls[0]["kwargs"]["body"]
    assert "Alice Row" in sms_body, (
        f"SMS did not use customer row name — body: {sms_body!r}"
    )
    assert "+15550001111" in sms_body, (
        f"SMS did not use customer row phone — body: {sms_body!r}"
    )
    assert "STALE_NAME" not in sms_body, (
        f"session name leaked into SMS body — {sms_body!r}"
    )
    assert "+15559999999" not in sms_body, (
        f"session phone leaked into SMS body — {sms_body!r}"
    )

    # ── Email subject / html must also draw name from the row.
    email_calls = wire_transports["email"].calls
    assert len(email_calls) == 1
    subject = email_calls[0]["kwargs"]["subject"]
    html = email_calls[0]["kwargs"]["html"]
    assert "Alice Row" in subject
    assert "STALE_NAME" not in subject
    assert "Alice Row" in html
    assert "+15550001111" in html


def test_identity_drift_raises_500(monkeypatch, wire_transports):
    """When the JWT session says customer_id=X but ``db.customers``
    returns a row with a different id, the endpoint MUST refuse
    (HTTP 500 — internal invariant violation) rather than ship the
    request under mismatched identity."""
    tenant_id = "t1"
    fake_db = _DB(customers=[])

    async def _drifted_find_one(query, projection=None):  # noqa: ARG001
        # Deliberately return a row whose id does NOT equal the
        # session's ``customer_id`` — simulates a corrupted or
        # leaked reference / stale JWT after a customer row swap.
        return {
            "id": "cust-DRIFT", "tenant_id": tenant_id,
            "name": "Wrong", "phone": "+15550002222",
        }
    fake_db.customers.find_one = _drifted_find_one  # type: ignore[assignment]
    monkeypatch.setattr("routers.customer_portal.db", fake_db)

    user = {"id": "u1", "role": "customer",
            "customer_id": "cust-1", "name": "Ignored"}
    body = ServiceRequestIn(service_type="Pool Cleaning")

    with pytest.raises(HTTPException) as exc_info:
        _run(create_service_request(
            body, user=user, tenant={"id": tenant_id},
        ))
    assert exc_info.value.status_code == 500, (
        f"expected 500 on identity drift, got {exc_info.value.status_code}"
    )
    # And no SMS/email must have gone out.
    assert wire_transports["sms"].calls == []
    assert wire_transports["email"].calls == []


def test_sms_body_omits_phone_when_customer_row_has_none(monkeypatch, wire_transports):
    """When the customer row has no phone we don't invent one from
    the session — the SMS just omits the parenthesised phone."""
    tenant_id = "t1"
    cid = "cust-1"
    fake_db = _DB(customers=[{
        "id": cid, "tenant_id": tenant_id,
        "name": "NoPhone Bob",
    }])
    monkeypatch.setattr("routers.customer_portal.db", fake_db)

    user = {"id": "u1", "role": "customer", "customer_id": cid,
            "name": "SessionName", "phone": "+15559999999"}
    body = ServiceRequestIn(service_type="Pool Cleaning")

    resp = _run(create_service_request(
        body, user=user, tenant={
            "id": tenant_id,
            "settings": {
                "notifications": {
                    # PHONE-PURGE · Feb-2026 — see the fixture in
                    # test_sms_body_uses_customer_row_name_and_phone
                    # above for the rationale.
                    "service_request_sms": "+15555550100",
                },
            },
        },
    ))
    assert resp.get("ok") is True

    sms_body = wire_transports["sms"].calls[0]["kwargs"]["body"]
    assert "NoPhone Bob" in sms_body
    # The session phone MUST NOT slip in as a fallback.
    assert "+15559999999" not in sms_body, (
        f"session phone leaked in when row had none — {sms_body!r}"
    )
