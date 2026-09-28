"""Phase CAD-2 · Feb-2026 — shape geometry helpers.

Covers ``services.geometry``:

  * ``polygon_area_pixels`` — legacy pixel-space shoelace (unchanged).
  * ``polygon_area_normalized_to_sqft`` — normalized 0..1 coords →
    canvas-scaled sqft.
  * ``polyline_length_normalized_to_ft`` — polyline length in feet.
  * ``clamp_normalized_coords`` — coord clamp with a ``clamped`` flag.
  * ``polygon_self_intersects`` — best-effort intersection detector.
"""
from __future__ import annotations

import pytest

from services.geometry import (
    clamp_normalized_coords,
    polygon_area_normalized_to_sqft,
    polygon_area_pixels,
    polygon_self_intersects,
    polyline_length_normalized_to_ft,
)


# ─── polygon_area_pixels (legacy, extracted) ────────────────────────
class TestPolygonAreaPixelsLegacy:
    def test_square_10_by_10_is_100(self):
        assert polygon_area_pixels([[0, 0], [10, 0], [10, 10], [0, 10]]) == 100.0

    def test_winding_order_irrelevant(self):
        cw = [[0, 0], [10, 0], [10, 10], [0, 10]]
        ccw = list(reversed(cw))
        assert polygon_area_pixels(cw) == polygon_area_pixels(ccw)

    def test_empty_and_degenerate_return_zero(self):
        assert polygon_area_pixels([]) == 0.0
        assert polygon_area_pixels([[0, 0]]) == 0.0
        assert polygon_area_pixels([[0, 0], [1, 1]]) == 0.0

    def test_triangle_shoelace(self):
        # Right-triangle base=6, height=8 → area 24.
        assert polygon_area_pixels([[0, 0], [6, 0], [0, 8]]) == 24.0


# ─── polygon_area_normalized_to_sqft ────────────────────────────────
class TestPolygonAreaNormalizedToSqft:
    def test_full_canvas_rectangle_equals_canvas_sqft(self):
        # Full-canvas rect over 60×40 ft canvas → 2400 sqft.
        coords = [{"x": 0, "y": 0}, {"x": 1, "y": 0},
                  {"x": 1, "y": 1}, {"x": 0, "y": 1}]
        sqft = polygon_area_normalized_to_sqft(
            coords, canvas_w_ft=60, canvas_h_ft=40,
        )
        assert sqft == pytest.approx(2400.0)

    def test_half_canvas_rectangle_equals_half_sqft(self):
        coords = [{"x": 0, "y": 0}, {"x": 0.5, "y": 0},
                  {"x": 0.5, "y": 1}, {"x": 0, "y": 1}]
        sqft = polygon_area_normalized_to_sqft(
            coords, canvas_w_ft=60, canvas_h_ft=40,
        )
        assert sqft == pytest.approx(1200.0)

    def test_accepts_list_and_dict_coord_shapes(self):
        list_form = [[0, 0], [1, 0], [1, 1], [0, 1]]
        dict_form = [{"x": 0, "y": 0}, {"x": 1, "y": 0},
                      {"x": 1, "y": 1}, {"x": 0, "y": 1}]
        a = polygon_area_normalized_to_sqft(
            list_form, canvas_w_ft=100, canvas_h_ft=50,
        )
        b = polygon_area_normalized_to_sqft(
            dict_form, canvas_w_ft=100, canvas_h_ft=50,
        )
        assert a == b == pytest.approx(5000.0)

    def test_degenerate_polygon_returns_zero(self):
        assert polygon_area_normalized_to_sqft(
            [{"x": 0, "y": 0}, {"x": 1, "y": 1}],
            canvas_w_ft=60, canvas_h_ft=40,
        ) == 0.0


# ─── polyline_length_normalized_to_ft ───────────────────────────────
class TestPolylineLength:
    def test_horizontal_full_canvas_is_canvas_width(self):
        coords = [{"x": 0, "y": 0.5}, {"x": 1, "y": 0.5}]
        assert polyline_length_normalized_to_ft(
            coords, canvas_w_ft=100, canvas_h_ft=50,
        ) == pytest.approx(100.0)

    def test_diagonal_pythagorean(self):
        coords = [{"x": 0, "y": 0}, {"x": 1, "y": 1}]
        # sqrt(60^2 + 40^2) = sqrt(3600 + 1600) = sqrt(5200) ≈ 72.111
        got = polyline_length_normalized_to_ft(
            coords, canvas_w_ft=60, canvas_h_ft=40,
        )
        assert got == pytest.approx(72.111, abs=0.01)

    def test_multi_segment_sums(self):
        # Three segments along the top edge, then down, then left.
        coords = [{"x": 0, "y": 0}, {"x": 0.5, "y": 0},
                  {"x": 1, "y": 0}, {"x": 1, "y": 1},
                  {"x": 0, "y": 1}]
        # 30 + 30 (top halves) + 40 (right) + 60 (bottom) = 160.
        got = polyline_length_normalized_to_ft(
            coords, canvas_w_ft=60, canvas_h_ft=40,
        )
        assert got == pytest.approx(160.0)

    def test_single_point_returns_zero(self):
        assert polyline_length_normalized_to_ft(
            [{"x": 0.5, "y": 0.5}], canvas_w_ft=60, canvas_h_ft=40,
        ) == 0.0


# ─── clamp_normalized_coords ────────────────────────────────────────
class TestClampNormalizedCoords:
    def test_all_in_range_is_noop(self):
        coords = [{"x": 0.1, "y": 0.2}, {"x": 0.5, "y": 0.9}]
        out, clamped = clamp_normalized_coords(coords)
        assert clamped is False
        assert out == [{"x": 0.1, "y": 0.2}, {"x": 0.5, "y": 0.9}]

    def test_negative_and_over_one_are_clamped(self):
        coords = [{"x": -0.2, "y": 0.5}, {"x": 1.4, "y": 2.0}]
        out, clamped = clamp_normalized_coords(coords)
        assert clamped is True
        assert out[0] == {"x": 0.0, "y": 0.5}
        assert out[1] == {"x": 1.0, "y": 1.0}

    def test_accepts_list_shape(self):
        out, clamped = clamp_normalized_coords([[1.5, -0.1]])
        assert clamped is True
        assert out == [{"x": 1.0, "y": 0.0}]


# ─── polygon_self_intersects ────────────────────────────────────────
class TestSelfIntersects:
    def test_convex_quad_does_not_intersect(self):
        assert polygon_self_intersects(
            [{"x": 0, "y": 0}, {"x": 1, "y": 0},
             {"x": 1, "y": 1}, {"x": 0, "y": 1}],
        ) is False

    def test_bowtie_intersects(self):
        # Bowtie: (0,0) → (1,1) → (1,0) → (0,1) — crossing diagonals.
        assert polygon_self_intersects(
            [{"x": 0, "y": 0}, {"x": 1, "y": 1},
             {"x": 1, "y": 0}, {"x": 0, "y": 1}],
        ) is True

    def test_area_still_returns_a_value_on_bowtie(self):
        # Shoelace on a bowtie gives the sum of the two triangle
        # areas' signed difference — still a finite non-negative
        # number. Contract: callers get a value AND can flag it.
        sqft = polygon_area_normalized_to_sqft(
            [{"x": 0, "y": 0}, {"x": 1, "y": 1},
             {"x": 1, "y": 0}, {"x": 0, "y": 1}],
            canvas_w_ft=10, canvas_h_ft=10,
        )
        assert sqft >= 0.0

    def test_triangle_never_intersects(self):
        assert polygon_self_intersects(
            [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 0.5, "y": 1}],
        ) is False
