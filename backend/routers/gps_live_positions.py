"""Feb-2026 · GPS Live Positions (Phase P2 of the G-series).

Endpoint::

    GET /api/gps/live-positions

Returns the most recent GPS pin (within the last 5 minutes) for every
currently clocked-in user for the caller's tenant. Powers the live
technician markers on the Dispatch Board.

Auth
----
* admin, super_admin, manager  → 200
* technician, customer, anon    → 403

The endpoint returns ``{ as_of, positions: [] }`` (not 404) whenever:
* GPS tracking is disabled (``gps_settings.enabled == False``)
* No shifts are currently open
* No open shift has a fresh (<5 min) ping

This lets the dispatch board poll harmlessly regardless of setup state.

Row shape::

    {
      "user_id":     str,
      "user_name":   str,
      "lat":         float,
      "lon":         float,
      "accuracy_m":  float | None,
      "captured_at": ISO datetime,
      "clock_in_id": str,
      "staleness_s": int,   # seconds between captured_at and server now
    }
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from config import db
from utils import get_current_user, now_iso

router = APIRouter()

_ALLOWED_ROLES = {"admin", "super_admin", "manager"}
_MAX_STALENESS_S = 300  # 5 minutes


def _parse_iso(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        ts = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


@router.get("/gps/live-positions", operation_id="gps.livePositions")
async def get_live_positions(user: Dict[str, Any] = Depends(get_current_user)):
    role = (user or {}).get("role") or ""
    if role not in _ALLOWED_ROLES:
        raise HTTPException(403, {"error": "forbidden"})

    tenant_id = (user or {}).get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(400, {"error": "missing_tenant"})

    as_of_dt = datetime.now(timezone.utc)
    as_of = as_of_dt.isoformat().replace("+00:00", "Z")

    # 1) Tracking toggle. Absence => disabled (matches gps_ingest.py default).
    settings = await db.gps_settings.find_one(
        {"tenant_id": tenant_id}, {"_id": 0, "enabled": 1},
    )
    if not settings or not settings.get("enabled"):
        return {"as_of": as_of, "positions": []}

    # 2) Open shifts (clock_out_at is null) — only these techs count.
    open_shifts: List[Dict[str, Any]] = []
    async for shift in db.time_entries.find(
        {"tenant_id": tenant_id, "clock_out_at": None},
        {"_id": 0, "id": 1, "user_id": 1, "user_name": 1},
    ):
        open_shifts.append(shift)

    if not open_shifts:
        return {"as_of": as_of, "positions": []}

    cutoff_dt = as_of_dt - timedelta(seconds=_MAX_STALENESS_S)

    positions: List[Dict[str, Any]] = []
    for shift in open_shifts:
        uid = shift.get("user_id")
        if not uid:
            continue

        # Most recent ping in the window for this user.
        latest = await db.gps_pings.find_one(
            {"tenant_id": tenant_id, "user_id": uid},
            {"_id": 0, "lat": 1, "lon": 1, "accuracy_m": 1,
             "captured_at": 1, "clock_in_id": 1},
            sort=[("captured_at", -1)],
        )
        if not latest:
            continue

        captured_dt = _parse_iso(latest.get("captured_at"))
        if not captured_dt or captured_dt < cutoff_dt:
            continue

        staleness = int((as_of_dt - captured_dt).total_seconds())
        if staleness < 0:
            staleness = 0

        positions.append({
            "user_id": uid,
            "user_name": shift.get("user_name") or "",
            "lat": float(latest["lat"]),
            "lon": float(latest["lon"]),
            "accuracy_m": (
                float(latest["accuracy_m"])
                if latest.get("accuracy_m") is not None else None
            ),
            "captured_at": latest.get("captured_at"),
            "clock_in_id": latest.get("clock_in_id") or shift.get("id"),
            "staleness_s": staleness,
        })

    # Newest first (smallest staleness first) for a stable UI order.
    positions.sort(key=lambda r: r["staleness_s"])

    # G3 · Feb-2026 — enrich each pin with a reverse-geocoded address
    # if available (cache-first; no Mapbox call when token missing).
    try:
        from services.reverse_geocoder import reverse_geocode
        for p in positions:
            try:
                r = await reverse_geocode(p["lat"], p["lon"], tenant_id)
                p["address"] = r.get("address")
                p["address_status"] = r.get("status")
            except Exception:                                            # noqa: BLE001
                p["address"] = None
                p["address_status"] = "error"
    except Exception:                                                    # noqa: BLE001
        pass

    # G5a · Feb-2026 — recent geofence crossings (last 60s) so the
    # dispatch board can toast on new enter/exit events. Additive
    # field only; missing/empty is treated as "no new crossings" by
    # the UI. Cap at 50 to keep the poll response bounded.
    recent_crossings: List[Dict[str, Any]] = []
    try:
        cutoff = (as_of_dt - timedelta(seconds=60)).isoformat().replace(
            "+00:00", "+00:00")
        async for e in db.geofence_events.find(
            {"tenant_id": tenant_id, "detected_at": {"$gte": cutoff}},
            {"_id": 0, "id": 1, "geofence_id": 1, "geofence_name": 1,
             "user_id": 1, "user_name": 1, "crossing": 1,
             "detected_at": 1, "lat": 1, "lon": 1},
        ).sort("detected_at", -1).limit(50):
            recent_crossings.append(e)
    except Exception:                                                    # noqa: BLE001
        recent_crossings = []

    return {"as_of": as_of, "positions": positions,
            "recent_crossings": recent_crossings}
