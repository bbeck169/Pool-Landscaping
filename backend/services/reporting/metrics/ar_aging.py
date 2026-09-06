"""Phase R1 · Feb-2026 — ``ar_aging`` grouped metric.

Bucket outstanding invoices into standard AR age brackets:
``0-30``, ``31-60``, ``61-90``, ``90+``. "Age" is measured from
the effective due date to the report ``end`` boundary (typically
"today" via MTD/YTD periods).

Effective due date resolution (see ``paid_date.py``):

  * ``due_date`` when present + non-empty
  * else ``created_at + net_terms_days`` (tenant default = 30)

Response shape::

    {
        "total":       12345.67,   # sum outstanding balance
        "rows": [
            {"bucket": "0-30",  "amount": 5000, "invoice_count": 8},
            {"bucket": "31-60", "amount": 3200, "invoice_count": 4},
            {"bucket": "61-90", "amount": 2100, "invoice_count": 2},
            {"bucket": "90+",   "amount": 2045.67, "invoice_count": 3},
        ],
        "row_count": 4,
        "net_terms_days": 30,
        "as_of": "2026-02-15"
    }

Balance calculation: ``max(total - amount_paid, 0)`` per invoice
so partial payments correctly reduce the outstanding amount but
never go negative (over-payments handled elsewhere).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from ..aggregation import AggregationEngine
from ..paid_date import (
    OUTSTANDING_STATUS_FILTER,
    build_effective_due_date_expr,
)
from ..registry import Metric, register_metric


AGE_BUCKETS = [
    ("0-30", 0, 30),
    ("31-60", 31, 60),
    ("61-90", 61, 90),
    ("90+", 91, 10_000),  # arbitrarily large upper bound
]


async def _resolve_net_terms(engine: AggregationEngine) -> int:
    """Read ``tenant.net_terms_days`` — default 30 when unset."""
    t = await engine.db.tenants.find_one(
        {"id": engine.tenant_id},
        {"_id": 0, "net_terms_days": 1},
    )
    if not t:
        return 30
    try:
        v = int(t.get("net_terms_days") or 30)
    except Exception:
        return 30
    return max(0, min(v, 365))


@register_metric
class ArAging(Metric):
    key = "ar_aging"
    label = "AR Aging"
    format = "currency"
    direction = "down_is_good"
    is_grouped = True
    description = ("Outstanding invoice balances bucketed by age: "
                   "0-30 / 31-60 / 61-90 / 90+ days past due.")

    async def compute_grouped(self, engine: AggregationEngine, period,
                              filters: dict) -> dict:
        net_terms = await _resolve_net_terms(engine)
        as_of = period.end  # aging measured against the period boundary

        # Pipeline: outstanding invoices → compute effective due
        # date → compute days_overdue vs as_of → bucket → sum.
        as_of_dt = {"$dateFromString": {
            "dateString": as_of, "onError": None, "onNull": None,
        }}
        pipeline = [
            {"$match": engine._scope(OUTSTANDING_STATUS_FILTER)},
            {"$addFields": {
                "_eff_due": build_effective_due_date_expr(net_terms),
                "_asof": as_of_dt,
                "_outstanding": {"$max": [
                    0,
                    {"$subtract": [
                        {"$convert": {"input": "$total", "to": "double",
                                       "onError": 0, "onNull": 0}},
                        {"$convert": {"input": "$amount_paid",
                                       "to": "double",
                                       "onError": 0, "onNull": 0}},
                    ]},
                ]},
            }},
            {"$addFields": {
                "_days_overdue": {"$cond": [
                    {"$or": [{"$eq": ["$_eff_due", None]},
                              {"$eq": ["$_asof", None]}]},
                    None,
                    {"$dateDiff": {
                        "startDate": "$_eff_due",
                        "endDate": "$_asof",
                        "unit": "day",
                    }},
                ]},
            }},
            # Past-due only: skip invoices whose effective due date
            # is still in the future (days_overdue < 0) so ``total``
            # matches the sum of the four past-due buckets.
            {"$match": {"_days_overdue": {"$gte": 0}}},
            {"$project": {
                "_id": 0, "_days_overdue": 1, "_outstanding": 1,
            }},
        ]

        counts: Dict[str, dict] = {b[0]: {"amount": 0.0,
                                          "invoice_count": 0}
                                    for b in AGE_BUCKETS}
        total = 0.0
        async for row in engine.db.quotes.aggregate(pipeline):
            days = int(row.get("_days_overdue") or 0)
            amt = float(row.get("_outstanding") or 0.0)
            if amt <= 0:
                continue
            for name, lo, hi in AGE_BUCKETS:
                if lo <= days <= hi:
                    counts[name]["amount"] += amt
                    counts[name]["invoice_count"] += 1
                    break
            total += amt

        rows = [
            {"bucket": name,
             "amount": round(counts[name]["amount"], 2),
             "invoice_count": counts[name]["invoice_count"]}
            for name, _, _ in AGE_BUCKETS
        ]

        return {
            "total": round(total, 2),
            "rows": rows,
            "row_count": len(rows),
            "net_terms_days": net_terms,
            "as_of": as_of,
        }
