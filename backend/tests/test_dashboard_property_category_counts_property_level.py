"""Ticket V · Feb-2026 — Dashboard property-level tile counts.

Locks the behaviour of the three canonical ``*_properties_active_count``
fields published by ``GET /api/dashboard`` + the shared
``active_customer_ids_with_category`` membership helper that
underwrites both the aggregator and the new
``/api/customers?property_service_category=X&is_active=true``
list filter.

Rules (Option X, operator-confirmed):

  * Count at the PROPERTY level — one increment per matching
    property doc (NOT per owning customer).
  * Only count properties whose parent customer is active
    (``is_active != False`` + no soft-delete).  Only count
    properties that are themselves active (``active != False`` +
    no soft-delete).
  * Inclusive-rule categories:
      - Pool tile        → ``service_category in {pool, both}``
      - Landscaping tile → ``service_category in {landscaping, both}``
      - Both tile        → ``service_category == both`` (exact)
    Expect ``Pool >= Both`` and ``Landscaping >= Both``.
  * Properties belonging to an INACTIVE customer are excluded
    entirely (every tile).
  * A customer with ZERO properties contributes zero to every
    tile.
  * Tenant isolation — no bleed across ``tenant_id``.

Backed by ``services.dashboard_property_category_counts.
compute_property_counts`` for the counts + ``active_customer_ids_with_category``
for the shared membership helper. Zero live-Mongo dependency —
a tiny FakeDB honours the Mongo operator subset the two helpers
emit.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.dashboard_property_category_counts import (  # noqa: E402
    active_customer_ids_with_category,
    compute_property_counts,
)


# ═════════════════════════════════════════════════════════════
# FakeCollection — supports the Mongo operator subset both the
# aggregator and the membership helper emit: $and / $or /
# $regex / $exists / $in / $ne / scalar equality.
# ═════════════════════════════════════════════════════════════
_MISSING = object()


def _get(doc, key):
    return doc.get(key, _MISSING)


def _match_clause(doc, clause):
    for key, pred in clause.items():
        if key == "$and":
            if not all(_match_clause(doc, c) for c in pred):
                return False
            continue
        if key == "$or":
            if not any(_match_clause(doc, c) for c in pred):
                return False
            continue
        value = _get(doc, key)
        if isinstance(pred, dict):
            for op, arg in pred.items():
                if op == "$exists":
                    present = value is not _MISSING
                    if bool(arg) != present:
                        return False
                elif op == "$ne":
                    if value is _MISSING:
                        continue
                    if value == arg:
                        return False
                elif op == "$regex":
                    if value is _MISSING or value is None:
                        return False
                    opts = pred.get("$options", "")
                    flags = re.IGNORECASE if "i" in opts else 0
                    if re.search(arg, str(value), flags) is None:
                        return False
                elif op == "$options":
                    pass
                elif op == "$in":
                    if value is _MISSING or value not in arg:
                        return False
                else:
                    raise AssertionError(f"unhandled op {op!r}")
        else:
            if value is _MISSING:
                if pred is None:
                    continue
                return False
            if value != pred:
                return False
    return True


class _FakeCollection:
    def __init__(self, docs):
        self.docs = list(docs or [])

    async def count_documents(self, query):
        return sum(1 for d in self.docs if _match_clause(d, query))

    def find(self, query, projection=None):
        async def _agen():
            for d in self.docs:
                if _match_clause(d, query):
                    if projection:
                        yield {k: d.get(k)
                               for k in projection.keys()
                               if projection[k] == 1 and k in d}
                    else:
                        yield d
        return _agen()

    async def distinct(self, field, query):
        seen = []
        async for d in self.find(query):
            v = d.get(field)
            if v not in seen:
                seen.append(v)
        return seen


class _FakeDB:
    def __init__(self, customers, properties):
        self.customers = _FakeCollection(customers)
        self.properties = _FakeCollection(properties)


# ═════════════════════════════════════════════════════════════
# Fixture helpers
# ═════════════════════════════════════════════════════════════
def _cust(**kw):
    base = {
        "id": kw.pop("id"),
        "tenant_id": kw.pop("tenant_id", "t-a"),
        "is_active": kw.pop("is_active", True),
    }
    base.update(kw)
    return base


def _prop(**kw):
    base = {
        "id": kw.pop("id"),
        "tenant_id": kw.pop("tenant_id", "t-a"),
        "customer_id": kw.pop("customer_id"),
        "service_category": kw.pop("service_category"),
        "active": kw.pop("active", True),
    }
    base.update(kw)
    return base


# ═════════════════════════════════════════════════════════════
# Test 1 — Operator-spec fixture
#
# Active customer A: 2 Pool props + 1 Both prop
# Active customer B: 1 Landscaping + 1 Both prop
# Inactive customer C: 3 Both props (must be excluded)
# Active customer D: zero properties (must be excluded)
#
# Expected tile counts (property-level, inclusive):
#   Pool tile        = (A's 2 pool) + (A's 1 both) + (B's 1 both) = 4
#   Landscaping tile = (B's 1 landscaping) + (A's 1 both) + (B's 1 both) = 3
#   Both tile        = (A's 1 both) + (B's 1 both) = 2
# ═════════════════════════════════════════════════════════════
def test_dashboard_property_counts_operator_fixture():
    customers = [
        _cust(id="A", is_active=True),
        _cust(id="B", is_active=True),
        _cust(id="C", is_active=False),
        _cust(id="D", is_active=True),
    ]
    properties = [
        _prop(id="A-p1", customer_id="A", service_category="pool"),
        _prop(id="A-p2", customer_id="A", service_category="pool"),
        _prop(id="A-p3", customer_id="A", service_category="both"),
        _prop(id="B-p1", customer_id="B",
                service_category="landscaping"),
        _prop(id="B-p2", customer_id="B", service_category="both"),
        _prop(id="C-p1", customer_id="C", service_category="both"),
        _prop(id="C-p2", customer_id="C", service_category="both"),
        _prop(id="C-p3", customer_id="C", service_category="both"),
    ]
    db = _FakeDB(customers, properties)
    res = asyncio.run(compute_property_counts(db=db, tenant_id="t-a"))
    assert res["pool_properties_count"] == 4, (
        f"Pool: expected 4 (A×2 pool + A×1 both + B×1 both), got "
        f"{res['pool_properties_count']}"
    )
    assert res["landscaping_properties_count"] == 3, (
        f"Landscaping: expected 3 (B×1 landscaping + A×1 both + "
        f"B×1 both), got {res['landscaping_properties_count']}"
    )
    assert res["both_properties_count"] == 2
    # Active-accounts count — total active props for active custs
    # (A has 3, B has 2, C excluded, D has 0) = 5.
    assert res["active_accounts_count"] == 5
    # Expect Pool >= Both and Landscaping >= Both (operator rule).
    assert res["pool_properties_count"] >= res["both_properties_count"]
    assert res["landscaping_properties_count"] >= res["both_properties_count"]


# ═════════════════════════════════════════════════════════════
# Test 2 — Inactive parent-customer exclusion
# ═════════════════════════════════════════════════════════════
def test_inactive_customer_properties_excluded_from_every_tile():
    customers = [
        _cust(id="X", is_active=False),
    ]
    properties = [
        _prop(id="X-p1", customer_id="X", service_category="pool"),
        _prop(id="X-p2", customer_id="X", service_category="both"),
        _prop(id="X-p3", customer_id="X",
                service_category="landscaping"),
    ]
    db = _FakeDB(customers, properties)
    res = asyncio.run(compute_property_counts(db=db, tenant_id="t-a"))
    assert res == {
        "active_accounts_count": 0,
        "pool_properties_count": 0,
        "landscaping_properties_count": 0,
        "both_properties_count": 0,
    }


# ═════════════════════════════════════════════════════════════
# Test 3 — Customer with no properties contributes nothing
# ═════════════════════════════════════════════════════════════
def test_no_property_customer_contributes_zero():
    customers = [
        _cust(id="A", is_active=True),
        _cust(id="B", is_active=True),  # no properties
    ]
    properties = [
        _prop(id="A-p1", customer_id="A", service_category="pool"),
    ]
    db = _FakeDB(customers, properties)
    res = asyncio.run(compute_property_counts(db=db, tenant_id="t-a"))
    assert res["pool_properties_count"] == 1
    assert res["active_accounts_count"] == 1


# ═════════════════════════════════════════════════════════════
# Test 4 — Tenant isolation
# ═════════════════════════════════════════════════════════════
def test_cross_tenant_isolation():
    customers = [
        _cust(id="A", tenant_id="t-a", is_active=True),
        _cust(id="B", tenant_id="t-b", is_active=True),
    ]
    properties = [
        _prop(id="A-p1", tenant_id="t-a", customer_id="A",
                service_category="pool"),
        _prop(id="B-p1", tenant_id="t-b", customer_id="B",
                service_category="pool"),
        _prop(id="B-p2", tenant_id="t-b", customer_id="B",
                service_category="both"),
    ]
    db = _FakeDB(customers, properties)
    res_a = asyncio.run(compute_property_counts(db=db, tenant_id="t-a"))
    res_b = asyncio.run(compute_property_counts(db=db, tenant_id="t-b"))
    assert res_a["pool_properties_count"] == 1
    assert res_b["pool_properties_count"] == 2  # pool + both
    assert res_b["both_properties_count"] == 1


# ═════════════════════════════════════════════════════════════
# Test 5 — Inactive property (property.active == False) excluded
# ═════════════════════════════════════════════════════════════
def test_inactive_property_excluded():
    customers = [_cust(id="A", is_active=True)]
    properties = [
        _prop(id="A-p1", customer_id="A", service_category="pool"),
        _prop(id="A-p2", customer_id="A", service_category="pool",
                active=False),
    ]
    db = _FakeDB(customers, properties)
    res = asyncio.run(compute_property_counts(db=db, tenant_id="t-a"))
    assert res["pool_properties_count"] == 1
    assert res["active_accounts_count"] == 1


# ═════════════════════════════════════════════════════════════
# Test 6 — Case-insensitive service_category matching
# ═════════════════════════════════════════════════════════════
def test_case_insensitive_property_category_match():
    customers = [_cust(id="A", is_active=True)]
    properties = [
        _prop(id="p1", customer_id="A", service_category="Pool"),
        _prop(id="p2", customer_id="A", service_category="POOL"),
        _prop(id="p3", customer_id="A", service_category="Both"),
    ]
    db = _FakeDB(customers, properties)
    res = asyncio.run(compute_property_counts(db=db, tenant_id="t-a"))
    assert res["pool_properties_count"] == 3  # 2 pool variants + 1 both
    assert res["both_properties_count"] == 1
    assert res["landscaping_properties_count"] == 1  # the Both prop


# ═════════════════════════════════════════════════════════════
# Test 7 — Shared helper ``active_customer_ids_with_category``
#
# Returns the DISTINCT customer_ids who own ≥1 matching property.
# Deliberately deduplicates on customer_id (that's the "list
# filter" row-shape), while the aggregator counts raw properties.
# This is the X-divergence operator ACKed — tests lock the
# divergence shape so later refactors don't silently flip it.
# ═════════════════════════════════════════════════════════════
def test_shared_helper_returns_distinct_customer_ids():
    customers = [
        _cust(id="A", is_active=True),
        _cust(id="B", is_active=True),
        _cust(id="C", is_active=False),
    ]
    properties = [
        _prop(id="A-p1", customer_id="A", service_category="pool"),
        _prop(id="A-p2", customer_id="A", service_category="pool"),
        _prop(id="A-p3", customer_id="A", service_category="both"),
        _prop(id="B-p1", customer_id="B", service_category="both"),
        _prop(id="C-p1", customer_id="C", service_category="pool"),
    ]
    db = _FakeDB(customers, properties)
    pool = asyncio.run(active_customer_ids_with_category(
        db=db, tenant_id="t-a", category="pool",
    ))
    land = asyncio.run(active_customer_ids_with_category(
        db=db, tenant_id="t-a", category="landscaping",
    ))
    both = asyncio.run(active_customer_ids_with_category(
        db=db, tenant_id="t-a", category="both",
    ))
    # A has pool+both props, B has only both — both in Pool
    # inclusive {pool, both}. C excluded (inactive).
    assert sorted(pool) == ["A", "B"]
    # Landscaping inclusive = {landscaping, both} → only B qualifies.
    assert sorted(land) == ["A", "B"]
    # Both exact → A + B both own a 'both' prop; neither duplicated.
    assert sorted(both) == ["A", "B"]


def test_shared_helper_unknown_category_returns_empty():
    customers = [_cust(id="A", is_active=True)]
    properties = [
        _prop(id="A-p1", customer_id="A", service_category="pool"),
    ]
    db = _FakeDB(customers, properties)
    assert asyncio.run(active_customer_ids_with_category(
        db=db, tenant_id="t-a", category="sauna",
    )) == []
    assert asyncio.run(active_customer_ids_with_category(
        db=db, tenant_id="t-a", category="",
    )) == []


def test_shared_helper_no_active_customers_short_circuits():
    customers = [_cust(id="X", is_active=False)]
    properties = [
        _prop(id="X-p1", customer_id="X", service_category="pool"),
    ]
    db = _FakeDB(customers, properties)
    assert asyncio.run(active_customer_ids_with_category(
        db=db, tenant_id="t-a", category="pool",
    )) == []


# ═════════════════════════════════════════════════════════════
# Test 8 — Aggregator ↔ shared-helper membership consistency
#
# For a given tenant/fixture, the DISTINCT customer_ids whose
# properties contribute to ``pool_properties_count`` MUST equal
# the set returned by ``active_customer_ids_with_category``
# (category="pool"). This is the operator's "share one helper"
# requirement — both call-sites consume the same gate.
# ═════════════════════════════════════════════════════════════
def test_aggregator_contributing_set_equals_shared_helper():
    customers = [
        _cust(id="A", is_active=True),
        _cust(id="B", is_active=True),
        _cust(id="C", is_active=True),
        _cust(id="D", is_active=False),
    ]
    properties = [
        _prop(id="A-p1", customer_id="A", service_category="pool"),
        _prop(id="A-p2", customer_id="A", service_category="pool"),
        _prop(id="B-p1", customer_id="B", service_category="both"),
        _prop(id="C-p1", customer_id="C",
                service_category="landscaping"),
        _prop(id="D-p1", customer_id="D", service_category="pool"),
    ]
    db = _FakeDB(customers, properties)
    # Aggregator contributing-customer set for Pool: emulate by
    # querying the same inclusive rule the aggregator emits.
    helper_pool = set(asyncio.run(active_customer_ids_with_category(
        db=db, tenant_id="t-a", category="pool",
    )))
    # Expected contributing set: A (2 pool props) + B (1 both prop).
    # C excluded (landscaping only). D excluded (inactive).
    assert helper_pool == {"A", "B"}
    # And the aggregator's count on the same fixtures = 3
    # (A×2 + B×1).
    res = asyncio.run(compute_property_counts(db=db, tenant_id="t-a"))
    assert res["pool_properties_count"] == 3
    # The X-divergence is explicit: tile=3, len(helper_set)=2.
    assert res["pool_properties_count"] > len(helper_pool)
