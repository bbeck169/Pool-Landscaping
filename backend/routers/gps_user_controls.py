"""Phase G4 · Feb-2026 — GPS per-user admin controls + CSV exports.

Admin+/manager only. Tenant-scoped. Extends G0-G3.

Endpoints
---------
* ``GET  /admin/gps/tracking-summary``
* ``PATCH /admin/gps/users/{user_id}``
* ``GET  /admin/gps/export/activity.csv``
* ``GET  /admin/gps/export/pings.csv``
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso

router = APIRouter()

_MOD_ROLES = {"admin", "super_admin", "manager"}
_TECH_ROLES = {"technician"}
_ACTIVITY_ROW_CAP = 50_000
_PINGS_ROW_CAP = 100_000
_MAX_WINDOW_DAYS = 90


def _require_mod(user: Dict[str, Any]) -> None:
    if (user or {}).get("role") not in _MOD_ROLES:
        raise HTTPException(403, {"error": "forbidden"})


def _tenant_or_400(user: Dict[str, Any]) -> str:
    tid = (user or {}).get("tenant_id") or ""
    if not tid:
        raise HTTPException(400, {"error": "missing_tenant"})
    return tid


def _parse_iso(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


# ═══════════════════════ Tracking summary ══════════════════════════

@router.get("/admin/gps/tracking-summary",
             operation_id="gps.trackingSummary")
async def tracking_summary(
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)

    settings = await db.gps_settings.find_one(
        {"tenant_id": tenant_id}, {"_id": 0}) or {}
    tenant_enabled = bool(settings.get("enabled"))
    hr_agreement_ack = bool(settings.get("hr_agreement_ack"))

    techs: List[Dict[str, Any]] = []
    async for u in db.users.find(
            {"tenant_id": tenant_id, "role": "technician",
              "deleted_at": None},
            {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1,
              "gps_tracking_opt_out": 1,
              "gps_retention_override_days": 1,
              "gps_tracking_note": 1,
              "gps_tracking_updated_at": 1}):
        techs.append(u)

    # Open shifts (map of user_id → shift row).
    open_shifts: Dict[str, Any] = {}
    async for s in db.time_entries.find(
            {"tenant_id": tenant_id, "clock_out_at": None},
            {"_id": 0, "user_id": 1, "id": 1}):
        open_shifts[s["user_id"]] = s

    # Last ping per tech (single roundtrip via aggregation).
    now = datetime.now(timezone.utc)
    fresh_cutoff = (now - timedelta(minutes=5)).isoformat()
    last_pings: Dict[str, str] = {}
    pipeline = [
        {"$match": {"tenant_id": tenant_id}},
        {"$sort": {"user_id": 1, "captured_at": -1}},
        {"$group": {"_id": "$user_id",
                     "captured_at": {"$first": "$captured_at"}}},
    ]
    async for row in db.gps_pings.aggregate(pipeline):
        last_pings[row["_id"]] = row["captured_at"]

    tech_rows: List[Dict[str, Any]] = []
    opted_in = opted_out = clocked_in = sending = 0
    for t in techs:
        opt_out = bool(t.get("gps_tracking_opt_out"))
        last_at = last_pings.get(t["id"])
        seconds_ago: Optional[int] = None
        is_fresh = False
        if last_at:
            try:
                dt = _parse_iso(last_at)
                seconds_ago = max(0, int((now - dt).total_seconds()))
                is_fresh = last_at >= fresh_cutoff
            except Exception:                                            # noqa: BLE001
                pass
        row_clocked_in = t["id"] in open_shifts
        tech_rows.append({
            "user_id": t["id"],
            "user_name": t.get("name") or t.get("email") or "",
            "role": t.get("role"),
            "opted_out": opt_out,
            "retention_override_days":
                t.get("gps_retention_override_days"),
            "clocked_in": row_clocked_in,
            "last_ping_at": last_at,
            "last_ping_seconds_ago": seconds_ago,
            "note": t.get("gps_tracking_note"),
            "updated_at": t.get("gps_tracking_updated_at"),
        })
        if opt_out:
            opted_out += 1
        elif tenant_enabled:
            opted_in += 1
        if row_clocked_in and not opt_out:
            clocked_in += 1
        if is_fresh and not opt_out:
            sending += 1

    return {
        "as_of": now_iso(),
        "tenant_enabled": tenant_enabled,
        "hr_agreement_ack": hr_agreement_ack,
        "counts": {
            "total_technicians": len(techs),
            "opted_in": opted_in,
            "opted_out": opted_out,
            "clocked_in_now": clocked_in,
            "sending_pings_now": sending,
        },
        "technicians": tech_rows,
    }


# ═══════════════════════ PATCH /admin/gps/users/{id} ═══════════════

class UserGpsPatch(BaseModel):
    gps_tracking_opt_out: Optional[bool] = None
    gps_retention_override_days: Optional[int] = Field(
        None, ge=7, le=365)
    gps_tracking_note: Optional[str] = None


@router.patch("/admin/gps/users/{user_id}",
               operation_id="gps.patchUserOverride")
async def patch_user_override(
    user_id: str,
    body: UserGpsPatch,
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    row = await db.users.find_one(
        {"id": user_id, "tenant_id": tenant_id,
          "deleted_at": None}, {"_id": 0})
    if not row:
        raise HTTPException(404, {"error": "user_not_found"})

    updates: Dict[str, Any] = {}
    before: Dict[str, Any] = {}
    if body.gps_tracking_opt_out is not None:
        before["gps_tracking_opt_out"] = row.get("gps_tracking_opt_out")
        updates["gps_tracking_opt_out"] = bool(body.gps_tracking_opt_out)
    if body.gps_retention_override_days is not None:
        before["gps_retention_override_days"] = row.get(
            "gps_retention_override_days")
        updates["gps_retention_override_days"] = int(
            body.gps_retention_override_days)
    if body.gps_tracking_note is not None:
        before["gps_tracking_note"] = row.get("gps_tracking_note")
        updates["gps_tracking_note"] = body.gps_tracking_note

    if not updates:
        return {"unchanged": True, "user_id": user_id}

    updates["gps_tracking_updated_at"] = now_iso()
    updates["gps_tracking_updated_by_user_id"] = caller["id"]

    await db.users.update_one(
        {"id": user_id, "tenant_id": tenant_id},
        {"$set": updates})

    # Audit trail.
    await db.audits.insert_one({
        "id": new_id(),
        "tenant_id": tenant_id,
        "kind": "gps_user_override_changed",
        "actor_user_id": caller["id"],
        "target_user_id": user_id,
        "before": before,
        "after": {k: v for k, v in updates.items()
                    if k not in {"gps_tracking_updated_at",
                                  "gps_tracking_updated_by_user_id"}},
        "created_at": now_iso(),
    })

    fresh = await db.users.find_one(
        {"id": user_id, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1, "email": 1,
          "gps_tracking_opt_out": 1,
          "gps_retention_override_days": 1,
          "gps_tracking_note": 1,
          "gps_tracking_updated_at": 1,
          "gps_tracking_updated_by_user_id": 1})
    return {"updated": True, "user": fresh}


# ═══════════════════════ CSV exports ═══════════════════════════════

def _stream_csv(header: List[str],
                    row_iter: AsyncGenerator[List[Any], None]
                    ) -> AsyncGenerator[bytes, None]:
    async def _gen() -> AsyncGenerator[bytes, None]:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        yield buf.getvalue().encode("utf-8")
        buf.seek(0); buf.truncate(0)
        async for row in row_iter:
            w.writerow(row)
            yield buf.getvalue().encode("utf-8")
            buf.seek(0); buf.truncate(0)
    return _gen()


def _validate_range(from_: str, to: str) -> tuple[str, str]:
    try:
        f = _parse_iso(from_)
        t = _parse_iso(to)
    except Exception:
        raise HTTPException(400, {"error": "invalid_datetime"})
    if t <= f:
        raise HTTPException(400, {"error": "invalid_range"})
    if (t - f).days > _MAX_WINDOW_DAYS:
        raise HTTPException(400, {"error": "range_too_large",
                                    "max_days": _MAX_WINDOW_DAYS})
    return from_.replace("Z", "+00:00"), to.replace("Z", "+00:00")


async def _tech_name_map(tenant_id: str) -> Dict[str, str]:
    m: Dict[str, str] = {}
    async for u in db.users.find(
            {"tenant_id": tenant_id, "role": "technician"},
            {"_id": 0, "id": 1, "name": 1, "email": 1}):
        m[u["id"]] = u.get("name") or u.get("email") or ""
    return m


@router.get("/admin/gps/export/activity.csv",
             operation_id="gps.exportActivityCsv")
async def export_activity_csv(
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    user_id: Optional[str] = Query(None),
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    f, t = _validate_range(from_, to)

    q: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "started_at": {"$gte": f, "$lte": t},
    }
    if user_id:
        q["user_id"] = user_id

    total = await db.driver_stops.count_documents(q)
    if total > _ACTIVITY_ROW_CAP:
        raise HTTPException(413, {"error": "row_cap_exceeded",
                                    "cap": _ACTIVITY_ROW_CAP,
                                    "matched": total})

    name_map = await _tech_name_map(tenant_id)

    async def _rows():
        cursor = db.driver_stops.find(q, {"_id": 0}) \
                                    .sort("started_at", 1)
        async for s in cursor:
            addr = (s.get("address") or {}).get("formatted") or ""
            yield [
                s.get("user_id") or "",
                name_map.get(s.get("user_id") or "", ""),
                s.get("started_at") or "",
                s.get("ended_at") or "",
                s.get("duration_s") or 0,
                s.get("center_lat"),
                s.get("center_lon"),
                addr,
                len(s.get("ping_ids") or []),
            ]

    header = ["user_id", "user_name", "started_at", "ended_at",
              "duration_s", "center_lat", "center_lon", "address",
              "ping_count"]
    filename = f'driver_activity_{from_.replace(":", "").replace("-", "")}_{to.replace(":", "").replace("-", "")}.csv'
    return StreamingResponse(
        _stream_csv(header, _rows()),
        media_type="text/csv",
        headers={"Content-Disposition":
                  f'attachment; filename="{filename}"'},
    )


@router.get("/admin/gps/export/pings.csv",
             operation_id="gps.exportPingsCsv")
async def export_pings_csv(
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    user_id: Optional[str] = Query(None),
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    f, t = _validate_range(from_, to)

    q: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "captured_at": {"$gte": f, "$lte": t},
    }
    if user_id:
        q["user_id"] = user_id

    total = await db.gps_pings.count_documents(q)
    if total > _PINGS_ROW_CAP:
        raise HTTPException(413, {"error": "row_cap_exceeded",
                                    "cap": _PINGS_ROW_CAP,
                                    "matched": total})

    name_map = await _tech_name_map(tenant_id)

    async def _rows():
        cursor = db.gps_pings.find(
            q, {"_id": 0, "user_id": 1, "captured_at": 1,
                 "lat": 1, "lon": 1, "accuracy_m": 1,
                 "source": 1, "clock_in_id": 1}
            ).sort("captured_at", 1)
        async for p in cursor:
            yield [
                p.get("user_id") or "",
                name_map.get(p.get("user_id") or "", ""),
                p.get("captured_at") or "",
                p.get("lat"),
                p.get("lon"),
                p.get("accuracy_m"),
                p.get("source") or "",
                p.get("clock_in_id") or "",
            ]

    header = ["user_id", "user_name", "captured_at", "lat", "lon",
              "accuracy_m", "source", "clock_in_id"]
    filename = f'gps_pings_{from_.replace(":", "").replace("-", "")}_{to.replace(":", "").replace("-", "")}.csv'
    return StreamingResponse(
        _stream_csv(header, _rows()),
        media_type="text/csv",
        headers={"Content-Disposition":
                  f'attachment; filename="{filename}"'},
    )
