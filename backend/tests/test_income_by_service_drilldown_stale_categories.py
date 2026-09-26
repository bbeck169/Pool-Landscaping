"""Feb-2026 · Income-by-service drill-down — stale/deleted category refs.

Locks the drill-down's Uncategorized bucket to include every line
item whose ``service_category_id`` cannot be resolved via
``bucket_service_category`` on the chart tile, matching the chart's
own Uncategorized bucket cent-for-cent.

Pre-fix bug: the drill-down inlined a ``service_category_id`` →
``svc_name`` lookup and skipped lines whose id was present but
missing from ``svc_id_to_name`` (hard-deleted category, or belongs
to another tenant).  The chart tile — which uses the shared
``bucket_service_category`` helper — bucketed the same lines under
Uncategorized, so the drill-down modal under-reported the
Uncategorized total.

Post-fix contract:
  * Drill-down routes lines through the SAME ``bucket_service_category``
    ladder the tile uses (line ``service_category_id`` → pricebook
    ``item.service_category_id`` → ``UNCATEGORIZED_KEY`` fallback when
    neither resolves to a name in ``svc_id_to_name``).
  * Bucket matching is on ``bucket_id`` (real UUID or ``__uncategorized__``
    sentinel), NOT the inline svc_id from the line.
  * Parity contract: for every bucket key returned by the tile, the
    drill-down rows for that bucket sum to the exact same amount.

Uses ``_phase34_asyncio.batch_safe_run`` for Motor loop consistency,
matching the sibling P53 precedence test file.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._phase34_asyncio import batch_safe_run as _run


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "drilldown_stale_"


@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def scenario(dbc):
    ids = {
        "tenants": [], "items": [], "service_categories": [],
        "quotes": [],
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
        "name": f"drilldown stale-cat test {tid}",
        "created_at": _now(),
    })
    scenario["tenants"].append(tid)
    return {"id": tid, "name": f"drilldown stale-cat test {tid}"}


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
# Core drill-down · stale + null service_category_id → Uncategorized
# ═════════════════════════════════════════════════════════════════════
def test_drilldown_uncategorized_contains_stale_ref_line(dbc, scenario):
    """A line whose ``service_category_id`` points at an id that was
    hard-deleted from ``service_categories`` (or belongs to another
    tenant — same read effect) MUST appear in the drill-down's
    Uncategorized bucket.  The pre-fix drill-down skipped it."""
    tenant = _seed_tenant(dbc, scenario)
    pool = _seed_service_category(
        dbc, scenario, tenant_id=tenant["id"], name="Pool Service",
    )
    item_pool = _seed_pricebook_item(
        dbc, scenario, tenant_id=tenant["id"],
        name="Chlorine", service_category_id=pool,
    )
    # A line whose service_category_id points at a category that
    # doesn't exist in this tenant's service_categories collection.
    stale_svc_id = f"{TAG}deleted-svc-{uuid.uuid4().hex[:8]}"
    _seed_paid_invoice(dbc, scenario, tenant_id=tenant["id"], line_items=[
        {"item_id": item_pool, "service_category_id": stale_svc_id,
          "quantity": 1, "unit_price": 42.00,
          "description": "Points at deleted category"},
    ])

    rows_unc = _call_drilldown(tenant, service_category_id="Uncategorized")

    assert rows_unc["total"] == 1, (
        f"stale service_category_id line missing from Uncategorized "
        f"drill-down: {rows_unc}"
    )
    assert rows_unc["rows"][0]["extended"] == 42.00
    assert rows_unc["rows"][0]["service_category"] == "Uncategorized"


def test_drilldown_uncategorized_contains_null_svc_line(dbc, scenario):
    """A line with no ``service_category_id`` and a pricebook item
    that also has no ``service_category_id`` falls into
    Uncategorized (pre-fix path — still must work)."""
    tenant = _seed_tenant(dbc, scenario)
    item_bare = _seed_pricebook_item(
        dbc, scenario, tenant_id=tenant["id"],
        name="Bare", service_category_id=None,
    )
    _seed_paid_invoice(dbc, scenario, tenant_id=tenant["id"], line_items=[
        {"item_id": item_bare, "quantity": 3, "unit_price": 15.00,
          "description": "Truly bare — no svc anywhere"},
    ])

    rows_unc = _call_drilldown(tenant, service_category_id="Uncategorized")

    assert rows_unc["total"] == 1
    assert rows_unc["rows"][0]["extended"] == 45.00
    assert rows_unc["rows"][0]["service_category"] == "Uncategorized"


def test_drilldown_uncategorized_holds_both_stale_and_null_lines(
    dbc, scenario,
):
    """The core scope of the fix: an invoice with a live-category
    line, a stale-ref line, and a null-svc line puts BOTH the stale
    AND the null lines into the drill-down's Uncategorized bucket."""
    tenant = _seed_tenant(dbc, scenario)
    pool = _seed_service_category(
        dbc, scenario, tenant_id=tenant["id"], name="Pool Service",
    )
    item_pool = _seed_pricebook_item(
        dbc, scenario, tenant_id=tenant["id"],
        name="Chlorine", service_category_id=pool,
    )
    item_bare = _seed_pricebook_item(
        dbc, scenario, tenant_id=tenant["id"],
        name="Bare", service_category_id=None,
    )
    stale_svc_id = f"{TAG}deleted-svc-{uuid.uuid4().hex[:8]}"
    _seed_paid_invoice(dbc, scenario, tenant_id=tenant["id"], line_items=[
        # Live category — Pool Service bucket
        {"item_id": item_pool, "quantity": 1, "unit_price": 100.00},
        # Stale ref — expected Uncategorized
        {"item_id": item_pool, "service_category_id": stale_svc_id,
          "quantity": 1, "unit_price": 25.00,
          "description": "Stale — svc_id points at deleted cat"},
        # Null svc — expected Uncategorized
        {"item_id": item_bare, "quantity": 1, "unit_price": 10.00,
          "description": "Null svc"},
    ])

    rows_unc = _call_drilldown(tenant, service_category_id="Uncategorized")
    rows_pool = _call_drilldown(tenant, service_category_id=pool)

    unc_sum = round(sum(r["extended"] for r in rows_unc["rows"]), 2)
    pool_sum = round(sum(r["extended"] for r in rows_pool["rows"]), 2)

    assert rows_unc["total"] == 2, (
        f"Uncategorized bucket must contain BOTH stale + null "
        f"lines; got {rows_unc}"
    )
    assert unc_sum == 35.00, (
        f"Uncategorized sum should be 25 + 10 = 35; got {unc_sum}"
    )
    assert rows_pool["total"] == 1
    assert pool_sum == 100.00


# ═════════════════════════════════════════════════════════════════════
# Parity contract — chart tile ↔ drill-down bucket sums, cent-for-cent
# ═════════════════════════════════════════════════════════════════════
def test_tile_and_drilldown_lockstep_on_stale_refs(dbc, scenario):
    """The drill-down's Uncategorized sum MUST equal the tile's
    Uncategorized bucket amount for the same tenant + range.  This
    is the acceptance criterion cited in the task brief."""
    tenant = _seed_tenant(dbc, scenario)
    pool = _seed_service_category(
        dbc, scenario, tenant_id=tenant["id"], name="Pool Service",
    )
    landscape = _seed_service_category(
        dbc, scenario, tenant_id=tenant["id"], name="Landscaping",
    )
    item_pool = _seed_pricebook_item(
        dbc, scenario, tenant_id=tenant["id"],
        name="Chlorine", service_category_id=pool,
    )
    item_land = _seed_pricebook_item(
        dbc, scenario, tenant_id=tenant["id"],
        name="Bush Trim", service_category_id=landscape,
    )
    item_bare = _seed_pricebook_item(
        dbc, scenario, tenant_id=tenant["id"],
        name="Bare", service_category_id=None,
    )
    stale_a = f"{TAG}stale-a-{uuid.uuid4().hex[:8]}"
    stale_b = f"{TAG}stale-b-{uuid.uuid4().hex[:8]}"

    _seed_paid_invoice(dbc, scenario, tenant_id=tenant["id"], line_items=[
        # Pool bucket
        {"item_id": item_pool, "quantity": 1, "unit_price": 200.00},
        # Landscaping bucket
        {"item_id": item_land, "quantity": 1, "unit_price": 300.00},
        # Uncategorized · stale line-level svc
        {"item_id": item_pool, "service_category_id": stale_a,
          "quantity": 2, "unit_price": 50.00},   # 100
        # Uncategorized · another stale line-level svc
        {"item_id": item_land, "service_category_id": stale_b,
          "quantity": 1, "unit_price": 75.00},   # 75
        # Uncategorized · null svc
        {"item_id": item_bare, "quantity": 1, "unit_price": 20.00},
    ])

    tile = _call_tile(tenant)
    tile_pool = _amount(tile, "Pool Service")
    tile_land = _amount(tile, "Landscaping")
    tile_unc = _amount(tile, "Uncategorized")

    assert tile_pool == 200.00
    assert tile_land == 300.00
    assert tile_unc == 100.00 + 75.00 + 20.00  # 195.00

    rows_pool = _call_drilldown(tenant, service_category_id=pool)
    rows_land = _call_drilldown(tenant, service_category_id=landscape)
    rows_unc = _call_drilldown(tenant, service_category_id="Uncategorized")

    sum_pool = round(sum(r["extended"] for r in rows_pool["rows"]), 2)
    sum_land = round(sum(r["extended"] for r in rows_land["rows"]), 2)
    sum_unc = round(sum(r["extended"] for r in rows_unc["rows"]), 2)

    assert sum_pool == tile_pool, (
        f"tile/drilldown Pool parity broken: tile={tile_pool}, "
        f"drilldown_sum={sum_pool}"
    )
    assert sum_land == tile_land, (
        f"tile/drilldown Landscaping parity broken: tile={tile_land}, "
        f"drilldown_sum={sum_land}"
    )
    assert sum_unc == tile_unc, (
        f"tile/drilldown Uncategorized parity broken: tile={tile_unc}, "
        f"drilldown_sum={sum_unc} — the exact bug this ships fixes"
    )
    # Also assert the Uncategorized drilldown rowcount matches the
    # number of stale/null lines seeded (3).
    assert rows_unc["total"] == 3


# ═════════════════════════════════════════════════════════════════════
# Tenant isolation — a second tenant's stale-ref line MUST NOT leak
# ═════════════════════════════════════════════════════════════════════
def test_drilldown_stale_refs_respect_tenant_isolation(dbc, scenario):
    """Tenant A has one stale-svc line; tenant B's drill-down must
    return 0 rows for Uncategorized even though tenant B's
    ``svc_id_to_name`` is empty (which used to be the state that
    tempted the pre-fix drill-down to spill A's line into B)."""
    tenant_a = _seed_tenant(dbc, scenario)
    tenant_b = _seed_tenant(dbc, scenario)
    pool_a = _seed_service_category(
        dbc, scenario, tenant_id=tenant_a["id"], name="Pool Service",
    )
    item_a = _seed_pricebook_item(
        dbc, scenario, tenant_id=tenant_a["id"],
        name="A", service_category_id=pool_a,
    )
    stale_a = f"{TAG}stale-a-{uuid.uuid4().hex[:8]}"
    _seed_paid_invoice(dbc, scenario, tenant_id=tenant_a["id"], line_items=[
        {"item_id": item_a, "service_category_id": stale_a,
          "quantity": 1, "unit_price": 999.00,
          "description": "Tenant A stale line"},
    ])

    # Tenant B's Uncategorized drill-down MUST be empty.
    rows_b_unc = _call_drilldown(
        tenant_b, service_category_id="Uncategorized",
    )
    assert rows_b_unc["total"] == 0, (
        f"Tenant A's stale-svc line leaked into tenant B's drill-down: "
        f"{rows_b_unc}"
    )

    # And tenant A's Uncategorized drill-down DOES contain the line.
    rows_a_unc = _call_drilldown(
        tenant_a, service_category_id="Uncategorized",
    )
    assert rows_a_unc["total"] == 1
    assert rows_a_unc["rows"][0]["extended"] == 999.00
