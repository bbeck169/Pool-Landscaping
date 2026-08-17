"""Task 4 · Feb-2026 — hydrate_homeworks_pricebook_prices pytest.

Uses an in-memory fake Mongo matching the shape of the pricebook /
dispatcher test suites so the same idioms carry over.

Covered:
  1. **Supplier upsert idempotency** — running twice creates the row
     once and reports supplier_created only on the first pass.
  2. **Hydration idempotency** — a second run with identical
     ``homeworks_costs`` produces zero writes (items_unchanged
     grows, items_hydrated stays 0).
  3. **Prices shape correct** — the injected ``supplier_prices``
     entry matches the user-brief schema
     ``{supplier_slug, cost_cents, retail_cents, currency}``.
  4. **``homeworks_costs`` blob preserved** — never mutated by the
     script.
  5. **Non-Homeworks entries survive** — a hand-added ``scp``
     supplier_prices entry is left untouched.
  6. **Missing-cost skip** — items with 0 cost and 0 retail are
     counted as ``items_skipped_missing_costs`` and not touched.
"""
from __future__ import annotations

import asyncio
import re
import sys
from typing import Any, Dict, List

import pytest

sys.path.insert(0, "/app/backend")

from scripts.hydrate_homeworks_pricebook_prices import (  # noqa: E402
    upsert_homeworks_supplier, hydrate_items, Counters,
    HOMEWORKS_SLUG,
)


# ── Fake Mongo (matches pricebook test shape) ────────────────────────
def _match(d, q):
    for k, v in q.items():
        actual = d.get(k)
        if isinstance(v, dict):
            if "$ne" in v and actual == v["$ne"]:
                return False
            if "$exists" in v and (k in d) != bool(v["$exists"]):
                return False
        else:
            if actual != v:
                return False
    return True


class _Cursor:
    def __init__(self, rows): self._rows = rows

    def __aiter__(self):
        self._i = 0
        return self

    async def __anext__(self):
        if self._i >= len(self._rows):
            raise StopAsyncIteration
        r = self._rows[self._i]
        self._i += 1
        return r


class _Coll:
    def __init__(self):
        self._d: List[Dict[str, Any]] = []

    async def find_one(self, q, projection=None):
        for d in self._d:
            if _match(d, q):
                return {**d}
        return None

    def find(self, q, projection=None):
        return _Cursor([{**d} for d in self._d if _match(d, q)])

    async def insert_one(self, doc):
        self._d.append({**doc})

    async def update_one(self, q, upd):
        for d in self._d:
            if _match(d, q):
                if "$set" in upd:
                    d.update(upd["$set"])
                return


class _DB:
    def __init__(self):
        self.pricebook_suppliers = _Coll()
        self.income_categories = _Coll()
        self.items = _Coll()


@pytest.fixture
def db_with_pool():
    db = _DB()
    asyncio.get_event_loop().run_until_complete(
        db.income_categories.insert_one({
            "tenant_id": "t1", "id": "ic-pool", "name": "Pool",
        }),
    )
    return db


# ── 1. Supplier upsert idempotency ───────────────────────────────────
def test_supplier_upsert_is_idempotent(db_with_pool):
    db = db_with_pool
    c1 = Counters()
    asyncio.get_event_loop().run_until_complete(
        upsert_homeworks_supplier(db, "t1", dry_run=False, counters=c1),
    )
    assert c1.supplier_created is True

    # Second run — no changes needed → both flags stay False.
    c2 = Counters()
    asyncio.get_event_loop().run_until_complete(
        upsert_homeworks_supplier(db, "t1", dry_run=False, counters=c2),
    )
    assert c2.supplier_created is False
    assert c2.supplier_updated is False

    # And only ONE supplier row exists.
    matches = [d for d in db.pricebook_suppliers._d
                if d.get("slug") == HOMEWORKS_SLUG and d.get("tenant_id") == "t1"]
    assert len(matches) == 1
    assert matches[0]["income_category_id"] == "ic-pool"


# ── 2. Hydration idempotency ─────────────────────────────────────────
def test_hydration_second_run_yields_zero_writes(db_with_pool):
    db = db_with_pool
    asyncio.get_event_loop().run_until_complete(
        db.items.insert_one({
            "tenant_id": "t1", "id": "i-1", "imported_from": "homeworks",
            "name": "Pump", "unit_price": 100.0, "wholesale_price": 40.0,
            "supplier_prices": [],
            "homeworks_costs": {"wholesaleCost": 40.0},
        }),
    )
    c = Counters()
    asyncio.get_event_loop().run_until_complete(
        upsert_homeworks_supplier(db, "t1", dry_run=False, counters=c),
    )
    asyncio.get_event_loop().run_until_complete(
        hydrate_items(db, "t1", dry_run=False, counters=c,
                       sample_snapshots=[]),
    )
    assert c.items_hydrated == 1
    assert c.prices_added == 1

    # Second pass — no changes.
    c2 = Counters()
    asyncio.get_event_loop().run_until_complete(
        hydrate_items(db, "t1", dry_run=False, counters=c2,
                       sample_snapshots=[]),
    )
    assert c2.items_hydrated == 0
    assert c2.items_unchanged == 1
    assert c2.prices_added == 0


# ── 3. Supplier_prices shape correct ─────────────────────────────────
def test_supplier_prices_shape(db_with_pool):
    db = db_with_pool
    asyncio.get_event_loop().run_until_complete(
        db.items.insert_one({
            "tenant_id": "t1", "id": "i-1", "imported_from": "homeworks",
            "name": "Chlorine", "unit_price": 25.5, "wholesale_price": 12.75,
            "supplier_prices": [],
            "homeworks_costs": {"wholesaleCost": 12.75},
        }),
    )
    c = Counters()
    asyncio.get_event_loop().run_until_complete(
        upsert_homeworks_supplier(db, "t1", dry_run=False, counters=c),
    )
    asyncio.get_event_loop().run_until_complete(
        hydrate_items(db, "t1", dry_run=False, counters=c,
                       sample_snapshots=[]),
    )
    row = asyncio.get_event_loop().run_until_complete(
        db.items.find_one({"id": "i-1"}),
    )
    assert row["supplier_prices"] == [{
        "supplier_slug": "homeworks",
        "cost_cents": 1275,
        "retail_cents": 2550,
        "currency": "USD",
    }]


# ── 4. homeworks_costs blob preserved ────────────────────────────────
def test_homeworks_costs_preserved(db_with_pool):
    db = db_with_pool
    original_costs = {
        "wholesaleCost": 10.0, "materialCost": 4.0,
        "markupType": "PERCENT", "markup": 60.0,
    }
    asyncio.get_event_loop().run_until_complete(
        db.items.insert_one({
            "tenant_id": "t1", "id": "i-1", "imported_from": "homeworks",
            "name": "X", "unit_price": 20.0, "supplier_prices": [],
            "homeworks_costs": original_costs,
        }),
    )
    c = Counters()
    asyncio.get_event_loop().run_until_complete(
        upsert_homeworks_supplier(db, "t1", dry_run=False, counters=c),
    )
    asyncio.get_event_loop().run_until_complete(
        hydrate_items(db, "t1", dry_run=False, counters=c,
                       sample_snapshots=[]),
    )
    row = asyncio.get_event_loop().run_until_complete(
        db.items.find_one({"id": "i-1"}),
    )
    assert row["homeworks_costs"] == original_costs


# ── 5. Non-Homeworks entries survive ─────────────────────────────────
def test_non_homeworks_supplier_prices_left_alone(db_with_pool):
    db = db_with_pool
    asyncio.get_event_loop().run_until_complete(
        db.items.insert_one({
            "tenant_id": "t1", "id": "i-1", "imported_from": "homeworks",
            "name": "X", "unit_price": 20.0,
            "supplier_prices": [
                {"supplier_slug": "scp", "cost_cents": 500, "retail_cents": 1000, "currency": "USD"},
            ],
            "homeworks_costs": {"wholesaleCost": 5.0},
        }),
    )
    c = Counters()
    asyncio.get_event_loop().run_until_complete(
        upsert_homeworks_supplier(db, "t1", dry_run=False, counters=c),
    )
    asyncio.get_event_loop().run_until_complete(
        hydrate_items(db, "t1", dry_run=False, counters=c,
                       sample_snapshots=[]),
    )
    row = asyncio.get_event_loop().run_until_complete(
        db.items.find_one({"id": "i-1"}),
    )
    slugs = {e["supplier_slug"] for e in row["supplier_prices"]}
    assert slugs == {"scp", "homeworks"}


# ── 6. Missing-cost skip ─────────────────────────────────────────────
def test_zero_cost_and_retail_are_skipped(db_with_pool):
    db = db_with_pool
    asyncio.get_event_loop().run_until_complete(
        db.items.insert_one({
            "tenant_id": "t1", "id": "i-zero", "imported_from": "homeworks",
            "name": "Test", "unit_price": 0, "wholesale_price": 0,
            "supplier_prices": [],
            "homeworks_costs": {"wholesaleCost": 0, "materialCost": 0},
        }),
    )
    c = Counters()
    asyncio.get_event_loop().run_until_complete(
        upsert_homeworks_supplier(db, "t1", dry_run=False, counters=c),
    )
    asyncio.get_event_loop().run_until_complete(
        hydrate_items(db, "t1", dry_run=False, counters=c,
                       sample_snapshots=[]),
    )
    assert c.items_scanned == 1
    assert c.items_hydrated == 0
    assert c.items_skipped_missing_costs == 1
    row = asyncio.get_event_loop().run_until_complete(
        db.items.find_one({"id": "i-zero"}),
    )
    assert row["supplier_prices"] == []
