"""Feb-2026 · Phase 2 · Pricebook supplier_prices backfill tests.

Uses sync ``pymongo`` fixtures on an ephemeral test tenant so the
Motor-loop-binding class of flakes is avoided entirely. Every test
creates + tears down its own tenant + items so there's no ordering
dependency and no cross-test pollution.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from pymongo import MongoClient

# Point script imports at the backend root.
import sys
sys.path.insert(0, "/app/backend")

from scripts.backfill_pricebook_supplier_prices import _run_tenant  # noqa: E402


def _read_env(key: str) -> str:
    v = os.environ.get(key)
    if v:
        return v
    for ln in Path("/app/backend/.env").read_text().splitlines():
        if ln.startswith(f"{key}="):
            return ln.split("=", 1)[1].strip().strip('"')
    return ""


@pytest.fixture(scope="module")
def sync_db():
    cli = MongoClient(_read_env("MONGO_URL"), serverSelectionTimeoutMS=5000)
    try:
        yield cli[_read_env("DB_NAME") or "aquaterra"]
    finally:
        cli.close()


@pytest.fixture()
def test_tenant(sync_db):
    """Ephemeral tenant with the minimum config the hydration helper
    needs (an income_category). Torn down entirely after the test."""
    tenant_id = f"test-backfill-{uuid.uuid4().hex[:10]}"
    sync_db.tenants.insert_one({"id": tenant_id, "name": "test-backfill"})
    cat_id = f"cat-{uuid.uuid4().hex[:8]}"
    sync_db.income_categories.insert_one({
        "id": cat_id, "tenant_id": tenant_id, "name": "Pool",
    })
    yield tenant_id, cat_id
    # Teardown
    for coll in ("tenants", "income_categories", "items",
                   "pricebook_suppliers"):
        sync_db[coll].delete_many({"tenant_id": tenant_id})


def _make_item(tenant_id: str, *, homeworks_costs: dict | None,
                 supplier_prices=None, unit_price: float = 25.0):
    return {
        "id": f"item-{uuid.uuid4().hex[:8]}",
        "tenant_id": tenant_id,
        "name": "Test item",
        "unit_price": unit_price,
        "imported_from": "homeworks" if homeworks_costs is not None else None,
        "homeworks_costs": homeworks_costs,
        "supplier_prices": supplier_prices or [],
    }


def _sync_run(coro_factory):
    """Run one-shot async on a fresh loop with a fresh Motor client
    bound to that loop, avoiding the ``config.db`` global whose loop
    binding causes cross-test collisions."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro_factory())
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def _motor_db_factory():
    """Return a fresh Motor client bound to whichever loop the caller
    is currently running under. Callers must invoke this *inside* the
    async body, not at module import time."""
    from motor.motor_asyncio import AsyncIOMotorClient
    cli = AsyncIOMotorClient(_read_env("MONGO_URL"))
    return cli[_read_env("DB_NAME") or "aquaterra"]


def test_hydratable_item_gets_populated(sync_db, test_tenant):
    tenant_id, _cat = test_tenant
    hydratable = _make_item(tenant_id, homeworks_costs={
        "materialCost": 5.0, "wholesaleCost": 3.75, "markup": 1.0,
    }, unit_price=25.0)
    sync_db.items.insert_one(hydratable)

    report = _sync_run(lambda: _run_tenant(_motor_db_factory(), tenant_id, commit=True))
    assert report.hydrated == 1, report
    assert report.skipped_already_populated == 0

    persisted = sync_db.items.find_one({"id": hydratable["id"]})
    prices = persisted["supplier_prices"]
    assert len(prices) == 1
    entry = prices[0]
    assert entry["supplier_slug"] == "homeworks"
    assert entry["cost_cents"] == 375, entry
    assert entry["retail_cents"] == 2500, entry
    # Raw source must survive untouched.
    assert persisted["homeworks_costs"]["wholesaleCost"] == 3.75


def test_already_populated_item_is_untouched(sync_db, test_tenant):
    tenant_id, _cat = test_tenant
    pre_hydrated = _make_item(
        tenant_id,
        homeworks_costs={"materialCost": 5.0, "wholesaleCost": 3.75},
        supplier_prices=[{
            "supplier_slug": "homeworks",
            "cost_cents": 999,  # obviously wrong — proves we don't overwrite
            "retail_cents": 999,
            "currency": "USD",
        }],
        unit_price=25.0,
    )
    sync_db.items.insert_one(pre_hydrated)

    report = _sync_run(lambda: _run_tenant(_motor_db_factory(), tenant_id, commit=True))
    assert report.hydrated == 0, report
    assert report.skipped_already_populated == 1

    persisted = sync_db.items.find_one({"id": pre_hydrated["id"]})
    assert persisted["supplier_prices"][0]["cost_cents"] == 999


def test_unmapped_supplier_item_is_skipped_and_reported(sync_db):
    """A tenant without any income_categories cannot get a
    pricebook_suppliers row upserted, so hydratable items must be
    reported under ``skipped_unmapped_supplier`` — not silently
    hydrated against a phantom supplier."""
    tenant_id = f"test-unmapped-{uuid.uuid4().hex[:10]}"
    sync_db.tenants.insert_one({"id": tenant_id, "name": "test-unmapped"})
    hydratable = _make_item(tenant_id, homeworks_costs={
        "materialCost": 5.0, "wholesaleCost": 3.75,
    }, unit_price=25.0)
    sync_db.items.insert_one(hydratable)
    try:
        report = _sync_run(lambda: _run_tenant(_motor_db_factory(), tenant_id, commit=True))
        assert report.hydrated == 0
        assert report.skipped_unmapped_supplier == 1, report
        reasons = [x["reason"] for x in report.skipped_items]
        assert any("unmapped_supplier" in r for r in reasons), reasons
        persisted = sync_db.items.find_one({"id": hydratable["id"]})
        assert persisted["supplier_prices"] == []
    finally:
        for coll in ("tenants", "items", "pricebook_suppliers"):
            sync_db[coll].delete_many({"tenant_id": tenant_id})


def test_idempotent_second_commit_is_a_noop(sync_db, test_tenant):
    tenant_id, _cat = test_tenant
    hydratable = _make_item(tenant_id, homeworks_costs={
        "materialCost": 4.0, "wholesaleCost": 2.5,
    }, unit_price=10.0)
    sync_db.items.insert_one(hydratable)

    first = _sync_run(lambda: _run_tenant(_motor_db_factory(), tenant_id, commit=True))
    assert first.hydrated == 1

    persisted_after_first = sync_db.items.find_one({"id": hydratable["id"]})
    updated_at_first = persisted_after_first.get("updated_at")

    second = _sync_run(lambda: _run_tenant(_motor_db_factory(), tenant_id, commit=True))
    assert second.hydrated == 0, second
    assert second.skipped_already_populated == 1

    persisted_after_second = sync_db.items.find_one({"id": hydratable["id"]})
    # No write happened on the second commit — updated_at unchanged.
    assert persisted_after_second.get("updated_at") == updated_at_first


def test_no_source_blob_item_bucketed_correctly(sync_db, test_tenant):
    tenant_id, _cat = test_tenant
    orphan = _make_item(tenant_id, homeworks_costs=None, unit_price=10.0)
    orphan.pop("homeworks_costs")
    sync_db.items.insert_one(orphan)
    report = _sync_run(lambda: _run_tenant(_motor_db_factory(), tenant_id, commit=True))
    assert report.skipped_no_source == 1
    assert report.hydrated == 0
    reasons = [x["reason"] for x in report.skipped_items]
    assert "no_source_blob" in reasons


def test_all_costs_zero_item_bucketed_correctly(sync_db, test_tenant):
    tenant_id, _cat = test_tenant
    zeros = _make_item(tenant_id, homeworks_costs={
        "materialCost": 0.0, "wholesaleCost": 0.0,
        "equipmentCost": 0.0, "subcontractCost": 0.0,
    }, unit_price=15.0)
    sync_db.items.insert_one(zeros)
    report = _sync_run(lambda: _run_tenant(_motor_db_factory(), tenant_id, commit=True))
    assert report.skipped_all_costs_zero == 1, report
    assert report.hydrated == 0
    reasons = [x["reason"] for x in report.skipped_items]
    assert "all_costs_zero" in reasons


def test_dry_run_does_not_persist(sync_db, test_tenant):
    tenant_id, cat_id = test_tenant
    # Pre-provision the homeworks supplier row so the dry-run path can
    # accurately preview the hydration count (in commit mode this
    # would be auto-upserted). The test asserts BOTH that the item
    # is hydrated-in-plan AND that no store mutation occurs.
    import uuid as _uuid
    sync_db.pricebook_suppliers.insert_one({
        "id": _uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "slug": "homeworks",
        "display_name": "Homeworks (imported)",
        "income_category_id": cat_id,
        "is_active": True,
    })
    hydratable = _make_item(tenant_id, homeworks_costs={
        "materialCost": 4.0, "wholesaleCost": 2.5,
    }, unit_price=10.0)
    sync_db.items.insert_one(hydratable)

    report = _sync_run(lambda: _run_tenant(_motor_db_factory(), tenant_id, commit=False))
    # ``hydrated`` counts intent, not the write — this matches the
    # reused hydration helper's contract.
    assert report.hydrated == 1, report

    persisted = sync_db.items.find_one({"id": hydratable["id"]})
    assert persisted["supplier_prices"] == [], (
        "dry-run must not touch the store"
    )
