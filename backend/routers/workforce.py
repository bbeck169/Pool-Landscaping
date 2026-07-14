"""Phase 16A — Workyard-style Workforce Ops.

GPS-based time clock, geofenced job clock-in, mileage tracking, precise job
costing, and a live crew map. All multi-tenant.

Collections
-----------
* `time_entries`    — one row per shift/job clock-in
* `location_pings`  — GPS breadcrumbs while clocked-in (TTL 30d)
* `job_materials`   — materials added to a job (used in cost calc)

Endpoints (all under /api/workforce/*, tenant-scoped)
-----------------------------------------------------
* POST /clock-in                 { job_id, lat, lng, accuracy?, photo_url? }
* POST /clock-out                { entry_id, lat, lng, notes? }
* POST /break/start              { entry_id }
* POST /break/end                { entry_id }
* POST /location-ping            { lat, lng, speed?, heading?, battery?, entry_id? }
* GET  /timesheets               ?user_id=&from=&to=&status=
* POST /timesheets/{id}/approve  (admin)
* POST /timesheets/{id}/reject   (admin)
* GET  /crew-map                 (admin)
* GET  /job-cost/{job_id}
* GET  /mileage                  ?user_id=&from=&to=
* GET  /export/timesheets.csv    ?from=&to=  → StreamingResponse text/csv
"""
import csv
import io
import math
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, get_current_user, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()


# ─── Tenant workforce settings ─────────────────────────────────────────────
DEFAULT_SETTINGS = {
    "geofence_radius_m": 100,
    "mileage_rate_usd": 0.67,
    "overtime_daily_hours": 8,
    "overtime_weekly_hours": 40,
    "require_photo_clock_in": False,
    "ping_min_seconds": 30,       # rate-limit floor
    "mileage_max_speed_mph": 80,  # discard super-fast pings
    "mileage_min_hop_m": 25,      # ignore tiny jitter
}


def _settings(tenant: dict) -> dict:
    """Merge tenant.settings.workforce onto defaults."""
    override = (tenant.get("settings") or {}).get("workforce") or {}
    return {**DEFAULT_SETTINGS, **override}


# ─── Geo helpers ───────────────────────────────────────────────────────────
def _haversine_m(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    """Great-circle distance between two lat/lng points in metres."""
    r = 6_371_000.0
    p1 = math.radians(a_lat)
    p2 = math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lng - a_lng)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def _within_geofence(job: dict, lat: float, lng: float, radius_m: float) -> bool:
    site_lat = job.get("site_lat") or job.get("lat")
    site_lng = job.get("site_lng") or job.get("lng")
    if site_lat is None or site_lng is None:
        # Job has no known coords → we can't validate, treat as inside (flag none).
        return True
    return _haversine_m(site_lat, site_lng, lat, lng) <= radius_m


# ─── Duration helpers ──────────────────────────────────────────────────────
def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _minutes_between(a: Optional[str], b: Optional[str]) -> float:
    da, db_ = _parse_iso(a), _parse_iso(b)
    if not da or not db_:
        return 0.0
    return max(0.0, (db_ - da).total_seconds() / 60.0)


def _sum_break_minutes(breaks: List[dict]) -> float:
    total = 0.0
    for b in breaks or []:
        if b.get("start") and b.get("end"):
            total += _minutes_between(b["start"], b["end"])
    return total


def _iso_week(d: datetime) -> str:
    y, w, _ = d.isocalendar()
    return f"{y:04d}-W{w:02d}"


def _split_daily_overtime(hours: float, threshold: float = 8.0) -> tuple:
    """Return (regular_hours, overtime_hours) for a single day."""
    if hours <= threshold:
        return hours, 0.0
    return threshold, hours - threshold


# ─── Ensure indexes at import time ─────────────────────────────────────────
_INDEXES_ENSURED = False


async def _ensure_indexes():
    global _INDEXES_ENSURED
    if _INDEXES_ENSURED:
        return
    try:
        await db.time_entries.create_index([("tenant_id", 1), ("user_id", 1), ("clock_in_at", -1)])
        await db.time_entries.create_index([("tenant_id", 1), ("job_id", 1)])
        await db.location_pings.create_index([("tenant_id", 1), ("user_id", 1), ("ts", -1)])
        # TTL 30 days on location_pings via createdAt-style field.
        await db.location_pings.create_index("created_at_dt", expireAfterSeconds=30 * 24 * 3600)
        _INDEXES_ENSURED = True
    except Exception as e:
        logger.warning(f"workforce index ensure skipped: {e}")


# ─── Real-time broadcast helper ────────────────────────────────────────────
async def _broadcast(user_id: str, msg_type: str, payload: dict):
    try:
        from routers.realtime import bus
        await bus.broadcast(user_id, {"type": msg_type, "payload": payload})
    except Exception:
        pass


# ─── Pydantic models ───────────────────────────────────────────────────────
class ClockInReq(BaseModel):
    job_id: str
    lat: float
    lng: float
    accuracy: Optional[float] = None
    photo_url: Optional[str] = None


class ClockOutReq(BaseModel):
    entry_id: str
    lat: float
    lng: float
    notes: Optional[str] = None


class BreakReq(BaseModel):
    entry_id: str


class PingReq(BaseModel):
    lat: float
    lng: float
    speed: Optional[float] = None
    heading: Optional[float] = None
    battery: Optional[float] = None
    entry_id: Optional[str] = None


class RejectReq(BaseModel):
    reason: Optional[str] = ""


# ─── Mileage calc from pings ───────────────────────────────────────────────
async def _entry_mileage_miles(tenant_id: str, entry_id: str, user_id: str,
                                start: Optional[str], end: Optional[str],
                                settings: dict) -> float:
    """Sum Haversine hops between successive pings, filtered by speed + hop size."""
    if not start:
        return 0.0
    q = {"tenant_id": tenant_id, "user_id": user_id,
         "ts": {"$gte": start}}
    if end:
        q["ts"]["$lte"] = end
    pings = await db.location_pings.find(q, {"_id": 0}).sort("ts", 1).to_list(2000)
    if len(pings) < 2:
        return 0.0
    max_mps = settings["mileage_max_speed_mph"] * 0.44704  # mph → m/s
    min_hop = settings["mileage_min_hop_m"]
    total_m = 0.0
    prev = pings[0]
    for p in pings[1:]:
        dt = _minutes_between(prev["ts"], p["ts"]) * 60.0
        if dt <= 0:
            prev = p
            continue
        hop = _haversine_m(prev["lat"], prev["lng"], p["lat"], p["lng"])
        speed = hop / dt if dt > 0 else 0
        if hop >= min_hop and speed <= max_mps:
            total_m += hop
        prev = p
    return round(total_m / 1609.344, 3)


# ─── Endpoints ─────────────────────────────────────────────────────────────
@router.post("/workforce/clock-in")
async def clock_in(body: ClockInReq,
                    user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant)):
    await _ensure_indexes()
    job = await db.jobs.find_one(
        {"id": body.job_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not job:
        raise HTTPException(404, "Job not found")
    s = _settings(tenant)
    if s["require_photo_clock_in"] and not body.photo_url:
        raise HTTPException(400, "Photo required to clock in")

    # One open entry per user at a time.
    open_entry = await db.time_entries.find_one(
        {"tenant_id": tenant["id"], "user_id": user["id"], "clock_out_at": None},
        {"_id": 0},
    )
    if open_entry:
        raise HTTPException(400, "You already have an open shift — clock out first.")

    out_of_geofence = not _within_geofence(job, body.lat, body.lng, s["geofence_radius_m"])
    now = now_iso()
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "user_id": user["id"],
        "user_name": user.get("name") or user.get("email"),
        "job_id": body.job_id,
        "job_title": job.get("title"),
        "customer_id": job.get("customer_id"),
        "clock_in_at": now,
        "clock_out_at": None,
        "clock_in_geo": {"lat": body.lat, "lng": body.lng, "accuracy": body.accuracy},
        "clock_out_geo": None,
        "out_of_geofence": out_of_geofence,
        "photo_url": body.photo_url,
        "breaks": [],
        "duration_minutes": 0,
        "mileage_miles": 0,
        "status": "open",
        "notes": "",
        "created_at": now,
    }
    await db.time_entries.insert_one(doc)
    doc.pop("_id", None)
    await _broadcast(user["id"], "workforce.clock_in",
                     {"entry_id": doc["id"], "job_id": doc["job_id"],
                      "out_of_geofence": out_of_geofence})
    return doc


@router.post("/workforce/clock-out")
async def clock_out(body: ClockOutReq,
                     user: dict = Depends(get_current_user),
                     tenant: dict = Depends(get_current_tenant)):
    entry = await db.time_entries.find_one(
        {"id": body.entry_id, "tenant_id": tenant["id"], "user_id": user["id"]},
        {"_id": 0},
    )
    if not entry:
        raise HTTPException(404, "Time entry not found")
    if entry.get("clock_out_at"):
        raise HTTPException(400, "Already clocked out")
    # Close any open break implicitly.
    breaks = list(entry.get("breaks") or [])
    if breaks and not breaks[-1].get("end"):
        breaks[-1]["end"] = now_iso()

    now = now_iso()
    duration = _minutes_between(entry["clock_in_at"], now) - _sum_break_minutes(breaks)
    duration = round(max(0.0, duration), 2)

    s = _settings(tenant)
    mileage = await _entry_mileage_miles(
        tenant["id"], entry["id"], user["id"], entry["clock_in_at"], now, s
    )
    upd = {
        "clock_out_at": now,
        "clock_out_geo": {"lat": body.lat, "lng": body.lng},
        "breaks": breaks,
        "duration_minutes": duration,
        "mileage_miles": mileage,
        "notes": body.notes or entry.get("notes", ""),
        "status": "submitted",
        "submitted_at": now,
    }
    await db.time_entries.update_one({"id": entry["id"]}, {"$set": upd})
    await _broadcast(user["id"], "workforce.clock_out",
                     {"entry_id": entry["id"], "duration_minutes": duration,
                      "mileage_miles": mileage})
    return {**entry, **upd}


@router.post("/workforce/break/start")
async def break_start(body: BreakReq,
                       user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    entry = await db.time_entries.find_one(
        {"id": body.entry_id, "tenant_id": tenant["id"], "user_id": user["id"]},
        {"_id": 0},
    )
    if not entry or entry.get("clock_out_at"):
        raise HTTPException(400, "No open shift")
    breaks = list(entry.get("breaks") or [])
    if breaks and not breaks[-1].get("end"):
        raise HTTPException(400, "Break already in progress")
    breaks.append({"start": now_iso()})
    await db.time_entries.update_one({"id": entry["id"]}, {"$set": {"breaks": breaks}})
    return {"ok": True, "breaks": breaks}


@router.post("/workforce/break/end")
async def break_end(body: BreakReq,
                     user: dict = Depends(get_current_user),
                     tenant: dict = Depends(get_current_tenant)):
    entry = await db.time_entries.find_one(
        {"id": body.entry_id, "tenant_id": tenant["id"], "user_id": user["id"]},
        {"_id": 0},
    )
    if not entry or entry.get("clock_out_at"):
        raise HTTPException(400, "No open shift")
    breaks = list(entry.get("breaks") or [])
    if not breaks or breaks[-1].get("end"):
        raise HTTPException(400, "No break in progress")
    breaks[-1]["end"] = now_iso()
    await db.time_entries.update_one({"id": entry["id"]}, {"$set": {"breaks": breaks}})
    return {"ok": True, "breaks": breaks}


@router.post("/workforce/location-ping")
async def location_ping(body: PingReq,
                         user: dict = Depends(get_current_user),
                         tenant: dict = Depends(get_current_tenant)):
    await _ensure_indexes()
    s = _settings(tenant)
    now_dt = datetime.now(timezone.utc)
    # Rate-limit: last ping within ping_min_seconds → drop (no error).
    last = await db.location_pings.find_one(
        {"tenant_id": tenant["id"], "user_id": user["id"]},
        {"_id": 0, "ts": 1},
        sort=[("ts", -1)],
    )
    if last:
        try:
            last_dt = datetime.fromisoformat(last["ts"].replace("Z", "+00:00"))
            if (now_dt - last_dt).total_seconds() < s["ping_min_seconds"]:
                return {"accepted": False, "reason": "rate_limit"}
        except Exception:
            pass
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "user_id": user["id"],
        "ts": now_dt.isoformat(),
        "lat": body.lat,
        "lng": body.lng,
        "speed": body.speed,
        "heading": body.heading,
        "battery": body.battery,
        "entry_id": body.entry_id,
        "created_at_dt": now_dt,  # TTL anchor
    }
    await db.location_pings.insert_one(doc)
    return {"accepted": True}


# ─── Timesheets aggregation ────────────────────────────────────────────────
def _group_key(iso_ts: str) -> str:
    """Return YYYY-MM-DD day-key for an ISO timestamp."""
    dt = _parse_iso(iso_ts)
    return dt.date().isoformat() if dt else ""


@router.get("/workforce/timesheets")
async def list_timesheets(
    user_id: Optional[str] = None,
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = None,
    status: Optional[str] = None,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    # Non-admin users only see their own timesheets.
    q: dict = {"tenant_id": tenant["id"]}
    if user.get("role") not in ("admin", "super_admin"):
        q["user_id"] = user["id"]
    elif user_id:
        q["user_id"] = user_id
    if status:
        q["status"] = status
    if from_ or to:
        rng = {}
        if from_:
            rng["$gte"] = from_
        if to:
            rng["$lte"] = to
        q["clock_in_at"] = rng
    rows = await db.time_entries.find(q, {"_id": 0}).sort("clock_in_at", -1).to_list(2000)

    # Weekly overtime buckets per user × iso-week.
    s = _settings(tenant)
    daily_ot = s["overtime_daily_hours"]
    weekly_ot = s["overtime_weekly_hours"]
    weekly_totals: dict = {}

    grouped = []
    for r in rows:
        day = _group_key(r.get("clock_in_at"))
        hours = round((r.get("duration_minutes") or 0) / 60.0, 3)
        reg, ot = _split_daily_overtime(hours, daily_ot)
        # Track running weekly total to spill any excess past weekly_ot into overtime.
        try:
            wk = _iso_week(_parse_iso(r["clock_in_at"]))
        except Exception:
            wk = ""
        key = (r["user_id"], wk)
        used = weekly_totals.get(key, 0)
        # Portion of `reg` beyond weekly cap flips into OT.
        room = max(0.0, weekly_ot - used)
        if reg > room:
            spill = reg - room
            reg = room
            ot += spill
        weekly_totals[key] = used + reg
        grouped.append({
            **r,
            "day": day,
            "hours": hours,
            "regular_hours": round(reg, 3),
            "overtime_hours": round(ot, 3),
            "break_deduction_minutes": round(_sum_break_minutes(r.get("breaks") or []), 2),
        })
    return grouped


@router.post("/workforce/timesheets/{eid}/approve")
async def approve_timesheet(eid: str,
                             admin: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    r = await db.time_entries.update_one(
        {"id": eid, "tenant_id": tenant["id"]},
        {"$set": {"status": "approved", "approved_by": admin["id"],
                  "approved_at": now_iso()}},
    )
    if not r.matched_count:
        raise HTTPException(404, "Timesheet not found")
    doc = await db.time_entries.find_one({"id": eid, "tenant_id": tenant["id"]}, {"_id": 0})
    await _broadcast(doc["user_id"], "workforce.timesheet_approved", {"entry_id": eid})
    return doc


@router.post("/workforce/timesheets/{eid}/reject")
async def reject_timesheet(eid: str, body: RejectReq,
                            admin: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    r = await db.time_entries.update_one(
        {"id": eid, "tenant_id": tenant["id"]},
        {"$set": {"status": "rejected", "rejected_by": admin["id"],
                  "rejected_at": now_iso(), "reject_reason": body.reason or ""}},
    )
    if not r.matched_count:
        raise HTTPException(404, "Timesheet not found")
    doc = await db.time_entries.find_one({"id": eid, "tenant_id": tenant["id"]}, {"_id": 0})
    await _broadcast(doc["user_id"], "workforce.timesheet_rejected",
                     {"entry_id": eid, "reason": body.reason or ""})
    return doc


# ─── Crew map ──────────────────────────────────────────────────────────────
@router.get("/workforce/crew-map")
async def crew_map(admin: dict = Depends(require_admin),
                    tenant: dict = Depends(get_current_tenant)):
    """Latest known ping + current shift for each user with any recent activity."""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    # Get latest ping per user in the last 24h.
    pipeline = [
        {"$match": {"tenant_id": tenant["id"], "ts": {"$gte": since}}},
        {"$sort": {"ts": -1}},
        {"$group": {
            "_id": "$user_id",
            "ts": {"$first": "$ts"},
            "lat": {"$first": "$lat"},
            "lng": {"$first": "$lng"},
            "speed": {"$first": "$speed"},
            "battery": {"$first": "$battery"},
        }},
    ]
    pings = await db.location_pings.aggregate(pipeline).to_list(500)
    out = []
    for p in pings:
        uid = p["_id"]
        u = await db.users.find_one({"id": uid, "tenant_id": tenant["id"]},
                                    {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1, "avatar": 1})
        if not u:
            continue
        # Current open shift, if any.
        entry = await db.time_entries.find_one(
            {"tenant_id": tenant["id"], "user_id": uid, "clock_out_at": None},
            {"_id": 0},
        )
        # Today's hours-so-far.
        today = datetime.now(timezone.utc).date().isoformat()
        today_rows = await db.time_entries.find(
            {"tenant_id": tenant["id"], "user_id": uid,
             "clock_in_at": {"$gte": today + "T00:00:00+00:00"}},
            {"_id": 0, "duration_minutes": 1},
        ).to_list(50)
        hours_today = round(sum((r.get("duration_minutes") or 0) for r in today_rows) / 60.0, 2)
        out.append({
            "user": u,
            "last_ping": {"ts": p["ts"], "lat": p["lat"], "lng": p["lng"],
                          "speed": p.get("speed"), "battery": p.get("battery")},
            "clocked_in": bool(entry),
            "current_entry": entry,
            "hours_today": hours_today,
        })
    return out


# ─── Job cost ──────────────────────────────────────────────────────────────
@router.get("/workforce/job-cost/{job_id}")
async def job_cost(job_id: str,
                    user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant)):
    job = await db.jobs.find_one({"id": job_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    s = _settings(tenant)
    entries = await db.time_entries.find(
        {"tenant_id": tenant["id"], "job_id": job_id}, {"_id": 0}
    ).to_list(500)
    labor_cost = 0.0
    total_hours = 0.0
    mileage_miles = 0.0
    for e in entries:
        h = (e.get("duration_minutes") or 0) / 60.0
        total_hours += h
        mileage_miles += e.get("mileage_miles") or 0
        u = await db.users.find_one({"id": e["user_id"]}, {"_id": 0, "hourly_rate": 1})
        rate = float((u or {}).get("hourly_rate") or 0)
        labor_cost += h * rate
    materials_cost = 0.0
    materials = await db.job_materials.find(
        {"tenant_id": tenant["id"], "job_id": job_id}, {"_id": 0}
    ).to_list(500)
    for m in materials:
        materials_cost += float(m.get("cost") or 0) * float(m.get("quantity") or 1)
    mileage_cost = round(mileage_miles * s["mileage_rate_usd"], 2)
    revenue = float(job.get("price") or 0)
    total_cost = round(labor_cost + materials_cost + mileage_cost, 2)
    gross_margin = round(revenue - total_cost, 2)
    return {
        "job_id": job_id,
        "job_title": job.get("title"),
        "revenue": revenue,
        "labor_cost": round(labor_cost, 2),
        "labor_hours": round(total_hours, 2),
        "materials_cost": round(materials_cost, 2),
        "mileage_miles": round(mileage_miles, 2),
        "mileage_cost": mileage_cost,
        "mileage_rate_usd": s["mileage_rate_usd"],
        "total_cost": total_cost,
        "gross_margin": gross_margin,
        "gross_margin_pct": round(100 * gross_margin / revenue, 1) if revenue else None,
    }


# ─── Mileage report ────────────────────────────────────────────────────────
@router.get("/workforce/mileage")
async def mileage_report(user_id: Optional[str] = None,
                          from_: Optional[str] = Query(None, alias="from"),
                          to: Optional[str] = None,
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    q: dict = {"tenant_id": tenant["id"]}
    if user.get("role") not in ("admin", "super_admin"):
        q["user_id"] = user["id"]
    elif user_id:
        q["user_id"] = user_id
    if from_ or to:
        rng = {}
        if from_:
            rng["$gte"] = from_
        if to:
            rng["$lte"] = to
        q["clock_in_at"] = rng
    entries = await db.time_entries.find(q, {"_id": 0}).sort("clock_in_at", 1).to_list(2000)
    by_day: dict = {}
    for e in entries:
        day = _group_key(e.get("clock_in_at"))
        key = (e["user_id"], day)
        by_day.setdefault(key, {"user_id": e["user_id"],
                                "user_name": e.get("user_name"),
                                "day": day, "miles": 0.0, "entries": 0})
        by_day[key]["miles"] += e.get("mileage_miles") or 0
        by_day[key]["entries"] += 1
    return sorted(
        [{**v, "miles": round(v["miles"], 3)} for v in by_day.values()],
        key=lambda r: (r["day"], r["user_name"] or ""),
    )


# ─── CSV export ────────────────────────────────────────────────────────────
@router.get("/workforce/export/timesheets.csv")
async def export_csv(from_: Optional[str] = Query(None, alias="from"),
                      to: Optional[str] = None,
                      admin: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    q: dict = {"tenant_id": tenant["id"]}
    if from_ or to:
        rng = {}
        if from_:
            rng["$gte"] = from_
        if to:
            rng["$lte"] = to
        q["clock_in_at"] = rng
    entries = await db.time_entries.find(q, {"_id": 0}).sort("clock_in_at", -1).to_list(5000)

    def row_iter():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "entry_id", "user_id", "user_name", "job_id", "job_title",
            "clock_in_at", "clock_out_at", "duration_minutes",
            "mileage_miles", "out_of_geofence", "status", "approved_by",
        ])
        yield buf.getvalue()
        buf.seek(0); buf.truncate(0)
        for e in entries:
            writer.writerow([
                e.get("id"), e.get("user_id"), e.get("user_name") or "",
                e.get("job_id"), e.get("job_title") or "",
                e.get("clock_in_at"), e.get("clock_out_at") or "",
                e.get("duration_minutes") or 0,
                e.get("mileage_miles") or 0,
                "true" if e.get("out_of_geofence") else "false",
                e.get("status"), e.get("approved_by") or "",
            ])
            yield buf.getvalue()
            buf.seek(0); buf.truncate(0)

    filename = f"timesheets_{(from_ or 'all')}_{(to or 'now')}.csv"
    return StreamingResponse(
        row_iter(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
