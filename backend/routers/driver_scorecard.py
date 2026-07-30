"""Phase G5d · Feb-2026 — Driver scorecard admin endpoints."""
from __future__ import annotations

import csv
import io
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from services.driver_scorecard import (
    compute_leaderboard, compute_user_detail,
)
from utils import get_current_user

router = APIRouter()
_MOD_ROLES = {"admin", "super_admin", "manager"}


def _require_mod(u):
    if (u or {}).get("role") not in _MOD_ROLES:
        raise HTTPException(403, {"error": "forbidden"})


def _tid(u):
    t = (u or {}).get("tenant_id") or ""
    if not t:
        raise HTTPException(400, {"error": "missing_tenant"})
    return t


_RANGE_PATTERN = "^(this_week|last_week|month_to_date|custom)$"


@router.get("/admin/gps/scorecard/leaderboard",
             operation_id="gps.scorecard.leaderboard")
async def get_leaderboard(
        range: str = Query("this_week", pattern=_RANGE_PATTERN),
        from_: Optional[str] = Query(None, alias="from"),
        to: Optional[str] = Query(None),
        department: Optional[str] = Query(None),
        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant = _tid(caller)
    if range == "custom" and not (from_ and to):
        raise HTTPException(422, {"error": "custom_needs_from_to"})
    return await compute_leaderboard(tenant, range, from_, to, department)


@router.get("/admin/gps/scorecard/user/{user_id}",
             operation_id="gps.scorecard.userDetail")
async def get_user_detail(
        user_id: str,
        range: str = Query("this_week", pattern=_RANGE_PATTERN),
        from_: Optional[str] = Query(None, alias="from"),
        to: Optional[str] = Query(None),
        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant = _tid(caller)
    if range == "custom" and not (from_ and to):
        raise HTTPException(422, {"error": "custom_needs_from_to"})
    detail = await compute_user_detail(tenant, user_id, range, from_, to)
    if not detail:
        raise HTTPException(404, {"error": "user_not_found"})
    return detail


@router.get("/admin/gps/scorecard/export.csv",
             operation_id="gps.scorecard.exportCsv")
async def export_csv(
        range: str = Query("this_week", pattern=_RANGE_PATTERN),
        from_: Optional[str] = Query(None, alias="from"),
        to: Optional[str] = Query(None),
        department: Optional[str] = Query(None),
        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant = _tid(caller)
    if range == "custom" and not (from_ and to):
        raise HTTPException(422, {"error": "custom_needs_from_to"})
    board = await compute_leaderboard(tenant, range, from_, to,
                                        department, use_cache=False)

    def _stream():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["rank", "user_id", "user_name", "role", "department",
                     "score", "stops_count", "avg_stop_duration_s",
                     "total_stopped_time_s", "total_driving_time_s",
                     "total_pings_count", "unique_jobs_attributed",
                     "unique_customers_attributed", "on_time_arrival_rate",
                     "estimated_miles", "days_active",
                     "attribution_coverage", "idle_penalty"])
        yield buf.getvalue(); buf.seek(0); buf.truncate(0)
        for r in board["rows"]:
            m = r["metrics"]
            w.writerow([r["rank"], r["user_id"], r["user_name"],
                         r["role"], r.get("department") or "",
                         r["score"], m["stops_count"],
                         m["avg_stop_duration_s"],
                         m["total_stopped_time_s"],
                         m["total_driving_time_s"],
                         m["total_pings_count"],
                         m["unique_jobs_attributed"],
                         m["unique_customers_attributed"],
                         m["on_time_arrival_rate"] or "",
                         m["estimated_miles"], m["days_active"],
                         m["attribution_coverage"],
                         m["idle_penalty"]])
            yield buf.getvalue(); buf.seek(0); buf.truncate(0)

    label = board["range"]["label"].replace(" ", "_").lower()
    return StreamingResponse(
        _stream(), media_type="text/csv",
        headers={"Content-Disposition":
                  f'attachment; filename="driver_scorecard_{label}.csv"'})
