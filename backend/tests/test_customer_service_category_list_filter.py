"""P2 #6 · Feb-2026 — GET /customers?service_category=<key> pytest.

Locks four invariants on the list-filter chip integration:
  1. ``?service_category=pool`` returns only customers with
     service_category=="pool" scoped to tenant.
  2. ``?service_category=unset`` returns customers with
     service_category=None OR field-missing.
  3. ``?service_category=invalid-value`` silently passes (list
     unchanged — guards against bookmarked legacy URLs 400'ing).
  4. Composes as AND with existing filters: when combined with
     ``is_active=True``, only pool+active rows return.
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
    for mod in ("routers.customers", "routers.properties"):
        __import__(mod)
        import sys as _sys
        _sys.modules[mod].db = _DB


PREFIX = f"p26b-{uuid4().hex[:8]}"
TENANT_A = f"{PREFIX}-tenant-a"
ADMIN = {"id": f"{PREFIX}-u-admin", "role": "admin"}


async def _seed_batch():
    await _DB.tenants.insert_one({"id": TENANT_A, "name": "T",
        "timezone": "America/Phoenix", "settings": {}})
    rows = [
        {"id": f"{PREFIX}-c-pool-1", "name": "Pool A",
         "service_category": "pool", "is_active": True},
        {"id": f"{PREFIX}-c-pool-2", "name": "Pool B",
         "service_category": "pool", "is_active": False},
        {"id": f"{PREFIX}-c-land-1", "name": "Land A",
         "service_category": "landscaping", "is_active": True},
        {"id": f"{PREFIX}-c-both-1", "name": "Both A",
         "service_category": "both", "is_active": True},
        {"id": f"{PREFIX}-c-unset-1", "name": "Unset A",
         "service_category": None, "is_active": True},
        {"id": f"{PREFIX}-c-unset-2", "name": "Unset B",
         "is_active": True},  # field missing
    ]
    for r in rows:
        r["tenant_id"] = TENANT_A
        await _DB.customers.insert_one(r)


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    await _DB.customers.delete_many({"$or": [{"id": rx}, {"tenant_id": rx}]})
    await _DB.tenants.delete_many({"id": rx})


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())
    _run(_seed_batch())
    yield
    _run(_cleanup())


async def _list(**kwargs):
    from routers.customers import list_customers
    _defaults = dict(
        search=None, tag=None, tags=None, city=None, waitlisted=None,
        unscheduled=None, is_active=None, missing_card=None,
        missing_email=False, missing_phone=False, missing_address=False,
        portal_activated=None, portal_invited=None, first_access=None,
        portal_status=None, is_muted=None, service_category=None,
        has_payment_method=None, count_only=False,
        include_deleted=False, include_merged=False,
        page=None, page_size=None, size=None, sort="created_desc",
        slim=None,
    )
    _defaults.update(kwargs)
    return await list_customers(
        user=ADMIN, tenant={"id": TENANT_A}, **_defaults,
    )


def _ids(items):
    return sorted(r.get("id") if isinstance(r, dict) else r["id"]
                    for r in items)


def test_filter_pool_returns_only_pool_customers():
    out = _run(_list(service_category="pool"))
    assert _ids(out) == sorted([f"{PREFIX}-c-pool-1", f"{PREFIX}-c-pool-2"])


def test_filter_unset_returns_null_and_missing():
    out = _run(_list(service_category="unset"))
    assert _ids(out) == sorted([f"{PREFIX}-c-unset-1", f"{PREFIX}-c-unset-2"])


def test_filter_invalid_value_silently_passes():
    out = _run(_list(service_category="bogus"))
    # All 6 seeded rows pass (silently ignored).
    assert len(out) == 6


def test_composes_with_is_active_and_filter():
    out = _run(_list(service_category="pool", is_active=True))
    assert _ids(out) == [f"{PREFIX}-c-pool-1"]
