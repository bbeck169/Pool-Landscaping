"""SO-A · Feb-2026 — Tech-origin cascade.

Cascade (highest priority first):
    1. Recent GPS ping (< 4h old) from ``tech_locations`` — matches
       FLEET-A's :func:`routers.fleet._latest_location` shape.
    2. Address of the FIRST scheduled job on ``target_date`` (per
       ``route_index`` asc) — used as a proxy for "start of day".
    3. None — caller surfaces ``origin_source="unknown"`` and skips
       the tech in ``unavailable_technicians``.

The user brief mentions ``home_lat``/``home_lng`` but that field
does NOT exist on ``users`` in this codebase (recon-confirmed).
Design fork #4: substitute step 2 in its place + a warn log.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import logger

GPS_FRESHNESS_S = 4 * 3600           # 4 hours, per brief §3


@dataclass(frozen=True)
class OriginResolution:
    tech_user_id: str
    lat: Optional[float]
    lng: Optional[float]
    source: str                       # "gps" | "first_job" | "unknown"
    detail: Optional[str] = None      # human-readable e.g. "ping 2m old"


def _coalesce_coords(job: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """Same key-cascade as FLEET-A's ``_job_coords``."""
    for lat_key, lng_key in (
        ("latitude", "longitude"),
        ("site_lat", "site_lng"),
        ("lat", "lng"),
    ):
        lat, lng = job.get(lat_key), job.get(lng_key)
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            return float(lat), float(lng)
    return None


async def resolve_origin(
    *, db: Any, tenant_id: str, tech_user_id: str,
    ordered_stops_today: List[Dict[str, Any]],
    now_utc: Optional[datetime] = None,
) -> OriginResolution:
    """Compute the tech's start-of-route origin.

    ``ordered_stops_today`` — the tech's jobs on the target date,
    already sorted by ``route_index`` ascending — is used as the
    fallback origin.
    """
    now = now_utc or datetime.now(timezone.utc)

    # Step 1 · recent GPS ping.
    try:
        loc = await db.tech_locations.find_one(
            {"tenant_id": tenant_id, "tech_user_id": tech_user_id},
            {"_id": 0},
            sort=[("recorded_at", -1)],
        )
    except Exception as exc:                                       # noqa: BLE001
        logger.warning(
            "[so-a.origin] tech_locations query failed tenant=%s tech=%s err=%s",
            tenant_id, tech_user_id, exc,
        )
        loc = None
    if loc and isinstance(loc.get("lat"), (int, float)):
        try:
            rec = datetime.fromisoformat(
                str(loc.get("recorded_at") or "").replace("Z", "+00:00"),
            )
            if rec.tzinfo is None:
                rec = rec.replace(tzinfo=timezone.utc)
            age = (now - rec).total_seconds()
        except Exception:                                          # noqa: BLE001
            age = float("inf")
        if 0 <= age <= GPS_FRESHNESS_S:
            return OriginResolution(
                tech_user_id=tech_user_id,
                lat=float(loc["lat"]), lng=float(loc["lng"]),
                source="gps",
                detail=f"ping {int(age // 60)}m old",
            )

    # Step 2 · first-job proxy.
    if ordered_stops_today:
        first = ordered_stops_today[0]
        coords = _coalesce_coords(first)
        if coords is not None:
            logger.info(
                "[so-a.origin] tech=%s using first-job proxy (no fresh gps)",
                tech_user_id,
            )
            return OriginResolution(
                tech_user_id=tech_user_id,
                lat=coords[0], lng=coords[1],
                source="first_job",
                detail=f"first stop of {len(ordered_stops_today)} scheduled",
            )

    # Step 3 · give up.
    logger.warning(
        "[so-a.origin] tech=%s no gps + no scheduled stops — origin unknown",
        tech_user_id,
    )
    return OriginResolution(
        tech_user_id=tech_user_id, lat=None, lng=None,
        source="unknown", detail="no gps ping, no scheduled stops",
    )


__all__ = ["OriginResolution", "resolve_origin", "GPS_FRESHNESS_S"]
