"""Feb-2026 · Job Timers Phase 1 — backend router.

Phase 1 scope (this ship): backend + web reporting + admin edit.
Phase 2 (separate dispatch to ``e1_expo_frontend_dev``) will wire
the mobile-side GPS geofence auto-start into ``/start``.

Endpoints (all tenant-scoped):
  * POST   /api/job-timers/start                — super_admin/admin
  * POST   /api/job-timers/{id}/close           — super_admin/admin
  * PATCH  /api/job-timers/{id}                 — super_admin/admin
  * GET    /api/job-timers                      — super_admin/admin/manager
  * GET    /api/job-timers/aggregates           — super_admin/admin/manager

Auto-close hook lives in ``service_reports.py::submit_report`` —
after the service report is written, every open timer for that job
is closed with ``end_source = "service_report_submit"``. Wired
below via ``close_open_timers_for_job``.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db
from routers.tenants import get_current_tenant
from utils import get_current_user


router = APIRouter()
logger = logging.getLogger("job_timers")


_ADMIN_ROLES = {"super_admin", "admin"}
_REPORT_ROLES = {"super_admin", "admin", "manager"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:                                            # noqa: BLE001
        return None


def _compute_duration_seconds(started: Any, ended: Any) -> Optional[int]:
    s = _parse_iso(started)
    e = _parse_iso(ended)
    if not (s and e):
        return None
    return int(max(0, (e - s).total_seconds()))


def _require_role(user: Dict[str, Any], allowed: set) -> None:
    role = (user.get("role") or "").lower()
    if role not in allowed:
        raise HTTPException(403, "forbidden")


# ═══════════════════════════════════════════════════════════════════════
# Pydantic bodies
# ═══════════════════════════════════════════════════════════════════════
class StartTimerIn(BaseModel):
    job_id: str
    entity_type: str = Field(..., pattern="^(tech|crew)$")
    tech_id: Optional[str] = None
    crew_id: Optional[str] = None
    started_at: Optional[str] = None
    source: str = Field(default="manual_admin",
                          pattern="^(geofence|manual_admin)$")


class CloseTimerIn(BaseModel):
    ended_at: Optional[str] = None
    source: str = Field(default="manual_admin",
                          pattern="^(service_report_submit|manual_admin)$")


class PatchTimerIn(BaseModel):
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    tech_id: Optional[str] = None
    crew_id: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════
# Auto-close helper — called from service_reports.py::submit_report.
# ═══════════════════════════════════════════════════════════════════════
async def close_open_timers_for_job(
    *, job_id: str, tenant_id: str,
    actor_user_id: Optional[str] = None,
) -> int:
    """Close every open ``job_timers`` row for the given job.
    Returns the count of rows closed. Never raises — the caller
    (service-report submit) must not fail on a timer close error."""
    now = _now_iso()
    closed = 0
    try:
        cursor = db.job_timers.find(
            {"tenant_id": tenant_id, "job_id": job_id,
              "ended_at": None},
            {"_id": 0, "id": 1, "started_at": 1},
        )
        rows = [r async for r in cursor]
        for r in rows:
            dur = _compute_duration_seconds(r.get("started_at"), now)
            await db.job_timers.update_one(
                {"id": r["id"], "tenant_id": tenant_id},
                {"$set": {
                    "ended_at": now,
                    "duration_seconds": dur,
                    "end_source": "service_report_submit",
                    "updated_at": now,
                }},
            )
            await db.job_timer_audit.insert_one({
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "timer_id": r["id"],
                "event": "auto_close",
                "actor_user_id": actor_user_id,
                "at": now,
                "payload": {"reason": "service_report_submit"},
            })
            closed += 1
    except Exception as exc:                                     # noqa: BLE001
        logger.warning("[job-timers] auto-close failed job=%s: %s",
                        job_id, exc)
    return closed


# ═══════════════════════════════════════════════════════════════════════
# POST /job-timers/start
# ═══════════════════════════════════════════════════════════════════════
@router.post("/job-timers/start")
async def start_timer(
    body: StartTimerIn,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_role(user, _ADMIN_ROLES)
    if body.entity_type == "tech" and not body.tech_id:
        raise HTTPException(400, "tech_id required for entity_type=tech")
    if body.entity_type == "crew" and not body.crew_id:
        raise HTTPException(400, "crew_id required for entity_type=crew")

    # Resolve customer_id from the job for reporting joins.
    job = await db.jobs.find_one(
        {"id": body.job_id, "tenant_id": tenant["id"]},
        {"_id": 0, "customer_id": 1},
    )
    if not job:
        raise HTTPException(404, "job not found")

    now = _now_iso()
    started_at = body.started_at or now
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant["id"],
        "job_id": body.job_id,
        "customer_id": job.get("customer_id"),
        "entity_type": body.entity_type,
        "tech_id": body.tech_id,
        "crew_id": body.crew_id,
        "started_at": started_at,
        "ended_at": None,
        "duration_seconds": None,
        "start_source": body.source,
        "end_source": None,
        "created_at": now,
        "updated_at": now,
    }
    await db.job_timers.insert_one(doc)
    await db.job_timer_audit.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": tenant["id"],
        "timer_id": doc["id"],
        "event": "start",
        "actor_user_id": user.get("id"),
        "at": now,
        "payload": {"source": body.source, "entity_type": body.entity_type,
                      "tech_id": body.tech_id, "crew_id": body.crew_id},
    })
    doc.pop("_id", None)
    return doc


# ═══════════════════════════════════════════════════════════════════════
# POST /job-timers/{id}/close
# ═══════════════════════════════════════════════════════════════════════
@router.post("/job-timers/{timer_id}/close")
async def close_timer(
    timer_id: str,
    body: CloseTimerIn,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_role(user, _ADMIN_ROLES)
    row = await db.job_timers.find_one(
        {"id": timer_id, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "started_at": 1, "ended_at": 1},
    )
    if not row:
        raise HTTPException(404, "timer not found")
    if row.get("ended_at"):
        # Idempotent — return the row without re-writing.
        return await db.job_timers.find_one(
            {"id": timer_id, "tenant_id": tenant["id"]}, {"_id": 0},
        )
    now = _now_iso()
    ended_at = body.ended_at or now
    dur = _compute_duration_seconds(row.get("started_at"), ended_at)
    await db.job_timers.update_one(
        {"id": timer_id, "tenant_id": tenant["id"]},
        {"$set": {
            "ended_at": ended_at,
            "duration_seconds": dur,
            "end_source": body.source,
            "updated_at": now,
        }},
    )
    await db.job_timer_audit.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": tenant["id"],
        "timer_id": timer_id,
        "event": "close",
        "actor_user_id": user.get("id"),
        "at": now,
        "payload": {"source": body.source, "duration_seconds": dur,
                      "ended_at": ended_at},
    })
    return await db.job_timers.find_one(
        {"id": timer_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )


# ═══════════════════════════════════════════════════════════════════════
# PATCH /job-timers/{id} — admin edit
# ═══════════════════════════════════════════════════════════════════════
@router.patch("/job-timers/{timer_id}")
async def edit_timer(
    timer_id: str,
    body: PatchTimerIn,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_role(user, _ADMIN_ROLES)
    row = await db.job_timers.find_one(
        {"id": timer_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "timer not found")
    patch: Dict[str, Any] = {"updated_at": _now_iso()}
    diff: Dict[str, Any] = {}
    for field in ("started_at", "ended_at", "tech_id", "crew_id"):
        val = getattr(body, field)
        if val is not None:
            patch[field] = val
            diff[field] = {"from": row.get(field), "to": val}
    if not diff:
        return row
    # Recompute duration if either bound changed.
    if "started_at" in diff or "ended_at" in diff:
        s = patch.get("started_at", row.get("started_at"))
        e = patch.get("ended_at", row.get("ended_at"))
        if e is not None:
            patch["duration_seconds"] = _compute_duration_seconds(s, e)
    await db.job_timers.update_one(
        {"id": timer_id, "tenant_id": tenant["id"]},
        {"$set": patch},
    )
    await db.job_timer_audit.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": tenant["id"],
        "timer_id": timer_id,
        "event": "edit",
        "actor_user_id": user.get("id"),
        "at": patch["updated_at"],
        "payload": diff,
    })
    return await db.job_timers.find_one(
        {"id": timer_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )


# ═══════════════════════════════════════════════════════════════════════
# GET /job-timers
# ═══════════════════════════════════════════════════════════════════════
@router.get("/job-timers")
async def list_timers(
    job_id: Optional[str] = Query(None),
    tech_id: Optional[str] = Query(None),
    crew_id: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    open_only: bool = Query(False),
    limit: int = Query(500, ge=1, le=2000),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_role(user, _REPORT_ROLES)
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if job_id:
        q["job_id"] = job_id
    if tech_id:
        q["tech_id"] = tech_id
    if crew_id:
        q["crew_id"] = crew_id
    if customer_id:
        q["customer_id"] = customer_id
    if open_only:
        q["ended_at"] = None
    range_gate: Dict[str, Any] = {}
    if date_from:
        range_gate["$gte"] = date_from
    if date_to:
        range_gate["$lte"] = date_to + ("T23:59:59+00:00" if len(date_to) == 10 else "")
    if range_gate:
        q["started_at"] = range_gate

    rows: List[Dict[str, Any]] = []
    async for r in db.job_timers.find(q, {"_id": 0}).sort([("started_at", -1)]).limit(limit):
        rows.append(r)

    # Enrich with job title + tech name + crew name for the table.
    job_ids = list({r.get("job_id") for r in rows if r.get("job_id")})
    tech_ids = list({r.get("tech_id") for r in rows if r.get("tech_id")})
    crew_ids = list({r.get("crew_id") for r in rows if r.get("crew_id")})
    customer_ids = list({r.get("customer_id") for r in rows if r.get("customer_id")})

    jobs_map: Dict[str, Dict[str, Any]] = {}
    if job_ids:
        async for j in db.jobs.find(
            {"tenant_id": tenant["id"], "id": {"$in": job_ids}},
            {"_id": 0, "id": 1, "title": 1, "service_type": 1,
              "scheduled_date": 1},
        ):
            jobs_map[j["id"]] = j
    techs_map: Dict[str, Dict[str, Any]] = {}
    if tech_ids:
        async for t in db.technicians.find(
            {"tenant_id": tenant["id"], "id": {"$in": tech_ids}},
            {"_id": 0, "id": 1, "name": 1},
        ):
            techs_map[t["id"]] = t
    crews_map: Dict[str, Dict[str, Any]] = {}
    if crew_ids:
        async for c in db.crews.find(
            {"tenant_id": tenant["id"], "id": {"$in": crew_ids}},
            {"_id": 0, "id": 1, "name": 1},
        ):
            crews_map[c["id"]] = c
    customers_map: Dict[str, Dict[str, Any]] = {}
    if customer_ids:
        async for cust in db.customers.find(
            {"tenant_id": tenant["id"], "id": {"$in": customer_ids}},
            {"_id": 0, "id": 1, "name": 1},
        ):
            customers_map[cust["id"]] = cust

    for r in rows:
        r["job_title"] = (jobs_map.get(r.get("job_id")) or {}).get("title")
        r["service_type"] = (jobs_map.get(r.get("job_id")) or {}).get("service_type")
        r["tech_name"] = (techs_map.get(r.get("tech_id")) or {}).get("name")
        r["crew_name"] = (crews_map.get(r.get("crew_id")) or {}).get("name")
        r["customer_name"] = (customers_map.get(r.get("customer_id")) or {}).get("name")
    return {"items": rows, "count": len(rows)}


# ═══════════════════════════════════════════════════════════════════════
# GET /job-timers/aggregates
# ═══════════════════════════════════════════════════════════════════════
@router.get("/job-timers/aggregates")
async def timer_aggregates(
    group_by: str = Query("service_category",
                            pattern="^(service_category|customer|both)$"),
    tech_id: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_role(user, _REPORT_ROLES)
    q: Dict[str, Any] = {
        "tenant_id": tenant["id"],
        "duration_seconds": {"$gt": 0},
        "ended_at": {"$ne": None},
    }
    if tech_id:
        q["tech_id"] = tech_id
    if customer_id:
        q["customer_id"] = customer_id
    range_gate: Dict[str, Any] = {}
    if date_from:
        range_gate["$gte"] = date_from
    if date_to:
        range_gate["$lte"] = date_to + ("T23:59:59+00:00" if len(date_to) == 10 else "")
    if range_gate:
        q["started_at"] = range_gate

    # Bring in job.service_type + customer.name for grouping. We do
    # the join in Python — the timer collection is small enough
    # (retrospective reporting; not real-time) that a proper $lookup
    # pipeline isn't worth the extra complexity for Phase 1.
    rows: List[Dict[str, Any]] = []
    async for r in db.job_timers.find(q, {"_id": 0}):
        rows.append(r)
    if not rows:
        return {"buckets": [], "totals": {"total_seconds": 0, "count": 0,
                                            "avg_seconds": 0}}

    job_ids = list({r.get("job_id") for r in rows if r.get("job_id")})
    customer_ids = list({r.get("customer_id") for r in rows if r.get("customer_id")})
    jobs_map: Dict[str, Dict[str, Any]] = {}
    if job_ids:
        async for j in db.jobs.find(
            {"tenant_id": tenant["id"], "id": {"$in": job_ids}},
            {"_id": 0, "id": 1, "service_type": 1},
        ):
            jobs_map[j["id"]] = j
    customers_map: Dict[str, Dict[str, Any]] = {}
    if customer_ids:
        async for c in db.customers.find(
            {"tenant_id": tenant["id"], "id": {"$in": customer_ids}},
            {"_id": 0, "id": 1, "name": 1},
        ):
            customers_map[c["id"]] = c

    buckets: Dict[str, Dict[str, Any]] = {}
    total_secs = 0
    total_ct = 0
    for r in rows:
        svc = ((jobs_map.get(r.get("job_id")) or {}).get("service_type")
                or "Uncategorized")
        cust = ((customers_map.get(r.get("customer_id")) or {}).get("name")
                or "Unknown")
        if group_by == "service_category":
            key = svc
            label = svc
        elif group_by == "customer":
            key = cust
            label = cust
        else:                                                   # both
            key = f"{cust}||{svc}"
            label = f"{cust} · {svc}"
        b = buckets.setdefault(key, {
            "key": key, "label": label,
            "customer_name": cust, "service_category": svc,
            "total_seconds": 0, "count": 0,
        })
        b["total_seconds"] += int(r.get("duration_seconds") or 0)
        b["count"] += 1
        total_secs += int(r.get("duration_seconds") or 0)
        total_ct += 1

    out = []
    for b in buckets.values():
        b["avg_seconds"] = (b["total_seconds"] // b["count"]) if b["count"] else 0
        out.append(b)
    out.sort(key=lambda x: x["avg_seconds"], reverse=True)
    return {
        "buckets": out,
        "totals": {
            "total_seconds": total_secs,
            "count": total_ct,
            "avg_seconds": total_secs // total_ct if total_ct else 0,
        },
    }
