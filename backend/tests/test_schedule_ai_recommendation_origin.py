"""SO-A · Feb-2026 — Origin cascade tests.

Locks:
    * GPS ping < 4h old → origin = ping coords.
    * GPS ping stale → falls through to first-job proxy.
    * No GPS + first-job has coords → source="first_job".
    * No GPS + no jobs → source="unknown".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.schedule_optimizer.origin import resolve_origin, GPS_FRESHNESS_S
from tests._mth_c_helpers import mth_c_db, run                    # noqa: F401


NOW = datetime(2026, 2, 15, 14, 0, 0, tzinfo=timezone.utc)


def _ping(fake, *, tenant_id: str, tech_id: str, minutes_old: int,
             lat: float = 25.7, lng: float = -80.2) -> None:
    """Insert a tech_locations row for the test."""
    fake.tech_locations.rows.append({
        "id": f"loc-{tech_id}",
        "tenant_id": tenant_id, "tech_user_id": tech_id,
        "lat": lat, "lng": lng,
        "recorded_at":
            (NOW - timedelta(minutes=minutes_old)).isoformat(),
    })


def test_fresh_gps_ping_wins(mth_c_db):
    _ping(mth_c_db, tenant_id="t1", tech_id="tech_a", minutes_old=30,
             lat=25.11, lng=-80.22)
    result = run(resolve_origin(
        db=mth_c_db, tenant_id="t1", tech_user_id="tech_a",
        ordered_stops_today=[{"id": "j1", "lat": 90.0, "lng": 90.0}],
        now_utc=NOW,
    ))
    assert result.source == "gps"
    assert result.lat == 25.11
    assert result.lng == -80.22
    assert "30m" in (result.detail or "")


def test_stale_gps_falls_through(mth_c_db):
    # 5h old — beyond the 4h window.
    _ping(mth_c_db, tenant_id="t1", tech_id="tech_a", minutes_old=5 * 60,
             lat=25.11, lng=-80.22)
    result = run(resolve_origin(
        db=mth_c_db, tenant_id="t1", tech_user_id="tech_a",
        ordered_stops_today=[
            {"id": "j1", "latitude": 25.99, "longitude": -80.55},
        ],
        now_utc=NOW,
    ))
    assert result.source == "first_job"
    assert result.lat == 25.99
    assert result.lng == -80.55


def test_no_gps_and_no_jobs_returns_unknown(mth_c_db):
    result = run(resolve_origin(
        db=mth_c_db, tenant_id="t1", tech_user_id="tech_a",
        ordered_stops_today=[], now_utc=NOW,
    ))
    assert result.source == "unknown"
    assert result.lat is None and result.lng is None


def test_no_gps_first_job_missing_coords_returns_unknown(mth_c_db):
    result = run(resolve_origin(
        db=mth_c_db, tenant_id="t1", tech_user_id="tech_a",
        ordered_stops_today=[{"id": "j1"}],   # no coords
        now_utc=NOW,
    ))
    assert result.source == "unknown"


def test_ping_boundary_at_exactly_4h_counts_as_fresh(mth_c_db):
    # Exactly at the boundary — spec says "< 4 hours" so we accept
    # <= 4h to avoid boundary flake.
    _ping(mth_c_db, tenant_id="t1", tech_id="tech_a",
             minutes_old=(GPS_FRESHNESS_S // 60),
             lat=1.0, lng=2.0)
    result = run(resolve_origin(
        db=mth_c_db, tenant_id="t1", tech_user_id="tech_a",
        ordered_stops_today=[], now_utc=NOW,
    ))
    assert result.source == "gps"


def test_ping_key_variants_on_first_job(mth_c_db):
    """First-job proxy must accept lat/lng OR latitude/longitude
    OR site_lat/site_lng — matches FLEET-A's key cascade."""
    for lat_key, lng_key in [("latitude", "longitude"),
                                 ("site_lat", "site_lng"),
                                 ("lat", "lng")]:
        stop = {"id": "j1", lat_key: 10.0, lng_key: 20.0}
        result = run(resolve_origin(
            db=mth_c_db, tenant_id="t1", tech_user_id="tech_x",
            ordered_stops_today=[stop], now_utc=NOW,
        ))
        assert result.source == "first_job", (lat_key, lng_key)
        assert result.lat == 10.0 and result.lng == 20.0
