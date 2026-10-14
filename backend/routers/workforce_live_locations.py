"""P1 Phase 3 · Feb-2026 — Live technician GPS pins for Schedule map.

Serves ``GET /api/workforce/live-locations`` — read-only snapshot
of the most-recent ``gps_pings`` document for every technician /
worker in the current tenant whose latest ping is less than 2
hours old.  Consumed by the admin Schedule page's live-tech
overlay (polled every 30s).

Reuses the Branch 1 ping collection (``db.gps_pings``,
``captured_at`` / ``lat`` / ``lon``) that the mileage calculator
and the mileage audit endpoint now consult — the collection the
background-safe ``expo-task-manager`` GpsTracker service writes
to.  Does NOT read ``location_pings`` (foreground-only legacy
path).

Role gate
---------
``require_gps_read`` (admin / super_admin / owner / manager /
dispatcher) — reuses the shipped helper in ``utils.py`` that
every other GPS-read surface already uses.  Techs POST pings but
cannot READ cross-tech locations.

Staleness buckets
-----------------
    * ``live``   — age_seconds ≤ 120 (2 min).
    * ``recent`` — age_seconds ≤ 600 (10 min).
    * ``stale``  — age_seconds ≤ 7200 (2 hr).
    * > 2 hr    — excluded from the response entirely.

Perf
----
Backed by the compound index
``gps_pings(tenant_id, user_id, captured_at desc)`` added in
``scripts/ensure_indexes._gps_pings_user_captured_at_index`` so
the per-tech "latest ping" lookup is a single index scan.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends

from config import db
from routers.tenants import get_current_tenant
from utils import require_gps_read


router = APIRouter()


# Staleness thresholds in seconds — keep as constants so pytest
# can import them directly and pin boundary behaviour.
STALENESS_LIVE_MAX_S = 120
STALENESS_RECENT_MAX_S = 600
STALENESS_STALE_MAX_S = 7200  # 2 hours — exclude anything older.

# Roles that qualify as a technician on the Schedule map.
_TECH_ROLES = ("technician", "worker")


def classify_staleness(age_seconds: int) -> Optional[str]:
    """Return the staleness bucket or ``None`` when the ping is
    too old to show.  Pure helper so unit tests pin boundaries.
    """
    if age_seconds < 0:
        # Clock skew (ping stamped in the future) — surface as
        # ``live`` instead of hiding the pin; this keeps the map
        # useful during local time-sync drift.
        return "live"
    if age_seconds <= STALENESS_LIVE_MAX_S:
        return "live"
    if age_seconds <= STALENESS_RECENT_MAX_S:
        return "recent"
    if age_seconds <= STALENESS_STALE_MAX_S:
        return "stale"
    return None


@router.get("/workforce/live-locations")
async def live_locations(
    _user: Dict[str, Any] = Depends(require_gps_read),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Return the most-recent ``gps_pings`` doc per active
    technician in the current tenant, excluding pings older than
    2 hours.
    """
    tenant_id = tenant["id"]
    now = datetime.now(timezone.utc)
    cutoff_iso = (now - timedelta(seconds=STALENESS_STALE_MAX_S)).isoformat()

    # Resolve candidate technician user ids first — bounds the
    # per-user ping lookup below.  Soft-deleted + inactive users
    # excluded.
    users = await db.users.find(
        {
            "tenant_id": tenant_id,
            "role": {"$in": list(_TECH_ROLES)},
            "$and": [
                {"$or": [
                    {"deleted_at": {"$exists": False}},
                    {"deleted_at": None},
                ]},
                {"$or": [
                    {"is_active": True},
                    {"is_active": None},
                    {"is_active": {"$exists": False}},
                ]},
            ],
        },
        {"_id": 0, "id": 1, "name": 1, "email": 1},
    ).to_list(500)

    pings: List[Dict[str, Any]] = []
    for u in users:
        uid = u.get("id")
        if not uid:
            continue
        latest = await db.gps_pings.find_one(
            {
                "tenant_id": tenant_id,
                "user_id": uid,
                "captured_at": {"$gte": cutoff_iso},
            },
            {"_id": 0, "captured_at": 1, "lat": 1, "lon": 1},
            sort=[("captured_at", -1)],
        )
        if not latest:
            continue
        lat = latest.get("lat")
        lon = latest.get("lon")
        if lat is None or lon is None:
            continue
        age = _age_seconds(latest.get("captured_at"), now)
        bucket = classify_staleness(age)
        if bucket is None:
            continue
        pings.append({
            "user_id": uid,
            "user_name": u.get("name") or u.get("email") or "",
            "lat": float(lat),
            "lon": float(lon),
            "captured_at": latest.get("captured_at"),
            "age_seconds": age,
            "staleness": bucket,
        })

    # Stable sort — freshest first so the FE can render in order.
    pings.sort(key=lambda p: p["age_seconds"])

    return {"pings": pings, "server_time": now.isoformat()}


def _age_seconds(captured_at: Optional[str],
                  now: datetime) -> int:
    if not captured_at:
        return STALENESS_STALE_MAX_S + 1
    try:
        s = captured_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return STALENESS_STALE_MAX_S + 1
    return int((now - dt).total_seconds())
