"""Phase R0 · Feb-2026 — ``revenue_total`` KPI.

Sums ``amount_paid`` across ``quotes`` documents that are (a) not
soft-deleted, (b) marked ``payment_status="paid"``, and (c) whose
``paid_date`` (falling back to ``created_at``) lies inside the
selected period. Sparkline granularity is chosen based on the
period length so a YTD KPI doesn't render 12 months of daily
points.

R1 will layer additional revenue metrics on top of the same
aggregation engine; this file is the reference shape all future
metrics should copy.
"""
from __future__ import annotations

from ..aggregation import AggregationEngine
from ..registry import Metric, register_metric


PAID_FILTER = {
    "$or": [
        {"amount_paid": {"$gt": 0}},
        {"payment_status": "paid"},
    ],
}


def _pick_granularity(start: str, end: str) -> str:
    """Return a sensible sparkline bucket size for the window."""
    from datetime import date
    try:
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    except Exception:
        return "day"
    if days <= 45:
        return "day"
    if days <= 180:
        return "week"
    return "month"


async def _sum_paid(engine: AggregationEngine, start: str, end: str) -> float:
    """Sum of ``amount_paid`` on paid ``quotes`` in [start, end)."""
    date_window = {"$or": [
        {"paid_date": {"$gte": start, "$lt": end}},
        {"$and": [
            {"paid_date": {"$in": [None, ""]}},
            {"created_at": {"$gte": start, "$lt": end}},
        ]},
    ]}
    combined = {"$and": [PAID_FILTER, date_window]}
    return await engine.sum_field("quotes", combined, "amount_paid") \
        or await engine.sum_field("quotes", {"$and": [{"payment_status": "paid"}, date_window]}, "total")


@register_metric
class RevenueTotal(Metric):
    key = "revenue_total"
    label = "Total Revenue"
    format = "currency"
    direction = "up_is_good"
    description = ("Sum of paid invoice amounts in the selected "
                    "period, tenant-scoped and soft-delete safe.")

    async def compute(self, engine: AggregationEngine, period) -> dict:
        # Period-over-period + sparkline in parallel-safe sequence.
        cur = await _sum_paid(engine, period.start, period.end)
        prior = await _sum_paid(engine, period.prior_start, period.prior_end)
        delta_pct = None
        if prior:
            delta_pct = round(((cur - prior) / prior) * 100.0, 2)

        gran = _pick_granularity(period.start, period.end)
        # Sparkline uses the SAME filter shape as the sum so drift is impossible.
        date_window = {"$or": [
            {"paid_date": {"$gte": period.start, "$lt": period.end}},
            {"$and": [
                {"paid_date": {"$in": [None, ""]}},
                {"created_at": {"$gte": period.start, "$lt": period.end}},
            ]},
        ]}
        combined = {"$and": [PAID_FILTER, date_window]}
        # ``bucket_by_date`` needs one date field; fall back to created_at
        # since paid_date may be sparse on historic rows.
        buckets = await engine.bucket_by_date(
            "quotes", combined, "created_at",
            granularity=gran, value_field="amount_paid",
        )
        sparkline = [{"t": b.t, "v": b.v} for b in buckets]

        return {
            "value": cur,
            "prior_value": prior,
            "delta_pct": delta_pct,
            "sparkline": sparkline,
        }
