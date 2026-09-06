"""Phase R0.1 · Feb-2026 — ``revenue_by_city`` grouped metric.

Groups invoice revenue by city derived from ``customers.address``.
Rows with unparseable / missing addresses fold into a single
``"(unknown)"`` bucket — the metric never drops rows.

Because the Feb-2026 customer schema stores city as part of a flat
``address`` string (see ``_revenue_shared.parse_city``), the
aggregation happens in Python after streaming the invoices with
their linked customer address. This costs a bit more memory than
a pure Mongo pipeline but keeps the parser in one place.
"""
from __future__ import annotations

from collections import defaultdict

from ..aggregation import AggregationEngine
from ..registry import Metric, register_metric
from ._revenue_shared import (
    build_lens_filter,
    parse_city,
    resolve_customer_whitelist,
)


@register_metric
class RevenueByCity(Metric):
    key = "revenue_by_city"
    label = "Revenue by City"
    format = "currency"
    direction = "up_is_good"
    is_grouped = True
    description = ("Sum of invoiced or collected revenue grouped "
                    "by service-address city. Rows with missing / "
                    "unparseable addresses fold into '(unknown)'.")

    async def compute_grouped(self, engine: AggregationEngine, period, filters: dict) -> dict:
        lens = filters.get("lens") or "invoiced"

        whitelist = await resolve_customer_whitelist(
            engine,
            filters.get("service_type"),
            filters.get("tech_id"),
        )
        if whitelist is not None and len(whitelist) == 0:
            return {"total": 0.0, "rows": [], "row_count": 0}

        # Step 1 — build a customer_id → address map (tenant-scoped).
        cust_scope: dict = {}
        if whitelist is not None:
            cust_scope["id"] = {"$in": whitelist}
        cust_address: dict[str, str] = {}
        async for c in engine.db.customers.find(
            engine._scope(cust_scope),
            {"_id": 0, "id": 1, "address": 1},
        ):
            cust_address[c.get("id") or ""] = c.get("address") or ""

        # Step 2 — sum invoice revenue per customer for the period.
        lens_filter = build_lens_filter(lens, period.start, period.end)
        match_filter: dict = {"$and": [lens_filter]}
        if whitelist is not None:
            match_filter["$and"].append({"customer_id": {"$in": whitelist}})

        pipeline = [
            {"$match": engine._scope(match_filter)},
            {"$group": {
                "_id": "$customer_id",
                "revenue": {"$sum": {"$convert": {
                    "input": "$total", "to": "double",
                    "onError": 0, "onNull": 0,
                }}},
            }},
        ]

        # Step 3 — fold customer revenue into city buckets.
        city_totals: dict[str, float] = defaultdict(float)
        city_customers: dict[str, set] = defaultdict(set)
        total = 0.0
        async for r in engine.db.quotes.aggregate(pipeline):
            cid = r.get("_id") or ""
            revenue = float(r.get("revenue") or 0.0)
            total += revenue
            city = parse_city(cust_address.get(cid))
            city_totals[city] += revenue
            if cid:
                city_customers[city].add(cid)

        rows = [
            {
                "city": city,
                "customer_count": len(city_customers.get(city, set())),
                "revenue": round(rev, 2),
            }
            for city, rev in city_totals.items()
        ]
        rows.sort(key=lambda x: (-x["revenue"], x["city"]))

        return {"total": total, "rows": rows, "row_count": len(rows)}
