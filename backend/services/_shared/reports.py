"""Feb-2026 · P16B · Reports shared helpers.

Consolidates helper functions previously duplicated across the
``routers/reports_*.py`` files. Extraction is triggered by the
``services/_shared`` "rule of three" convention: once three+
routers need the same helper, it lifts here.

Contents:
  * ``_iso_day_bounds(start, end)`` — normalize ``YYYY-MM-DD`` inputs
    into inclusive UTC ISO bounds. Used by 7 report routers.
  * ``_parse_dt(v)`` — coerce ``str`` / ``datetime`` / ``None`` to a
    UTC-aware datetime, or ``None`` on parse failure.
  * ``_percentile(sorted_vals, pct)`` — nearest-rank percentile.
  * ``_norm_status(s)`` — canonicalize lead-status strings.
  * ``_first_float(row, *keys)`` — return the first strictly-positive
    float value at any of the given keys (Labor Efficiency +
    Booked-Out / Capacity report shape reconciler).

Names retain the underscore-prefix convention of the original
router-local defs so the ``from ... import _iso_day_bounds`` swap
is a byte-level rewrite of the call sites — nothing else changes.

The ``reports_client_lifetime_value.py`` router keeps its own
``_iso_day_bounds`` variant (materially different signature —
``Optional[str]`` args supporting an all-time mode). That drift is
locked in place by the dispatch guardrails and NOT reconciled here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import HTTPException


def _iso_day_bounds(start_date: str, end_date: str) -> tuple[str, str]:
    """Normalize ``YYYY-MM-DD`` inputs into inclusive ISO bounds.
    ``end_date`` becomes ``23:59:59.999999`` so a row stamped at
    ``23:30`` on the last day of the window is included."""
    try:
        s = datetime.fromisoformat(start_date).replace(
            hour=0, minute=0, second=0, microsecond=0,
            tzinfo=timezone.utc,
        )
        e = datetime.fromisoformat(end_date).replace(
            hour=23, minute=59, second=59, microsecond=999999,
            tzinfo=timezone.utc,
        )
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="start_date and end_date must be YYYY-MM-DD",
        )
    if e < s:
        raise HTTPException(400, "end_date must be >= start_date")
    return (s.isoformat(), e.isoformat())


def _parse_dt(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _percentile(sorted_vals: List[float], pct: float) -> float:
    """Nearest-rank percentile (matches Excel PERCENTILE.INC to
    within rounding for the small samples we surface). Returns 0.0
    when the input is empty."""
    if not sorted_vals:
        return 0.0
    if pct <= 0:
        return float(sorted_vals[0])
    if pct >= 100:
        return float(sorted_vals[-1])
    k = (len(sorted_vals) - 1) * (pct / 100)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return float(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac)


def _norm_status(s: Any) -> str:
    """Canonicalize the lead status. Mirror of the read-side of
    ``routers.leads.migrate_lead_statuses`` — lower-case + collapse
    whitespace + swap space for underscore. Values not on the
    canonical list flow through unchanged."""
    if not s:
        return ""
    v = str(s).strip().lower().replace(" ", "_")
    return v


def _first_float(row: dict, *keys: str) -> Optional[float]:
    for k in keys:
        v = row.get(k)
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv > 0:
            return fv
    return None


__all__ = [
    "_iso_day_bounds",
    "_parse_dt",
    "_percentile",
    "_norm_status",
    "_first_float",
]
