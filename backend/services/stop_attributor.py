"""Phase G5b · Feb-2026 — Stop → Job proximity attributor.

Pure-ish orchestration (uses Motor for DB) — no HTTP, no reverse
geocoding. Given a completed ``driver_stops`` row and the tenant's
attribution tuning, find the closest same-day scheduled job whose
customer/property has known lat/lon and link them.

Design notes
------------
* No Mapbox / no external calls. Jobs without cached geocoded coords
  are skipped (not attributed). The G3 reverse-geocoder handles the
  live-position address labels; this batch attributor stays offline.
* Batch is idempotent w.r.t. ``manual_linked`` and ``unlinked`` rows —
  we never overwrite a human's decision.
* Haversine reused from ``services.geofence_engine`` to keep one
  source of truth for the distance formula.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import db, logger
from services.geofence_engine import haversine_m
from utils import now_iso

_SCHEDULED_STATUSES = ("scheduled", "assigned", "in_progress", "pending")
_MANUAL_STATUSES = {"manual_linked", "unlinked"}


# ── Date helpers ────────────────────────────────────────────────────

def _parse_iso(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        ts = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _stop_day_yyyy_mm_dd(stop_time: Any) -> Optional[str]:
    ts = _parse_iso(stop_time)
    if not ts:
        return None
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%d")


# ── Settings ────────────────────────────────────────────────────────

_DEFAULTS = {
    "proximity_threshold_m": 100,
    "same_day_only": True,
    "require_scheduled_status": True,
}


async def get_settings(tenant_id: str) -> Dict[str, Any]:
    row = await db.stop_attribution_meta.find_one(
        {"tenant_id": tenant_id}, {"_id": 0})
    if not row:
        return {**_DEFAULTS, "tenant_id": tenant_id}
    out = {**_DEFAULTS, **row}
    # Ensure canonical types even when a legacy field slipped through.
    out["proximity_threshold_m"] = int(out.get("proximity_threshold_m")
                                        or _DEFAULTS["proximity_threshold_m"])
    out["same_day_only"] = bool(out.get("same_day_only",
                                          _DEFAULTS["same_day_only"]))
    out["require_scheduled_status"] = bool(
        out.get("require_scheduled_status",
                _DEFAULTS["require_scheduled_status"]))
    return out


# ── Address resolution: job → (lat, lon) ────────────────────────────

def job_address_latlon_from_docs(job: Dict[str, Any],
                                  customer: Optional[Dict[str, Any]] = None,
                                  prop: Optional[Dict[str, Any]] = None
                                  ) -> Optional[Tuple[float, float]]:
    """Pull the best-known lat/lon for a job, using pre-loaded customer
    and property docs. Returns None when nothing is geocoded."""
    # Job-level lat/lon (rare — very old data).
    if job.get("lat") is not None and job.get("lon") is not None:
        try:
            return float(job["lat"]), float(job["lon"])
        except (TypeError, ValueError):
            pass
    # Property-level geocoded coords (properties.lat / properties.lng).
    if prop:
        if prop.get("lat") is not None and prop.get("lng") is not None:
            try:
                return float(prop["lat"]), float(prop["lng"])
            except (TypeError, ValueError):
                pass
    # Customer-level geocoded coords (customers.service_lat/service_lng).
    if customer:
        if (customer.get("service_lat") is not None
                and customer.get("service_lng") is not None):
            try:
                return (float(customer["service_lat"]),
                        float(customer["service_lng"]))
            except (TypeError, ValueError):
                pass
    return None


# ── Candidate jobs ──────────────────────────────────────────────────

async def find_candidate_jobs(*, tenant_id: str, user_id: str,
                                stop_time: Any,
                                same_day_only: bool,
                                require_scheduled_status: bool
                                ) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if same_day_only:
        day = _stop_day_yyyy_mm_dd(stop_time)
        if day:
            # Jobs can store scheduled_date as bare 'YYYY-MM-DD' or
            # 'YYYY-MM-DDT...'. Regex-anchor to the day so both match.
            q["scheduled_date"] = {"$regex": f"^{day}"}
    if require_scheduled_status:
        q["status"] = {"$in": list(_SCHEDULED_STATUSES)}

    # Prefer jobs assigned to the same tech, but don't require it. If
    # a technician_id exists on any candidate we bias toward it below.
    # Sort by scheduled_date desc so recent jobs come first when we
    # cap at the fan-out limit — old jobs shouldn't crowd out today's
    # scheduled work.
    jobs: List[Dict[str, Any]] = []
    async for j in (db.jobs.find(q, {"_id": 0})
                    .sort("scheduled_date", -1)
                    .limit(2000)):
        jobs.append(j)
    return jobs


# ── Attribution ─────────────────────────────────────────────────────

async def attribute_stop(stop: Dict[str, Any],
                          settings: Dict[str, Any]
                          ) -> Dict[str, Any]:
    """Return the attribution decision for a single stop. Does NOT
    write to the DB — the caller decides when to persist."""
    tenant_id = stop.get("tenant_id") or ""
    user_id = stop.get("user_id") or ""
    stop_lat = stop.get("center_lat")
    stop_lon = stop.get("center_lon")
    if (not tenant_id or stop_lat is None or stop_lon is None):
        return {"status": "no_match"}

    threshold = int(settings.get("proximity_threshold_m") or 100)
    same_day = bool(settings.get("same_day_only", True))
    req_sched = bool(settings.get("require_scheduled_status", True))

    candidates = await find_candidate_jobs(
        tenant_id=tenant_id, user_id=user_id,
        stop_time=stop.get("started_at"),
        same_day_only=same_day,
        require_scheduled_status=req_sched)

    if not candidates:
        return {"status": "no_match"}

    # Preload customers/properties in one round-trip each to avoid an
    # N+1 fan-out on large candidate sets.
    cids = list({c.get("customer_id") for c in candidates
                  if c.get("customer_id")})
    pids = list({c.get("property_id") for c in candidates
                  if c.get("property_id")})
    cust_map: Dict[str, Dict[str, Any]] = {}
    prop_map: Dict[str, Dict[str, Any]] = {}
    if cids:
        async for c in db.customers.find(
            {"tenant_id": tenant_id, "id": {"$in": cids}},
            {"_id": 0, "id": 1, "service_lat": 1, "service_lng": 1,
              "name": 1},
        ):
            cust_map[c["id"]] = c
    if pids:
        async for p in db.properties.find(
            {"tenant_id": tenant_id, "id": {"$in": pids}},
            {"_id": 0, "id": 1, "lat": 1, "lng": 1},
        ):
            prop_map[p["id"]] = p

    best: Optional[Tuple[float, Dict[str, Any]]] = None
    for j in candidates:
        ll = job_address_latlon_from_docs(
            j,
            customer=cust_map.get(j.get("customer_id") or ""),
            prop=prop_map.get(j.get("property_id") or ""))
        if not ll:
            continue
        dist = haversine_m(float(stop_lat), float(stop_lon), ll[0], ll[1])
        if dist > threshold:
            continue
        # Bias by tech-match when equal-ish distance: a job assigned
        # to this tech wins ties by a small epsilon.
        adj = dist - (5.0 if j.get("technician_id") == user_id else 0.0)
        if best is None or adj < best[0]:
            best = (adj, {"job": j, "distance": dist})

    if best is None:
        return {"status": "no_match"}
    j = best[1]["job"]
    return {
        "status": "auto_linked",
        "job_id": j["id"],
        "customer_id": j.get("customer_id"),
        "distance_m": float(round(best[1]["distance"], 2)),
    }


# ── Batch driver ────────────────────────────────────────────────────

async def run_attribution_batch(tenant_id: str,
                                  limit: int = 500) -> Dict[str, Any]:
    """Attribute every ``pending`` stop for the tenant (capped at
    ``limit`` per invocation). Returns per-status counts. Manual
    rows are never touched here — the caller filter enforces it."""
    settings = await get_settings(tenant_id)
    counts = {"processed": 0, "auto_linked": 0, "no_match": 0, "skipped": 0}

    # Pull pending stops. Rows without ``attribution_status`` are also
    # implicitly pending — the $in matches both null and "pending".
    query = {
        "tenant_id": tenant_id,
        "$or": [
            {"attribution_status": {"$exists": False}},
            {"attribution_status": None},
            {"attribution_status": "pending"},
        ],
    }
    pending: List[Dict[str, Any]] = []
    async for s in db.driver_stops.find(query, {"_id": 0}).limit(limit):
        pending.append(s)

    for s in pending:
        counts["processed"] += 1
        decision = await attribute_stop(s, settings)
        upd: Dict[str, Any] = {
            "attribution_status": decision.get("status") or "no_match",
            "attribution_updated_at": now_iso(),
            "attribution_updated_by_user_id": None,
        }
        if decision.get("status") == "auto_linked":
            upd["attributed_job_id"] = decision["job_id"]
            upd["attributed_customer_id"] = decision.get("customer_id")
            upd["attribution_distance_m"] = decision["distance_m"]
            counts["auto_linked"] += 1
        else:
            # Clear any stale link but keep the status = no_match.
            upd["attributed_job_id"] = None
            upd["attributed_customer_id"] = None
            upd["attribution_distance_m"] = None
            counts["no_match"] += 1
        await db.driver_stops.update_one(
            {"id": s["id"], "tenant_id": tenant_id},
            {"$set": upd})

    return counts


async def run_attribution_batch_all_tenants() -> Dict[str, Any]:
    """Cron entrypoint — iterate every tenant with GPS enabled and run
    attribution. Failure in one tenant does not stop the others."""
    totals = {"tenants": 0, "processed": 0,
              "auto_linked": 0, "no_match": 0}
    async for st in db.gps_settings.find({"enabled": True},
                                            {"_id": 0, "tenant_id": 1}):
        tid = st.get("tenant_id")
        if not tid:
            continue
        totals["tenants"] += 1
        try:
            c = await run_attribution_batch(tid)
            for k in ("processed", "auto_linked", "no_match"):
                totals[k] += c.get(k, 0)
            logger.info(
                "[stop_attribute] tenant=%s processed=%s auto=%s no_match=%s",
                tid, c["processed"], c["auto_linked"], c["no_match"])
        except Exception as e:                                            # noqa: BLE001
            logger.warning("[stop_attribute] tenant=%s failed: %s", tid, e)
    return totals
