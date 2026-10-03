"""Phase 2 · Feb-2026 · Quote-to-Lead Recipient — picker search endpoint."""
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
    import routers.quote_recipients as _qr
    _qr.db = _DB


_patch_db_everywhere()

PREFIX = f"ph2sch-{uuid4().hex[:8]}"
TENANT_A = f"{PREFIX}-tenant-a"
TENANT_B = f"{PREFIX}-tenant-b"


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    await _DB.customers.delete_many({"$or": [{"id": rx}, {"tenant_id": rx}]})
    await _DB.leads.delete_many({"$or": [{"id": rx}, {"tenant_id": rx}]})


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())
    yield
    _run(_cleanup())


_ADMIN = {"id": f"{PREFIX}-u-admin", "role": "admin"}


async def _seed_many(tid, customers=(), leads=()):
    for row in customers:
        await _DB.customers.insert_one({"tenant_id": tid, **row})
    for row in leads:
        await _DB.leads.insert_one({"tenant_id": tid, **row})


def test_returns_customers():
    _run(_seed_many(TENANT_A, customers=[
        {"id": f"{PREFIX}-c-1", "name": "Alice Angler",
         "email": "alice@ex.com", "phone": "480-555-1111"}]))
    from routers.quote_recipients import search_quote_recipients
    rows = _run(search_quote_recipients(q="Alice", limit=20,
        user=_ADMIN, tenant={"id": TENANT_A}))
    assert any(r["kind"] == "customer" and r["id"] == f"{PREFIX}-c-1"
                 for r in rows)


def test_returns_leads():
    _run(_seed_many(TENANT_A, leads=[
        {"id": f"{PREFIX}-l-1", "name": "Larry Lead",
         "email": "larry@ex.com", "phone": "480-555-2222"}]))
    from routers.quote_recipients import search_quote_recipients
    rows = _run(search_quote_recipients(q="Larry", limit=20,
        user=_ADMIN, tenant={"id": TENANT_A}))
    assert any(r["kind"] == "lead" and r["id"] == f"{PREFIX}-l-1"
                 for r in rows)


def test_filters_by_term_case_insensitive_across_fields():
    _run(_seed_many(TENANT_A,
        customers=[
            {"id": f"{PREFIX}-c-match", "name": "Beth Brown",
             "email": "SPECIAL@beth.io", "phone": "480-555-3333"},
            {"id": f"{PREFIX}-c-nomatch", "name": "Zara Zimmer",
             "email": "zara@ex.com", "phone": "480-555-9999"}],
        leads=[
            {"id": f"{PREFIX}-l-match", "name": "Buddy Beam",
             "email": "buddy@ex.com", "phone": "480-555-0001"},
            {"id": f"{PREFIX}-l-nomatch", "name": "Nina North",
             "email": "nina@ex.com", "phone": "480-555-7777"}]))
    from routers.quote_recipients import search_quote_recipients
    rows = _run(search_quote_recipients(q="special", limit=20,
        user=_ADMIN, tenant={"id": TENANT_A}))
    ids = {r["id"] for r in rows}
    assert f"{PREFIX}-c-match" in ids
    assert f"{PREFIX}-c-nomatch" not in ids
    rows2 = _run(search_quote_recipients(q="B", limit=20,
        user=_ADMIN, tenant={"id": TENANT_A}))
    ids2 = {r["id"] for r in rows2}
    assert f"{PREFIX}-c-match" in ids2
    assert f"{PREFIX}-l-match" in ids2


def test_tenant_scoped_never_leaks_cross_tenant():
    _run(_seed_many(TENANT_A,
        customers=[{"id": f"{PREFIX}-c-ta", "name": "Shared Name Cust"}],
        leads=[{"id": f"{PREFIX}-l-ta", "name": "Shared Name Lead"}]))
    _run(_seed_many(TENANT_B,
        customers=[{"id": f"{PREFIX}-c-tb", "name": "Shared Name Cust"}],
        leads=[{"id": f"{PREFIX}-l-tb", "name": "Shared Name Lead"}]))
    from routers.quote_recipients import search_quote_recipients
    rows = _run(search_quote_recipients(q="Shared", limit=20,
        user=_ADMIN, tenant={"id": TENANT_A}))
    ids = {r["id"] for r in rows}
    assert ids == {f"{PREFIX}-c-ta", f"{PREFIX}-l-ta"}


def test_empty_term_returns_default_list():
    _run(_seed_many(TENANT_A,
        customers=[{"id": f"{PREFIX}-c-{i}", "name": f"Cust {i}"}
                    for i in range(3)],
        leads=[{"id": f"{PREFIX}-l-{i}", "name": f"Lead {i}"}
                 for i in range(3)]))
    from routers.quote_recipients import search_quote_recipients
    rows = _run(search_quote_recipients(q="", limit=20,
        user=_ADMIN, tenant={"id": TENANT_A}))
    kinds = [r["kind"] for r in rows]
    assert "customer" in kinds
    assert "lead" in kinds
    first_lead = next(i for i, k in enumerate(kinds) if k == "lead")
    last_customer = max(i for i, k in enumerate(kinds) if k == "customer")
    assert last_customer < first_lead


def test_respects_limit_cap():
    _run(_seed_many(TENANT_A,
        customers=[{"id": f"{PREFIX}-c-{i}", "name": f"Cust {i}"}
                    for i in range(8)],
        leads=[{"id": f"{PREFIX}-l-{i}", "name": f"Lead {i}"}
                 for i in range(8)]))
    from routers.quote_recipients import search_quote_recipients
    rows = _run(search_quote_recipients(q="", limit=6,
        user=_ADMIN, tenant={"id": TENANT_A}))
    assert len(rows) == 6
