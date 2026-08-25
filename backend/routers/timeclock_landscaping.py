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
      • technicians with department = "landscaping" or "both"

    Pool techs, customers, and unassigned techs → 403.
    """
    role = (user.get("role") or "").lower()
    dept = (user.get("department") or "").lower()
    if role in ("admin", "super_admin"):
        return
    if dept in ("landscaping", "both"):
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
    rows = await db.timeclock_punches.find({
        "tenant_id": user["tenant_id"], "user_id": user["id"],
        "timestamp": {"$gte": f"{today}T00:00:00+00:00",
                       "$lte": f"{today}T23:59:59+00:00"},
    }).sort("timestamp", 1).to_list(50)
    open_in = None
    for p in rows:
        if p["punch_type"] == "in": open_in = p
        elif p["punch_type"] == "out" and open_in: open_in = None
    return {
        "punches": [{k: v for k, v in p.items() if k != "_id"} for p in rows],
        "seconds": _sum_shifts(rows),
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
    gate entirely for roles it doesn't apply to."""
    _require_landscaping(user)
    today = date.today().isoformat()
    rows = await db.timeclock_punches.find({
        "tenant_id": user["tenant_id"], "user_id": user["id"],
        "timestamp": {"$gte": f"{today}T00:00:00+00:00",
                       "$lte": f"{today}T23:59:59+00:00"},
        "punch_type": {"$in": ["in", "out"]},
    }, {"_id": 0, "punch_type": 1, "timestamp": 1}).sort("timestamp", 1).to_list(50)
    open_in = False
    for p in rows:
        if p["punch_type"] == "in":
            open_in = True
        elif p["punch_type"] == "out":
            open_in = False
    return {"clocked_in": open_in, "punch_count": len(rows)}


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
