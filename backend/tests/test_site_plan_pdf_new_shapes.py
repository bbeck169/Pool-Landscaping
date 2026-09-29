"""Phase CAD-3.5b · Feb-2026 — Site-plan PDF handling for
straight-line, smooth-curve, and paver-material elements.

Verifies:
  1. ``_draw_element`` renders a ``line`` shape without error and
     invokes the ReportLab low-level ``line`` primitive.
  2. ``_draw_element`` renders a ``curve`` shape via
     ``beginPath``/``curveTo`` (Catmull-Rom → Bezier approximation
     of the FE ``tension=0.5`` line).
  3. ``_draw_element`` renders a paver with a ``material_id`` using
     the material's representative color from
     :data:`PAVER_MATERIAL_PALETTE` (documented fallback: ReportLab
     lacks arbitrary-polygon pattern fill).
  4. ``_summarise_elements`` counts ``line`` / ``curve`` totals and
     surfaces a ``paver_materials`` breakdown row.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from reportlab.lib.colors import HexColor

from services.cad.site_plan_pdf import (
    PAVER_MATERIAL_PALETTE,
    _draw_element,
    _summarise_elements,
)


def _mock_canvas() -> MagicMock:
    """A ReportLab-shaped stub whose call log captures every draw
    primitive so tests can assert primitive counts without parsing
    the emitted PDF binary."""
    c = MagicMock()
    c.beginPath.return_value = MagicMock()
    return c


def _region():
    # A 100pt-wide × 60pt-tall drawing region at origin (10, 10).
    return dict(ox=10.0, oy=10.0, sw=100.0, sh=60.0)


def test_line_element_renders_without_error_and_invokes_c_line():
    c = _mock_canvas()
    _draw_element(c, {
        "id": "l-1", "type": "line",
        "coords": [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.9}],
        "props": {},
    }, **_region())
    # ReportLab's line primitive fired exactly once.
    assert c.line.call_count == 1
    # Endpoints picked up from the normalized coords.
    args = c.line.call_args.args
    # x = ox + p.x * sw   → 10 + 0.1*100 = 20    → 10 + 0.9*100 = 100
    # y = oy + (1 - p.y) * sh → 10 + (1-0.1)*60 = 64   → 10 + (1-0.9)*60 = 16
    assert args == pytest.approx((20.0, 64.0, 100.0, 16.0))


def test_curve_element_renders_via_beginPath_curveTo():
    c = _mock_canvas()
    _draw_element(c, {
        "id": "cv-1", "type": "curve",
        "coords": [{"x": 0.1, "y": 0.2}, {"x": 0.4, "y": 0.6},
                   {"x": 0.7, "y": 0.3}, {"x": 0.9, "y": 0.7}],
        "props": {"tension": 0.5},
    }, **_region())
    # beginPath fires once → moveTo once → 3 curveTo hops
    # (one Catmull-Rom → Bezier segment per adjacent-vertex pair).
    assert c.beginPath.call_count == 1
    path = c.beginPath.return_value
    assert path.moveTo.call_count == 1
    assert path.curveTo.call_count == 3
    # ``drawPath`` stroked (not filled) — curves are outlines.
    c.drawPath.assert_called_once()
    _, kwargs = c.drawPath.call_args
    assert kwargs.get("stroke", 0) == 1
    assert kwargs.get("fill", 0) == 0


def test_curve_two_points_falls_back_to_straight_line():
    c = _mock_canvas()
    _draw_element(c, {
        "id": "cv-2", "type": "curve",
        "coords": [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.9}],
        "props": {"tension": 0.5},
    }, **_region())
    # Degenerate 2-point curve renders as a plain line.
    assert c.line.call_count == 1
    assert c.beginPath.call_count == 0


@pytest.mark.parametrize(
    "material_id,expected_hex",
    [
        ("travertine",         "#D9C7A9"),
        ("flagstone",          "#7C7A75"),
        ("brick_running_bond", "#8B4A3B"),
        ("slate",              "#3F434B"),
    ],
)
def test_paver_material_maps_to_representative_hex_fill(
    material_id, expected_hex,
):
    c = _mock_canvas()
    _draw_element(c, {
        "id": "pv-1", "type": "paver",
        "coords": [
            {"x": 0.2, "y": 0.2}, {"x": 0.6, "y": 0.2},
            {"x": 0.6, "y": 0.6}, {"x": 0.2, "y": 0.6},
        ],
        "props": {"material_id": material_id},
        "computed": {"area_sqft": 320},
    }, **_region())
    # Fill was set to the material's representative color BEFORE
    # the polygon was drawn.
    fill_calls = c.setFillColor.call_args_list
    assert fill_calls, "setFillColor was never invoked"
    last_before_path = fill_calls[-1].args[0]
    assert last_before_path == HexColor(expected_hex)


def test_paver_missing_material_falls_back_to_default_travertine():
    c = _mock_canvas()
    _draw_element(c, {
        "id": "pv-2", "type": "paver",
        "coords": [
            {"x": 0.1, "y": 0.1}, {"x": 0.4, "y": 0.1},
            {"x": 0.4, "y": 0.4}, {"x": 0.1, "y": 0.4},
        ],
        "props": {},  # No material_id
    }, **_region())
    fill_calls = c.setFillColor.call_args_list
    assert fill_calls[-1].args[0] == HexColor(
        PAVER_MATERIAL_PALETTE["travertine"]["color"],
    )


def test_summarise_elements_counts_line_and_curve_and_paver_materials():
    rows = _summarise_elements(
        [
            {"id": "l1", "type": "line",
             "coords": [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}],
             "computed": {"linear_ft": 12.0}},
            {"id": "l2", "type": "line",
             "coords": [{"x": 0.1, "y": 0.2}, {"x": 0.9, "y": 0.2}],
             "computed": {"linear_ft": 8.0}},
            {"id": "c1", "type": "curve",
             "coords": [{"x": 0.1, "y": 0.5}, {"x": 0.5, "y": 0.6},
                        {"x": 0.9, "y": 0.5}],
             "computed": {"linear_ft": 15.0}},
            {"id": "p1", "type": "paver",
             "coords": [{"x": 0.1, "y": 0.7}, {"x": 0.4, "y": 0.7},
                        {"x": 0.4, "y": 0.9}, {"x": 0.1, "y": 0.9}],
             "props": {"material_id": "slate"},
             "computed": {"area_sqft": 100}},
            {"id": "p2", "type": "paver",
             "coords": [{"x": 0.6, "y": 0.7}, {"x": 0.9, "y": 0.7},
                        {"x": 0.9, "y": 0.9}, {"x": 0.6, "y": 0.9}],
             "props": {"material_id": "flagstone"},
             "computed": {"area_sqft": 90}},
            {"id": "p3", "type": "paver",
             "coords": [{"x": 0.5, "y": 0.4}, {"x": 0.8, "y": 0.4},
                        {"x": 0.8, "y": 0.6}, {"x": 0.5, "y": 0.6}],
             "props": {"material_id": "slate"},
             "computed": {"area_sqft": 60}},
        ],
        canvas_w_ft=60.0, canvas_h_ft=40.0,
    )
    by_type = {r["type"]: r for r in rows}
    assert by_type["line"]["count"] == 2
    assert by_type["line"]["total_linear_ft"] == 20.0
    assert by_type["curve"]["count"] == 1
    assert by_type["curve"]["total_linear_ft"] == 15.0
    assert by_type["paver"]["count"] == 3
    assert by_type["paver"]["paver_materials"] == {
        "slate": 2, "flagstone": 1,
    }


def test_paver_material_palette_matches_frontend_catalog_ids():
    # Guard: the FE ships four material IDs; the BE palette must
    # cover every one so no PDF export ever renders a paver in the
    # generic fallback color.
    assert set(PAVER_MATERIAL_PALETTE.keys()) == {
        "travertine", "flagstone", "brick_running_bond", "slate",
    }
    for mid, cfg in PAVER_MATERIAL_PALETTE.items():
        assert cfg["color"].startswith("#") and len(cfg["color"]) == 7
        assert cfg["label"], f"material {mid} missing legend label"
