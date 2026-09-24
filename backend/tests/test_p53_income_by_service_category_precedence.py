"""Phase P53 tail · Feb-2026 — Fix A · Income by Service Category
resolution precedence.

Locks the resolution ladder for service-category bucketing in both
handlers:

  1. Line item's own ``service_category_id`` (user explicitly
     recategorized the line) — highest precedence.
  2. Pricebook item's ``service_category_id`` via
     ``line.item_id`` → ``db.items``.
  3. ``"Uncategorized"`` fallback when neither is set.

Pre-P53 the tile + drilldown only read the pricebook item, so a
recategorized line still bucketed under the item's original
category. User-visible bug: report showed "Uncategorized" for lines
the user had explicitly moved elsewhere.

Uses ``_phase34_asyncio.batch_safe_run`` for Motor loop consistency.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._phase34_asyncio import batch_safe_run as _run


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "p53_fixA_"


@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def scenario(dbc):
    ids = {
        "tenants": [], "items": [], "service_categories": [],
        "income_categories": [], "quotes": [],
    }
    yield ids
    for coll, keys in ids.items():
        if keys:
            dbc[coll].delete_many({"id": {"$in": keys}})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_tenant(dbc, scenario) -> dict:
    tid = f"{TAG}tenant-{uuid.uuid4().hex[:8]}"
    dbc.tenants.insert_one({
        "id": tid,
        "name": f"P53 Fix A test {tid}",
        "created_at": _now(),
    })
    scenario["tenants"].append(tid)
    return {"id": tid, "name": f"P53 Fix A test {tid}"}


def _seed_service_category(dbc, scenario, *, tenant_id: str,
                              name: str) -> str:
    sid = f"{TAG}svc-{uuid.uuid4().hex[:8]}"
    dbc.service_categories.insert_one({
        "id": sid, "tenant_id": tenant_id, "name": name,
        "created_at": _now(),
    })
    scenario["service_categories"].append(sid)
    return sid


def _seed_pricebook_item(dbc, scenario, *, tenant_id: str,
                           name: str,
                           service_category_id: str = None) -> str:
    iid = f"{TAG}item-{uuid.uuid4().hex[:8]}"
    dbc.items.insert_one({
        "id": iid,
        "tenant_id": tenant_id,
        "name": name,
        "service_category_id": service_category_id,
        "category": None,
        "created_at": _now(),
    })
    scenario["items"].append(iid)
    return iid


def _seed_paid_invoice(dbc, scenario, *, tenant_id: str,
                         line_items: list, total: float = None) -> str:
    qid = f"{TAG}q-{uuid.uuid4().hex[:8]}"
    now = _now()
    if total is None:
        total = sum(
            float(li.get("quantity") or 0) * float(li.get("unit_price") or 0)
            for li in line_items
        )
    dbc.quotes.insert_one({
        "id": qid,
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "status": "paid",
        "payment_status": "paid",
        "line_items": line_items,
        "total": total,
        "currency": "USD",
        "created_at": now,
        "issue_date": now,
        "invoice_date": now,
        "customer_id": f"{TAG}cust-{uuid.uuid4().hex[:6]}",
    })
    scenario["quotes"].append(qid)
    return qid


def _call_tile(tenant: dict) -> dict:
    """Directly invoke the FastAPI handler function (bypassing DI)."""
    from routers.dashboard_revenue import income_by_service_category

    return _run(income_by_service_category(
        start="2020-01-01T00:00:00+00:00",
        end="2099-01-01T00:00:00+00:00",
        user={"role": "admin", "tenant_id": tenant["id"]},
        tenant=tenant,
    ))


def _call_drilldown(tenant: dict, *, service_category_id: str) -> dict:
    from routers.dashboard_drilldown import income_by_service_rows

    return _run(income_by_service_rows(
        service_category_id=service_category_id,
        from_="2020-01-01T00:00:00+00:00",
        to="2099-01-01T00:00:00+00:00",
        limit=100,
        cursor=None,
        user={"role": "admin", "tenant_id": tenant["id"]},
        tenant=tenant,
    ))


def _amount(tile: dict, name: str) -> float:
    for row in tile["items"]:
        if row["category"] == name:
            return row["amount"]
    return 0.0


# ═════════════════════════════════════════════════════════════════════
# Section 1 — Tile precedence
# ═════════════════════════════════════════════════════════════════════
def test_tile_line_service_category_id_beats_pricebook(dbc, scenario):
    """A line with an EXPLICIT ``service_category_id`` MUST bucket
    to that category — NOT the pricebook item's category. This is
    the P53 fix scenario."""
    tenant = _seed_tenant(dbc, scenario)
    landscaping = _seed_service_category(
        dbc, scenario, tenant_id=tenant["id"], name="Landscaping",
    )
    pool = _seed_service_category(
        dbc, scenario, tenant_id=tenant["id"], name="Pool Service",
    )
    # Pricebook item points at Landscaping.
    item_land = _seed_pricebook_item(
        dbc, scenario, tenant_id=tenant["id"],
        name="Bush Trim", service_category_id=landscaping,
    )
    # But the LINE explicitly overrides to Pool Service.
    _seed_paid_invoice(dbc, scenario, tenant_id=tenant["id"], line_items=[
        {"item_id": item_land, "service_category_id": pool,
          "quantity": 1, "unit_price": 100.00,
          "description": "Recategorized to Pool"},
    ])

    tile = _call_tile(tenant)

    assert _amount(tile, "Pool Service") == 100.00, (
        f"line-level service_category_id was NOT honored; tile={tile}"
    )
    assert _amount(tile, "Landscaping") == 0.0, (
        "pricebook precedence regression — Landscaping should be $0"
    )


def test_tile_falls_back_to_pricebook_when_line_has_no_override(
    dbc, scenario,
):
    """Line with NO explicit ``service_category_id`` inherits the
    pricebook item's category (the pre-P53 default path)."""
    tenant = _seed_tenant(dbc, scenario)
    landscaping = _seed_service_category(
        dbc, scenario, tenant_id=tenant["id"], name="Landscaping",
    )
    item_land = _seed_pricebook_item(
        dbc, scenario, tenant_id=tenant["id"],
        name="Bush Trim", service_category_id=landscaping,
    )
    _seed_paid_invoice(dbc, scenario, tenant_id=tenant["id"], line_items=[
        {"item_id": item_land, "quantity": 2, "unit_price": 50.00,
          "description": "Default inherit"},
    ])

    tile = _call_tile(tenant)

    assert _amount(tile, "Landscaping") == 100.00, (
        f"fallback path regressed; tile={tile}"
    )


def test_tile_buckets_uncategorized_when_neither_line_nor_pricebook(
    dbc, scenario,
):
    tenant = _seed_tenant(dbc, scenario)
    item_bare = _seed_pricebook_item(
        dbc, scenario, tenant_id=tenant["id"],
        name="Bare Item", service_category_id=None,
    )
    _seed_paid_invoice(dbc, scenario, tenant_id=tenant["id"], line_items=[
        {"item_id": item_bare, "quantity": 3, "unit_price": 20.00,
          "description": "Truly uncategorized"},
    ])

    tile = _call_tile(tenant)

    assert _amount(tile, "Uncategorized") == 60.00


def test_tile_mixed_dataset_totals(dbc, scenario):
    tenant = _seed_tenant(dbc, scenario)
    landscaping = _seed_service_category(
        dbc, scenario, tenant_id=tenant["id"], name="Landscaping",
    )
    pool = _seed_service_category(
        dbc, scenario, tenant_id=tenant["id"], name="Pool Service",
    )
    item_land = _seed_pricebook_item(
        dbc, scenario, tenant_id=tenant["id"],
        name="Bush Trim", service_category_id=landscaping,
    )
    item_pool = _seed_pricebook_item(
        dbc, scenario, tenant_id=tenant["id"],
        name="Chlorine", service_category_id=pool,
    )
    item_bare = _seed_pricebook_item(
        dbc, scenario, tenant_id=tenant["id"],
        name="Misc", service_category_id=None,
    )
    _seed_paid_invoice(dbc, scenario, tenant_id=tenant["id"], line_items=[
        # Recategorized: landscaping → pool ($100)
        {"item_id": item_land, "service_category_id": pool,
          "quantity": 1, "unit_price": 100.00},
        # Default inherit: pool ($50)
        {"item_id": item_pool, "quantity": 1, "unit_price": 50.00},
        # Recategorized: pool → landscaping ($30)
        {"item_id": item_pool, "service_category_id": landscaping,
          "quantity": 1, "unit_price": 30.00},
        # No category anywhere ($15)
        {"item_id": item_bare, "quantity": 1, "unit_price": 15.00},
    ])

    tile = _call_tile(tenant)

    assert _amount(tile, "Pool Service") == 150.00
    assert _amount(tile, "Landscaping") == 30.00
    assert _amount(tile, "Uncategorized") == 15.00
    assert round(tile["total"], 2) == 195.00


def test_tile_cross_tenant_isolation(dbc, scenario):
    tenant_a = _seed_tenant(dbc, scenario)
    tenant_b = _seed_tenant(dbc, scenario)
    pool_a = _seed_service_category(
        dbc, scenario, tenant_id=tenant_a["id"], name="Pool Service",
    )
    item_a = _seed_pricebook_item(
        dbc, scenario, tenant_id=tenant_a["id"],
        name="A", service_category_id=pool_a,
    )
    _seed_paid_invoice(dbc, scenario, tenant_id=tenant_a["id"], line_items=[
        {"item_id": item_a, "service_category_id": pool_a,
          "quantity": 1, "unit_price": 999.00},
    ])

    tile_b = _call_tile(tenant_b)

    assert _amount(tile_b, "Pool Service") == 0.0
    assert tile_b["total"] == 0.0


# ═════════════════════════════════════════════════════════════════════
# Section 2 — Drilldown precedence + parity with the tile
# ═════════════════════════════════════════════════════════════════════
def test_drilldown_shows_recategorized_line_under_new_bucket(
    dbc, scenario,
):
    tenant = _seed_tenant(dbc, scenario)
    landscaping = _seed_service_category(
        dbc, scenario, tenant_id=tenant["id"], name="Landscaping",
    )
    pool = _seed_service_category(
        dbc, scenario, tenant_id=tenant["id"], name="Pool Service",
    )
    item_land = _seed_pricebook_item(
        dbc, scenario, tenant_id=tenant["id"],
        name="Bush Trim", service_category_id=landscaping,
    )
    _seed_paid_invoice(dbc, scenario, tenant_id=tenant["id"], line_items=[
        {"item_id": item_land, "service_category_id": pool,
          "quantity": 1, "unit_price": 100.00,
          "description": "Recategorized to Pool"},
    ])

    # Drilldown for Pool must include the recategorized line.
    rows_pool = _call_drilldown(tenant, service_category_id=pool)
    assert rows_pool["total"] == 1, rows_pool
    assert rows_pool["rows"][0]["extended"] == 100.00

    # Drilldown for Landscaping must NOT include it (pricebook path
    # regression check).
    rows_land = _call_drilldown(tenant, service_category_id=landscaping)
    assert rows_land["total"] == 0, (
        f"pricebook precedence bug regressed in drilldown; rows={rows_land}"
    )


def test_drilldown_and_tile_stay_in_lockstep(dbc, scenario):
    """Parity contract: a bucket showing $X on the tile MUST return
    rows summing to $X in the drilldown."""
    tenant = _seed_tenant(dbc, scenario)
    landscaping = _seed_service_category(
        dbc, scenario, tenant_id=tenant["id"], name="Landscaping",
    )
    pool = _seed_service_category(
        dbc, scenario, tenant_id=tenant["id"], name="Pool Service",
    )
    item_land = _seed_pricebook_item(
        dbc, scenario, tenant_id=tenant["id"],
        name="Bush Trim", service_category_id=landscaping,
    )
    item_pool = _seed_pricebook_item(
        dbc, scenario, tenant_id=tenant["id"],
        name="Chlorine", service_category_id=pool,
    )
    _seed_paid_invoice(dbc, scenario, tenant_id=tenant["id"], line_items=[
        {"item_id": item_land, "service_category_id": pool,
          "quantity": 1, "unit_price": 100.00},
        {"item_id": item_pool, "quantity": 1, "unit_price": 50.00},
        {"item_id": item_pool, "service_category_id": landscaping,
          "quantity": 1, "unit_price": 30.00},
    ])

    tile = _call_tile(tenant)
    tile_pool = _amount(tile, "Pool Service")
    tile_land = _amount(tile, "Landscaping")
    assert tile_pool == 150.00
    assert tile_land == 30.00

    rows_pool = _call_drilldown(tenant, service_category_id=pool)
    rows_land = _call_drilldown(tenant, service_category_id=landscaping)

    sum_pool = round(sum(r["extended"] for r in rows_pool["rows"]), 2)
    sum_land = round(sum(r["extended"] for r in rows_land["rows"]), 2)

    assert sum_pool == tile_pool, (
        f"tile/drilldown parity broken: tile Pool={tile_pool}, "
        f"drilldown sum={sum_pool}"
    )
    assert sum_land == tile_land, (
        f"tile/drilldown parity broken: tile Landscaping={tile_land}, "
        f"drilldown sum={sum_land}"
    )
