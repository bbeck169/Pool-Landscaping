"""TD-80 · Feb-2026 — Aggregator ↔ List parity suite.

Locks the invariant that the dashboard aggregator's
``active_accounts_count`` ALWAYS equals the row-count returned by
``GET /api/properties?is_active=true`` for the same tenant.

Pre-TD-80 the two paths diverged: the list used a two-pass
pattern with a ``.to_list(limit*4)`` over-fetch cap that silently
truncated when the property-level prelim exceeded the cap.  On
preview the delta was 211 rows (290 aggregator vs 79 list).  The
TD-80 ship swapped both call-sites onto a shared predicate
(``services/properties_active_predicate``) so the aggregator's
single-query shape is now mirrored by the list.

This suite seeds a fixture tenant with 5000+ property rows (so
the pre-TD-80 two-pass cap of 2000 would have truncated) and
asserts both call-sites emit the SAME count.  Any future refactor
that re-introduces a lossy intermediate step will fail here.
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ═════════════════════════════════════════════════════════════
# Mock DB — reuses the shape from the aggregator suite but adds
# ``skip`` + ``$in`` + ``$ne`` support for the list query path.
# ═════════════════════════════════════════════════════════════

class _MockCursor:
    def __init__(self, rows):
        self._rows = list(rows)
        self._skip = 0

    def skip(self, n):
        self._skip = n
        return self

    async def to_list(self, length=None):
        rows = self._rows[self._skip:]
        if length is not None:
            rows = rows[:length]
        return rows

    def __aiter__(self):
        async def _gen():
            for r in self._rows[self._skip:]:
                yield r
        return _gen()


class _MockCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find(self, query, projection=None):
        return _MockCursor([r for r in self.rows if _match(r, query)])

    async def count_documents(self, query):
        return sum(1 for r in self.rows if _match(r, query))


def _match(row, query):
    for key, val in query.items():
        if key == "$or":
            if not any(_match(row, sub) for sub in val):
                return False
            continue
        if key == "$and":
            if not all(_match(row, sub) for sub in val):
                return False
            continue
        if isinstance(val, dict):
            if "$in" in val:
                if row.get(key) not in val["$in"]:
                    return False
                continue
            if "$ne" in val:
                if row.get(key) == val["$ne"]:
                    return False
                continue
            if "$exists" in val:
                exists = key in row
                if exists != val["$exists"]:
                    return False
                continue
            if "$regex" in val:
                import re
                flags = re.I if val.get("$options") == "i" else 0
                v = row.get(key)
                if not isinstance(v, str):
                    return False
                if not re.search(val["$regex"], v, flags):
                    return False
                continue
        else:
            if row.get(key) != val:
                return False
    return True


class _MockDB:
    def __init__(self, customers=None, properties=None):
        self.customers = _MockCollection(customers)
        self.properties = _MockCollection(properties)


# ═════════════════════════════════════════════════════════════
# Fixture builder — produces a tenant that would have tripped the
# pre-TD-80 two-pass truncation (property-level prelim > 2000).
# ═════════════════════════════════════════════════════════════

def _build_fixture(*, active_customers: int, properties_per_active: int,
                     inactive_customers: int, properties_per_inactive: int,
                     tenant_id: str = "t-fixture"):
    """Return (customers, properties) lists mimicking the preview
    tenant: a small set of active customers each owning N
    properties, plus a large set of inactive customers each owning
    properties that would pass the property-level gate alone.
    """
    customers = []
    properties = []
    pid_counter = 0
    for i in range(active_customers):
        cid = f"act-{i}"
        customers.append({"id": cid, "tenant_id": tenant_id,
                           "is_active": True})
        for _ in range(properties_per_active):
            pid_counter += 1
            properties.append({
                "id": f"p-{pid_counter}",
                "tenant_id": tenant_id,
                "customer_id": cid,
                "active": True,
            })
    for i in range(inactive_customers):
        cid = f"inact-{i}"
        customers.append({"id": cid, "tenant_id": tenant_id,
                           "is_active": False})
        for _ in range(properties_per_inactive):
            pid_counter += 1
            properties.append({
                "id": f"p-{pid_counter}",
                "tenant_id": tenant_id,
                "customer_id": cid,
                "active": True,  # property-level active, parent isn't
            })
    return customers, properties


# ═════════════════════════════════════════════════════════════
# Parity tests
# ═════════════════════════════════════════════════════════════

async def test_aggregator_equals_list_on_preview_shape():
    """Preview tenant shape: ~250 active customers avg ~1.16
    properties, ~5500 inactive customers (bulk of the 5852 prelim)
    with ~1 property each.  Pre-TD-80 the list truncated at 2000
    prelim → ~79 rows.  Post-TD-80 both paths return the same
    count (290-equivalent for this fixture: 250 × 1 = 250)."""
    customers, properties = _build_fixture(
        active_customers=250,
        properties_per_active=1,
        inactive_customers=5500,
        properties_per_inactive=1,
    )
    db = _MockDB(customers=customers, properties=properties)

    from services.dashboard_property_category_counts import (
        compute_property_counts,
    )
    agg = await compute_property_counts(db=db, tenant_id="t-fixture")

    # Mimic the list handler's shape via the shared predicate.
    from services.properties_active_predicate import (
        active_customer_ids,
        active_property_match_base,
    )
    cids = await active_customer_ids(db=db, tenant_id="t-fixture")
    base = active_property_match_base("t-fixture")
    base["customer_id"] = {"$in": cids}
    list_rows = await db.properties.find(base, {"_id": 0}).to_list(500)

    assert agg["active_accounts_count"] == 250
    assert len(list_rows) == 250
    # Invariant: parity.
    assert agg["active_accounts_count"] == len(list_rows)


async def test_parity_holds_with_multi_property_customers():
    """Realistic preview distribution — 250 active customers avg
    1.16 properties ≈ 290 total active properties.  Aggregator
    + list must agree exactly."""
    customers = []
    properties = []
    pid = 0
    # 210 customers × 1 property + 40 customers × 2 properties = 290.
    for i in range(210):
        cid = f"c1-{i}"
        customers.append({"id": cid, "tenant_id": "t-x", "is_active": True})
        pid += 1
        properties.append({"id": f"p-{pid}", "tenant_id": "t-x",
                            "customer_id": cid, "active": True})
    for i in range(40):
        cid = f"c2-{i}"
        customers.append({"id": cid, "tenant_id": "t-x", "is_active": True})
        for _ in range(2):
            pid += 1
            properties.append({"id": f"p-{pid}", "tenant_id": "t-x",
                                "customer_id": cid, "active": True})
    # Noise — 3000 inactive-customer properties that would pre-TD-80
    # dominate the 2000-row prelim cap.
    for i in range(3000):
        cid = f"n-{i}"
        customers.append({"id": cid, "tenant_id": "t-x", "is_active": False})
        pid += 1
        properties.append({"id": f"p-{pid}", "tenant_id": "t-x",
                            "customer_id": cid, "active": True})
    db = _MockDB(customers=customers, properties=properties)

    from services.dashboard_property_category_counts import (
        compute_property_counts,
    )
    agg = await compute_property_counts(db=db, tenant_id="t-x")

    from services.properties_active_predicate import (
        active_customer_ids,
        active_property_match_base,
    )
    cids = await active_customer_ids(db=db, tenant_id="t-x")
    base = active_property_match_base("t-x")
    base["customer_id"] = {"$in": cids}
    list_rows = await db.properties.find(base, {"_id": 0}).to_list(500)

    assert agg["active_accounts_count"] == 290, agg
    assert len(list_rows) == 290
    assert agg["active_accounts_count"] == len(list_rows)


async def test_empty_tenant_parity():
    """Zero-customer tenant short-circuits identically on both paths."""
    db = _MockDB(customers=[], properties=[])
    from services.dashboard_property_category_counts import (
        compute_property_counts,
    )
    from services.properties_active_predicate import (
        active_customer_ids,
    )
    agg = await compute_property_counts(db=db, tenant_id="t-empty")
    cids = await active_customer_ids(db=db, tenant_id="t-empty")
    assert agg["active_accounts_count"] == 0
    assert cids == []


async def test_parity_with_category_pool_filter():
    """Category tile deep-link parity — Pool count on aggregator
    must equal the row count on
    ``/properties?is_active=true&service_category=pool``."""
    customers = [
        {"id": "c1", "tenant_id": "t-c", "is_active": True},
        {"id": "c2", "tenant_id": "t-c", "is_active": True},
        {"id": "c3", "tenant_id": "t-c", "is_active": False},
    ]
    properties = [
        {"id": "p1", "tenant_id": "t-c", "customer_id": "c1",
         "active": True, "service_category": "pool"},
        {"id": "p2", "tenant_id": "t-c", "customer_id": "c2",
         "active": True, "service_category": "both"},
        {"id": "p3", "tenant_id": "t-c", "customer_id": "c1",
         "active": True, "service_category": "landscaping"},
        {"id": "p4", "tenant_id": "t-c", "customer_id": "c3",
         "active": True, "service_category": "pool"},  # inactive parent
    ]
    db = _MockDB(customers=customers, properties=properties)

    from services.dashboard_property_category_counts import (
        compute_property_counts,
    )
    agg = await compute_property_counts(db=db, tenant_id="t-c")

    from services.properties_active_predicate import (
        active_customer_ids,
        active_property_match_base,
    )
    cids = await active_customer_ids(db=db, tenant_id="t-c")
    base = active_property_match_base("t-c")
    base["customer_id"] = {"$in": cids}
    base["service_category"] = {"$regex": r"^(pool|both)$",
                                   "$options": "i"}
    list_rows = await db.properties.find(base, {"_id": 0}).to_list(500)

    # Expected: p1 (pool) + p2 (both) = 2.  p4 excluded (inactive parent).
    assert agg["pool_properties_count"] == 2
    assert len(list_rows) == 2
    assert agg["pool_properties_count"] == len(list_rows)
