"""G1 · GPS Ping Ingest endpoints.

Endpoints
---------
* ``POST /api/gps/pings`` — accept single or batched pings from a
  clocked-in technician.  Verifies both ``gps_settings.enabled`` and
  the user having an open shift.
* ``GET  /api/gps/config`` — returns resolved tracking config for the
  current authenticated user's tenant.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso

router = APIRouter()

MAX_BATCH = 60


# ── Models ──────────────────────────────────────────────────────────

class PingIn(BaseModel):
    lat: float
    lon: float
    accuracy_m: Optional[float] = None
    heading: Optional[float] = None
    speed_mps: Optional[float] = None
    source: str = "foreground"
    captured_at: str
    device_id: Optional[str] = None
    app_version: Optional[str] = None


class PingBatchIn(BaseModel):
    """Accept either a single ping or an array."""
    pings: Optional[List[PingIn]] = None
    # Also accept top-level single ping fields for convenience
    lat: Optional[float] = None
    lon: Optional[float] = None
    accuracy_m: Optional[float] = None
    heading: Optional[float] = None
    speed_mps: Optional[float] = None
    source: str = "foreground"
    captured_at: Optional[str] = None
    device_id: Optional[str] = None
    app_version: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────

async def _get_gps_settings(tenant_id: str) -> Dict[str, Any]:
    row = await db.gps_settings.find_one({"tenant_id": tenant_id}, {"_id": 0})
    if not row:
        return {"enabled": False, "ping_interval_foreground_s": 60,
                "ping_interval_background_s": 300}
    return row


async def _get_open_shift(tenant_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    return await db.time_entries.find_one(
        {"tenant_id": tenant_id, "user_id": user_id, "clock_out_at": None},
        {"_id": 0},
    )


# ── POST /api/gps/pings ─────────────────────────────────────────────

@router.post("/gps/pings")
async def ingest_pings(body: PingBatchIn,
                       user: dict = Depends(get_current_user)):
    tid = (user or {}).get("tenant_id") or ""
    uid = (user or {}).get("id") or ""
    if not tid:
        raise HTTPException(400, {"error": "missing_tenant"})

    # Resolve pings list
    pings: List[PingIn] = []
    if body.pings:
        pings = body.pings
    elif body.lat is not None and body.lon is not None and body.captured_at:
        pings = [PingIn(
            lat=body.lat, lon=body.lon, accuracy_m=body.accuracy_m,
            heading=body.heading, speed_mps=body.speed_mps,
            source=body.source, captured_at=body.captured_at,
            device_id=body.device_id, app_version=body.app_version,
        )]

    if not pings:
        raise HTTPException(422, {"error": "no_pings"})

    if len(pings) > MAX_BATCH:
        raise HTTPException(413, {"error": "batch_too_large",
                                  "max": MAX_BATCH, "received": len(pings)})

    # Check GPS settings enabled
    settings = await _get_gps_settings(tid)
    if not settings.get("enabled"):
        raise HTTPException(409, {"error": "tracking_not_enabled"})

    # Check user has open shift
    shift = await _get_open_shift(tid, uid)
    if not shift:
        raise HTTPException(409, {"error": "not_clocked_in"})

    clock_in_id = shift.get("id")
    received_at = now_iso()

    docs = []
    for p in pings:
        docs.append({
            "id": new_id(),
            "tenant_id": tid,
            "user_id": uid,
            "clock_in_id": clock_in_id,
            "lat": p.lat,
            "lon": p.lon,
            "accuracy_m": p.accuracy_m,
            "heading": p.heading,
            "speed_mps": p.speed_mps,
            "source": p.source,
            "captured_at": p.captured_at,
            "received_at": received_at,
            "device_id": p.device_id,
            "app_version": p.app_version,
        })

    if len(docs) == 1:
        await db.gps_pings.insert_one(docs[0])
    else:
        await db.gps_pings.insert_many(docs)

    logger.info("[gps_ingest] user=%s pings=%d clock_in=%s", uid, len(docs), clock_in_id)
    return {"inserted": len(docs), "clock_in_id": clock_in_id}


# ── GET /api/gps/config ─────────────────────────────────────────────

@router.get("/gps/config")
async def get_gps_config(user: dict = Depends(get_current_user)):
    tid = (user or {}).get("tenant_id") or ""
    if not tid:
        raise HTTPException(400, {"error": "missing_tenant"})

    settings = await _get_gps_settings(tid)
    return {
        "enabled": bool(settings.get("enabled")),
        "ping_interval_foreground_s": int(settings.get("ping_interval_foreground_s") or 60),
        "ping_interval_background_s": int(settings.get("ping_interval_background_s") or 300),
    }
