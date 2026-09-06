"""K65 · Feb-2026 — Prod schedule perf diagnostic endpoint.

``POST /api/admin/perf/explain-schedule``

Super-admin only. Feature-gated behind ``FEATURE_PERF_EXPLAIN=1`` in
the backend environment (default OFF on prod). Runs
``explain('executionStats')`` on three read paths that back the
``/schedule?date=…`` page load:

  1. The ``/api/jobs`` aggregation pipeline (post-K65.fix shape:
     index-covered sort on ``scheduled_date``, then in-Python
     re-sort — this endpoint only reflects what Mongo sees, not the
     Python re-sort.).
  2. A representative ``db.jobs.count_documents`` from the technicians
     N+1 loop (now collapsed post-K65.fix, but the diagnostic still
     validates the underlying index chose the expected plan).
  3. The service_reports enrichment ``$in`` lookup.

Read-only. Zero writes. Never mutates state. Not exposed on the hot
request path — only reached when ops flips the flag on for a
targeted diagnostic window.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from bson import json_util
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db
from utils import require_super_admin
from routers.tenants import get_current_tenant


router = APIRouter()


def _feature_enabled() -> bool:
    return (os.environ.get("FEATURE_PERF_EXPLAIN") or "").strip() == "1"


def _bson_safe(doc: Any) -> Any:
    """Recursively convert BSON-only types (Binary planCacheKey,
    ObjectId, datetime, etc.) into JSON-safe primitives.  ``json_util``
    round-trip handles the entire matrix in one shot.
    """
    try:
        return json.loads(json_util.dumps(doc))
    except Exception:  # noqa: BLE001
        # Fall back to a string dump so the caller still gets
        # SOMETHING actionable rather than a 500.
        return {"__unserialisable__": True, "repr": repr(doc)[:2000]}


class ExplainScheduleRequest(BaseModel):
    """Request body for POST /api/admin/perf/explain-schedule.

    Every field optional — defaults produce a representative window
    for the tenant of the caller.
    """
    focus_date: Optional[str] = None  # YYYY-MM-DD; defaults to today
    window_before_days: int = 30
    window_after_days: int = 60
    technician_id: Optional[str] = None  # for the count_documents leg
    crew_id: Optional[str] = None
    limit: int = 1000
    # ``service_reports`` explain leg — number of ``job_id`` values to
    # $in-query (capped at 200 for safety).
    sample_job_ids: Optional[List[str]] = None


@router.post("/admin/perf/explain-schedule",
             summary="[K65 diag] Explain the schedule read plan",
             operation_id="admin.perf.explainSchedule")
async def explain_schedule(
    body: ExplainScheduleRequest,
    user: dict = Depends(require_super_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Returns ``executionStats`` for the three schedule-load queries.

    Gated by:
      * ``require_super_admin`` — 403 for every other role.
      * ``FEATURE_PERF_EXPLAIN=1`` env flag — 404 when off so the
        route is invisible on prod by default.
    """
    if not _feature_enabled():
        # 404 (not 403) so probing the endpoint from unauthorised
        # roles can't distinguish "flag off" from "route missing".
        raise HTTPException(404, "Not Found")

    tid = tenant["id"]
    focus = body.focus_date or date.today().isoformat()
    try:
        focus_dt = date.fromisoformat(focus)
    except ValueError:
        raise HTTPException(400, "focus_date must be YYYY-MM-DD")

    start = (focus_dt - timedelta(days=int(body.window_before_days))).isoformat()
    end   = (focus_dt + timedelta(days=int(body.window_after_days))).isoformat()

    out: Dict[str, Any] = {
        "tenant_id": tid,
        "focus_date": focus,
        "window": {"start": start, "end": end},
        "limit": int(body.limit),
        "feature_flag": "FEATURE_PERF_EXPLAIN",
        "results": {},
    }

    # ── Leg 1 · /api/jobs aggregation ────────────────────────────
    match_q: Dict[str, Any] = {
        "tenant_id": tid,
        "scheduled_date": {"$gte": start, "$lte": end},
        "$or": [
            {"deleted_at": None},
            {"deleted_at": {"$exists": False}},
        ],
    }
    if body.crew_id:
        match_q["crew_id"] = body.crew_id
    pipeline = [
        {"$match": match_q},
        {"$sort": {"scheduled_date": 1}},
        {"$limit": int(body.limit)},
        {"$project": {"_id": 0}},
    ]
    try:
        # Motor exposes explain via the command interface.
        cmd = {
            "aggregate": "jobs",
            "pipeline": pipeline,
            "explain": True,
            "cursor": {},
        }
        out["results"]["jobs_pipeline"] = _bson_safe(await db.command(cmd))
    except Exception as exc:  # noqa: BLE001
        out["results"]["jobs_pipeline"] = {"error": str(exc)}

    # ── Leg 2 · representative /api/technicians count ────────────
    tech_filter: Dict[str, Any] = {
        "tenant_id": tid,
        "status": {"$in": ["pending", "active"]},
    }
    if body.technician_id:
        tech_filter["technician_id"] = body.technician_id
    else:
        # Pick any tech id from the tenant so the explain has a
        # concrete equality bound rather than a full-scan match.
        _sample = await db.technicians.find_one(
            {"tenant_id": tid}, {"_id": 0, "id": 1},
        )
        if _sample and _sample.get("id"):
            tech_filter["technician_id"] = _sample["id"]
    try:
        out["results"]["technician_count"] = _bson_safe(await db.command({
            "explain": {
                "count": "jobs",
                "query": tech_filter,
            },
            "verbosity": "executionStats",
        }))
    except Exception as exc:  # noqa: BLE001
        out["results"]["technician_count"] = {"error": str(exc)}

    # ── Leg 3 · service_reports $in enrichment ───────────────────
    jids = list(body.sample_job_ids or [])[:200]
    if not jids:
        # Pull up to 50 job ids in the window so the $in has real
        # values without the caller needing to know any.
        cursor = db.jobs.find(match_q, {"_id": 0, "id": 1}).limit(50)
        jids = [j["id"] async for j in cursor if j.get("id")]
    if jids:
        sr_query = {"tenant_id": tid, "job_id": {"$in": jids}}
        try:
            out["results"]["service_reports_lookup"] = _bson_safe(await db.command({
                "explain": {
                    "find": "service_reports",
                    "filter": sr_query,
                },
                "verbosity": "executionStats",
            }))
        except Exception as exc:  # noqa: BLE001
            out["results"]["service_reports_lookup"] = {"error": str(exc)}
    else:
        out["results"]["service_reports_lookup"] = {
            "skipped": "no job_ids in window",
        }

    return out


@router.get("/admin/perf/explain-schedule/status",
            summary="[K65 diag] Is the explain endpoint enabled?",
            operation_id="admin.perf.explainScheduleStatus")
async def explain_schedule_status(
    user: dict = Depends(require_super_admin),
) -> Dict[str, Any]:
    """Introspection helper — lets super-admin operators verify
    whether the flag is currently on without POSTing anything.
    """
    return {
        "feature_flag": "FEATURE_PERF_EXPLAIN",
        "enabled": _feature_enabled(),
        "endpoint": "/api/admin/perf/explain-schedule",
    }
