"""Feb-2026 · Reports Gap Fill Phase 5b.2 — Labor Efficiency.

Per-job budgeted-vs-actual hour ratio. When ``actual_hours == 0``
the row is dropped from BOTH summary and rows to avoid a
division-by-zero AND to keep the truth-first principle: an
un-time-logged job is "insufficient data," not "100% efficient."

Contract:
    GET /api/reports/labor-efficiency?start_date&end_date

    → {
        "summary": {"labor_efficiency_pct", "budgeted_hours",
                     "actual_hours", "jobs_counted"},
        "rows": [
            {"job_id", "customer_id", "customer_name",
             "service_date", "budgeted_hours", "actual_hours",
             "efficiency_pct", "technician_id", "technician_name"}
        ],
        "chart": {"monthly_efficiency":
            [{"month", "efficiency_pct"}]},
        "tenant_id", "start_date", "end_date", "computed_at"
      }

Canonical pins:
* **Collection** — ``db.jobs`` with ``scheduled_date`` in the
  window. Same predicate as the schedule/dispatch surfaces.
* **``budgeted_hours``** — read directly from ``job.budgeted_hours``
  when present. Falls back to ``job.estimated_hours`` or
  ``job.duration_hours``; if none of the three are set the row is
  excluded (truthful empty state, not a fabricated default).
* **``actual_hours``** — read directly from ``job.actual_hours``
  when present. Falls back to ``job.time_entry_hours_total`` (a
  denorm some tenants carry). Rows with ``actual_hours`` missing
  or zero are excluded per spec.
* **Efficiency** — ``budgeted_hours / actual_hours * 100`` per row,
  aggregated by ``sum(budgeted) / sum(actual) * 100`` at the
  summary level to weight by job size (a 20h job carries more
  weight than a 1h job).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
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


def _first_float(row: dict, *keys: str) -> Optional[float]:
    for k in keys:
        v = row.get(k)
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv > 0:
            return fv
    return None


def _short_date(v: Any) -> Optional[str]:
    if not v:
        return None
    if isinstance(v, str):
        return v[:10]
    return None


@router.get(
    "/reports/labor-efficiency",
    operation_id="reports.laborEfficiency",
    summary="Labor Efficiency — budgeted vs. actual hours by job",
)
async def labor_efficiency(
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

    _s_iso, _e_iso = _iso_day_bounds(start_date, end_date)
    s_day = start_date  # YYYY-MM-DD prefix match
    e_day = end_date

    # ``scheduled_date`` is stored variably (bare date OR full ISO)
    # per ``routers/jobs.py:544-570``. Use a regex prefix match on
    # the day portion so both shapes are covered.
    jobs = await db.jobs.find(
        {"tenant_id": tid,
         "scheduled_date": {"$gte": s_day, "$lte": e_day + "T23:59:59Z"},
         "$or": [{"deleted_at": None},
                   {"deleted_at": {"$exists": False}}]},
        {"_id": 0, "id": 1, "customer_id": 1, "scheduled_date": 1,
         "budgeted_hours": 1, "estimated_hours": 1, "duration_hours": 1,
         "actual_hours": 1, "time_entry_hours_total": 1,
         "assigned_tech_ids": 1, "technician_id": 1},
    ).to_list(10000)

    # Batch-load customer names + technician names.
    cids = list({j.get("customer_id") for j in jobs if j.get("customer_id")})
    tech_ids: List[str] = []
    for j in jobs:
        t = j.get("technician_id")
        if t:
            tech_ids.append(t)
        for tt in (j.get("assigned_tech_ids") or [])[:1]:
            tech_ids.append(tt)
    tech_ids = list({t for t in tech_ids if t})

    cust_names: Dict[str, str] = {}
    if cids:
        async for c in db.customers.find(
            {"tenant_id": tid, "id": {"$in": cids}},
            {"_id": 0, "id": 1, "name": 1,
             "first_name": 1, "last_name": 1},
        ):
            cust_names[c["id"]] = (
                c.get("name")
                or " ".join([c.get("first_name") or "",
                              c.get("last_name") or ""]).strip()
                or "—"
            )

    tech_names: Dict[str, str] = {}
    if tech_ids:
        # Technicians live in both ``db.technicians`` and ``db.users``
        # (Phase 34/35 union). Match on either.
        async for t in db.technicians.find(
            {"tenant_id": tid, "id": {"$in": tech_ids}},
            {"_id": 0, "id": 1, "name": 1},
        ):
            tech_names[t["id"]] = t.get("name") or "—"
        async for u in db.users.find(
            {"tenant_id": tid, "id": {"$in": tech_ids}},
            {"_id": 0, "id": 1, "name": 1},
        ):
            tech_names.setdefault(u["id"], u.get("name") or "—")

    per_month: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"budgeted": 0.0, "actual": 0.0},
    )
    rows: List[dict] = []
    total_budgeted = 0.0
    total_actual = 0.0

    for j in jobs:
        budgeted = _first_float(j,
            "budgeted_hours", "estimated_hours", "duration_hours")
        actual = _first_float(j, "actual_hours", "time_entry_hours_total")
        if budgeted is None or actual is None or actual == 0:
            # Truthful "insufficient data" — drop the row rather
            # than fabricate a 100% or an infinity.
            continue
        eff = round((budgeted / actual) * 100, 1)
        sd = _short_date(j.get("scheduled_date"))
        month = (sd or "")[:7]
        per_month[month]["budgeted"] += budgeted
        per_month[month]["actual"] += actual
        total_budgeted += budgeted
        total_actual += actual
        tid_row = (j.get("technician_id")
                    or (j.get("assigned_tech_ids") or [None])[0])
        rows.append({
            "job_id":           j.get("id"),
            "customer_id":      j.get("customer_id"),
            "customer_name":    cust_names.get(j.get("customer_id") or "", "—"),
            "service_date":     sd,
            "budgeted_hours":   round(budgeted, 2),
            "actual_hours":     round(actual, 2),
            "efficiency_pct":   eff,
            "technician_id":    tid_row,
            "technician_name":  tech_names.get(tid_row or "", "—"),
        })

    # Sort by efficiency asc — worst first (actionable ops view).
    rows.sort(key=lambda r: r["efficiency_pct"])

    monthly_chart = []
    for month in sorted(per_month.keys()):
        b = per_month[month]["budgeted"]
        a = per_month[month]["actual"]
        eff = round((b / a) * 100, 1) if a > 0 else 0.0
        monthly_chart.append({"month": month, "efficiency_pct": eff})

    overall = (round((total_budgeted / total_actual) * 100, 1)
               if total_actual > 0 else 0.0)

    return {
        "summary": {
            "labor_efficiency_pct": overall,
            "budgeted_hours":       round(total_budgeted, 2),
            "actual_hours":         round(total_actual, 2),
            "jobs_counted":         len(rows),
        },
        "rows":  rows,
        "chart": {"monthly_efficiency": monthly_chart},
        "tenant_id":  tid,
        "start_date": start_date,
        "end_date":   end_date,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
