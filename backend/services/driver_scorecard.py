"""Phase G5d · Feb-2026 — Driver scorecard aggregation.

Pure DB-backed derivation from G0-G5c data:
  * gps_pings         → estimated_miles, days_active, total_pings_count,
                         total_driving_time_s (implicit).
  * driver_stops      → stops_count, avg_stop_duration_s,
                         total_stopped_time_s, attribution_coverage,
                         unique_jobs / unique_customers, on_time rate.
  * jobs.scheduled_start (if present) drives on-time arrival delta.

No behavior-signal inference (harsh braking, speed).

Cache
-----
Result cached in ``db.scorecard_cache`` with a 5-minute TTL keyed by
``(tenant_id, range_label, department)``. Falls through on cache miss
or when a custom range is passed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import db, logger
from services.geofence_engine import haversine_m
from utils import now_iso

# ── Config ──────────────────────────────────────────────────────────

SCORECARD_WEIGHTS: Dict[str, float] = {
    "stops_count": 15.0,
    "on_time_arrival_rate": 25.0,
    "unique_jobs_attributed": 20.0,
    "days_active": 15.0,
    "attribution_coverage": 15.0,
    "idle_penalty_max": 10.0,   # subtracted (max) when avg stop > 4hrs.
    "base_offset": 10.0,        # so a tech with zero data doesn't sit at 0.
}
_STOPS_SOFT_CAP = 40
_JOBS_SOFT_CAP = 15
_DAYS_SOFT_CAP = 5
_ON_TIME_WINDOW_S = 15 * 60      # 15 minutes considered "on time".
_OFFLINE_GAP_S = 15 * 60         # ping gaps >15 min not counted as driving.
_IDLE_STOP_THRESHOLD_S = 4 * 3600  # avg stop > 4h → idle-penalty applies.
_CACHE_TTL_S = 300


# ── Range resolver ──────────────────────────────────────────────────

def resolve_range(range_label: str,
                    from_iso: Optional[str] = None,
                    to_iso: Optional[str] = None
                    ) -> Tuple[datetime, datetime, str]:
    now = datetime.now(timezone.utc)
    if range_label == "custom":
        if not from_iso or not to_iso:
            raise ValueError("custom range requires from + to")
        f = datetime.fromisoformat(from_iso.replace("Z", "+00:00"))
        t = datetime.fromisoformat(to_iso.replace("Z", "+00:00"))
        return f, t, "Custom"
    if range_label == "last_week":
        # Monday-to-Monday of the previous ISO week.
        today = now.date()
        monday_this = today - timedelta(days=today.weekday())
        monday_last = monday_this - timedelta(days=7)
        f = datetime(monday_last.year, monday_last.month, monday_last.day,
                      tzinfo=timezone.utc)
        t = f + timedelta(days=7) - timedelta(seconds=1)
        return f, t, "Last Week"
    if range_label == "month_to_date":
        f = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return f, now, "Month to Date"
    # Default: this_week
    today = now.date()
    monday = today - timedelta(days=today.weekday())
    f = datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)
    return f, now, "This Week"


# ── Metric computation for a single (tech, window) ──────────────────

async def _stops_metrics(tenant_id: str, uid: str,
                          f_iso: str, t_iso: str) -> Dict[str, Any]:
    stops: List[Dict[str, Any]] = []
    async for s in db.driver_stops.find(
            {"tenant_id": tenant_id, "user_id": uid,
              "started_at": {"$gte": f_iso, "$lte": t_iso}},
            {"_id": 0, "duration_s": 1, "attribution_status": 1,
              "attributed_job_id": 1, "attributed_customer_id": 1,
              "started_at": 1}):
        stops.append(s)
    total = len(stops)
    dur_sum = sum(int(s.get("duration_s") or 0) for s in stops)
    avg = int(dur_sum / total) if total else 0
    linked_stops = [s for s in stops
                     if s.get("attribution_status")
                        in ("auto_linked", "manual_linked")]
    unique_jobs = len({s.get("attributed_job_id")
                       for s in linked_stops if s.get("attributed_job_id")})
    unique_customers = len({s.get("attributed_customer_id")
                             for s in linked_stops
                             if s.get("attributed_customer_id")})
    coverage = (len(linked_stops) / total) if total else 0.0
    return {
        "stops": stops,
        "linked_stops": linked_stops,
        "stops_count": total,
        "avg_stop_duration_s": avg,
        "total_stopped_time_s": dur_sum,
        "unique_jobs_attributed": unique_jobs,
        "unique_customers_attributed": unique_customers,
        "attribution_coverage": round(coverage, 3),
    }


async def _on_time_rate(tenant_id: str,
                          linked_stops: List[Dict[str, Any]]
                          ) -> Optional[float]:
    if not linked_stops:
        return None
    job_ids = [s.get("attributed_job_id") for s in linked_stops
               if s.get("attributed_job_id")]
    if not job_ids:
        return None
    jobs_by_id: Dict[str, Dict[str, Any]] = {}
    async for j in db.jobs.find(
            {"tenant_id": tenant_id, "id": {"$in": job_ids}},
            {"_id": 0, "id": 1, "scheduled_start": 1,
              "scheduled_time": 1}):
        jobs_by_id[j["id"]] = j
    considered = 0
    on_time = 0
    for s in linked_stops:
        j = jobs_by_id.get(s.get("attributed_job_id") or "")
        if not j:
            continue
        sched = j.get("scheduled_start") or j.get("scheduled_time")
        if not sched:
            continue
        try:
            sched_dt = datetime.fromisoformat(
                str(sched).replace("Z", "+00:00"))
            started_dt = datetime.fromisoformat(
                str(s.get("started_at")).replace("Z", "+00:00"))
        except Exception:                                                # noqa: BLE001
            continue
        considered += 1
        delta = (started_dt - sched_dt).total_seconds()
        if delta <= _ON_TIME_WINDOW_S:
            on_time += 1
    if not considered:
        return None
    return round(on_time / considered, 3)


async def _ping_metrics(tenant_id: str, uid: str,
                         f_iso: str, t_iso: str) -> Dict[str, Any]:
    total = 0
    miles = 0.0
    driving_s = 0
    active_days: set = set()
    prev = None
    async for p in db.gps_pings.find(
            {"tenant_id": tenant_id, "user_id": uid,
              "captured_at": {"$gte": f_iso, "$lte": t_iso}},
            {"_id": 0, "lat": 1, "lon": 1, "captured_at": 1}
            ).sort("captured_at", 1):
        total += 1
        cap = p.get("captured_at") or ""
        if isinstance(cap, str) and len(cap) >= 10:
            active_days.add(cap[:10])
        if prev is not None:
            try:
                gap = (datetime.fromisoformat(str(cap).replace("Z","+00:00"))
                       - datetime.fromisoformat(
                            str(prev["captured_at"]).replace("Z","+00:00"))
                       ).total_seconds()
            except Exception:                                            # noqa: BLE001
                gap = 0
            if 0 < gap <= _OFFLINE_GAP_S:
                driving_s += int(gap)
                d_m = haversine_m(float(prev["lat"]), float(prev["lon"]),
                                   float(p["lat"]), float(p["lon"]))
                miles += d_m / 1609.344
        prev = p
    return {
        "total_pings_count": total,
        "estimated_miles": round(miles, 1),
        "days_active": len(active_days),
        "total_driving_time_s": driving_s,
    }


def _composite_score(m: Dict[str, Any]) -> Tuple[int, int]:
    """Return (score, idle_penalty). Score is int 0-100."""
    W = SCORECARD_WEIGHTS
    s = W["base_offset"]
    s += W["stops_count"] * min(1.0, (m["stops_count"] or 0) / _STOPS_SOFT_CAP)
    otr = m.get("on_time_arrival_rate")
    if otr is not None:
        s += W["on_time_arrival_rate"] * otr
    s += W["unique_jobs_attributed"] * min(
        1.0, (m["unique_jobs_attributed"] or 0) / _JOBS_SOFT_CAP)
    s += W["days_active"] * min(1.0, (m["days_active"] or 0) / _DAYS_SOFT_CAP)
    s += W["attribution_coverage"] * (m.get("attribution_coverage") or 0.0)
    # Idle penalty: linear from 0 at avg=4h to max at avg=8h.
    avg = m.get("avg_stop_duration_s") or 0
    penalty = 0
    if avg > _IDLE_STOP_THRESHOLD_S:
        excess = min(1.0, (avg - _IDLE_STOP_THRESHOLD_S) / _IDLE_STOP_THRESHOLD_S)
        penalty = int(round(W["idle_penalty_max"] * excess))
        s -= penalty
    return max(0, min(100, int(round(s)))), penalty


async def compute_scorecard_for_user(tenant_id: str, uid: str,
                                       user_name: str,
                                       department: Optional[str],
                                       role: Optional[str],
                                       f_dt: datetime, t_dt: datetime
                                       ) -> Dict[str, Any]:
    f_iso = f_dt.isoformat().replace("+00:00", "Z")
    t_iso = t_dt.isoformat().replace("+00:00", "Z")
    stops_m = await _stops_metrics(tenant_id, uid, f_iso, t_iso)
    on_time = await _on_time_rate(tenant_id, stops_m["linked_stops"])
    pings_m = await _ping_metrics(tenant_id, uid, f_iso, t_iso)
    metrics = {
        "stops_count": stops_m["stops_count"],
        "avg_stop_duration_s": stops_m["avg_stop_duration_s"],
        "total_stopped_time_s": stops_m["total_stopped_time_s"],
        "total_driving_time_s": pings_m["total_driving_time_s"],
        "total_pings_count": pings_m["total_pings_count"],
        "unique_jobs_attributed": stops_m["unique_jobs_attributed"],
        "unique_customers_attributed": stops_m["unique_customers_attributed"],
        "on_time_arrival_rate": on_time,
        "estimated_miles": pings_m["estimated_miles"],
        "days_active": pings_m["days_active"],
        "attribution_coverage": stops_m["attribution_coverage"],
    }
    score, penalty = _composite_score(metrics)
    metrics["idle_penalty"] = penalty
    return {
        "user_id": uid,
        "user_name": user_name,
        "role": role or "technician",
        "department": department or "",
        "score": score,
        "metrics": metrics,
    }


# ── Leaderboard driver ──────────────────────────────────────────────

async def compute_leaderboard(tenant_id: str,
                                range_label: str,
                                from_iso: Optional[str],
                                to_iso: Optional[str],
                                department: Optional[str],
                                use_cache: bool = True
                                ) -> Dict[str, Any]:
    f_dt, t_dt, label = resolve_range(range_label, from_iso, to_iso)
    cache_key = f"{tenant_id}::{range_label}::{department or ''}"

    if use_cache and range_label != "custom":
        cached = await db.scorecard_cache.find_one(
            {"key": cache_key}, {"_id": 0})
        if cached:
            age = (datetime.now(timezone.utc)
                    - datetime.fromisoformat(
                        cached["as_of"].replace("Z", "+00:00"))
                   ).total_seconds()
            if age < _CACHE_TTL_S:
                return cached["payload"]

    # Collect eligible technicians (role in {technician, tech_lead}).
    q_users: Dict[str, Any] = {"tenant_id": tenant_id,
                                 "role": {"$in": ["technician",
                                                    "tech_lead"]}}
    if department:
        q_users["department"] = department
    users: List[Dict[str, Any]] = []
    async for u in db.users.find(q_users, {"_id": 0, "id": 1, "name": 1,
                                             "email": 1, "role": 1,
                                             "department": 1}).limit(300):
        users.append(u)

    rows: List[Dict[str, Any]] = []
    for u in users:
        r = await compute_scorecard_for_user(
            tenant_id, u["id"],
            u.get("name") or u.get("email") or "",
            u.get("department"), u.get("role"),
            f_dt, t_dt)
        rows.append(r)

    rows.sort(key=lambda r: (-r["score"],
                              -r["metrics"]["unique_jobs_attributed"]))
    for idx, r in enumerate(rows):
        r["rank"] = idx + 1
    rows = rows[:100]

    payload = {
        "range": {
            "from": f_dt.isoformat().replace("+00:00", "Z"),
            "to": t_dt.isoformat().replace("+00:00", "Z"),
            "label": label,
        },
        "rows": rows,
    }
    if range_label != "custom":
        await db.scorecard_cache.update_one(
            {"key": cache_key},
            {"$set": {"key": cache_key,
                      "as_of": now_iso(),
                      "payload": payload}},
            upsert=True)
    return payload


# ── Per-user detail w/ 8-week trend ─────────────────────────────────

async def compute_user_detail(tenant_id: str, uid: str,
                                range_label: str,
                                from_iso: Optional[str],
                                to_iso: Optional[str]
                                ) -> Dict[str, Any]:
    u = await db.users.find_one({"tenant_id": tenant_id, "id": uid},
                                 {"_id": 0, "id": 1, "name": 1,
                                   "email": 1, "role": 1, "department": 1})
    if not u:
        return {}
    f_dt, t_dt, label = resolve_range(range_label, from_iso, to_iso)
    row = await compute_scorecard_for_user(
        tenant_id, uid, u.get("name") or u.get("email") or "",
        u.get("department"), u.get("role"), f_dt, t_dt)

    # 8-week trend — always compute (uncached to keep code simple).
    now = datetime.now(timezone.utc)
    today = now.date()
    monday_this = today - timedelta(days=today.weekday())
    trend: List[Dict[str, Any]] = []
    for i in range(7, -1, -1):
        start = monday_this - timedelta(days=7 * i)
        end = start + timedelta(days=7) - timedelta(seconds=1)
        f = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
        t = datetime(end.year, end.month, end.day, 23, 59, 59,
                      tzinfo=timezone.utc)
        weekly = await compute_scorecard_for_user(
            tenant_id, uid, u.get("name") or u.get("email") or "",
            u.get("department"), u.get("role"), f, t)
        trend.append({"week_start": start.isoformat(),
                      "score": weekly["score"]})

    return {"range": {"from": f_dt.isoformat().replace("+00:00","Z"),
                       "to":   t_dt.isoformat().replace("+00:00","Z"),
                       "label": label},
             "row": row, "trend": trend}
