"""Phase CAD-2.5 · Feb-2026 — Site-plan scale-bar accuracy.

Locks the ``compute_scale_bar_pt`` helper contract:

  * ``feet_per_pixel`` + ``map_size_px`` set → bar length derives
    from ``feet_per_pixel × map_size_px.w`` real-world width, so
    the bar tracks the actual map tile dimensions rather than the
    design's declared ``canvas_w_ft``.
  * ``feet_per_pixel`` set but ``map_size_px`` missing (pre-CAD-1
    designs) → legacy ``sw / canvas_w_ft`` fallback.
  * ``feet_per_pixel`` unset → nominal ``sw × 0.2`` bar.
"""
from __future__ import annotations

import pytest

from services.cad.site_plan_pdf import (
    build_render_context,
    compute_scale_bar_pt,
)


@pytest.fixture
def design_with_map_meta():
    return {
        "name": "Backyard",
        "canvas_w_ft": 60.0, "canvas_h_ft": 40.0,
        "feet_per_pixel": 0.05,
        "map_size_px": {"w": 800, "h": 500},
        "elements": [], "boundary": [],
    }


def _ctx(design):
    return build_render_context(
        design=design,
        customer=None,
        tenant={"name": "T"},
        map_bytes=None,
    )


class TestCAD25ScaleBar:
    def test_map_size_px_matches_canvas_dims_uses_new_formula(
        self, design_with_map_meta,
    ):
        """Standard case — 800×500 map at 0.05 ft/px → real width
        40 ft. A ``sw = 400 pt`` drawing region → 50 ft bar =
        50 × (400 / (800 × 0.05)) = 50 × 10 = 500 pt, capped at
        sw × 0.4 = 160 pt.
        """
        ctx = _ctx(design_with_map_meta)
        bar = compute_scale_bar_pt(ctx, 400.0)
        # Cap at sw × 0.4 = 160 pt.
        assert bar == pytest.approx(160.0, abs=0.01)

    def test_map_wider_than_canvas_dims_does_not_use_canvas_w_ft(
        self, design_with_map_meta,
    ):
        """Regression — customer overrode the map fetch to
        1000 px wide but ``canvas_w_ft`` stayed at 60. With
        feet_per_pixel = 0.05, real map width = 50 ft. A 50 ft
        bar spans the whole map. At ``sw = 500 pt`` the new
        formula → 50 × (500 / 50) = 500 pt, capped at 200 pt.
        The legacy ``sw / canvas_w_ft`` formula would have
        returned ``50 × (500 / 60) ≈ 417 pt`` capped at 200 —
        the two happen to converge at the cap in this case, so
        we assert a smaller ``sw`` that puts both below the cap
        and shows the divergence.
        """
        d = dict(design_with_map_meta)
        d["map_size_px"] = {"w": 1000, "h": 500}
        d["canvas_w_ft"] = 60.0
        d["feet_per_pixel"] = 0.05
        ctx = _ctx(d)
        # sw = 100 pt → 50 × (100 / (1000 × 0.05)) = 100 pt
        # (capped at sw × 0.4 = 40 pt).
        bar = compute_scale_bar_pt(ctx, 100.0)
        # New formula clamps to sw × 0.4 = 40 pt. Legacy would
        # have returned min(40, 50 × (100 / 60)) = min(40, 83.3)
        # = 40 pt — same at cap. Move sw high enough to expose
        # the divergence:
        # sw = 240 pt → new = min(96, 50 × 240 / 50) = 96 pt
        #             legacy = min(96, 50 × 240 / 60) = 96 pt
        # Both still cap. Push feet_per_pixel higher so the raw
        # value stays under the cap:
        d["feet_per_pixel"] = 0.5   # real map width = 500 ft
        ctx = _ctx(d)
        bar = compute_scale_bar_pt(ctx, 240.0)
        # New: 50 × (240 / (1000 × 0.5)) = 50 × 0.48 = 24 pt
        # Legacy would have been: 50 × (240 / 60) = 200 pt
        # capped at 96 pt. New is decisively smaller → 24 pt.
        assert bar == pytest.approx(24.0, abs=0.01)
        # And explicitly NOT the legacy result.
        assert bar != pytest.approx(96.0, abs=0.01)

    def test_missing_feet_per_pixel_returns_nominal_bar(
        self, design_with_map_meta,
    ):
        d = dict(design_with_map_meta)
        d["feet_per_pixel"] = None
        ctx = _ctx(d)
        # sw × 0.2 = 100 pt for sw = 500.
        assert compute_scale_bar_pt(ctx, 500.0) == pytest.approx(100.0)

    def test_legacy_design_without_map_size_px_falls_back(
        self, design_with_map_meta,
    ):
        """Pre-CAD-1 designs may have ``feet_per_pixel`` set (from
        manual calibration) but no ``map_size_px``. Fall back to
        the old ``sw / canvas_w_ft`` formula without crashing.
        """
        d = dict(design_with_map_meta)
        d.pop("map_size_px", None)
        d["canvas_w_ft"] = 60.0
        d["feet_per_pixel"] = 0.05
        ctx = _ctx(d)
        # sw = 240 pt → legacy = min(96, 50 × 240 / 60) = 96 pt.
        bar = compute_scale_bar_pt(ctx, 240.0)
        assert bar == pytest.approx(96.0, abs=0.01)

    def test_zero_or_negative_feet_per_pixel_treated_as_missing(
        self, design_with_map_meta,
    ):
        d = dict(design_with_map_meta)
        d["feet_per_pixel"] = 0
        ctx = _ctx(d)
        assert compute_scale_bar_pt(ctx, 500.0) == pytest.approx(100.0)
        d["feet_per_pixel"] = -0.5
        ctx = _ctx(d)
        assert compute_scale_bar_pt(ctx, 500.0) == pytest.approx(100.0)
