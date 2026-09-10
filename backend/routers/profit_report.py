"""PB1 · Feb-2026 — Profit report + CSV export.
Feb-2026 · PB × Profit-Reporting Phase 3 extensions:

  * Effective-value math now honours the per-line overrides added in
    Phase 2 (``wholesale_cost_override``, ``labor_cost_override``,
    ``service_category_id_override``, ``income_category_id_override``)
    — overrides win over snapshots / line-level base fields.
  * Eligible invoices restricted to ``{"paid","partial"}``. Partial
    invoices prorate line-item REVENUE by ``amount_paid / total``.
    Costs are NOT prorated (cash-basis revenue recognition, snapshot
    costs = all-or-nothing at fulfilment).
  * New sibling endpoint ``GET /api/reports/pricebook-health`` surfaces
    snapshot coverage % across a trailing window so admins can see how
    much of their profit report is muddled by legacy Uncategorized
    lines.
  * Response envelope adds ``rows`` (canonical alias of ``breakdown``),
    ``currency``, and ``assumptions`` for downstream integrators.
    ``breakdown`` stays populated for PB1 back-compat.
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

_ELIGIBLE_STATUSES = {"paid", "partial"}
_MAX_BREAKDOWN = 500
_MAX_CUSTOM_DAYS = 366
_DEFAULT_CURRENCY = "USD"
_ASSUMPTIONS = {
    "partial_invoices": "prorated by amount_paid/total",
    "tax": "excluded (unit_price treated as pre-tax retail)",
    "null_snapshots": "bucketed as Uncategorized",
    "override_precedence": (
        "override > line-level > item-lookup for categories; "
        "override > snapshot for wholesale/labor"
    ),
}

RANGE_LABELS = {
    "this_month": "This Month",
    "last_month": "Last Month",
    "qtd": "Quarter to Date",
    "ytd": "Year to Date",
    "custom": "Custom",
}


def _require_admin(user: dict) -> None:
    # Feb-2026 · Phase 3 — spec is "admin-only, tenant-scoped".
    # Managers were previously allowed under PB1; tighten now so
    # the profit report + snapshot health tile stay in the admin
    # RBAC scope. Owner/super_admin retain access.
    role = (user or {}).get("role") or ""
    if role not in ("admin", "super_admin", "owner"):
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


def _line_value(
    li: Dict[str, Any], prorate: float = 1.0,
) -> tuple[float, float, float]:
    """Return (revenue, cogs, labor) contributions for a single line.

    Feb-2026 · Phase 3 — per-line admin overrides win over the
    snapshot values (``wholesale_cost_override ??
    wholesale_price_snapshot``; same for labor). Revenue is
    prorated by ``prorate`` (1.0 for fully-paid invoices; the
    ``amount_paid / total`` fraction for partials); costs are NOT
    prorated because the snapshot values represent the full
    cost-of-goods incurred at fulfilment (cash-basis revenue vs
    accrual-cost recognition).
    """
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
    # Override-first for wholesale + labor cost.
    _w_ov = li.get("wholesale_cost_override")
    wholesale_raw = _w_ov if _w_ov is not None else li.get("wholesale_price_snapshot") or 0
    _l_ov = li.get("labor_cost_override")
    labor_raw = _l_ov if _l_ov is not None else li.get("labor_cost_snapshot") or 0
    try:
        wholesale = float(wholesale_raw or 0)
    except (TypeError, ValueError):
        wholesale = 0.0
    try:
        labor = float(labor_raw or 0)
    except (TypeError, ValueError):
        labor = 0.0
    return qty * retail_f * prorate, qty * wholesale, qty * labor


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
        {"_id": 0, "id": 1, "line_items": 1, "created_at": 1,
         # Feb-2026 · Phase 3 — pull ``amount_paid`` + ``total`` so we
         # can prorate line-item revenue on ``partial`` invoices.
         "amount_paid": 1, "total": 1, "status": 1},
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
        # Feb-2026 · Phase 3 — partial-invoice proration on revenue.
        # ``prorate`` is capped at 1.0 to guard against amount_paid
        # exceeding total (data integrity edge case).
        prorate = 1.0
        _status = str(inv.get("status") or "").lower()
        if _status == "partial":
            try:
                _paid = float(inv.get("amount_paid") or 0)
                _total = float(inv.get("total") or 0)
                if _total > 0:
                    prorate = max(0.0, min(1.0, _paid / _total))
                else:
                    prorate = 0.0
            except (TypeError, ValueError):
                prorate = 0.0
        for li in inv.get("line_items") or []:
            rev, cogs, labor = _line_value(li, prorate=prorate)
            total_rev += rev
            total_cogs += cogs
            total_labor += labor
            total_lines += 1
            if dimension == "service_category":
                # Feb-2026 · Phase 3 — override > line-level >
                # item-lookup precedence for the service category.
                cat_id = (
                    li.get("service_category_id_override")
                    or li.get("service_category_id")
                    or item_to_svc.get(li.get("item_id") or "", "")
                    or ""
                )
                cat_name = svc_lookup.get(cat_id) if cat_id else ""
                if not cat_name:
                    cat_id = "__uncategorized__"
                    cat_name = "Uncategorized"
            else:
                # Feb-2026 · Phase 3 — override > line-level for the
                # income category (item master has no income binding).
                cat_id = (
                    li.get("income_category_id_override")
                    or li.get("income_category_id")
                    or "__uncategorized__"
                )
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
        # Feb-2026 · Phase 3 — canonical envelope keys expected by
        # spec ("from"/"to"/"group_by"/"rows"/"currency"/"assumptions").
        # Legacy PB1 keys ("range"/"dimension"/"breakdown") stay
        # populated for back-compat with the existing frontend.
        "from": range_bounds["from"],
        "to": range_bounds["to"],
        "group_by": dimension,
        "dimension": dimension,
        "currency": _DEFAULT_CURRENCY,
        "totals": {
            "revenue": round(total_rev, 2),
            "cogs": round(total_cogs, 2),
            "labor": round(total_labor, 2),
            "gross_profit": round(gross_profit, 2),
            "margin_pct": _pct(gross_profit, total_rev),
            "line_count": total_lines,
        },
        "breakdown": breakdown,
        "rows": breakdown,
        "assumptions": _ASSUMPTIONS,
    }


@router.get("/reports/profit")
async def profit_report(
    dimension: Optional[str] = Query(None,
                                      description="service_category | income_category"),
    group_by: Optional[str] = Query(None,
                                     description="Feb-2026 Phase 3 alias for ``dimension``"),
    range: Optional[str] = Query(None,
                                  description="this_month|last_month|qtd|ytd|custom"),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_admin(user)
    tenant_id = (user or {}).get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(400, {"error": "missing_tenant"})
    # Feb-2026 · Phase 3 — accept spec-shape query (``group_by`` +
    # explicit ``from`` / ``to``) alongside the legacy PB1 shape
    # (``dimension`` + preset ``range``).
    effective_dim = dimension or group_by
    if not effective_dim:
        raise HTTPException(422, {"error": "missing_dimension"})
    effective_range = range or ("custom" if (from_ and to) else None)
    if not effective_range:
        raise HTTPException(422, {"error": "missing_range"})
    range_bounds = _resolve_range(effective_range, from_, to)
    return await _compute(tenant_id, range_bounds, effective_dim)


@router.get("/reports/profit.csv")
async def profit_report_csv(
    dimension: Optional[str] = Query(None),
    group_by: Optional[str] = Query(None),
    range: Optional[str] = Query(None),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
) -> Response:
    _require_admin(user)
    tenant_id = (user or {}).get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(400, {"error": "missing_tenant"})
    effective_dim = dimension or group_by
    if not effective_dim:
        raise HTTPException(422, {"error": "missing_dimension"})
    effective_range = range or ("custom" if (from_ and to) else None)
    if not effective_range:
        raise HTTPException(422, {"error": "missing_range"})
    range_bounds = _resolve_range(effective_range, from_, to)
    data = await _compute(tenant_id, range_bounds, effective_dim)

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
        effective_dim, "__totals__", "TOTALS",
        t["revenue"], t["cogs"], t["labor"], t["gross_profit"],
        t["margin_pct"], t["line_count"],
    ])
    for row in data["breakdown"]:
        w.writerow([
            range_bounds["from"], range_bounds["to"], range_bounds["label"],
            effective_dim, row["category_id"], row["category_name"],
            row["revenue"], row["cogs"], row["labor"],
            row["profit"], row["margin_pct"], row["line_count"],
        ])
    csv_bytes = buf.getvalue().encode("utf-8")
    # Feb-2026 · Phase 3 spec — canonical filename shape
    # ``profit_report_{from}_{to}.csv``. Legacy PB1 shape stayed
    # dimension-prefixed; the spec asks for the from/to-only shape
    # so downstream automations don't have to guess the dimension.
    filename = (
        f"profit_report_{range_bounds['from']}_{range_bounds['to']}.csv"
    )
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── Feb-2026 · Phase 3 — Pricebook health tile ───────────────
# Simple snapshot-coverage aggregate over PAID/PARTIAL invoices in
# a trailing window (default 90 days). Answers the "how much of my
# profit report is muddled by legacy Uncategorized lines" question.
_HEALTH_CACHE: Dict[str, Any] = {}
_HEALTH_TTL_S = 60


@router.get("/reports/pricebook-health")
async def pricebook_health(
    window_days: int = Query(90, ge=1, le=365),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return snapshot-coverage stats for the trailing ``window_days``."""
    _require_admin(user)
    tenant_id = (user or {}).get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(400, {"error": "missing_tenant"})
    now = datetime.now(timezone.utc)
    cache_key = f"{tenant_id}:{window_days}"
    cached = _HEALTH_CACHE.get(cache_key)
    if cached and (now - cached["_at"]).total_seconds() < _HEALTH_TTL_S:
        return cached["value"]
    start = (now - timedelta(days=window_days)).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    query = {
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "status": {"$in": list(_ELIGIBLE_STATUSES)},
        "created_at": {"$gte": start.isoformat()},
    }
    invoices = await db.quotes.find(
        query, {"_id": 0, "line_items": 1},
    ).to_list(10000)
    lines_total = 0
    with_wholesale = 0
    with_labor = 0
    with_any = 0
    for inv in invoices:
        for li in inv.get("line_items") or []:
            lines_total += 1
            has_w = li.get("wholesale_price_snapshot") not in (None, 0, 0.0)
            has_l = li.get("labor_cost_snapshot") not in (None, 0, 0.0)
            if has_w:
                with_wholesale += 1
            if has_l:
                with_labor += 1
            if has_w or has_l:
                with_any += 1

    def _pct(num: int, denom: int) -> float:
        return round((num / denom * 100.0), 2) if denom else 0.0

    value = {
        "window_days": window_days,
        "as_of": now.isoformat(),
        "lines_total": lines_total,
        "lines_with_wholesale_snapshot": with_wholesale,
        "lines_with_labor_snapshot": with_labor,
        "lines_with_any_snapshot": with_any,
        "coverage_pct": {
            "wholesale": _pct(with_wholesale, lines_total),
            "labor": _pct(with_labor, lines_total),
            "any": _pct(with_any, lines_total),
        },
    }
    _HEALTH_CACHE[cache_key] = {"_at": now, "value": value}
    return value
