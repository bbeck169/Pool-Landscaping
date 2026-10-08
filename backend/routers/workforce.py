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
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, get_current_user, require_admin, require_admin_or_manager
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
    # Feb-2026 · MARCO Proactive Alerts — resolve any active
    # "missing_clock_in" alert for this job now that a clock-in
    # exists.  Best-effort, no raise.
    if doc.get("job_id"):
        try:
            from services.marco_alerts import (
                auto_resolve_alert,
                MARCO_ALERT_KIND_MISSING_CLOCK_IN,
            )
            await auto_resolve_alert(
                db, tenant_id=tenant["id"],
                kind=MARCO_ALERT_KIND_MISSING_CLOCK_IN,
                entity_ref={"type": "job", "id": doc["job_id"]},
                reason="clock_in",
            )
        except Exception:
            pass
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


# ─── Timecard edit (admin / manager) · TIMECARD-EDIT atomic ────────────────
class TimecardEditReq(BaseModel):
    """PATCH body for ``/workforce/timesheets/{eid}``.

    All fields optional. ``date`` (``YYYY-MM-DD``) acts as a day-only
    re-anchor on whichever of ``clock_in_at`` / ``clock_out_at`` the
    body did NOT also supply verbatim — the stored HH:MM:SS + tz
    offset is preserved. ``reason`` is a free-text audit note capped
    at 500 chars.
    """
    clock_in_at: Optional[str] = None
    clock_out_at: Optional[str] = None
    date: Optional[str] = None
    reason: Optional[str] = None


_REASON_MAX_LEN = 500
# After midnight-crossing auto-advance (``co <= ci`` → +1 day on co),
# any resolved shift > 20h is a fat-finger reversal, not a real shift.
# 20h covers legitimate split-shifts (~18h) with headroom; a true 24h
# on-call pass-through is rare enough to be worth a conscious re-key.
# See TIMECARD-EDIT atomic receipt for rationale.
_SHIFT_MAX_HOURS = 20.0


def _reanchor_iso_day(iso_str: str, new_date_yyyymmdd: str) -> str:
    """Replace the DATE portion of ``iso_str`` with ``new_date_yyyymmdd``,
    preserving ``HH:MM:SS.ffffff`` and timezone. Raises 400 on malformed
    input."""
    try:
        new_d = datetime.strptime(new_date_yyyymmdd, "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(400, f"Invalid date: {new_date_yyyymmdd!r} (expected YYYY-MM-DD)")
    try:
        orig = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(400, f"Invalid ISO timestamp: {iso_str!r}")
    return orig.replace(year=new_d.year, month=new_d.month, day=new_d.day).isoformat()


def _shift_iso_by_days(iso_str: str, delta_days: int) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        return iso_str
    return (dt + timedelta(days=delta_days)).isoformat()


def _shift_breaks_by_days(breaks: List[dict], delta_days: int) -> List[dict]:
    """Shift every break ``start``/``end`` by ``delta_days`` while keeping
    non-ISO / unset fields untouched. Zero delta → identity."""
    if not breaks or delta_days == 0:
        return list(breaks or [])
    out: List[dict] = []
    for b in breaks:
        nb = dict(b)
        if nb.get("start"):
            nb["start"] = _shift_iso_by_days(nb["start"], delta_days)
        if nb.get("end"):
            nb["end"] = _shift_iso_by_days(nb["end"], delta_days)
        out.append(nb)
    return out


@router.patch("/workforce/timesheets/{eid}")
async def edit_timesheet(
    eid: str, body: TimecardEditReq,
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
):
    """TIMECARD-EDIT · admin/manager/owner/super_admin edit of
    ``clock_in_at`` / ``clock_out_at`` / day-attribution on a
    ``time_entries`` row with an embedded audit trail (``edits: [...]``).

    Resolution order:
      1. Load row (tenant-scoped). 404 if missing / soft-deleted.
         400 if the row is on a paid payroll run.
      2. Apply ``clock_in_at`` / ``clock_out_at`` verbatim overrides.
      3. If ``date`` supplied, re-anchor DATE part of each timestamp
         the body did NOT already supply verbatim.
      4. Open shifts (``clock_out_at is None``): reject any body-level
         ``clock_out_at`` write (callers must use ``/workforce/clock-out``);
         ``clock_in_at`` / ``date`` edits are permitted and leave the
         shift open with ``duration_minutes`` unchanged.
      5. If closed shift and ``clock_out_at <= clock_in_at`` after
         resolution → auto-advance ``clock_out_at`` by +1 day
         (overnight shift). Then if resolved duration > 20h →
         ``400 shift_duration_unreasonable`` (fat-finger guard).
      6. Breaks: shift ``start``/``end`` by the day-delta applied to
         ``clock_in_at`` so breaks stay inside the (possibly re-dated)
         shift.
      7. Recompute ``duration_minutes`` from final (ci, co) minus
         break minutes (closed shifts only).
      8. No-op short-circuit: if resolved values match stored, return
         the row untouched and do NOT append an edit record.
      9. Successful mutation appends one ``edits[]`` entry capturing
         actor + per-field from/to deltas. Rejected PATCHes do NOT
         write an audit entry.
    """
    if body.reason is not None and len(body.reason) > _REASON_MAX_LEN:
        raise HTTPException(400, f"reason too long (>{_REASON_MAX_LEN} chars)")
    if (body.clock_in_at is None and body.clock_out_at is None
            and body.date is None):
        raise HTTPException(400, "No editable fields supplied")

    entry = await db.time_entries.find_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not entry or entry.get("deleted_at"):
        raise HTTPException(404, "Time entry not found")
    if entry.get("payroll_run_id") and entry.get("payroll_paid_at"):
        raise HTTPException(400, "Time entry is on a paid payroll run — not editable")

    old_ci = entry.get("clock_in_at")
    old_co = entry.get("clock_out_at")
    was_open = old_co is None

    if was_open and body.clock_out_at is not None:
        raise HTTPException(
            400,
            "Open shift — use /workforce/clock-out to close, not PATCH",
        )

    new_ci = body.clock_in_at if body.clock_in_at is not None else old_ci
    new_co = body.clock_out_at if body.clock_out_at is not None else old_co

    if body.date is not None:
        if body.clock_in_at is None and new_ci:
            new_ci = _reanchor_iso_day(new_ci, body.date)
        if body.clock_out_at is None and new_co:
            new_co = _reanchor_iso_day(new_co, body.date)

    ci_dt = _parse_iso(new_ci) if new_ci else None
    if new_ci is not None and ci_dt is None:
        raise HTTPException(400, f"Invalid clock_in_at: {new_ci!r}")
    co_dt = _parse_iso(new_co) if new_co else None
    if new_co is not None and co_dt is None:
        raise HTTPException(400, f"Invalid clock_out_at: {new_co!r}")

    if ci_dt and co_dt and co_dt <= ci_dt:
        co_dt = co_dt + timedelta(days=1)
        new_co = co_dt.isoformat()

    if ci_dt and co_dt:
        hrs = (co_dt - ci_dt).total_seconds() / 3600.0
        if hrs > _SHIFT_MAX_HOURS:
            raise HTTPException(
                400,
                f"shift_duration_unreasonable: {hrs:.1f}h exceeds "
                f"{_SHIFT_MAX_HOURS:.0f}h cap; verify start/end times",
            )

    breaks = list(entry.get("breaks") or [])
    if body.date is not None and ci_dt and old_ci:
        try:
            old_ci_date = datetime.fromisoformat(old_ci.replace("Z", "+00:00")).date()
            delta_days = (ci_dt.date() - old_ci_date).days
            if delta_days:
                breaks = _shift_breaks_by_days(breaks, delta_days)
        except Exception:
            pass

    old_dur = entry.get("duration_minutes") or 0
    if ci_dt and co_dt:
        new_dur = round(
            max(0.0, (co_dt - ci_dt).total_seconds() / 60.0
                - _sum_break_minutes(breaks)),
            2,
        )
    else:
        new_dur = old_dur

    changes: dict = {}
    if new_ci != old_ci:
        changes["clock_in_at"] = {"from": old_ci, "to": new_ci}
    if new_co != old_co:
        changes["clock_out_at"] = {"from": old_co, "to": new_co}
    if body.date is not None:
        try:
            old_d = (datetime.fromisoformat(old_ci.replace("Z", "+00:00"))
                     .date().isoformat() if old_ci else None)
        except Exception:
            old_d = None
        if old_d != body.date:
            changes["date"] = {"from": old_d, "to": body.date}
    if new_dur != old_dur:
        changes["duration_minutes"] = {"from": old_dur, "to": new_dur}

    if not changes:
        return entry

    edit = {
        "edit_id": new_id(),
        "edited_by": user["id"],
        "edited_by_name": user.get("name") or user.get("email"),
        "edited_by_role": user.get("role"),
        "edited_at": now_iso(),
        "changes": changes,
    }
    if body.reason:
        edit["reason"] = body.reason

    upd: dict = {}
    if "clock_in_at" in changes:
        upd["clock_in_at"] = new_ci
    if "clock_out_at" in changes:
        upd["clock_out_at"] = new_co
    if "duration_minutes" in changes:
        upd["duration_minutes"] = new_dur
    if breaks != (entry.get("breaks") or []):
        upd["breaks"] = breaks

    await db.time_entries.update_one(
        {"id": eid, "tenant_id": tenant["id"]},
        {"$set": upd, "$push": {"edits": edit}},
    )
    doc = await db.time_entries.find_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
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
    job = await db.jobs.find_one({"id": job_id, "tenant_id": tenant["id"]}, {"_id": 0, "photos.data": 0})
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


# ═══════════════════════════════════════════════════════════════════════════
# GPS-based auto clock-in + cancel grace-window
# ═══════════════════════════════════════════════════════════════════════════
class AutoClockInReq(BaseModel):
    lat: float
    lng: float
    accuracy: Optional[float] = None


# Simple in-memory 60s rate limit per user (best-effort — nothing sensitive).
_AUTO_LAST: Dict[str, float] = {}
_AUTO_MIN_GAP_S = 60
_AUTO_ACC_MAX_M = 100.0
_AUTO_TIME_WINDOW_H = 2


@router.post("/workforce/_test/reset-autoclock")
async def _reset_autoclock_ratelimit(user: dict = Depends(get_current_user)):
    """Test-only hook — clears the in-memory rate-limit map for the current
    user. Gated by env var so it's a no-op in production."""
    if not os.environ.get("ALLOW_TEST_HOOKS"):
        raise HTTPException(404, "Not found")
    _AUTO_LAST.pop(user["id"], None)
    return {"ok": True, "cleared": user["id"]}


@router.post("/workforce/_test/seed-in-window-job")
async def _seed_in_window_job(user: dict = Depends(get_current_user),
                              tenant: dict = Depends(get_current_tenant)):
    """Test-only hook — creates a fresh scheduled job at Jennifer Carson's
    coordinates, scheduled `now() + 5 minutes`, assigned to the calling tech.
    Idempotent-ish: each call creates a new job (safe to call repeatedly).
    Returns { job_id }. Env-gated via ALLOW_TEST_HOOKS.
    """
    if not os.environ.get("ALLOW_TEST_HOOKS"):
        raise HTTPException(404, "Not found")
    tech_id = user.get("id")
    if user.get("role") != "technician":
        # Restrict this seed to techs — no need to seed jobs for admins here.
        raise HTTPException(400, "Only techs can seed a personal in-window job")
    scheduled_start = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    scheduled_end = (datetime.now(timezone.utc) + timedelta(minutes=65)).isoformat()
    jid = new_id()
    doc = {
        "id": jid,
        "tenant_id": tenant["id"],
        "customer_name": "TEST_ auto-clockin (seed hook)",
        "title": "Weekly Pool Service",
        "service_type": "Weekly Pool Service",
        "job_type": "Weekly Pool Service",
        "status": "scheduled",
        "technician_id": tech_id,
        "site_lat": 33.7005,
        "site_lng": -112.228,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "photos": [],
        "created_at": now_iso(),
        "seed_source": "auto_clockin_test_hook",
    }
    await db.jobs.insert_one(doc)
    return {"job_id": jid, "scheduled_start": scheduled_start,
            "site_lat": 33.7005, "site_lng": -112.228}


def _log_auto_decision(tenant_id: str, user_id: str, lat: float, lng: float,
                        decision: str, extra: dict | None = None):
    try:
        # Fire-and-forget audit trail via location_pings.decision field.
        # We DON'T await this — it's audit only, don't block the endpoint.
        import asyncio
        async def _write():
            ping = {
                "id": new_id(), "tenant_id": tenant_id, "user_id": user_id,
                "lat": lat, "lng": lng, "ts": now_iso(),
                "kind": "auto_clockin_decision", "decision": decision,
            }
            if extra:
                ping.update(extra)
            try:
                await db.location_pings.insert_one(ping)
            except Exception as e:
                logger.warning(f"auto-clockin audit insert failed: {e}")
        asyncio.create_task(_write())
    except Exception:
        pass


@router.post("/workforce/auto-clock-in")
async def auto_clock_in(body: AutoClockInReq,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    """GPS-triggered auto-clock-in.

    Fires when the tech is inside a scheduled job's geofence AND within ±2h of
    the job's `scheduled_start`. Rate-limited to once per 60s per user.
    Returns 200 with `clocked_in:false` (and a `reason`) instead of 4xx for
    business misses, so the client can keep polling as the tech moves around.

    Reason ordering (short-circuits, most-useful first):
      1. already_clocked_in
      2. throttled            (rate limit)
      3. low_accuracy
      4. not_at_any_scheduled_site   (no today's job is within geofence)
      5. out_of_time_window           (a geofence match exists but not in ±2h)
    """
    import time as _time
    uid = user["id"]

    # 1) Already clocked in? Never auto-switch jobs.
    open_entry = await db.time_entries.find_one(
        {"tenant_id": tenant["id"], "user_id": uid, "clock_out_at": None},
        {"_id": 0},
    )
    if open_entry:
        _log_auto_decision(tenant["id"], uid, body.lat, body.lng, "already_clocked_in",
                           {"open_entry_id": open_entry["id"]})
        return {"clocked_in": False, "reason": "already_clocked_in",
                "open_entry_id": open_entry["id"],
                "open_job_id": open_entry.get("job_id")}

    # 2) Rate-limit — keep AFTER #1 so a user already clocked in gets the more
    #    useful message. Returns 200 with reason so the client can just poll.
    now_epoch = _time.time()
    last = _AUTO_LAST.get(uid, 0)
    if now_epoch - last < _AUTO_MIN_GAP_S:
        _log_auto_decision(tenant["id"], uid, body.lat, body.lng, "throttled")
        return {"clocked_in": False, "reason": "throttled"}
    _AUTO_LAST[uid] = now_epoch

    # 3) Low-accuracy fix → refuse (spec says >100m is unusable).
    if body.accuracy is not None and body.accuracy > _AUTO_ACC_MAX_M:
        _log_auto_decision(tenant["id"], uid, body.lat, body.lng, "low_accuracy",
                           {"accuracy": body.accuracy})
        return {"clocked_in": False, "reason": "low_accuracy",
                "accuracy_m": body.accuracy}

    # 4) & 5) Fetch ALL of TODAY's assigned jobs, then split by geofence and
    #         ±2h window so we can hand back the right reason string.
    s = _settings(tenant)
    radius = s.get("geofence_radius_m", 100)
    now_dt = datetime.now(timezone.utc)
    day_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    day_end = (now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
                + timedelta(days=1)).isoformat()
    window_start = (now_dt - timedelta(hours=_AUTO_TIME_WINDOW_H)).isoformat()
    window_end = (now_dt + timedelta(hours=_AUTO_TIME_WINDOW_H)).isoformat()
    # Phase P12.2 · Feb-2026 · SAFETY-CRITICAL — replace the pre-P12
    # dict-spread merge of ``not_deleted_filter`` over the tech-lane
    # ``$or`` (P10 flag row 813-824). ``_nd()`` returns
    # ``{"$or": [<soft-delete clauses>]}`` and gets spread LAST, so
    # the tech-lane ``$or`` was silently dropped every request.
    # Failure mode: the query degraded to "any non-deleted tenant
    # job today matching the exact-match kwargs (tenant / status /
    # scheduled_start-in-day)" — a tech near a coworker's job site
    # (same tenant, same day, same ±2h window) auto-clocked into
    # the coworker's job. Nest both disjunctions under ``$and`` via
    # the shared ``tenant_scoped_filter`` helper — the identical
    # fix P12 applied to ``/api/schedule/optimize-route`` and P10
    # applied to ``/api/jobs/reorder``.
    from services.query_scope import tenant_scoped_filter as _tsf
    query = _tsf(
        tenant["id"],
        [
            {"technician_id": uid},
            {"technician_id": user.get("technician_id")},
            {"assigned_technician_id": uid},
        ],
        status={"$nin": ["completed", "cancelled"]},
        scheduled_start={"$gte": day_start, "$lt": day_end},
    )
    jobs_today = await db.jobs.find(query, {"_id": 0, "photos.data": 0}).to_list(50)

    # Split by geofence first.
    in_geofence: list = []
    for j in jobs_today:
        site_lat = j.get("site_lat") or j.get("lat")
        site_lng = j.get("site_lng") or j.get("lng")
        if site_lat is None or site_lng is None:
            continue
        d = _haversine_m(site_lat, site_lng, body.lat, body.lng)
        if d <= radius:
            in_geofence.append((d, j))

    if not in_geofence:
        _log_auto_decision(tenant["id"], uid, body.lat, body.lng,
                           "not_at_any_scheduled_site")
        return {"clocked_in": False, "reason": "not_at_any_scheduled_site"}

    # Of the geofence matches, keep only those in the ±2h window.
    in_window = [
        (d, j) for (d, j) in in_geofence
        if (j.get("scheduled_start") or "") >= window_start
        and (j.get("scheduled_start") or "") <= window_end
    ]
    if not in_window:
        _log_auto_decision(tenant["id"], uid, body.lat, body.lng,
                           "out_of_time_window")
        return {"clocked_in": False, "reason": "out_of_time_window"}

    # Nearest of the qualifying jobs.
    in_window.sort(key=lambda t: t[0])
    best_dist, best = in_window[0]

    # Clock the tech in.
    now = now_iso()
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "user_id": uid,
        "user_name": user.get("name") or user.get("email"),
        "job_id": best["id"],
        "job_title": best.get("title"),
        "customer_id": best.get("customer_id"),
        "clock_in_at": now,
        "clock_out_at": None,
        "clock_in_geo": {"lat": body.lat, "lng": body.lng,
                          "accuracy": body.accuracy},
        "clock_out_geo": None,
        "out_of_geofence": False,
        "photo_url": None,
        "breaks": [],
        "duration_minutes": 0,
        "mileage_miles": 0,
        "status": "open",
        "notes": "",
        "origin": "gps_auto",
        "distance_m_from_site": round(best_dist, 1),
        "created_at": now,
    }
    await db.time_entries.insert_one(doc)
    doc.pop("_id", None)
    await _broadcast(uid, "workforce.clock_in",
                     {"entry_id": doc["id"], "job_id": doc["job_id"],
                      "auto": True, "distance_m": doc["distance_m_from_site"]})
    # Feb-2026 · MARCO Proactive Alerts — mirror the manual
    # clock-in auto-resolve for the GPS-auto path.
    if doc.get("job_id"):
        try:
            from services.marco_alerts import (
                auto_resolve_alert,
                MARCO_ALERT_KIND_MISSING_CLOCK_IN,
            )
            await auto_resolve_alert(
                db, tenant_id=tenant["id"],
                kind=MARCO_ALERT_KIND_MISSING_CLOCK_IN,
                entity_ref={"type": "job", "id": doc["job_id"]},
                reason="clock_in_gps",
            )
        except Exception:
            pass
    _log_auto_decision(tenant["id"], uid, body.lat, body.lng, "clocked_in",
                       {"job_id": best["id"], "distance_m": doc["distance_m_from_site"]})
    return {
        "clocked_in": True,
        "entry_id": doc["id"],
        "job_id": best["id"],
        "job_title": best.get("title"),
        "customer_name": best.get("customer_name"),
        "distance_m": doc["distance_m_from_site"],
    }


@router.post("/workforce/cancel-auto-clock-in/{entry_id}")
async def cancel_auto_clock_in(entry_id: str,
                               user: dict = Depends(get_current_user),
                               tenant: dict = Depends(get_current_tenant)):
    """Void a gps_auto time_entry within a 30-second grace window."""
    entry = await db.time_entries.find_one(
        {"id": entry_id, "tenant_id": tenant["id"], "user_id": user["id"]},
        {"_id": 0},
    )
    if not entry:
        raise HTTPException(404, "Time entry not found")
    if entry.get("origin") != "gps_auto":
        raise HTTPException(400, "Only gps_auto entries can be cancelled — clock out normally")
    if entry.get("clock_out_at"):
        raise HTTPException(400, "Entry already closed — cannot cancel")
    if entry.get("breaks"):
        raise HTTPException(400, "Grace window expired (breaks recorded)")
    # Enforce 30-second grace window.
    try:
        started = datetime.fromisoformat(entry["clock_in_at"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - started).total_seconds()
    except Exception:
        age = 999
    if age > 30:
        raise HTTPException(400, "Grace window expired — clock out normally instead")
    await db.time_entries.delete_one({"id": entry_id, "tenant_id": tenant["id"]})
    await _broadcast(user["id"], "workforce.clock_in_cancelled",
                     {"entry_id": entry_id})
    return {"ok": True, "entry_id": entry_id, "cancelled": True}


async def force_clock_out_if_auto(tenant_id: str, user_id: str, job_id: str) -> Optional[dict]:
    """Called by service-report submit to guarantee clock-out on gps_auto entries.
    Returns the closed entry summary if a clock-out happened, else None.
    """
    entry = await db.time_entries.find_one(
        {"tenant_id": tenant_id, "user_id": user_id, "job_id": job_id,
         "clock_out_at": None},
        {"_id": 0},
    )
    if not entry:
        return None
    # Only mandatory for gps_auto; manual best-effort keeps existing behavior.
    is_auto = entry.get("origin") == "gps_auto"
    now = now_iso()
    breaks = list(entry.get("breaks") or [])
    if breaks and not breaks[-1].get("end"):
        breaks[-1]["end"] = now
    duration = _minutes_between(entry["clock_in_at"], now) - _sum_break_minutes(breaks)
    tenant_doc = await db.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}
    settings = _settings(tenant_doc)
    miles = await _entry_mileage_miles(
        tenant_id, entry["id"], user_id, entry.get("clock_in_at"), now, settings
    )
    upd = {
        "clock_out_at": now,
        "clock_out_geo": entry.get("clock_in_geo"),  # best-effort — client already left the geofence
        "breaks": breaks,
        "duration_minutes": max(0, duration),
        "mileage_miles": miles,
        "status": "submitted",
        "closed_by_report": True,
    }
    await db.time_entries.update_one({"id": entry["id"]}, {"$set": upd})
    await _broadcast(user_id, "workforce.clock_out",
                     {"entry_id": entry["id"], "auto": is_auto})
    entry.update(upd)
    return entry

