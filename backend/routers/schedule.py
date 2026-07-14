"""Phase 16C — Tech Today Schedule endpoint.

Returns a chronologically ordered list of items for *the current user, today*:
  - jobs assigned to them scheduled for today
  - time_entries (shifts) they opened today (from Phase 16A)
  - break intervals inside those shifts

Also emits `route_legs` between consecutive jobs so the client can hydrate
driving time/distance via the Google Distance Matrix JS API. If a
`distance_matrix_cache` entry already exists for a leg, we hydrate it
server-side so the client can skip the Distance Matrix call.

Endpoints (all tenant-scoped)
-----------------------------
* GET  /api/schedule/today
* POST /api/schedule/route-leg    (client-provided distance/duration cache write)
"""
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from config import db
from utils import now_iso, get_current_user
from routers.tenants import get_current_tenant

router = APIRouter()


DEFAULT_TZ = "America/Phoenix"  # AquaTerra HQ, no DST → consistent


def _today_bounds_utc(tz_name: str) -> tuple:
    """Return (start_iso, end_iso) UTC ISO strings covering *today* in the given tz.
    Simplified: Phoenix is UTC-7 year-round (no DST), sunbelt tenant is same.
    For other zones we still bucket by UTC midnight — good enough for the
    schedule endpoint. Client renders in local tz."""
    # Anchor "today" to UTC midnight, expand ±14h to safely catch jobs
    # scheduled in the tenant local day even for East-Coast tenants. The
    # client filters again by local tz when rendering.
    now = datetime.now(timezone.utc)
    start = (now - timedelta(hours=14)).replace(microsecond=0)
    end = (now + timedelta(hours=14)).replace(microsecond=0)
    return start.isoformat(), end.isoformat()


def _cache_key(from_lat, from_lng, to_lat, to_lng):
    return f"{round(from_lat, 4)},{round(from_lng, 4)}|{round(to_lat, 4)},{round(to_lng, 4)}"


@router.get("/schedule/today")
async def schedule_today(user: dict = Depends(get_current_user),
                         tenant: dict = Depends(get_current_tenant)):
    tid = tenant["id"]
    tz_name = (tenant.get("settings") or {}).get("tz") or DEFAULT_TZ
    start_iso, end_iso = _today_bounds_utc(tz_name)
    today_yyyymmdd = datetime.now(timezone.utc).date().isoformat()

    # Jobs — assigned to *this* user for today. Support several assignment field
    # names the codebase has used historically.
    job_q = {
        "tenant_id": tid,
        "$or": [
            {"assigned_technician_id": user["id"]},
            {"technician_id": user["id"]},
            {"assigned_to": user["id"]},
        ],
        "scheduled_date": {"$gte": start_iso, "$lte": end_iso},
    }
    jobs = await db.jobs.find(job_q, {"_id": 0}).sort("scheduled_date", 1).to_list(200)

    # Time entries + break intervals for *today* (by user).
    entries = await db.time_entries.find(
        {"tenant_id": tid, "user_id": user["id"],
         "clock_in_at": {"$gte": start_iso, "$lte": end_iso}},
        {"_id": 0},
    ).sort("clock_in_at", 1).to_list(50)

    items: list = []
    for j in jobs:
        items.append({
            "type": "job",
            "id": j.get("id"),
            "title": j.get("title") or j.get("service_type") or "Job",
            "customer_name": j.get("customer_name"),
            "customer_id": j.get("customer_id"),
            "address": j.get("address") or j.get("site_address"),
            "lat": j.get("site_lat") or j.get("lat"),
            "lng": j.get("site_lng") or j.get("lng"),
            "scheduled_start": j.get("scheduled_date") or j.get("scheduled_start"),
            "scheduled_end": j.get("scheduled_end"),
            "status": j.get("status"),
            "priority": j.get("priority"),
        })

    for e in entries:
        items.append({
            "type": "shift",
            "entry_id": e.get("id"),
            "job_id": e.get("job_id"),
            "job_title": e.get("job_title"),
            "clock_in_at": e.get("clock_in_at"),
            "clock_out_at": e.get("clock_out_at"),
            "out_of_geofence": bool(e.get("out_of_geofence")),
            "status": e.get("status"),
        })
        for b in (e.get("breaks") or []):
            items.append({
                "type": "break",
                "entry_id": e.get("id"),
                "start": b.get("start"),
                "end": b.get("end"),
            })

    def _sort_key(it):
        k = (it.get("scheduled_start") or it.get("clock_in_at")
             or it.get("start") or "")
        return k or ""
    items.sort(key=_sort_key)

    # Route legs between consecutive jobs with coords
    coord_jobs = [it for it in items if it["type"] == "job"
                                       and it.get("lat") is not None
                                       and it.get("lng") is not None]
    legs = []
    for a, b in zip(coord_jobs, coord_jobs[1:]):
        leg_key = _cache_key(a["lat"], a["lng"], b["lat"], b["lng"])
        cached = await db.distance_matrix_cache.find_one(
            {"key": leg_key}, {"_id": 0}
        )
        legs.append({
            "from_job_id": a["id"],
            "to_job_id": b["id"],
            "from_lat": a["lat"], "from_lng": a["lng"],
            "to_lat": b["lat"], "to_lng": b["lng"],
            "distance_meters": (cached or {}).get("distance_meters"),
            "duration_seconds": (cached or {}).get("duration_seconds"),
            "cached": bool(cached),
        })

    # Summary
    total_hours = sum(
        (e.get("duration_minutes") or 0) for e in entries
    ) / 60.0
    total_miles = sum((e.get("mileage_miles") or 0) for e in entries)
    scheduled_hours = 0.0
    for j in jobs:
        s = j.get("scheduled_date") or j.get("scheduled_start")
        eend = j.get("scheduled_end")
        if s and eend:
            try:
                ds = datetime.fromisoformat(s.replace("Z", "+00:00"))
                de = datetime.fromisoformat(eend.replace("Z", "+00:00"))
                scheduled_hours += max(0, (de - ds).total_seconds() / 3600.0)
            except Exception:
                pass
    open_shift = next((e for e in entries if not e.get("clock_out_at")), None)

    return {
        "date": today_yyyymmdd,
        "tz": tz_name,
        "items": items,
        "route_legs": legs,
        "summary": {
            "job_count": len(coord_jobs) + sum(1 for it in items
                                                if it["type"] == "job"
                                                and (it.get("lat") is None)),
            "scheduled_hours": round(scheduled_hours, 2),
            "hours_logged_today": round(total_hours, 2),
            "miles_logged_today": round(total_miles, 2),
            "clocked_in": bool(open_shift),
            "open_entry_id": open_shift and open_shift.get("id"),
        },
    }


# ─── Route-leg cache write (client posts back after Distance Matrix call) ──
class LegIn(BaseModel):
    from_lat: float
    from_lng: float
    to_lat: float
    to_lng: float
    distance_meters: float
    duration_seconds: float


class RouteLegCacheReq(BaseModel):
    legs: List[LegIn]


@router.post("/schedule/route-leg")
async def cache_route_legs(body: RouteLegCacheReq,
                            user: dict = Depends(get_current_user),
                            tenant: dict = Depends(get_current_tenant)):
    written = 0
    for l in body.legs:
        key = _cache_key(l.from_lat, l.from_lng, l.to_lat, l.to_lng)
        await db.distance_matrix_cache.update_one(
            {"key": key},
            {"$set": {
                "key": key,
                "tenant_id": tenant["id"],   # last-writer tenant for auditing
                "from_lat": l.from_lat, "from_lng": l.from_lng,
                "to_lat": l.to_lat, "to_lng": l.to_lng,
                "distance_meters": l.distance_meters,
                "duration_seconds": l.duration_seconds,
                "updated_at": now_iso(),
                "mode": "driving",
            }},
            upsert=True,
        )
        written += 1
    return {"ok": True, "written": written}
