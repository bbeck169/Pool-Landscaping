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
    """Return ``int(max(0, (ended - started).total_seconds()))`` or
    ``None`` when either bound is missing / malformed.

    2026-10-02 · duration_seconds=0 fix — the ``None`` return on
    parse failure is diagnostically distinct from a legitimate
    0-second duration (clock skew etc.).  The ``close_open_timers_
    for_job`` caller passes the ``None`` straight through to the
    ``$set`` payload so Mongo stores ``null``; the dashboard
    aggregation filter ``{"duration_seconds": {"$gt": 0}}`` at the
    bottom of this module naturally excludes ``null`` rows.
    """
    s = _parse_iso(started)
    e = _parse_iso(ended)
    if not (s and e):
        return None
    try:
        return int(max(0, (e - s).total_seconds()))
    except Exception:                                             # noqa: BLE001
        return None


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
                          pattern="^(geofence|manual_admin|gps_arrival|manual)$")


class CloseTimerIn(BaseModel):
    ended_at: Optional[str] = None
    source: str = Field(default="manual_admin",
                          pattern="^(service_report_submit|manual_admin|job_completed|manual)$")


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
    reason: str = "service_report_submit",
) -> int:
    """Close every open ``job_timers`` row for the given job.
    Returns the count of rows closed. Never raises — the caller
    (service-report submit OR job-completed transition) must not
    fail on a timer close error.

    ``reason`` populates the ``end_source`` field. Callers pass
    ``"service_report_submit"`` (default, from
    ``service_reports.py::submit_report``) or ``"job_completed"``
    (from the job status → completed transition in
    ``routers/jobs.py``).
    """
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
                    "end_source": reason,
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
                "payload": {"reason": reason},
            })
            closed += 1
    except Exception as exc:                                     # noqa: BLE001
        logger.warning("[job-timers] auto-close failed job=%s: %s",
                        job_id, exc)
    return closed


# Feb-2026 · Job Timers dashboard phase — GPS-arrival auto-start.
# Called from ``routers/jobs.py::job_arrive`` after a successful
# arrival gate flip. Idempotent: an open row for the same
# ``(tenant_id, job_id, tech_id, crew_id)`` quadruple is left
# untouched so multiple ``/arrive`` events (mobile queue replay,
# out-of-band retries) never spawn duplicate timers.
#
# Phase 6 · Feb-2026 — ``crew_id`` support.  Pre-Phase-6 callers
# passed only ``tech_id`` so crew-only jobs (``crew_id`` set,
# ``technician_id`` null) produced a timer row with BOTH
# attribution fields unset — effectively orphan rows that the
# ``/job-timers/aggregates`` grouping ignored.  The observed
# symptom was "timers only fire for landscape maintenance" because
# landscape jobs in the operator's dataset tended to be solo-tech
# assigned while pool / repair jobs were crew-assigned.  Carrying
# ``crew_id`` + resolving ``entity_type`` from whichever id is
# present fixes the attribution so every service_type + every
# assignee type (tech, crew_lead, crew_member) gets a proper row.
async def auto_start_timer_on_arrival(
    *, job_id: str, tenant_id: str,
    tech_id: Optional[str] = None,
    crew_id: Optional[str] = None,
    started_at: Optional[str] = None,
    customer_id: Optional[str] = None,
) -> Optional[str]:
    """Upsert an open timer row keyed on
    ``(tenant_id, job_id, tech_id, crew_id)``. Returns the row id
    (existing or freshly-inserted). Never raises — the caller is
    the GPS-arrival hot-path which MUST NOT fail on a bookkeeping
    error.

    Resolution rule:
      * ``tech_id`` present → ``entity_type="tech"``.
      * else ``crew_id`` present → ``entity_type="crew"``.
      * else → ``entity_type="tech"`` with both ids null (legacy
        shape — the record is still inserted so the ops dashboard
        sees the arrival happened; the dashboard filter
        ``{"tech_id": {"$ne": null}}`` or similar can elide these
        rows if desired).
    """
    try:
        # Idempotency probe: any open row for this (job, tech, crew)?
        existing = await db.job_timers.find_one(
            {"tenant_id": tenant_id, "job_id": job_id,
              "tech_id": tech_id, "crew_id": crew_id,
              "ended_at": None},
            {"_id": 0, "id": 1},
        )
        if existing:
            return existing["id"]
        now = _now_iso()
        starts = started_at or now
        entity_type = "tech" if tech_id else ("crew" if crew_id else "tech")
        doc = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "job_id": job_id,
            "customer_id": customer_id,
            "entity_type": entity_type,
            "tech_id": tech_id,
            "crew_id": crew_id,
            "started_at": starts,
            "ended_at": None,
            "duration_seconds": None,
            "start_source": "gps_arrival",
            "end_source": None,
            "created_at": now,
            "updated_at": now,
        }
        await db.job_timers.insert_one(doc)
        await db.job_timer_audit.insert_one({
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "timer_id": doc["id"],
            "event": "start",
            "actor_user_id": None,
            "at": now,
            "payload": {"source": "gps_arrival",
                          "entity_type": entity_type,
                          "tech_id": tech_id,
                          "crew_id": crew_id},
        })
        return doc["id"]
    except Exception as exc:                                     # noqa: BLE001
        logger.warning("[job-timers] arrival auto-start failed job=%s: %s",
                        job_id, exc)
        return None


async def ensure_job_timers_indexes() -> None:
    """Boot-time idempotent index creation. Registered from
    ``server.py`` alongside the other feature-router index hooks."""
    try:
        await db.job_timers.create_index(
            [("tenant_id", 1), ("tech_id", 1), ("started_at", -1)],
            name="idx_job_timers_tenant_tech_started",
        )
        await db.job_timers.create_index(
            [("tenant_id", 1), ("job_id", 1)],
            name="idx_job_timers_tenant_job",
        )
    except Exception as exc:                                     # noqa: BLE001
        logger.warning("[job-timers] index create skipped: %s", exc)


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
    technician_id: Optional[str] = Query(None),
    crew_id: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    # Feb-2026 · Dashboard phase — spec aliases for the filters +
    # cursor pagination envelope. Existing callers continue to use
    # ``date_from``/``date_to``/``tech_id`` and ignore pagination
    # keys → they hit the legacy ``limit`` branch.
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    page: Optional[int] = Query(None, ge=1),
    page_size: Optional[int] = Query(None, ge=1, le=200),
    open_only: bool = Query(False),
    limit: int = Query(500, ge=1, le=2000),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_role(user, _REPORT_ROLES)

    # Aliases — dashboard spec uses ``technician_id`` / ``from`` /
    # ``to``; legacy admin edit UI uses ``tech_id`` / ``date_from`` /
    # ``date_to``. Whichever is present wins; both is a wash.
    effective_tech = technician_id or tech_id
    effective_from = from_ or date_from
    effective_to = to or date_to

    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if job_id:
        q["job_id"] = job_id
    if effective_tech:
        q["tech_id"] = effective_tech
    if crew_id:
        q["crew_id"] = crew_id
    if customer_id:
        q["customer_id"] = customer_id
    if open_only:
        q["ended_at"] = None
    range_gate: Dict[str, Any] = {}
    if effective_from:
        range_gate["$gte"] = effective_from
    if effective_to:
        range_gate["$lte"] = effective_to + (
            "T23:59:59+00:00" if len(effective_to) == 10 else "")
    if range_gate:
        q["started_at"] = range_gate

    # Paginated envelope path — only fires when the caller passed
    # BOTH ``page`` and ``page_size``. Legacy consumers omit them
    # and hit the ``limit``-only branch (bit-for-bit compat).
    paginated = page is not None and page_size is not None
    total = None
    if paginated:
        total = await db.job_timers.count_documents(q)
        skip = (page - 1) * page_size
        cursor = (db.job_timers.find(q, {"_id": 0})
                    .sort([("started_at", -1)])
                    .skip(skip).limit(page_size))
    else:
        cursor = (db.job_timers.find(q, {"_id": 0})
                    .sort([("started_at", -1)]).limit(limit))
    rows: List[Dict[str, Any]] = [r async for r in cursor]

    # Enrich with job title + tech name + crew name + customer.
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
        r["technician_name"] = r["tech_name"]                # spec alias
        r["crew_name"] = (crews_map.get(r.get("crew_id")) or {}).get("name")
        r["customer_name"] = (customers_map.get(r.get("customer_id")) or {}).get("name")
        # Feb-2026 · Dashboard phase — normalise the two-field
        # start_source/end_source model down to the spec's single
        # ``source`` field for the dashboard row-render code.
        start_src = (r.get("start_source") or "").lower()
        r["source"] = ("gps_arrival"
                          if start_src in ("gps_arrival", "geofence")
                          else "manual")
        # Alias ``ended_at`` → ``completed_at`` per spec vocabulary.
        r["completed_at"] = r.get("ended_at")
        r["technician_id"] = r.get("tech_id")

    envelope: Dict[str, Any] = {"items": rows, "count": len(rows)}
    if paginated:
        envelope.update({
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size if page_size else 0,
        })
    return envelope


# ═══════════════════════════════════════════════════════════════════════
# GET /job-timers/summary
# ═══════════════════════════════════════════════════════════════════════
@router.get("/job-timers/summary")
async def timer_summary(
    technician_id: Optional[str] = Query(None),
    tech_id: Optional[str] = Query(None),                       # spec alias
    job_id: Optional[str] = Query(None),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),                     # legacy alias
    date_to: Optional[str] = Query(None),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    """Feb-2026 · Job Timers dashboard phase — summary metrics for
    the filter window. Only closed timers with ``duration_seconds
    > 0`` participate; open timers are excluded so a still-running
    job doesn't skew the avg/median toward zero.

    Returns::

        {avg_seconds, median_seconds, min_seconds,
         max_seconds, count}

    All values are integers. ``count == 0`` → every metric is 0
    (never null) so the dashboard can render without null-guards.
    """
    _require_role(user, _REPORT_ROLES)
    effective_tech = technician_id or tech_id
    effective_from = from_ or date_from
    effective_to = to or date_to

    q: Dict[str, Any] = {
        "tenant_id": tenant["id"],
        "duration_seconds": {"$gt": 0},
        "ended_at": {"$ne": None},
    }
    if effective_tech:
        q["tech_id"] = effective_tech
    if job_id:
        q["job_id"] = job_id
    range_gate: Dict[str, Any] = {}
    if effective_from:
        range_gate["$gte"] = effective_from
    if effective_to:
        range_gate["$lte"] = effective_to + (
            "T23:59:59+00:00" if len(effective_to) == 10 else "")
    if range_gate:
        q["started_at"] = range_gate

    durations: List[int] = []
    async for r in db.job_timers.find(q, {"_id": 0, "duration_seconds": 1}):
        v = int(r.get("duration_seconds") or 0)
        if v > 0:
            durations.append(v)
    if not durations:
        return {"avg_seconds": 0, "median_seconds": 0,
                 "min_seconds": 0, "max_seconds": 0, "count": 0}

    durations.sort()
    n = len(durations)
    mid = n // 2
    median = (durations[mid] if n % 2 else
                (durations[mid - 1] + durations[mid]) // 2)
    return {
        "avg_seconds": sum(durations) // n,
        "median_seconds": int(median),
        "min_seconds": durations[0],
        "max_seconds": durations[-1],
        "count": n,
    }


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
