"""Phase 45 · Task 3 — Time Clock (landscaping-only) with GPS punches.

Endpoints:
    POST /api/timeclock/punch
    GET  /api/timeclock/summary?start=&end=
    GET  /api/timeclock/today

Schema (`timeclock_punches`):
    {tenant_id, user_id, punch_type: "in"|"out", timestamp,
     lat, lng, accuracy_m, source: "mobile"|"web", geo_denied: bool}

Rules:
- Only users with `department == "landscaping"` may punch. Others → 403.
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


def _require_landscaping(user: dict) -> None:
    """Gate: only landscaping techs (per user `department` field)."""
    dept = (user.get("department") or "").lower()
    if dept != "landscaping":
        raise HTTPException(
            status_code=403,
            detail={"code": "not_landscaping",
                    "msg": "Time Clock is available for landscaping techs only."},
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
    }
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


@router.get("/summary")
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


@router.get("/today")
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
    }
