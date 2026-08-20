"""G2 · Feb-2026 — Driver Activity endpoints.

* ``GET  /api/gps/stops``                   Read stops for a user + window.
* ``POST /api/admin/gps/stops/rebuild``     Wipe + re-run the detector.

The batch cron itself lives in ``services/gps_stops_batch.py``. This
router is the read + admin-tune surface.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db
from services.gps_stops_batch import rebuild_for_user, run_gps_stops_batch
from utils import get_current_user

router = APIRouter()

_READ_ROLES = {"admin", "super_admin", "manager"}
_ADMIN_ROLES = {"admin", "super_admin"}
_MAX_WINDOW_DAYS = 31


def _require(role: str, allowed: set) -> None:
    if role not in allowed:
        raise HTTPException(403, {"error": "forbidden"})


def _parse_iso_arg(v: str, name: str) -> datetime:
    try:
        ts = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(422, {"error": f"invalid_{name}",
                                     "hint": "ISO 8601 expected"})
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


@router.get("/gps/stops", operation_id="gps.stops.list")
async def list_stops(
    user_id: str = Query(...),
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    q_customer: Optional[str] = Query(None),
    q_address: Optional[str] = Query(None),
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require(caller.get("role") or "", _READ_ROLES)
    tenant_id = caller.get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(400, {"error": "missing_tenant"})

    from_dt = _parse_iso_arg(from_, "from")
    to_dt = _parse_iso_arg(to, "to")
    if to_dt < from_dt:
        raise HTTPException(422, {"error": "to_before_from"})
    if (to_dt - from_dt) > timedelta(days=_MAX_WINDOW_DAYS):
        raise HTTPException(422, {"error": "window_too_wide",
                                     "max_days": _MAX_WINDOW_DAYS})

    target = await db.users.find_one(
        {"id": user_id, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1, "email": 1},
    )
    if not target:
        raise HTTPException(404, {"error": "user_not_found"})

    stops = []
    async for s in db.driver_stops.find(
        {
            "tenant_id": tenant_id, "user_id": user_id,
            "started_at": {"$gte": from_dt.isoformat().replace("+00:00", "Z"),
                            "$lte": to_dt.isoformat().replace("+00:00", "Z")},
        },
        {
            "_id": 0, "id": 1, "started_at": 1, "ended_at": 1,
            "duration_s": 1, "center_lat": 1, "center_lon": 1,
            "radius_m": 1, "ping_count": 1, "source": 1,
            # G3 · Feb-2026 — reverse-geocoded address (nullable).
            "address": 1, "address_status": 1,
            # G5b · Feb-2026 — attribution fields (nullable, additive).
            "attribution_status": 1, "attributed_job_id": 1,
            "attributed_customer_id": 1, "attribution_distance_m": 1,
            "attribution_updated_at": 1,
        },
    ).sort("started_at", 1):
        stops.append(s)

    # G5b · Feb-2026 — one-round-trip hydrate of job + customer names
    # so the driver-activity UI can render "attributed to X" inline.
    job_ids = list({s.get("attributed_job_id") for s in stops
                    if s.get("attributed_job_id")})
    cust_ids = list({s.get("attributed_customer_id") for s in stops
                     if s.get("attributed_customer_id")})
    jobs_by_id: Dict[str, Any] = {}
    custs_by_id: Dict[str, Any] = {}
    if job_ids:
        from utils import not_deleted_filter as _nd
        async for j in db.jobs.find(
            {"tenant_id": tenant_id, "id": {"$in": job_ids}, **_nd()},
            {"_id": 0, "id": 1, "title": 1, "service_type": 1,
             "customer_name": 1, "address": 1},
        ):
            jobs_by_id[j["id"]] = j
    if cust_ids:
        async for c in db.customers.find(
            {"tenant_id": tenant_id, "id": {"$in": cust_ids}},
            {"_id": 0, "id": 1, "name": 1},
        ):
            custs_by_id[c["id"]] = c
    for s in stops:
        jid = s.get("attributed_job_id")
        cid = s.get("attributed_customer_id")
        j = jobs_by_id.get(jid) if jid else None
        c = custs_by_id.get(cid) if cid else None
        if j:
            s["attributed_job_name"] = (j.get("title")
                                        or j.get("service_type") or "Job")
        # G5b addendum · Feb-2026 — only trust the live customer doc.
        # If the customer no longer exists, echo null (per the
        # deleted-customer contract).
        if cid:
            s["attributed_customer_name"] = (c.get("name")
                                              if c else None)
        else:
            s["attributed_customer_name"] = None

    # G5b addendum #2 · Feb-2026 — post-hydration filters. Substring,
    # case-insensitive. Applied AFTER the join so the fields we filter
    # on already exist on the row.
    import re
    if q_customer:
        pat = re.compile(re.escape(q_customer), re.IGNORECASE)
        stops = [s for s in stops
                 if pat.search(s.get("attributed_customer_name") or "")]
    if q_address:
        pat = re.compile(re.escape(q_address), re.IGNORECASE)
        stops = [s for s in stops
                 if pat.search((s.get("address") or {}).get("formatted") or "")]

    return {
        "user_id": user_id,
        "user_name": target.get("name") or target.get("email") or "",
        "from": from_,
        "to": to,
        "stops": stops,
        "count": len(stops),
    }


class RebuildBody(BaseModel):
    user_id: Optional[str] = None
    from_: Optional[str] = None
    to: Optional[str] = None

    class Config:
        fields = {"from_": "from"}


@router.post("/admin/gps/stops/rebuild", operation_id="gps.stops.rebuild")
async def rebuild_stops(body: RebuildBody,
                          caller: Dict[str, Any] = Depends(get_current_user)):
    _require(caller.get("role") or "", _ADMIN_ROLES)
    tenant_id = caller.get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(400, {"error": "missing_tenant"})

    now_dt = datetime.now(timezone.utc)
    to_dt = _parse_iso_arg(body.to, "to") if body.to else now_dt
    from_dt = _parse_iso_arg(body.from_, "from") if body.from_ else (
        to_dt - timedelta(days=1))
    if to_dt < from_dt:
        raise HTTPException(422, {"error": "to_before_from"})
    if (to_dt - from_dt) > timedelta(days=_MAX_WINDOW_DAYS):
        raise HTTPException(422, {"error": "window_too_wide",
                                     "max_days": _MAX_WINDOW_DAYS})

    settings = await db.gps_settings.find_one(
        {"tenant_id": tenant_id}, {"_id": 0}) or {}

    targets: list[str] = []
    if body.user_id:
        targets = [body.user_id]
    else:
        async for u in db.users.find(
            {"tenant_id": tenant_id, "role": "technician"},
            {"_id": 0, "id": 1},
        ):
            if u.get("id"):
                targets.append(u["id"])

    total_created = 0
    for uid in targets:
        total_created += await rebuild_for_user(
            tenant_id, uid,
            from_dt=from_dt, to_dt=to_dt,
            settings=settings,
        )

    return {"users_processed": len(targets), "stops_created": total_created}


@router.post("/admin/gps/stops/run-batch", operation_id="gps.stops.runBatch")
async def run_stops_batch_now(
    caller: Dict[str, Any] = Depends(get_current_user),
):
    """G2 · Feb-2026 — Trigger the stops-batch cron manually.

    Admin+ / super_admin only. Handy for live smoke (post a seeded
    ping burst, then invoke this endpoint to force stop detection
    without waiting for the 3-minute cron). Returns the totals from
    the batch pass ({tenants, users_processed, stops_emitted})."""
    _require(caller.get("role") or "", _ADMIN_ROLES)
    return await run_gps_stops_batch()
