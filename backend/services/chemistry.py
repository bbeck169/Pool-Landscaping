"""Feb-2026 · Chemistry classification helper (Slice 3C).

Pool chemistry readings are stored as raw numeric values (e.g. Free
Chlorine ``3.2 ppm``).  Customer-portal surfaces must show a
qualitative *band* (``below`` / ``average`` / ``above`` / ``elevated``)
instead of the number so homeowners get a signal, not a puzzle. Admin
surfaces continue to see the raw number — with the band available on
the side as a small tooltip when the caller opts in.

The classification is a pure computation over the stored value. The
raw number is never mutated on disk.

Boundary policy (per product spec)
----------------------------------
Bands are ordered ``below → average → above → elevated``.  The band
transition happens **strictly above** each stated ceiling — so a Free
Chlorine of exactly 5.0 falls in ``average`` while 5.01 crosses into
``above``.  Concretely, for a chemical with thresholds ``lo`` (below
ceiling), ``mid`` (average ceiling) and ``hi`` (above ceiling)::

    value > hi        → elevated
    value > mid       → above
    value >= lo       → average         (except phosphates, no ``lo``)
    value < lo        → below

Phosphates have no ``below`` band — ``0`` is fine, so any value up to
and including the ``mid`` (100 ppb) is ``average``.

Chemicals covered
-----------------
The service-report doc uses keys such as ``chlorine`` (free) and
``combined_chlorine`` (combined, not total).  We normalise a small
alias table so both spec-facing keys (e.g. ``free_chlorine``, ``cya``)
and code-facing keys (e.g. ``chlorine``, ``cyanuric``) resolve to the
right threshold set. Keys we can't map (``salt``, ``calcium_hardness``,
``combined_chlorine``, ``water_temp``, …) return ``None`` — callers
should omit those readings from customer surfaces.
"""
from __future__ import annotations

from typing import Dict, Literal, Optional, Union

Band = Literal["below", "average", "above", "elevated"]

# ── Thresholds ────────────────────────────────────────────────────────────
# ``lo`` = ceiling of the "below" band  (values >= lo enter "average")
# ``mid`` = ceiling of the "average" band (values > mid enter "above")
# ``hi`` = ceiling of the "above" band   (values > hi enter "elevated")
#
# ``lo`` is None for phosphates (no "below" band — 0 is fine).
_THRESHOLDS: Dict[str, Dict[str, Optional[float]]] = {
    "free_chlorine":   {"lo": 2,   "mid": 5,    "hi": 8},
    "total_chlorine":  {"lo": 2,   "mid": 5,    "hi": 8},
    "ph":              {"lo": 7.2, "mid": 7.6,  "hi": 8.0},
    "alkalinity":      {"lo": 80,  "mid": 120,  "hi": 140},
    "cya":             {"lo": 30,  "mid": 100,  "hi": 150},
    "tds":             {"lo": 500, "mid": 2000, "hi": 2500},
    "phosphates":      {"lo": None, "mid": 100, "hi": 500},
}

# Map any input key (from service_reports.chemical_readings[].key or a
# spec-facing alias) to a threshold key. Anything not in this map is
# returned as-is and looked up in ``_THRESHOLDS``; a miss returns ``None``.
_ALIASES: Dict[str, str] = {
    "chlorine": "free_chlorine",
    "free_cl": "free_chlorine",
    "free_chlorine": "free_chlorine",

    "total_cl": "total_chlorine",
    "total_chlorine": "total_chlorine",

    # ``combined_chlorine`` deliberately DOES NOT map — the numeric
    # range of combined Cl is very different from free/total, and
    # applying total-Cl thresholds would mis-classify most readings.

    "ph": "ph",
    "alkalinity": "alkalinity",
    "total_alkalinity": "alkalinity",

    "cyanuric": "cya",
    "cyanuric_acid": "cya",
    "cya": "cya",

    "tds": "tds",
    "total_dissolved_solids": "tds",

    "phosphates": "phosphates",
    "phosphate": "phosphates",
}


def _canonical(chemical: str) -> Optional[str]:
    """Return the threshold-table key for ``chemical`` (or ``None``)."""
    if not chemical:
        return None
    k = str(chemical).strip().lower()
    k = _ALIASES.get(k, k)
    return k if k in _THRESHOLDS else None


def classify_reading(
    chemical: str,
    value: Union[int, float, str, None],
) -> Optional[Band]:
    """Return the band label for ``value`` on ``chemical``.

    Returns ``None`` when:
    * ``value`` is None, empty, or not numeric
    * ``chemical`` is unknown or doesn't have a threshold set
    """
    key = _canonical(chemical)
    if key is None:
        return None

    # Coerce numeric — strings from the picker widget are common.
    if value is None or value == "":
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None

    bands = _THRESHOLDS[key]
    hi = bands["hi"]
    mid = bands["mid"]
    lo = bands["lo"]

    if v > hi:
        return "elevated"
    if v > mid:
        return "above"
    # Phosphates: no "below" — everything from 0 up to ``mid`` is average.
    if lo is None:
        return "average"
    if v >= lo:
        return "average"
    return "below"


def classify_readings(readings) -> Dict[str, Band]:
    """Convenience — build a ``{key: band}`` map from a readings list.

    Silently skips readings without a classifiable key / numeric value.
    Accepts either a list-of-dicts (``[{"key":..., "value":...}]``) or
    a dict (``{key: value}``).
    """
    out: Dict[str, Band] = {}
    if not readings:
        return out
    if isinstance(readings, dict):
        items = readings.items()
    else:
        items = (
            (r.get("key"), r.get("value"))
            for r in readings
            if isinstance(r, dict)
        )
    for key, value in items:
        band = classify_reading(key or "", value)
        if band is not None and key:
            out[str(key)] = band
    return out
