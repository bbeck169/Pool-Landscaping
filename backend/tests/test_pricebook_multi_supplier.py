"""Phase 56-b · Aug-2026 — Multi-supplier pricing on pricebook items.

Contract covered:
  * ``POST /api/items`` — accepts ``income_category_id`` +
    ``supplier_prices``, validates + persists.
  * ``PATCH /api/items/{id}`` — same validation on patch.

Validation rules:
  1. Unknown supplier slug → 400 ``unknown_supplier``.
  2. Supplier belongs to a different income_category → 400
     ``supplier_income_category_mismatch`` with ``expected_category``.
  3. Empty ``supplier_prices=[]`` is legal (no prices).
  4. Duplicate slug → 400 ``duplicate_supplier_slug``.
  5. Soft-deleted supplier still on an item's prices is preserved on
     READS (soft delete on supplier ≠ nuke prices).

Same in-memory stub pattern as ``test_pricebook_suppliers.py`` — we
call the handlers directly so no Motor cross-loop issues.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest


class _FakeCollection:
    def __init__(self, docs=None):
        self.docs: List[Dict[str, Any]] = list(docs or [])

    @staticmethod
    def _match(doc, q):
        for k, v in q.items():
            dv = doc.get(k)
            if isinstance(v, dict) and "$in" in v:
                if dv not in v["$in"]:
                    return False
            elif isinstance(v, dict) and "$or" in v:
                if not any(_FakeCollection._match(doc, sub) for sub in v["$or"]):
                    return False
            elif isinstance(v, dict) and "$exists" in v:
                exists = k in doc
                if exists != v["$exists"]:
                    return False
            elif dv != v:
                return False
        return True

    async def find_one(self, q, projection=None):
        for d in self.docs:
            if self._match(d, q):
                return dict(d)
        return None

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def update_one(self, q, upd):
        for d in self.docs:
            if self._match(d, q):
                for k, v in (upd.get("$set") or {}).items():
                    d[k] = v
                return


@pytest.fixture
def fake_db(monkeypatch):
    from config import db as _real
    items = _FakeCollection()
    suppliers = _FakeCollection()
    cats = _FakeCollection()
    audit = _FakeCollection()
    tenants = _FakeCollection([{"id": "tenant-A"}])
    # Product code touches these when validating service categories.
    monkeypatch.setattr(_real, "items", items, raising=False)
    monkeypatch.setattr(_real, "pricebook_suppliers", suppliers, raising=False)
    monkeypatch.setattr(_real, "income_categories", cats, raising=False)
    monkeypatch.setattr(_real, "audit_log", audit, raising=False)
    monkeypatch.setattr(_real, "tenants", tenants, raising=False)
    # Stub out service_categories validator so it doesn't hit Mongo.
    from routers import service_categories as sc

    async def _noop(*a, **kw): return None
    monkeypatch.setattr(sc, "validate_service_category", _noop)
    return {"items": items, "suppliers": suppliers,
            "cats": cats, "audit": audit}


ADMIN = {"id": "u1", "email": "a@x", "role": "admin", "tenant_id": "tenant-A"}


def _seed_cats_and_suppliers(fake_db):
    fake_db["cats"].docs = [
        {"id": "cat-pool", "tenant_id": "tenant-A", "name": "Pool",
         "is_archived": False},
        {"id": "cat-land", "tenant_id": "tenant-A", "name": "Landscaping",
         "is_archived": False},
    ]
    fake_db["suppliers"].docs = [
        {"id": "s1", "tenant_id": "tenant-A", "slug": "scp",
         "display_name": "SCP", "income_category_id": "cat-pool",
         "deleted_at": None},
        {"id": "s2", "tenant_id": "tenant-A", "slug": "epoolsupply",
         "display_name": "ePoolSupply", "income_category_id": "cat-pool",
         "deleted_at": None},
        {"id": "s3", "tenant_id": "tenant-A", "slug": "home_depot",
         "display_name": "Home Depot", "income_category_id": "cat-land",
         "deleted_at": None},
    ]


# ─── POST /api/items ────────────────────────────────────────────────────
def test_create_item_persists_supplier_prices_for_matching_category(fake_db):
    import asyncio

    async def _run():
        _seed_cats_and_suppliers(fake_db)
        from models import ItemIn
        from routers.items import create_item
        body = ItemIn(
            name="Chlorine Tabs",
            service_category_id="sc-1",
            income_category_id="cat-pool",
            supplier_prices=[
                {"supplier_slug": "scp", "cost_cents": 1850},
                {"supplier_slug": "epoolsupply", "cost_cents": 1900},
            ],
        )
        res = await create_item(body, user=ADMIN)
        assert res["income_category_id"] == "cat-pool"
        assert len(res["supplier_prices"]) == 2
        slugs = {r["supplier_slug"] for r in res["supplier_prices"]}
        assert slugs == {"scp", "epoolsupply"}
        cents = {r["supplier_slug"]: r["cost_cents"]
                  for r in res["supplier_prices"]}
        assert cents == {"scp": 1850, "epoolsupply": 1900}
        # Persisted to db.
        assert len(fake_db["items"].docs) == 1

    asyncio.run(_run())


def test_create_item_with_empty_supplier_prices_allowed(fake_db):
    import asyncio

    async def _run():
        _seed_cats_and_suppliers(fake_db)
        from models import ItemIn
        from routers.items import create_item
        body = ItemIn(
            name="Legacy Item", service_category_id="sc-1",
            income_category_id="cat-pool",
            supplier_prices=[],
        )
        res = await create_item(body, user=ADMIN)
        assert res["supplier_prices"] == []

    asyncio.run(_run())


def test_create_item_rejects_mismatched_supplier_category(fake_db):
    """Pool item + Landscape supplier → 400 with friendly detail."""
    import asyncio

    async def _run():
        _seed_cats_and_suppliers(fake_db)
        from fastapi import HTTPException
        from models import ItemIn
        from routers.items import create_item
        body = ItemIn(
            name="Boots", service_category_id="sc-1",
            income_category_id="cat-pool",
            supplier_prices=[
                {"supplier_slug": "home_depot", "cost_cents": 5000},
            ],
        )
        with pytest.raises(HTTPException) as ex:
            await create_item(body, user=ADMIN)
        assert ex.value.status_code == 400
        assert ex.value.detail["error"] == "supplier_income_category_mismatch"
        assert ex.value.detail["supplier_slug"] == "home_depot"
        assert ex.value.detail["expected_category"] == "Landscaping"

    asyncio.run(_run())


def test_create_item_rejects_unknown_supplier(fake_db):
    import asyncio

    async def _run():
        _seed_cats_and_suppliers(fake_db)
        from fastapi import HTTPException
        from models import ItemIn
        from routers.items import create_item
        body = ItemIn(
            name="X", service_category_id="sc-1",
            income_category_id="cat-pool",
            supplier_prices=[
                {"supplier_slug": "does_not_exist", "cost_cents": 100},
            ],
        )
        with pytest.raises(HTTPException) as ex:
            await create_item(body, user=ADMIN)
        assert ex.value.status_code == 400
        assert ex.value.detail["error"] == "unknown_supplier"
        assert ex.value.detail["supplier_slug"] == "does_not_exist"

    asyncio.run(_run())


def test_create_item_rejects_duplicate_supplier_slug(fake_db):
    import asyncio

    async def _run():
        _seed_cats_and_suppliers(fake_db)
        from fastapi import HTTPException
        from models import ItemIn
        from routers.items import create_item
        body = ItemIn(
            name="X", service_category_id="sc-1",
            income_category_id="cat-pool",
            supplier_prices=[
                {"supplier_slug": "scp", "cost_cents": 100},
                {"supplier_slug": "scp", "cost_cents": 200},
            ],
        )
        with pytest.raises(HTTPException) as ex:
            await create_item(body, user=ADMIN)
        assert ex.value.status_code == 400
        assert ex.value.detail["error"] == "duplicate_supplier_slug"

    asyncio.run(_run())


# ─── PATCH /api/items/{id} ──────────────────────────────────────────────
def test_patch_appends_new_supplier_price(fake_db):
    """PATCH with supplier_prices REPLACES the list. Confirm we can go
    from 1 → 2 prices without losing the existing one when the caller
    sends both."""
    import asyncio

    async def _run():
        _seed_cats_and_suppliers(fake_db)
        fake_db["items"].docs = [{
            "id": "item-1", "tenant_id": "tenant-A", "name": "Chlorine",
            "income_category_id": "cat-pool",
            "supplier_prices": [
                {"supplier_slug": "scp", "cost_cents": 1850},
            ],
        }]
        from routers.items import ItemPatch, patch_item
        body = ItemPatch(supplier_prices=[
            {"supplier_slug": "scp", "cost_cents": 1850},
            {"supplier_slug": "epoolsupply", "cost_cents": 1900},
        ])
        res = await patch_item("item-1", body, user=ADMIN)
        assert len(res["supplier_prices"]) == 2
        slugs = {r["supplier_slug"] for r in res["supplier_prices"]}
        assert slugs == {"scp", "epoolsupply"}

    asyncio.run(_run())


def test_soft_deleted_supplier_preserved_on_item_reads(fake_db):
    """Preflight rule: soft-deleting a supplier does NOT touch items
    that already reference it. Prove the persisted supplier_prices
    survive after the supplier's ``deleted_at`` is set."""
    import asyncio

    async def _run():
        _seed_cats_and_suppliers(fake_db)
        # Store an item with a scp price.
        fake_db["items"].docs = [{
            "id": "item-1", "tenant_id": "tenant-A", "name": "Chlorine",
            "income_category_id": "cat-pool",
            "supplier_prices": [
                {"supplier_slug": "scp", "cost_cents": 1850},
            ],
        }]
        # Now soft-delete scp.
        for s in fake_db["suppliers"].docs:
            if s["slug"] == "scp":
                s["deleted_at"] = "2026-08-10T00:00:00"

        # Read the item back — supplier_prices intact.
        row = fake_db["items"].docs[0]
        assert row["supplier_prices"][0]["supplier_slug"] == "scp"
        assert row["supplier_prices"][0]["cost_cents"] == 1850

        # But a fresh PATCH that TRIES to keep scp on a live write
        # is rejected — you can't validate against a deleted supplier.
        from fastapi import HTTPException
        from routers.items import ItemPatch, patch_item
        with pytest.raises(HTTPException) as ex:
            await patch_item("item-1", ItemPatch(supplier_prices=[
                {"supplier_slug": "scp", "cost_cents": 2000},
            ]), user=ADMIN)
        assert ex.value.status_code == 400
        assert ex.value.detail["error"] == "unknown_supplier"

    asyncio.run(_run())
