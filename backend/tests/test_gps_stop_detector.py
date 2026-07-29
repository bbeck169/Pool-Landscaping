"""G2 · Feb-2026 — Unit tests for the pure stop-detection algorithm.

No Mongo, no HTTP. The algorithm lives in
``services/gps_stop_detector.py`` and is a pure function; these tests
feed synthetic ping fixtures and assert the emitted stops.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.gps_stop_detector import (
    Stop, StopParams, detect_stops_for_user, _haversine_m,
)


def _pings(anchor_lat: float, anchor_lon: float,
             *, count: int, spacing_s: int,
             start: datetime, lat_step: float = 0.0,
             lon_step: float = 0.0):
    """Build synthetic pings walking away from an anchor."""
    return [
        {
            "id": f"p{i}",
            "lat": anchor_lat + lat_step * i,
            "lon": anchor_lon + lon_step * i,
            "captured_at": (start + timedelta(seconds=spacing_s * i))
                             .isoformat().replace("+00:00", "Z"),
            "tenant_id": "T", "user_id": "U",
        }
        for i in range(count)
    ]


def _standard_params():
    return StopParams(stop_radius_m=75.0,
                      stop_min_duration_s=300,
                      stop_gap_close_s=120)


# ─── 1) Single ping — no stop ───────────────────────────────────────
def test_single_ping_yields_no_stop():
    p = _pings(33.7, -112.2, count=1, spacing_s=60,
                start=datetime(2026, 2, 14, 9, 0, tzinfo=timezone.utc))
    assert detect_stops_for_user(p, _standard_params()) == []


def test_below_min_duration_yields_no_stop():
    # 4 pings, 60 s apart → 3 min total, below 5 min threshold.
    p = _pings(33.7, -112.2, count=4, spacing_s=60,
                start=datetime(2026, 2, 14, 9, 0, tzinfo=timezone.utc))
    assert detect_stops_for_user(p, _standard_params()) == []


# ─── 2) Cluster of pings → emits a stop with correct centroid + dur ─
def test_clustered_pings_emit_stop_with_centroid():
    start = datetime(2026, 2, 14, 9, 0, tzinfo=timezone.utc)
    # 7 pings, 60 s apart → 6 min duration, all within a metre of anchor.
    p = _pings(33.7, -112.2, count=7, spacing_s=60,
                start=start,
                lat_step=1e-6, lon_step=1e-6)  # near-zero drift
    stops = detect_stops_for_user(p, _standard_params(),
                                     tenant_id="T", user_id="U")
    assert len(stops) == 1
    s = stops[0]
    assert isinstance(s, Stop)
    assert s.tenant_id == "T" and s.user_id == "U"
    assert s.duration_s == 360
    assert s.ping_count == 7
    assert s.center_lat == round(sum(pp["lat"] for pp in p) / 7, 6)
    assert s.center_lon == round(sum(pp["lon"] for pp in p) / 7, 6)
    assert s.radius_m < 10  # trivial drift
    assert s.started_at == p[0]["captured_at"]
    assert s.ended_at == p[-1]["captured_at"]
    assert s.source == "algo"
    assert s.ping_ids == [f"p{i}" for i in range(7)]


# ─── 3) Walking beyond radius closes the stop ───────────────────────
def test_walk_beyond_radius_closes_stop():
    start = datetime(2026, 2, 14, 9, 0, tzinfo=timezone.utc)
    # First 6 pings clustered → 5 min at anchor.
    cluster = _pings(33.7, -112.2, count=6, spacing_s=60, start=start)
    # Then a ping 500 m away → should close the previous cluster.
    walker = [{
        "id": "p6", "lat": 33.705, "lon": -112.2,
        "captured_at": (start + timedelta(minutes=6))
                         .isoformat().replace("+00:00", "Z"),
        "tenant_id": "T", "user_id": "U",
    }]
    # Followed by a fresh cluster 5 min at the new site.
    late_start = start + timedelta(minutes=7)
    fresh = _pings(33.705, -112.2, count=6, spacing_s=60, start=late_start)
    all_pings = cluster + walker + fresh
    stops = detect_stops_for_user(all_pings, _standard_params())
    assert len(stops) == 2
    # First stop should have ended at cluster's last ping.
    assert stops[0].ping_count == 6
    assert stops[0].ping_ids[-1] == "p5"
    # Second stop starts at the walker+fresh.
    assert stops[1].ping_ids[0] == "p6"


# ─── 4) Gap in pings > gap_close closes the stop ────────────────────
def test_time_gap_closes_stop():
    start = datetime(2026, 2, 14, 9, 0, tzinfo=timezone.utc)
    # First cluster: 6 pings 60 s apart at anchor (5 min duration).
    first = _pings(33.7, -112.2, count=6, spacing_s=60, start=start)
    # Then a big gap (> 120 s) followed by more pings at the SAME spot.
    late = _pings(33.7, -112.2, count=6, spacing_s=60,
                    start=start + timedelta(minutes=30))
    all_pings = first + late
    stops = detect_stops_for_user(all_pings, _standard_params())
    assert len(stops) == 2
    assert stops[0].ended_at == first[-1]["captured_at"]
    assert stops[1].started_at == late[0]["captured_at"]


# ─── 5) Idempotency ─────────────────────────────────────────────────
def test_algorithm_is_idempotent():
    start = datetime(2026, 2, 14, 9, 0, tzinfo=timezone.utc)
    p = _pings(33.7, -112.2, count=7, spacing_s=60, start=start)
    p += _pings(33.72, -112.22, count=10, spacing_s=90,
                 start=start + timedelta(minutes=30))
    run1 = detect_stops_for_user(p, _standard_params())
    run2 = detect_stops_for_user(p, _standard_params())
    assert run1 == run2


# ─── 6) Distance helper sanity ──────────────────────────────────────
def test_haversine_helper_returns_realistic_distance():
    # Golden Gate → Empire State ≈ 4 128 km.
    d = _haversine_m(37.8199, -122.4783, 40.7484, -73.9857)
    assert 4_100_000 < d < 4_200_000


# ─── 7) StopParams validates its inputs ─────────────────────────────
def test_stop_params_rejects_bad_values():
    import pytest
    with pytest.raises(ValueError):
        StopParams(stop_radius_m=0)
    with pytest.raises(ValueError):
        StopParams(stop_min_duration_s=0)
    with pytest.raises(ValueError):
        StopParams(stop_gap_close_s=0)


# ─── 8) Out-of-order pings are sorted before processing ────────────
def test_out_of_order_pings_are_sorted():
    start = datetime(2026, 2, 14, 9, 0, tzinfo=timezone.utc)
    p = _pings(33.7, -112.2, count=7, spacing_s=60, start=start)
    # Shuffle
    p = [p[3], p[0], p[6], p[1], p[5], p[2], p[4]]
    stops = detect_stops_for_user(p, _standard_params())
    assert len(stops) == 1
    assert stops[0].duration_s == 360
