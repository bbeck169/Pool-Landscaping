"""G0 · Feb-2026 — GPS Driver Activity foundational endpoints.

Scaffolding phase — schema stubs, admin settings, purge helper. No
live pings are collected yet; that lands in G1 with the mobile
``expo-location`` wire.

Endpoints
---------
* ``GET  /api/admin/gps/settings`` — returns the tenant's settings
  row, creating a default one on first read.
* ``PUT  /api/admin/gps/settings`` — updates any subset of the
  tunable fields.  Enabling tracking requires the HR-agreement
  acknowledgement (soft gate).

Purge helper
------------
* ``purge_expired_pings()`` — coroutine callable from the app
  scheduler. Iterates every tenant, drops ``gps_pings`` rows
  whose ``captured_at`` is older than the tenant's ``retention_days``.
  Safe against empty collections.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso

router = APIRouter()

_ALLOWED_GEOCODERS = {"mapbox"}


def _require_admin(user: dict) -> None:
    role = (user or {}).get("role") or ""
    if role not in ("admin", "super_admin"):
        raise HTTPException(403, {"error": "forbidden"})


def _default_row(tenant_id: str) -> Dict[str, Any]:
    """Fresh settings row for a tenant that has never opened the page."""
    return {
        "id": new_id(),
        "tenant_id": tenant_id,
        "enabled": False,
        "hr_agreement_ack": False,
        "ping_interval_foreground_s": 60,
        "ping_interval_background_s": 300,
        "retention_days": 90,
        "geocoder": "mapbox",
        # G2 · Feb-2026 — Stop-detection tunables.
        "stop_radius_m": 75,
        "stop_min_duration_s": 300,
        "stop_gap_close_s": 120,
        "stop_batch_window_min": 15,
        "updated_at": now_iso(),
        "updated_by_user_id": None,
    }


async def _ensure_indexes() -> None:
    """Idempotent index setup — invoked lazily from GET so we don't
    add a boot-time hard dependency on Mongo readiness."""
    try:
        await db.gps_settings.create_index("tenant_id", unique=True)
        await db.gps_pings.create_index(
            [("tenant_id", 1), ("user_id", 1), ("captured_at", -1)])
        await db.gps_pings.create_index("captured_at")
        await db.driver_stops.create_index(
            [("tenant_id", 1), ("user_id", 1), ("started_at", -1)])
    except Exception as e:                                            # noqa: BLE001
        logger.debug("[gps] index setup skipped: %s", e)


class GpsSettingsPatch(BaseModel):
    enabled: Optional[bool] = None
    hr_agreement_ack: Optional[bool] = None
    ping_interval_foreground_s: Optional[int] = Field(None, ge=15, le=600)
    ping_interval_background_s: Optional[int] = Field(None, ge=60, le=3600)
    retention_days: Optional[int] = Field(None, ge=7, le=365)
    geocoder: Optional[str] = None
    # G2 · Feb-2026 — Stop-detection tunables (see gps_stop_detector.py).
    stop_radius_m: Optional[int] = Field(None, ge=10, le=500)
    stop_min_duration_s: Optional[int] = Field(None, ge=60, le=3600)
    stop_gap_close_s: Optional[int] = Field(None, ge=30, le=900)
    stop_batch_window_min: Optional[int] = Field(None, ge=5, le=120)


@router.get("/admin/gps/settings")
async def get_gps_settings(user: dict = Depends(get_current_user)):
    _require_admin(user)
    tid = (user or {}).get("tenant_id") or ""
    if not tid:
        raise HTTPException(400, {"error": "missing_tenant"})
    await _ensure_indexes()
    row = await db.gps_settings.find_one({"tenant_id": tid}, {"_id": 0})
    if not row:
        row = _default_row(tid)
        await db.gps_settings.insert_one(dict(row))
    return row


@router.put("/admin/gps/settings")
async def put_gps_settings(body: GpsSettingsPatch,
                              user: dict = Depends(get_current_user)):
    _require_admin(user)
    tid = (user or {}).get("tenant_id") or ""
    if not tid:
        raise HTTPException(400, {"error": "missing_tenant"})
    await _ensure_indexes()

    row = await db.gps_settings.find_one({"tenant_id": tid}, {"_id": 0})
    if not row:
        row = _default_row(tid)
        await db.gps_settings.insert_one(dict(row))

    upd = {k: v for k, v in body.dict(exclude_none=True).items()}
    if not upd:
        return row

    if "geocoder" in upd and upd["geocoder"] not in _ALLOWED_GEOCODERS:
        raise HTTPException(422, {"error": "invalid_geocoder",
                                     "allowed": sorted(_ALLOWED_GEOCODERS)})

    # HR-agreement soft gate — enabled=true requires ack=true either
    # already stored or being set in this payload.
    if upd.get("enabled") is True:
        ack_after = upd.get("hr_agreement_ack",
                              row.get("hr_agreement_ack") or False)
        if not ack_after:
            raise HTTPException(422, {"error": "hr_agreement_required"})

    upd["updated_at"] = now_iso()
    upd["updated_by_user_id"] = (user or {}).get("id")
    await db.gps_settings.update_one({"tenant_id": tid},
                                        {"$set": upd})
    return await db.gps_settings.find_one({"tenant_id": tid}, {"_id": 0})


# ══════════════════════════════════════════════════════════════════
# Purge cron
# ══════════════════════════════════════════════════════════════════
async def purge_expired_pings() -> Dict[str, int]:
    """Delete expired ``gps_pings`` rows per tenant per its own
    ``retention_days`` setting. Safe against empty collections."""
    now = datetime.now(timezone.utc)
    total_purged = 0
    tenant_count = 0
    async for row in db.gps_settings.find(
        {}, {"_id": 0, "tenant_id": 1, "retention_days": 1},
    ):
        tid = row["tenant_id"]
        days = int(row.get("retention_days") or 90)
        cutoff = (now - timedelta(days=days)).isoformat()
        try:
            res = await db.gps_pings.delete_many(
                {"tenant_id": tid, "captured_at": {"$lt": cutoff}})
            purged = int(res.deleted_count or 0)
        except Exception as e:                                        # noqa: BLE001
            logger.warning("[gps_purge] tenant=%s delete error: %s", tid, e)
            purged = 0
        try:
            retained = await db.gps_pings.count_documents({"tenant_id": tid})
        except Exception:
            retained = -1
        logger.info(
            "[gps_purge] tenant=%s retained=%s purged=%s",
            tid, retained, purged,
        )
        total_purged += purged
        tenant_count += 1
    return {"tenants": tenant_count, "purged": total_purged}
