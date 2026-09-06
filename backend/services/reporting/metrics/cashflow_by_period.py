"""Phase R1 · Feb-2026 — ``cashflow_by_period`` grouped metric.

Bucket-per-month view of Invoiced vs Collected + Running Balance.

Rows shape::

    [
        {bucket: "2026-01-01", invoiced: 12345.67, collected: 8000.00,
         net: 4345.67, running_balance: 4345.67},
        {bucket: "2026-02-01", invoiced: ...,     collected: ...,
         net: ...,     running_balance: ...},
        ...
    ]

Invoiced = ``$sum(total)`` on quotes with ``doc_type="invoice"``
whose ``created_at`` is in the bucket.
Collected = ``$sum(total)`` on the same doc set filtered further
by ``PAID_STATUS_FILTER`` and bucketed on the paid-window
(``paid_at → paid_date → created_at`` cascade).
Net = Invoiced − Collected (positive means outstanding grew).
Running balance rolls Net forward across buckets.
"""
from __future__ import annotations

from typing import Dict, List

from ..aggregation import AggregationEngine
from ..paid_date import PAID_STATUS_FILTER, build_paid_window_filter
from ..registry import Metric, register_metric


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
class CashflowByPeriod(Metric):
    key = "cashflow_by_period"
    label = "Cash Flow by Period"
    format = "currency"
    direction = "up_is_good"
    is_grouped = True
    description = ("Invoiced vs Collected by month with running "
                   "cash-balance carry-forward.")

    async def compute_grouped(self, engine: AggregationEngine, period,
                              filters: dict) -> dict:
        gran = _pick_granularity(period.start, period.end)

        # ── Invoiced buckets: created_at in window ────────────────
        invoiced_buckets = await engine.bucket_by_date(
            "quotes",
            {"doc_type": "invoice",
             "created_at": {"$gte": period.start, "$lt": period.end}},
            "created_at", granularity=gran, value_field="total",
        )
        invoiced_by_t: Dict[str, float] = {b.t: b.v for b in invoiced_buckets}

        # ── Collected buckets: PAID + paid-window ─────────────────
        collected_buckets = await engine.bucket_by_date(
            "quotes",
            {"$and": [
                {"doc_type": "invoice"},
                PAID_STATUS_FILTER,
                build_paid_window_filter(period.start, period.end),
            ]},
            "paid_at", granularity=gran, value_field="total",
        )
        collected_by_t: Dict[str, float] = {b.t: b.v for b in collected_buckets}

        all_ts = sorted(set(invoiced_by_t) | set(collected_by_t))
        rows: List[dict] = []
        running = 0.0
        total_invoiced = 0.0
        total_collected = 0.0
        for t in all_ts:
            inv = float(invoiced_by_t.get(t, 0.0))
            col = float(collected_by_t.get(t, 0.0))
            net = inv - col
            running += net
            total_invoiced += inv
            total_collected += col
            rows.append({
                "bucket": t,
                "invoiced": round(inv, 2),
                "collected": round(col, 2),
                "net": round(net, 2),
                "running_balance": round(running, 2),
            })

        return {
            "total": round(total_invoiced - total_collected, 2),
            "rows": rows,
            "row_count": len(rows),
            "granularity": gran,
            "summary": {
                "invoiced_total": round(total_invoiced, 2),
                "collected_total": round(total_collected, 2),
                "ending_balance": round(running, 2),
            },
        }
