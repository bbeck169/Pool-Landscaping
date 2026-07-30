"""Phase G5a · Feb-2026 — Unit tests for services.geofence_engine.

Pure-function tests — no DB, no network. Runs standalone via
``pytest tests/test_geofence_engine.py``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from services.geofence_engine import (  # noqa: E402
    bbox_hit, compute_bbox, haversine_m, point_in_circle,
    point_in_fence, point_in_polygon,
)


# ── Haversine ───────────────────────────────────────────────────────

class TestHaversine:
    def test_zero_distance(self):
        assert haversine_m(33.5, -112.0, 33.5, -112.0) == pytest.approx(0.0, abs=0.01)

    def test_one_degree_lat_is_about_111km(self):
        d = haversine_m(33.0, -112.0, 34.0, -112.0)
        assert 110_000 < d < 112_000

    def test_symmetric(self):
        a = haversine_m(33.5, -112.0, 34.0, -111.5)
        b = haversine_m(34.0, -111.5, 33.5, -112.0)
        assert a == pytest.approx(b, abs=0.01)


# ── point_in_circle ─────────────────────────────────────────────────

class TestPointInCircle:
    def test_center_is_inside(self):
        assert point_in_circle(33.5, -112.0, 33.5, -112.0, 100)

    def test_edge_case_at_radius(self):
        # ~1m north of center; 200m radius → inside.
        assert point_in_circle(33.500009, -112.0, 33.5, -112.0, 200)

    def test_outside(self):
        # 10km away, 200m radius → outside.
        assert not point_in_circle(33.6, -112.1, 33.5, -112.0, 200)


# ── point_in_polygon ────────────────────────────────────────────────

class TestPointInPolygon:
    SQUARE = [
        {"lat": 33.5, "lon": -112.0},
        {"lat": 33.5, "lon": -111.9},
        {"lat": 33.6, "lon": -111.9},
        {"lat": 33.6, "lon": -112.0},
    ]

    def test_center_inside(self):
        assert point_in_polygon(33.55, -111.95, self.SQUARE)

    def test_far_outside(self):
        assert not point_in_polygon(30.0, -110.0, self.SQUARE)

    def test_below(self):
        assert not point_in_polygon(33.4, -111.95, self.SQUARE)

    def test_needs_at_least_3_points(self):
        assert not point_in_polygon(33.5, -112.0, [])
        assert not point_in_polygon(33.5, -112.0, [{"lat":33.5,"lon":-112.0}])


# ── compute_bbox + bbox_hit ─────────────────────────────────────────

class TestBBox:
    def test_circle_bbox_covers_center(self):
        f = {"shape": "circle", "center_lat": 33.5,
             "center_lon": -112.0, "radius_m": 500}
        b = compute_bbox(f)
        assert b["min_lat"] < 33.5 < b["max_lat"]
        assert b["min_lon"] < -112.0 < b["max_lon"]
        assert bbox_hit(33.5, -112.0, b)

    def test_polygon_bbox_wraps_all_points(self):
        f = {"shape": "polygon", "points": [
            {"lat": 33.5, "lon": -112.0},
            {"lat": 33.6, "lon": -111.9},
            {"lat": 33.4, "lon": -111.8},
        ]}
        b = compute_bbox(f)
        assert b["min_lat"] == 33.4 and b["max_lat"] == 33.6
        assert b["min_lon"] == -112.0 and b["max_lon"] == -111.8

    def test_bbox_hit_rejects_outsiders(self):
        b = {"min_lat": 0, "max_lat": 1, "min_lon": 0, "max_lon": 1}
        assert not bbox_hit(2, 0.5, b)
        assert not bbox_hit(0.5, 2, b)


# ── point_in_fence integration ──────────────────────────────────────

class TestPointInFence:
    def test_circle_inside(self):
        f = {"shape": "circle", "center_lat": 33.5,
             "center_lon": -112.0, "radius_m": 200}
        assert point_in_fence(33.5, -112.0, f)

    def test_circle_outside_bbox_short_circuits(self):
        f = {"shape": "circle", "center_lat": 33.5,
             "center_lon": -112.0, "radius_m": 200}
        # Somewhere very far away — bbox fast-reject.
        assert not point_in_fence(50.0, 0.0, f)

    def test_polygon_inside(self):
        f = {"shape": "polygon", "points": [
            {"lat": 33.5, "lon": -112.0},
            {"lat": 33.5, "lon": -111.9},
            {"lat": 33.6, "lon": -111.9},
            {"lat": 33.6, "lon": -112.0},
        ]}
        assert point_in_fence(33.55, -111.95, f)

    def test_uses_precomputed_bbox_if_present(self):
        f = {"shape": "circle", "center_lat": 33.5,
             "center_lon": -112.0, "radius_m": 200,
             "bbox": compute_bbox({"shape":"circle","center_lat":33.5,
                                    "center_lon":-112.0,"radius_m":200})}
        assert point_in_fence(33.5, -112.0, f)

    def test_unknown_shape_is_false(self):
        assert not point_in_fence(33.5, -112.0, {"shape": "nope"})
