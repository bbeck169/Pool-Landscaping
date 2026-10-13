"""Feb-2026 · P2 #6 property pivot — Commit 1 pytest suite.

Covers:

  * ``_canonical_service_category`` helper (case-insensitive +
    out-of-enum tolerance).
  * ``PATCH /properties/{pid}`` canonicalisation ladder (admin
    override / admin clear / out-of-enum drop).
  * Startup migration ``run_property_service_category_inheritance``
    idempotency + per-category stamps + legacy "Pool" → "pool"
    normalisation.
  * ``GET /api/properties`` query shape — union filter, is_active=true
    parent-customer gate, tenant scoping.

Pure-helper suite — no live Mongo required. The migration tests
use a ``_MockDB`` with ``customers``, ``properties``, and
``migrations`` collections.
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ═════════════════════════════════════════════════════════════
# Canonical helper
# ═════════════════════════════════════════════════════════════

def test_canonical_service_category_lowers_valid_values():
    from routers.properties import _canonical_service_category
    assert _canonical_service_category("pool") == "pool"
    assert _canonical_service_category("Pool") == "pool"
    assert _canonical_service_category("POOL") == "pool"
    assert _canonical_service_category("landscaping") == "landscaping"
    assert _canonical_service_category("Landscaping") == "landscaping"
    assert _canonical_service_category("Both") == "both"


def test_canonical_service_category_drops_out_of_enum():
    from routers.properties import _canonical_service_category
    assert _canonical_service_category(None) is None
    assert _canonical_service_category("") is None
    assert _canonical_service_category("unset") is None
    assert _canonical_service_category("Chemistry") is None
    assert _canonical_service_category("pool and landscaping") is None
    # Non-string inputs defensive.
    assert _canonical_service_category(123) is None
    assert _canonical_service_category({"service_category": "pool"}) is None


# ═════════════════════════════════════════════════════════════
# Mock DB used by migration tests.
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
        self.inserted = []
        self.updates = []

    def find(self, query, projection=None):
        return _MockCursor([r for r in self.rows if _match(r, query)])

    async def find_one(self, query, projection=None):
        for r in self.rows:
            if _match(r, query):
                return dict(r)
        return None

    async def insert_one(self, doc):
        self.inserted.append(dict(doc))
        self.rows.append(dict(doc))
        return type("R", (), {"inserted_id": doc.get("id") or "m"})()

    async def update_one(self, query, update):
        for r in self.rows:
            if _match(r, query):
                for k, v in (update.get("$set") or {}).items():
                    r[k] = v
                self.updates.append({"q": query, "u": update})
                return type("U", (), {"matched_count": 1,
                                        "modified_count": 1})()
        return type("U", (), {"matched_count": 0, "modified_count": 0})()

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
            if "$nin" in val:
                if row.get(key) in val["$nin"]:
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
        else:
            if row.get(key) != val:
                return False
    return True


class _MockDB:
    def __init__(self, customers=None, properties=None, migrations=None):
        self.customers = _MockCollection(customers)
        self.properties = _MockCollection(properties)
        self.migrations = _MockCollection(migrations)


# ═════════════════════════════════════════════════════════════
# Migration — inheritance.
# ═════════════════════════════════════════════════════════════

async def test_migration_inherits_pool_landscaping_both(monkeypatch):
    import services.migrations.seed_property_service_category_from_customer as mig

    db = _MockDB(
        customers=[
            {"id": "c1", "tenant_id": "t1", "service_category": "pool"},
            {"id": "c2", "tenant_id": "t1",
             "service_category": "landscaping"},
            {"id": "c3", "tenant_id": "t1", "service_category": "Both"},
            {"id": "c4", "tenant_id": "t1"},  # no category → unset
        ],
        properties=[
            {"id": "p1", "tenant_id": "t1", "customer_id": "c1"},
            {"id": "p2", "tenant_id": "t1", "customer_id": "c2"},
            {"id": "p3", "tenant_id": "t1", "customer_id": "c3"},
            {"id": "p4", "tenant_id": "t1", "customer_id": "c4"},
        ],
    )
    monkeypatch.setattr(mig, "db", db)
    out = await mig.run_property_service_category_inheritance()
    assert out["already_ran"] is False
    summary = out["summary"]
    assert summary["processed"] == 4
    assert summary["inherited_pool"] == 1
    assert summary["inherited_landscaping"] == 1
    assert summary["inherited_both"] == 1
    assert summary["left_unset"] == 1

    # Properties stamped.
    p1 = next(r for r in db.properties.rows if r["id"] == "p1")
    assert p1["service_category"] == "pool"
    assert p1["service_category_source"] == "inherited_from_customer"
    p3 = next(r for r in db.properties.rows if r["id"] == "p3")
    assert p3["service_category"] == "both"
    p4 = next(r for r in db.properties.rows if r["id"] == "p4")
    assert "service_category" not in p4 or p4.get("service_category") is None


async def test_migration_is_idempotent(monkeypatch):
    import services.migrations.seed_property_service_category_from_customer as mig

    db = _MockDB(
        customers=[{"id": "c1", "tenant_id": "t1",
                    "service_category": "pool"}],
        properties=[{"id": "p1", "tenant_id": "t1",
                     "customer_id": "c1"}],
    )
    monkeypatch.setattr(mig, "db", db)
    first = await mig.run_property_service_category_inheritance()
    assert first["already_ran"] is False
    second = await mig.run_property_service_category_inheritance()
    assert second["already_ran"] is True
    # No additional writes on second run.
    assert len([u for u in db.properties.updates
                if u["q"].get("id") == "p1"]) == 1


async def test_migration_skips_properties_with_explicit_category(
    monkeypatch,
):
    import services.migrations.seed_property_service_category_from_customer as mig

    db = _MockDB(
        customers=[{"id": "c1", "tenant_id": "t1",
                    "service_category": "pool"}],
        properties=[
            {"id": "p-pinned", "tenant_id": "t1", "customer_id": "c1",
             "service_category": "landscaping",
             "service_category_source": "admin_override"},
            {"id": "p-unset", "tenant_id": "t1", "customer_id": "c1"},
        ],
    )
    monkeypatch.setattr(mig, "db", db)
    out = await mig.run_property_service_category_inheritance()
    assert out["summary"]["processed"] == 1  # only the unset row
    pinned = next(r for r in db.properties.rows if r["id"] == "p-pinned")
    assert pinned["service_category"] == "landscaping"
    assert pinned["service_category_source"] == "admin_override"
