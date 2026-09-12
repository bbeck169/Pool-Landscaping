"""Feb-2026 · Reports Gap Fill Phase 5a.1 (Part B) — Attrition Report.

Date-ranged view of customers who transitioned to *inactive*
(muted OR plain-deactivated) within ``[start_date, end_date]``.
Complements the pre-existing Inactive Customers surface (which is
a full active/inactive dump) by scoping to **transitions** and
exposing the **reason breakdown** + per-row LTV.

Contract (single endpoint, tenant-scoped, super_admin may override):

    GET /api/reports/attrition?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD

    → {
        "summary": {
            "total_attrited": int,
            "attrition_rate_pct": float,
            "avg_ltv_of_attrited": float,
        },
        "rows": [
            {"customer_id", "customer_name", "became_inactive_at",
             "inactive_reason", "lifetime_value", "last_service_date"}
        ],
        "chart": {"reason_counts": {"<reason>": int, ...}},
        "tenant_id": "<tid>",
        "start_date": "<iso>", "end_date": "<iso>",
        "computed_at": "<iso>"
      }

Canonical data-source pins:
* **Inactive transition** — a customer row with ``is_active=False``
  (i.e., either muted-via-P27 or plain-deactivated). The transition
  timestamp is the row's ``muted_at`` (mute path) OR the row's
  ``updated_at`` (deactivation path) — whichever is present. If
  neither is present the row is excluded (we won't fabricate a
  transition date).
* **inactive_reason** — ``muted_reason`` for muted rows;
  ``"not_specified"`` for plain-deactivated rows without a reason
  field. This mirrors the P29 pattern (see
  ``routers/customers.py::mute_customer``).
* **lifetime_value** — sum of paid-invoice totals (mirrors
  ``routers.analytics._lifetime_revenue_by_customer`` — reused via
  direct import so cockpit parity is a compile-time guarantee, not
  a copy-paste).
* **last_service_date** — latest ``completed_at`` on the customer's
  jobs (matches ``routers.analytics.churn_risk`` picking pattern).
* **attrition_rate_pct** — ``total_attrited / total_customers_at_period_start * 100``
  where the denominator is customers created **before** the window
  (i.e., the population "at risk" during the window). Rounded to
  1dp.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter(tags=["reports"])


# Feb-2026 · P16B — helper extracted to services/_shared/reports.py.
# See /app/memory/CLEANUP_DISPATCH_A.md.
from services._shared.reports import _iso_day_bounds  # noqa: E402


def _pick_inactive_at(row: dict) -> Optional[str]:
    """Best-effort transition timestamp. ``muted_at`` wins when the
    P27 mute path stamped it; otherwise ``updated_at`` is the
    fallback. Returns ``None`` when neither is present so callers
    can drop the row (we don't invent a transition date)."""
    return row.get("muted_at") or row.get("updated_at")


def _in_window(iso: Optional[str], s: str, e: str) -> bool:
    if not iso or not isinstance(iso, str):
        return False
    return s <= iso <= e


async def _attrition_rows(
    tid: str, start_iso: str, end_iso: str,
) -> tuple[List[dict], Dict[str, float], Dict[str, Optional[str]]]:
    """Return ``(inactive_rows, ltv_by_cid, last_service_by_cid)``
    for the window. Kept private so tests can drive the shape."""
    inactive_cursor = db.customers.find(
        {"tenant_id": tid, "is_active": False,
         "$or": [{"deleted_at": None},
                   {"deleted_at": {"$exists": False}}]},
        {"_id": 0, "id": 1, "name": 1, "first_name": 1, "last_name": 1,
         "muted_at": 1, "muted_reason": 1, "updated_at": 1},
    )
    rows: List[dict] = []
    async for c in inactive_cursor:
        became = _pick_inactive_at(c)
        if not _in_window(became, start_iso, end_iso):
            continue
        rows.append({**c, "_became_inactive_at": became})

    # LTV — mirror ``routers.analytics._lifetime_revenue_by_customer``.
    from routers.analytics import _lifetime_revenue_by_customer as _ltv
    invoices = await db.quotes.find(
        {"tenant_id": tid, "doc_type": "invoice",
         "payment_status": "paid"},
        {"_id": 0, "customer_id": 1, "total": 1, "payment_status": 1},
    ).to_list(10000)
    ltv_by_cid: Dict[str, float] = _ltv(invoices)

    # Last service date — latest completed_at per customer.
    last_service: Dict[str, Optional[str]] = defaultdict(lambda: None)
    jobs_cursor = db.jobs.find(
        {"tenant_id": tid, "completed_at": {"$ne": None}},
        {"_id": 0, "customer_id": 1, "completed_at": 1},
    )
    async for j in jobs_cursor:
        cid = j.get("customer_id")
        ca = j.get("completed_at")
        if not cid or not ca:
            continue
        cur = last_service.get(cid)
        if cur is None or (isinstance(ca, str) and ca > cur):
            last_service[cid] = ca

    return rows, ltv_by_cid, dict(last_service)


@router.get(
    "/reports/attrition",
    operation_id="reports.attrition",
    summary="Attrition Report — customers who became inactive in a window",
)
async def attrition_report(
    start_date: str = Query(..., description="YYYY-MM-DD (inclusive)"),
    end_date:   str = Query(..., description="YYYY-MM-DD (inclusive)"),
    tenant_id: Optional[str] = Query(
        None, description="super_admin only — override tenant scope",
    ),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    role = (user.get("role") or "").strip().lower()
    if tenant_id and role != "super_admin":
        raise HTTPException(
            status_code=403,
            detail="tenant_id override requires super_admin",
        )
    tid = (tenant_id or tenant["id"]).strip()
    if not tid:
        raise HTTPException(400, "tenant scope missing")

    s_iso, e_iso = _iso_day_bounds(start_date, end_date)
    inactive, ltv_by_cid, last_service = await _attrition_rows(
        tid, s_iso, e_iso,
    )

    # Denominator for the attrition rate — customers created strictly
    # BEFORE the window (i.e., the "at-risk" population). Excludes
    # soft-deleted rows so the rate doesn't drift on cleanup.
    denom_q = {
        "tenant_id": tid,
        "$or": [{"deleted_at": None},
                  {"deleted_at": {"$exists": False}}],
        "$and": [
            {"$or": [{"created_at": {"$lt": s_iso}},
                       {"created_at": {"$exists": False}}]},
        ],
    }
    total_at_risk = await db.customers.count_documents(denom_q)

    rows_out: List[dict] = []
    ltv_sum = 0.0
    for c in inactive:
        cid = c.get("id")
        ltv = round(float(ltv_by_cid.get(cid, 0.0)), 2)
        reason = (c.get("muted_reason") or "").strip() or "not_specified"
        name = (c.get("name")
                 or " ".join([c.get("first_name") or "",
                                c.get("last_name") or ""]).strip()
                 or "—")
        rows_out.append({
            "customer_id": cid,
            "customer_name": name,
            "became_inactive_at": c.get("_became_inactive_at"),
            "inactive_reason": reason,
            "lifetime_value": ltv,
            "last_service_date": last_service.get(cid),
        })
        ltv_sum += ltv

    total = len(rows_out)
    avg_ltv = round(ltv_sum / total, 2) if total else 0.0
    rate = round((total / total_at_risk) * 100, 1) if total_at_risk else 0.0
    reason_counts = dict(Counter(r["inactive_reason"] for r in rows_out))

    logger.info(
        "[reports.attrition] tenant=%s window=%s→%s total=%s at_risk=%s",
        tid, start_date, end_date, total, total_at_risk,
    )
    return {
        "summary": {
            "total_attrited":       total,
            "attrition_rate_pct":   rate,
            "avg_ltv_of_attrited":  avg_ltv,
        },
        "rows":   rows_out,
        "chart":  {"reason_counts": reason_counts},
        "tenant_id":  tid,
        "start_date": start_date,
        "end_date":   end_date,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
