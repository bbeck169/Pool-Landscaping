"""Ticket Y · Feb-2026 — ``GET /jobs?service_category=<bucket>``.

Locks the behaviour of the new Service Category filter on the
Schedule page's /jobs fetch:

  * ``pool`` / ``landscaping`` / ``both`` are the only accepted
    values (lowercase enum match ``customers.service_category``).
  * Case-insensitive input (``Pool`` / ``POOL`` / ``pool`` all
    land on the same bucket).
  * Invalid values silent-pass as no-filter (treated as "All").
  * Tenant isolation — never leak jobs across tenants.
  * AND composition with other filters (status, technician_id,
    customer_id has special precedence — see test 7).
  * Empty-match short-circuit — no customers in the bucket
    returns [] without running the full jobs query.

Hits live Mongo via the same scaffolding every other router
integration test in this suite uses.
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
    for mod in ("routers.jobs",):
        __import__(mod)
        import sys as _sys
        if hasattr(_sys.modules[mod], "db"):
            _sys.modules[mod].db = _DB


PREFIX = f"ty-{uuid4().hex[:8]}"
TENANT_A = f"{PREFIX}-tenant-a"
TENANT_B = f"{PREFIX}-tenant-b"
ADMIN = {"id": f"{PREFIX}-u-admin", "role": "admin"}


async def _seed():
    for tid in (TENANT_A, TENANT_B):
        await _DB.tenants.insert_one({
            "id": tid, "name": "T", "timezone": "America/Phoenix",
            "settings": {},
        })

    # Tenant A — 3 customers (pool / landscaping / both), each
    # with 2 jobs on the schedule window.
    customers = [
        {"id": f"{PREFIX}-A-cp", "name": "Pool-Cust",
         "service_category": "pool"},
        {"id": f"{PREFIX}-A-cl", "name": "Land-Cust",
         "service_category": "landscaping"},
        {"id": f"{PREFIX}-A-cb", "name": "Both-Cust",
         "service_category": "both"},
        {"id": f"{PREFIX}-A-cn", "name": "Unset-Cust"},  # no cat
    ]
    for c in customers:
        c["tenant_id"] = TENANT_A
        c["is_active"] = True
        await _DB.customers.insert_one(c)

    for i, c in enumerate(customers):
        for n in range(2):
            await _DB.jobs.insert_one({
                "id": f"{PREFIX}-A-j-{i}-{n}",
                "tenant_id": TENANT_A,
                "customer_id": c["id"],
                "customer_name": c["name"],
                "status": "scheduled" if n == 0 else "missed",
                "scheduled_date": "2026-02-10",
                "service_type": "Pool" if i == 0 else "Mow",
            })

    # Tenant B — 1 pool customer with 1 pool job (tenant-isolation
    # anchor).
    await _DB.customers.insert_one({
        "id": f"{PREFIX}-B-cp", "name": "B-Pool",
        "service_category": "pool",
        "tenant_id": TENANT_B, "is_active": True,
    })
    await _DB.jobs.insert_one({
        "id": f"{PREFIX}-B-j-0", "tenant_id": TENANT_B,
        "customer_id": f"{PREFIX}-B-cp",
        "customer_name": "B-Pool", "status": "scheduled",
        "scheduled_date": "2026-02-10", "service_type": "Pool",
    })


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in (_DB.jobs, _DB.customers, _DB.tenants):
        try:
            await coll.delete_many(
                {"$or": [{"id": rx}, {"tenant_id": rx}]},
            )
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())
    _run(_seed())
    yield
    _run(_cleanup())


async def _call(**overrides):
    from routers.jobs import list_jobs
    kw = dict(
        user=overrides.pop("user", ADMIN),
        tenant={"id": overrides.pop("tenant_id", TENANT_A)},
        status=None, technician_id=None, customer_id=None,
        crew_id=None, service_category=None,
        start=None, end=None, scheduled_date=None,
        recurring_template_id=None,
        limit=1000, offset=0, sort=None,
        include_deleted=False, include_photos=False,
        response=None,
    )
    kw.update(overrides)
    return await list_jobs(**kw)


def _ids(rows):
    out = []
    for r in rows:
        if isinstance(r, dict):
            out.append(r.get("id"))
        else:
            out.append(getattr(r, "id", None))
    return sorted([i for i in out if i])


# ═════════════════════════════════════════════════════════════
# Test 1 — Pool bucket exact match
# ═════════════════════════════════════════════════════════════
def test_pool_bucket_matches_exact_pool_customers():
    out = _run(_call(service_category="pool"))
    # Only Pool-cust's 2 jobs qualify.
    assert _ids(out) == sorted([
        f"{PREFIX}-A-j-0-0", f"{PREFIX}-A-j-0-1",
    ])


# ═════════════════════════════════════════════════════════════
# Test 2 — Landscaping bucket exact match
# ═════════════════════════════════════════════════════════════
def test_landscaping_bucket_matches_exact_landscaping_customers():
    out = _run(_call(service_category="landscaping"))
    assert _ids(out) == sorted([
        f"{PREFIX}-A-j-1-0", f"{PREFIX}-A-j-1-1",
    ])


# ═════════════════════════════════════════════════════════════
# Test 3 — Both bucket exact match (NO union with pool/landscaping)
# ═════════════════════════════════════════════════════════════
def test_both_bucket_exact_match_no_union():
    out = _run(_call(service_category="both"))
    # Only Both-cust's 2 jobs — Pool-cust + Land-cust do NOT
    # bleed in. This is the whole point of the Ticket Y
    # "strict customer-tag match" directive (operator waived
    # inclusive semantics here, mirroring the untouched
    # /customers?service_category= filter).
    assert _ids(out) == sorted([
        f"{PREFIX}-A-j-2-0", f"{PREFIX}-A-j-2-1",
    ])


# ═════════════════════════════════════════════════════════════
# Test 4 — Case-insensitive input
# ═════════════════════════════════════════════════════════════
@pytest.mark.parametrize("value", ["Pool", "POOL", "pool", " pool "])
def test_case_insensitive_input(value):
    out = _run(_call(service_category=value))
    assert len(out) == 2
    for row in out:
        assert row["customer_id"] == f"{PREFIX}-A-cp"


# ═════════════════════════════════════════════════════════════
# Test 5 — Invalid value silent-pass (no filter applied)
# ═════════════════════════════════════════════════════════════
@pytest.mark.parametrize("value", [
    "sauna", "spa", "all", "All", "", "  ",
])
def test_invalid_value_silent_passes_as_no_filter(value):
    out = _run(_call(service_category=value))
    # Full tenant-A jobs set = 4 customers × 2 jobs = 8 (every
    # customer has jobs, including the untagged Unset-Cust).
    assert len(out) == 8


# ═════════════════════════════════════════════════════════════
# Test 6 — Tenant isolation
# ═════════════════════════════════════════════════════════════
def test_tenant_isolation():
    out_a = _run(_call(service_category="pool", tenant_id=TENANT_A))
    out_b = _run(_call(service_category="pool", tenant_id=TENANT_B))
    assert all("A-" in r["id"] for r in out_a)
    assert all("B-" in r["id"] for r in out_b)
    assert len(out_b) == 1
    assert _ids(out_a) == sorted([
        f"{PREFIX}-A-j-0-0", f"{PREFIX}-A-j-0-1",
    ])


# ═════════════════════════════════════════════════════════════
# Test 7 — AND composition with existing filters
# ═════════════════════════════════════════════════════════════
def test_composes_with_status_filter():
    out = _run(_call(service_category="pool", status="scheduled"))
    assert _ids(out) == [f"{PREFIX}-A-j-0-0"]


def test_composes_with_status_missed():
    out = _run(_call(service_category="landscaping", status="missed"))
    assert _ids(out) == [f"{PREFIX}-A-j-1-1"]


def test_customer_id_filter_wins_over_service_category():
    """When ``customer_id`` is explicitly passed, the
    ``service_category`` filter is a no-op on top (the user has
    asked for one specific customer's jobs, not further-narrowed
    by category). Locked by the pre-explicit-customer_id branch
    in the handler."""
    out = _run(_call(
        customer_id=f"{PREFIX}-A-cp",
        service_category="landscaping",  # would exclude everyone
    ))
    # customer_id branch wins — returns the pool customer's jobs.
    assert len(out) == 2
    for row in out:
        assert row["customer_id"] == f"{PREFIX}-A-cp"


# ═════════════════════════════════════════════════════════════
# Test 8 — Short-circuit: no matching customers → []
# ═════════════════════════════════════════════════════════════
def test_empty_match_short_circuit_returns_empty_list():
    # Delete every customer in tenant A so no customer_ids
    # match the pool bucket.
    async def _wipe():
        await _DB.customers.delete_many({"tenant_id": TENANT_A})
    _run(_wipe())
    out = _run(_call(service_category="pool"))
    assert out == []
