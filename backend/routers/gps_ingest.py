"""G1 · GPS Ping Ingest endpoints.

Endpoints
---------
* ``POST /api/gps/pings`` — accept single or batched pings from a
  clocked-in technician/admin.  Validates role, gps_settings.enabled,
  open shift, field ranges, source enum, freshness, and dedup.
* ``GET  /api/gps/config`` — returns resolved tracking config for the
  current authenticated user's tenant (mobile-trimmed).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, validator

from config import db, logger
from utils import get_current_user, new_id, now_iso

router = APIRouter()

MAX_BATCH = 60
_VALID_SOURCES = {"foreground", "background"}
_STALE_HOURS = 24

# ── Roles allowed to POST pings ─────────────────────────────────────
_PING_ROLES = {"technician", "admin", "super_admin"}
# Roles allowed to GET config (wider)
_CONFIG_ROLES = {"technician", "admin", "super_admin", "manager"}


# ── Pydantic Models ─────────────────────────────────────────────────

class PingIn(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    accuracy_m: float = Field(..., ge=0, le=10000)
    source: str
    captured_at: str
    heading: Optional[float] = None
    speed_mps: Optional[float] = None
    device_id: Optional[str] = None
    app_version: Optional[str] = None

    @validator("source")
    def validate_source(cls, v: str) -> str:
        if v not in _VALID_SOURCES:
            raise ValueError(f"source must be one of {sorted(_VALID_SOURCES)}")
        return v

    @validator("captured_at")
    def validate_captured_at(cls, v: str) -> str:
        try:
            ts = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except Exception:
            raise ValueError("captured_at must be a valid ISO8601 timestamp")
        cutoff = datetime.now(timezone.utc) - timedelta(hours=_STALE_HOURS)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts < cutoff:
            raise ValueError("stale_ping")
        return v


class PingBatchIn(BaseModel):
    """Accept either ``{ pings: [...] }`` or a flat single-ping body."""
    pings: Optional[List[PingIn]] = None
    # Single-ping convenience fields (ignored when pings is supplied)
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)
    accuracy_m: Optional[float] = Field(None, ge=0, le=10000)
    source: Optional[str] = None
    captured_at: Optional[str] = None
    heading: Optional[float] = None
    speed_mps: Optional[float] = None
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
    role = (user or {}).get("role") or ""
    if role not in _PING_ROLES:
        raise HTTPException(403, {"error": "forbidden"})

    tid = (user or {}).get("tenant_id") or ""
    uid = (user or {}).get("id") or ""
    if not tid:
        raise HTTPException(400, {"error": "missing_tenant"})

    # ── Resolve pings list ───────────────────────────────────────
    pings: List[PingIn] = []
    if body.pings is not None:
        pings = body.pings
    elif body.lat is not None and body.lon is not None and body.captured_at and body.accuracy_m is not None and body.source:
        # Validate single-ping source + captured_at via PingIn constructor
        try:
            single = PingIn(
                lat=body.lat, lon=body.lon, accuracy_m=body.accuracy_m,
                heading=body.heading, speed_mps=body.speed_mps,
                source=body.source, captured_at=body.captured_at,
                device_id=body.device_id, app_version=body.app_version,
            )
            pings = [single]
        except Exception as e:
            raise HTTPException(422, {"error": str(e)})

    if not pings:
        raise HTTPException(422, {"error": "no_pings"})

    if len(pings) > MAX_BATCH:
        raise HTTPException(413, {"error": "batch_too_large", "limit": MAX_BATCH})

    # ── Server-side gates ────────────────────────────────────────
    settings = await _get_gps_settings(tid)
    if not settings.get("enabled"):
        raise HTTPException(409, {"error": "tracking_disabled"})

    shift = await _get_open_shift(tid, uid)
    if not shift:
        raise HTTPException(409, {"error": "not_clocked_in"})

    clock_in_id = shift.get("id")
    received_at = now_iso()

    # ── Dedup + insert ───────────────────────────────────────────
    inserted = 0
    dedup_count = 0

    for p in pings:
        # Soft dedup on (user_id, captured_at, source)
        existing = await db.gps_pings.find_one(
            {"user_id": uid, "captured_at": p.captured_at, "source": p.source},
            {"_id": 1},
        )
        if existing:
            dedup_count += 1
            continue

        doc = {
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
        }
        await db.gps_pings.insert_one(doc)
        inserted += 1

    logger.info("[gps_ingest] user=%s inserted=%d dedup=%d clock_in=%s",
                uid, inserted, dedup_count, clock_in_id)
    return {"inserted": inserted, "dedup_count": dedup_count,
            "clock_in_id": clock_in_id}


# ── GET /api/gps/config ─────────────────────────────────────────────

@router.get("/gps/config")
async def get_gps_config(user: dict = Depends(get_current_user)):
    role = (user or {}).get("role") or ""
    if role not in _CONFIG_ROLES:
        raise HTTPException(403, {"error": "forbidden"})

    tid = (user or {}).get("tenant_id") or ""
    if not tid:
        raise HTTPException(400, {"error": "missing_tenant"})

    settings = await _get_gps_settings(tid)
    return {
        "enabled": bool(settings.get("enabled")),
        "ping_interval_foreground_s": int(settings.get("ping_interval_foreground_s") or 60),
        "ping_interval_background_s": int(settings.get("ping_interval_background_s") or 300),
    }
