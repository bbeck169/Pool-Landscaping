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
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from config import db
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


def _require_landscaping(user: dict) -> None:
    """Phase 45.3 / 56.3.B follow-up — gate for the Landscape Time Clock.

    Allowed callers:
      • admin / super_admin  (any department, including "both")
      • technicians with ``department`` in ``_LANDSCAPE_DEPTS``
        (``landscaping``, ``landscape_tech``, ``landscaper``, ``both``)

    Pool techs, customers, and unassigned techs → 403.

    Feb-2026 · Phase 4 follow-up — this tech-allow tuple is sourced
    from the module-level ``_LANDSCAPE_DEPTS`` constant (defined
    below) so it stays in lock-step with the admin-summary user
    filter at ``admin_summary``'s MongoDB query. Previously this
    guard only accepted ``("landscaping", "both")`` which 403'd
    cross-trained techs whose ``users.department`` was
    ``"landscape_tech"`` or ``"landscaper"`` even though the mobile
    client's ``LANDSCAPE_DEPTS`` set (and this file's
    ``admin_summary`` aggregation at ~L272/L308) already treated
    those values as landscape-authorized. The forward reference to
    ``_LANDSCAPE_DEPTS`` is intentional — Python resolves module
    names at call time, not def time, and keeping the constant at
    its original location preserves the admin-summary section's
    local-definition convention.
    """
    role = (user.get("role") or "").lower()
    dept = (user.get("department") or "").lower()
    if role in ("admin", "super_admin"):
        return
    if dept in _LANDSCAPE_DEPTS:
        return
    raise HTTPException(
        status_code=403,
        detail={"code": "not_landscaping",
                "msg": "Time Clock is available for landscape-authorized users only."},
    )


def _day_key(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).date().isoformat()


@router.post("/punch")
async def punch(body: PunchIn, user: dict = Depends(get_current_user)):
    _require_landscaping(user)
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
    _require_landscaping(user)
    rows = await db.timeclock_punches.find({
        "tenant_id": user["tenant_id"],
        "user_id": user["id"],
        "timestamp": {"$gte": f"{start}T00:00:00+00:00",
                       "$lte": f"{end}T23:59:59+00:00"},
    }).sort("timestamp", 1).to_list(1000)
    by_day: dict = {}
    for p in rows:
        d = _day_key(datetime.fromisoformat(p["timestamp"]))
        by_day.setdefault(d, []).append(p)
    days = [{"day": d, "seconds": _sum_shifts(ps)} for d, ps in sorted(by_day.items())]
    total = sum(d["seconds"] for d in days)
    return {"days": days, "total_seconds": total,
            "punches": [{k: v for k, v in p.items() if k != "_id"} for p in rows]}


@router.get("/mine-today")
async def today(user: dict = Depends(get_current_user)):
    _require_landscaping(user)
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
    rows = await db.timeclock_punches.find({
        "tenant_id": user["tenant_id"], "user_id": user["id"],
        "timestamp": {"$gte": f"{yesterday}T00:00:00+00:00",
                       "$lte": f"{today}T23:59:59+00:00"},
    }).sort("timestamp", 1).to_list(50)
    open_in = None
    for p in rows:
        if p["punch_type"] == "in": open_in = p
        elif p["punch_type"] == "out" and open_in: open_in = None
    todays_rows = [
        p for p in rows
        if str(p.get("timestamp", "")).startswith(today)
    ]
    return {
        "punches": [{k: v for k, v in p.items() if k != "_id"} for p in todays_rows],
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
    _require_landscaping(user)
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    # Look back to yesterday's midnight so a rollover shift that
    # started at 22:00 and hasn't been closed still surfaces as an
    # open ``in``.  Latest punch wins.
    rows = await db.timeclock_punches.find({
        "tenant_id": user["tenant_id"], "user_id": user["id"],
        "timestamp": {"$gte": f"{yesterday}T00:00:00+00:00",
                       "$lte": f"{today}T23:59:59+00:00"},
        "punch_type": {"$in": ["in", "out"]},
    }, {"_id": 0, "punch_type": 1, "timestamp": 1}).sort("timestamp", 1).to_list(50)
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
    _require_landscaping(user)
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
        rows = await db.timeclock_punches.find(
            {"tenant_id": tenant_id,
             "user_id": tech["id"],
             "timestamp": {
                 "$gte": f"{start_s}T00:00:00+00:00",
                 "$lte": f"{end_s}T23:59:59+00:00",
             }},
            {"_id": 0},
        ).sort("timestamp", 1).to_list(5000)

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
                }
                for p in rows
            ],
        })

    return {
        "range": {"start": start_s, "end": end_s},
        "techs": out,
    }
