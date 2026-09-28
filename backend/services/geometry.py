"""Geometry helpers shared by the CAD Studio + AI Measure surfaces.

Phase CAD-2 · Feb-2026 — extracted from
``routers/ai_measure.py::polygon_area_pixels`` so the CAD router can
call the shoelace math without importing an admin-only measure
router (which would pull in the whole Google + Vision stack). The
extraction is byte-identical: the original is now a re-export from
this module.

Pure functions — no I/O, no DB, no logging. Safe to import from any
router / service / test.
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, List, Sequence, Tuple


# ─── Legacy polygon-area shoelace (pixel-space) ─────────────────────
def polygon_area_pixels(polygon: Sequence[Sequence[float]]) -> float:
    """Shoelace area of a polygon in **pixel space**.

    ``polygon`` is a sequence of ``[x, y]`` pairs. Winding order
    (CW / CCW) is irrelevant — the sign is dropped with ``abs``.
    Returns ``0.0`` for any polygon with fewer than 3 vertices
    (matches the legacy contract in ``routers.ai_measure``).
    """
    n = len(polygon)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = polygon[i][0], polygon[i][1]
        x2, y2 = polygon[(i + 1) % n][0], polygon[(i + 1) % n][1]
        s += (x1 * y2) - (x2 * y1)
    return abs(s) / 2.0


# ─── CAD-2 additions ────────────────────────────────────────────────
def _to_pair(pt) -> Tuple[float, float]:
    """Accept either ``[x, y]`` list/tuple or ``{"x": _, "y": _}``
    dict — the FE speaks the dict form, ``polygon_area_pixels``'s
    legacy signature spoke the list form. Normalize on input."""
    if isinstance(pt, dict):
        return float(pt.get("x", 0.0)), float(pt.get("y", 0.0))
    return float(pt[0]), float(pt[1])


def polygon_area_normalized_to_sqft(
    coords: Iterable, *,
    canvas_w_ft: float, canvas_h_ft: float,
) -> float:
    """Shoelace on **normalized** 0..1 coordinates → **sq ft**.

    Multiplies each coord pair by ``(canvas_w_ft, canvas_h_ft)`` so
    the shoelace runs in feet space. Returns ``0.0`` for degenerate
    input (fewer than 3 points). Self-intersecting polygons still
    get a computed value (shoelace is undefined for those, but the
    absolute value is the closest single-number answer — callers
    can decide whether to warn).
    """
    pairs = [_to_pair(p) for p in coords]
    if len(pairs) < 3:
        return 0.0
    px = [(x * canvas_w_ft, y * canvas_h_ft) for x, y in pairs]
    return polygon_area_pixels(px)


def polyline_length_normalized_to_ft(
    coords: Iterable, *,
    canvas_w_ft: float, canvas_h_ft: float,
) -> float:
    """Sum of segment lengths for a **polyline** (open) in
    normalized coords, converted to feet. Returns ``0.0`` for
    fewer than 2 vertices.
    """
    pairs = [_to_pair(p) for p in coords]
    if len(pairs) < 2:
        return 0.0
    total = 0.0
    for i in range(len(pairs) - 1):
        x1, y1 = pairs[i]
        x2, y2 = pairs[i + 1]
        dx = (x2 - x1) * canvas_w_ft
        dy = (y2 - y1) * canvas_h_ft
        total += math.hypot(dx, dy)
    return total


def clamp_normalized_coords(coords: Iterable) -> Tuple[List[Dict[str, float]], bool]:
    """Clamp each ``x/y`` into ``[0.0, 1.0]`` and report whether
    any clamp actually happened. Always returns a fresh list of
    ``{"x": _, "y": _}`` dicts — safe to hand back to the FE."""
    out: List[Dict[str, float]] = []
    clamped = False
    for p in coords:
        x, y = _to_pair(p)
        nx = min(1.0, max(0.0, x))
        ny = min(1.0, max(0.0, y))
        if nx != x or ny != y:
            clamped = True
        out.append({"x": nx, "y": ny})
    return out, clamped


def polygon_self_intersects(coords: Iterable) -> bool:
    """Best-effort self-intersection check on a **closed** polygon.
    Handles the small vertex counts a hand-drawn paver polygon
    generates (< ~20 vertices) in O(n^2) — good enough for editor-
    time labels. Returns ``False`` for < 4 vertices."""
    pairs = [_to_pair(p) for p in coords]
    n = len(pairs)
    if n < 4:
        return False

    def _seg_intersect(p1, p2, p3, p4) -> bool:
        # Standard 2D segment-intersection using cross products.
        def _cross(o, a, b):
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
        d1 = _cross(p3, p4, p1)
        d2 = _cross(p3, p4, p2)
        d3 = _cross(p1, p2, p3)
        d4 = _cross(p1, p2, p4)
        if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and (
            (d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)
        ):
            return True
        return False

    for i in range(n):
        a1, a2 = pairs[i], pairs[(i + 1) % n]
        # Skip adjacent + wrap-adjacent edges.
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            b1, b2 = pairs[j], pairs[(j + 1) % n]
            if _seg_intersect(a1, a2, b1, b2):
                return True
    return False


__all__ = [
    "polygon_area_pixels",
    "polygon_area_normalized_to_sqft",
    "polyline_length_normalized_to_ft",
    "clamp_normalized_coords",
    "polygon_self_intersects",
]
