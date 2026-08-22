"""Feb-2026 · P37d — Dispatcher GPS Auto-Start audit report.

Surfaces the operational health of the P37a-c GPS auto-start feature
so dispatch can tune the 75m radius default or diagnose systematic
consent / throttle issues.

Data source: ``audit_logs`` collection, filtered by
``event == "job_timer_auto_start"``. Every /arrive outcome
(started + 5 failure branches + already_running) writes an entry
here as of the P37d audit-log extension.

RBAC: super_admin / admin / manager. Techs cannot see fleet-level
distance stats.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter()

_ALLOWED_ROLES = {"super_admin", "admin", "manager"}


def _iso_default_from() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()


def _iso_default_to() -> str:
    return datetime.now(timezone.utc).isoformat()


def _median(values: list[float]) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return round((s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0), 1)


def _percentile(values: list[float], p: float) -> Optional[float]:
    """Nearest-rank percentile — matches ops-team intuition better
    than linear interpolation for the small sample sizes typical of
    a dispatcher's daily audit slice."""
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return round(s[k], 1)


@router.get("/reports/gps-auto-start-audit")
async def gps_auto_start_audit(
    from_: Optional[str] = Query(None, alias="from",
        description="ISO datetime — default 30d ago"),
    to: Optional[str] = Query(None,
        description="ISO datetime — default now"),
    tech_id: Optional[str] = Query(None,
        description="Filter to a single technician_id"),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if user.get("role") not in _ALLOWED_ROLES:
        raise HTTPException(403, "Not allowed")

    from_iso = from_ or _iso_default_from()
    to_iso = to or _iso_default_to()

    q: dict = {
        "tenant_id": tenant["id"],
        "event": "job_timer_auto_start",
        "at": {"$gte": from_iso, "$lte": to_iso},
    }
    if tech_id:
        q["payload.technician_id"] = tech_id

    rows: list[dict] = []
    try:
        cursor = db.audit_logs.find(q, {"_id": 0}).sort("at", -1)
        async for r in cursor:
            rows.append(r)
    except Exception as e:
        logger.warning(f"[p37d] audit query failed: {e}")

    # ── Outcome tally + distance percentiles ────────────────────────
    outcomes = {
        "started": 0, "throttled": 0, "out_of_radius": 0,
        "consent_required": 0, "feature_disabled": 0,
        "already_running": 0, "job_completed": 0,
    }
    distances: list[float] = []
    # Radius at time of trigger — used for the percent-over-radius
    # calc. We take the most recent radius seen in the window so ops
    # gets a "current effective" reference.
    current_radius: Optional[int] = None
    for r in rows:
        p = r.get("payload") or {}
        outcome = str(p.get("outcome") or "started")
        if outcome not in outcomes:
            outcomes[outcome] = 0
        outcomes[outcome] += 1
        d = p.get("distance_m")
        if isinstance(d, (int, float)):
            distances.append(float(d))
        rr = p.get("radius_m")
        if current_radius is None and isinstance(rr, (int, float)):
            current_radius = int(rr)

    excellent = sum(1 for d in distances if d < 25)
    acceptable = sum(1 for d in distances
                        if 25 <= d <= (current_radius or 75))
    over_radius = sum(1 for d in distances
                        if d > (current_radius or 75))
    n_dist = len(distances)

    def _pct(n: int) -> float:
        return round((n / n_dist) * 100.0, 1) if n_dist else 0.0

    # ── Recent events (last 50) hydrated with tech + customer names ─
    recent = rows[:50]
    tech_ids = {r.get("payload", {}).get("technician_id")
                    for r in recent
                    if r.get("payload", {}).get("technician_id")}
    job_ids = {r.get("payload", {}).get("job_id")
                   for r in recent
                   if r.get("payload", {}).get("job_id")}
    tech_names: dict[str, str] = {}
    job_customer_names: dict[str, str] = {}
    try:
        async for t in db.technicians.find(
            {"tenant_id": tenant["id"], "id": {"$in": list(tech_ids)}},
            {"id": 1, "name": 1, "_id": 0}):
            tech_names[t["id"]] = t.get("name") or ""
        # Job → customer_id lookup, then customer_id → name.
        job_to_cust: dict[str, str] = {}
        async for j in db.jobs.find(
            {"tenant_id": tenant["id"], "id": {"$in": list(job_ids)}},
            {"id": 1, "customer_id": 1, "_id": 0}):
            job_to_cust[j["id"]] = j.get("customer_id") or ""
        cust_ids = list({v for v in job_to_cust.values() if v})
        cust_names: dict[str, str] = {}
        async for c in db.customers.find(
            {"tenant_id": tenant["id"], "id": {"$in": cust_ids}},
            {"id": 1, "name": 1, "_id": 0}):
            cust_names[c["id"]] = c.get("name") or ""
        for jid, cid in job_to_cust.items():
            job_customer_names[jid] = cust_names.get(cid, "")
    except Exception as e:
        logger.warning(f"[p37d] hydration failed: {e}")

    recent_events = []
    for r in recent:
        p = r.get("payload") or {}
        jid = p.get("job_id") or ""
        tid = p.get("technician_id") or ""
        recent_events.append({
            "arrived_at": p.get("arrived_at") or r.get("at"),
            "tech_name": tech_names.get(tid, ""),
            "customer_name": job_customer_names.get(jid, ""),
            "job_id": jid,
            "outcome": p.get("outcome") or "started",
            "distance_m": p.get("distance_m"),
            "radius_m": p.get("radius_m"),
            "consent_state": p.get("consent_state") or "not_required",
        })

    return {
        "ok": True,
        "window": {"from": from_iso, "to": to_iso},
        "summary": {
            "total_arrivals": len(rows),
            "started": outcomes["started"],
            "throttled": outcomes["throttled"],
            "out_of_radius": outcomes["out_of_radius"],
            "consent_required": outcomes["consent_required"],
            "feature_disabled": outcomes["feature_disabled"],
            "already_running": outcomes["already_running"],
            "job_completed": outcomes["job_completed"],
            "median_distance_m": _median(distances),
            "p90_distance_m": _percentile(distances, 90),
            "percent_excellent": _pct(excellent),
            "percent_acceptable": _pct(acceptable),
            "percent_over_radius": _pct(over_radius),
            "distance_sample_size": n_dist,
            "current_radius_m": current_radius,
        },
        "recent_events": recent_events,
    }
