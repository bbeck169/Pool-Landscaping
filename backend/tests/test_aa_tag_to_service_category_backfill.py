"""Ticket AA · Feb-2026 — Tag → customers.service_category backfill pytest.

Locks the following invariants on
``services.migrations.aa_tag_to_service_category_backfill``:

  1. Permissive canonical mapping — Pool / Pool Client / pool →
     "pool"; Landscaping → "landscaping"; Pool & Landscaping → "both".
  2. "Two singles = both" promotion when a customer has BOTH a
     Pool-mapped tag AND a Landscaping-mapped tag as separate tags.
  3. Only touches customers whose ``service_category`` is currently
     null / missing / empty — preserves manually PATCH'd rows.
  4. Idempotent — second run returns ``already_ran=True`` + no
     additional writes.
  5. ``force=True`` bypasses the sentinel for admin re-run.
  6. ``dry_run=True`` returns the summary without any writes.
  7. Unmapped tags surface in ``unmapped_tag_counts`` for operator
     review (not written to DB).
  8. Cross-tenant isolation preserved — writes only touch the
     authoring tenant.
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
    for mod in ("services.migrations.aa_tag_to_service_category_backfill",):
        __import__(mod)
        import sys as _sys
        _sys.modules[mod].db = _DB


PREFIX = f"aatags-{uuid4().hex[:8]}"
TENANT_A = f"{PREFIX}-tenant-a"
TENANT_B = f"{PREFIX}-tenant-b"
SENTINEL = "aa_tag_to_service_category_backfill_v1"


async def _seed(tid, cid, *, tags=None, service_category=None):
    doc = {"id": cid, "tenant_id": tid, "name": f"cust-{cid}"}
    if tags is not None:
        doc["tags"] = tags
    if service_category is not None:
        doc["service_category"] = service_category
    await _DB.customers.insert_one(doc)


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    await _DB.customers.delete_many(
        {"$or": [{"id": rx}, {"tenant_id": rx}]},
    )
    await _DB.migrations.delete_one({"id": SENTINEL})


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())
    yield
    _run(_cleanup())


# ═══════════════════════════════════════════════════════════════════
# 1. Permissive canonical mapping.
# ═══════════════════════════════════════════════════════════════════
def test_canonical_mapping_pool_landscaping_both():
    from services.migrations.aa_tag_to_service_category_backfill import (
        run_tag_to_service_category_backfill,
    )
    _run(_seed(TENANT_A, f"{PREFIX}-c-pool", tags=["Pool"]))
    _run(_seed(TENANT_A, f"{PREFIX}-c-pool-client", tags=["Pool Client"]))
    _run(_seed(TENANT_A, f"{PREFIX}-c-pool-lower", tags=["pool"]))
    _run(_seed(TENANT_A, f"{PREFIX}-c-land", tags=["Landscaping"]))
    _run(_seed(TENANT_A, f"{PREFIX}-c-both", tags=["Pool & Landscaping"]))
    _run(_seed(TENANT_A, f"{PREFIX}-c-both-alt", tags=["Pool and Landscaping"]))

    res = _run(run_tag_to_service_category_backfill())
    s = res["summary"]
    # Tenant-scoped assertions — the migration runs globally across
    # all tenants so overall totals include background rows; use
    # per_tenant counters for the seeded fixtures.
    tbucket = s["per_tenant"].get(TENANT_A, {})
    assert tbucket.get("pool") == 3
    assert tbucket.get("landscaping") == 1
    assert tbucket.get("both") == 2

    pool = _run(_DB.customers.find_one({"id": f"{PREFIX}-c-pool"},
                                        {"_id": 0}))
    assert pool["service_category"] == "pool"
    assert pool["service_category_source"] == "aa_tag_backfill"
    assert pool.get("service_category_set_at")

    both = _run(_DB.customers.find_one({"id": f"{PREFIX}-c-both"},
                                        {"_id": 0}))
    assert both["service_category"] == "both"


# ═══════════════════════════════════════════════════════════════════
# 2. Two singles → both promotion.
# ═══════════════════════════════════════════════════════════════════
def test_two_singles_promote_to_both():
    from services.migrations.aa_tag_to_service_category_backfill import (
        run_tag_to_service_category_backfill,
    )
    _run(_seed(TENANT_A, f"{PREFIX}-c-split",
                 tags=["Pool", "Landscaping"]))

    _run(run_tag_to_service_category_backfill())
    doc = _run(_DB.customers.find_one({"id": f"{PREFIX}-c-split"},
                                        {"_id": 0}))
    assert doc["service_category"] == "both"


# ═══════════════════════════════════════════════════════════════════
# 3. Pre-set customers are preserved.
# ═══════════════════════════════════════════════════════════════════
def test_preexisting_service_category_is_preserved():
    from services.migrations.aa_tag_to_service_category_backfill import (
        run_tag_to_service_category_backfill,
    )
    # This customer already has an admin-set category + tags that would
    # otherwise map to "both". Backfill must leave it alone.
    _run(_seed(TENANT_A, f"{PREFIX}-c-manual",
                 tags=["Pool & Landscaping"],
                 service_category="landscaping"))
    _run(run_tag_to_service_category_backfill())
    doc = _run(_DB.customers.find_one({"id": f"{PREFIX}-c-manual"},
                                        {"_id": 0}))
    assert doc["service_category"] == "landscaping"
    assert doc.get("service_category_source") is None


# ═══════════════════════════════════════════════════════════════════
# 4. Idempotency — second run short-circuits.
# ═══════════════════════════════════════════════════════════════════
def test_idempotent_second_run_short_circuits():
    from services.migrations.aa_tag_to_service_category_backfill import (
        run_tag_to_service_category_backfill,
    )
    _run(_seed(TENANT_A, f"{PREFIX}-c-pool", tags=["Pool"]))
    first = _run(run_tag_to_service_category_backfill())
    assert first["already_ran"] is False
    assert first["summary"]["per_tenant"].get(TENANT_A, {}).get("pool") == 1

    second = _run(run_tag_to_service_category_backfill())
    assert second["already_ran"] is True


# ═══════════════════════════════════════════════════════════════════
# 5. force=True bypasses the sentinel.
# ═══════════════════════════════════════════════════════════════════
def test_force_rerun_bypasses_sentinel():
    from services.migrations.aa_tag_to_service_category_backfill import (
        run_tag_to_service_category_backfill,
    )
    _run(_seed(TENANT_A, f"{PREFIX}-c-pool", tags=["Pool"]))
    _run(run_tag_to_service_category_backfill())
    # Add a new customer AFTER the first run.
    _run(_seed(TENANT_A, f"{PREFIX}-c-land", tags=["Landscaping"]))
    forced = _run(run_tag_to_service_category_backfill(force=True))
    assert forced["already_ran"] is False
    # Only the NEW null customer is picked up for TENANT_A on force;
    # the previously-filled one is skipped by the null-guard query.
    tbucket = forced["summary"]["per_tenant"].get(TENANT_A, {})
    assert tbucket.get("pool", 0) == 0
    assert tbucket.get("landscaping") == 1


# ═══════════════════════════════════════════════════════════════════
# 6. dry_run writes nothing but reports counts.
# ═══════════════════════════════════════════════════════════════════
def test_dry_run_no_writes():
    from services.migrations.aa_tag_to_service_category_backfill import (
        run_tag_to_service_category_backfill,
    )
    _run(_seed(TENANT_A, f"{PREFIX}-c-pool", tags=["Pool"]))
    res = _run(run_tag_to_service_category_backfill(dry_run=True))
    tbucket = res["summary"]["per_tenant"].get(TENANT_A, {})
    assert tbucket.get("pool") == 1
    assert res["summary"]["dry_run"] is True

    doc = _run(_DB.customers.find_one({"id": f"{PREFIX}-c-pool"},
                                        {"_id": 0}))
    assert doc.get("service_category") in (None, "")
    assert _run(_DB.migrations.find_one({"id": SENTINEL})) is None


# ═══════════════════════════════════════════════════════════════════
# 7. Unmapped tags surface in unmapped_tag_counts.
# ═══════════════════════════════════════════════════════════════════
def test_unmapped_tags_surfaced():
    from services.migrations.aa_tag_to_service_category_backfill import (
        run_tag_to_service_category_backfill,
    )
    _run(_seed(TENANT_A, f"{PREFIX}-c-vip",
                 tags=["VIP", "Filter Clean"]))
    _run(_seed(TENANT_A, f"{PREFIX}-c-vip-2", tags=["VIP"]))
    res = _run(run_tag_to_service_category_backfill())
    unmapped = res["summary"]["unmapped_tag_counts"]
    # These tags are AA-specific (DB may contain other VIP rows but
    # Filter Clean is unique to this fixture).  Prefix-scope by
    # asserting '>=' instead of '=='.
    assert unmapped.get("VIP", 0) >= 2
    assert unmapped.get("Filter Clean", 0) >= 1
    doc = _run(_DB.customers.find_one({"id": f"{PREFIX}-c-vip"},
                                        {"_id": 0}))
    assert doc.get("service_category") in (None, "")


# ═══════════════════════════════════════════════════════════════════
# 8. Cross-tenant isolation.
# ═══════════════════════════════════════════════════════════════════
def test_cross_tenant_isolation_per_tenant_counts():
    from services.migrations.aa_tag_to_service_category_backfill import (
        run_tag_to_service_category_backfill,
    )
    _run(_seed(TENANT_A, f"{PREFIX}-ca-1", tags=["Pool"]))
    _run(_seed(TENANT_A, f"{PREFIX}-ca-2", tags=["Pool"]))
    _run(_seed(TENANT_B, f"{PREFIX}-cb-1", tags=["Landscaping"]))
    res = _run(run_tag_to_service_category_backfill())
    per_tenant = res["summary"]["per_tenant"]
    assert per_tenant[TENANT_A]["pool"] == 2
    assert per_tenant[TENANT_B]["landscaping"] == 1
    # No cross-tenant leaks on the write path.
    assert _run(_DB.customers.count_documents(
        {"tenant_id": TENANT_A, "service_category": "landscaping"})) == 0
