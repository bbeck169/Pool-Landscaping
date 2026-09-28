"""SO-A · Feb-2026 — Detour-cost math (pure, no I/O).

For a tech with an ordered route ``[J0, J1, ..., Jn]`` and a
proposed insertion ``TARGET`` we compute:

  * baseline route duration   = origin → J0 → ... → Jn
  * with-insertion duration_i = origin → ... → J(i-1) → TARGET → J(i) → ... → Jn
  * detour_delta_i            = with_i - baseline
  * best insertion            = argmin_i detour_delta_i

The ETA provider is passed in as an async callable so this module
stays pure and testable without spinning up httpx.  Callers wire it
to :func:`services.fleet.eta.compute_eta` in production and to a
deterministic fake in unit tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple


Coord = Tuple[float, float]
EtaCallable = Callable[[float, float, float, float], Awaitable[Any]]


@dataclass(frozen=True)
class Stop:
    """One route stop.  ``job_id`` is opaque to this module."""
    job_id: str
    lat: float
    lng: float


@dataclass(frozen=True)
class InsertionResult:
    insertion_index: int
    detour_seconds: float
    detour_meters: float
    baseline_seconds: float
    with_insertion_seconds: float
    provider_used: str        # dominant provider across the pair scan


async def _pair_eta(
    a: Coord, b: Coord, *, eta_fn: EtaCallable,
    cache: Dict[Tuple[Coord, Coord], Any],
) -> Any:
    """Request-scoped memoisation for pairwise ETA lookups.  Route
    with 6 stops = 7 pair calls baseline + 7 per insertion; caching
    prevents re-hitting the provider for the same (a,b) across
    every candidate index.
    """
    key = (a, b)
    if key in cache:
        return cache[key]
    result = await eta_fn(a[0], a[1], b[0], b[1])
    cache[key] = result
    return result


async def _route_duration(
    origin: Coord, stops: List[Stop], *, eta_fn: EtaCallable,
    cache: Dict[Tuple[Coord, Coord], Any],
) -> Tuple[float, float, List[str]]:
    """Sum drive time + distance across origin → stops[0] → ... →
    stops[-1].  Does NOT round-trip back to origin — assumes the
    tech ends at the last stop.  Returns
    ``(seconds, meters, providers_used_list)``.
    """
    if not stops:
        return 0.0, 0.0, []
    total_s = 0.0
    total_m = 0.0
    providers: List[str] = []
    prev: Coord = origin
    for s in stops:
        r = await _pair_eta(prev, (s.lat, s.lng), eta_fn=eta_fn, cache=cache)
        total_s += float(getattr(r, "duration_s", 0) or 0)
        total_m += float(getattr(r, "distance_m", 0) or 0)
        providers.append(str(getattr(r, "provider", "crowflies")))
        prev = (s.lat, s.lng)
    return total_s, total_m, providers


def _dominant_provider(pool: List[str]) -> str:
    """The most-frequent provider name in ``pool`` — tie-broken by
    the ranking order (google > osrm > crowflies)."""
    if not pool:
        return "crowflies"
    counts: Dict[str, int] = {}
    for p in pool:
        counts[p] = counts.get(p, 0) + 1
    order = {"google": 3, "osrm": 2, "crowflies": 1}
    best = max(counts.items(), key=lambda kv: (kv[1], order.get(kv[0], 0)))
    return best[0]


async def best_insertion(
    origin: Coord, existing_stops: List[Stop], target: Stop,
    *, eta_fn: EtaCallable,
    cache: Optional[Dict[Tuple[Coord, Coord], Any]] = None,
) -> InsertionResult:
    """Return the best (min-detour) insertion for ``target`` into
    the ordered route ``existing_stops`` starting at ``origin``.

    Indices are 0-based: ``insertion_index = 0`` means the target
    becomes the tech's first stop; ``insertion_index = len(stops)``
    means the target becomes the LAST stop.
    """
    cache = cache if cache is not None else {}

    # Baseline.
    baseline_s, _baseline_m, base_providers = await _route_duration(
        origin, existing_stops, eta_fn=eta_fn, cache=cache,
    )

    best_idx = 0
    best_detour_s = float("inf")
    best_detour_m = 0.0
    best_with_s = 0.0
    best_providers: List[str] = []

    # Try every candidate index 0..len(stops).
    for i in range(len(existing_stops) + 1):
        candidate = (
            list(existing_stops[:i]) + [target] + list(existing_stops[i:])
        )
        with_s, with_m, providers = await _route_duration(
            origin, candidate, eta_fn=eta_fn, cache=cache,
        )
        detour = with_s - baseline_s
        if detour < best_detour_s:
            best_idx = i
            best_detour_s = detour
            best_detour_m = with_m
            best_with_s = with_s
            best_providers = providers

    return InsertionResult(
        insertion_index=best_idx,
        detour_seconds=max(0.0, best_detour_s),
        detour_meters=max(0.0, best_detour_m),
        baseline_seconds=baseline_s,
        with_insertion_seconds=best_with_s,
        provider_used=_dominant_provider(base_providers + best_providers),
    )


def score_from_detour(detour_seconds: float) -> float:
    """Map detour minutes → a 0..100 score (higher = better).

    Linear decay: 0 min → 100, 30 min → 0, clamped.  Cheap for the
    FE to sort/format; the endpoint is still authoritative on rank.
    """
    minutes = detour_seconds / 60.0
    if minutes <= 0:
        return 100.0
    if minutes >= 30:
        return 0.0
    return round(100.0 - (minutes / 30.0) * 100.0, 1)


__all__ = [
    "Stop", "InsertionResult",
    "best_insertion", "score_from_detour",
]
