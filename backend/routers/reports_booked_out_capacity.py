"""Feb-2026 · Reports Gap Fill Phase 5b.2 — Booked Out / Capacity.

Forward-looking N-week rolling capacity view. **Reuses the exact
same capacity helpers that Business Snapshot uses** — imported
by name from ``routers.reports_business_snapshot``:

* ``_active_technicians_for_tenant(tenant_id)`` — active-tech union
  (technicians + assignable users), deduped by id.
* ``_weekly_hours_for(tech)`` — weekly hours per tech (defaults
  to 40 when unset). Business Snapshot uses this to compute
  ``bh_per_week_capacity``; this report uses the same helper for
  the ``weekly_capacity_hours`` field so both surfaces cannot
  drift.

Contract:
    GET /api/reports/booked-out-capacity?weeks_ahead=N

    → {
        "summary": {"weekly_capacity_hours", "total_booked_hours",
                     "avg_weekly_utilization_pct",
                     "first_available_week"},
        "rows": [
            {"week_start", "week_end", "booked_hours",
             "capacity_hours", "utilization_pct", "jobs_count"}
        ],
        "chart": {"weekly_bookings":
            [{"week_label", "week_start",
              "booked_hours", "capacity_hours"}]},
        "tenant_id", "computed_at"
      }

Data source:
* **Booked hours** — sum of the same
  ``(budgeted_hours | estimated_hours | duration_hours)`` picker
  that the Labor Efficiency report uses (verbatim, ``_first_float``
  imported below) — so the two surfaces bucket the same job
  the same way.

Semantics:
* Weeks are ISO weeks, Monday-anchored (`isocalendar()`).
* ``first_available_week`` is the FIRST week under 80% utilized
  or ``None`` when the schedule is fully-booked throughout the
  ``weeks_ahead`` window (truthful null, per spec).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db, logger  # noqa: F401
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter(tags=["reports"])


# Parity requirement (dispatch spec): reuse Business Snapshot's
# capacity helpers verbatim so the two surfaces cannot drift.
from routers.reports_business_snapshot import (
    _active_technicians_for_tenant,
    _weekly_hours_for,
)
# Parity requirement (5b.2 self-imposed): reuse the Labor
# Efficiency job-hours picker so the two reports bucket the same
# job the same way.
from routers.reports_labor_efficiency import _first_float


_FULL_UTIL_THRESHOLD = 80.0  # first_available_week cutoff (%)


def _iso_week_bounds(d: date) -> tuple[date, date]:
    """Return the Monday..Sunday date range of the ISO week
    containing ``d``."""
    weekday = d.weekday()  # Mon=0 .. Sun=6
    monday = d - timedelta(days=weekday)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _iso_week_label(d: date) -> str:
    """``YYYY-Www`` per ISO 8601."""
    yr, wk, _ = d.isocalendar()
    return f"{yr:04d}-W{wk:02d}"


@router.get(
    "/reports/booked-out-capacity",
    operation_id="reports.bookedOutCapacity",
    summary="Booked Out / Capacity — forward-looking N-week rolling view",
)
async def booked_out_capacity(
    weeks_ahead: int = Query(
        8, ge=1, le=24,
        description="How many weeks ahead to project (default 8, max 24)."),
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

    # Capacity — reuse Business Snapshot helpers.
    active_techs = await _active_technicians_for_tenant(tid)
    weekly_capacity_hours = round(
        sum(_weekly_hours_for(t) for t in active_techs), 2,
    )

    # Rolling window — the CURRENT ISO week plus the next
    # ``weeks_ahead - 1`` weeks (so ``weeks_ahead=8`` covers
    # the current week + 7 more, mirroring how "8 weeks out"
    # is usually reported in ops).
    today = datetime.now(timezone.utc).date()
    week_monday, _ = _iso_week_bounds(today)
    weeks: List[tuple[date, date]] = []
    for i in range(weeks_ahead):
        mon = week_monday + timedelta(weeks=i)
        sun = mon + timedelta(days=6)
        weeks.append((mon, sun))
    window_start_iso = weeks[0][0].isoformat()
    window_end_iso = (weeks[-1][1] + timedelta(days=1)).isoformat()

    # Pull jobs scheduled within the window.
    jobs = await db.jobs.find(
        {"tenant_id": tid,
         "scheduled_date": {"$gte": window_start_iso,
                              "$lt":  window_end_iso},
         "$or": [{"deleted_at": None},
                   {"deleted_at": {"$exists": False}}]},
        {"_id": 0, "id": 1, "scheduled_date": 1,
         "budgeted_hours": 1, "estimated_hours": 1, "duration_hours": 1},
    ).to_list(10000)

    per_week_hours:  Dict[str, float] = defaultdict(float)
    per_week_jobs:   Dict[str, int]   = defaultdict(int)
    for j in jobs:
        sd = j.get("scheduled_date")
        if not isinstance(sd, str) or len(sd) < 10:
            continue
        try:
            d = date.fromisoformat(sd[:10])
        except Exception:
            continue
        mon, _ = _iso_week_bounds(d)
        # Round the job to the correct week bucket.
        key = mon.isoformat()
        hours = _first_float(j,
            "budgeted_hours", "estimated_hours", "duration_hours")
        if hours is None:
            # Job scheduled but no hours estimate — count the job
            # but don't inflate booked hours from thin air.
            per_week_jobs[key] += 1
            continue
        per_week_hours[key] += hours
        per_week_jobs[key] += 1

    rows: List[dict] = []
    chart_bars: List[dict] = []
    total_booked = 0.0
    util_sum = 0.0
    first_available_week: Optional[str] = None
    for i, (mon, sun) in enumerate(weeks):
        key = mon.isoformat()
        booked = round(per_week_hours.get(key, 0.0), 2)
        util = (round((booked / weekly_capacity_hours) * 100, 1)
                if weekly_capacity_hours > 0 else 0.0)
        if first_available_week is None and util < _FULL_UTIL_THRESHOLD:
            first_available_week = _iso_week_label(mon)
        rows.append({
            "week_start":       mon.isoformat(),
            "week_end":         sun.isoformat(),
            "booked_hours":     booked,
            "capacity_hours":   weekly_capacity_hours,
            "utilization_pct":  util,
            "jobs_count":       per_week_jobs.get(key, 0),
        })
        chart_bars.append({
            "week_label":     f"+{i} weeks" if i > 0 else "This week",
            "week_start":     mon.isoformat(),
            "booked_hours":   booked,
            "capacity_hours": weekly_capacity_hours,
        })
        total_booked += booked
        util_sum += util

    avg_util = round(util_sum / weeks_ahead, 1) if weeks_ahead else 0.0

    return {
        "summary": {
            "weekly_capacity_hours":       weekly_capacity_hours,
            "total_booked_hours":          round(total_booked, 2),
            "avg_weekly_utilization_pct":  avg_util,
            "first_available_week":        first_available_week,
        },
        "rows":  rows,
        "chart": {"weekly_bookings": chart_bars},
        "tenant_id":  tid,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
