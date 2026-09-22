"""Sprint 3b · Feb-2026 — Chemistry configuration API.

Two admin-only endpoint groups mounted under
``/api/tenants/mine/settings/chemistry`` (targets + gate_mode) and
``/api/tenants/mine/settings/chemistry/dosing-formulas``, plus a
preview endpoint at ``/api/chemistry/dose/preview``.

Persistence lives on the tenant document under
``settings.chemistry.*`` — same pattern as Ticket #3/#4 (see
``routers/tenant_org_settings.py``).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from config import db
from routers.tenants import get_current_tenant
from services.chemistry_dosing_engine import (
    FORMULA_KEYS,
    AZ_DEFAULT_FORMULAS,
    _FORMULA_MAX_LEN,
    dry_run_formula,
    evaluate as engine_evaluate,
)
from services.chemistry_tenant_targets import (
    CHEMICAL_KEYS,
    ChemistryTargetError,
    OUTER_BOUNDS,
    UNITS,
    default_targets,
    get_tenant_chemistry_settings,
    reset_request_cache,
    validate_gate_mode,
    validate_targets_patch,
)
from utils import require_admin


log = logging.getLogger("tenant_chemistry_settings")

router = APIRouter(tags=["chemistry-settings"])


# ─── Targets + gate_mode ────────────────────────────────────────────
class ChemistryTargetRowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min: float
    max: float


class ChemistrySettingsPatchIn(BaseModel):
    """Partial PATCH — each field optional.

    ``targets`` is a partial dict keyed by chemical (e.g. only
    ``{"chlorine": {"min": 1.2, "max": 3.5}}`` to edit one row).
    ``gate_mode`` accepts ``strict`` / ``warn_only`` / ``off``.
    """
    model_config = ConfigDict(extra="forbid")
    targets: Optional[Dict[str, ChemistryTargetRowIn]] = None
    gate_mode: Optional[str] = None


def _serialize_targets(merged: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Render targets in the API contract (unit + min + max only —
    ``ideal`` stays server-side)."""
    out: Dict[str, Dict[str, Any]] = {}
    for key in CHEMICAL_KEYS:
        row = merged.get(key) or {}
        out[key] = {
            "min":  float(row.get("min", 0)),
            "max":  float(row.get("max", 0)),
            "unit": UNITS.get(key, row.get("unit") or ""),
        }
    return out


@router.get("/tenants/mine/settings/chemistry")
async def get_chemistry_settings(
    _user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    settings = await get_tenant_chemistry_settings(tenant["id"], db)
    return {
        "targets":   _serialize_targets(settings["targets"]),
        "gate_mode": settings["gate_mode"],
        "outer_bounds": OUTER_BOUNDS,
    }


@router.patch("/tenants/mine/settings/chemistry")
async def patch_chemistry_settings(
    body: ChemistrySettingsPatchIn,
    _user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    updates: Dict[str, Any] = {}
    if body.targets is not None:
        raw = {k: v.model_dump() for k, v in body.targets.items()}
        try:
            validated = validate_targets_patch(raw)
        except ChemistryTargetError as ex:
            raise HTTPException(status_code=400, detail=ex.detail)
        for key, row in validated.items():
            updates[f"settings.chemistry.targets.{key}"] = row
    if body.gate_mode is not None:
        try:
            gm = validate_gate_mode(body.gate_mode)
        except ChemistryTargetError as ex:
            raise HTTPException(status_code=400, detail=ex.detail)
        updates["settings.chemistry.gate_mode"] = gm
    if updates:
        await db.tenants.update_one({"id": tenant["id"]}, {"$set": updates})
        reset_request_cache()
    settings = await get_tenant_chemistry_settings(tenant["id"], db)
    return {
        "targets":   _serialize_targets(settings["targets"]),
        "gate_mode": settings["gate_mode"],
        "outer_bounds": OUTER_BOUNDS,
    }


# ─── Dosing formulas ────────────────────────────────────────────────
class DosingFormulasPatchIn(BaseModel):
    """Partial PATCH — each formula field optional.

    Formula strings are SimpleEval-safe arithmetic (see
    ``services.chemistry_dosing_engine`` for the whitelist).
    Empty string clears back to the AZ default.
    """
    model_config = ConfigDict(extra="forbid")
    chlorine:            Optional[str] = None
    ph_up:               Optional[str] = None
    ph_down:             Optional[str] = None
    alkalinity_up:       Optional[str] = None
    cyanuric_acid_up:    Optional[str] = None
    calcium_hardness_up: Optional[str] = None
    salt_up:             Optional[str] = None


def _serialize_formulas(stored: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Render one row per formula key with tenant + default strings +
    whether the tenant has overridden the default."""
    out: Dict[str, Dict[str, Any]] = {}
    for key in FORMULA_KEYS:
        tenant_formula = stored.get(key)
        has_override = isinstance(tenant_formula, str) and tenant_formula.strip() != ""
        out[key] = {
            "tenant_formula": tenant_formula if has_override else "",
            "default_formula": AZ_DEFAULT_FORMULAS[key],
            "using_default":   not has_override,
        }
    return out


@router.get("/tenants/mine/settings/chemistry/dosing-formulas")
async def get_dosing_formulas(
    _user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    settings = await get_tenant_chemistry_settings(tenant["id"], db)
    return {
        "formulas": _serialize_formulas(settings.get("dosing_formulas") or {}),
        "allowed_names":     [
            "current", "min_target", "max_target", "avg_target",
            "volume_gallons", "delta",
        ],
        "allowed_functions": ["abs", "min", "max", "round"],
        "max_length": _FORMULA_MAX_LEN,
    }


@router.patch("/tenants/mine/settings/chemistry/dosing-formulas")
async def patch_dosing_formulas(
    body: DosingFormulasPatchIn,
    _user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    updates: Dict[str, Any] = {}
    for key in FORMULA_KEYS:
        val = getattr(body, key, None)
        if val is None:
            continue
        if not isinstance(val, str) or not val.strip():
            # Empty → clear override; store an empty string (the
            # merger drops empty strings so the tenant falls back to
            # the AZ default automatically).
            updates[f"settings.chemistry.dosing_formulas.{key}"] = ""
            continue
        # Dry-run against a synthetic reading BEFORE persisting.
        result = dry_run_formula(val)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail={
                "detail": "chemistry_formula_invalid",
                "field": key,
                "error": result.get("error"),
                "message": f"formula for '{key}' failed dry-run: {result.get('error')}",
            })
        updates[f"settings.chemistry.dosing_formulas.{key}"] = val.strip()
    if updates:
        await db.tenants.update_one({"id": tenant["id"]}, {"$set": updates})
        reset_request_cache()
    settings = await get_tenant_chemistry_settings(tenant["id"], db)
    return {
        "formulas": _serialize_formulas(settings.get("dosing_formulas") or {}),
        "allowed_names":     [
            "current", "min_target", "max_target", "avg_target",
            "volume_gallons", "delta",
        ],
        "allowed_functions": ["abs", "min", "max", "round"],
        "max_length": _FORMULA_MAX_LEN,
    }


# ─── Preview endpoint (admin-only) ─────────────────────────────────
class DosePreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chemical:        str
    current:         float
    volume_gallons:  float
    formula:         Optional[str] = None  # optional tenant-authored candidate


@router.post("/chemistry/dose/preview")
async def preview_dose(
    body: DosePreviewIn,
    _user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    if body.chemical not in FORMULA_KEYS:
        raise HTTPException(status_code=400, detail={
            "detail": "chemistry_formula_invalid",
            "field":  "chemical",
            "message": f"'{body.chemical}' not in {list(FORMULA_KEYS)}",
        })
    # Fetch tenant settings — we need the resolved target range so the
    # preview uses the SAME range the tenant configured.
    settings = await get_tenant_chemistry_settings(tenant["id"], db)
    # Map formula key back to its chemical key for target lookup
    # (``ph_up``/``ph_down`` both use ``ph``; ``*_up`` uses the base key).
    target_key = body.chemical.rsplit("_up", 1)[0].rsplit("_down", 1)[0]
    target_range = settings["targets"].get(target_key) or default_targets().get(target_key)
    if not target_range:
        raise HTTPException(status_code=400, detail={
            "detail": "chemistry_formula_invalid",
            "message": f"no target range configured for {target_key}",
        })
    # If a candidate formula is provided, dry-run it FIRST so the
    # response surfaces a clean 400 on syntax/timeout/unsafe.
    if body.formula and body.formula.strip():
        dr = dry_run_formula(body.formula)
        if not dr.get("ok"):
            raise HTTPException(status_code=400, detail={
                "detail": "chemistry_formula_invalid",
                "field":  "formula",
                "error":  dr.get("error"),
                "message": dr.get("error"),
            })
    result = engine_evaluate(
        chemical=body.chemical,
        current=body.current,
        target_range=target_range,
        volume_gallons=body.volume_gallons,
        tenant_formula=body.formula,
    )
    return result
