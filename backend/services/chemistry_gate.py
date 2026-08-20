"""Feb-2026 · Chemistry required-readings gate.

Single source of truth for the "5 core readings needed to close a
job" business rule.  Used by every backend path that can transition
a job to ``completed``:

  * ``POST /api/jobs/{jid}/service-report/submit`` (tech submit)
  * ``PUT  /api/jobs/{jid}`` when the payload flips ``status`` to
    ``completed`` (admin edit)
  * ``mobile_sync._handle_job_close`` (offline replay)

The five required keys map to the canonical service-report field
names.  ``chemical_readings`` on either the ``service_reports`` doc
(list-of-dicts shape) OR the legacy ``jobs.chemical_readings`` dict
are both accepted — the helper normalises to a flat dict before the
check.

"Could Not Service" transitions and any other non-``completed``
status change are NOT gated.  See :func:`assert_core_readings_present`
for the raise contract.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException

# Canonical field names.  Aliases (``free_cl`` / ``total_cl`` / ``cya``)
# fold onto these keys during normalisation.
CORE_READINGS: List[str] = [
    "free_chlorine",
    "total_chlorine",
    "alkalinity",
    "ph",
    "cyanuric_acid",
]

# UI-friendly SHORT labels for the ``missing_fields`` payload — used
# by legacy API consumers and machine parsers (kebab-y snake case).
_LABEL: Dict[str, str] = {
    "free_chlorine":  "free_cl",
    "total_chlorine": "total_cl",
    "alkalinity":     "alkalinity",
    "ph":             "ph",
    "cyanuric_acid":  "cya",
}

# Human-friendly DISPLAY labels for the ``missing_labels`` payload +
# every UI surface (button tooltips, inline banners, mobile hints).
# Product-approved wording (Feb-2026 spec).
DISPLAY_LABELS: Dict[str, str] = {
    "free_chlorine":  "Free Cl",
    "total_chlorine": "Total Cl",
    "alkalinity":     "Alkalinity",
    "ph":             "pH",
    "cyanuric_acid":  "CYA",
}

_ALIASES: Dict[str, str] = {
    "free_cl":            "free_chlorine",
    "freecl":             "free_chlorine",
    "free chlorine":      "free_chlorine",
    "total_cl":           "total_chlorine",
    "totalcl":            "total_chlorine",
    "total chlorine":     "total_chlorine",
    "cya":                "cyanuric_acid",
    "cyanuric":           "cyanuric_acid",
    "cyanuric acid":      "cyanuric_acid",
    "ph_balance":         "ph",
    "ph balance":         "ph",
    "alk":                "alkalinity",
    "total_alkalinity":   "alkalinity",
}


def _canonical_key(k: Any) -> Optional[str]:
    if not isinstance(k, str):
        return None
    norm = k.strip().lower().replace("-", "_")
    if norm in CORE_READINGS:
        return norm
    return _ALIASES.get(norm) or _ALIASES.get(norm.replace("_", " "))


def _is_valid_reading(v: Any) -> bool:
    """A reading is VALID when it parses as a real (finite) float.
    ``None`` / empty / whitespace / unparseable strings are MISSING.
    ``0`` and negative floats are treated as valid readings — real
    chemistry values, not sentinels."""
    if v is None:
        return False
    if isinstance(v, bool):
        # ``True`` / ``False`` are numeric in Python but we don't
        # want a stray boolean flag to satisfy the gate.
        return False
    if isinstance(v, (int, float)):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return False
        # Reject NaN / inf.
        return f == f and f not in (float("inf"), float("-inf"))
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return False
        try:
            f = float(s)
        except (TypeError, ValueError):
            return False
        return f == f and f not in (float("inf"), float("-inf"))
    return False


def normalize_readings(source: Any) -> Dict[str, Any]:
    """Coerce a ``chemical_readings`` payload into a flat
    ``{canonical_key: value}`` dict.  Accepts:

    * list-of-dicts:   ``[{"key": "free_chlorine", "value": 2.5}, …]``
                       — the ``service_reports.chemical_readings`` shape.
    * dict:            ``{"free_chlorine": 2.5, …}``
                       — the legacy ``jobs.chemical_readings`` shape.

    Unknown / unaliased keys are dropped.  The first occurrence of
    a canonical key wins (list order preserved).
    """
    out: Dict[str, Any] = {}
    if isinstance(source, dict):
        for k, v in source.items():
            ck = _canonical_key(k)
            if ck and ck not in out:
                out[ck] = v
        return out
    if isinstance(source, list):
        for row in source:
            if not isinstance(row, dict):
                continue
            ck = _canonical_key(row.get("key") or row.get("name"))
            if not ck or ck in out:
                continue
            out[ck] = row.get("value")
        return out
    return out


def missing_core_readings(source: Any) -> List[str]:
    """Return the machine-friendly SHORT label list of MISSING core
    readings (matches ``missing_fields`` in the 422 payload).
    Empty list means the gate would pass."""
    norm = normalize_readings(source)
    return [_LABEL[k] for k in CORE_READINGS if not _is_valid_reading(norm.get(k))]


def missing_core_reading_labels(source: Any) -> List[str]:
    """Return the human-friendly DISPLAY label list of MISSING core
    readings (matches ``missing_labels`` in the 422 payload).  Same
    ordering as :func:`missing_core_readings`."""
    norm = normalize_readings(source)
    return [DISPLAY_LABELS[k] for k in CORE_READINGS if not _is_valid_reading(norm.get(k))]


def assert_core_readings_present(source: Any) -> None:
    """Raise ``HTTPException(422)`` when any of the five core
    chemistry readings is missing.  Uses the same detail shape
    across every call site so the FE can key off ``detail`` and
    render ``missing_fields`` / ``missing_labels`` inline.
    """
    norm = normalize_readings(source)
    missing_keys = [k for k in CORE_READINGS
                    if not _is_valid_reading(norm.get(k))]
    if not missing_keys:
        return
    raise HTTPException(
        status_code=422,
        detail={
            "detail": "chemistry_core_readings_missing",
            "missing_fields": [_LABEL[k] for k in missing_keys],
            "missing_labels": [DISPLAY_LABELS[k] for k in missing_keys],
            "message": "Cannot close job — required chemistry readings missing",
        },
    )


def gather_readings_for_job(job: Dict[str, Any],
                             service_report: Optional[Dict[str, Any]] = None,
                             ) -> Dict[str, Any]:
    """Compose the flat readings dict from BOTH the service_report
    (preferred) and the job doc (legacy fallback).  Used by the
    admin PUT and mobile-sync paths where the caller may not have
    the service_report in hand."""
    combined: Dict[str, Any] = {}
    if service_report:
        combined.update(normalize_readings(service_report.get("chemical_readings")))
    if job:
        legacy = normalize_readings(job.get("chemical_readings"))
        for k, v in legacy.items():
            combined.setdefault(k, v)
    return combined


def is_pool_job(job: Dict[str, Any]) -> bool:
    """Pool jobs are the only ones that carry chemistry.  Landscape
    jobs don't have readings — the gate MUST NOT block their
    completion.  Reuses the same heuristic surface as
    ``routers/jobs._derive_checklist_kind`` (imported lazily to
    avoid a hard dependency in this small helper module)."""
    try:
        from routers.jobs import _derive_checklist_kind
        return _derive_checklist_kind(job, None) == "pool"
    except Exception:
        # Fail-safe fallback — treat as pool so we err toward
        # gating rather than accidentally letting a pool job close
        # without readings.  If the caller knows it's a landscape
        # job it can skip calling the gate entirely.
        return True
