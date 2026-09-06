"""Phase R0 · Feb-2026 — ``revenue_total`` KPI.

Sums ``amount_paid`` across ``quotes`` documents that are (a) not
soft-deleted, (b) marked ``payment_status="paid"`` (or have
``amount_paid > 0``), and (c) whose payment date lies inside the
selected period.

R1 fix · Feb-2026
-----------------
Originally this metric queried a ``paid_date`` field the live
schema doesn't populate (the real field is ``paid_at``). The
metric silently fell through to a ``created_at``-in-range
fallback and bucketed on invoice-creation rather than payment
date.

The paid-window resolution moved to the shared
``services.reporting.paid_date`` helper — the same helper is
used by every R1 metric so the KPI reconciles with the P&L,
cash-flow, and unpaid-invoices reports byte-for-byte.

Reconciliation note (see PHASE_R1_A_FINANCIAL_BACKEND.md §5):
numbers may shift for tenants where a paid invoice's ``paid_at``
lies in a different calendar bucket than its ``created_at``. The
delta is documented in the R1.a ship report.
"""
from __future__ import annotations

from ..aggregation import AggregationEngine
from ..paid_date import PAID_STATUS_FILTER, build_paid_window_filter
from ..registry import Metric, register_metric


# Kept as an alias for any external caller. New code imports
# ``PAID_STATUS_FILTER`` from ``services.reporting.paid_date``.
PAID_FILTER = PAID_STATUS_FILTER


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
    combined = {"$and": [
        PAID_STATUS_FILTER,
        build_paid_window_filter(start, end),
    ]}
    return await engine.sum_field("quotes", combined, "amount_paid") \
        or await engine.sum_field("quotes", {"$and": [
            {"payment_status": "paid"},
            build_paid_window_filter(start, end),
        ]}, "total")


@register_metric
class RevenueTotal(Metric):
    key = "revenue_total"
    label = "Total Revenue"
    format = "currency"
    direction = "up_is_good"
    description = ("Sum of paid invoice amounts in the selected "
                    "period, tenant-scoped and soft-delete safe.")

    async def compute(self, engine: AggregationEngine, period) -> dict:
        cur = await _sum_paid(engine, period.start, period.end)
        prior = await _sum_paid(engine, period.prior_start, period.prior_end)
        delta_pct = None
        if prior:
            delta_pct = round(((cur - prior) / prior) * 100.0, 2)

        gran = _pick_granularity(period.start, period.end)
        combined = {"$and": [
            PAID_STATUS_FILTER,
            build_paid_window_filter(period.start, period.end),
        ]}
        # Sparkline: bucket by ``paid_at`` when present so a
        # payment-date view is consistent with the scalar value.
        buckets = await engine.bucket_by_date(
            "quotes", combined, "paid_at",
            granularity=gran, value_field="amount_paid",
        )
        sparkline = [{"t": b.t, "v": b.v} for b in buckets]

        return {
            "value": cur,
            "prior_value": prior,
            "delta_pct": delta_pct,
            "sparkline": sparkline,
        }
