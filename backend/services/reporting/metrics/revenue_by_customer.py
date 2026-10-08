"""Phase R0.1 · Feb-2026 — ``revenue_by_customer`` grouped metric.

Groups invoice revenue by ``customer_id`` and returns the top-N (or
paginated) rows sorted DESC by revenue.  Supports two lenses
(``invoiced`` / ``collected``) plus customer-side ``service_type``
and ``tech_id`` filters. See ``_revenue_shared.py`` for the shared
filter helpers so ``revenue_by_city`` stays in lockstep.

Phase R0.1+ · Feb-2026 — Prior-period delta.
When ``filters["include_prior"]`` is truthy (default), each row is
enriched with ``prior_revenue`` (same customer's revenue on the
same-length window ending at ``period.start``), ``delta_abs``, and
``delta_pct`` (``None`` when prior is 0 — the FE renders that case
as "New"). The prior aggregation reuses the exact same lens +
customer-whitelist filter shape so the two numbers are apples to
apples. Callers that opt out via ``include_prior=false`` get the
pre-R0.1+ response shape verbatim for backward compat.
"""
from __future__ import annotations

from ..aggregation import AggregationEngine
from ..registry import Metric, register_metric
from ._revenue_shared import (
    build_lens_filter,
    excluded_customer_ids,
    resolve_customer_whitelist,
)


def _row_pipeline(match_filter: dict) -> list[dict]:
    """Group-by-customer aggregation. Reused for both windows so
    ``prior_revenue`` and ``revenue`` are computed identically —
    only the ``created_at`` / ``paid_at`` window differs."""
    return [
        {"$match": match_filter},
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


@register_metric
class RevenueByCustomer(Metric):
    key = "revenue_by_customer"
    label = "Revenue by Customer"
    format = "currency"
    direction = "up_is_good"
    is_grouped = True
    description = ("Sum of invoiced or collected revenue grouped "
                    "by customer, sorted DESC. Supports service_type "
                    "and tech_id filters via customer scoping. "
                    "Optional prior-period delta enrichment.")

    async def compute_grouped(self, engine: AggregationEngine, period, filters: dict) -> dict:
        lens = filters.get("lens") or "invoiced"
        limit = filters.get("limit")
        offset = int(filters.get("offset") or 0)
        include_prior = filters.get("include_prior")
        if include_prior is None:
            include_prior = True

        # Customer whitelist (None means "no filter applied").
        whitelist = await resolve_customer_whitelist(
            engine,
            filters.get("service_type"),
            filters.get("tech_id"),
        )
        if whitelist is not None and len(whitelist) == 0:
            return {"total": 0.0, "rows": [], "row_count": 0}

        # CUSTOMER-RETENTION-ACCOUNT-CORRECTION-PARITY · Feb-2026 —
        # exclude customers currently flagged as bookkeeping / test
        # accounts so the KPI "Revenue by Customer" tile matches the
        # dedicated ``GET /reports/revenue-by-customer`` route (which
        # already excludes flagged accounts).  Retroactive by design:
        # flipping the flag ON drops the customer from every past
        # bucket on the very next refresh (no cache invalidation).
        # Empty list → no clause added, pre-flag behavior preserved
        # byte-for-byte.
        excluded = await excluded_customer_ids(engine)

        def _build_match(start: str, end: str) -> dict:
            lens_filter = build_lens_filter(lens, start, end)
            match: dict = {"$and": [lens_filter]}
            if whitelist is not None:
                match["$and"].append({"customer_id": {"$in": whitelist}})
            if excluded:
                match["$and"].append({"customer_id": {"$nin": excluded}})
            return engine._scope(match)

        # ── Current window ────────────────────────────────────────
        cur_match = _build_match(period.start, period.end)
        rows: list[dict] = []
        total = 0.0
        row_count = 0
        async for r in engine.db.quotes.aggregate(_row_pipeline(cur_match)):
            total += float(r.get("revenue") or 0.0)
            row_count += 1
            rows.append({
                "customer_id": r.get("_id"),
                "customer_name": r.get("customer_name") or "(unnamed)",
                "revenue": float(r.get("revenue") or 0.0),
                "invoice_count": int(r.get("row_count") or 0),
            })

        # ── R0.1+ · Prior-period enrichment ───────────────────────
        #
        # The prior aggregation runs across the SAME customer set
        # returned by the current window — this guarantees the
        # "prior revenue" column is meaningful (a row on the page
        # always represents one customer, not a joined superset).
        # Customers with no revenue in the prior window still
        # surface here with ``prior_revenue=0`` and the FE renders
        # them as "New".
        if include_prior:
            prior_by_id: dict[str, float] = {}
            prior_match = _build_match(period.prior_start, period.prior_end)
            # Narrow to just the current-window customer set so the
            # prior pipeline never over-scans.
            cur_ids = [row["customer_id"] for row in rows if row.get("customer_id")]
            if cur_ids:
                prior_match_narrowed = engine._scope({"$and": [
                    prior_match.get("$and", [{}])[0] if False else {},
                    # Merge the tenant-scoped filter with an id filter.
                ]}) if False else prior_match
                # We already have the tenant-scoped ``_build_match``
                # result — just append the id filter as another
                # constraint.
                prior_match_narrowed = {
                    "$and": list(prior_match.get("$and", [prior_match]))
                             + [{"customer_id": {"$in": cur_ids}}],
                }
                async for r in engine.db.quotes.aggregate(
                    _row_pipeline(prior_match_narrowed)
                ):
                    cid = r.get("_id")
                    if cid:
                        prior_by_id[cid] = float(r.get("revenue") or 0.0)
            for row in rows:
                pr = float(prior_by_id.get(row.get("customer_id") or "", 0.0))
                cur = float(row.get("revenue") or 0.0)
                row["prior_revenue"] = pr
                row["delta_abs"] = round(cur - pr, 2)
                row["delta_pct"] = (
                    None if pr == 0
                    else round(((cur - pr) / pr) * 100.0, 2)
                )

        # Apply pagination *after* the total is computed so the
        # response's ``total`` always reflects the full filter set,
        # not the visible slice.
        if offset:
            rows = rows[offset:]
        if limit:
            rows = rows[:limit]

        return {"total": total, "rows": rows, "row_count": row_count}
