"""Phase I1.5.a — WCAG contrast helpers.

Pure functions, no state. Deliberately kept in their own module so
I1 (industry profile) + I1.5.b (frontend preview) can import them
without dragging in the presets registry.
"""
from __future__ import annotations


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    c = (color or "").strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        raise ValueError(f"invalid hex color: {color!r}")
    try:
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except ValueError as e:
        raise ValueError(f"invalid hex color: {color!r}") from e


def _channel_luminance(c: int) -> float:
    v = c / 255.0
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    """WCAG relative luminance (0.0 = black, 1.0 = white)."""
    r, g, b = _hex_to_rgb(color)
    return (
        0.2126 * _channel_luminance(r)
        + 0.7152 * _channel_luminance(g)
        + 0.0722 * _channel_luminance(b)
    )


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG contrast ratio between two hex colors. 1.0 → 21.0."""
    l1 = relative_luminance(fg)
    l2 = relative_luminance(bg)
    lo, hi = (l1, l2) if l1 < l2 else (l2, l1)
    return (hi + 0.05) / (lo + 0.05)


def passes_aa_normal_text(fg: str, bg: str) -> bool:
    """WCAG AA for normal-size body text: ≥ 4.5:1."""
    return contrast_ratio(fg, bg) >= 4.5
