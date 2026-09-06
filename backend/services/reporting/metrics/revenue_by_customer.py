"""Phase R0.1 · Feb-2026 — ``revenue_by_customer`` grouped metric.

Groups invoice revenue by ``customer_id`` and returns the top-N (or
paginated) rows sorted DESC by revenue.  Supports two lenses
(``invoiced`` / ``collected``) plus customer-side ``service_type``
and ``tech_id`` filters. See ``_revenue_shared.py`` for the shared
filter helpers so ``revenue_by_city`` stays in lockstep.
"""
from __future__ import annotations

from ..aggregation import AggregationEngine
from ..registry import Metric, register_metric
from ._revenue_shared import build_lens_filter, resolve_customer_whitelist


@register_metric
class RevenueByCustomer(Metric):
    key = "revenue_by_customer"
    label = "Revenue by Customer"
    format = "currency"
    direction = "up_is_good"
    is_grouped = True
    description = ("Sum of invoiced or collected revenue grouped "
                    "by customer, sorted DESC. Supports service_type "
                    "and tech_id filters via customer scoping.")

    async def compute_grouped(self, engine: AggregationEngine, period, filters: dict) -> dict:
        lens = filters.get("lens") or "invoiced"
        limit = filters.get("limit")
        offset = int(filters.get("offset") or 0)

        # Customer whitelist (None means "no filter applied").
        whitelist = await resolve_customer_whitelist(
            engine,
            filters.get("service_type"),
            filters.get("tech_id"),
        )
        if whitelist is not None and len(whitelist) == 0:
            return {"total": 0.0, "rows": [], "row_count": 0}

        lens_filter = build_lens_filter(lens, period.start, period.end)
        match_filter: dict = {"$and": [lens_filter]}
        if whitelist is not None:
            match_filter["$and"].append({"customer_id": {"$in": whitelist}})

        # Aggregate ``quotes`` — this is the invoices collection on
        # Feb-2026 (doc_type "quote" | "invoice" — both carry a
        # ``total`` field; both flow through ``payment_status``).
        pipeline: list[dict] = [
            {"$match": engine._scope(match_filter)},
            {"$group": {
                "_id": "$customer_id",
                "revenue": {"$sum": {"$convert": {
                    "input": "$total", "to": "double",
                    "onError": 0, "onNull": 0,
                }}},
                "customer_name": {"$first": "$customer_name"},
                "row_count": {"$sum": 1},
            }},
            {"$sort": {"revenue": -1, "_id": 1}},
        ]

        rows: list[dict] = []
        total = 0.0
        row_count = 0
        async for r in engine.db.quotes.aggregate(pipeline):
            total += float(r.get("revenue") or 0.0)
            row_count += 1
            rows.append({
                "customer_id": r.get("_id"),
                "customer_name": r.get("customer_name") or "(unnamed)",
                "revenue": float(r.get("revenue") or 0.0),
                "invoice_count": int(r.get("row_count") or 0),
            })

        # Apply pagination *after* the total is computed so the
        # response's ``total`` always reflects the full filter set,
        # not the visible slice.
        if offset:
            rows = rows[offset:]
        if limit:
            rows = rows[:limit]

        return {"total": total, "rows": rows, "row_count": row_count}
