"""G2 · Feb-2026 — Server-side stop-detection algorithm.

Pure function. No I/O, no Mongo, no time-of-day awareness beyond the
timestamps embedded on the incoming pings. Given a chronologically
ordered list of pings for a single user and a set of parameters,
return the list of Stops that fall out of that trajectory.

Stop model
==========
A "stop" is a contiguous cluster of pings from the same user where:

* Every ping in the cluster is within ``stop_radius_m`` of the
  cluster's anchor (the first ping of the cluster).
* Consecutive pings in the cluster are separated by no more than
  ``stop_gap_close_s`` — a longer gap closes the cluster.
* The cluster's total duration (``last.captured_at - first.captured_at``)
  is at least ``stop_min_duration_s``; shorter candidates are discarded.

The centre of an emitted stop is the arithmetic mean of the lat/lon of
its pings.  ``radius_m`` is the max distance from that centre to any
member ping (bounded above by ``stop_radius_m``).

This module is intentionally free of any dependency on FastAPI, Mongo,
or the rest of the app, so it can be unit-tested with plain fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
from typing import Any, Iterable, List, Mapping, Sequence

_EARTH_RADIUS_M = 6_371_000.0


# ─── Distance helper (self-contained) ───────────────────────────────
def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_M * asin(sqrt(a))


# ─── Public types ───────────────────────────────────────────────────
@dataclass
class StopParams:
    stop_radius_m: float = 75.0
    stop_min_duration_s: int = 300
    stop_gap_close_s: int = 120

    def __post_init__(self) -> None:
        if self.stop_radius_m <= 0:
            raise ValueError("stop_radius_m must be > 0")
        if self.stop_min_duration_s <= 0:
            raise ValueError("stop_min_duration_s must be > 0")
        if self.stop_gap_close_s <= 0:
            raise ValueError("stop_gap_close_s must be > 0")


@dataclass
class Stop:
    tenant_id: str
    user_id: str
    started_at: str            # ISO 8601 UTC
    ended_at: str              # ISO 8601 UTC
    center_lat: float
    center_lon: float
    radius_m: float
    duration_s: int
    ping_count: int
    source: str = "algo"
    ping_ids: List[str] = field(default_factory=list)


# ─── Ping parsing helper ────────────────────────────────────────────
def _parse_ts(v: Any) -> datetime:
    """Accept either a datetime (aware/naive) or an ISO string. Returns
    a tz-aware datetime in UTC. Raises on invalid input."""
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not isinstance(v, str):
        raise ValueError(f"unparseable timestamp: {v!r}")
    ts = datetime.fromisoformat(v.replace("Z", "+00:00"))
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ─── Algorithm ──────────────────────────────────────────────────────
def detect_stops_for_user(
    pings: Sequence[Mapping[str, Any]],
    params: StopParams,
    *,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> List[Stop]:
    """Return the list of Stops embedded in ``pings``.

    Parameters
    ----------
    pings :
        Iterable of ping dicts. Each ping MUST have ``lat``, ``lon``,
        ``captured_at``. Optional: ``tenant_id``, ``user_id``, ``id``.
    params :
        Algorithm knobs (radius, min duration, gap close).
    tenant_id, user_id :
        Used as fallbacks when the individual pings don't carry them.

    The function is *idempotent* — same input → same output.
    """
    normed: List[dict] = []
    for p in pings:
        if p.get("lat") is None or p.get("lon") is None:
            continue
        try:
            ts = _parse_ts(p.get("captured_at"))
        except Exception:
            continue
        normed.append({
            "id": p.get("id"),
            "lat": float(p["lat"]),
            "lon": float(p["lon"]),
            "ts": ts,
            "tenant_id": p.get("tenant_id") or tenant_id or "",
            "user_id": p.get("user_id") or user_id or "",
        })

    normed.sort(key=lambda r: r["ts"])
    if not normed:
        return []

    def _close(candidate: List[dict]) -> Stop | None:
        if len(candidate) < 2:
            return None
        first, last = candidate[0], candidate[-1]
        duration_s = int((last["ts"] - first["ts"]).total_seconds())
        if duration_s < params.stop_min_duration_s:
            return None
        # Centroid + true radius from centroid.
        lat_c = sum(p["lat"] for p in candidate) / len(candidate)
        lon_c = sum(p["lon"] for p in candidate) / len(candidate)
        max_r = 0.0
        for p in candidate:
            d = _haversine_m(lat_c, lon_c, p["lat"], p["lon"])
            if d > max_r:
                max_r = d
        return Stop(
            tenant_id=first["tenant_id"],
            user_id=first["user_id"],
            started_at=_iso(first["ts"]),
            ended_at=_iso(last["ts"]),
            center_lat=round(lat_c, 6),
            center_lon=round(lon_c, 6),
            radius_m=round(max_r, 1),
            duration_s=duration_s,
            ping_count=len(candidate),
            source="algo",
            ping_ids=[p["id"] for p in candidate if p.get("id")],
        )

    out: List[Stop] = []
    candidate: List[dict] = [normed[0]]

    for p in normed[1:]:
        anchor = candidate[0]
        prev = candidate[-1]
        gap = (p["ts"] - prev["ts"]).total_seconds()
        dist = _haversine_m(anchor["lat"], anchor["lon"], p["lat"], p["lon"])

        if gap > params.stop_gap_close_s or dist > params.stop_radius_m:
            emitted = _close(candidate)
            if emitted is not None:
                out.append(emitted)
            candidate = [p]
        else:
            candidate.append(p)

    tail = _close(candidate)
    if tail is not None:
        out.append(tail)

    return out


__all__ = ["StopParams", "Stop", "detect_stops_for_user", "_haversine_m"]
