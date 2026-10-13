"""P2 #6 · Feb-2026 — backfill_customer_service_category_from_jobs pytest.

Locks four invariants on the one-shot migration:
  1. pool-only job history → bucket "pool"; land-only → "landscaping";
     mixed → "both"; no match → unchanged null.
  2. Existing non-null service_category is NEVER overwritten
     (first-write-wins); the plan skips those rows entirely.
  3. Dry-run leaves customer rows UNCHANGED but still writes exactly
     one batch audit row with dry_run=True.
  4. Commit mode writes the field + writes exactly one batch audit
     row with dry_run=False + accurate per-bucket counts.
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


PREFIX = f"p26e-{uuid4().hex[:8]}"
TENANT = f"{PREFIX}-tenant"


async def _seed_tenant():
    await _DB.tenants.insert_one({"id": TENANT, "name": "T",
        "timezone": "America/Phoenix", "settings": {}})


async def _seed_customer(cid, *, category=None):
    doc = {"id": cid, "tenant_id": TENANT, "name": "C"}
    if category is not None:
        doc["service_category"] = category
    await _DB.customers.insert_one(doc)


async def _seed_job(cid, service_type):
    await _DB.jobs.insert_one({
        "id": f"{PREFIX}-j-{uuid4().hex[:6]}", "tenant_id": TENANT,
        "customer_id": cid, "service_type": service_type,
        "status": "scheduled",
    })


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in ("customers", "jobs", "audit_logs"):
        await _DB[coll].delete_many({"$or": [
            {"id": rx}, {"tenant_id": rx}, {"customer_id": rx},
            {"tenant_scope": rx},
        ]})
    await _DB.tenants.delete_many({"id": rx})


@pytest.fixture(autouse=True)
def _clean():
    _run(_cleanup())
    yield
    _run(_cleanup())


def _import_runner():
    import sys
    sys.path.insert(0,
        str(Path(__file__).resolve().parents[1] / "scripts"))
    from backfill_customer_service_category_from_jobs import run as _r
    return _r


def test_dry_run_bucket_assignment_does_not_write_customers():
    _run(_seed_tenant())
    _run(_seed_customer(f"{PREFIX}-c-pool-only"))
    _run(_seed_job(f"{PREFIX}-c-pool-only", "Weekly Pool Service"))
    _run(_seed_customer(f"{PREFIX}-c-land-only"))
    _run(_seed_job(f"{PREFIX}-c-land-only", "Landscaping Maintenance"))
    _run(_seed_customer(f"{PREFIX}-c-both"))
    _run(_seed_job(f"{PREFIX}-c-both", "Pool Cleaning"))
    _run(_seed_job(f"{PREFIX}-c-both", "Lawn / Land upkeep"))
    _run(_seed_customer(f"{PREFIX}-c-nojobs"))
    _run(_seed_customer(f"{PREFIX}-c-nomatch"))
    _run(_seed_job(f"{PREFIX}-c-nomatch", "Hot tub"))
    r = _import_runner()
    out = _run(r(dry_run=True, tenant_scope=TENANT, _db_override=_DB))
    assert out["dry_run"] is True
    assert out["total_updated"] == 0
    assert out["counts"]["pool"] == 1
    assert out["counts"]["landscaping"] == 1
    assert out["counts"]["both"] == 1
    # DB rows unchanged.
    for cid in [f"{PREFIX}-c-pool-only", f"{PREFIX}-c-land-only",
                 f"{PREFIX}-c-both", f"{PREFIX}-c-nojobs",
                 f"{PREFIX}-c-nomatch"]:
        doc = _run(_DB.customers.find_one({"id": cid}, {"_id": 0}))
        assert doc.get("service_category") is None, (
            f"{cid} should remain unset in dry-run (got "
            f"{doc.get('service_category')!r})"
        )
    # Exactly one batch audit row.
    rows = _run(_DB.audit_logs.find({
        "event": "customer.service_category_backfill_run",
        "tenant_scope": TENANT,
    }, {"_id": 0}).to_list(10))
    assert len(rows) == 1
    row = rows[0]
    assert row["dry_run"] is True
    assert row["total_scanned"] == 5
    assert row["pool_count"] == 1
    assert row["landscaping_count"] == 1
    assert row["both_count"] == 1
    assert row["total_updated"] == 0


def test_commit_mode_writes_and_batch_audits():
    _run(_seed_tenant())
    _run(_seed_customer(f"{PREFIX}-c-pool"))
    _run(_seed_job(f"{PREFIX}-c-pool", "Pool Cleaning"))
    _run(_seed_customer(f"{PREFIX}-c-land"))
    _run(_seed_job(f"{PREFIX}-c-land", "Landscape pruning"))
    r = _import_runner()
    out = _run(r(dry_run=False, tenant_scope=TENANT, _db_override=_DB))
    assert out["dry_run"] is False
    assert out["total_updated"] == 2
    pool_doc = _run(_DB.customers.find_one({"id": f"{PREFIX}-c-pool"},
                                                {"_id": 0}))
    assert pool_doc["service_category"] == "pool"
    land_doc = _run(_DB.customers.find_one({"id": f"{PREFIX}-c-land"},
                                                {"_id": 0}))
    assert land_doc["service_category"] == "landscaping"
    row = _run(_DB.audit_logs.find_one({
        "event": "customer.service_category_backfill_run",
        "tenant_scope": TENANT,
    }, {"_id": 0}))
    assert row is not None
    assert row["dry_run"] is False
    assert row["total_updated"] == 2
    assert row["pool_count"] == 1
    assert row["landscaping_count"] == 1


def test_first_write_wins_does_not_overwrite_existing_category():
    _run(_seed_tenant())
    _run(_seed_customer(f"{PREFIX}-c-preset", category="landscaping"))
    # Pool-signal job on an already-landscaping-tagged customer.
    _run(_seed_job(f"{PREFIX}-c-preset", "Pool Service"))
    r = _import_runner()
    out = _run(r(dry_run=False, tenant_scope=TENANT, _db_override=_DB))
    # Preset row was NOT in the scan (service_category already set).
    assert out["total_scanned"] == 0
    assert out["total_updated"] == 0
    doc = _run(_DB.customers.find_one({"id": f"{PREFIX}-c-preset"},
                                            {"_id": 0}))
    # Original value is untouched.
    assert doc["service_category"] == "landscaping"


def test_idempotent_on_repeat_runs():
    _run(_seed_tenant())
    _run(_seed_customer(f"{PREFIX}-c-x"))
    _run(_seed_job(f"{PREFIX}-c-x", "Pool"))
    r = _import_runner()
    out1 = _run(r(dry_run=False, tenant_scope=TENANT, _db_override=_DB))
    assert out1["total_updated"] == 1
    # Second run finds nothing to do.
    out2 = _run(r(dry_run=False, tenant_scope=TENANT, _db_override=_DB))
    assert out2["total_scanned"] == 0
    assert out2["total_updated"] == 0
    # Two distinct batch audit rows (one per invocation).
    cnt = _run(_DB.audit_logs.count_documents({
        "event": "customer.service_category_backfill_run",
        "tenant_scope": TENANT,
    }))
    assert cnt == 2
