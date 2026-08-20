"""Feb-2026 · Qualitative water-test bands for customer-facing views.

Turns raw ppm/pH numbers into one of four user-friendly labels:

  * ``Below Average``
  * ``Average``
  * ``Above Average``
  * ``Elevated``

Used by the door-hanger email + the portal service-report page.
Tech / admin surfaces continue to render exact numeric values.

Boundary rule (product-approved, Feb-2026):
    **Lower bound INCLUSIVE, upper bound EXCLUSIVE.**
Concretely:

  * Free Cl == 1.0 → ``Average`` (not Below Average)
  * Free Cl == 5.0 → ``Above Average`` (not Average)
  * Free Cl == 10  → ``Elevated`` (not Above Average)

This matches most pool-industry lookup tables and keeps every
boundary deterministic, so an ``exactly-at-boundary`` reading
always classifies into the HIGHER band.
"""
from __future__ import annotations

from typing import Any, Optional


BAND_BELOW = "Below Average"
BAND_AVERAGE = "Average"
BAND_ABOVE = "Above Average"
BAND_ELEVATED = "Elevated"

# Thresholds — user-confirmed for pH / Alkalinity / CYA. Free Cl and
# Total Cl "Above Average" / "Elevated" cutoffs (5 – 10 / >= 10) are
# main-agent defaults surfaced for confirmation in the release notes.
CANONICAL_BAND_THRESHOLDS = {
    "free_chlorine":   {"average_min": 1,   "average_max": 5,   "above_avg_max": 10},
    "total_chlorine":  {"average_min": 1,   "average_max": 5,   "above_avg_max": 10},
    "ph":              {"average_min": 7.2, "average_max": 7.6, "above_avg_max": 8.2},
    "alkalinity":      {"average_min": 80,  "average_max": 120, "above_avg_max": 140},
    "cyanuric_acid":   {"average_min": 30,  "average_max": 80,  "above_avg_max": 150},
}

# UI-friendly display labels — imported from the chemistry-gate
# module so the bands section and the tech-facing form agree on the
# exact wording ("Free Cl", "Total Cl", "pH", "Alkalinity", "CYA").
from services.chemistry_gate import DISPLAY_LABELS  # noqa: E402


def _coerce_float(v: Any) -> Optional[float]:
    """Return a finite float, or ``None`` for anything unparseable
    (matches the missing-reading semantics of the chemistry gate)."""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            f = float(s)
        except (TypeError, ValueError):
            return None
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    return None


def band_for_reading(key: str, value: Any) -> Optional[str]:
    """Classify a single reading into one of the four bands, or
    return ``None`` when the key isn't banded (e.g. water_temp,
    calcium_hardness) or the value can't be parsed as a real
    number.

    Boundary rule: lower INCLUSIVE, upper EXCLUSIVE — see module
    docstring.
    """
    thresholds = CANONICAL_BAND_THRESHOLDS.get(key)
    if not thresholds:
        return None
    v = _coerce_float(value)
    if v is None:
        return None
    if v < thresholds["average_min"]:
        return BAND_BELOW
    if v < thresholds["average_max"]:
        return BAND_AVERAGE
    if v < thresholds["above_avg_max"]:
        return BAND_ABOVE
    return BAND_ELEVATED
