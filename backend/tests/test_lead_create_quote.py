"""LEAD-CREATE-QUOTE · Feb-2026 — pytest end-to-end.

Phase B of LEAD-CREATE-QUOTE wires:
  1. A "Create Quote" button on the lead detail panel that opens
     the full quote builder pre-populated with the lead (frontend
     side — covered by vitest).
  2. Backend reparent inside ``_run_close_won_pipeline`` that
     flips every lead-recipient quote onto the new customer when
     the lead is converted.
  3. ``GET /leads/{lid}`` enriched with ``quotes_count`` for the
     button's badge.
  4. New index ``quotes.(tenant_id, recipient_type, recipient_id)``
     seeded by ``migrations/quotes_recipient_index_v1``.

Loop-isolation + ``_patch_db_everywhere`` pattern mirrors
``test_quote_lead_recipient.py`` so cross-file collection order
can't shadow our loop-bound ``_DB`` alias.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from fastapi import HTTPException
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


PREFIX = f"lcq-{uuid4().hex[:8]}"
TENANT_A = f"{PREFIX}-tenant-a"


async def _seed_tenant(tid):
    await _DB.tenants.insert_one({
        "id": tid, "name": f"Tenant {tid}",
        "timezone": "America/Phoenix", "settings": {},
    })


async def _seed_lead(lid, tid, *, name="Larry Lead",
                       email="larry@example.com", phone="480-555-0001",
                       address="100 Palo Verde Way"):
    await _DB.leads.insert_one({
        "id": lid, "tenant_id": tid, "name": name,
        "email": email, "phone": phone,
        "service_address": address, "address": address,
        "status": "new", "source": "admin_manual",
        "timeline": [], "notes": "",
    })


async def _seed_customer(cid, tid, name="Carla Cust"):
    await _DB.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": name,
        "email": "carla@example.com", "phone": "480-555-0002",
    })


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in ("quotes", "customers", "leads", "audit_logs",
                 "invoice_number_sequences", "settings", "properties"):
        await _DB[coll].delete_many(
            {"$or": [{"id": rx}, {"tenant_id": rx}]},
        )
    await _DB.tenants.delete_many({"id": rx})


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()  # re-pin before every test
    _run(_cleanup())
    yield
    _run(_cleanup())
    # Loop-isolation hygiene for sibling test files (notably
    # ``test_quote_lead_recipient.py``) that also call
    # ``create_quote`` → ``routers.income_categories`` →
    # ``routers.service_categories`` but do NOT patch those modules
    # in their own ``_patch_db_everywhere`` list.  Both modules
    # capture ``from config import db`` once at module-import time;
    # if OUR test triggers the first import, the sibling test
    # later finds a stale db pinned to our event loop.  Dropping
    # the modules from ``sys.modules`` forces the next
    # ``create_quote`` call-site to re-import them fresh against
    # the sibling's ``config.db`` + ``_LOOP``.
    import sys as _sys
    for _mod in (
        "routers.income_categories",
        "routers.service_categories",
    ):
        _sys.modules.pop(_mod, None)


_ADMIN = {"id": f"{PREFIX}-u-admin", "role": "admin"}
_MANAGER = {"id": f"{PREFIX}-u-mgr",   "role": "manager"}
_TECH = {"id": f"{PREFIX}-u-tech",     "role": "technician"}


async def _post_quote(user, **body_kwargs):
    from routers.quotes import create_quote
    from models import QuoteIn, LineItem
    tenant_id = body_kwargs.pop("_tenant", TENANT_A)
    line_items = body_kwargs.pop("line_items", None) or [
        LineItem(description="Service", quantity=1, unit_price=100.0),
    ]
    body_kwargs.setdefault("title", "Test")
    body = QuoteIn(line_items=line_items, **body_kwargs)
    return await create_quote(body, user=user,
                                 tenant={"id": tenant_id})


# ═══════════════════════════════════════════════════════════════════
# 1. POST /quotes with recipient_type=lead — role gate contract.
# ═══════════════════════════════════════════════════════════════════
def test_post_quote_lead_recipient_admin_ok():
    lid = f"{PREFIX}-lead-admin-ok"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid, TENANT_A))
    out = _run(_post_quote(_ADMIN, recipient_type="lead",
                              recipient_id=lid))
    assert out["recipient_type"] == "lead"
    assert out["recipient_id"] == lid
    assert out.get("customer_id") in (None, "")
    assert out["customer_name"] == "Larry Lead"


def test_post_quote_lead_recipient_manager_403():
    """``POST /quotes`` → ``require_admin`` — managers get 403.

    Mirrors the frontend ``isAdmin`` gate on the ``lead-create-quote``
    button; if this ever drifts the ROUTE-GUARD-AUDIT ticket catches
    it. The ``create_quote`` function body does not invoke the dep
    itself (FastAPI injects it on real HTTP), so this test calls
    ``require_admin`` directly against the manager user — same code
    path FastAPI runs before handing the call to ``create_quote``.
    """
    from utils import require_admin
    with pytest.raises(HTTPException) as exc:
        require_admin(user=_MANAGER)
    assert exc.value.status_code == 403


def test_post_quote_lead_recipient_technician_403():
    from utils import require_admin
    with pytest.raises(HTTPException) as exc:
        require_admin(user=_TECH)
    assert exc.value.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# 2. close-won reparent — lead-recipient quotes flip to customer.
# ═══════════════════════════════════════════════════════════════════
def test_close_won_reparents_lead_recipient_quotes():
    """All lead-recipient quotes get customer_id, recipient_type,
    recipient_id overwritten + ``converted_from_lead_id`` stamped."""
    lid = f"{PREFIX}-lead-reparent"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid, TENANT_A, name="Rhonda Reparent"))

    # Seed TWO lead-recipient quotes on the lead.
    q1 = _run(_post_quote(_ADMIN, recipient_type="lead",
                             recipient_id=lid))
    q2 = _run(_post_quote(_ADMIN, recipient_type="lead",
                             recipient_id=lid,
                             title="Second quote"))

    # Trigger close-won.
    from routers.leads import close_won
    _run(close_won(lid, user=_ADMIN, tenant={"id": TENANT_A}))

    # Re-fetch both docs — expect full reparent.
    for qid in (q1["id"], q2["id"]):
        after = _run(_DB.quotes.find_one(
            {"id": qid, "tenant_id": TENANT_A}, {"_id": 0}))
        assert after is not None, f"quote {qid} vanished"
        assert after["recipient_type"] == "customer", \
            f"quote {qid} recipient_type not flipped"
        assert after["converted_from_lead_id"] == lid, \
            f"quote {qid} missing converted_from_lead_id provenance"
        # The lead's close-won created / merged a customer — the
        # id must now live on all three customer-identity fields.
        new_cid = after["customer_id"]
        assert new_cid, f"quote {qid} customer_id still null"
        assert after["recipient_id"] == new_cid, \
            f"quote {qid} recipient_id != new customer_id"


def test_close_won_reparent_is_idempotent():
    """Running close-won TWICE must not double-reparent (also must
    not corrupt the quote back to recipient_type=lead on retry)."""
    lid = f"{PREFIX}-lead-idem"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid, TENANT_A, name="Isa Idempotent"))
    created = _run(_post_quote(_ADMIN, recipient_type="lead",
                                   recipient_id=lid))
    from routers.leads import close_won
    _run(close_won(lid, user=_ADMIN, tenant={"id": TENANT_A}))

    first_cid = _run(_DB.quotes.find_one(
        {"id": created["id"], "tenant_id": TENANT_A}, {"_id": 0}
    ))["customer_id"]

    # Second close-won — the pipeline short-circuits on
    # ``converted_customer_id`` so the quote stays as reparented.
    _run(close_won(lid, user=_ADMIN, tenant={"id": TENANT_A}))

    after = _run(_DB.quotes.find_one(
        {"id": created["id"], "tenant_id": TENANT_A}, {"_id": 0}))
    assert after["recipient_type"] == "customer"
    assert after["customer_id"] == first_cid
    assert after["recipient_id"] == first_cid
    assert after["converted_from_lead_id"] == lid


def test_close_won_does_not_touch_customer_recipient_quotes():
    """A pre-existing customer-recipient quote on a different
    customer MUST NOT be rewritten when a sibling lead is
    close-won."""
    lid = f"{PREFIX}-lead-safe"
    other_cid = f"{PREFIX}-cust-other"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid, TENANT_A))
    _run(_seed_customer(other_cid, TENANT_A, name="Other Customer"))

    # Seed a customer-recipient quote on the OTHER customer.
    other_quote = _run(_post_quote(_ADMIN, customer_id=other_cid))
    # Seed a lead-recipient quote on OUR lead.
    _run(_post_quote(_ADMIN, recipient_type="lead",
                        recipient_id=lid))

    from routers.leads import close_won
    _run(close_won(lid, user=_ADMIN, tenant={"id": TENANT_A}))

    # The OTHER customer's quote is untouched.
    unchanged = _run(_DB.quotes.find_one(
        {"id": other_quote["id"], "tenant_id": TENANT_A},
        {"_id": 0}))
    assert unchanged["recipient_type"] == "customer"
    assert unchanged["customer_id"] == other_cid
    assert unchanged["recipient_id"] == other_cid
    assert "converted_from_lead_id" not in unchanged, \
        "customer-recipient quote should NEVER get " \
        "converted_from_lead_id stamped"


# ═══════════════════════════════════════════════════════════════════
# 3. GET /leads/{lid} enrichment — quotes_count badge payload.
# ═══════════════════════════════════════════════════════════════════
def test_get_lead_returns_quotes_count_zero():
    lid = f"{PREFIX}-lead-count-0"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid, TENANT_A))
    from routers.leads import get_lead
    row = _run(get_lead(lid, user=_ADMIN,
                         tenant={"id": TENANT_A}))
    assert row["quotes_count"] == 0


def test_get_lead_returns_quotes_count_multiple():
    lid = f"{PREFIX}-lead-count-n"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid, TENANT_A))
    # Seed 3 lead-recipient quotes.
    for _ in range(3):
        _run(_post_quote(_ADMIN, recipient_type="lead",
                           recipient_id=lid))
    from routers.leads import get_lead
    row = _run(get_lead(lid, user=_ADMIN,
                         tenant={"id": TENANT_A}))
    assert row["quotes_count"] == 3


def test_get_lead_quotes_count_scoped_to_lead():
    """Count MUST only reflect THIS lead's quotes — a sibling
    lead's quotes don't leak into the badge."""
    lid_a = f"{PREFIX}-lead-count-a"
    lid_b = f"{PREFIX}-lead-count-b"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid_a, TENANT_A))
    _run(_seed_lead(lid_b, TENANT_A))
    _run(_post_quote(_ADMIN, recipient_type="lead", recipient_id=lid_a))
    _run(_post_quote(_ADMIN, recipient_type="lead", recipient_id=lid_a))
    _run(_post_quote(_ADMIN, recipient_type="lead", recipient_id=lid_b))

    from routers.leads import get_lead
    assert _run(get_lead(lid_a, user=_ADMIN,
                           tenant={"id": TENANT_A}))["quotes_count"] == 2
    assert _run(get_lead(lid_b, user=_ADMIN,
                           tenant={"id": TENANT_A}))["quotes_count"] == 1


# ═══════════════════════════════════════════════════════════════════
# 4. Migration — idempotency.
# ═══════════════════════════════════════════════════════════════════
def test_migration_quotes_recipient_index_idempotent():
    """Second run returns ``sentinel: present`` without touching
    the index catalogue a second time."""
    from migrations.quotes_recipient_index_v1 import run as _run_mig
    # Clear any sentinel from a prior test invocation first.
    _run(_DB["_migrations"].delete_many(
        {"id": "quotes_recipient_index_v1"},
    ))
    first = _run(_run_mig())
    assert first["sentinel"] == "stamped"
    assert first["name"] == "tenant_recipient"

    second = _run(_run_mig())
    assert second["sentinel"] == "present"
    assert second["created"] is False

    # Verify the compound index actually exists on the live
    # collection.
    names = []
    async def _collect():
        async for idx in _DB.quotes.list_indexes():
            names.append(idx["name"])
    _run(_collect())
    assert "tenant_recipient" in names, \
        "quotes_recipient_index_v1 did not create the index"
