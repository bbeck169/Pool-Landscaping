"""Feb-2026 · P2 #6 property pivot — Commit 2 pytest suite.

Covers ``services.dashboard_property_category_counts.compute_property_counts``:

  * Active Accounts count = active + non-deleted properties whose
    parent customer is active + non-deleted.
  * Parent-customer inactive → disqualifies property.
  * Parent-customer soft-deleted → disqualifies property.
  * Parent-customer muted → does NOT disqualify property.
  * Property soft-deleted → excluded.
  * Property ``active == False`` → excluded.
  * Zero-property customer contributes 0 to Active Accounts.
  * Union semantics: ``both`` counts on BOTH Pool + Landscaping;
    exact-only on Both-services.
  * Case-insensitive match on legacy ``"Pool"`` / ``"POOL"``.
  * Tenant scoping: cross-tenant properties never leak.
  * Empty-tenant short-circuit returns zeros without crashing.
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ═════════════════════════════════════════════════════════════
# Mock DB (reuses the shape from Commit 1 tests).
# ═════════════════════════════════════════════════════════════

class _MockCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    async def to_list(self, length=None):
        return list(self._rows)

    def __aiter__(self):
        async def _gen():
            for r in self._rows:
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
# Tests
# ═════════════════════════════════════════════════════════════

async def test_counts_happy_path():
    from services.dashboard_property_category_counts import (
        compute_property_counts,
    )
    db = _MockDB(
        customers=[
            {"id": "c1", "tenant_id": "t1", "is_active": True},
            {"id": "c2", "tenant_id": "t1"},
        ],
        properties=[
            {"id": "p1", "tenant_id": "t1", "customer_id": "c1",
             "active": True, "service_category": "pool"},
            {"id": "p2", "tenant_id": "t1", "customer_id": "c1",
             "active": True, "service_category": "landscaping"},
            {"id": "p3", "tenant_id": "t1", "customer_id": "c2",
             "active": True, "service_category": "both"},
            {"id": "p4", "tenant_id": "t1", "customer_id": "c2",
             "active": True},  # no category → active account only
        ],
    )
    out = await compute_property_counts(db=db, tenant_id="t1")
    assert out["active_accounts_count"] == 4
    assert out["pool_properties_count"] == 2  # p1 + p3 (both)
    assert out["landscaping_properties_count"] == 2  # p2 + p3 (both)
    assert out["both_properties_count"] == 1  # p3 only


async def test_parent_customer_inactive_excludes_property():
    from services.dashboard_property_category_counts import (
        compute_property_counts,
    )
    db = _MockDB(
        customers=[
            {"id": "c1", "tenant_id": "t1", "is_active": False},
        ],
        properties=[
            {"id": "p1", "tenant_id": "t1", "customer_id": "c1",
             "active": True, "service_category": "pool"},
        ],
    )
    out = await compute_property_counts(db=db, tenant_id="t1")
    assert out["active_accounts_count"] == 0
    assert out["pool_properties_count"] == 0


async def test_parent_customer_soft_deleted_excludes_property():
    from services.dashboard_property_category_counts import (
        compute_property_counts,
    )
    db = _MockDB(
        customers=[
            {"id": "c1", "tenant_id": "t1",
             "deleted_at": "2026-01-01T00:00:00Z"},
        ],
        properties=[
            {"id": "p1", "tenant_id": "t1", "customer_id": "c1",
             "active": True, "service_category": "pool"},
        ],
    )
    out = await compute_property_counts(db=db, tenant_id="t1")
    assert out["active_accounts_count"] == 0


async def test_parent_customer_muted_does_not_exclude():
    """Muted = comms-suppressed, not deactivated. Properties count."""
    from services.dashboard_property_category_counts import (
        compute_property_counts,
    )
    db = _MockDB(
        customers=[
            {"id": "c1", "tenant_id": "t1", "is_active": True,
             "is_muted": True},
        ],
        properties=[
            {"id": "p1", "tenant_id": "t1", "customer_id": "c1",
             "active": True, "service_category": "pool"},
        ],
    )
    out = await compute_property_counts(db=db, tenant_id="t1")
    assert out["active_accounts_count"] == 1
    assert out["pool_properties_count"] == 1


async def test_property_soft_deleted_excluded():
    from services.dashboard_property_category_counts import (
        compute_property_counts,
    )
    db = _MockDB(
        customers=[{"id": "c1", "tenant_id": "t1", "is_active": True}],
        properties=[
            {"id": "p1", "tenant_id": "t1", "customer_id": "c1",
             "active": True, "service_category": "pool",
             "deleted_at": "2026-01-01T00:00:00Z"},
        ],
    )
    out = await compute_property_counts(db=db, tenant_id="t1")
    assert out["active_accounts_count"] == 0


async def test_property_active_false_excluded():
    from services.dashboard_property_category_counts import (
        compute_property_counts,
    )
    db = _MockDB(
        customers=[{"id": "c1", "tenant_id": "t1", "is_active": True}],
        properties=[
            {"id": "p1", "tenant_id": "t1", "customer_id": "c1",
             "active": False, "service_category": "pool"},
        ],
    )
    out = await compute_property_counts(db=db, tenant_id="t1")
    assert out["active_accounts_count"] == 0


async def test_zero_property_customer_contributes_zero():
    from services.dashboard_property_category_counts import (
        compute_property_counts,
    )
    db = _MockDB(
        customers=[{"id": "c1", "tenant_id": "t1", "is_active": True}],
        properties=[],
    )
    out = await compute_property_counts(db=db, tenant_id="t1")
    assert out["active_accounts_count"] == 0


async def test_case_insensitive_legacy_pool_label():
    from services.dashboard_property_category_counts import (
        compute_property_counts,
    )
    db = _MockDB(
        customers=[{"id": "c1", "tenant_id": "t1", "is_active": True}],
        properties=[
            {"id": "p1", "tenant_id": "t1", "customer_id": "c1",
             "active": True, "service_category": "Pool"},
            {"id": "p2", "tenant_id": "t1", "customer_id": "c1",
             "active": True, "service_category": "POOL"},
        ],
    )
    out = await compute_property_counts(db=db, tenant_id="t1")
    assert out["pool_properties_count"] == 2


async def test_tenant_scoping_cross_tenant_isolation():
    from services.dashboard_property_category_counts import (
        compute_property_counts,
    )
    db = _MockDB(
        customers=[
            {"id": "c1", "tenant_id": "t1", "is_active": True},
            {"id": "c2", "tenant_id": "t2", "is_active": True},
        ],
        properties=[
            {"id": "p1", "tenant_id": "t1", "customer_id": "c1",
             "active": True, "service_category": "pool"},
            {"id": "p2", "tenant_id": "t2", "customer_id": "c2",
             "active": True, "service_category": "pool"},
        ],
    )
    out = await compute_property_counts(db=db, tenant_id="t1")
    assert out["active_accounts_count"] == 1
    assert out["pool_properties_count"] == 1


async def test_empty_tenant_short_circuit_returns_zeros():
    from services.dashboard_property_category_counts import (
        compute_property_counts,
    )
    db = _MockDB(customers=[], properties=[])
    out = await compute_property_counts(db=db, tenant_id="t1")
    assert out == {
        "active_accounts_count": 0,
        "pool_properties_count": 0,
        "landscaping_properties_count": 0,
        "both_properties_count": 0,
    }


async def test_customer_with_3_properties_contributes_3_to_active_accounts():
    """Explicit spec sentence: customer with 3 active properties
    contributes 3 to the Active Accounts count."""
    from services.dashboard_property_category_counts import (
        compute_property_counts,
    )
    db = _MockDB(
        customers=[{"id": "c1", "tenant_id": "t1", "is_active": True}],
        properties=[
            {"id": "p1", "tenant_id": "t1", "customer_id": "c1",
             "active": True, "service_category": "pool"},
            {"id": "p2", "tenant_id": "t1", "customer_id": "c1",
             "active": True, "service_category": "pool"},
            {"id": "p3", "tenant_id": "t1", "customer_id": "c1",
             "active": True, "service_category": "landscaping"},
        ],
    )
    out = await compute_property_counts(db=db, tenant_id="t1")
    assert out["active_accounts_count"] == 3
    assert out["pool_properties_count"] == 2
    assert out["landscaping_properties_count"] == 1
