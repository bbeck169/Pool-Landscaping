"""Phase R1 · Feb-2026 — ``ar_aging_by_customer`` drill-down.

Per-customer breakdown of outstanding balance + age bucket +
oldest overdue invoice. Sorted DESC by total_outstanding.

Row shape::

    {
        "customer_id":   "cust-1234",
        "customer_name": "Alan Chesebrough",
        "total_outstanding": 1245.67,
        "invoice_count": 3,
        "oldest_days_overdue": 87,
        "buckets": {
            "0-30":  {"amount": 145.67, "invoice_count": 1},
            "31-60": {"amount": 500.00, "invoice_count": 1},
            "61-90": {"amount": 600.00, "invoice_count": 1},
            "90+":   {"amount": 0.00,   "invoice_count": 0}
        }
    }
"""
from __future__ import annotations

from typing import Dict, List

from ..aggregation import AggregationEngine
from ..paid_date import (
    OUTSTANDING_STATUS_FILTER,
    build_effective_due_date_expr,
)
from ..registry import Metric, register_metric
from .ar_aging import AGE_BUCKETS, _resolve_net_terms


def _bucket_for_days(days: int) -> str:
    for name, lo, hi in AGE_BUCKETS:
        if lo <= days <= hi:
            return name
    return "90+"


@register_metric
class ArAgingByCustomer(Metric):
    key = "ar_aging_by_customer"
    label = "AR Aging by Customer"
    format = "currency"
    direction = "down_is_good"
    is_grouped = True
    description = ("Outstanding invoice balances grouped by "
                   "customer, sorted DESC.")

    async def compute_grouped(self, engine: AggregationEngine, period,
                              filters: dict) -> dict:
        net_terms = await _resolve_net_terms(engine)
        as_of = period.end
        as_of_dt = {"$dateFromString": {
            "dateString": as_of, "onError": None, "onNull": None,
        }}
        limit = int(filters.get("limit") or 0)
        offset = int(filters.get("offset") or 0)

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
                    {"$dateDiff": {"startDate": "$_eff_due",
                                   "endDate": "$_asof", "unit": "day"}},
                ]},
            }},
            # Past-due only: exclude invoices not yet past their
            # effective due date so bucket sums equal total_outstanding.
            {"$match": {"_days_overdue": {"$gte": 0},
                         "_outstanding": {"$gt": 0}}},
            {"$project": {"_id": 0, "customer_id": 1,
                           "customer_name": 1,
                           "_days_overdue": 1, "_outstanding": 1}},
        ]

        by_cust: Dict[str, dict] = {}
        async for row in engine.db.quotes.aggregate(pipeline):
            cid = row.get("customer_id") or "(unknown)"
            entry = by_cust.setdefault(cid, {
                "customer_id": cid,
                "customer_name": row.get("customer_name") or "(unnamed)",
                "total_outstanding": 0.0,
                "invoice_count": 0,
                "oldest_days_overdue": 0,
                "buckets": {b[0]: {"amount": 0.0, "invoice_count": 0}
                             for b in AGE_BUCKETS},
            })
            amt = float(row.get("_outstanding") or 0.0)
            days = int(row.get("_days_overdue") or 0)
            entry["total_outstanding"] += amt
            entry["invoice_count"] += 1
            entry["oldest_days_overdue"] = max(entry["oldest_days_overdue"],
                                                days)
            bname = _bucket_for_days(days)
            entry["buckets"][bname]["amount"] += amt
            entry["buckets"][bname]["invoice_count"] += 1

        rows: List[dict] = sorted(
            by_cust.values(),
            key=lambda r: r["total_outstanding"],
            reverse=True,
        )
        for r in rows:
            r["total_outstanding"] = round(r["total_outstanding"], 2)
            for b in r["buckets"].values():
                b["amount"] = round(b["amount"], 2)

        total = round(sum(r["total_outstanding"] for r in rows), 2)
        row_count = len(rows)
        if offset:
            rows = rows[offset:]
        if limit:
            rows = rows[:limit]

        return {
            "total": total,
            "rows": rows,
            "row_count": row_count,
            "net_terms_days": net_terms,
            "as_of": as_of,
        }
