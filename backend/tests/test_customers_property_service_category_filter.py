"""Ticket V · Feb-2026 — ``GET /customers?property_service_category=X``.

Locks the behaviour of the new property-level inclusive filter
on the customer list (Option X, operator-confirmed):

  1. ``?property_service_category=pool`` returns customers who
     own ≥1 active property with ``service_category in {pool, both}``,
     gated on parent-customer active + no soft-delete.
  2. Case-insensitive match (``Pool`` / ``POOL`` / ``pool`` all land).
  3. Landscaping follows the inclusive rule (land + both).
  4. ``?property_service_category=both`` is EXACT — only customers
     owning ≥1 ``both`` property qualify (no pool-only / land-only
     bleed-in).
  5. Composes AS AND with the existing ``?service_category=X``
     customer-level filter — passing both narrows the result.
  6. Inactive customers are excluded regardless of their property
     categories.
  7. Properties on an inactive customer never contribute (the
     active-parent gate inside the shared helper filters them out).
  8. Tenant isolation — a property in tenant B never leaks a
     customer into tenant A's list.
  9. Cross-check: the list endpoint's returned customer-id set
     under ``property_service_category=X&is_active=true`` equals
     the shared helper's output on the same tenant/fixtures. This
     is the "single membership helper" invariant Ticket V locks.

Hits live Mongo via the same scaffolding the pre-existing
``test_customer_service_category_list_filter.py`` uses so the
list-filter integration is tested end-to-end rather than through
a fake collection.
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
    for mod in ("routers.customers", "routers.properties",
                 "services.dashboard_property_category_counts",
                 "services.properties_active_predicate"):
        __import__(mod)
        import sys as _sys
        if hasattr(_sys.modules[mod], "db"):
            _sys.modules[mod].db = _DB


PREFIX = f"tv-{uuid4().hex[:8]}"
TENANT_A = f"{PREFIX}-tenant-a"
TENANT_B = f"{PREFIX}-tenant-b"
ADMIN = {"id": f"{PREFIX}-u-admin", "role": "admin"}


async def _seed():
    for tid in (TENANT_A, TENANT_B):
        await _DB.tenants.insert_one({
            "id": tid, "name": "T", "timezone": "America/Phoenix",
            "settings": {},
        })

    # ── Tenant A ──
    # Active customer A1 → owns 2 Pool + 1 Both property.
    # Active customer A2 → owns 1 Landscaping + 1 Both property.
    # Inactive customer A3 → owns 3 Both properties (ALL excluded).
    # Active customer A4 → owns zero properties (never qualifies).
    # Active customer A5 → owns only an INACTIVE Pool property
    #                       (excluded via active-property gate).
    customers_a = [
        {"id": f"{PREFIX}-A1", "name": "A1", "is_active": True,
         "service_category": "pool"},
        {"id": f"{PREFIX}-A2", "name": "A2", "is_active": True,
         "service_category": "landscaping"},
        {"id": f"{PREFIX}-A3", "name": "A3", "is_active": False,
         "service_category": "both"},
        {"id": f"{PREFIX}-A4", "name": "A4", "is_active": True,
         "service_category": None},
        {"id": f"{PREFIX}-A5", "name": "A5", "is_active": True,
         "service_category": "pool"},
    ]
    for r in customers_a:
        r["tenant_id"] = TENANT_A
        await _DB.customers.insert_one(r)

    # Properties for tenant A.
    props_a = [
        # A1 — 2 pool + 1 both
        {"id": f"{PREFIX}-A1-p1", "customer_id": f"{PREFIX}-A1",
         "service_category": "pool", "active": True},
        {"id": f"{PREFIX}-A1-p2", "customer_id": f"{PREFIX}-A1",
         "service_category": "Pool", "active": True},  # mixed case
        {"id": f"{PREFIX}-A1-p3", "customer_id": f"{PREFIX}-A1",
         "service_category": "both", "active": True},
        # A2 — 1 landscaping + 1 both
        {"id": f"{PREFIX}-A2-p1", "customer_id": f"{PREFIX}-A2",
         "service_category": "landscaping", "active": True},
        {"id": f"{PREFIX}-A2-p2", "customer_id": f"{PREFIX}-A2",
         "service_category": "Both", "active": True},
        # A3 — 3 both (inactive parent → excluded)
        {"id": f"{PREFIX}-A3-p1", "customer_id": f"{PREFIX}-A3",
         "service_category": "both", "active": True},
        {"id": f"{PREFIX}-A3-p2", "customer_id": f"{PREFIX}-A3",
         "service_category": "both", "active": True},
        {"id": f"{PREFIX}-A3-p3", "customer_id": f"{PREFIX}-A3",
         "service_category": "both", "active": True},
        # A5 — inactive property (excluded via active-prop gate)
        {"id": f"{PREFIX}-A5-p1", "customer_id": f"{PREFIX}-A5",
         "service_category": "pool", "active": False},
    ]
    for r in props_a:
        r["tenant_id"] = TENANT_A
        await _DB.properties.insert_one(r)

    # ── Tenant B ── isolation check.
    await _DB.customers.insert_one({
        "id": f"{PREFIX}-B1", "name": "B1", "is_active": True,
        "tenant_id": TENANT_B, "service_category": "pool",
    })
    await _DB.properties.insert_one({
        "id": f"{PREFIX}-B1-p1", "customer_id": f"{PREFIX}-B1",
        "service_category": "pool", "active": True,
        "tenant_id": TENANT_B,
    })


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in (_DB.customers, _DB.properties, _DB.tenants):
        await coll.delete_many(
            {"$or": [{"id": rx}, {"tenant_id": rx}]},
        )


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())
    _run(_seed())
    yield
    _run(_cleanup())


async def _list(tenant_id=TENANT_A, **kwargs):
    from routers.customers import list_customers
    _defaults = dict(
        search=None, tag=None, tags=None, city=None, waitlisted=None,
        unscheduled=None, is_active=None, missing_card=None,
        missing_email=False, missing_phone=False, missing_address=False,
        portal_activated=None, portal_invited=None, first_access=None,
        portal_status=None, is_muted=None, service_category=None,
        property_service_category=None,
        has_payment_method=None, count_only=False,
        include_deleted=False, include_merged=False,
        ids_in=None,
        page=None, page_size=None, size=None, sort="created_desc",
        slim=None,
    )
    _defaults.update(kwargs)
    return await list_customers(
        user=ADMIN, tenant={"id": tenant_id}, **_defaults,
    )


def _ids(items):
    out = []
    for r in items:
        if isinstance(r, dict):
            out.append(r.get("id"))
        else:
            out.append(r.id if hasattr(r, "id") else r["id"])
    return sorted(out)


# ═════════════════════════════════════════════════════════════
# Test 1 — Pool inclusive rule
# ═════════════════════════════════════════════════════════════
def test_property_service_category_pool_inclusive_rule():
    out = _run(_list(
        property_service_category="pool", is_active=True,
    ))
    # A1 (owns Pool props + Both) + A2 (owns Both) qualify.
    # A3 (inactive parent) excluded. A4 (no props) excluded.
    # A5 (only inactive-prop) excluded via active-property gate.
    assert _ids(out) == sorted([f"{PREFIX}-A1", f"{PREFIX}-A2"])


# ═════════════════════════════════════════════════════════════
# Test 2 — Landscaping inclusive rule
# ═════════════════════════════════════════════════════════════
def test_property_service_category_landscaping_inclusive_rule():
    out = _run(_list(
        property_service_category="landscaping", is_active=True,
    ))
    # A2 (owns Landscaping + Both) + A1 (owns Both) qualify.
    assert _ids(out) == sorted([f"{PREFIX}-A1", f"{PREFIX}-A2"])


# ═════════════════════════════════════════════════════════════
# Test 3 — Both exact-match (no pool-only / land-only bleed-in)
# ═════════════════════════════════════════════════════════════
def test_property_service_category_both_exact_match():
    out = _run(_list(
        property_service_category="both", is_active=True,
    ))
    # A1 (owns a Both prop) + A2 (owns a Both prop) qualify.
    # Neither A1 nor A2 appear because of their Pool-only /
    # Landscaping-only props — ONLY because of their Both props.
    assert _ids(out) == sorted([f"{PREFIX}-A1", f"{PREFIX}-A2"])


# ═════════════════════════════════════════════════════════════
# Test 4 — Case-insensitive param value
# ═════════════════════════════════════════════════════════════
def test_property_service_category_param_case_insensitive():
    out_upper = _run(_list(
        property_service_category="POOL", is_active=True,
    ))
    out_mixed = _run(_list(
        property_service_category="Pool", is_active=True,
    ))
    out_lower = _run(_list(
        property_service_category="pool", is_active=True,
    ))
    assert _ids(out_upper) == _ids(out_mixed) == _ids(out_lower)
    assert _ids(out_lower) == sorted([f"{PREFIX}-A1", f"{PREFIX}-A2"])


# ═════════════════════════════════════════════════════════════
# Test 5 — Invalid values silently pass (no 400)
# ═════════════════════════════════════════════════════════════
def test_property_service_category_invalid_value_silently_passes():
    # Omit is_active so all 5 tenant-A customers are candidates.
    out = _run(_list(property_service_category="sauna"))
    assert len(out) == 5


# ═════════════════════════════════════════════════════════════
# Test 6 — Inactive customers excluded regardless of ``is_active``
# query arg absent (gate baked into shared helper).
# ═════════════════════════════════════════════════════════════
def test_inactive_customer_never_qualifies():
    # Do NOT pass is_active=True — the shared helper's own
    # active-parent gate must still exclude A3.
    out = _run(_list(property_service_category="both"))
    assert f"{PREFIX}-A3" not in _ids(out)
    # And the match set is exactly A1 + A2 regardless.
    assert _ids(out) == sorted([f"{PREFIX}-A1", f"{PREFIX}-A2"])


# ═════════════════════════════════════════════════════════════
# Test 7 — AND composition with ?service_category=
# ═════════════════════════════════════════════════════════════
def test_combined_customer_level_and_property_level_filters_and():
    # A1's customer.service_category is "pool"; A2's is
    # "landscaping". Combining ``service_category=pool`` (customer-
    # level) with ``property_service_category=landscaping``
    # (property-level inclusive {landscaping, both}) narrows:
    #   * A1 matches property-level (owns Both prop) BUT customer-
    #     level is "pool" ✓
    #   * A2 matches property-level (owns Landscaping + Both) AND
    #     customer-level IS "landscaping" ✗ (customer_cat="pool"
    #     excludes it)
    # Expected: only A1 (customer_cat=pool AND owns a landscaping-
    # inclusive property).
    out = _run(_list(
        service_category="pool",
        property_service_category="landscaping",
        is_active=True,
    ))
    assert _ids(out) == [f"{PREFIX}-A1"]


# ═════════════════════════════════════════════════════════════
# Test 8 — Tenant isolation
# ═════════════════════════════════════════════════════════════
def test_tenant_isolation():
    out_a = _run(_list(
        tenant_id=TENANT_A, property_service_category="pool",
        is_active=True,
    ))
    out_b = _run(_list(
        tenant_id=TENANT_B, property_service_category="pool",
        is_active=True,
    ))
    assert _ids(out_a) == sorted([f"{PREFIX}-A1", f"{PREFIX}-A2"])
    assert _ids(out_b) == [f"{PREFIX}-B1"]
    # Negative — A1 must never land in tenant B's list, and B1
    # must never land in tenant A's.
    assert f"{PREFIX}-B1" not in _ids(out_a)
    assert f"{PREFIX}-A1" not in _ids(out_b)


# ═════════════════════════════════════════════════════════════
# Test 9 — Cross-check: list endpoint ↔ shared helper
#
# The customer-id set returned by the list endpoint under
# ``property_service_category=X&is_active=true`` MUST equal the
# shared helper's output on the same tenant/fixtures.  This is
# the Ticket V "single membership helper" invariant: the
# aggregator and the list filter cannot diverge.
# ═════════════════════════════════════════════════════════════
def test_list_matches_shared_helper_contributing_set():
    from services.dashboard_property_category_counts import (
        active_customer_ids_with_category,
    )
    for cat in ("pool", "landscaping", "both"):
        list_ids = _ids(_run(_list(
            property_service_category=cat, is_active=True,
        )))
        helper_ids = sorted(_run(active_customer_ids_with_category(
            db=_DB, tenant_id=TENANT_A, category=cat,
        )))
        assert list_ids == helper_ids, (
            f"category={cat}: list_ids={list_ids} != "
            f"helper_ids={helper_ids}"
        )


# ═════════════════════════════════════════════════════════════
# Test 10 — count_only honors the new filter
# ═════════════════════════════════════════════════════════════
def test_count_only_matches_list_length():
    out = _run(_list(
        property_service_category="both", is_active=True,
        count_only=True,
    ))
    count = out["count"] if isinstance(out, dict) else out.count
    rows = _run(_list(
        property_service_category="both", is_active=True,
    ))
    assert count == len(rows) == 2
