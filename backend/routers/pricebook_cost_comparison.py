"""Phase 56-c · Aug-2026 — Pricebook Cost Comparison report.

Read-only reporting surface at ``GET /api/reports/pricebook-cost-comparison``.
Aggregates per-item supplier price spread so operators can spot items
where one supplier is significantly cheaper than another.

Uses a Mongo aggregation pipeline (``$match`` + ``$project``) to
narrow the item set on the server, then computes min/max/spread in
Python (still one linear pass — O(n·k) where n=items and k=avg
supplier prices per item, comfortable up to 10k items).

Query params:
  * ``income_category_id`` — optional filter (Pool / Landscaping / etc.).
  * ``min_spread_pct``     — optional threshold (0-1000). Items whose
                              spread% falls at or below this value are
                              excluded. Handy for "items I'm
                              overpaying on" views.
  * ``sort``               — ``spread_desc`` (default) / ``spread_asc``
                              / ``name``.
  * ``limit``              — default 100, capped at 500.

Role gate: ``require_admin`` (admin / super_admin / owner). Tenant-scoped.

Soft-deleted suppliers:
  * EXCLUDED from the min/max/spread computation (a deleted supplier
    shouldn't drive "cheapest supplier" recommendations).
  * PRESERVED in the raw ``supplier_prices`` sub-list on each row so
    the UI can render them muted if desired.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db, logger
from routers.tenants import get_current_tenant
from utils import require_admin


router = APIRouter()


_MAX_LIMIT = 500
_DEFAULT_LIMIT = 100
_SORTS = {"spread_desc", "spread_asc", "name"}


def _compute_report(
    items: list,
    active_supplier_lookup: dict,
    all_supplier_lookup: dict,
    income_cat_lookup: dict,
    min_spread_pct: float,
) -> list:
    """Pure-Python transform: item docs → report rows.

    Split out so pytest can exercise the compute logic directly with
    fixture dicts instead of monkeypatching ``db.items.aggregate``.

    Backlog #iii · Feb-2026 — prefers the rich ``suppliers[]`` shape
    (min/max/spread over ``unit_cost``); falls back to legacy
    ``supplier_prices[]`` compact rows for grandfathered items.
    """
    import re as _re

    def _slugify(s: str) -> str:
        s = str(s or "").strip().lower()
        s = _re.sub(r"[^a-z0-9]+", "-", s).strip("-")
        return s or ""

    rows: list = []
    for item in items:
        rich = item.get("suppliers") or []
        prices = item.get("supplier_prices") or []
        # Prefer rich shape; fall back to compact.
        use_rich = bool([r for r in rich if isinstance(r, dict)
                          and r.get("supplier_name")
                          and r.get("unit_cost") is not None])
        if not use_rich and not prices:
            continue

        enriched: list = []
        active_cents: list = []

        if use_rich:
            for r in rich:
                if not isinstance(r, dict):
                    continue
                name = str(r.get("supplier_name") or "").strip()
                if not name or r.get("unit_cost") is None:
                    continue
                try:
                    cents = int(round(float(r.get("unit_cost") or 0) * 100))
                except (TypeError, ValueError):
                    continue
                slug = _slugify(name)
                meta = all_supplier_lookup.get(slug) or {}
                is_deleted = bool(meta.get("deleted_at"))
                enriched.append({
                    "supplier_slug": slug,
                    "supplier_name": name,
                    "display_name": meta.get("display_name") or name,
                    "cost_cents": cents,
                    "unit_cost": round(cents / 100.0, 2),
                    "is_deleted": is_deleted,
                    "supplier_sku": r.get("supplier_sku") or "",
                    "unit_size": r.get("unit_size") or "",
                    "notes": r.get("notes") or "",
                })
                # Rich-shape rows are always "active" — soft-delete
                # concept lives on the pricebook_suppliers catalog,
                # not on per-item rows.
                if not is_deleted:
                    active_cents.append(cents)
        else:
            for p in prices:
                slug = p.get("supplier_slug")
                cents = int(p.get("cost_cents") or 0)
                meta = all_supplier_lookup.get(slug) or {}
                is_deleted = bool(meta.get("deleted_at"))
                enriched.append({
                    "supplier_slug": slug,
                    "display_name": meta.get("display_name") or slug,
                    "cost_cents": cents,
                    "is_deleted": is_deleted,
                })
                # Only ACTIVE suppliers contribute to min/max/spread.
                if slug in active_supplier_lookup and not is_deleted:
                    active_cents.append(cents)

        if not active_cents:
            # No live supplier drives min/max — skip this row (nothing
            # actionable to report on).
            continue

        min_c = min(active_cents)
        max_c = max(active_cents)
        spread_c = max_c - min_c
        # Spread % relative to the min supplier (canonical "overpaying
        # by X% vs cheapest" framing). Guard divide-by-zero.
        spread_pct = round((spread_c / min_c) * 100.0, 2) if min_c > 0 else 0.0

        if min_spread_pct and spread_pct <= min_spread_pct:
            continue

        cat = income_cat_lookup.get(item.get("income_category_id")) or {}
        rows.append({
            "item_id": item.get("id"),
            "item_name": item.get("name"),
            "income_category_id": item.get("income_category_id"),
            "income_category_name": cat.get("name") or "Uncategorized",
            "supplier_prices": enriched,
            "min_cost_cents": min_c,
            "max_cost_cents": max_c,
            "spread_cents": spread_c,
            "spread_pct": spread_pct,
            "supplier_count": len(active_cents),
        })
    return rows


@router.get("/reports/pricebook-cost-comparison")
async def pricebook_cost_comparison(
    income_category_id: Optional[str] = Query(None),
    min_spread_pct: float = Query(0, ge=0, le=1000),
    sort: str = Query("spread_desc"),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    if sort not in _SORTS:
        raise HTTPException(400, f"sort must be one of {sorted(_SORTS)}")

    # Aggregation pipeline — server-side narrow to items with any
    # supplier data. Backlog #iii · Feb-2026 — accept EITHER
    # ``suppliers[]`` (new rich shape) OR ``supplier_prices[]`` (legacy
    # compact shape) so grandfathered items still show up.
    match: dict = {
        "tenant_id": tenant["id"],
        "$expr": {"$or": [
            {"$gt": [{"$size": {"$ifNull": ["$suppliers", []]}}, 0]},
            {"$gt": [{"$size": {"$ifNull": ["$supplier_prices", []]}}, 0]},
        ]},
        # Exclude soft-deleted items — hidden from every other pricebook
        # surface, so hidden here too.
        "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}],
    }
    if income_category_id:
        match["income_category_id"] = income_category_id
    pipeline = [
        {"$match": match},
        {"$project": {"_id": 0, "id": 1, "name": 1,
                        "income_category_id": 1,
                        "suppliers": 1, "supplier_prices": 1}},
    ]
    try:
        cursor = db.items.aggregate(pipeline)
        items = [doc async for doc in cursor]
    except Exception as e:                                        # noqa: BLE001
        logger.warning(f"[pricebook_cost_comparison] aggregate failed: {e}")
        items = []

    # One-shot lookups (tenant-scoped).
    all_suppliers: dict = {}
    active_suppliers: dict = {}
    async for s in db.pricebook_suppliers.find(
        {"tenant_id": tenant["id"]},
        {"_id": 0, "slug": 1, "display_name": 1,
          "income_category_id": 1, "deleted_at": 1, "is_active": 1},
    ):
        slug = s["slug"]
        all_suppliers[slug] = s
        if not s.get("deleted_at") and s.get("is_active") is not False:
            active_suppliers[slug] = s

    income_cats: dict = {}
    async for c in db.income_categories.find(
        {"tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "name": 1},
    ):
        income_cats[c["id"]] = c

    rows = _compute_report(
        items, active_suppliers, all_suppliers, income_cats,
        float(min_spread_pct or 0),
    )

    if sort == "spread_desc":
        rows.sort(key=lambda r: r["spread_pct"], reverse=True)
    elif sort == "spread_asc":
        rows.sort(key=lambda r: r["spread_pct"])
    else:                                                          # name
        rows.sort(key=lambda r: (r["item_name"] or "").lower())

    return {"rows": rows[:limit], "total": len(rows)}
