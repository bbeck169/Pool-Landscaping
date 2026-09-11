"""Feb-2026 · Reports Gap Fill Phase 5b.1 — Time to Close.

Per-lead cycle-time analysis. Mirrors the Time to Get Paid
pattern verbatim — same ``_iso_day_bounds`` / ``_parse_dt`` /
``_percentile`` helpers, just pointed at ``db.leads`` instead of
``db.quotes``.

Contract:
    GET /api/reports/time-to-close?start_date&end_date

    → {
        "summary": {"avg_days_to_close", "p50_days", "p90_days",
                     "leads_counted"},
        "rows": [
            {"lead_id", "customer_id", "customer_name",
             "created_at", "closed_at", "days_to_close", "outcome"}
        ],
        "chart": {"monthly_avg_days":
            [{"month", "avg_days"}]},
        "tenant_id", "start_date", "end_date", "computed_at"
      }

Only leads with BOTH ``created_at`` AND ``closed_at`` set AND
``closed_at >= created_at`` count. Skip anything else.
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


def _norm_status(s: Any) -> str:
    if not s:
        return ""
    return str(s).strip().lower().replace(" ", "_")


async def _customer_name_map(tid: str, cids: List[str]) -> Dict[str, str]:
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
    "/reports/time-to-close",
    operation_id="reports.timeToClose",
    summary="Time to Close — days-to-outcome summary + rolling chart",
)
async def time_to_close(
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

    q = {
        "tenant_id": tid,
        "closed_at": {"$gte": min(s_iso, t12_floor_iso)},
        "$or": [{"deleted_at": None},
                  {"deleted_at": {"$exists": False}}],
    }
    leads = await db.leads.find(
        q,
        {"_id": 0, "id": 1, "customer_id": 1, "status": 1,
         "created_at": 1, "closed_at": 1},
    ).to_list(20000)

    windowed_deltas: List[float] = []
    windowed_rows: List[dict] = []
    monthly_bucket: Dict[str, List[float]] = defaultdict(list)

    for L in leads:
        created_dt = _parse_dt(L.get("created_at"))
        closed_dt = _parse_dt(L.get("closed_at"))
        if not created_dt or not closed_dt:
            continue
        delta = (closed_dt - created_dt).total_seconds() / 86400.0
        if delta < 0:
            continue
        days = round(delta, 2)
        closed_iso = closed_dt.isoformat()

        status = _norm_status(L.get("status"))
        # Only count leads that actually closed (won or lost). An
        # ``closed_at`` set on a still-open row would be data drift;
        # exclude to avoid inflating counts.
        if status not in ("closed_won", "closed_lost"):
            continue
        outcome = "won" if status == "closed_won" else "lost"

        if s_iso <= closed_iso <= e_iso:
            windowed_deltas.append(days)
            windowed_rows.append({
                "lead_id":       L.get("id"),
                "customer_id":   L.get("customer_id"),
                "created_at":    L.get("created_at"),
                "closed_at":     L.get("closed_at"),
                "days_to_close": days,
                "outcome":       outcome,
            })
        if closed_iso >= t12_floor_iso:
            monthly_bucket[closed_dt.strftime("%Y-%m")].append(days)

    # Enrich rows with customer names (best-effort — leads may not
    # have a linked customer yet if they never converted).
    cids = [r["customer_id"] for r in windowed_rows if r.get("customer_id")]
    name_by_cid = await _customer_name_map(tid, cids)
    for r in windowed_rows:
        r["customer_name"] = name_by_cid.get(r.get("customer_id") or "", "—")
    windowed_rows.sort(key=lambda r: r["days_to_close"], reverse=True)

    sorted_deltas = sorted(windowed_deltas)
    n = len(sorted_deltas)
    avg = round(sum(sorted_deltas) / n, 2) if n else 0.0
    p50 = round(_percentile(sorted_deltas, 50), 2)
    p90 = round(_percentile(sorted_deltas, 90), 2)

    chart_rows: List[dict] = []
    for month in sorted(monthly_bucket.keys()):
        vals = monthly_bucket[month]
        chart_rows.append({
            "month":    month,
            "avg_days": round(sum(vals) / len(vals), 2) if vals else 0.0,
        })

    return {
        "summary": {
            "avg_days_to_close": avg,
            "p50_days":          p50,
            "p90_days":          p90,
            "leads_counted":     n,
        },
        "rows":  windowed_rows,
        "chart": {"monthly_avg_days": chart_rows},
        "tenant_id":  tid,
        "start_date": start_date,
        "end_date":   end_date,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
