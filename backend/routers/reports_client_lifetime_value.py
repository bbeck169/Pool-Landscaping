"""Feb-2026 · Reports Gap Fill Phase 5a.2 — Client Lifetime Value.

Per-customer lifetime aggregate. Wraps
``routers.analytics._client_lifetime_summary`` (new helper — see
that module's docstring for the parity note vs
``_lifetime_revenue_by_customer``, which the Attrition report
still calls).

Contract:
    GET /api/reports/client-lifetime-value
        ?start_date&end_date         # optional — both null = all-time
        &tenant_id                   # super_admin only

    → {
        "summary": {"avg_ltv_recurring", "avg_ltv_project",
                     "top_10_pct_revenue_share", "active_client_count"},
        "rows": [
            {"customer_id", "customer_name", "first_service_date",
             "last_service_date", "total_billed", "total_collected",
             "is_active", "client_type"}
        ],
        "chart": {"ltv_buckets": [{"bucket", "count"}, ...]},
        "tenant_id", "as_of", "computed_at"
      }

Canonical pins:
* **billed / collected / recurring_invoice_count** ← the new
  ``_client_lifetime_summary`` helper. Directly imported —
  never re-derived.
* **first_service_date / last_service_date** — min/max of
  ``jobs.completed_at`` per customer.
* **is_active** — mirrors ``routers.customers`` semantics:
  ``customer.is_active`` truthy (or missing → treated active by
  Phase 34f defaults). Ties to the Attrition report's inverse.
* **client_type** — ``recurring`` if the customer's
  ``recurring_invoice_count > project_invoice_count`` (i.e., the
  invoice-mix majority), else ``project``. This is the report-
  layer classifier and is documented in the memo.
* **avg_ltv_recurring / avg_ltv_project** — average of
  ``total_collected`` within each ``client_type`` cohort.
* **top_10_pct_revenue_share** — sum of ``total_collected`` for
  the top 10% of customers by collected, divided by the grand
  total, ×100 (1dp). Uses ``ceil`` for tiny populations so 1
  customer with 1 collected dollar still shows as 100%.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db, logger  # noqa: F401
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter(tags=["reports"])


# LTV histogram bucket edges (upper-exclusive except the last).
_LTV_BUCKETS = (
    ("$0-500",    0,     500),
    ("$500-1K",   500,   1000),
    ("$1K-2.5K",  1000,  2500),
    ("$2.5K-5K",  2500,  5000),
    ("$5K+",      5000,  float("inf")),
)


def _bucket_for(v: float) -> str:
    for label, lo, hi in _LTV_BUCKETS:
        if v >= lo and (v < hi or hi == float("inf")):
            return label
    return _LTV_BUCKETS[0][0]


def _iso_day_bounds(
    start_date: Optional[str], end_date: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """Both-optional variant. Returns ``(None, None)`` when both
    inputs are missing (all-time mode)."""
    if not start_date and not end_date:
        return None, None
    if not start_date or not end_date:
        raise HTTPException(400,
            "start_date and end_date must both be provided or both absent")
    try:
        s = datetime.fromisoformat(start_date).replace(
            hour=0, minute=0, second=0, microsecond=0,
            tzinfo=timezone.utc,
        )
        e = datetime.fromisoformat(end_date).replace(
            hour=23, minute=59, second=59, microsecond=999999,
            tzinfo=timezone.utc,
        )
    except Exception:
        raise HTTPException(400,
            "start_date and end_date must be YYYY-MM-DD")
    if e < s:
        raise HTTPException(400, "end_date must be >= start_date")
    return s.isoformat(), e.isoformat()


@router.get(
    "/reports/client-lifetime-value",
    operation_id="reports.clientLifetimeValue",
    summary="Client Lifetime Value — per-customer billed/collected + histogram",
)
async def client_lifetime_value(
    start_date: Optional[str] = Query(
        None, description="YYYY-MM-DD (inclusive). Both null → all-time."),
    end_date:   Optional[str] = Query(
        None, description="YYYY-MM-DD (inclusive). Both null → all-time."),
    tenant_id: Optional[str] = Query(None,
        description="super_admin only — override tenant scope"),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    role = (user.get("role") or "").strip().lower()
    if tenant_id and role != "super_admin":
        raise HTTPException(403, "tenant_id override requires super_admin")
    tid = (tenant_id or tenant["id"]).strip()
    if not tid:
        raise HTTPException(400, "tenant scope missing")

    s_iso, e_iso = _iso_day_bounds(start_date, end_date)

    # Customers (id → doc).
    customers = await db.customers.find(
        {"tenant_id": tid,
         "$or": [{"deleted_at": None},
                   {"deleted_at": {"$exists": False}}]},
        {"_id": 0, "id": 1, "name": 1, "first_name": 1, "last_name": 1,
         "is_active": 1},
    ).to_list(10000)
    cust_by_id = {c["id"]: c for c in customers}

    # Invoices — window-filtered when provided, all-time otherwise.
    q: Dict[str, Any] = {
        "tenant_id": tid, "doc_type": "invoice",
        "$or": [{"deleted_at": None},
                  {"deleted_at": {"$exists": False}}],
    }
    if s_iso and e_iso:
        q["$and"] = [{"created_at": {"$gte": s_iso, "$lte": e_iso}}]
    invoices = await db.quotes.find(
        q,
        {"_id": 0, "id": 1, "customer_id": 1, "total": 1,
         "payment_status": 1, "title": 1},
    ).to_list(20000)

    # Enriched per-customer aggregation (billed / collected /
    # invoice-count / recurring-vs-project mix).
    from routers.analytics import _client_lifetime_summary
    summary_by_cid = _client_lifetime_summary(invoices)

    # First / last service date from jobs.
    first_svc: Dict[str, Optional[str]] = {}
    last_svc:  Dict[str, Optional[str]] = {}
    jobs_cursor = db.jobs.find(
        {"tenant_id": tid, "completed_at": {"$ne": None}},
        {"_id": 0, "customer_id": 1, "completed_at": 1},
    )
    async for j in jobs_cursor:
        cid = j.get("customer_id")
        ca = j.get("completed_at")
        if not cid or not ca:
            continue
        cur_first = first_svc.get(cid)
        if cur_first is None or (isinstance(ca, str) and ca < cur_first):
            first_svc[cid] = ca
        cur_last = last_svc.get(cid)
        if cur_last is None or (isinstance(ca, str) and ca > cur_last):
            last_svc[cid] = ca

    # Rows — one per customer that has at least one invoice OR
    # one job in the window. All-time mode → any customer with any
    # invoice or job.
    row_cids = set(summary_by_cid.keys()) | set(last_svc.keys())
    rows: List[dict] = []
    recurring_ltvs: List[float] = []
    project_ltvs:   List[float] = []
    active_count = 0
    for cid in row_cids:
        cust = cust_by_id.get(cid, {})
        name = (cust.get("name")
                 or " ".join([cust.get("first_name") or "",
                                cust.get("last_name") or ""]).strip()
                 or "—")
        agg = summary_by_cid.get(cid, {"billed": 0.0, "collected": 0.0,
                                             "invoice_count": 0,
                                             "recurring_invoice_count": 0})
        rec_n = agg["recurring_invoice_count"]
        proj_n = agg["invoice_count"] - rec_n
        client_type = "recurring" if rec_n > proj_n else "project"
        # Is-active — treat "field missing" as active (Phase 34f).
        is_active = cust.get("is_active", True)
        if is_active is None:
            is_active = True
        if is_active:
            active_count += 1
        total_collected = round(agg["collected"], 2)
        if client_type == "recurring":
            recurring_ltvs.append(total_collected)
        else:
            project_ltvs.append(total_collected)
        rows.append({
            "customer_id":         cid,
            "customer_name":       name,
            "first_service_date":  first_svc.get(cid),
            "last_service_date":   last_svc.get(cid),
            "total_billed":        round(agg["billed"], 2),
            "total_collected":     total_collected,
            "is_active":           bool(is_active),
            "client_type":         client_type,
        })
    rows.sort(key=lambda r: -r["total_collected"])

    avg_r = round(sum(recurring_ltvs) / len(recurring_ltvs), 2) if recurring_ltvs else 0.0
    avg_p = round(sum(project_ltvs)   / len(project_ltvs),   2) if project_ltvs   else 0.0
    total_collected_all = sum(r["total_collected"] for r in rows)
    top_share = 0.0
    if rows and total_collected_all > 0:
        top_n = max(1, math.ceil(len(rows) * 0.10))
        top_sum = sum(r["total_collected"] for r in rows[:top_n])
        top_share = round((top_sum / total_collected_all) * 100, 1)

    # Histogram — bucket by ``total_collected``.
    hist: Dict[str, int] = defaultdict(int)
    for r in rows:
        hist[_bucket_for(r["total_collected"])] += 1
    hist_rows = [{"bucket": label, "count": hist.get(label, 0)}
                   for label, *_ in _LTV_BUCKETS]

    return {
        "summary": {
            "avg_ltv_recurring":         avg_r,
            "avg_ltv_project":           avg_p,
            "top_10_pct_revenue_share":  top_share,
            "active_client_count":       active_count,
        },
        "rows":  rows,
        "chart": {"ltv_buckets": hist_rows},
        "tenant_id":  tid,
        "as_of":  datetime.now(timezone.utc).isoformat(),
        "start_date": start_date,
        "end_date":   end_date,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
