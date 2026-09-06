"""Phase R1 · Feb-2026 — ``revenue_by_service_type`` grouped metric.

Groups collected revenue by ``service_category_id`` — the K71
service-category field on quote line items. Historical rows
without the field bucket under ``"Uncategorized"``.

Data model reminder (K71):

* Each ``quote.line_items[i]`` carries ``service_category_id``
  (optional). Missing → "Uncategorized".
* ``db.service_categories`` maps id → display name (tenant-scoped).

Row shape::

    {
        "service_category_id":   "svc-cat-123" | null,
        "service_category_name": "Weekly Maintenance",
        "revenue":               12345.67,
        "invoice_count":         28,
        "line_item_count":       84
    }
"""
from __future__ import annotations

from typing import Dict, List

from ..aggregation import AggregationEngine
from ..paid_date import PAID_STATUS_FILTER, build_paid_window_filter
from ..registry import Metric, register_metric


_UNCATEGORIZED_LABEL = "Uncategorized"


async def _resolve_category_names(engine: AggregationEngine,
                                    ids: list) -> Dict[str, str]:
    if not ids:
        return {}
    non_null = [i for i in ids if i]
    if not non_null:
        return {}
    out: Dict[str, str] = {}
    async for row in engine.db.service_categories.find(
        {"tenant_id": engine.tenant_id, "id": {"$in": non_null}},
        {"_id": 0, "id": 1, "name": 1},
    ):
        out[row["id"]] = row.get("name") or _UNCATEGORIZED_LABEL
    return out


@register_metric
class RevenueByServiceType(Metric):
    key = "revenue_by_service_type"
    label = "Revenue by Service Type"
    format = "currency"
    direction = "up_is_good"
    is_grouped = True
    description = ("Collected revenue grouped by service category "
                   "(K71). Rows without a category → Uncategorized.")

    async def compute_grouped(self, engine: AggregationEngine, period,
                              filters: dict) -> dict:
        lens = filters.get("lens") or "collected"
        limit = int(filters.get("limit") or 0)
        offset = int(filters.get("offset") or 0)

        # Base doc filter — paid invoices in-window for the
        # collected lens, all invoices created-in-window for
        # invoiced.
        if lens == "invoiced":
            doc_match = {"$and": [
                {"doc_type": "invoice"},
                {"created_at": {"$gte": period.start, "$lt": period.end}},
            ]}
        else:
            doc_match = {"$and": [
                {"doc_type": "invoice"},
                PAID_STATUS_FILTER,
                build_paid_window_filter(period.start, period.end),
            ]}

        pipeline = [
            {"$match": engine._scope(doc_match)},
            {"$unwind": "$line_items"},
            {"$group": {
                "_id": {"$ifNull": ["$line_items.service_category_id", None]},
                "revenue": {"$sum": {"$multiply": [
                    {"$convert": {"input": "$line_items.quantity",
                                   "to": "double",
                                   "onError": 0, "onNull": 0}},
                    {"$convert": {"input": {"$ifNull": [
                        "$line_items.retail_price_snapshot",
                        "$line_items.unit_price",
                    ]}, "to": "double", "onError": 0, "onNull": 0}},
                ]}},
                "invoice_ids": {"$addToSet": "$id"},
                "line_item_count": {"$sum": 1},
            }},
            {"$project": {
                "_id": 1, "revenue": 1, "line_item_count": 1,
                "invoice_count": {"$size": "$invoice_ids"},
            }},
            {"$sort": {"revenue": -1, "_id": 1}},
        ]

        # First pass: collect raw group rows so we can look up names.
        raw_rows: list[dict] = []
        cat_ids: list = []
        async for r in engine.db.quotes.aggregate(pipeline):
            raw_rows.append(r)
            cat_ids.append(r.get("_id"))

        names = await _resolve_category_names(engine, cat_ids)

        rows: List[dict] = []
        total = 0.0
        for r in raw_rows:
            cat_id = r.get("_id")
            display = names.get(cat_id) if cat_id else _UNCATEGORIZED_LABEL
            rev = float(r.get("revenue") or 0.0)
            rows.append({
                "service_category_id": cat_id,
                "service_category_name": display or _UNCATEGORIZED_LABEL,
                "revenue": round(rev, 2),
                "invoice_count": int(r.get("invoice_count") or 0),
                "line_item_count": int(r.get("line_item_count") or 0),
            })
            total += rev

        row_count = len(rows)
        if offset:
            rows = rows[offset:]
        if limit:
            rows = rows[:limit]

        return {
            "total": round(total, 2),
            "rows": rows,
            "row_count": row_count,
            "lens": lens,
        }
