"""Phase G5b · Feb-2026 — Stop → Job attribution admin endpoints.

Endpoints (admin+/manager unless noted)
--------------------------------------
* ``GET  /api/admin/gps/attribution/settings``   Tuning knobs.
* ``PATCH /api/admin/gps/attribution/settings``  Update knobs.
* ``POST /api/admin/gps/attribution/run-batch``  Manual run.
* ``POST /api/admin/gps/stops/{stop_id}/attribute``
        Manual link / unlink override (audited).
* ``GET  /api/admin/gps/attribution/summary``    Counts + top jobs by
        total time-on-site.
* ``GET  /api/admin/gps/attribution/job/{job_id}``
        Per-job attributed-stops detail.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from services.stop_attributor import (
    get_settings, run_attribution_batch, run_attribution_batch_all_tenants,
)
from utils import get_current_user, new_id, now_iso

router = APIRouter()
_MOD_ROLES = {"admin", "super_admin", "manager"}
_MANUAL_STATUSES = {"manual_linked", "unlinked"}


def _require_mod(u):
    if (u or {}).get("role") not in _MOD_ROLES:
        raise HTTPException(403, {"error": "forbidden"})


def _tid(u):
    t = (u or {}).get("tenant_id") or ""
    if not t:
        raise HTTPException(400, {"error": "missing_tenant"})
    return t


# ── Settings ────────────────────────────────────────────────────────

class SettingsPatch(BaseModel):
    proximity_threshold_m: Optional[int] = Field(None, ge=10, le=5000)
    same_day_only: Optional[bool] = None
    require_scheduled_status: Optional[bool] = None


@router.get("/admin/gps/attribution/settings",
             operation_id="gps.attribution.getSettings")
async def get_attribution_settings(
        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tid = _tid(caller)
    return await get_settings(tid)


@router.patch("/admin/gps/attribution/settings",
               operation_id="gps.attribution.updateSettings")
async def patch_attribution_settings(
        body: SettingsPatch,
        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tid = _tid(caller)
    upd = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not upd:
        return await get_settings(tid)
    upd["tenant_id"] = tid
    upd["updated_at"] = now_iso()
    upd["updated_by_user_id"] = caller.get("id")
    await db.stop_attribution_meta.update_one(
        {"tenant_id": tid}, {"$set": upd}, upsert=True)
    return await get_settings(tid)


# ── Batch trigger ───────────────────────────────────────────────────

@router.post("/admin/gps/attribution/run-batch",
              operation_id="gps.attribution.runBatch")
async def run_batch_now(
        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tid = _tid(caller)
    counts = await run_attribution_batch(tid)
    logger.info("[stop_attribute] MANUAL tenant=%s counts=%s", tid, counts)
    return counts


# ── Manual override ─────────────────────────────────────────────────

class AttributeStopBody(BaseModel):
    job_id: Optional[str] = None
    customer_id: Optional[str] = None
    unlink: bool = False


async def _audit(tenant_id: str, user_id: str,
                  kind: str, before: Dict[str, Any],
                  after: Dict[str, Any]) -> None:
    try:
        await db.audits.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "user_id": user_id,
            "kind": kind,
            "at": now_iso(),
            "before": before,
            "after": after,
        })
    except Exception as e:                                                # noqa: BLE001
        logger.warning("[stop_attribute] audit insert failed: %s", e)


@router.post("/admin/gps/stops/{stop_id}/attribute",
              operation_id="gps.attribution.manualAttribute")
async def manual_attribute_stop(
        stop_id: str,
        body: AttributeStopBody,
        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tid = _tid(caller)
    stop = await db.driver_stops.find_one(
        {"id": stop_id, "tenant_id": tid}, {"_id": 0})
    if not stop:
        raise HTTPException(404, {"error": "stop_not_found"})

    before = {
        "attribution_status": stop.get("attribution_status"),
        "attributed_job_id": stop.get("attributed_job_id"),
        "attributed_customer_id": stop.get("attributed_customer_id"),
        "attribution_distance_m": stop.get("attribution_distance_m"),
    }

    if body.unlink:
        upd = {
            "attribution_status": "unlinked",
            "attributed_job_id": None,
            "attributed_customer_id": None,
            "attribution_distance_m": None,
            "attribution_updated_at": now_iso(),
            "attribution_updated_by_user_id": caller.get("id"),
        }
    else:
        if not body.job_id:
            raise HTTPException(422, {"error": "job_id_required"})
        job = await db.jobs.find_one(
            {"id": body.job_id, "tenant_id": tid},
            {"_id": 0, "id": 1, "customer_id": 1})
        if not job:
            raise HTTPException(404, {"error": "job_not_found"})
        upd = {
            "attribution_status": "manual_linked",
            "attributed_job_id": body.job_id,
            "attributed_customer_id": (body.customer_id
                                        or job.get("customer_id")),
            "attribution_distance_m": None,
            "attribution_updated_at": now_iso(),
            "attribution_updated_by_user_id": caller.get("id"),
        }
    await db.driver_stops.update_one(
        {"id": stop_id, "tenant_id": tid}, {"$set": upd})
    after = {k: upd[k] for k in ("attribution_status",
                                    "attributed_job_id",
                                    "attributed_customer_id",
                                    "attribution_distance_m")}
    await _audit(tid, caller.get("id"),
                  "stop_attribution_changed", before, after)
    fresh = await db.driver_stops.find_one(
        {"id": stop_id, "tenant_id": tid}, {"_id": 0})
    return fresh


# ── Summary ─────────────────────────────────────────────────────────

@router.get("/admin/gps/attribution/summary",
             operation_id="gps.attribution.summary")
async def get_summary(
        range: str = Query("week", pattern="^(day|week|month)$"),
        q_customer: Optional[str] = Query(None),
        q_address: Optional[str] = Query(None),
        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tid = _tid(caller)
    as_of_dt = datetime.now(timezone.utc)
    lookback_days = {"day": 1, "week": 7, "month": 30}[range]
    since_iso = (as_of_dt - timedelta(days=lookback_days))\
        .isoformat().replace("+00:00", "Z")

    # Status counts across ALL time — this is a health metric,
    # not a range chart.
    counts = {"pending": 0, "auto_linked": 0, "manual_linked": 0,
              "no_match": 0, "unlinked": 0}
    async for row in db.driver_stops.aggregate([
        {"$match": {"tenant_id": tid}},
        {"$group": {
            "_id": {"$ifNull": ["$attribution_status", "pending"]},
            "n": {"$sum": 1},
        }},
    ]):
        key = row["_id"] or "pending"
        if key in counts:
            counts[key] = int(row["n"])

    # Top jobs by total attributed stop duration in the window.
    top_rows: List[Dict[str, Any]] = []
    async for row in db.driver_stops.aggregate([
        {"$match": {
            "tenant_id": tid,
            "attributed_job_id": {"$ne": None},
            "started_at": {"$gte": since_iso},
        }},
        {"$group": {
            "_id": "$attributed_job_id",
            "total_stop_duration_s": {"$sum": "$duration_s"},
            "stop_count": {"$sum": 1},
        }},
        {"$sort": {"total_stop_duration_s": -1}},
        {"$limit": 5},
    ]):
        top_rows.append(row)

    # Hydrate job + customer names in one round-trip each.
    job_ids = [r["_id"] for r in top_rows if r.get("_id")]
    jobs_by_id: Dict[str, Dict[str, Any]] = {}
    cust_ids: List[str] = []
    if job_ids:
        async for j in db.jobs.find(
            {"tenant_id": tid, "id": {"$in": job_ids}},
            {"_id": 0, "id": 1, "title": 1, "service_type": 1,
              "customer_id": 1, "customer_name": 1, "address": 1,
              "scheduled_date": 1},
        ):
            jobs_by_id[j["id"]] = j
            if j.get("customer_id"):
                cust_ids.append(j["customer_id"])
    cust_by_id: Dict[str, Dict[str, Any]] = {}
    if cust_ids:
        async for c in db.customers.find(
            {"tenant_id": tid, "id": {"$in": list(set(cust_ids))}},
            {"_id": 0, "id": 1, "name": 1},
        ):
            cust_by_id[c["id"]] = c

    top_jobs: List[Dict[str, Any]] = []
    for r in top_rows:
        j = jobs_by_id.get(r["_id"]) or {}
        cust = cust_by_id.get(j.get("customer_id") or "") or {}
        top_jobs.append({
            "job_id": r["_id"],
            "job_name": j.get("title") or j.get("service_type") or "Job",
            "customer_id": j.get("customer_id"),
            "customer_name": (cust.get("name")
                                or j.get("customer_name") or ""),
            "address": j.get("address") or "",
            "scheduled_date": j.get("scheduled_date"),
            "total_stop_duration_s": int(r.get("total_stop_duration_s") or 0),
            "stop_count": int(r.get("stop_count") or 0),
        })

    # G5b addendum #2 · Feb-2026 — post-hydration search filters.
    import re
    if q_customer:
        pat = re.compile(re.escape(q_customer), re.IGNORECASE)
        top_jobs = [r for r in top_jobs
                    if pat.search(r.get("customer_name") or "")]
    if q_address:
        pat = re.compile(re.escape(q_address), re.IGNORECASE)
        top_jobs = [r for r in top_jobs
                    if pat.search(r.get("address") or "")]

    return {
        "as_of": as_of_dt.isoformat().replace("+00:00", "Z"),
        "range": range,
        "counts": counts,
        "top_jobs_by_time_on_site": top_jobs,
    }


# ── Job detail ──────────────────────────────────────────────────────

@router.get("/admin/gps/attribution/job/{job_id}",
             operation_id="gps.attribution.jobDetail")
async def get_job_time_on_site(
        job_id: str,
        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tid = _tid(caller)
    job = await db.jobs.find_one(
        {"id": job_id, "tenant_id": tid}, {"_id": 0})
    if not job:
        raise HTTPException(404, {"error": "job_not_found"})

    cust = None
    if job.get("customer_id"):
        cust = await db.customers.find_one(
            {"tenant_id": tid, "id": job["customer_id"]},
            {"_id": 0, "name": 1})

    stops: List[Dict[str, Any]] = []
    total_dur = 0
    techs = set()
    async for s in db.driver_stops.find(
        {"tenant_id": tid, "attributed_job_id": job_id},
        {"_id": 0, "id": 1, "user_id": 1, "started_at": 1,
          "ended_at": 1, "duration_s": 1,
          "attribution_distance_m": 1, "attribution_status": 1},
    ).sort("started_at", 1):
        stops.append(s)
        total_dur += int(s.get("duration_s") or 0)
        if s.get("user_id"):
            techs.add(s["user_id"])

    # Hydrate user names + customer name on each attributed stop.
    if techs:
        uid_to_name = {}
        async for u in db.users.find(
            {"tenant_id": tid, "id": {"$in": list(techs)}},
            {"_id": 0, "id": 1, "name": 1, "email": 1},
        ):
            uid_to_name[u["id"]] = u.get("name") or u.get("email") or ""
        for s in stops:
            s["user_name"] = uid_to_name.get(s.get("user_id") or "", "")
    # G5b addendum · Feb-2026 — echo the customer name on every
    # attributed stop for symmetry with /gps/stops + /gps/route.
    cust_name = (cust.get("name") if cust
                  else job.get("customer_name") or None)
    for s in stops:
        s["attributed_customer_name"] = cust_name

    return {
        "job_id": job_id,
        "job_name": (job.get("title")
                      or job.get("service_type") or "Job"),
        "customer_id": job.get("customer_id"),
        "customer_name": (cust.get("name") if cust
                           else job.get("customer_name") or ""),
        "scheduled_date": job.get("scheduled_date"),
        "attributed_stops": stops,
        "total_stop_duration_s": total_dur,
        "unique_techs": len(techs),
    }
