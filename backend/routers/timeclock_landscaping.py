"""Phase 45 · Task 3 — Time Clock (landscaping-only) with GPS punches.

Endpoints:
    POST /api/timeclock/punch
    GET  /api/timeclock/mine-summary?start=&end=
    GET  /api/timeclock/mine-today

Note: the `/timeclock/today` route in `routers/ops.py` is a tenant-wide
admin overview; these `mine-*` routes are the personal per-user endpoints
used by the landscaping time-clock UI.

Schema (`timeclock_punches`):
    {tenant_id, user_id, punch_type: "in"|"out", timestamp,
     lat, lng, accuracy_m, source: "mobile"|"web", geo_denied: bool}

Rules:
- Users with `department in ("landscaping", "both")` may punch — cross-
  trained techs included. Admins / super-admins always pass. All other
  callers (pool-only techs, customers, unassigned techs) → 403.
- Single open shift per user per day; a second `in` without an `out`
  returns 409 (`already_clocked_in`).
- Punching `out` without a matching `in` returns 409 (`no_open_shift`).
- GPS may be null when the device denies permission; we still record
  the punch but flag `geo_denied: true`.
"""
from datetime import datetime, timezone, date, timedelta
from typing import Any, Literal, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from config import db, logger
from utils import now_iso, new_id, get_current_user

router = APIRouter(prefix="/timeclock", tags=["timeclock"])


class PunchIn(BaseModel):
    punch_type: Literal["in", "out"]
    lat: Optional[float] = None
    lng: Optional[float] = None
    accuracy_m: Optional[float] = None
    source: Literal["mobile", "web"] = "mobile"
    geo_denied: bool = False
    # Phase 50.H — landscapers may attribute a shift to a specific job so
    # `GET /api/jobs/{id}/costing` can bucket labor cost precisely.
    # Optional; falls back to un-attributed "general work" when null.
    job_id: Optional[str] = None


def _dept_matches_landscape(dept_val: Any) -> bool:
    """Normalize + membership-check against ``_LANDSCAPE_DEPTS``.
    Shared so the dual-source read below stays symmetric."""
    s = (dept_val or "")
    if not isinstance(s, str):
        return False
    return s.strip().lower() in _LANDSCAPE_DEPTS


async def _resolve_tech_department(user: dict) -> Optional[str]:
    """Feb-2026 landscaping-tech clock-in regression fix.

    The admin team-roster UI (``routers/team.py::create_team_user``
    + the sibling edit route) writes ``department`` to the
    ``db.users`` row.  But a sibling admin flow — the
    ``POST /api/technicians/{id}/attributes`` + legacy mobile
    tech-onboarding writes — stores the department on the
    ``db.technicians`` row.  Preview-DB evidence (`47/50` users
    with ``department=None`` while a few ``db.technicians`` rows
    carry a canonical ``"landscaping"`` value) confirms the two
    collections aren't guaranteed to stay in sync.  This helper
    reads from both sources and returns the first non-empty
    value so a legitimate landscaping tech whose ``db.users.
    department`` was never populated can still clock in.

    Order of precedence — ``db.users`` wins when populated so
    super_admin edits via the roster UI take effect immediately
    without a cross-collection sync.
    """
    u_dept = (user.get("department") or "").strip()
    if u_dept:
        return u_dept
    tid = user.get("technician_id")
    if not tid:
        return None
    try:
        tech = await db.technicians.find_one(
            {"id": tid, "tenant_id": user.get("tenant_id")},
            {"_id": 0, "department": 1},
        )
    except Exception:
        return None
    return ((tech or {}).get("department") or "").strip() or None


async def _require_landscaping(user: dict) -> None:
    """Phase 45.3 / 56.3.B follow-up — gate for the Landscape Time Clock.

    Allowed callers:
      • admin / super_admin  (any department, including "both")
      • technicians with ``department`` in ``_LANDSCAPE_DEPTS``
        (``landscaping``, ``landscape_tech``, ``landscaper``, ``both``)
        resolved against EITHER ``db.users.department`` OR, when
        that is null/empty, ``db.technicians.department`` — see
        :func:`_resolve_tech_department` for the dual-source
        rationale.

    Pool techs, customers, and unassigned techs → 403.

    Feb-2026 landscape-tech clock-in regression fix — this guard
    was previously a sync function reading ``user.get("department")``
    only.  Promoting to async + the dual-source fallback closed the
    denormalization gap that silently 403'd legitimate landscaping
    techs whose ``db.users.department`` field was never populated
    by the admin roster UI.  On final 403 we emit a structured
    log line (user_id + resolved department + fallback source) so
    operators can audit any remaining mis-categorized techs
    without diffing collections by hand.
    """
    role = (user.get("role") or "").lower()
    if role in ("admin", "super_admin"):
        return
    resolved_dept = await _resolve_tech_department(user)
    if _dept_matches_landscape(resolved_dept):
        return
    # Telemetry — operator's debug directive #1 ("paste the exact
    # error from server logs"); surfaces which users are being
    # 403'd + which source (if any) carried a department value.
    logger.info(
        "[timeclock-landscaping] 403 not_landscaping · "
        "user_id=%s role=%s users.department=%r "
        "technicians.department=%r resolved=%r",
        user.get("id"), role,
        user.get("department"),
        # Second read is best-effort and would re-hit Mongo — guard
        # it the same way _resolve_tech_department does.
        (await (
            db.technicians.find_one(
                {"id": user.get("technician_id"),
                 "tenant_id": user.get("tenant_id")},
                {"_id": 0, "department": 1},
            )
            if user.get("technician_id") else _noop_tech_find()
        ) or {}).get("department"),
        resolved_dept,
    )
    raise HTTPException(
        status_code=403,
        detail={"code": "not_landscaping",
                "msg": "Time Clock is available for landscape-authorized users only."},
    )


async def _noop_tech_find() -> dict:
    """Shim so the telemetry f-string stays symmetric when the
    user has no ``technician_id``; keeps the log one-liner."""
    return {}


def _day_key(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).date().isoformat()


@router.post("/punch")
async def punch(body: PunchIn, user: dict = Depends(get_current_user)):
    await _require_landscaping(user)
    tenant_id = user["tenant_id"]
    user_id = user["id"]
    ts = datetime.now(timezone.utc)
    today = _day_key(ts)

    # Find today's punches for this user.
    day_start = f"{today}T00:00:00+00:00"
    day_end   = f"{today}T23:59:59+00:00"
    todays = await db.timeclock_punches.find({
        "tenant_id": tenant_id, "user_id": user_id,
        "timestamp": {"$gte": day_start, "$lte": day_end},
    }).sort("timestamp", 1).to_list(50)

    open_in = None
    for p in todays:
        if p["punch_type"] == "in":
            open_in = p
        elif p["punch_type"] == "out" and open_in and open_in["timestamp"] < p["timestamp"]:
            open_in = None

    if body.punch_type == "in" and open_in is not None:
        raise HTTPException(409, detail={"code": "already_clocked_in"})
    if body.punch_type == "out" and open_in is None:
        raise HTTPException(409, detail={"code": "no_open_shift"})

    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "user_id": user_id,
        "punch_type": body.punch_type,
        "timestamp": ts.isoformat(),
        "lat": body.lat,
        "lng": body.lng,
        "accuracy_m": body.accuracy_m,
        "source": body.source,
        "geo_denied": body.geo_denied,
        # Phase 50.H — attach the job so the costing view can pull actual
        # landscape labor into per-job margin. Optional (may be null).
        "job_id": body.job_id,
    }
    # If this is an "out" and the caller didn't specify a job, inherit
    # from the matching open "in" so the paired shift lands on the same
    # job — techs might forget to re-select on clock-out.
    if body.punch_type == "out" and not body.job_id and open_in:
        doc["job_id"] = open_in.get("job_id")
    await db.timeclock_punches.insert_one(doc)
    doc.pop("_id", None)
    return doc


def _flatten_time_entries_to_events(rows: list) -> list:
    """TC · C1 (Feb-2026) — flatten paired ``time_entries`` docs into the
    event-row shape the ``timeclock_punches`` + ``_sum_shifts`` + FE
    ``pairPunches.js`` consumers already speak. Each paired doc emits one
    ``in`` event; if ``clock_out_at`` is non-null a matching ``out``
    event is emitted too.

    This is the normalization half of the TD-landscape-time-clock-unify-
    reads cash-in (see memory/TD-landscape-time-clock-unify-reads.md).
    The FE pairs the merged flat events client-side via
    ``frontend/src/lib/timeclock/pairPunches.js:68-96`` — keeping the
    wire shape flat means the admin aggregation UI stays byte-stable
    after this ticket.
    """
    events: list = []
    for r in rows:
        in_at = r.get("clock_in_at")
        if not in_at:
            continue
        in_geo = r.get("clock_in_geo") or {}
        events.append({
            "id": r.get("id"),
            "tenant_id": r.get("tenant_id"),
            "user_id": r.get("user_id"),
            "timestamp": in_at,
            "punch_type": "in",
            "lat": in_geo.get("lat"),
            "lng": in_geo.get("lng"),
            "accuracy_m": in_geo.get("accuracy"),
            "job_id": r.get("job_id"),
            "source": "time_entries",
        })
        out_at = r.get("clock_out_at")
        if out_at:
            out_geo = r.get("clock_out_geo") or {}
            events.append({
                # Synthesize a distinct id for the OUT event so FE row
                # keys stay unique (the paired doc only carries one id).
                "id": f'{r.get("id")}-out',
                "tenant_id": r.get("tenant_id"),
                "user_id": r.get("user_id"),
                "timestamp": out_at,
                "punch_type": "out",
                "lat": out_geo.get("lat"),
                "lng": out_geo.get("lng"),
                "accuracy_m": None,
                "job_id": r.get("job_id"),
                "source": "time_entries",
            })
    return events


async def _unified_events(tenant_id: str, user_id: str,
                            start_iso: str, end_iso: str) -> list:
    """TC · C1 (Feb-2026) — read both the ``timeclock_punches`` event
    log and the ``time_entries`` paired-shift log for a single tech in
    a time window, flatten + merge + sort by timestamp ascending.
    Preserves tenant isolation. The returned list carries a ``source``
    field (``"time_entries"`` or ``"timeclock_punches"``) so callers +
    admin UIs can attribute each event to its underlying collection.

    Window semantics mirror the pre-TC single-collection behavior:
    each collection is filtered on its own primary-timestamp field
    (``timestamp`` for punches, ``clock_in_at`` for time entries).
    Overnight shifts whose ``clock_in_at`` lands in-window surface
    their matching ``clock_out_at`` even when it rolls past
    ``end_iso``, by design — the pairing then surfaces the full
    shift. The 2-day UTC-rollover scan at ``/mine-today`` is
    preserved on its caller.

    Also logs orphan OUT events (an ``out`` with no preceding open
    ``in`` for the same tech in-window) at ``logger.warning`` level —
    matches the FE pairPunches.js:84 ``console.warn`` precedent so
    admins can spot data-quality issues. Non-fatal.
    """
    tp_rows = await db.timeclock_punches.find(
        {"tenant_id": tenant_id, "user_id": user_id,
         "timestamp": {"$gte": start_iso, "$lte": end_iso}},
        {"_id": 0},
    ).to_list(5000)
    for r in tp_rows:
        # Preserve any pre-existing source (e.g. "mobile", "web");
        # fall back to the collection name as the authoritative tag.
        r["source"] = r.get("source") or "timeclock_punches"

    te_rows = await db.time_entries.find(
        {"tenant_id": tenant_id, "user_id": user_id,
         "clock_in_at": {"$gte": start_iso, "$lte": end_iso}},
        {"_id": 0},
    ).to_list(5000)
    te_events = _flatten_time_entries_to_events(te_rows)

    merged = tp_rows + te_events
    merged.sort(key=lambda e: str(e.get("timestamp") or ""))

    # Orphan-OUT forensics walk. Non-fatal; _sum_shifts naturally skips
    # orphan OUTs during pairing but the warning helps admins notice.
    open_in = None
    for p in merged:
        if p.get("punch_type") == "in":
            open_in = p
        elif p.get("punch_type") == "out":
            if open_in is not None:
                open_in = None
            else:
                logger.warning(
                    "[timeclock] orphan OUT punch user=%s tenant=%s ts=%s source=%s",
                    user_id, tenant_id, p.get("timestamp"), p.get("source"),
                )
    return merged


def _sum_shifts(punches: list) -> int:
    """Sum completed shift durations (seconds). Open shifts ignored."""
    total = 0
    open_in = None
    for p in sorted(punches, key=lambda x: x["timestamp"]):
        if p["punch_type"] == "in":
            open_in = p
        elif p["punch_type"] == "out" and open_in:
            try:
                a = datetime.fromisoformat(open_in["timestamp"])
                b = datetime.fromisoformat(p["timestamp"])
                total += int((b - a).total_seconds())
            except Exception:
                pass
            open_in = None
    return total


@router.get("/mine-summary")
async def summary(start: str = Query(...), end: str = Query(...),
                   user: dict = Depends(get_current_user)):
    await _require_landscaping(user)
    # TC · C1 (Feb-2026) — unified read across ``timeclock_punches``
    # + ``time_entries`` so widget-sourced shifts (which land in
    # ``time_entries`` since TD-timeclock-tech-clock-out-flow) surface
    # alongside page / mobile punches on the per-tech summary.
    rows = await _unified_events(
        tenant_id=user["tenant_id"], user_id=user["id"],
        start_iso=f"{start}T00:00:00+00:00",
        end_iso=f"{end}T23:59:59+00:00",
    )
    by_day: dict = {}
    for p in rows:
        d = _day_key(datetime.fromisoformat(p["timestamp"]))
        by_day.setdefault(d, []).append(p)
    days = [{"day": d, "seconds": _sum_shifts(ps)} for d, ps in sorted(by_day.items())]
    total = sum(d["seconds"] for d in days)
    return {"days": days, "total_seconds": total,
            "punches": rows}


@router.get("/mine-today")
async def today(user: dict = Depends(get_current_user)):
    await _require_landscaping(user)
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    # Feb-2026 · Day-boundary rollover — mirrors the ``/mine-status``
    # fix (line 197 docstring).  Scan ``yesterday → today`` so an
    # unclosed shift that started before UTC midnight still surfaces
    # as the current open punch.  Repro: a Phoenix (UTC-7) tech
    # clocks in at 2 pm local = 21:00 UTC on day N; at 5 pm local
    # UTC rolls to day N+1 and the pre-fix one-day window silently
    # dropped the open punch so ``clocked_in`` flipped to ``False``
    # and the UI rendered the tech as "auto-clocked-out" even
    # though no OUT punch was ever written.
    #
    # Open-shift detection walks the 2-day stream in timestamp
    # order (same state-machine the pre-fix walker used, just
    # over a wider window).  The ``punches`` list + ``seconds``
    # keep today-only semantics so the UI's "today timeline"
    # affordance is unchanged byte-for-byte.
    # TC · C1 (Feb-2026) — unified read across ``timeclock_punches``
    # + ``time_entries`` so a shift opened via the widget / per-job
    # /workforce/clock-in path surfaces here as the current open
    # shift. 2-day scan window preserved (see rationale above).
    rows = await _unified_events(
        tenant_id=user["tenant_id"], user_id=user["id"],
        start_iso=f"{yesterday}T00:00:00+00:00",
        end_iso=f"{today}T23:59:59+00:00",
    )
    open_in = None
    for p in rows:
        if p["punch_type"] == "in": open_in = p
        elif p["punch_type"] == "out" and open_in: open_in = None
    todays_rows = [
        p for p in rows
        if str(p.get("timestamp", "")).startswith(today)
    ]
    return {
        "punches": todays_rows,
        "seconds": _sum_shifts(todays_rows),
        "clocked_in": open_in is not None,
        "open_job_id": (open_in or {}).get("job_id") if open_in else None,
    }


@router.get("/mine-status")
async def mine_status(user: dict = Depends(get_current_user)):
    """Phase 56.3 follow-up — lightweight clock-in status probe used by
    the job-open gate on the schedule / workstream. Unlike `/mine-today`
    this returns only the boolean, so calendar taps stay snappy.

    Restricted to landscape-authorized users (admins get through
    `_require_landscaping`); everyone else 403s so the UI can skip the
    gate entirely for roles it doesn't apply to.

    Feb-2026 · Day-boundary rollover — an unclosed shift that started
    yesterday and hasn't been clocked out still means the tech is
    ``clocked_in`` today (spec: device-local midnight is a soft
    boundary; the OPEN entry is the source of truth).  We therefore
    scan the last 2 days and use the LATEST punch's type to decide.
    ``in`` → clocked in, ``out`` → clocked out, no punches → false."""
    await _require_landscaping(user)
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    # Look back to yesterday's midnight so a rollover shift that
    # started at 22:00 and hasn't been closed still surfaces as an
    # open ``in``.  Latest punch wins.
    # TC · C1 (Feb-2026) — unified read across ``timeclock_punches``
    # + ``time_entries`` so a widget-opened shift is correctly
    # reflected as ``clocked_in: true``. ``latest-wins`` semantics
    # preserved from the pre-TC implementation.
    rows = await _unified_events(
        tenant_id=user["tenant_id"], user_id=user["id"],
        start_iso=f"{yesterday}T00:00:00+00:00",
        end_iso=f"{today}T23:59:59+00:00",
    )
    rows = [p for p in rows if p.get("punch_type") in ("in", "out")]
    latest_type = rows[-1]["punch_type"] if rows else None
    open_in = (latest_type == "in")
    # ``punch_count`` reports TODAY's activity only so the existing
    # UI copy ("N punches today") stays semantically accurate.
    todays_only = [
        p for p in rows
        if str(p.get("timestamp", "")).startswith(today)
    ]
    return {"clocked_in": open_in, "punch_count": len(todays_only)}


# ── Phase 50.H · Assigned jobs picker for the top-of-page widget ──────
@router.get("/mine-jobs-today")
async def my_jobs_today(user: dict = Depends(get_current_user)):
    """List today's scheduled jobs for this landscape tech so the
    clock-in widget can attach a job to the shift."""
    await _require_landscaping(user)
    today = date.today().isoformat()
    # Match either `technician_id == user.id` (rare) or the user's
    # `technician_id` field (canonical after Phase 15D).
    tech_link = user.get("technician_id") or user["id"]
    # scheduled_date is stored either as a bare "YYYY-MM-DD" or a full
    # ISO datetime string. Match both via a `startswith` regex.
    from utils import not_deleted_filter as _nd
    cur = db.jobs.find(
        {"tenant_id": user["tenant_id"],
         "technician_id": {"$in": [tech_link, user["id"]]},
         "scheduled_date": {"$regex": f"^{today}"},
         **_nd()},
        {"_id": 0, "id": 1, "title": 1, "customer_name": 1,
         "service_type": 1, "scheduled_start": 1, "status": 1},
    ).sort("scheduled_start", 1)
    items = await cur.to_list(50)
    return {"items": items, "count": len(items)}


# ── Phase 4-landscape · Feb-2026 · Admin aggregation ─────────────
_LANDSCAPE_DEPTS = ("landscaping", "landscape_tech", "landscaper", "both")

# Phase 31 — hide designated landscape test accounts from the Team
# Aggregation UI without affecting their user records, auth, seed data,
# or `test_credentials.md`. These users still exist, still log in, and
# still accrue data elsewhere — they just don't surface in the
# ``admin_summary`` payroll table. Scoped by email (stable unique id)
# rather than name or user_id. ``frozenset`` for immutability; converted
# to ``list`` for the MongoDB ``$nin`` operator at query time.
_AGGREGATION_HIDE_EMAILS = frozenset({
    "carlos@aquaterra.com",
    "luis@aquaterra.com",
})


@router.get("/admin-summary")
async def admin_summary(start: Optional[str] = Query(None),
                        end: Optional[str] = Query(None),
                        user: dict = Depends(get_current_user)):
    role = (user.get("role") or "").lower()
    if role not in ("admin", "super_admin", "owner", "manager"):
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden",
                    "msg": "admin-only endpoint"},
        )
    today_d = date.today()
    monday = today_d - timedelta(days=today_d.weekday())
    sunday = monday + timedelta(days=6)
    start_s = start or monday.isoformat()
    end_s = end or sunday.isoformat()

    tenant_id = user["tenant_id"]
    techs_cur = db.users.find(
        {"tenant_id": tenant_id,
         "role": "technician",
         "department": {"$in": list(_LANDSCAPE_DEPTS)},
         "email": {"$nin": list(_AGGREGATION_HIDE_EMAILS)}},
        {"_id": 0, "id": 1, "name": 1, "email": 1},
    ).sort("name", 1)
    techs = await techs_cur.to_list(1000)

    out = []
    for tech in techs:
        # TC · C1 (Feb-2026) — unified read across ``timeclock_punches``
        # + ``time_entries`` so widget-sourced shifts (which land in
        # ``time_entries`` since TD-timeclock-tech-clock-out-flow)
        # surface on the admin team-aggregation payroll table.
        rows = await _unified_events(
            tenant_id=tenant_id, user_id=tech["id"],
            start_iso=f"{start_s}T00:00:00+00:00",
            end_iso=f"{end_s}T23:59:59+00:00",
        )

        total_seconds = _sum_shifts(rows)
        last = rows[-1] if rows else None
        status = ("in" if last and last.get("punch_type") == "in"
                   else "out")
        out.append({
            "user_id": tech["id"],
            "name": tech.get("name") or tech.get("email") or tech["id"],
            "status": status,
            "total_seconds": total_seconds,
            "last_punch": (
                {
                    "ts": last.get("timestamp"),
                    "lat": last.get("lat"),
                    "lng": last.get("lng"),
                    "punch_type": last.get("punch_type"),
                    # TC · C1 — expose source attribution so the admin UI
                    # can show which collection the shift came from.
                    "source": last.get("source"),
                } if last else None
            ),
            "punches": [
                {
                    "id": p.get("id"),
                    "ts": p.get("timestamp"),
                    "lat": p.get("lat"),
                    "lng": p.get("lng"),
                    "punch_type": p.get("punch_type"),
                    "job_id": p.get("job_id"),
                    # TC · C1 — additive per-event source tag; FE's
                    # pairPunches.js ignores unknown fields.
                    "source": p.get("source"),
                }
                for p in rows
            ],
        })

    return {
        "range": {"start": start_s, "end": end_s},
        "techs": out,
    }
