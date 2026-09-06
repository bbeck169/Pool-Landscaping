"""Phase R1 · Feb-2026 — ``pnl_line_items`` grouped metric.

Drill-down for the P&L KPI. Returns one row per accounting line:

    [
        {label: "Revenue",       value: 12345.67, prior_value: ..., delta_pct: ...},
        {label: "COGS",          value:  4500.00, prior_value: ..., delta_pct: ...},
        {label: "Labor",         value:  1200.00, ...},
        {label: "OpEx",          value:  2800.00, ...},
        {label: "Depreciation",  value:   180.00, ...},
        {label: "Net Profit",    value:  3665.67, ...},
        {label: "Gross Margin %",value:     47.6, ...},
    ]

``total`` is the Net Profit for the period so the KPI tile can
mirror ``pnl_by_period`` when both are on-screen.
"""
from __future__ import annotations

from ..aggregation import AggregationEngine
from ..registry import Metric, register_metric
from .pnl_by_period import (
    _sum_revenue,
    _sum_line_snapshot,
    _sum_checks,
)


def _pct_delta(cur: float, prior: float):
    if prior:
        return round(((cur - prior) / prior) * 100.0, 2)
    return None


def _row(label: str, cur: float, prior: float, fmt: str = "currency") -> dict:
    return {
        "label": label,
        "value": round(cur, 2),
        "prior_value": round(prior, 2),
        "delta_abs": round(cur - prior, 2),
        "delta_pct": _pct_delta(cur, prior),
        "format": fmt,
    }


async def _compute_slice(engine: AggregationEngine, start: str, end: str):
    revenue = await _sum_revenue(engine, start, end)
    cogs = await _sum_line_snapshot(engine, start, end,
                                     "wholesale_price_snapshot")
    labor = await _sum_line_snapshot(engine, start, end,
                                      "labor_cost_snapshot")
    opex = await _sum_checks(engine, start, end, depreciation=False)
    deprec = await _sum_checks(engine, start, end, depreciation=True)
    net_profit = revenue - cogs - labor - opex - deprec
    gross_margin_pct = 0.0
    if revenue:
        gross_margin_pct = round(((revenue - cogs - labor) / revenue) * 100.0,
                                  2)
    return {
        "revenue": revenue,
        "cogs": cogs,
        "labor": labor,
        "opex": opex,
        "depreciation": deprec,
        "net_profit": net_profit,
        "gross_margin_pct": gross_margin_pct,
    }


@register_metric
class PnlLineItems(Metric):
    key = "pnl_line_items"
    label = "P&L Line Items"
    format = "currency"
    direction = "up_is_good"
    is_grouped = True
    description = ("Per-line breakdown of Revenue / COGS / Labor / "
                   "OpEx / Depreciation / Net Profit / Gross Margin.")

    async def compute_grouped(self, engine: AggregationEngine, period,
                              filters: dict) -> dict:
        cur = await _compute_slice(engine, period.start, period.end)
        prior = await _compute_slice(engine, period.prior_start,
                                      period.prior_end)

        rows = [
            _row("Revenue",       cur["revenue"],       prior["revenue"]),
            _row("COGS",          cur["cogs"],          prior["cogs"]),
            _row("Labor",         cur["labor"],         prior["labor"]),
            _row("OpEx",          cur["opex"],          prior["opex"]),
            _row("Depreciation",  cur["depreciation"],  prior["depreciation"]),
            _row("Net Profit",    cur["net_profit"],    prior["net_profit"]),
            _row("Gross Margin %", cur["gross_margin_pct"],
                 prior["gross_margin_pct"], fmt="percent"),
        ]

        # Empty-tenant hint — surfaced by the FE as an info banner
        # when true (no ``checks`` rows AND no COGS/labor rows).
        no_costs = (cur["cogs"] == 0 and cur["labor"] == 0
                     and cur["opex"] == 0 and cur["depreciation"] == 0)

        return {
            "total": round(cur["net_profit"], 2),
            "rows": rows,
            "row_count": len(rows),
            "no_costs_recorded": no_costs,
        }
