"""P2 #4 · Feb-2026 — ``quote.created_from_lead`` audit log pytest.

Locks three invariants on ``POST /quotes``:
  1. Lead-recipient quote birth writes exactly one audit_logs row
     ``event="quote.created_from_lead"`` with tenant/lead/quote ids.
  2. Attribution ``source`` landed verbatim when supplied; defaults
     to ``"unknown"`` when the client omits the field.
  3. Customer-recipient quote birth writes NO such row.

Loop-isolation + ``_patch_db_everywhere`` pattern mirrors the sibling
``test_quote_lead_recipient.py`` + ``test_lead_create_quote.py`` so
cross-file pytest collection order can't shadow the loop-bound
``_DB`` alias.
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
                "routers.finances"):
        __import__(mod)
        import sys as _sys
        _sys.modules[mod].db = _DB


PREFIX = f"p24a-{uuid4().hex[:8]}"
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
    })


async def _seed_customer(cid, tid, name="Carla Cust"):
    await _DB.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": name,
        "email": "carla@example.com",
    })


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in ("quotes", "customers", "leads", "audit_logs",
                 "invoice_number_sequences", "settings", "properties"):
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


async def _post_quote(**body_kwargs):
    from routers.quotes import create_quote
    from models import QuoteIn, LineItem
    tenant_id = body_kwargs.pop("_tenant", TENANT)
    line_items = body_kwargs.pop("line_items", None) or [
        LineItem(description="Service", quantity=1, unit_price=100.0),
    ]
    body = QuoteIn(line_items=line_items, title="Test", **body_kwargs)
    return await create_quote(body, user=ADMIN, tenant={"id": tenant_id})


def test_lead_recipient_quote_emits_audit_row_with_supplied_source():
    lid = f"{PREFIX}-lead-a"
    _run(_seed_tenant(TENANT))
    _run(_seed_lead(lid, TENANT))
    out = _run(_post_quote(
        recipient_type="lead", recipient_id=lid,
        lead_attach_source="from_lead_button",
    ))
    rows = _run(_DB.audit_logs.find({
        "tenant_id": TENANT, "event": "quote.created_from_lead",
        "quote_id": out["id"],
    }, {"_id": 0}).to_list(10))
    assert len(rows) == 1, f"expected 1 audit row, got {len(rows)}"
    row = rows[0]
    assert row["lead_id"] == lid
    assert row["quote_id"] == out["id"]
    assert row["entity_kind"] == "quote"
    assert row["entity_id"] == out["id"]
    assert row["source"] == "from_lead_button"
    assert row["actor_user_id"] == ADMIN["id"]
    assert row.get("created_at")


def test_lead_recipient_quote_defaults_source_to_unknown():
    lid = f"{PREFIX}-lead-b"
    _run(_seed_tenant(TENANT))
    _run(_seed_lead(lid, TENANT))
    out = _run(_post_quote(recipient_type="lead", recipient_id=lid))
    row = _run(_DB.audit_logs.find_one({
        "tenant_id": TENANT, "event": "quote.created_from_lead",
        "quote_id": out["id"],
    }, {"_id": 0}))
    assert row is not None
    assert row["source"] == "unknown"


def test_customer_recipient_quote_emits_no_lead_audit_row():
    cid = f"{PREFIX}-cust-c"
    _run(_seed_tenant(TENANT))
    _run(_seed_customer(cid, TENANT))
    out = _run(_post_quote(customer_id=cid))
    count = _run(_DB.audit_logs.count_documents({
        "tenant_id": TENANT, "event": "quote.created_from_lead",
        "quote_id": out["id"],
    }))
    assert count == 0
