"""PB1 · Feb-2026 — Profit report + CSV export.

Two admin-only endpoints:

  * ``GET /api/reports/profit`` — JSON summary + per-category
    breakdown of revenue, COGS, labor cost, gross profit, and margin
    for the requested date range.
  * ``GET /api/reports/profit.csv`` — CSV attachment with identical
    numbers.

Calculation
-----------
Rows summed = ``db.quotes`` documents where
``doc_type == "invoice"`` AND
``status in {"paid","partial","sent","overdue"}`` (drafts + cancelled
excluded) AND ``created_at`` inside the requested window.

For each ``line_item``:
  * ``revenue = quantity * (retail_price_snapshot OR unit_price)``
  * ``cogs = quantity * (wholesale_price_snapshot OR 0)``
  * ``labor = quantity * (labor_cost_snapshot OR 0)``
  * ``profit = revenue - cogs - labor``

Grouping
--------
* ``dimension=service_category`` — group by
  ``items[line.item_id].service_category_id`` → category name.
  Lines whose item is unknown or missing service_category → "Uncategorized".
* ``dimension=income_category`` — group by
  ``line.income_category_id`` → name.  Missing → "Uncategorized".

Breakdown array is capped at 500 entries — enforce so the response
never blows past our JSON size budget on very-long-tail categories.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from config import db
from utils import get_current_user

router = APIRouter()

_ELIGIBLE_STATUSES = {"paid", "partial", "sent", "overdue"}
_MAX_BREAKDOWN = 500
_MAX_CUSTOM_DAYS = 366

RANGE_LABELS = {
    "this_month": "This Month",
    "last_month": "Last Month",
    "qtd": "Quarter to Date",
    "ytd": "Year to Date",
    "custom": "Custom",
}


def _require_admin(user: dict) -> None:
    role = (user or {}).get("role") or ""
    if role not in ("admin", "super_admin", "manager"):
        raise HTTPException(403, {"error": "forbidden"})


def _resolve_range(
    range_key: str,
    from_: Optional[str],
    to: Optional[str],
) -> Dict[str, str]:
    today = datetime.now(timezone.utc).date()
    if range_key == "this_month":
        start = date(today.year, today.month, 1)
        end = today
    elif range_key == "last_month":
        first_of_this = date(today.year, today.month, 1)
        last_month_end = first_of_this - timedelta(days=1)
        start = date(last_month_end.year, last_month_end.month, 1)
        end = last_month_end
    elif range_key == "qtd":
        q_start_month = (((today.month - 1) // 3) * 3) + 1
        start = date(today.year, q_start_month, 1)
        end = today
    elif range_key == "ytd":
        start = date(today.year, 1, 1)
        end = today
    elif range_key == "custom":
        if not from_ or not to:
            raise HTTPException(
                422, {"error": "custom_requires_from_to"})
        try:
            start = date.fromisoformat(from_)
            end = date.fromisoformat(to)
        except ValueError as e:
            raise HTTPException(422, {"error": "invalid_date_format"}) from e
        if end < start:
            raise HTTPException(422, {"error": "to_before_from"})
        if (end - start).days > _MAX_CUSTOM_DAYS:
            raise HTTPException(
                422, {"error": "range_too_large",
                        "max_days": _MAX_CUSTOM_DAYS})
    else:
        raise HTTPException(
            422, {"error": "invalid_range",
                    "allowed": list(RANGE_LABELS.keys())})
    return {"from": start.isoformat(), "to": end.isoformat(),
            "label": RANGE_LABELS.get(range_key, range_key)}


def _line_value(li: Dict[str, Any]) -> tuple[float, float, float]:
    """Return (revenue, cogs, labor) contributions for a single line."""
    try:
        qty = float(li.get("quantity") or 0)
    except (TypeError, ValueError):
        qty = 0.0
    retail = li.get("retail_price_snapshot")
    if retail is None:
        retail = li.get("unit_price") or 0
    try:
        retail_f = float(retail)
    except (TypeError, ValueError):
        retail_f = 0.0
    try:
        wholesale = float(li.get("wholesale_price_snapshot") or 0)
    except (TypeError, ValueError):
        wholesale = 0.0
    try:
        labor = float(li.get("labor_cost_snapshot") or 0)
    except (TypeError, ValueError):
        labor = 0.0
    return qty * retail_f, qty * wholesale, qty * labor


async def _load_service_category_lookup(tenant_id: str) -> Dict[str, str]:
    rows = await db.service_categories.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1},
    ).to_list(1000)
    return {r["id"]: r.get("name") or r["id"] for r in rows}


async def _load_income_category_lookup(tenant_id: str) -> Dict[str, str]:
    rows = await db.income_categories.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1},
    ).to_list(1000)
    return {r["id"]: r.get("name") or r["id"] for r in rows}


async def _load_item_service_category_map(tenant_id: str) -> Dict[str, str]:
    """items.id → items.service_category_id"""
    rows = await db.items.find(
        {"$or": [{"tenant_id": tenant_id}, {"tenant_id": {"$exists": False}}]},
        {"_id": 0, "id": 1, "service_category_id": 1},
    ).to_list(5000)
    return {r["id"]: (r.get("service_category_id") or "")
             for r in rows if r.get("id")}


def _end_of_day(d: str) -> str:
    return f"{d}T23:59:59.999999+00:00"


async def _compute(
    tenant_id: str,
    range_bounds: Dict[str, str],
    dimension: str,
) -> Dict[str, Any]:
    query = {
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "status": {"$in": list(_ELIGIBLE_STATUSES)},
        "created_at": {
            "$gte": f"{range_bounds['from']}T00:00:00+00:00",
            "$lte": _end_of_day(range_bounds["to"]),
        },
    }
    invoices = await db.quotes.find(
        query,
        {"_id": 0, "id": 1, "line_items": 1, "created_at": 1},
    ).to_list(10000)

    if dimension == "service_category":
        item_to_svc = await _load_item_service_category_map(tenant_id)
        svc_lookup = await _load_service_category_lookup(tenant_id)
    elif dimension == "income_category":
        income_lookup = await _load_income_category_lookup(tenant_id)
        item_to_svc = {}
        svc_lookup = {}
    else:
        raise HTTPException(
            422, {"error": "invalid_dimension",
                    "allowed": ["service_category", "income_category"]})

    # {category_id: {"name": ..., "revenue": ..., "cogs": ..., "labor": ...,
    #                 "line_count": ...}}
    buckets: Dict[str, Dict[str, Any]] = {}
    # PB1-QoL · Feb-2026 — Uncategorized "Fix" deep-link.
    # Collect the distinct item ids that fed the Uncategorized bucket
    # so the frontend can render a per-item fix affordance. Capped at
    # 100 ids so the JSON payload stays bounded on very-long-tail
    # tenants with hundreds of pricebook rows missing a taxonomy.
    _UNCAT_CAP = 100
    uncat_item_ids: List[str] = []
    uncat_seen: set = set()

    def _bucket(cat_id: str, cat_name: str) -> Dict[str, Any]:
        b = buckets.get(cat_id)
        if b is None:
            b = {"category_id": cat_id, "category_name": cat_name,
                  "revenue": 0.0, "cogs": 0.0, "labor": 0.0,
                  "line_count": 0}
            buckets[cat_id] = b
        return b

    total_rev = total_cogs = total_labor = 0.0
    total_lines = 0

    for inv in invoices:
        for li in inv.get("line_items") or []:
            rev, cogs, labor = _line_value(li)
            total_rev += rev
            total_cogs += cogs
            total_labor += labor
            total_lines += 1
            if dimension == "service_category":
                cat_id = item_to_svc.get(li.get("item_id") or "", "") or ""
                cat_name = svc_lookup.get(cat_id) if cat_id else ""
                if not cat_name:
                    cat_id = "__uncategorized__"
                    cat_name = "Uncategorized"
            else:
                cat_id = li.get("income_category_id") or "__uncategorized__"
                cat_name = income_lookup.get(cat_id) if cat_id and cat_id != "__uncategorized__" else "Uncategorized"
                if not cat_name:
                    cat_name = "Uncategorized"
            # PB1-QoL · Track the item id feeding the Uncategorized bucket.
            if cat_id == "__uncategorized__":
                iid = li.get("item_id") or ""
                if iid and iid not in uncat_seen and len(uncat_item_ids) < _UNCAT_CAP:
                    uncat_seen.add(iid)
                    uncat_item_ids.append(iid)
            bucket = _bucket(cat_id, cat_name)
            bucket["revenue"] += rev
            bucket["cogs"] += cogs
            bucket["labor"] += labor
            bucket["line_count"] += 1

    def _pct(profit: float, rev: float) -> float:
        if rev <= 0:
            return 0.0
        return round(profit / rev * 100.0, 2)

    breakdown: List[Dict[str, Any]] = []
    for b in buckets.values():
        profit = b["revenue"] - b["cogs"] - b["labor"]
        row: Dict[str, Any] = {
            "category_id": b["category_id"],
            "category_name": b["category_name"],
            "revenue": round(b["revenue"], 2),
            "cogs": round(b["cogs"], 2),
            "labor": round(b["labor"], 2),
            "profit": round(profit, 2),
            "margin_pct": _pct(profit, b["revenue"]),
            "line_count": b["line_count"],
        }
        # PB1-QoL · Attach contributing item ids ONLY to the
        # Uncategorized row so the frontend can offer a "Fix" deep-link.
        if b["category_id"] == "__uncategorized__":
            row["uncategorized_item_ids"] = uncat_item_ids
        breakdown.append(row)
    breakdown.sort(key=lambda r: r["revenue"], reverse=True)
    breakdown = breakdown[:_MAX_BREAKDOWN]

    gross_profit = total_rev - total_cogs - total_labor
    return {
        "range": range_bounds,
        "dimension": dimension,
        "totals": {
            "revenue": round(total_rev, 2),
            "cogs": round(total_cogs, 2),
            "labor": round(total_labor, 2),
            "gross_profit": round(gross_profit, 2),
            "margin_pct": _pct(gross_profit, total_rev),
            "line_count": total_lines,
        },
        "breakdown": breakdown,
    }


@router.get("/reports/profit")
async def profit_report(
    dimension: str = Query(...,
                              description="service_category | income_category"),
    range: str = Query(...,
                          description="this_month|last_month|qtd|ytd|custom"),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_admin(user)
    tenant_id = (user or {}).get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(400, {"error": "missing_tenant"})
    range_bounds = _resolve_range(range, from_, to)
    return await _compute(tenant_id, range_bounds, dimension)


@router.get("/reports/profit.csv")
async def profit_report_csv(
    dimension: str = Query(...),
    range: str = Query(...),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
) -> Response:
    _require_admin(user)
    tenant_id = (user or {}).get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(400, {"error": "missing_tenant"})
    range_bounds = _resolve_range(range, from_, to)
    data = await _compute(tenant_id, range_bounds, dimension)

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "range_from", "range_to", "range_label",
        "dimension", "category_id", "category_name",
        "revenue", "cogs", "labor", "profit", "margin_pct", "line_count",
    ])
    # Totals row first for quick spreadsheet consumption.
    t = data["totals"]
    w.writerow([
        range_bounds["from"], range_bounds["to"], range_bounds["label"],
        dimension, "__totals__", "TOTALS",
        t["revenue"], t["cogs"], t["labor"], t["gross_profit"],
        t["margin_pct"], t["line_count"],
    ])
    for row in data["breakdown"]:
        w.writerow([
            range_bounds["from"], range_bounds["to"], range_bounds["label"],
            dimension, row["category_id"], row["category_name"],
            row["revenue"], row["cogs"], row["labor"],
            row["profit"], row["margin_pct"], row["line_count"],
        ])
    csv_bytes = buf.getvalue().encode("utf-8")
    filename = (
        f"profit-{dimension}-{range_bounds['from']}_to_"
        f"{range_bounds['to']}.csv"
    )
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
