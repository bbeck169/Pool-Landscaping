"""TD-lead-profile-z3 (Ticket Z3 BE) · Feb-2026 — Quote-sent timeline emission.

Z3 ships a single-concern BE change on ``POST /quotes/{qid}/send-to-
customer``: when the quote recipient is a lead, also emit a
``lead_communications`` row so the Z4 Overview ▾ timeline on
``/leads/:id`` surfaces the quote send alongside the SMS + email
rows.  Customer-recipient sends continue to surface on
``audit_logs`` only.

Cases:
  1. Lead-recipient quote send → one ``lead_communications`` row
     with ``channel="email"``, ``type="quote_sent"``, ``status="sent"``,
     ``lead_id=<lid>``, ``quote_id=<qid>``, subject == quote title.
  2. Customer-recipient quote send → NO ``lead_communications`` row
     written (regression lock on existing customer-only behaviour).
  3. Lead-recipient send with email transport failure → row still
     written with ``status="failed"`` + ``error="transport_failed"``.

Loop-isolation + ``_patch_db_everywhere`` pattern mirrors
``test_lead_create_quote.py``.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_ENV = {k: (v.strip().strip('"').strip("'") if isinstance(v, str) else v)
        for k, v in _ENV.items()}
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _patch_db_everywhere():
    import config
    config.db = _DB
    for mod in (
        "routers.quotes", "routers.leads", "routers.estimates",
        "routers.estimate_viewer", "services.recipient",
        "routers.lead_communications",
    ):
        __import__(mod)
        import sys as _sys
        _sys.modules[mod].db = _DB


PREFIX = f"z3qts-{uuid4().hex[:8]}"
TENANT_A = f"{PREFIX}-tenant-a"


async def _seed_tenant(tid):
    await _DB.tenants.insert_one({
        "id": tid, "name": f"Tenant {tid}",
        "timezone": "America/Phoenix", "settings": {},
        "support_email": "support@example.com",
    })


async def _seed_lead(lid, tid, *, email="larry@example.com"):
    await _DB.leads.insert_one({
        "id": lid, "tenant_id": tid, "name": "Larry Lead",
        "email": email, "phone": "480-555-0001",
        "service_address": "100 Palo Verde Way",
        "address": "100 Palo Verde Way",
        "status": "new", "source": "admin_manual",
        "timeline": [], "notes": "",
    })


async def _seed_customer(cid, tid, *, email="carla@example.com"):
    await _DB.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": "Carla Cust",
        "email": email, "phone": "480-555-0002",
    })


async def _seed_quote(qid, tid, *, recipient_type, recipient_id,
                        quote_number="Q-1001", title="Pool Resurface",
                        status="sent"):
    """Seed a quote already in ``sent`` state so the handler skips
    the mark-sent flip and we test only the comm-log emission."""
    await _DB.quotes.insert_one({
        "id": qid, "tenant_id": tid,
        "customer_id": None if recipient_type == "lead" else recipient_id,
        "recipient_type": recipient_type,
        "recipient_id": recipient_id,
        "title": title, "quote_number": quote_number,
        "doc_type": "quote", "status": status,
        "sent_at": "2026-02-12T10:00:00Z",
        "line_items": [], "tax_rate": 0.0,
        "created_at": "2026-02-12T09:00:00Z",
    })


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in ("quotes", "customers", "leads", "audit_logs",
                 "lead_communications", "tenants"):
        await _DB[coll].delete_many(
            {"$or": [{"id": rx}, {"tenant_id": rx}]},
        )


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())
    yield
    _run(_cleanup())


_ADMIN = {"id": f"{PREFIX}-u-admin", "role": "admin"}


async def _send(qid, *, email_sent=True, override_email=None):
    """Invoke the handler directly with the email transport mocked."""
    from routers.quotes import send_quote_to_customer, _SendToCustomerIn
    body = _SendToCustomerIn(recipient_email=override_email)
    tenant_doc = await _DB.tenants.find_one({"id": TENANT_A}, {"_id": 0})
    with patch("routers.quotes.send_estimate_reminder_email",
                new=AsyncMock(return_value=email_sent)):
        return await send_quote_to_customer(
            qid=qid, body=body, user=_ADMIN, tenant=tenant_doc,
        )


# ═══════════════════════════════════════════════════════════════════
# 1. Lead-recipient send → lead_communications row written.
# ═══════════════════════════════════════════════════════════════════
def test_lead_recipient_send_emits_quote_sent_comm_row():
    lid = f"{PREFIX}-lead-1"
    qid = f"{PREFIX}-q-1"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid, TENANT_A))
    _run(_seed_quote(qid, TENANT_A,
                        recipient_type="lead", recipient_id=lid))

    out = _run(_send(qid, email_sent=True))
    assert out["email_sent"] is True

    rows = _run(
        _DB.lead_communications.find(
            {"tenant_id": TENANT_A, "lead_id": lid}, {"_id": 0},
        ).to_list(length=10),
    )
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["channel"] == "email"
    assert row["type"] == "quote_sent"
    assert row["status"] == "sent"
    assert row["direction"] == "outbound"
    assert row["quote_id"] == qid
    assert row["lead_id"] == lid
    assert row["subject"] == "Pool Resurface"
    assert "Q-1001" in (row["body"] or "")
    assert "larry@example.com" in (row["body"] or "")
    assert row.get("error") is None


# ═══════════════════════════════════════════════════════════════════
# 2. Customer-recipient send → NO lead_communications row written.
# ═══════════════════════════════════════════════════════════════════
def test_customer_recipient_send_does_not_emit_lead_comm_row():
    cid = f"{PREFIX}-cust-1"
    qid = f"{PREFIX}-q-2"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_customer(cid, TENANT_A))
    _run(_seed_quote(qid, TENANT_A,
                        recipient_type="customer", recipient_id=cid))

    out = _run(_send(qid, email_sent=True))
    assert out["email_sent"] is True

    rows = _run(
        _DB.lead_communications.find(
            {"tenant_id": TENANT_A}, {"_id": 0},
        ).to_list(length=10),
    )
    assert rows == []


# ═══════════════════════════════════════════════════════════════════
# 3. Lead send with email transport failure → row written as failed.
# ═══════════════════════════════════════════════════════════════════
def test_lead_recipient_send_failure_writes_failed_row():
    lid = f"{PREFIX}-lead-3"
    qid = f"{PREFIX}-q-3"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid, TENANT_A))
    _run(_seed_quote(qid, TENANT_A,
                        recipient_type="lead", recipient_id=lid))

    out = _run(_send(qid, email_sent=False))
    assert out["email_sent"] is False

    rows = _run(
        _DB.lead_communications.find(
            {"tenant_id": TENANT_A, "lead_id": lid}, {"_id": 0},
        ).to_list(length=10),
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "failed"
    assert row["error"] == "transport_failed"
    assert row["type"] == "quote_sent"
    assert row["quote_id"] == qid
