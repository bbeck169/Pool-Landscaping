"""P2 #6 · Feb-2026 — Dashboard service-category breakdown pytest.

Locks four invariants on
``GET /api/dashboard/service-category-breakdown``:
  1. Customer counts per bucket match the ``service_category`` field
     on customers scoped to the tenant.  Unset bucket catches null +
     field-missing.
  2. Active-job counts aggregate only jobs with status ∈
     {scheduled, pending, in_progress, active} AND whose customer
     carries a valid category.  Jobs on unset-category customers do
     NOT inflate any enum bucket.
  3. MTD revenue aggregates only invoice-docs (``doc_type=="invoice"``)
     whose ``paid_at`` falls within the current calendar month,
     summing ``amount_paid`` into the owning customer's bucket.
  4. 403 for role=customer and role=technician.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
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
    for mod in ("routers.dashboard_service_category",):
        __import__(mod)
        import sys as _sys
        _sys.modules[mod].db = _DB


PREFIX = f"p26d-{uuid4().hex[:8]}"
TENANT_A = f"{PREFIX}-tenant-a"
ADMIN = {"id": f"{PREFIX}-u-admin", "role": "admin"}
MANAGER = {"id": f"{PREFIX}-u-manager", "role": "manager"}
TECH = {"id": f"{PREFIX}-u-tech", "role": "technician"}
CUSTOMER = {"id": f"{PREFIX}-u-cust", "role": "customer"}


async def _seed_tenant():
    await _DB.tenants.insert_one({"id": TENANT_A, "name": "T",
        "timezone": "America/Phoenix", "settings": {}})


async def _seed_cust(cid, category=None):
    doc = {"id": cid, "tenant_id": TENANT_A, "name": "C"}
    if category is not None:
        doc["service_category"] = category
    await _DB.customers.insert_one(doc)


async def _seed_job(jid, cid, status="scheduled"):
    await _DB.jobs.insert_one({
        "id": jid, "tenant_id": TENANT_A,
        "customer_id": cid, "status": status,
    })


async def _seed_invoice(iid, cid, amount, paid_at_iso):
    await _DB.quotes.insert_one({
        "id": iid, "tenant_id": TENANT_A, "doc_type": "invoice",
        "customer_id": cid, "amount_paid": amount,
        "paid_at": paid_at_iso,
    })


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in ("customers", "jobs", "quotes"):
        await _DB[coll].delete_many({"$or": [
            {"id": rx}, {"tenant_id": rx},
            {"customer_id": rx},
        ]})
    await _DB.tenants.delete_many({"id": rx})


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())
    yield
    _run(_cleanup())


def _month_start_iso():
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, 15, 12, 0, 0,
                      tzinfo=timezone.utc).isoformat()


def _last_month_iso():
    now = datetime.now(timezone.utc)
    # subtract one calendar month safely
    year = now.year
    month = now.month - 1
    if month < 1:
        month = 12
        year -= 1
    return datetime(year, month, 1, 12, 0, 0,
                      tzinfo=timezone.utc).isoformat()


async def _call(user):
    from routers.dashboard_service_category import service_category_breakdown
    return await service_category_breakdown(user=user,
                                                tenant={"id": TENANT_A})


def test_customer_counts_per_bucket():
    _run(_seed_tenant())
    # 2 pool, 1 landscaping, 1 both, 2 unset (one null, one field-missing)
    _run(_seed_cust(f"{PREFIX}-c-p1", "pool"))
    _run(_seed_cust(f"{PREFIX}-c-p2", "pool"))
    _run(_seed_cust(f"{PREFIX}-c-l1", "landscaping"))
    _run(_seed_cust(f"{PREFIX}-c-b1", "both"))
    _run(_seed_cust(f"{PREFIX}-c-u1", None))
    _run(_seed_cust(f"{PREFIX}-c-u2"))
    out = _run(_call(ADMIN))
    # Feb-2026 behavior correction: ``both``-customers union into
    # pool AND landscaping AND both. 2 pool + 1 both = 3 pool.
    # 1 landscaping + 1 both = 2 landscaping. 1 both. 2 unset.
    assert out["pool"]["customers"] == 3
    assert out["landscaping"]["customers"] == 2
    assert out["both"]["customers"] == 1
    assert out["unset"]["customers"] == 2


def test_both_customer_unions_into_pool_landscaping_and_both_tiles():
    """Behavior correction: a single ``both``-customer MUST be
    counted in all three enum tiles' ``customers`` field."""
    _run(_seed_tenant())
    _run(_seed_cust(f"{PREFIX}-c-only-both", "both"))
    out = _run(_call(ADMIN))
    assert out["pool"]["customers"] == 1
    assert out["landscaping"]["customers"] == 1
    assert out["both"]["customers"] == 1
    assert out["unset"]["customers"] == 0
    # Confirm the three enum tiles reference the SAME physical
    # customer (counts align — no accidental triple-insertion
    # of distinct rows).


def test_both_customer_active_jobs_and_mtd_revenue_union_into_pool_and_landscaping():
    """Behavior correction extends to active-jobs + MTD-revenue:
    a both-customer's single active job + single paid invoice
    MUST increment pool AND landscaping AND both tiles — same
    delta on each, no double-counting the increment."""
    _run(_seed_tenant())
    _run(_seed_cust(f"{PREFIX}-c-both-only", "both"))
    _run(_seed_job(f"{PREFIX}-j-sched",
                      f"{PREFIX}-c-both-only", status="scheduled"))
    _run(_seed_invoice(f"{PREFIX}-inv-both-mtd",
                           f"{PREFIX}-c-both-only",
                           75.25, _month_start_iso()))
    out = _run(_call(ADMIN))
    assert out["pool"]["active_jobs"] == 1
    assert out["landscaping"]["active_jobs"] == 1
    assert out["both"]["active_jobs"] == 1
    assert out["pool"]["mtd_revenue"] == 75.25
    assert out["landscaping"]["mtd_revenue"] == 75.25
    assert out["both"]["mtd_revenue"] == 75.25


def test_active_jobs_aggregate_only_valid_statuses_and_bucketed_customers():
    _run(_seed_tenant())
    _run(_seed_cust(f"{PREFIX}-cj-p1", "pool"))
    _run(_seed_cust(f"{PREFIX}-cj-u1", None))
    _run(_seed_job(f"{PREFIX}-j-sched", f"{PREFIX}-cj-p1", status="scheduled"))
    _run(_seed_job(f"{PREFIX}-j-prog", f"{PREFIX}-cj-p1", status="in_progress"))
    _run(_seed_job(f"{PREFIX}-j-done", f"{PREFIX}-cj-p1", status="completed"))  # NOT active
    _run(_seed_job(f"{PREFIX}-j-canc", f"{PREFIX}-cj-p1", status="canceled"))   # NOT active
    _run(_seed_job(f"{PREFIX}-j-unset", f"{PREFIX}-cj-u1", status="scheduled"))  # unset customer
    out = _run(_call(ADMIN))
    assert out["pool"]["active_jobs"] == 2
    assert out["landscaping"]["active_jobs"] == 0
    # unset bucket does NOT carry active_jobs — only `customers` key.
    assert "active_jobs" not in out["unset"]


def test_mtd_revenue_sums_only_this_month_paid_invoices_bucketed_by_category():
    _run(_seed_tenant())
    _run(_seed_cust(f"{PREFIX}-ci-p1", "pool"))
    _run(_seed_cust(f"{PREFIX}-ci-l1", "landscaping"))
    _run(_seed_cust(f"{PREFIX}-ci-u1", None))
    _run(_seed_invoice(f"{PREFIX}-inv-pool-mtd", f"{PREFIX}-ci-p1",
                           100.0, _month_start_iso()))
    _run(_seed_invoice(f"{PREFIX}-inv-pool-mtd-2", f"{PREFIX}-ci-p1",
                           50.5, _month_start_iso()))
    _run(_seed_invoice(f"{PREFIX}-inv-land-mtd", f"{PREFIX}-ci-l1",
                           200.0, _month_start_iso()))
    _run(_seed_invoice(f"{PREFIX}-inv-pool-OLD", f"{PREFIX}-ci-p1",
                           999.0, _last_month_iso()))
    _run(_seed_invoice(f"{PREFIX}-inv-unset-mtd", f"{PREFIX}-ci-u1",
                           400.0, _month_start_iso()))
    out = _run(_call(ADMIN))
    assert out["pool"]["mtd_revenue"] == 150.5
    assert out["landscaping"]["mtd_revenue"] == 200.0
    assert out["both"]["mtd_revenue"] == 0.0
    assert "mtd_revenue" not in out["unset"]


@pytest.mark.parametrize("bad_user", [TECH, CUSTOMER])
def test_403_for_non_admin_manager_roles(bad_user):
    from utils import require_admin_or_manager
    with pytest.raises(HTTPException) as exc:
        require_admin_or_manager(user=bad_user)
    assert exc.value.status_code == 403
