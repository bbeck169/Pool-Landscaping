"""Feb-2026 · Reports Gap Fill Phase 5a.2 — Recurring vs. Project Revenue.

Splits paid revenue into two buckets using the SAME predicate the
admin dashboard uses (``dashboard.py::L167``): an invoice is
"recurring" when its ``title`` contains any of
``["monthly", "weekly", "recurring"]``; otherwise "project".

Reuses ``routers.analytics._is_recurring_invoice`` (the top-level
helper introduced in Phase-5a.2) so both surfaces cannot drift.

Contract:
    GET /api/reports/recurring-vs-project-revenue?start_date&end_date

    → {
        "summary": {"total_revenue", "recurring_amount",
                     "project_amount", "recurring_pct"},
        "rows": [
            {"month": "YYYY-MM", "recurring_amount",
             "project_amount", "total"}
        ],
        "chart": {
            "donut": {"recurring", "project"},
            "trailing_12mo": [
                {"month", "recurring_amount", "project_amount"}, ...
            ]
        },
        "tenant_id", "start_date", "end_date", "computed_at"
      }
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db, logger  # noqa: F401
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter(tags=["reports"])


def _iso_day_bounds(start_date: str, end_date: str) -> tuple[str, str]:
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
        raise HTTPException(
            400, "start_date and end_date must be YYYY-MM-DD")
    if e < s:
        raise HTTPException(400, "end_date must be >= start_date")
    return s.isoformat(), e.isoformat()


@router.get(
    "/reports/recurring-vs-project-revenue",
    operation_id="reports.recurringVsProjectRevenue",
    summary="Recurring vs. Project Revenue — dashboard-mirrored split",
)
async def recurring_vs_project_revenue(
    start_date: str = Query(..., description="YYYY-MM-DD (inclusive)"),
    end_date:   str = Query(..., description="YYYY-MM-DD (inclusive)"),
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
    now = datetime.now(timezone.utc)
    t12_floor_iso = (now - timedelta(days=365)).isoformat()

    # Paid invoices for the union window (in-filter + trailing-12mo).
    from routers.analytics import _is_recurring_invoice
    invoices = await db.quotes.find(
        {"tenant_id": tid, "doc_type": "invoice",
         "payment_status": "paid",
         "$or": [{"deleted_at": None},
                   {"deleted_at": {"$exists": False}}]},
        {"_id": 0, "id": 1, "title": 1, "total": 1, "paid_at": 1,
         "created_at": 1},
    ).to_list(20000)

    # In-window aggregation (per-month rows).
    per_month: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"recurring_amount": 0.0, "project_amount": 0.0},
    )
    # Trailing-12mo chart (independent of the filter).
    per_month_t12: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"recurring_amount": 0.0, "project_amount": 0.0},
    )
    recurring_in = 0.0
    project_in   = 0.0

    for inv in invoices:
        paid_at = inv.get("paid_at") or ""
        total = float(inv.get("total") or 0)
        is_rec = _is_recurring_invoice(inv)
        month_key = (paid_at or "")[:7]  # YYYY-MM
        # In-window contribution.
        if isinstance(paid_at, str) and s_iso <= paid_at <= e_iso:
            if is_rec:
                recurring_in += total
                per_month[month_key]["recurring_amount"] += total
            else:
                project_in += total
                per_month[month_key]["project_amount"] += total
        # Trailing-12mo contribution (rolling; filter-independent).
        if isinstance(paid_at, str) and paid_at >= t12_floor_iso:
            if is_rec:
                per_month_t12[month_key]["recurring_amount"] += total
            else:
                per_month_t12[month_key]["project_amount"] += total

    rows: List[dict] = []
    for month in sorted(per_month.keys()):
        rec = round(per_month[month]["recurring_amount"], 2)
        proj = round(per_month[month]["project_amount"], 2)
        rows.append({
            "month":            month,
            "recurring_amount": rec,
            "project_amount":   proj,
            "total":            round(rec + proj, 2),
        })

    chart_trailing: List[dict] = []
    for month in sorted(per_month_t12.keys()):
        chart_trailing.append({
            "month":            month,
            "recurring_amount": round(per_month_t12[month]["recurring_amount"], 2),
            "project_amount":   round(per_month_t12[month]["project_amount"], 2),
        })

    total_revenue = round(recurring_in + project_in, 2)
    recurring_amount = round(recurring_in, 2)
    project_amount = round(project_in, 2)
    recurring_pct = (
        round((recurring_amount / total_revenue) * 100, 1)
        if total_revenue else 0.0
    )

    return {
        "summary": {
            "total_revenue":     total_revenue,
            "recurring_amount":  recurring_amount,
            "project_amount":    project_amount,
            "recurring_pct":     recurring_pct,
        },
        "rows": rows,
        "chart": {
            "donut": {"recurring": recurring_amount,
                        "project":   project_amount},
            "trailing_12mo": chart_trailing,
        },
        "tenant_id":  tid,
        "start_date": start_date,
        "end_date":   end_date,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
