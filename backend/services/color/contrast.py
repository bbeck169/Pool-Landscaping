"""Feb-2026 · Global Color Picker · shared WCAG contrast validator.

Every color-write endpoint (``PATCH /api/team/users/{uid}``, and
future service-category / tag writers) MUST route the incoming hex
through :func:`validate_color_hex_for_pin` to guarantee the color
remains legible against the map pin's white inner disc.

Threshold: WCAG 2.1 contrast ratio against pure white (``#FFFFFF``)
strictly BELOW 3.0 is rejected. The 3:1 threshold is the WCAG
"large UI graphics" bar — anything below reads as noise on a
36-pixel map pin.

Public API:
  * :func:`relative_luminance(hex)`      → float in [0, 1]
  * :func:`contrast_ratio_vs_white(hex)` → float
  * :func:`validate_color_hex_for_pin(hex)` — raises
    ``HTTPException(400, {"code": "color_contrast_too_low",
    "ratio": <float>, "min": 3.0})`` when the ratio is below 3.0
    OR the hex is malformed.
"""
from __future__ import annotations

import re
from typing import Tuple

from fastapi import HTTPException


_HEX_RE = re.compile(r"^#?([0-9A-Fa-f]{6})$")
_MIN_CONTRAST_VS_WHITE = 3.0


def _parse_hex(hex_str: str) -> Tuple[int, int, int]:
    """Return ``(r, g, b)`` for a 6-digit hex. Raises ``ValueError``
    on malformed inputs (short hex, non-hex chars, wrong length)."""
    if not isinstance(hex_str, str):
        raise ValueError("hex must be a string")
    m = _HEX_RE.match(hex_str.strip())
    if not m:
        raise ValueError(f"invalid hex color: {hex_str!r}")
    raw = m.group(1)
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def _linearize(v_255: int) -> float:
    """WCAG 2.1 linearised channel value in [0, 1]."""
    c = v_255 / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_str: str) -> float:
    """WCAG 2.1 relative luminance in [0, 1] for a 6-digit hex."""
    r, g, b = _parse_hex(hex_str)
    return (0.2126 * _linearize(r)
            + 0.7152 * _linearize(g)
            + 0.0722 * _linearize(b))


def contrast_ratio_vs_white(hex_str: str) -> float:
    """WCAG contrast ratio of ``hex_str`` against pure white.

    ``(L_lighter + 0.05) / (L_darker + 0.05)`` — white always
    dominates in the numerator so the formula collapses to
    ``1.05 / (L(color) + 0.05)``.
    """
    return 1.05 / (relative_luminance(hex_str) + 0.05)


def validate_color_hex_for_pin(hex_str: str) -> str:
    """Return the canonicalised (upper-case) hex when the color
    reads legibly on the pin disc. Raise ``HTTPException(400)``
    otherwise. Accepts inputs with or without a leading ``#``.
    """
    try:
        r, g, b = _parse_hex(hex_str)
    except ValueError:
        raise HTTPException(400, {
            "code": "color_hex_invalid",
            "message": "color must be a 6-digit hex (e.g. '#0EA5E9').",
        })
    ratio = contrast_ratio_vs_white(hex_str)
    if ratio < _MIN_CONTRAST_VS_WHITE:
        raise HTTPException(400, {
            "code": "color_contrast_too_low",
            "ratio": round(ratio, 3),
            "min": _MIN_CONTRAST_VS_WHITE,
            "message": (
                "This color is too light to read on the map pin. "
                "Pick a darker shade."
            ),
        })
    return f"#{r:02X}{g:02X}{b:02X}"


__all__ = [
    "relative_luminance",
    "contrast_ratio_vs_white",
    "validate_color_hex_for_pin",
]
