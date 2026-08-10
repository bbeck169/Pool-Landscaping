"""Phase 56-d · Aug-2026 — Supplier Spend / Margin report contract.

Exercises the ``_compute_spend_report`` helper directly + the
LineItem persistence contract (``pricebook_item_id`` round-trip).

Locks:
  * LineItem model accepts + serializes ``pricebook_item_id``.
  * Report aggregates spend by resolved primary supplier
    (lowest-cost active supplier on the linked pricebook item).
  * Line items without a FK bucket into "Uncategorized".
  * Date filter honoured (out-of-range docs excluded upstream).
  * Soft-deleted supplier still appears in the report (historical
    spend is real).
"""
from __future__ import annotations

import pytest

from routers.pricebook_supplier_spend import (
    _compute_spend_report, _primary_supplier_slug, UNCATEGORIZED_KEY,
)


POOL_ID = "cat-pool"
LAND_ID = "cat-land"
CATS = {POOL_ID: {"id": POOL_ID, "name": "Pool"},
        LAND_ID: {"id": LAND_ID, "name": "Landscaping"}}


def _pb_item(iid, category, prices):
    return {"id": iid, "income_category_id": category,
            "supplier_prices": prices}


def _line(pbi_id, qty, unit_price, wp_snap):
    return {"pricebook_item_id": pbi_id, "quantity": qty,
            "unit_price": unit_price,
            "wholesale_price_snapshot": wp_snap}


# ─── LineItem model persistence ─────────────────────────────────────────
def test_line_item_model_persists_and_reads_pricebook_item_id():
    """Aug-2026 · Phase 56-d — LineItem accepts and round-trips the
    new ``pricebook_item_id`` field alongside the legacy ``item_id``."""
    from models import LineItem
    li = LineItem(description="Chlorine tabs (case)",
                   quantity=2, unit_price=25.0,
                   pricebook_item_id="pb-1",
                   wholesale_price_snapshot=18.13)
    d = li.model_dump()
    assert d["pricebook_item_id"] == "pb-1"
    assert d["wholesale_price_snapshot"] == 18.13
    # Legacy item_id defaults to None (not overridden).
    assert d["item_id"] is None
    # Round-trip through Pydantic.
    li2 = LineItem(**d)
    assert li2.pricebook_item_id == "pb-1"


# ─── _primary_supplier_slug ─────────────────────────────────────────────
def test_primary_supplier_is_lowest_cost_ties_broken_alphabetically():
    item = _pb_item("i1", POOL_ID, [
        {"supplier_slug": "scp", "cost_cents": 2000},
        {"supplier_slug": "epool", "cost_cents": 1800},
        {"supplier_slug": "heritage", "cost_cents": 1800},
    ])
    # epool + heritage tied at 1800; alphabetical → epool wins.
    assert _primary_supplier_slug(item) == "epool"


# ─── Report shape ───────────────────────────────────────────────────────
def test_report_aggregates_spend_by_primary_supplier():
    pbi = {
        "pb-1": _pb_item("pb-1", POOL_ID, [
            {"supplier_slug": "scp", "cost_cents": 1800},
            {"supplier_slug": "epool", "cost_cents": 1900},
        ]),
        "pb-2": _pb_item("pb-2", LAND_ID, [
            {"supplier_slug": "home_depot", "cost_cents": 500},
        ]),
    }
    suppliers = {
        "scp":        {"slug": "scp",        "display_name": "SCP",
                        "income_category_id": POOL_ID, "deleted_at": None},
        "epool":      {"slug": "epool",      "display_name": "ePool",
                        "income_category_id": POOL_ID, "deleted_at": None},
        "home_depot": {"slug": "home_depot", "display_name": "Home Depot",
                        "income_category_id": LAND_ID, "deleted_at": None},
    }
    # Two chlorine sales (linked to pb-1 → scp primary), one landscape
    # bag (linked to pb-2 → home_depot). Snapshot wholesales set.
    lines = [
        _line("pb-1", qty=2, unit_price=25.00, wp_snap=18.00),
        _line("pb-1", qty=3, unit_price=25.00, wp_snap=18.00),
        _line("pb-2", qty=10, unit_price=8.00, wp_snap=5.00),
    ]
    rows = _compute_spend_report(lines, pbi, suppliers, CATS)
    by_slug = {r["supplier_slug"]: r for r in rows}
    assert set(by_slug.keys()) == {"scp", "home_depot"}
    # SCP: 5 units × $25 = $125 revenue · 5 × $18 = $90 spend · $35 margin (28%)
    scp = by_slug["scp"]
    assert scp["line_item_count"] == 2
    assert scp["quantity_sum"] == 5
    assert scp["revenue_cents"] == 12500
    assert scp["spend_cents"] == 9000
    assert scp["margin_cents"] == 3500
    assert scp["margin_pct"] == 28.0
    assert scp["income_category_name"] == "Pool"
    # Home Depot: 10 × $8 = $80 revenue · 10 × $5 = $50 spend · $30 margin (37.5%)
    hd = by_slug["home_depot"]
    assert hd["revenue_cents"] == 8000
    assert hd["spend_cents"] == 5000
    assert hd["margin_pct"] == 37.5


# ─── Uncategorized bucket ───────────────────────────────────────────────
def test_line_items_without_pricebook_fk_bucket_into_uncategorized():
    lines = [
        _line(None, qty=1, unit_price=100, wp_snap=60),
        _line("does_not_exist", qty=1, unit_price=50, wp_snap=30),
    ]
    rows = _compute_spend_report(lines, {}, {}, CATS,
                                    include_uncategorized=True)
    assert len(rows) == 1
    assert rows[0]["display_name"] == "Uncategorized"
    assert rows[0]["supplier_slug"] is None
    assert rows[0]["line_item_count"] == 2
    assert rows[0]["revenue_cents"] == 15000  # 100 + 50 dollars → cents
    assert rows[0]["spend_cents"] == 9000    # 60 + 30 dollars → cents

    # include_uncategorized=False drops the bucket entirely.
    rows2 = _compute_spend_report(lines, {}, {}, CATS,
                                    include_uncategorized=False)
    assert rows2 == []


# ─── Deleted-supplier semantics ─────────────────────────────────────────
def test_soft_deleted_supplier_still_appears_in_report():
    """Historical spend is real — a deleted supplier row must still
    surface in the spend report so operators can trace where the
    money went in prior periods."""
    pbi = {"pb-1": _pb_item("pb-1", POOL_ID, [
        {"supplier_slug": "old_vendor", "cost_cents": 1500},
    ])}
    suppliers = {"old_vendor": {
        "slug": "old_vendor", "display_name": "Old Vendor",
        "income_category_id": POOL_ID,
        "deleted_at": "2026-08-01T00:00:00",
    }}
    lines = [_line("pb-1", qty=4, unit_price=20, wp_snap=15)]
    rows = _compute_spend_report(lines, pbi, suppliers, CATS)
    assert len(rows) == 1
    assert rows[0]["supplier_slug"] == "old_vendor"
    assert rows[0]["display_name"] == "Old Vendor"
    assert rows[0]["revenue_cents"] == 8000
    assert rows[0]["spend_cents"] == 6000


# ─── Empty ──────────────────────────────────────────────────────────────
def test_empty_line_items_returns_empty():
    assert _compute_spend_report([], {}, {}, CATS) == []
