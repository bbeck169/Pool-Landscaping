"""Phase R0 · Feb-2026 — Aggregation primitives for the reporting engine.

Every method is tenant-scoped by contract: the caller MUST pass
``tenant_id`` and the filter MUST be a caller-owned dict that the
engine will $and-merge with the tenant + not-deleted guard. There
is no way to run an aggregation without a tenant scope — the class
constructor refuses to instantiate without one.

Primitives (all async):

* :py:meth:`AggregationEngine.count` — count of docs matching filter.
* :py:meth:`AggregationEngine.sum_field` — sum of one numeric field.
* :py:meth:`AggregationEngine.bucket_by_date` — group into
  day / week / month buckets on any ISO-string date field.
* :py:meth:`AggregationEngine.period_over_period` — return
  ``{current, prior, delta_pct}`` for any user-supplied metric fn.

These primitives are deliberately minimal — R1 will layer
metric-specific helpers on top of them rather than growing the
engine surface area.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase


Granularity = str  # "day" | "week" | "month"


@dataclass
class BucketPoint:
    t: str   # ISO date at the START of the bucket
    v: float


def _not_deleted_filter() -> dict:
    """Matches the ``$or [deleted_at null / deleted_at absent]``
    convention used across the app so aggregations never count
    soft-deleted docs."""
    return {"$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]}


class AggregationEngine:
    """Tenant-scoped aggregation surface. R1+ metrics take an
    instance of this class rather than the raw ``db`` handle so
    unit tests can inject a mock without stubbing Motor directly."""

    def __init__(self, db: AsyncIOMotorDatabase, tenant_id: str):
        if not tenant_id:
            raise ValueError("AggregationEngine requires tenant_id")
        self.db = db
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # Filter helpers
    # ------------------------------------------------------------------
    def _scope(self, filter_: Optional[dict] = None) -> dict:
        base = {"tenant_id": self.tenant_id}
        merged = {"$and": [base, _not_deleted_filter()]}
        if filter_:
            merged["$and"].append(dict(filter_))
        return merged

    # ------------------------------------------------------------------
    # Primitives
    # ------------------------------------------------------------------
    async def count(self, collection: str, filter_: Optional[dict] = None) -> int:
        return await self.db[collection].count_documents(self._scope(filter_))

    async def sum_field(
        self,
        collection: str,
        filter_: Optional[dict],
        field: str,
    ) -> float:
        """Sum a single numeric field across matching docs. Missing
        or non-numeric values contribute 0. Never raises on empty
        result sets — returns 0.0."""
        pipeline = [
            {"$match": self._scope(filter_)},
            {"$group": {"_id": None, "total": {
                "$sum": {"$convert": {
                    "input": f"${field}", "to": "double",
                    "onError": 0, "onNull": 0,
                }},
            }}},
        ]
        cur = self.db[collection].aggregate(pipeline)
        async for row in cur:
            return float(row.get("total") or 0.0)
        return 0.0

    async def bucket_by_date(
        self,
        collection: str,
        filter_: Optional[dict],
        date_field: str,
        granularity: Granularity = "day",
        value_field: Optional[str] = None,
    ) -> list[BucketPoint]:
        """Group docs by ``day`` | ``week`` | ``month`` derived from
        ``date_field``. If ``value_field`` is provided the bucket
        value is the SUM of that field; otherwise it's a COUNT.

        ``date_field`` is expected to hold an ISO-8601 string; the
        pipeline uses ``$dateFromString`` (fail-null) so unparseable
        rows silently drop out of the aggregation.
        """
        if granularity not in ("day", "week", "month"):
            raise ValueError(f"unsupported granularity: {granularity}")
        trunc_unit = {"day": "day", "week": "week",
                      "month": "month"}[granularity]

        val_expr: Any
        if value_field:
            val_expr = {"$sum": {"$convert": {
                "input": f"${value_field}", "to": "double",
                "onError": 0, "onNull": 0,
            }}}
        else:
            val_expr = {"$sum": 1}

        pipeline = [
            {"$match": self._scope(filter_)},
            {"$addFields": {
                "_dt": {"$dateFromString": {
                    "dateString": f"${date_field}", "onError": None, "onNull": None,
                }},
            }},
            {"$match": {"_dt": {"$ne": None}}},
            {"$addFields": {
                "_bucket": {"$dateTrunc": {
                    "date": "$_dt", "unit": trunc_unit,
                }},
            }},
            {"$group": {"_id": "$_bucket", "v": val_expr}},
            {"$sort": {"_id": 1}},
        ]
        out: list[BucketPoint] = []
        async for row in self.db[collection].aggregate(pipeline):
            bucket_dt = row.get("_id")
            if bucket_dt is None:
                continue
            out.append(BucketPoint(
                t=bucket_dt.date().isoformat(),
                v=float(row.get("v") or 0.0),
            ))
        return out

    async def period_over_period(
        self,
        metric_fn: Callable[[str, str], Awaitable[float]],
        current: tuple[str, str],
        prior: tuple[str, str],
    ) -> dict:
        """Run ``metric_fn(start, end)`` for the current + prior
        windows and return ``{current, prior, delta_pct}``.

        ``delta_pct`` is a signed float rounded to 2dp:
          * ``None`` if the prior value is 0 (no baseline).
          * Positive means the metric grew.
          * Negative means the metric shrank.
        """
        cur_val = float(await metric_fn(*current))
        prior_val = float(await metric_fn(*prior))
        if prior_val == 0:
            delta_pct = None
        else:
            delta_pct = round(((cur_val - prior_val) / prior_val) * 100.0, 2)
        return {"current": cur_val, "prior": prior_val, "delta_pct": delta_pct}
