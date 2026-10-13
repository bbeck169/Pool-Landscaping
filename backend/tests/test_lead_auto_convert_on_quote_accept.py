"""P2 #4 · Feb-2026 — ``lead.converted_via_quote`` + auto-convert pytest.

Locks three invariants on quote accept (``_mark_accepted``):
  1. First accept of a lead-recipient quote funnels the lead through
     ``_run_close_won_pipeline`` → lead flips to ``closed_won``, a
     customer is materialized, and the quote is reparented.
  2. The transition emits exactly one ``audit_logs`` row
     ``event="lead.converted_via_quote"``.
  3. A SECOND accept-like call (via the same helper) is a no-op —
     the pipeline is idempotent and NO additional audit row is written.

The reparent itself (quote.recipient_type: "lead" → "customer") is
exercised in ``test_lead_create_quote.py`` already; this file focuses
on the accept-triggered auto-conversion path.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
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
    for mod in ("routers.quotes", "routers.leads", "routers.estimates",
                "routers.reports", "routers.estimate_viewer",
                "services.invoice_builder",
                "services.invoice_numbering", "services.recipient",
                "services.lead_conversion_notifications",
                "routers.finances"):
        __import__(mod)
        import sys as _sys
        _sys.modules[mod].db = _DB


PREFIX = f"p24b-{uuid4().hex[:8]}"
TENANT = f"{PREFIX}-tenant"
ADMIN = {"id": f"{PREFIX}-u-admin", "role": "admin"}


async def _seed_tenant(tid):
    await _DB.tenants.insert_one({"id": tid, "name": f"Tenant {tid}",
        "timezone": "America/Phoenix", "settings": {}})


async def _seed_lead(lid, tid, name="Larry Lead"):
    await _DB.leads.insert_one({
        "id": lid, "tenant_id": tid, "name": name,
        "email": "larry@example.com", "phone": "480-555-0001",
        "service_address": "100 Palo Verde Way", "address": "100 Palo Verde Way",
        "status": "new", "source": "admin_manual",
        "timeline": [], "notes": "",
    })


async def _seed_lead_recipient_quote(qid, tid, lid, name="Larry Lead"):
    await _DB.quotes.insert_one({
        "id": qid, "tenant_id": tid, "doc_type": "quote",
        "customer_id": None, "customer_name": name,
        "recipient_type": "lead", "recipient_id": lid,
        "line_items": [{"description": "x", "quantity": 1,
                          "unit_price": 100.0, "category": ""}],
        "subtotal": 100.0, "tax": 0.0, "total": 100.0,
        "amount_paid": 0.0, "status": "sent", "payment_status": "unpaid",
        "created_at": "2026-02-10T00:00:00+00:00",
    })


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in ("quotes", "customers", "leads", "audit_logs",
                 "marketing_deliveries", "marketing_drip_enrollments",
                 "sales_sequences", "outbound_emails",
                 "tenant_pay_notifications"):
        await _DB[coll].delete_many(
            {"$or": [{"id": rx}, {"tenant_id": rx},
                     {"entity_id": rx}, {"lead_id": rx}, {"quote_id": rx}]},
        )
    await _DB.tenants.delete_many({"id": rx})


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())
    yield
    _run(_cleanup())


def _patch_notifications_noop():
    """fire_welcome_bundle imports Resend / RC adapter at call-time.
    Monkeypatch to a no-op so the pipeline stays hermetic in CI."""
    import services.lead_conversion_notifications as _m
    import sys

    async def _fake(**kw):
        return {"email_id": None, "sms_id": None, "drip_enrollment_id": None}

    _m.fire_welcome_bundle = _fake
    sys.modules["services.lead_conversion_notifications"].fire_welcome_bundle = _fake


def test_accept_lead_recipient_quote_converts_lead_and_audits():
    _patch_notifications_noop()
    lid = f"{PREFIX}-lead-conv"
    qid = f"{PREFIX}-q-conv"
    _run(_seed_tenant(TENANT))
    _run(_seed_lead(lid, TENANT))
    _run(_seed_lead_recipient_quote(qid, TENANT, lid))
    est = _run(_DB.quotes.find_one({"id": qid}, {"_id": 0}))
    from routers.estimate_viewer import _mark_accepted
    _run(_mark_accepted(est, TENANT, ADMIN["id"]))
    # Lead flipped to closed_won + has converted_customer_id
    lead_after = _run(_DB.leads.find_one({"id": lid}, {"_id": 0}))
    assert lead_after is not None
    _status = (lead_after.get("status") or "").lower().replace(" ", "_")
    assert _status == "closed_won", f"status was {lead_after.get('status')!r}"
    assert lead_after.get("converted_customer_id")
    # Reparent happened on the quote
    quote_after = _run(_DB.quotes.find_one({"id": qid}, {"_id": 0}))
    assert quote_after["recipient_type"] == "customer"
    assert quote_after["recipient_id"] == lead_after["converted_customer_id"]
    assert quote_after["customer_id"] == lead_after["converted_customer_id"]
    assert quote_after.get("converted_from_lead_id") == lid
    # Exactly one audit row
    rows = _run(_DB.audit_logs.find({
        "tenant_id": TENANT, "event": "lead.converted_via_quote",
        "lead_id": lid,
    }, {"_id": 0}).to_list(10))
    assert len(rows) == 1
    row = rows[0]
    assert row["quote_id"] == qid
    assert row["entity_kind"] == "lead"
    assert row["entity_id"] == lid
    assert row["actor_user_id"] == ADMIN["id"]


def test_second_accept_on_already_converted_lead_is_idempotent():
    _patch_notifications_noop()
    lid = f"{PREFIX}-lead-idemp"
    qid = f"{PREFIX}-q-idemp"
    _run(_seed_tenant(TENANT))
    _run(_seed_lead(lid, TENANT))
    _run(_seed_lead_recipient_quote(qid, TENANT, lid))
    est = _run(_DB.quotes.find_one({"id": qid}, {"_id": 0}))
    from routers.estimate_viewer import _mark_accepted
    # First accept converts
    _run(_mark_accepted(est, TENANT, ADMIN["id"]))
    # Re-read the quote (reparent has flipped recipient_type → customer).
    # Call _mark_accepted again with the fresh doc; the lead-branch
    # won't fire because recipient_type != "lead" anymore. But to
    # exercise the pipeline idempotency path directly we simulate the
    # case where a stale est with recipient_type="lead" is replayed.
    _run(_mark_accepted(est, TENANT, ADMIN["id"]))
    rows = _run(_DB.audit_logs.find({
        "tenant_id": TENANT, "event": "lead.converted_via_quote",
        "lead_id": lid,
    }, {"_id": 0}).to_list(10))
    # Still exactly one — the second call short-circuited inside the
    # pipeline (converted_customer_id already set) and no row was emitted.
    assert len(rows) == 1


def test_customer_recipient_quote_accept_does_not_touch_leads_or_audit():
    _patch_notifications_noop()
    cid = f"{PREFIX}-cust-plain"
    qid = f"{PREFIX}-q-plain"
    _run(_seed_tenant(TENANT))
    _run(_DB.customers.insert_one({
        "id": cid, "tenant_id": TENANT, "name": "Plain Jane",
        "email": "jane@example.com",
    }))
    _run(_DB.quotes.insert_one({
        "id": qid, "tenant_id": TENANT, "doc_type": "quote",
        "customer_id": cid, "customer_name": "Plain Jane",
        "recipient_type": "customer", "recipient_id": cid,
        "line_items": [], "subtotal": 100.0, "tax": 0.0, "total": 100.0,
        "amount_paid": 0.0, "status": "sent", "payment_status": "unpaid",
    }))
    est = _run(_DB.quotes.find_one({"id": qid}, {"_id": 0}))
    from routers.estimate_viewer import _mark_accepted
    _run(_mark_accepted(est, TENANT, ADMIN["id"]))
    count = _run(_DB.audit_logs.count_documents({
        "tenant_id": TENANT, "event": "lead.converted_via_quote",
    }))
    assert count == 0
