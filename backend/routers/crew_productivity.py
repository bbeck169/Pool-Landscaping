"""Phase H5 · Feb-2026 — Crew productivity endpoint.

Weekly / monthly revenue-per-crew aggregation for the admin
dashboard tile. Uses the F6a job-attribution semantic:

    (job.crew_id == crew.id) OR (job.technician_id ∈ crew.tech_ids)

so an ad-hoc tech-only assignment to a crew member still counts
toward that crew's revenue. Revenue is sourced from the F7
``job.job_totals.subtotal`` denorm (already stamped by the
line-items writeback path).

The endpoint is admin-tier only (mirrors the existing
``reports/revenue-by-crew`` gate) and always tenant-scoped.

Non-goals (per H5 brief):
    * no schema changes
    * no auto-poll / real-time updates
    * no mobile parity in this phase
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from utils import require_admin
from routers.tenants import get_current_tenant

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

router = APIRouter()


# ─── Time-range resolver ──────────────────────────────────────────────
_RANGE_VALUES = ("this_week", "last_week", "this_month")


def _tenant_tz(tenant: Dict[str, Any]):
    """Mirror the ``services.route_reassign._tenant_tz`` helper so the
    Phase D drift-alert tz behavior stays consistent across surfaces."""
    tz_name = tenant.get("timezone") or "America/Phoenix"
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("America/Phoenix")


def _resolve_range(range_key: str, tenant: Dict[str, Any]) -> tuple[datetime, datetime]:
    """Return ``(start_utc, end_utc)`` for the requested window.

    * ``this_week`` → Monday 00:00:00 → next Monday 00:00:00 (tenant-local)
    * ``last_week`` → previous Mon → this Mon (tenant-local)
    * ``this_month`` → 1st 00:00:00 → next month 1st 00:00:00
    Both bounds are exclusive on the high side so the SQL/Mongo
    ``$gte start AND $lt end`` window is a natural half-open range.
    """
    tz = _tenant_tz(tenant)
    now_local = datetime.now(tz)
    if range_key == "this_month":
        start_local = now_local.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0,
        )
        # First day of next month.
        if start_local.month == 12:
            end_local = start_local.replace(
                year=start_local.year + 1, month=1,
            )
        else:
            end_local = start_local.replace(month=start_local.month + 1)
    else:
        # weekday(): Mon=0 … Sun=6.  This week's Monday-midnight.
        this_week_mon_local = (
            now_local
            - timedelta(days=now_local.weekday())
        ).replace(hour=0, minute=0, second=0, microsecond=0)
        if range_key == "last_week":
            start_local = this_week_mon_local - timedelta(days=7)
            end_local = this_week_mon_local
        else:  # this_week
            start_local = this_week_mon_local
            end_local = this_week_mon_local + timedelta(days=7)
    return (start_local.astimezone(timezone.utc),
            end_local.astimezone(timezone.utc))


# ─── Revenue attribution helpers ──────────────────────────────────────
def _job_revenue(job: Dict[str, Any]) -> float:
    """Extract the F7 subtotal denorm. Fallback to 0 when the field
    is absent — a completed job with no line-items is legal (rare,
    but seen in production for pre-F7 legacy rows). Never negative."""
    totals = job.get("job_totals") or {}
    sub = totals.get("subtotal")
    try:
        v = float(sub or 0)
    except (TypeError, ValueError):
        return 0.0
    return v if v > 0 else 0.0


def _job_completion_datetime(job: Dict[str, Any]) -> Optional[datetime]:
    """Prefer ``completed_at`` (stamped on status flip). Fall back to
    ``scheduled_date`` for legacy rows that flipped to ``completed``
    before the ``completed_at`` denorm shipped."""
    raw = job.get("completed_at") or job.get("scheduled_date")
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    # ISO parse — accept both ``YYYY-MM-DD`` and full ISO datetimes.
    try:
        s = str(raw)
        # ``fromisoformat`` in Py3.11 handles Z-suffix natively via
        # a small massage; be safe about a trailing Z.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


# ─── Endpoint ─────────────────────────────────────────────────────────
@router.get("/admin/crew-productivity")
async def crew_productivity(
    range: str = Query(  # noqa: A002 — shadowing ``range`` is safe here
        "this_week",
        description=(
            "Time window. One of: ``this_week`` (default — Monday "
            "00:00 tenant-local through next Monday 00:00), "
            "``last_week``, ``this_month``. Unknown values 400 with "
            "``invalid_range``."
        ),
    ),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Return per-crew revenue + jobs-completed for the given window.

    Response shape is locked by tests in
    ``tests/test_crew_productivity.py``. Rows sorted by
    ``revenue_subtotal`` DESC; ties broken by ``crew_name`` ASC so
    the display is deterministic even with zero-revenue crews.
    """
    if range not in _RANGE_VALUES:
        raise HTTPException(
            400,
            {"detail": "invalid_range",
             "range": range,
             "allowed": list(_RANGE_VALUES)},
        )
    tid = tenant["id"]
    start_utc, end_utc = _resolve_range(range, tenant)

    # 1) Enumerate crews for the tenant.
    crews_raw = await db.crews.find(
        {"tenant_id": tid},
        {"_id": 0, "id": 1, "name": 1, "color": 1, "tech_ids": 1},
    ).sort("name", 1).to_list(500)

    # 2) Fetch every terminally-completed job in the tenant for the
    # window ONCE.  Attribute in-memory so we don't fan out N queries
    # (crew count × jobs count). Windows are small (weekly = ~hundreds
    # of jobs per tenant), so this is cheap and predictable.
    #
    # We over-select by fetching ALL completed jobs and filtering the
    # date window in-process because ``completed_at`` is a legacy-
    # inconsistent field: some rows store an ISO datetime, others a
    # bare ``YYYY-MM-DD`` on ``scheduled_date``.  Doing the parse in
    # Python guarantees a single, tested source of truth for the
    # bucket boundaries.
    completed_jobs = await db.jobs.find(
        {"tenant_id": tid, "status": "completed"},
        {"_id": 0, "id": 1, "crew_id": 1, "technician_id": 1,
         "job_totals": 1, "completed_at": 1, "scheduled_date": 1},
    ).to_list(20000)

    windowed: List[Dict[str, Any]] = []
    for j in completed_jobs:
        dt = _job_completion_datetime(j)
        if dt is None:
            continue
        if start_utc <= dt < end_utc:
            windowed.append(j)

    # 3) Attribute each windowed job to a crew (F6a semantic).  A
    # single job can only count under one crew — we prefer an explicit
    # ``crew_id`` match; otherwise the first crew whose ``tech_ids``
    # contains the ``technician_id``. Deterministic (crew list is
    # sorted by name), which the tenant-scoping test guards.
    crew_rows: List[Dict[str, Any]] = []
    totals_jobs = 0
    totals_rev = 0.0
    for crew in crews_raw:
        cid = crew.get("id")
        tech_ids = set(crew.get("tech_ids") or [])
        member_count = len(tech_ids)
        crew_jobs = 0
        crew_rev = 0.0
        for j in windowed:
            attributed = False
            if cid and j.get("crew_id") == cid:
                attributed = True
            elif tech_ids and j.get("technician_id") in tech_ids and not j.get("crew_id"):
                # Only fall back to tech attribution when the job has
                # no explicit crew_id — otherwise a job assigned to
                # crew A whose tech also belongs to crew B would
                # double-count.
                attributed = True
            if not attributed:
                continue
            crew_jobs += 1
            crew_rev += _job_revenue(j)
        avg = round(crew_rev / crew_jobs, 2) if crew_jobs else 0.0
        crew_rows.append({
            "crew_id": cid,
            "crew_name": crew.get("name") or "Unnamed crew",
            "color": crew.get("color") or "#0284C7",
            "member_count": member_count,
            "jobs_completed": crew_jobs,
            "revenue_subtotal": round(crew_rev, 2),
            "revenue_currency": "USD",
            "avg_job_value": avg,
        })
        totals_jobs += crew_jobs
        totals_rev += crew_rev

    crew_rows.sort(
        key=lambda r: (-r["revenue_subtotal"], r["crew_name"] or ""),
    )
    return {
        "tenant_id": tid,
        "range": range,
        "range_start": start_utc.isoformat(),
        "range_end": end_utc.isoformat(),
        "crews": crew_rows,
        "totals": {
            "jobs_completed": totals_jobs,
            "revenue_subtotal": round(totals_rev, 2),
        },
    }
