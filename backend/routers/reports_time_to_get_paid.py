"""Feb-2026 · Reports Gap Fill Phase 5a.1 (Part B) — Time to Get Paid.

Per-invoice cycle-time analysis. For every paid invoice in the
window, compute ``days_to_paid = paid_at - created_at``. Aggregate
into ``avg``, ``p50``, ``p90``, and expose the trailing-12-month
monthly average as a rolling chart independent of the filter.

Contract:

    GET /api/reports/time-to-get-paid?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD

    → {
        "summary": {
            "avg_days_to_paid": float,
            "p50_days":         float,
            "p90_days":         float,
            "invoices_counted": int
        },
        "rows": [
            {"invoice_id", "customer_id", "customer_name",
             "sent_at", "paid_at", "days_to_paid"}
        ],
        "chart": {"monthly_avg_days":
            [{"month": "YYYY-MM", "avg_days": float}, ...]},
        "tenant_id": "<tid>",
        "start_date": "<iso>", "end_date": "<iso>",
        "computed_at": "<iso>"
      }

Canonical data-source pins (see the memo for the "sent_at" note):

* **Collection** — ``db.quotes`` with ``doc_type="invoice"`` and
  ``payment_status="paid"`` (Phase 11 unified — this is what
  ``routers.analytics.churn_risk`` reads at L172-192 and what
  ``routers.finances`` writes to on invoice send).
* **sent_at proxy** — the invoice's ``created_at``. The unified
  invoice schema does NOT reliably stamp a distinct ``sent_at``
  field (``routers/estimator.py`` stamps it on *estimates*, not
  invoices, and ``routers/finances.py`` bumps status to "sent"
  without persisting a timestamp on the invoice doc). This mirrors
  ``analytics.churn_risk`` L177-183 which also uses ``created_at``
  as the invoice-issuance floor. Documented in the memo.
* **Delta validity** — only invoices with BOTH timestamps AND a
  non-negative delta are counted. Negatives and NULLs are dropped
  (matches the spec: "do not compute against partials").

Tenant-scoped by default; ``tenant_id`` override is super_admin only.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db, logger
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
            status_code=400,
            detail="start_date and end_date must be YYYY-MM-DD",
        )
    if e < s:
        raise HTTPException(400, "end_date must be >= start_date")
    return s.isoformat(), e.isoformat()


def _parse_dt(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _percentile(sorted_vals: List[float], pct: float) -> float:
    """Nearest-rank percentile (matches Excel PERCENTILE.INC to
    within rounding for the small samples we surface). Returns 0.0
    when the input is empty."""
    if not sorted_vals:
        return 0.0
    if pct <= 0:
        return float(sorted_vals[0])
    if pct >= 100:
        return float(sorted_vals[-1])
    k = (len(sorted_vals) - 1) * (pct / 100)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return float(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac)


async def _customer_name_map(tid: str, cids: List[str]) -> Dict[str, str]:
    """Batch-load customer names for the row-table. Names outside
    the referenced set are ignored — no scan-all."""
    if not cids:
        return {}
    out: Dict[str, str] = {}
    cursor = db.customers.find(
        {"tenant_id": tid, "id": {"$in": list(set(cids))}},
        {"_id": 0, "id": 1, "name": 1, "first_name": 1, "last_name": 1},
    )
    async for c in cursor:
        nm = (c.get("name")
              or " ".join([c.get("first_name") or "",
                             c.get("last_name") or ""]).strip()
              or "—")
        out[c["id"]] = nm
    return out


@router.get(
    "/reports/time-to-get-paid",
    operation_id="reports.timeToGetPaid",
    summary="Time to Get Paid — days-to-paid summary + rows + rolling chart",
)
async def time_to_get_paid(
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

    # Trailing-12-month floor for the rolling chart (independent
    # of the filter — the spec calls this out explicitly).
    now = datetime.now(timezone.utc)
    t12_floor = (now - timedelta(days=365)).isoformat()

    # Pull once — covers both the windowed summary/rows AND the
    # rolling chart. Cheaper than two round-trips.
    q = {
        "tenant_id": tid, "doc_type": "invoice",
        "payment_status": "paid",
        # ``paid_at`` bounds the union: we need everything paid
        # within the window OR within the trailing 12 months. The
        # trailing floor is always earlier than the window's start
        # in typical usage, so ``>= min(s_iso, t12_floor)`` is a
        # safe lower bound.
        "paid_at": {"$gte": min(s_iso, t12_floor)},
    }
    invoices = await db.quotes.find(
        q,
        {"_id": 0, "id": 1, "customer_id": 1, "created_at": 1,
         "paid_at": 1, "sent_at": 1, "total": 1},
    ).to_list(10000)

    # Compute deltas + partition into "windowed" vs "rolling".
    windowed_deltas: List[float] = []
    windowed_rows: List[dict] = []
    monthly_bucket: Dict[str, List[float]] = defaultdict(list)

    for inv in invoices:
        # ``sent_at`` is best-effort; fall back to ``created_at``.
        sent_dt = _parse_dt(inv.get("sent_at")) or _parse_dt(inv.get("created_at"))
        paid_dt = _parse_dt(inv.get("paid_at"))
        if not sent_dt or not paid_dt:
            continue
        delta_days = (paid_dt - sent_dt).total_seconds() / 86400.0
        if delta_days < 0:
            continue
        days = round(delta_days, 2)
        paid_iso = paid_dt.isoformat()

        if s_iso <= paid_iso <= e_iso:
            windowed_deltas.append(days)
            windowed_rows.append({
                "invoice_id":    inv.get("id"),
                "customer_id":   inv.get("customer_id"),
                "sent_at":       (inv.get("sent_at")
                                     or inv.get("created_at")),
                "paid_at":       inv.get("paid_at"),
                "days_to_paid":  days,
            })
        if paid_iso >= t12_floor:
            monthly_bucket[paid_dt.strftime("%Y-%m")].append(days)

    # Enrich rows with customer names.
    cids = [r["customer_id"] for r in windowed_rows if r.get("customer_id")]
    name_by_cid = await _customer_name_map(tid, cids)
    for r in windowed_rows:
        r["customer_name"] = name_by_cid.get(r.get("customer_id") or "", "—")
    windowed_rows.sort(key=lambda r: r["days_to_paid"], reverse=True)

    sorted_deltas = sorted(windowed_deltas)
    n = len(sorted_deltas)
    avg = round(sum(sorted_deltas) / n, 2) if n else 0.0
    p50 = round(_percentile(sorted_deltas, 50), 2)
    p90 = round(_percentile(sorted_deltas, 90), 2)

    # Rolling chart — sorted month-ascending so the FE line chart
    # can render it directly.
    chart_rows: List[dict] = []
    for month in sorted(monthly_bucket.keys()):
        vals = monthly_bucket[month]
        chart_rows.append({
            "month":    month,
            "avg_days": round(sum(vals) / len(vals), 2) if vals else 0.0,
        })

    logger.info(
        "[reports.time-to-get-paid] tenant=%s window=%s→%s n=%s avg=%s",
        tid, start_date, end_date, n, avg,
    )
    return {
        "summary": {
            "avg_days_to_paid": avg,
            "p50_days":         p50,
            "p90_days":         p90,
            "invoices_counted": n,
        },
        "rows":  windowed_rows,
        "chart": {"monthly_avg_days": chart_rows},
        "tenant_id":  tid,
        "start_date": start_date,
        "end_date":   end_date,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
