"""Sprint 3b · Feb-2026 — Tenant-scoped chemistry targets + gate mode.

Single source of truth for reading a tenant's editable chemistry
target ranges and gate mode. Falls back to the hardcoded AZ defaults
(mirroring ``services.pool_dosing._TARGETS``) when the tenant has
never customised the block — belt + suspenders on top of the
``tenant_chemistry_defaults_backfill`` migration.

Also owns validation used by ``PATCH /api/tenants/mine/settings/chemistry``.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("chemistry_tenant_targets")


# ── Canonical chemical keys — matches the codebase (Phase CHEM1). ──
# ``total_chlorine`` was removed in Phase CHEM1 and is intentionally
# absent here.
CHEMICAL_KEYS: Tuple[str, ...] = (
    "chlorine",
    "ph",
    "alkalinity",
    "cyanuric_acid",
    "calcium_hardness",
    "salt",
)

# Outer sanity bounds — the PATCH validator rejects target ranges
# outside these; these outer values match pool-industry realism.
# Note: salt uses 0-6000 ppm (per Sprint 3b brief — salt system
# ranges are wider than the other chemicals; 2500-3500 typical).
OUTER_BOUNDS: Dict[str, Tuple[float, float]] = {
    "chlorine":         (0.0, 10.0),
    "ph":               (0.0, 14.0),
    "alkalinity":       (0.0, 500.0),
    "cyanuric_acid":    (0.0, 300.0),
    "calcium_hardness": (0.0, 1000.0),
    "salt":             (0.0, 6000.0),
}

# UI unit strings. ``ph`` is unit-less by convention.
UNITS: Dict[str, str] = {
    "chlorine":         "ppm",
    "ph":               "",
    "alkalinity":       "ppm",
    "cyanuric_acid":    "ppm",
    "calcium_hardness": "ppm",
    "salt":             "ppm",
}

# ── AZ defaults — MIRROR ``services.pool_dosing._TARGETS``. ────────
# ``ideal`` matches the code-current bull's-eye (which is NOT always
# ``(min+max)/2``). This is critical for regression protection: an
# AZ-default tenant must see identical doses to today's behaviour.
#
# Phase P17.1 · Feb-2026 — canonical key renamed to ``chlorine``.
# The seasonal resolver in ``pool_dosing.resolve_chlorine_target``
# still overrides at compute-time for the high season (Mar–Sep,
# 5.0 ppm bull's-eye) — that behaviour is unchanged and orthogonal.
AZ_DEFAULT_TARGETS: Dict[str, Dict[str, Any]] = {
    "chlorine":         {"min": 1.0,  "max": 3.0,  "ideal": 2.0,   "unit": "ppm"},
    "ph":               {"min": 7.2,  "max": 7.6,  "ideal": 7.4,   "unit": ""},
    "alkalinity":       {"min": 80,   "max": 120,  "ideal": 100,   "unit": "ppm"},
    "cyanuric_acid":    {"min": 30,   "max": 50,   "ideal": 40,    "unit": "ppm"},
    "calcium_hardness": {"min": 200,  "max": 400,  "ideal": 250,   "unit": "ppm"},
    "salt":             {"min": 2700, "max": 3400, "ideal": 3200,  "unit": "ppm"},
}

GATE_MODES: Tuple[str, ...] = ("strict", "warn_only", "off")
DEFAULT_GATE_MODE = "strict"


# ── Per-request cache (async-safe via ContextVar). ────────────────
_REQ_CACHE: ContextVar[Optional[Dict[str, Dict[str, Any]]]] = ContextVar(
    "chemistry_targets_req_cache", default=None,
)


def _cache_get(tenant_id: str) -> Optional[Dict[str, Any]]:
    cache = _REQ_CACHE.get()
    if cache is None:
        return None
    return cache.get(tenant_id)


def _cache_set(tenant_id: str, value: Dict[str, Any]) -> None:
    cache = _REQ_CACHE.get()
    if cache is None:
        cache = {}
        _REQ_CACHE.set(cache)
    cache[tenant_id] = value


def reset_request_cache() -> None:
    """Test helper — invalidate the request cache."""
    _REQ_CACHE.set(None)


def default_targets() -> Dict[str, Dict[str, Any]]:
    """Return a fresh copy of the AZ default targets. Callers may
    mutate the return value safely."""
    return {k: dict(v) for k, v in AZ_DEFAULT_TARGETS.items()}


def _resolve_ideal(minimum: float, maximum: float, key: str) -> float:
    """Best-effort ideal picker for tenant-edited ranges.

    * If the AZ default ``ideal`` falls INSIDE the tenant's edited
      range, keep it (preserves regression for tenants whose only
      change is a slight range tweak).
    * Otherwise, use the midpoint.
    """
    az_ideal = AZ_DEFAULT_TARGETS.get(key, {}).get("ideal")
    if isinstance(az_ideal, (int, float)) and minimum <= az_ideal <= maximum:
        return float(az_ideal)
    return round((float(minimum) + float(maximum)) / 2.0, 3)


def merge_with_defaults(stored: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Merge the stored ``targets`` block onto AZ defaults.

    A stored partial (e.g. only ``chlorine`` edited) preserves
    every other chemical at the AZ default. Unknown/legacy keys are
    dropped. Adds a resolved ``ideal`` per chemical so downstream
    dosing math has a single, deterministic bull's-eye to aim at.
    """
    out: Dict[str, Dict[str, Any]] = default_targets()
    if not isinstance(stored, dict):
        return out
    for key in CHEMICAL_KEYS:
        row = stored.get(key)
        if not isinstance(row, dict):
            continue
        raw_min = row.get("min")
        raw_max = row.get("max")
        if raw_min is None or raw_max is None:
            continue
        try:
            m_min = float(raw_min)
            m_max = float(raw_max)
        except (TypeError, ValueError):
            continue
        out[key] = {
            "min": m_min,
            "max": m_max,
            "ideal": _resolve_ideal(m_min, m_max, key),
            "unit": UNITS.get(key, row.get("unit") or ""),
        }
    return out


# ── Async reader — fetches the tenant doc and merges with defaults ─
async def get_tenant_chemistry_settings(
    tenant_id: Optional[str], db=None,
) -> Dict[str, Any]:
    """Return the full ``chemistry`` settings block (targets + gate_mode
    + dosing_formulas) for the given tenant, merged with AZ defaults.

    ``tenant_id=None`` returns the pure AZ defaults — used by unit
    tests + the ``_pool_compute`` fallback path when the caller
    doesn't have a tenant in hand.
    """
    if not tenant_id:
        return {
            "targets": default_targets(),
            "gate_mode": DEFAULT_GATE_MODE,
            "dosing_formulas": {},
        }
    cached = _cache_get(tenant_id)
    if cached is not None:
        return cached
    if db is None:
        from config import db as _db
        db = _db
    tenant = await db.tenants.find_one(
        {"id": tenant_id},
        {"_id": 0, "settings.chemistry": 1},
    )
    stored = ((tenant or {}).get("settings") or {}).get("chemistry") or {}
    merged = {
        "targets": merge_with_defaults(stored.get("targets")),
        "gate_mode": _coerce_gate_mode(stored.get("gate_mode")),
        "dosing_formulas": {
            k: v for k, v in (stored.get("dosing_formulas") or {}).items()
            if isinstance(k, str) and isinstance(v, str) and v.strip()
        },
    }
    _cache_set(tenant_id, merged)
    return merged


def _coerce_gate_mode(v: Any) -> str:
    if isinstance(v, str) and v.strip().lower() in GATE_MODES:
        return v.strip().lower()
    return DEFAULT_GATE_MODE


# ── Validation for PATCH /settings/chemistry ───────────────────────
class ChemistryTargetError(Exception):
    """Raised by :func:`validate_targets_patch` — carries a ``detail``
    payload matching the 400 contract expected by callers."""

    def __init__(self, detail: Dict[str, Any]):
        super().__init__(detail.get("detail") or "chemistry_target_invalid")
        self.detail = detail


def validate_targets_patch(patch: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Validate a partial ``targets`` PATCH body and return the
    normalized dict ready for ``$set``.

    Rejects (with :class:`ChemistryTargetError`):
      * Unknown chemical keys.
      * ``min``/``max`` non-numeric.
      * ``min < 0`` or either value outside the chemical's outer
        sanity bounds (see :data:`OUTER_BOUNDS`).
      * ``min >= max``.
    """
    if not isinstance(patch, dict):
        raise ChemistryTargetError({
            "detail": "chemistry_target_invalid",
            "message": "targets patch must be an object",
        })
    out: Dict[str, Dict[str, Any]] = {}
    for key, row in patch.items():
        if key not in CHEMICAL_KEYS:
            raise ChemistryTargetError({
                "detail": "chemistry_target_unknown_key",
                "field": key,
                "message": f"unknown chemistry target '{key}'",
                "allowed": list(CHEMICAL_KEYS),
            })
        if not isinstance(row, dict):
            raise ChemistryTargetError({
                "detail": "chemistry_target_invalid",
                "field": key,
                "message": f"'{key}' must be an object with min + max",
            })
        raw_min = row.get("min")
        raw_max = row.get("max")
        if raw_min is None or raw_max is None:
            raise ChemistryTargetError({
                "detail": "chemistry_target_invalid",
                "field": key,
                "message": f"'{key}' requires both min and max",
            })
        try:
            m_min = float(raw_min)
            m_max = float(raw_max)
        except (TypeError, ValueError):
            raise ChemistryTargetError({
                "detail": "chemistry_target_invalid",
                "field": key,
                "message": f"'{key}' min/max must be numeric",
            })
        lo_bound, hi_bound = OUTER_BOUNDS[key]
        if m_min < lo_bound or m_max > hi_bound:
            raise ChemistryTargetError({
                "detail": "chemistry_target_out_of_bounds",
                "field": key,
                "message": (
                    f"'{key}' range {m_min}-{m_max} outside allowed "
                    f"{lo_bound}-{hi_bound}"
                ),
                "allowed": {"min": lo_bound, "max": hi_bound},
            })
        if m_min >= m_max:
            raise ChemistryTargetError({
                "detail": "chemistry_target_invalid",
                "field": key,
                "message": f"'{key}' min ({m_min}) must be < max ({m_max})",
            })
        out[key] = {"min": m_min, "max": m_max, "unit": UNITS.get(key, "")}
    return out


def validate_gate_mode(v: Any) -> str:
    if not isinstance(v, str) or v.strip().lower() not in GATE_MODES:
        raise ChemistryTargetError({
            "detail": "chemistry_gate_mode_invalid",
            "field": "gate_mode",
            "allowed": list(GATE_MODES),
            "message": f"gate_mode must be one of {GATE_MODES}",
        })
    return v.strip().lower()
