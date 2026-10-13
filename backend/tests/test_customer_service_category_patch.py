"""P2 #6 · Feb-2026 — PATCH /customers/{cid}/service-category pytest.

Locks six invariants:
  1. Happy path: null → "pool" stamps the value AND writes exactly
     one audit_logs row event="customer.service_category_changed"
     with {customer_id, from=None, to="pool", actor_user_id}.
  2. No-op PATCH (same value in and out) is idempotent — no write,
     no audit row.
  3. Explicit null body clears a previously-set category + emits
     audit row from->null transition.
  4. Invalid value → 400.
  5. 404 on unknown or cross-tenant customer id.
  6. Values are normalized to lowercase before validation ("Pool"
     → "pool" lands cleanly without a 400).
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
    for mod in ("routers.customers",):
        __import__(mod)
        import sys as _sys
        _sys.modules[mod].db = _DB


PREFIX = f"p26a-{uuid4().hex[:8]}"
TENANT_A = f"{PREFIX}-tenant-a"
TENANT_B = f"{PREFIX}-tenant-b"
ADMIN = {"id": f"{PREFIX}-u-admin", "role": "admin"}


async def _seed(tid, cid, category=None):
    await _DB.tenants.insert_one({"id": tid, "name": f"Tenant {tid}",
        "timezone": "America/Phoenix", "settings": {}})
    doc = {"id": cid, "tenant_id": tid, "name": "C", "is_active": True}
    if category is not None:
        doc["service_category"] = category
    await _DB.customers.insert_one(doc)


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in ("customers", "audit_logs"):
        await _DB[coll].delete_many({"$or": [
            {"id": rx}, {"tenant_id": rx}, {"customer_id": rx},
            {"entity_id": rx},
        ]})
    await _DB.tenants.delete_many({"id": rx})


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())
    yield
    _run(_cleanup())


async def _patch(cid, value, tid=TENANT_A):
    from routers.customers import (
        patch_customer_service_category, _ServiceCategoryPatch,
    )
    return await patch_customer_service_category(
        cid, _ServiceCategoryPatch(service_category=value),
        user=ADMIN, tenant={"id": tid},
    )


def test_happy_path_null_to_pool_stamps_and_audits():
    cid = f"{PREFIX}-cust-a"
    _run(_seed(TENANT_A, cid, category=None))
    out = _run(_patch(cid, "pool"))
    assert out["service_category"] == "pool"
    rows = _run(_DB.audit_logs.find({
        "tenant_id": TENANT_A,
        "event": "customer.service_category_changed",
        "customer_id": cid,
    }, {"_id": 0}).to_list(10))
    assert len(rows) == 1
    row = rows[0]
    assert row["from"] is None
    assert row["to"] == "pool"
    assert row["actor_user_id"] == ADMIN["id"]
    assert row["entity_kind"] == "customer"
    assert row["entity_id"] == cid


def test_idempotent_same_value_no_write_no_audit():
    cid = f"{PREFIX}-cust-idemp"
    _run(_seed(TENANT_A, cid, category="landscaping"))
    out = _run(_patch(cid, "landscaping"))
    assert out["service_category"] == "landscaping"
    count = _run(_DB.audit_logs.count_documents({
        "tenant_id": TENANT_A,
        "event": "customer.service_category_changed",
        "customer_id": cid,
    }))
    assert count == 0


def test_explicit_null_clears_and_audits():
    cid = f"{PREFIX}-cust-clear"
    _run(_seed(TENANT_A, cid, category="both"))
    out = _run(_patch(cid, None))
    assert out.get("service_category") is None
    row = _run(_DB.audit_logs.find_one({
        "tenant_id": TENANT_A,
        "event": "customer.service_category_changed",
        "customer_id": cid,
    }, {"_id": 0}))
    assert row is not None
    assert row["from"] == "both"
    assert row["to"] is None


def test_invalid_value_400():
    cid = f"{PREFIX}-cust-bad"
    _run(_seed(TENANT_A, cid))
    with pytest.raises(HTTPException) as exc:
        _run(_patch(cid, "swimming"))
    assert exc.value.status_code == 400


def test_404_on_unknown_and_cross_tenant():
    _run(_seed(TENANT_A, f"{PREFIX}-cust-ok"))
    _run(_seed(TENANT_B, f"{PREFIX}-cust-xten"))
    # unknown id
    with pytest.raises(HTTPException) as exc1:
        _run(_patch(f"{PREFIX}-cust-none", "pool"))
    assert exc1.value.status_code == 404
    # cross-tenant id
    with pytest.raises(HTTPException) as exc2:
        _run(_patch(f"{PREFIX}-cust-xten", "pool"))
    assert exc2.value.status_code == 404


def test_case_insensitive_normalization():
    cid = f"{PREFIX}-cust-case"
    _run(_seed(TENANT_A, cid))
    out = _run(_patch(cid, "  PoOl  "))
    assert out["service_category"] == "pool"
