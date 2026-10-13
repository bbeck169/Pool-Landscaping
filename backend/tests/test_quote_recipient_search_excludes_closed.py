"""P2 #4 · Feb-2026 — ``/quote-recipients/search`` closed-lead filter pytest.

Locks three invariants on ``GET /api/quote-recipients/search``:
  1. Default call (``include_closed`` omitted) HIDES leads whose
     status ∈ {closed_won, closed_lost}.
  2. Explicit ``include_closed=true`` returns the full list,
     including closed leads — preserves the capability.
  3. Customers are never filtered by lead status (unrelated resource).

Loop-isolation mirrors the sibling P2 #4 pytests.
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
    for mod in ("routers.quote_recipients",):
        __import__(mod)
        import sys as _sys
        _sys.modules[mod].db = _DB


PREFIX = f"p24c-{uuid4().hex[:8]}"
TENANT = f"{PREFIX}-tenant"
ADMIN = {"id": f"{PREFIX}-u-admin", "role": "admin"}


async def _seed_tenant(tid):
    await _DB.tenants.insert_one({"id": tid, "name": f"Tenant {tid}",
        "timezone": "America/Phoenix", "settings": {}})


async def _seed_lead(lid, tid, name, status="new"):
    await _DB.leads.insert_one({
        "id": lid, "tenant_id": tid, "name": name,
        "email": f"{name.lower().replace(' ', '')}@example.com",
        "phone": "480-555-0100",
        "status": status, "source": "admin_manual",
    })


async def _seed_customer(cid, tid, name):
    await _DB.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": name,
        "email": f"{name.lower().replace(' ', '')}@example.com",
    })


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in ("customers", "leads"):
        await _DB[coll].delete_many(
            {"$or": [{"id": rx}, {"tenant_id": rx}]},
        )
    await _DB.tenants.delete_many({"id": rx})


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())
    yield
    _run(_cleanup())


async def _search(q="", include_closed=False, limit=20):
    from routers.quote_recipients import search_quote_recipients
    return await search_quote_recipients(
        q=q, limit=limit, include_closed=include_closed,
        user=ADMIN, tenant={"id": TENANT},
    )


def test_default_excludes_closed_won_and_closed_lost_leads():
    _run(_seed_tenant(TENANT))
    _run(_seed_lead(f"{PREFIX}-l-open", TENANT, "Zed Opener", status="new"))
    _run(_seed_lead(f"{PREFIX}-l-contacted", TENANT,
                       "Zed Contacted", status="contacted"))
    _run(_seed_lead(f"{PREFIX}-l-won", TENANT,
                       "Zed Won", status="closed_won"))
    _run(_seed_lead(f"{PREFIX}-l-lost", TENANT,
                       "Zed Lost", status="closed_lost"))
    out = _run(_search(q="Zed"))
    kinds_by_name = {r["display_name"]: r["kind"] for r in out}
    assert "Zed Opener" in kinds_by_name
    assert "Zed Contacted" in kinds_by_name
    assert "Zed Won" not in kinds_by_name
    assert "Zed Lost" not in kinds_by_name


def test_include_closed_true_returns_full_list_including_closed_leads():
    _run(_seed_tenant(TENANT))
    _run(_seed_lead(f"{PREFIX}-l-open2", TENANT, "Yan Opener", status="new"))
    _run(_seed_lead(f"{PREFIX}-l-won2", TENANT,
                       "Yan Won", status="closed_won"))
    _run(_seed_lead(f"{PREFIX}-l-lost2", TENANT,
                       "Yan Lost", status="closed_lost"))
    out = _run(_search(q="Yan", include_closed=True))
    names = {r["display_name"] for r in out}
    assert {"Yan Opener", "Yan Won", "Yan Lost"} <= names


def test_customers_not_affected_by_lead_status_filter():
    _run(_seed_tenant(TENANT))
    _run(_seed_customer(f"{PREFIX}-c-x", TENANT, "Xavier Customer"))
    # Default call — customer still present even with lead-side filter on.
    out = _run(_search(q="Xavier"))
    kinds_by_name = {r["display_name"]: r["kind"] for r in out}
    assert kinds_by_name.get("Xavier Customer") == "customer"
