"""TD-80 · Feb-2026 — shared predicate helper unit tests.

Covers ``services/properties_active_predicate.py``, the single
source of truth for "active customer" + "active property" gates
consumed by both ``compute_property_counts`` (aggregator) and
``routers/properties.list_properties`` (list endpoint).

Three predicate shapes are locked here:

  * :func:`active_customer_filter` — exact dict shape (tenant +
    is_active permissive + no soft-delete).
  * :func:`active_property_match_base` — exact dict shape (tenant
    + active permissive + no soft-delete).
  * :func:`active_customer_ids` — async helper, correctly
    short-circuits + preserves the "active by default" semantics
    (missing/null fields pass the gate).
"""
from __future__ import annotations

import pytest

from services.properties_active_predicate import (
    active_customer_filter,
    active_customer_ids,
    active_property_match_base,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ═════════════════════════════════════════════════════════════
# Mock DB (same shape as the aggregator suite — kept local so this
# test file doesn't take a cross-module import on test fixtures).
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
            if "$exists" in val:
                exists = key in row
                if exists != val["$exists"]:
                    return False
                continue
        else:
            if row.get(key) != val:
                return False
    return True


class _MockDB:
    def __init__(self, customers=None):
        self.customers = _MockCollection(customers)


# ═════════════════════════════════════════════════════════════
# Filter-shape tests — these lock the exact Mongo filter the
# aggregator + list endpoint rely on. Any future refactor must
# preserve this shape bit-exact.
# ═════════════════════════════════════════════════════════════

def test_active_customer_filter_shape():
    """Locks the exact filter shape so a drift breaks the test
    before it reaches prod. Any change to the predicate semantics
    requires updating this test deliberately."""
    f = active_customer_filter("t1")
    assert f == {
        "tenant_id": "t1",
        "$and": [
            {"$or": [{"is_active": True},
                      {"is_active": None},
                      {"is_active": {"$exists": False}}]},
            {"$or": [{"deleted_at": {"$exists": False}},
                      {"deleted_at": None}]},
        ],
    }


def test_active_property_match_base_shape():
    """Locks the property-level predicate shape (parent-customer
    gate is applied by callers via ``customer_id: {"$in": ...}``,
    NOT inside this base)."""
    f = active_property_match_base("t1")
    assert f == {
        "tenant_id": "t1",
        "$and": [
            {"$or": [
                {"active": True},
                {"active": None},
                {"active": {"$exists": False}},
            ]},
            {"$or": [
                {"deleted_at": {"$exists": False}},
                {"deleted_at": None},
            ]},
        ],
    }


def test_filters_are_tenant_scoped():
    """Smoke test — the tenant id supplied flows into both filters
    exactly once."""
    a = active_customer_filter("tenant-xyz")
    b = active_property_match_base("tenant-xyz")
    assert a["tenant_id"] == "tenant-xyz"
    assert b["tenant_id"] == "tenant-xyz"
    # No stray tenant_id leaking into the AND clauses.
    for sub in a["$and"]:
        assert "tenant_id" not in sub
    for sub in b["$and"]:
        assert "tenant_id" not in sub


# ═════════════════════════════════════════════════════════════
# active_customer_ids — the async resolver.
# ═════════════════════════════════════════════════════════════

async def test_active_customer_ids_returns_only_active_rows():
    db = _MockDB(customers=[
        {"id": "c1", "tenant_id": "t1", "is_active": True},
        {"id": "c2", "tenant_id": "t1", "is_active": False},  # inactive
        {"id": "c3", "tenant_id": "t1"},  # missing → active-by-default
        {"id": "c4", "tenant_id": "t1", "is_active": None},  # null → active-by-default
        {"id": "c5", "tenant_id": "t1", "is_active": True,
         "deleted_at": "2026-02-01T00:00:00Z"},  # soft-deleted
        {"id": "c6", "tenant_id": "t2", "is_active": True},  # wrong tenant
    ])
    ids = await active_customer_ids(db=db, tenant_id="t1")
    assert set(ids) == {"c1", "c3", "c4"}
    assert "c2" not in ids  # explicit inactive
    assert "c5" not in ids  # soft-deleted
    assert "c6" not in ids  # cross-tenant


async def test_active_customer_ids_handles_null_deleted_at():
    """``deleted_at: None`` must count as "not soft-deleted"."""
    db = _MockDB(customers=[
        {"id": "c1", "tenant_id": "t1", "is_active": True,
         "deleted_at": None},
    ])
    ids = await active_customer_ids(db=db, tenant_id="t1")
    assert ids == ["c1"]


async def test_active_customer_ids_empty_tenant_returns_empty_list():
    db = _MockDB(customers=[])
    ids = await active_customer_ids(db=db, tenant_id="empty-tenant")
    assert ids == []


async def test_active_customer_ids_skips_rows_without_id():
    """Defensive — rows with missing ``id`` key are silently
    dropped so the ``$in`` filter never includes None."""
    db = _MockDB(customers=[
        {"id": "c1", "tenant_id": "t1", "is_active": True},
        {"tenant_id": "t1", "is_active": True},  # no id
        {"id": None, "tenant_id": "t1", "is_active": True},  # null id
    ])
    ids = await active_customer_ids(db=db, tenant_id="t1")
    assert ids == ["c1"]
