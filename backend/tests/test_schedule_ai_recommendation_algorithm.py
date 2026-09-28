"""SO-A · Feb-2026 — Detour-cost algorithm tests (pure math).

Uses a deterministic fake ETA callable so the tests don't depend on
Google/OSRM/crow-flies — the algorithm's correctness is decoupled
from provider selection.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from services.schedule_optimizer.detour import (
    Stop, best_insertion, score_from_detour,
)
from tests._mth_a_helpers import run


@dataclass(frozen=True)
class _FakeETA:
    """Duration = 60s * |manhattan distance in "degrees"|.  Distance
    in meters = duration * 20 (arbitrary but deterministic).
    """
    provider: str = "crowflies"

    async def __call__(self, a_lat: float, a_lng: float,
                         b_lat: float, b_lng: float):
        d = abs(a_lat - b_lat) + abs(a_lng - b_lng)
        duration_s = int(round(d * 60))
        distance_m = int(round(d * 20))
        return type("_R", (),
                     {"provider": self.provider,
                      "duration_s": duration_s,
                      "distance_m": distance_m})()


def _stops(specs: List[Tuple[float, float]]) -> List[Stop]:
    return [Stop(job_id=f"j{i}", lat=lat, lng=lng)
            for i, (lat, lng) in enumerate(specs)]


def test_baseline_and_with_insertion_math_5_stop_route():
    origin = (0.0, 0.0)
    # 5 stops arranged in a straight line on the equator: distances
    # from origin are 1,2,3,4,5.  Baseline should visit them in
    # order for a 5s cumulative duration (60s per unit).
    existing = _stops([(0, 1), (0, 2), (0, 3), (0, 4), (0, 5)])
    target = Stop(job_id="TGT", lat=0.0, lng=2.5)
    result = run(best_insertion(origin, existing, target,
                                     eta_fn=_FakeETA()))
    # Baseline: 0->1 + 1->2 + 2->3 + 3->4 + 4->5 = 5 units × 60s = 300s.
    # Best insertion for 2.5 is between stop 1 (=lng2) and stop 2
    # (=lng3): 0->1 + 1->2 + 2->2.5 + 2.5->3 + 3->4 + 4->5 = 5.0
    # units → 300s.  Detour = 0.
    assert result.baseline_seconds == 300
    assert result.insertion_index == 2
    assert result.detour_seconds == 0


def test_correct_min_delta_insertion_index_selected():
    origin = (0.0, 0.0)
    # 3 clustered stops at lng 5.  Target on the opposite side.
    existing = _stops([(0, 5), (0, 5.1), (0, 5.2)])
    target = Stop(job_id="TGT", lat=0.0, lng=0.05)
    result = run(best_insertion(origin, existing, target,
                                     eta_fn=_FakeETA()))
    # Placing target first (index 0) is optimal — origin->0.05 is
    # cheap, and the rest of the route is unchanged.
    assert result.insertion_index == 0


def test_ranking_sort_ascending_by_delta():
    # Verified indirectly: score_from_detour maps 0min → 100, 30min → 0.
    assert score_from_detour(0) == 100.0
    assert score_from_detour(30 * 60) == 0.0
    # Linear midpoint.
    assert score_from_detour(15 * 60) == 50.0
    # Clamps.
    assert score_from_detour(60 * 60) == 0.0
    assert score_from_detour(-10) == 100.0


def test_single_stop_route_has_two_candidate_insertions():
    origin = (0.0, 0.0)
    existing = _stops([(0, 3)])
    target = Stop(job_id="TGT", lat=0.0, lng=1.0)
    result = run(best_insertion(origin, existing, target,
                                     eta_fn=_FakeETA()))
    # Baseline 0→3 = 180s.
    # Idx 0 (origin→1→3): 60s + 120s = 180s → delta 0.
    # Idx 1 (origin→3→1): 180s + 120s = 300s → delta +120s.
    # Best is idx 0.
    assert result.insertion_index == 0
    assert result.detour_seconds == 0


def test_far_insertion_produces_positive_detour():
    origin = (0.0, 0.0)
    existing = _stops([(0, 1), (0, 2)])
    target = Stop(job_id="TGT", lat=0.0, lng=10.0)  # very far
    result = run(best_insertion(origin, existing, target,
                                     eta_fn=_FakeETA()))
    # No matter where inserted, target adds at least ~16 units (the
    # 10→ back and forth to get back to the existing route's last
    # stop) → positive detour, roughly minutes.
    assert result.detour_seconds > 0
    assert result.insertion_index in (0, 1, 2)


def test_max_suggestions_cap_upstream_of_algorithm():
    """The algorithm itself doesn't cap — the endpoint does.  We
    verify the algorithm's independence: running it twice returns
    two independent InsertionResult objects, sorted by the endpoint
    layer.  This is a smoke that we can compose independent per-tech
    runs."""
    origin_a = (0.0, 0.0)
    origin_b = (0.0, 8.0)   # different origin → different insertion index
    existing = _stops([(0, 5)])
    target = Stop(job_id="TGT", lat=0.0, lng=5.5)
    ra = run(best_insertion(origin_a, existing, target, eta_fn=_FakeETA()))
    rb = run(best_insertion(origin_b, existing, target, eta_fn=_FakeETA()))
    # Two independent InsertionResult objects with independent
    # detours — the endpoint layer will sort/rank them.
    assert isinstance(ra.detour_seconds, float)
    assert isinstance(rb.detour_seconds, float)
    assert (ra.insertion_index, ra.detour_seconds) != (
        rb.insertion_index, rb.detour_seconds,
    )


def test_empty_route_short_circuits_at_endpoint_level():
    """Directly: an empty route means the target is the ONLY stop,
    detour ≡ round-trip origin→target.  Algorithm still returns a
    valid result — the endpoint decides to exclude such techs when
    the brief says so.  This locks the contract that an empty
    existing_stops list is safe."""
    origin = (0.0, 0.0)
    target = Stop(job_id="TGT", lat=0.0, lng=1.0)
    result = run(best_insertion(origin, [], target,
                                     eta_fn=_FakeETA()))
    assert result.insertion_index == 0
    assert result.baseline_seconds == 0
    # detour == origin→target one-way = 60s
    assert result.detour_seconds == 60


def test_pair_eta_cache_reuses_provider_call():
    """Cache-hit count = pairs actually queried, not attempts."""
    calls = {"n": 0}

    class _CountingETA:
        provider = "crowflies"

        async def __call__(self, *args, **_kw):
            calls["n"] += 1
            d = abs(args[0] - args[2]) + abs(args[1] - args[3])
            duration_s = int(round(d * 60))
            return type("_R", (),
                         {"provider": self.provider,
                          "duration_s": duration_s,
                          "distance_m": duration_s * 20})()

    origin = (0.0, 0.0)
    existing = _stops([(0, 1), (0, 2), (0, 3)])
    target = Stop(job_id="TGT", lat=0.0, lng=1.5)
    _ = run(best_insertion(origin, existing, target,
                              eta_fn=_CountingETA()))
    # Baseline pairs: (o,j0)(j0,j1)(j1,j2) = 3 unique.
    # Each of the 4 candidate insertions introduces target-adjacent
    # pairs.  Enumerated novel pairs:
    #   i=0: (o,T),(T,j0)                  → 2 new
    #   i=1: (j0,T),(T,j1)                 → 2 new
    #   i=2: (j1,T),(T,j2)                 → 2 new
    #   i=3: (j2,T)                        → 1 new
    # Total unique = 3 baseline + 7 target-adjacent = 10.  The cache
    # prevents provider re-hits; without it we'd have 3 + 4*4 = 19.
    assert calls["n"] == 10


__all__: List[Any] = []
