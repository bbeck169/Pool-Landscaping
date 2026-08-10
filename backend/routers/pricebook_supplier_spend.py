"""Phase 56-d · Aug-2026 — Supplier Spend / Margin report.

``GET /api/reports/supplier-spend?date_from=&date_to=[&...]``

Aggregates spend + margin by resolved supplier over a date range.

Resolution rules (locked in scope §3):
  * Line item's ``pricebook_item_id`` → look up the pricebook item →
    look at ``supplier_prices`` → pick the LOWEST-COST supplier as
    the "primary". Ties broken alphabetically by ``supplier_slug``.
  * No FK, or pricebook item has no ``supplier_prices`` → the line
    item lands in an "Uncategorized" bucket (excluded when
    ``include_uncategorized=false``).
  * Soft-deleted suppliers ARE included in the report — historical
    spend is real even if the vendor relationship has since ended.

Role gate: ``require_admin`` (admin / super_admin / owner) — tighter
than 56-c because cost basis is sensitive. Tenant-scoped.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db, logger
from routers.tenants import get_current_tenant
from utils import require_admin


router = APIRouter()


_SORTS = {"spend_desc", "margin_desc", "name"}
UNCATEGORIZED_KEY = "__uncategorized__"


def _primary_supplier_slug(pricebook_item: dict) -> Optional[str]:
    """Pick the lowest-cost supplier as the item's primary. Ties
    broken alphabetically. Returns None if the item has no
    supplier_prices at all."""
    prices = (pricebook_item or {}).get("supplier_prices") or []
    if not prices:
        return None
    # Sort by (cost_cents, slug) so ties collapse deterministically.
    best = min(prices, key=lambda p: (int(p.get("cost_cents") or 0),
                                        p.get("supplier_slug") or ""))
    return best.get("supplier_slug")


def _compute_spend_report(
    line_items: list,
    pricebook_items_by_id: dict,
    suppliers_by_slug: dict,
    income_cats_by_id: dict,
    include_uncategorized: bool = True,
) -> list:
    """Pure-Python compute — takes flattened line-item docs (each with
    ``quantity``, ``unit_price``, ``wholesale_price_snapshot``,
    ``pricebook_item_id``) and returns bucketed rows.

    Split out so pytest exercises the aggregation logic directly
    without hitting Mongo.
    """
    buckets: dict = {}  # slug (or UNCATEGORIZED_KEY) → agg dict
    for li in line_items:
        qty = float(li.get("quantity") or 0)
        unit_price = float(li.get("unit_price") or 0)
        # Snapshot fields are immutable per project rules — only
        # READ them here, never write. Fall back to 0 when missing.
        wp_snap = float(li.get("wholesale_price_snapshot") or 0)
        revenue_cents = int(round(qty * unit_price * 100))
        spend_cents = int(round(qty * wp_snap * 100))

        pid = li.get("pricebook_item_id")
        item = pricebook_items_by_id.get(pid) if pid else None
        slug = _primary_supplier_slug(item) if item else None
        if not slug:
            if not include_uncategorized:
                continue
            key = UNCATEGORIZED_KEY
            display_name = "Uncategorized"
            category_name = "—"
        else:
            key = slug
            sup = suppliers_by_slug.get(slug) or {}
            display_name = sup.get("display_name") or slug
            cat = income_cats_by_id.get(sup.get("income_category_id")) or {}
            category_name = cat.get("name") or "Uncategorized"

        b = buckets.setdefault(key, {
            "supplier_slug": None if key == UNCATEGORIZED_KEY else slug,
            "display_name": display_name,
            "income_category_name": category_name,
            "line_item_count": 0,
            "quantity_sum": 0.0,
            "spend_cents": 0,
            "revenue_cents": 0,
        })
        b["line_item_count"] += 1
        b["quantity_sum"] += qty
        b["spend_cents"] += spend_cents
        b["revenue_cents"] += revenue_cents

    rows: list = []
    for b in buckets.values():
        margin_cents = b["revenue_cents"] - b["spend_cents"]
        margin_pct = (round((margin_cents / b["revenue_cents"]) * 100.0, 2)
                       if b["revenue_cents"] > 0 else 0.0)
        rows.append({**b, "margin_cents": margin_cents,
                       "margin_pct": margin_pct})
    return rows


@router.get("/reports/supplier-spend")
async def supplier_spend_report(
    date_from: str = Query(...),
    date_to: str = Query(...),
    income_category_id: Optional[str] = Query(None),
    include_uncategorized: bool = Query(True),
    sort: str = Query("spend_desc"),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    if sort not in _SORTS:
        raise HTTPException(400, f"sort must be one of {sorted(_SORTS)}")
    if not date_from or not date_to:
        raise HTTPException(400, "date_from and date_to are required")

    # Fetch quotes + invoices within the range (line items live as
    # subdocs). Bound by tenant + non-deleted.
    match: dict = {
        "tenant_id": tenant["id"],
        "created_at": {"$gte": date_from, "$lte": date_to + "T23:59:59"},
        "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}],
    }

    line_items: list = []
    for coll_name in ("quotes", "invoices"):
        try:
            async for doc in db[coll_name].find(
                match,
                {"_id": 0, "line_items": 1, "created_at": 1},
            ):
                for li in (doc.get("line_items") or []):
                    line_items.append(li)
        except Exception as e:                                    # noqa: BLE001
            logger.warning(f"[supplier-spend] {coll_name} fetch failed: {e}")

    # Bulk-load pricebook items referenced by the line items.
    pids = list({li.get("pricebook_item_id") for li in line_items
                  if li.get("pricebook_item_id")})
    pricebook_items: dict = {}
    if pids:
        async for it in db.items.find(
            {"tenant_id": tenant["id"], "id": {"$in": pids}},
            {"_id": 0, "id": 1, "income_category_id": 1, "supplier_prices": 1},
        ):
            pricebook_items[it["id"]] = it

    suppliers: dict = {}
    async for s in db.pricebook_suppliers.find(
        {"tenant_id": tenant["id"]},
        {"_id": 0, "slug": 1, "display_name": 1,
          "income_category_id": 1, "deleted_at": 1},
    ):
        suppliers[s["slug"]] = s

    income_cats: dict = {}
    async for c in db.income_categories.find(
        {"tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "name": 1},
    ):
        income_cats[c["id"]] = c

    rows = _compute_spend_report(
        line_items, pricebook_items, suppliers, income_cats,
        include_uncategorized=include_uncategorized,
    )

    if income_category_id:
        # Filter by category name resolved via the target category id.
        target = (income_cats.get(income_category_id) or {}).get("name")
        if target:
            rows = [r for r in rows if r["income_category_name"] == target
                     or r["display_name"] == "Uncategorized"
                        and include_uncategorized is False]
            # Second clause is a defensive keep-out for Uncategorized
            # when the user filters by a specific category; drop it
            # regardless.
            rows = [r for r in rows if r["display_name"] != "Uncategorized"]

    if sort == "spend_desc":
        rows.sort(key=lambda r: r["spend_cents"], reverse=True)
    elif sort == "margin_desc":
        rows.sort(key=lambda r: r["margin_pct"], reverse=True)
    else:
        rows.sort(key=lambda r: (r["display_name"] or "").lower())

    totals = {
        "line_item_count": sum(r["line_item_count"] for r in rows),
        "quantity_sum": sum(r["quantity_sum"] for r in rows),
        "spend_cents": sum(r["spend_cents"] for r in rows),
        "revenue_cents": sum(r["revenue_cents"] for r in rows),
    }
    totals["margin_cents"] = totals["revenue_cents"] - totals["spend_cents"]
    totals["margin_pct"] = (round(
        (totals["margin_cents"] / totals["revenue_cents"]) * 100.0, 2,
    ) if totals["revenue_cents"] > 0 else 0.0)

    return {"rows": rows, "totals": totals,
              "date_from": date_from, "date_to": date_to}
