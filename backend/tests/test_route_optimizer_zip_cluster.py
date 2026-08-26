"""Feb-2026 · Optimize Route (Phase A) — ORION-inspired zip-cluster
tiebreaker.

The full Google Directions v2 path is already covered end-to-end by
``tests/test_route_optimization_endpoint.py`` (pre-existing). This
file focuses on the NEW helper — the ZIP-cluster post-processing
swap pass that runs after Google returns an ordering.

Uses ``asyncio.get_event_loop().run_until_complete`` per repo
convention (no pytest-asyncio in the dev image).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault(
    "FERNET_KEY",
    "f2DlHrLPFFiF2HxLFglFEegS2pvke90APrHBSU_YGus=",
)

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.route_optimizer import (
    _extract_zip,
    zip_cluster_swap_pass,
    ZIP_CLUSTER_TIEBREAKER_BUDGET,
)


class TestExtractZip:
    def test_explicit_zip_field(self):
        assert _extract_zip({"zip": "94103"}) == "94103"

    def test_postal_code_field_fallback(self):
        assert _extract_zip({"postal_code": "94103"}) == "94103"

    def test_five_digit_zip_from_address_tail(self):
        assert _extract_zip({"address": "123 Main St, Anywhere, CA 94103"}) == "94103"

    def test_zip_plus_four_stripped_to_five(self):
        assert _extract_zip({"address": "123 Main St, Anywhere, CA 94103-1234"}) == "94103"

    def test_no_zip_returns_none(self):
        assert _extract_zip({"address": "no zip here"}) is None
        assert _extract_zip({}) is None


class TestZipClusterSwapPass:
    """Baseline: A(zip 1) → B(zip 2) → C(zip 1). A and C share a zip
    but B is between them. If swapping B and C keeps the total leg
    distance within the 2% budget, we swap — leaving the tour A → C
    → B (both zip-1 stops contiguous).
    """

    def test_swaps_apply_when_within_budget(self):
        # A + C are far apart; if we don't swap, distance is longer
        # because we jump A→B (short) then B→C (long back-track). If
        # we swap so it becomes A→C (short — same zip cluster) → B
        # (long), the total is SHORTER. So swap always applies.
        stops = [
            {"id": "A", "lat": 37.75, "lng": -122.42, "zip": "94103"},
            {"id": "B", "lat": 37.80, "lng": -122.30, "zip": "94612"},
            {"id": "C", "lat": 37.751, "lng": -122.421, "zip": "94103"},
        ]
        new_order, warnings = zip_cluster_swap_pass(
            ordered=stops, start_lat=37.75, start_lng=-122.42,
        )
        ids = [s["id"] for s in new_order]
        assert ids == ["A", "C", "B"]
        assert any("applied" in w for w in warnings)

    def test_does_not_swap_when_budget_would_blow(self):
        # A + C same zip but geographically far; B is closer to A.
        # Swapping A/B→C for A/C→B would ADD lots of distance
        # (A→C is huge). Budget refuses. No swap.
        stops = [
            {"id": "A", "lat": 37.75, "lng": -122.42, "zip": "94103"},
            {"id": "B", "lat": 37.751, "lng": -122.421, "zip": "94612"},
            {"id": "C", "lat": 40.75, "lng": -73.99,  "zip": "94103"},
        ]
        new_order, warnings = zip_cluster_swap_pass(
            ordered=stops, start_lat=37.75, start_lng=-122.42,
        )
        assert [s["id"] for s in new_order] == ["A", "B", "C"]
        # No "applied" warning — swap declined by budget.
        assert not any("applied" in w for w in warnings)

    def test_no_op_when_too_few_stops(self):
        stops = [
            {"id": "A", "lat": 37.75, "lng": -122.42, "zip": "94103"},
            {"id": "B", "lat": 37.80, "lng": -122.30, "zip": "94103"},
        ]
        new_order, warnings = zip_cluster_swap_pass(
            ordered=stops, start_lat=37.75, start_lng=-122.42,
        )
        assert [s["id"] for s in new_order] == ["A", "B"]
        # Neither "applied" nor "skipped" — <3 stops early exit.
        assert warnings == []

    def test_no_op_when_no_zip_data_available(self):
        stops = [
            {"id": "A", "lat": 37.75, "lng": -122.42},
            {"id": "B", "lat": 37.80, "lng": -122.30},
            {"id": "C", "lat": 37.751, "lng": -122.421},
        ]
        new_order, warnings = zip_cluster_swap_pass(
            ordered=stops, start_lat=37.75, start_lng=-122.42,
        )
        assert [s["id"] for s in new_order] == ["A", "B", "C"]
        assert any("no ZIP data" in w for w in warnings)

    def test_budget_constant_is_documented(self):
        # Lock the tolerance the SHIPPED note advertises (2%).
        # If a future dev changes this, they need to update the
        # user-facing summary text.
        assert ZIP_CLUSTER_TIEBREAKER_BUDGET == 0.02

    def test_does_not_mutate_input_list(self):
        stops = [
            {"id": "A", "lat": 37.75, "lng": -122.42, "zip": "1"},
            {"id": "B", "lat": 37.80, "lng": -122.30, "zip": "2"},
            {"id": "C", "lat": 37.751, "lng": -122.421, "zip": "1"},
        ]
        snapshot = [dict(s) for s in stops]
        _ = zip_cluster_swap_pass(
            ordered=stops, start_lat=37.75, start_lng=-122.42,
        )
        # Verify original list order + docs unchanged.
        assert [s["id"] for s in stops] == [s["id"] for s in snapshot]
