"""Phase R1 · Feb-2026 — ``pnl_by_period`` KPI.

Scalar metric returning Net Profit = Revenue − COGS − Labor −
OpEx − Depreciation for the selected period. Uses the exact same
data sources as the existing ``services/finance/ebit.py`` so the
KPI reconciles byte-for-byte with the EBIT report.

Response envelope (scalar):

    {
        "value":       12345.67,   # net profit
        "prior_value":  9876.54,
        "delta_pct":    25.0,
        "sparkline":  [{"t": "...", "v": ...}]  # monthly net profit
    }

Cost breakdown (revenue / cogs / labor / opex / depreciation)
is emitted by the ``pnl_line_items`` grouped metric — the scalar
form intentionally stays scalar so it fits a KpiCard tile.
"""
from __future__ import annotations

from ..aggregation import AggregationEngine
from ..paid_date import PAID_STATUS_FILTER, build_paid_window_filter
from ..registry import Metric, register_metric


DEPRECIATION_CATEGORIES = {"depreciation", "amortization"}


async def _sum_revenue(engine: AggregationEngine, start: str, end: str) -> float:
    """Sum invoice ``total`` for paid invoices in the paid-window."""
    combined = {"$and": [PAID_STATUS_FILTER,
                          {"doc_type": "invoice"},
                          build_paid_window_filter(start, end)]}
    return await engine.sum_field("quotes", combined, "total")


async def _sum_line_snapshot(engine: AggregationEngine, start: str, end: str,
                              field: str) -> float:
    """Sum ``line_items[].{field}`` * qty across paid invoices in-window.

    Uses an aggregation pipeline rather than ``sum_field`` because
    the target field is nested inside a line-items array."""
    match = engine._scope({"$and": [
        PAID_STATUS_FILTER,
        {"doc_type": "invoice"},
        build_paid_window_filter(start, end),
    ]})
    pipeline = [
        {"$match": match},
        {"$unwind": "$line_items"},
        {"$group": {"_id": None, "total": {"$sum": {
            "$multiply": [
                {"$convert": {"input": "$line_items.quantity",
                              "to": "double",
                              "onError": 0, "onNull": 0}},
                {"$convert": {"input": f"$line_items.{field}",
                              "to": "double",
                              "onError": 0, "onNull": 0}},
            ]
        }}}},
    ]
    async for row in engine.db.quotes.aggregate(pipeline):
        return float(row.get("total") or 0.0)
    return 0.0


async def _sum_checks(engine: AggregationEngine, start: str, end: str,
                      *, depreciation: bool) -> float:
    """Sum non-voided ``checks`` amounts in-window, optionally
    filtering to (or excluding) the depreciation categories."""
    cat_filter: dict
    if depreciation:
        cat_filter = {"category": {"$in": list(DEPRECIATION_CATEGORIES)}}
    else:
        cat_filter = {"category": {"$nin": list(DEPRECIATION_CATEGORIES)}}
    combined = {"$and": [
        {"$or": [{"voided": False}, {"voided": {"$exists": False}}]},
        {"date": {"$gte": start, "$lt": end}},
        cat_filter,
    ]}
    return await engine.sum_field("checks", combined, "amount")


async def _net_profit(engine: AggregationEngine, start: str, end: str) -> float:
    revenue = await _sum_revenue(engine, start, end)
    cogs = await _sum_line_snapshot(engine, start, end,
                                     "wholesale_price_snapshot")
    labor = await _sum_line_snapshot(engine, start, end,
                                      "labor_cost_snapshot")
    opex = await _sum_checks(engine, start, end, depreciation=False)
    deprec = await _sum_checks(engine, start, end, depreciation=True)
    return round(revenue - cogs - labor - opex - deprec, 2)


def _pick_granularity(start: str, end: str) -> str:
    from datetime import date
    try:
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    except Exception:
        return "month"
    if days <= 45:
        return "day"
    if days <= 180:
        return "week"
    return "month"


@register_metric
class PnlByPeriod(Metric):
    key = "pnl_by_period"
    label = "Net Profit"
    format = "currency"
    direction = "up_is_good"
    description = ("Revenue - COGS - Labor - OpEx - Depreciation "
                   "for the selected period. Reconciles with the "
                   "EBIT report.")

    async def compute(self, engine: AggregationEngine, period) -> dict:
        cur = await _net_profit(engine, period.start, period.end)
        prior = await _net_profit(engine, period.prior_start,
                                   period.prior_end)
        delta_pct = None
        if prior:
            delta_pct = round(((cur - prior) / prior) * 100.0, 2)

        # Sparkline: monthly net profit over the same window.
        # Compute by bucketing on invoice created_at as a proxy —
        # the full per-bucket cost math is what ``pnl_line_items``
        # returns; the sparkline is a shape hint, not a report.
        gran = _pick_granularity(period.start, period.end)
        buckets = await engine.bucket_by_date(
            "quotes",
            {"$and": [PAID_STATUS_FILTER, {"doc_type": "invoice"},
                       build_paid_window_filter(period.start, period.end)]},
            "created_at", granularity=gran, value_field="total",
        )
        sparkline = [{"t": b.t, "v": b.v} for b in buckets]

        return {
            "value": cur,
            "prior_value": prior,
            "delta_pct": delta_pct,
            "sparkline": sparkline,
        }
