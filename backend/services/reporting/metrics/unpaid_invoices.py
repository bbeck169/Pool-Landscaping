"""Phase R1 · Feb-2026 — ``unpaid_invoices`` list metric.

One row per outstanding invoice. Columns::

    id, customer_id, customer_name, invoice_number,
    total, amount_paid, balance,
    created_at, due_date, effective_due_date,
    days_overdue, payment_status, status,
    partial (bool)

Sorted DESC by ``days_overdue`` — the most-overdue invoices float
to the top of the operator's list. Callers can page via
``limit`` / ``offset``. Ignores the ``period`` window when
``all_outstanding`` filter is truthy; otherwise scopes to invoices
whose ``created_at`` is in the period.
"""
from __future__ import annotations

from typing import List

from ..aggregation import AggregationEngine
from ..paid_date import (
    OUTSTANDING_STATUS_FILTER,
    build_effective_due_date_expr,
)
from ..registry import Metric, register_metric
from .ar_aging import _resolve_net_terms


@register_metric
class UnpaidInvoices(Metric):
    key = "unpaid_invoices"
    label = "Unpaid Invoices"
    format = "currency"
    direction = "down_is_good"
    is_grouped = True
    description = ("Every outstanding invoice, sorted DESC by "
                   "days overdue.")

    async def compute_grouped(self, engine: AggregationEngine, period,
                              filters: dict) -> dict:
        net_terms = await _resolve_net_terms(engine)
        as_of = period.end
        all_outstanding = bool(filters.get("all_outstanding"))
        limit = int(filters.get("limit") or 0)
        offset = int(filters.get("offset") or 0)

        as_of_dt = {"$dateFromString": {
            "dateString": as_of, "onError": None, "onNull": None,
        }}

        base_match = OUTSTANDING_STATUS_FILTER
        if not all_outstanding:
            base_match = {"$and": list(OUTSTANDING_STATUS_FILTER["$and"]) + [
                {"created_at": {"$gte": period.start, "$lt": period.end}},
            ]}

        pipeline = [
            {"$match": engine._scope(base_match)},
            {"$addFields": {
                "_eff_due": build_effective_due_date_expr(net_terms),
                "_asof": as_of_dt,
                "_total_f": {"$convert": {"input": "$total", "to": "double",
                                            "onError": 0, "onNull": 0}},
                "_paid_f": {"$convert": {"input": "$amount_paid",
                                           "to": "double",
                                           "onError": 0, "onNull": 0}},
            }},
            {"$addFields": {
                "_balance": {"$max": [0, {"$subtract":
                                            ["$_total_f", "$_paid_f"]}]},
                "_days_overdue": {"$cond": [
                    {"$or": [{"$eq": ["$_eff_due", None]},
                              {"$eq": ["$_asof", None]}]},
                    None,
                    {"$dateDiff": {"startDate": "$_eff_due",
                                   "endDate": "$_asof", "unit": "day"}},
                ]},
                "_partial": {"$gt": ["$_paid_f", 0]},
            }},
            {"$match": {"_balance": {"$gt": 0}}},
            {"$project": {
                "_id": 0,
                "id": 1, "customer_id": 1, "customer_name": 1,
                "invoice_number": 1, "created_at": 1, "due_date": 1,
                "payment_status": 1, "status": 1,
                "total": "$_total_f",
                "amount_paid": "$_paid_f",
                "balance": "$_balance",
                "days_overdue": "$_days_overdue",
                "partial": "$_partial",
                "effective_due_date": {"$dateToString":
                                         {"date": "$_eff_due"}},
            }},
            {"$sort": {"days_overdue": -1, "created_at": 1}},
        ]

        rows: List[dict] = []
        total_outstanding = 0.0
        async for r in engine.db.quotes.aggregate(pipeline):
            rows.append({
                "id": r.get("id"),
                "customer_id": r.get("customer_id"),
                "customer_name": r.get("customer_name") or "(unnamed)",
                "invoice_number": r.get("invoice_number"),
                "total": round(float(r.get("total") or 0.0), 2),
                "amount_paid": round(float(r.get("amount_paid") or 0.0), 2),
                "balance": round(float(r.get("balance") or 0.0), 2),
                "created_at": r.get("created_at"),
                "due_date": r.get("due_date"),
                "effective_due_date": r.get("effective_due_date"),
                "days_overdue": int(r.get("days_overdue") or 0),
                "payment_status": r.get("payment_status"),
                "status": r.get("status"),
                "partial": bool(r.get("partial")),
            })
            total_outstanding += float(r.get("balance") or 0.0)

        row_count = len(rows)
        if offset:
            rows = rows[offset:]
        if limit:
            rows = rows[:limit]

        return {
            "total": round(total_outstanding, 2),
            "rows": rows,
            "row_count": row_count,
            "net_terms_days": net_terms,
            "as_of": as_of,
            "scope": ("all_outstanding" if all_outstanding
                       else "period_scoped"),
        }
