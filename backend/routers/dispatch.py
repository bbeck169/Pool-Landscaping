"""Phase 26 · Route Auto-Dispatcher + Weather-Triggered Auto-Reschedule.

Two modules share this router because they both live under `/api/dispatch/*`
and both hinge on the tenant `settings.dispatch.*` block.

Design notes:
- Route insertion cost is `min(haversine to existing today stops)` +
  `time_pressure_factor * WEIGHT` where time_pressure = remaining_jobs /
  max(1, hours_left_in_shift). Techs with empty routes today score their
  first stop at cost 0 (encouraged — even out load).
- Auto-assign-on-create only fires when `settings.dispatch.auto_assign_on_create`
  is True AND the incoming job has no `assigned_to` / `technician_id`.
- Weather scan reuses the existing keyless Open-Meteo forecast endpoint.
- APScheduler `weather_scan` runs daily at 05:00 UTC (per-tenant local-time
  tuning is deferred to a phase 26 polish task).
"""
import csv
import io
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db, logger
from utils import get_current_user, new_id, now_iso, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()

# ─── Constants ───────────────────────────────────────────────────────
TIME_PRESSURE_WEIGHT = 500.0  # meters-equivalent per unit
SKILL_MULT_EXACT = 1.0        # tech's preferences include job.service_type
SKILL_MULT_NEUTRAL = 1.5      # tech has no stated preferences
SKILL_MULT_OFF = 2.5          # tech has preferences but this job isn't one
DEFAULT_RAIN_THRESHOLD = 60
DEFAULT_WIND_THRESHOLD = 25
OUTDOOR_TYPES = {"landscape", "landscaping", "hardscape", "d2d",
                    "exterior", "external", "outdoor", "yard-care",
                    "lawn-care", "pressure-wash", "cleaning-external"}


# ─── Geo helpers ─────────────────────────────────────────────────────
def _haversine_m(lat1: float, lng1: float,
                    lat2: float, lng2: float) -> float:
    R = 6_371_000.0
    to_rad = math.pi / 180
    dlat = (lat2 - lat1) * to_rad
    dlng = (lng2 - lng1) * to_rad
    a = (math.sin(dlat / 2) ** 2
          + math.cos(lat1 * to_rad) * math.cos(lat2 * to_rad)
          * math.sin(dlng / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def _job_coords(j: Dict[str, Any]) -> Optional[tuple]:
    lat = j.get("site_lat") or j.get("lat")
    lng = j.get("site_lng") or j.get("lng")
    if lat is None or lng is None: return None
    try: return (float(lat), float(lng))
    except Exception: return None


def _today_key(tz: str = "UTC") -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _scheduled_today(job: Dict[str, Any], day_key: str) -> bool:
    d = (job.get("scheduled_date") or job.get("scheduled_start") or "")[:10]
    return d == day_key


# ─── Settings ────────────────────────────────────────────────────────
def _default_dispatch_settings() -> Dict[str, Any]:
    return {
        "auto_assign_on_create": False,
        "rain_threshold_pct": DEFAULT_RAIN_THRESHOLD,
        "wind_threshold_mph": DEFAULT_WIND_THRESHOLD,
        "weather_reschedule_mode": "manual",  # or "auto"
        "batch_layout": "3up",  # for checks — belongs to checks but
                                    # co-located under `settings.dispatch`
                                    # scope not required. The checks router
                                    # reads `settings.checks.batch_layout`.
    }


async def _get_settings(tenant_id: str) -> Dict[str, Any]:
    t = await db.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}
    stored = (t.get("settings") or {}).get("dispatch") or {}
    return {**_default_dispatch_settings(), **stored}


class DispatchSettingsPatch(BaseModel):
    auto_assign_on_create: Optional[bool] = None
    rain_threshold_pct: Optional[int] = None
    wind_threshold_mph: Optional[int] = None
    weather_reschedule_mode: Optional[str] = None


@router.get("/dispatch/settings")
async def get_dispatch_settings(user: dict = Depends(require_admin),
                                    tenant: dict = Depends(get_current_tenant)):
    return await _get_settings(tenant["id"])


@router.put("/dispatch/settings")
async def put_dispatch_settings(body: DispatchSettingsPatch,
                                    user: dict = Depends(require_admin),
                                    tenant: dict = Depends(get_current_tenant)):
    current = await _get_settings(tenant["id"])
    patch = {k: v for k, v in body.model_dump(exclude_unset=True).items()
              if v is not None}
    if patch.get("weather_reschedule_mode") not in (None, "manual", "auto"):
        raise HTTPException(422,
            "weather_reschedule_mode must be `manual` or `auto`")
    merged = {**current, **patch}
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {"settings.dispatch": merged}},
    )
    return merged


# ─── Auto-dispatch core ──────────────────────────────────────────────
async def _rank_techs_for_job(
    tenant_id: str, new_job: Dict[str, Any],
) -> List[Dict[str, Any]]:
    coords = _job_coords(new_job)
    if not coords:
        raise HTTPException(422,
            "Job has no coordinates; add lat/lng before dispatching")
    day_key = _today_key()
    # Active technicians in this tenant. `is_active` filter is best-effort.
    techs = await db.technicians.find(
        {"tenant_id": tenant_id, "is_active": {"$ne": False}},
        {"_id": 0, "id": 1, "user_id": 1, "name": 1, "email": 1,
          "preferred_service_types": 1},
    ).to_list(500)

    # Also include technicians who exist only in `users` (legacy).
    if not techs:
        users = await db.users.find(
            {"tenant_id": tenant_id, "role": "technician"},
            {"_id": 0, "id": 1, "name": 1, "email": 1,
              "preferred_service_types": 1},
        ).to_list(500)
        techs = [{"id": u["id"], "user_id": u["id"],
                    "name": u.get("name") or u.get("email"),
                    "email": u.get("email"),
                    "preferred_service_types":
                        u.get("preferred_service_types") or []}
                  for u in users]
    else:
        # `technicians` docs may lack preferences → fall back to user row.
        for te in techs:
            if te.get("preferred_service_types"):
                continue
            uid = te.get("user_id") or te.get("id")
            u = await db.users.find_one(
                {"id": uid, "tenant_id": tenant_id},
                {"_id": 0, "preferred_service_types": 1}) or {}
            te["preferred_service_types"] = (
                u.get("preferred_service_types") or [])

    from utils import not_deleted_filter as _nd
    # Today's existing jobs, grouped by tech.
    todays = await db.jobs.find(
        {"tenant_id": tenant_id,
          "status": {"$nin": ["cancelled", "completed"]}, **_nd()},
        {"_id": 0, "id": 1, "technician_id": 1,
          "scheduled_date": 1, "scheduled_start": 1,
          "site_lat": 1, "site_lng": 1, "lat": 1, "lng": 1},
    ).to_list(2000)
    todays = [j for j in todays if _scheduled_today(j, day_key)]

    # Hours left in the day, floor 1.
    now = datetime.now(timezone.utc)
    end_of_shift = now.replace(hour=17, minute=0, second=0, microsecond=0)
    if end_of_shift < now:
        end_of_shift = end_of_shift + timedelta(days=1)
    hours_left = max(1.0, (end_of_shift - now).total_seconds() / 3600)

    ranking: List[Dict[str, Any]] = []
    job_service_type = (new_job.get("service_type") or "").strip().lower()
    for t in techs:
        # A tech may be represented in `jobs.technician_id` either by its
        # own tech-table id OR by the user_id — accept both.
        my_ids = {x for x in (t.get("id"), t.get("user_id")) if x}
        mine = [j for j in todays if j.get("technician_id") in my_ids]
        stops_with_coords = [c for j in mine
                                 if (c := _job_coords(j)) is not None]
        if stops_with_coords:
            min_dist = min(_haversine_m(coords[0], coords[1], s[0], s[1])
                              for s in stops_with_coords)
            deciding = "nearest_existing_stop"
        else:
            min_dist = 0.0
            deciding = "empty_route_priority"
        time_pressure = len(mine) / hours_left
        raw_cost = min_dist + time_pressure * TIME_PRESSURE_WEIGHT

        prefs = [str(p).strip().lower()
                   for p in (t.get("preferred_service_types") or [])
                   if p]
        if not prefs:
            skill_mult = SKILL_MULT_NEUTRAL
            skill_match = "neutral"
        elif job_service_type and job_service_type in prefs:
            skill_mult = SKILL_MULT_EXACT
            skill_match = "exact"
        else:
            skill_mult = SKILL_MULT_OFF
            skill_match = "off_specialty"

        cost = raw_cost * skill_mult
        ranking.append({
            "tech_id": t.get("id"),
            "user_id": t.get("user_id") or t.get("id"),
            "tech_name": t.get("name") or t.get("email"),
            "cost": round(cost, 1),
            "raw_cost": round(raw_cost, 1),
            "skill_multiplier": skill_mult,
            "skill_match": skill_match,
            "preferred_service_types":
                t.get("preferred_service_types") or [],
            "min_distance_m": round(min_dist, 1),
            "existing_stops_today": len(mine),
            "hours_left": round(hours_left, 2),
            "deciding_factor": deciding,
        })
    ranking.sort(key=lambda r: r["cost"])
    return ranking


class AssignIn(BaseModel):
    job_id: str


@router.post("/dispatch/auto-assign")
async def auto_assign(body: AssignIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    job = await db.jobs.find_one(
        {"id": body.job_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    ranking = await _rank_techs_for_job(tenant["id"], job)
    if not ranking:
        raise HTTPException(409, "No active technicians available")
    winner = ranking[0]
    tech_doc = await db.technicians.find_one(
        {"id": winner["tech_id"], "tenant_id": tenant["id"]}, {"_id": 0})
    await db.jobs.update_one(
        {"id": body.job_id, "tenant_id": tenant["id"]},
        {"$set": {"technician_id": winner["tech_id"],
                    "technician_name": winner["tech_name"],
                    "assigned_to": winner["user_id"],
                    "technician_avatar":
                        (tech_doc or {}).get("avatar", ""),
                    "auto_assigned_at": now_iso(),
                    "updated_at": now_iso()}},
    )
    return {
        "assigned_to": winner["user_id"],
        "tech_id": winner["tech_id"],
        "tech_name": winner["tech_name"],
        "insertion_cost_meters": winner["cost"],
        "reasoning": ranking,
    }


@router.get("/dispatch/preview")
async def dispatch_preview(job_id: str = Query(...),
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    job = await db.jobs.find_one(
        {"id": job_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    ranking = await _rank_techs_for_job(tenant["id"], job)
    return {"reasoning": ranking,
             "would_assign_to": ranking[0] if ranking else None}


class ReassignIn(BaseModel):
    job_id: str
    user_id: str


@router.post("/dispatch/reassign-job",
              operation_id="dispatch.reassignJob")
async def dispatch_reassign(body: ReassignIn,
                                 user: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    job = await db.jobs.find_one(
        {"id": body.job_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    tech = await db.technicians.find_one(
        {"$or": [{"id": body.user_id}, {"user_id": body.user_id}],
          "tenant_id": tenant["id"]},
        {"_id": 0},
    ) or {}
    if not tech:
        user_row = await db.users.find_one(
            {"id": body.user_id, "tenant_id": tenant["id"]}, {"_id": 0})
        if not user_row:
            raise HTTPException(404, "Target user/technician not found")
        tech = {"id": user_row["id"],
                 "name": user_row.get("name") or user_row.get("email"),
                 "user_id": user_row["id"], "avatar": ""}
    await db.dispatch_audit.insert_one({
        "id": new_id(), "tenant_id": tenant["id"],
        "job_id": body.job_id,
        "prior_technician_id": job.get("technician_id"),
        "new_technician_id": tech.get("id"),
        "new_user_id": tech.get("user_id") or tech.get("id"),
        "reason": "manual_reassign",
        "by_user_id": user["id"], "ts": now_iso(),
    })
    await db.jobs.update_one(
        {"id": body.job_id, "tenant_id": tenant["id"]},
        {"$set": {"technician_id": tech.get("id"),
                    "assigned_to": tech.get("user_id") or tech.get("id"),
                    "technician_name": tech.get("name"),
                    "technician_avatar": tech.get("avatar", ""),
                    "reassigned_at": now_iso(),
                    "updated_at": now_iso()}},
    )
    return {"job_id": body.job_id,
             "assigned_to": tech.get("user_id") or tech.get("id"),
             "tech_name": tech.get("name")}


# ═══════════ WEATHER SCAN + RESCHEDULE ═══════════════════════════════

def _is_outdoor(job: Dict[str, Any]) -> bool:
    st = (job.get("service_type") or "").lower()
    if any(k in st for k in ("pool interior", "repair", "diagnostic",
                                 "warranty")):
        return False
    if any(k in st for k in OUTDOOR_TYPES):
        return True
    # Fallback: landscape/D2D/etc from title
    title = (job.get("title") or "").lower()
    return any(k in title for k in OUTDOOR_TYPES)


async def _forecast_for(lat: float, lng: float, days: int = 5,
                             tenant_id: Optional[str] = None) -> Dict[str, Any]:
    # Test/dev override: if a tenant has `settings.dispatch._test_forecast`
    # set to a dict of {date: {rain_prob, wind_mph}}, use it verbatim.
    # Documented purely for automated tests — never surface in the admin UI.
    if tenant_id:
        t = await db.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}
        override = (((t.get("settings") or {}).get("dispatch") or {})
                    .get("_test_forecast"))
        if isinstance(override, dict) and override:
            return override
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": lat, "longitude": lng,
                "daily": ("precipitation_probability_max,"
                             "wind_speed_10m_max,weather_code"),
                "wind_speed_unit": "mph", "timezone": "auto",
                "forecast_days": days,
            })
        if r.status_code >= 400:
            return {}
        d = (r.json() or {}).get("daily") or {}
        out: Dict[str, Dict[str, Any]] = {}
        for i, day in enumerate(d.get("time") or []):
            out[day] = {
                "date": day,
                "rain_prob":
                    (d.get("precipitation_probability_max") or [None])[i]
                    if i < len(d.get("precipitation_probability_max") or [])
                    else None,
                "wind_mph": (d.get("wind_speed_10m_max") or [None])[i]
                    if i < len(d.get("wind_speed_10m_max") or [])
                    else None,
            }
        return out
    except Exception as ex:
        logger.warning(f"Forecast failed: {ex}")
        return {}


def _next_dry_day(forecast: Dict[str, Any],
                    rain_thr: int, wind_thr: int,
                    after: str) -> Optional[str]:
    for day, w in sorted(forecast.items()):
        if day <= after: continue
        if ((w.get("rain_prob") or 0) < rain_thr
                and (w.get("wind_mph") or 0) < wind_thr):
            return day
    return None


@router.post("/dispatch/weather-scan")
async def weather_scan(user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    """Scan today's + tomorrow's outdoor jobs, propose reschedule for those
    exceeding the thresholds. In auto mode, actually moves them."""
    settings = await _get_settings(tenant["id"])
    rain_thr = int(settings["rain_threshold_pct"])
    wind_thr = int(settings["wind_threshold_mph"])
    mode = settings["weather_reschedule_mode"]

    today = _today_key()
    tomorrow = (datetime.now(timezone.utc).date()
                  + timedelta(days=1)).isoformat()
    from utils import not_deleted_filter as _nd
    jobs = await db.jobs.find(
        {"tenant_id": tenant["id"],
          "scheduled_date": {"$in": [today, tomorrow]},
          "status": {"$nin": ["cancelled", "completed"]},
          **_nd()},
        {"_id": 0},
    ).to_list(2000)
    outdoor = [j for j in jobs if _is_outdoor(j)]

    results: List[Dict[str, Any]] = []
    for j in outdoor:
        coords = _job_coords(j)
        if not coords:
            continue
        # Idempotency: skip if we've already proposed for this job/day.
        existing = await db.weather_reschedule_events.find_one({
            "tenant_id": tenant["id"], "job_id": j["id"],
            "original_date": j.get("scheduled_date"),
            "status": {"$in": ["proposed", "auto_applied"]},
        }, {"_id": 0})
        if existing:
            results.append({**existing, "skipped": "already_proposed"})
            continue

        fc = await _forecast_for(coords[0], coords[1], days=8,
                                       tenant_id=tenant["id"])
        day_forecast = fc.get(j.get("scheduled_date") or today) or {}
        rain = day_forecast.get("rain_prob") or 0
        wind = day_forecast.get("wind_mph") or 0
        if rain < rain_thr and wind < wind_thr:
            continue  # weather is fine

        proposed = _next_dry_day(fc, rain_thr, wind_thr,
                                     after=j.get("scheduled_date") or today)
        if not proposed:
            proposed = (datetime.strptime(
                j.get("scheduled_date") or today, "%Y-%m-%d")
                + timedelta(days=3)).date().isoformat()

        event = {
            "id": new_id(),
            "tenant_id": tenant["id"],
            "job_id": j["id"],
            "original_date": j.get("scheduled_date"),
            "proposed_date": proposed,
            "actual_date": None,
            "rain_prob_pct": rain,
            "wind_mph": wind,
            "mode": mode,
            "status": "proposed",
            "decided_by": None,
            "decided_at": None,
            "ts": now_iso(),
        }

        if mode == "auto":
            await db.jobs.update_one(
                {"id": j["id"], "tenant_id": tenant["id"]},
                {"$set": {"scheduled_date": proposed,
                            "auto_weather_rescheduled_at": now_iso(),
                            "updated_at": now_iso()}},
            )
            event["status"] = "auto_applied"
            event["actual_date"] = proposed
            event["decided_at"] = now_iso()

        await db.weather_reschedule_events.insert_one(dict(event))
        event.pop("_id", None)
        results.append(event)
    return {"scanned": len(outdoor), "affected": len(results),
             "events": results, "mode": mode}


async def scheduled_weather_scan_all():
    """Runs across every tenant. Called by APScheduler daily."""
    tenants = await db.tenants.find({}, {"_id": 0, "id": 1}).to_list(500)
    for t in tenants:
        try:
            # emulate a request-scoped call
            settings = await _get_settings(t["id"])
            if settings["weather_reschedule_mode"] not in ("manual", "auto"):
                continue
            # Direct call — bypass FastAPI dep injection.
            fake_user = {"id": "system", "role": "super_admin"}
            fake_tenant = {"id": t["id"]}
            await weather_scan.__wrapped__(user=fake_user,
                                                tenant=fake_tenant) \
                if hasattr(weather_scan, "__wrapped__") else \
                await weather_scan(user=fake_user, tenant=fake_tenant)
        except Exception as ex:
            logger.warning(f"weather_scan cron failed for {t['id']}: {ex}")


@router.get("/dispatch/weather-events")
async def list_weather_events(status: Optional[str] = None,
                                  user: dict = Depends(require_admin),
                                  tenant: dict = Depends(get_current_tenant)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if status: q["status"] = status
    rows = await db.weather_reschedule_events.find(q, {"_id": 0}).sort(
        "ts", -1).to_list(500)
    return {"items": rows, "total": len(rows)}


class DecisionIn(BaseModel):
    override_date: Optional[str] = None


@router.post("/dispatch/weather-events/{eid}/accept")
async def accept_weather_event(eid: str, body: DecisionIn = DecisionIn(),
                                     user: dict = Depends(require_admin),
                                     tenant: dict = Depends(get_current_tenant)):
    ev = await db.weather_reschedule_events.find_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not ev:
        raise HTTPException(404, "Event not found")
    if ev["status"] not in ("proposed",):
        raise HTTPException(409, f"Event is {ev['status']}, not proposed")
    new_date = body.override_date or ev["proposed_date"]
    await db.jobs.update_one(
        {"id": ev["job_id"], "tenant_id": tenant["id"]},
        {"$set": {"scheduled_date": new_date,
                    "manual_weather_rescheduled_at": now_iso(),
                    "updated_at": now_iso()}},
    )
    await db.weather_reschedule_events.update_one(
        {"id": eid, "tenant_id": tenant["id"]},
        {"$set": {"status": "accepted", "actual_date": new_date,
                    "decided_by": user["id"],
                    "decided_at": now_iso()}},
    )
    return await db.weather_reschedule_events.find_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.post("/dispatch/weather-events/{eid}/reject")
async def reject_weather_event(eid: str,
                                     user: dict = Depends(require_admin),
                                     tenant: dict = Depends(get_current_tenant)):
    ev = await db.weather_reschedule_events.find_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not ev:
        raise HTTPException(404, "Event not found")
    if ev["status"] != "proposed":
        raise HTTPException(409, f"Event is {ev['status']}")
    await db.weather_reschedule_events.update_one(
        {"id": eid, "tenant_id": tenant["id"]},
        {"$set": {"status": "rejected",
                    "decided_by": user["id"],
                    "decided_at": now_iso()}},
    )
    return await db.weather_reschedule_events.find_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"_id": 0})


# ═══════════ Auto-assign-on-create HOOK ═════════════════════════════

async def maybe_auto_assign_on_create(tenant_id: str,
                                            job_doc: Dict[str, Any],
                                            actor_user_id: str) -> Optional[Dict[str, Any]]:
    """Callable from jobs.create_job. Returns the assignment result or
    None if disabled / not applicable."""
    settings = await _get_settings(tenant_id)
    if not settings.get("auto_assign_on_create"):
        return None
    if job_doc.get("technician_id") or job_doc.get("assigned_to"):
        return None
    try:
        ranking = await _rank_techs_for_job(tenant_id, job_doc)
    except HTTPException:
        return None
    if not ranking:
        return None
    winner = ranking[0]
    tech_doc = await db.technicians.find_one(
        {"id": winner["tech_id"], "tenant_id": tenant_id}, {"_id": 0}) or {}
    await db.jobs.update_one(
        {"id": job_doc["id"], "tenant_id": tenant_id},
        {"$set": {"technician_id": winner["tech_id"],
                    "technician_name": winner["tech_name"],
                    "assigned_to": winner["user_id"],
                    "technician_avatar": tech_doc.get("avatar", ""),
                    "auto_assigned_at": now_iso(),
                    "auto_assigned_by": actor_user_id,
                    "updated_at": now_iso()}},
    )
    return {"assigned_to": winner["user_id"],
             "tech_id": winner["tech_id"],
             "tech_name": winner["tech_name"],
             "insertion_cost_meters": winner["cost"]}


# ═══════════ Phase 26 polish · skill profile endpoints ═════════════════

@router.get("/dispatch/technician-skills")
async def list_technician_skills(user: dict = Depends(require_admin),
                                       tenant: dict = Depends(get_current_tenant)):
    """Every active technician's skill profile — for the settings panel.

    Phase 34a fix — the previous version returned duplicate rows when a
    tech had entries in BOTH `technicians` and `users` (some legacy
    seed data shipped `technicians` rows with `user_id=None`, so the
    id-only dedup set never merged them). Now we dedup on email (with
    id/user_id as a secondary key) and always PREFER the `users` row
    when both exist — that row has the richer profile.
    """
    tenant_id = tenant["id"]

    # Canonical set — users with role "technician".
    urows = await db.users.find(
        {"tenant_id": tenant_id, "role": "technician"},
        {"_id": 0, "id": 1, "name": 1, "email": 1,
          "preferred_service_types": 1},
    ).to_list(500)

    by_email: Dict[str, Dict[str, Any]] = {}
    by_uid: Dict[str, Dict[str, Any]] = {}
    for u in urows:
        row = {
            "id": u["id"],
            "user_id": u["id"],
            "name": u.get("name") or u.get("email"),
            "email": (u.get("email") or "").lower() or None,
            "preferred_service_types": u.get("preferred_service_types") or [],
        }
        if row["email"]:
            by_email[row["email"]] = row
        by_uid[u["id"]] = row

    # Merge/append rows from the `technicians` collection.
    tech_rows = await db.technicians.find(
        {"tenant_id": tenant_id, "is_active": {"$ne": False}},
        {"_id": 0, "id": 1, "user_id": 1, "name": 1, "email": 1,
          "preferred_service_types": 1},
    ).to_list(500)

    for te in tech_rows:
        email = (te.get("email") or "").lower() or None
        uid = te.get("user_id")
        existing = None
        if email and email in by_email:
            existing = by_email[email]
        elif uid and uid in by_uid:
            existing = by_uid[uid]

        if existing is not None:
            # Prefer users' fields, fall back to technicians for anything empty.
            if not existing["preferred_service_types"]:
                existing["preferred_service_types"] = (
                    te.get("preferred_service_types") or []
                )
            if not existing.get("name"):
                existing["name"] = te.get("name")
            # keep the users.id as the canonical id (already set)
            continue

        # Standalone technician (no user login) — include as-is.
        row = {
            "id": te.get("id"),
            "user_id": te.get("user_id"),
            "name": te.get("name") or te.get("email"),
            "email": email,
            "preferred_service_types": te.get("preferred_service_types") or [],
        }
        if email:
            by_email[email] = row
        else:
            # No email → key on tech id to still dedup future scans.
            by_email[f"__tech_id__:{te.get('id')}"] = row

    items = list(by_email.values())
    return {"items": items, "total": len(items)}


class SkillProfilePatch(BaseModel):
    preferred_service_types: List[str] = []


@router.patch("/users/{uid}/skill-profile")
async def patch_skill_profile(uid: str, body: SkillProfilePatch,
                                    user: dict = Depends(require_admin),
                                    tenant: dict = Depends(get_current_tenant)):
    prefs = [str(p).strip().lower() for p in body.preferred_service_types
               if p and str(p).strip()]
    n1 = await db.users.update_one(
        {"id": uid, "tenant_id": tenant["id"]},
        {"$set": {"preferred_service_types": prefs,
                    "updated_at": now_iso()}},
    )
    await db.technicians.update_many(
        {"tenant_id": tenant["id"],
          "$or": [{"id": uid}, {"user_id": uid}]},
        {"$set": {"preferred_service_types": prefs,
                    "updated_at": now_iso()}},
    )
    if n1.matched_count == 0 and \
            await db.technicians.count_documents(
                {"tenant_id": tenant["id"],
                  "$or": [{"id": uid}, {"user_id": uid}]}) == 0:
        raise HTTPException(404, "User or technician not found")
    return {"user_id": uid, "preferred_service_types": prefs}

