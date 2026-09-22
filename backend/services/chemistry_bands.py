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
    "chlorine":        {"average_min": 1,   "average_max": 5,   "above_avg_max": 10},
    "ph":              {"average_min": 7.2, "average_max": 7.6, "above_avg_max": 8.2},
    "alkalinity":      {"average_min": 80,  "average_max": 120, "above_avg_max": 140},
    "cyanuric_acid":   {"average_min": 30,  "average_max": 80,  "above_avg_max": 150},
}

# Feb-2026 · Door-hanger range-badge extension. These are OPTIONAL
# readings — a tenant's chemistry gate (see ``chemistry_gate.py``)
# still only requires the 5 canonical readings above at submit time.
# Customer-facing surfaces (door-hanger email, portal detail) render
# these with the same qualitative bands so the customer gets a full
# picture of the visit. Boundary rule (lower INCLUSIVE, upper
# EXCLUSIVE) matches CANONICAL — see module docstring.
EXTENDED_BAND_THRESHOLDS = {
    # Calcium Hardness (ppm) — low <200 / avg 200-400 / above 400-500 / elevated ≥500.
    "calcium_hardness": {"average_min": 200,  "average_max": 400,  "above_avg_max": 500},
    # Salt (ppm, salt pools) — low <2700 / avg 2700-3400 / above 3400-4000 / elevated ≥4000.
    "salt":             {"average_min": 2700, "average_max": 3400, "above_avg_max": 4000},
    # TDS (ppm) — low <500 / avg 500-1500 / above 1500-2000 / elevated ≥2000.
    "tds":              {"average_min": 500,  "average_max": 1500, "above_avg_max": 2000},
    # Phosphates (ppb) — low <100 / avg 100-200 / above 200-500 / elevated ≥500.
    "phosphates":       {"average_min": 100,  "average_max": 200,  "above_avg_max": 500},
}

# Union used by ``band_for_reading`` — CANONICAL keys keep their own
# semantics for callers that iterate the canonical map alone
# (e.g., the chemistry gate + tech UIs).
_ALL_BAND_THRESHOLDS = {**CANONICAL_BAND_THRESHOLDS, **EXTENDED_BAND_THRESHOLDS}

# UI-friendly display labels — imported from the chemistry-gate
# module so the bands section and the tech-facing form agree on the
# exact wording ("Chlorine", "pH", "Alkalinity", "CYA").
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
    return ``None`` when the key isn't banded (e.g. water_temp) or
    the value can't be parsed as a real number.

    Consults both ``CANONICAL_BAND_THRESHOLDS`` (chemistry-gate core
    readings) and ``EXTENDED_BAND_THRESHOLDS`` (customer-facing
    optional readings) so a single call classifies every banded key.

    Boundary rule: lower INCLUSIVE, upper EXCLUSIVE — see module
    docstring.
    """
    thresholds = _ALL_BAND_THRESHOLDS.get(key)
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
