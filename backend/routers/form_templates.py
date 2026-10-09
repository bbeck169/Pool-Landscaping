"""Phase 7A · Feb-2026 — Form Templates (scaffold).

Backend-only scaffold for the drag-and-drop form editor.  Ships the
data model + CRUD endpoints for the ``form_templates`` collection,
plus the ``build_default_form_template`` seed-template builder for
all currently-rendered form surfaces.

Phase 7A ships:
    * ``db.form_templates`` collection shape
    * 5 endpoints under ``/api/form-templates/...``
    * Seed templates derived from the hardcoded render sites
    * Lazy-init on first GET (no migration script)
    * Reorder-and-restyle-only validation on PUT

Phase 7A does NOT ship (deferred to 7B/7C/7D):
    * The drag-reorder / color-picker editor UI
    * The runtime renderers that consume the current template
    * Field add / delete workflow (PUT rejects both today)

Role gates
----------
GET  /api/form-templates                   admin / super_admin / owner / manager
GET  /api/form-templates/{form_type}       admin / super_admin / owner / manager
GET  /api/form-templates/{form_type}/versions
                                           admin / super_admin / owner  (manager 403)
PUT  /api/form-templates/{form_type}       admin / super_admin / owner  (manager 403)
POST /api/form-templates/{form_type}/revert/{version}
                                           admin / super_admin / owner  (manager 403)

Tenant isolation
----------------
Every query is scoped by ``user["tenant_id"]`` so a super_admin of
tenant A cannot read or mutate tenant B's templates — a cross-tenant
GET returns the asking tenant's lazily-seeded v1 (same shape, but
distinct ``id``), not tenant B's doc.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db
from utils import get_current_user, new_id, now_iso


router = APIRouter(tags=["form-templates"])


# ──────────────────────────────────────────────────────────────────
#  Enums + constants
# ──────────────────────────────────────────────────────────────────

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

#
# Form types.  The brief called for "6 form surfaces" with the caveat
# that ``job_checklist`` splits into its own ``form_type`` per variant.
# The current render surfaces are:
#
#   1. Pool service report              → ``pool_service_report``
#   2. Landscape service report         → ``landscape_service_report``
#   3. Job checklist (pool variant)     → ``job_checklist_pool``
#   4. Job checklist (landscape variant)→ ``job_checklist_landscape``
#   5. Job checklist (generic variant)  → ``job_checklist_generic``
#   6. Estimate                         → ``estimate``
#   7. Invoice                          → ``invoice``
#   8. CAD editor overlay               → ``cad_overlay``
#
# The three ``job_checklist_*`` variants mirror the three in-code
# defaults (``POOL_CHECKLIST_DEFAULT`` / ``LANDSCAPE_CHECKLIST_DEFAULT``
# / ``GENERIC_CHECKLIST_DEFAULT`` at ``routers/service_reports.py``)
# which currently drive the checklist shape of a service report.  The
# broader 11-industry ``industry_checklists.py`` seed is a *separate*
# concept (industry-matched defaults inside a service report) and is
# intentionally not enumerated here — Phase 7B/7C may extend the enum
# once the editor surface is wired.
#
FORM_TYPES = (
    "pool_service_report",
    "landscape_service_report",
    "job_checklist_pool",
    "job_checklist_landscape",
    "job_checklist_generic",
    "estimate",
    "invoice",
    "cad_overlay",
)


DEFAULT_FIELD_STYLE: Dict[str, Any] = {
    "bg_color":     "#FFFFFF",
    "bg_alpha":     1.0,
    "text_color":   "#111827",
    "border_color": "#E5E7EB",
    "width_cols":   12,
    "padding_y":    2,
}


def _col_style(width_cols: int) -> Dict[str, Any]:
    s = dict(DEFAULT_FIELD_STYLE)
    s["width_cols"] = width_cols
    return s


# ──────────────────────────────────────────────────────────────────
#  Seed field lists  (one tuple-list per form_type)
#
#  Phase 7A deliberately uses the SAME default style for every field
#  — including the "billable / payment" fields on pool-service-report
#  chemical dosing and on the estimate / invoice ``line_items_table``.
#  Pre-Phase-7A those fields were locked to a white background by the
#  renderer; Phase 7B/7C make the editable surface unlock them.  This
#  seed therefore treats them identically so the editor has a uniform
#  starting point.
# ──────────────────────────────────────────────────────────────────

# (field_id, label, field_type, width_cols)
_POOL_SR_FIELDS: List[tuple] = [
    ("water_body_identifier",   "Water Body",          "water_body_header",       12),
    ("chemistry_readings",      "Chemistry Readings",  "chemistry_readings",      12),
    ("chemicals_added_section", "Chemicals Added",     "chemicals_added_section", 12),
    ("checklist_section",       "Checklist",           "checklist_section",       12),
    ("notes",                   "Technician Notes",    "textarea",                12),
    ("photos",                  "Photos",              "photo",                   12),
    ("signature",               "Signature",           "signature",               12),
]

_LANDSCAPE_SR_FIELDS: List[tuple] = [
    ("checklist_section", "Checklist",        "checklist_section", 12),
    ("notes",             "Technician Notes", "textarea",          12),
    ("photos",            "Photos",           "photo",             12),
    ("signature",         "Signature",        "signature",         12),
]

# Mirrors ``POOL_CHECKLIST_DEFAULT`` at ``routers/service_reports.py:41``
# at Phase 7A seed time.  New items appended to that constant will NOT
# auto-flow here — Phase 7B+ owns the migration workflow.
_POOL_CHECKLIST_FIELDS: List[tuple] = [
    ("chk_skim_surface",       "Skim surface and empty baskets",          "checkbox", 12),
    ("chk_brush_walls",        "Brush walls and steps",                   "checkbox", 12),
    ("chk_vacuum_floor",       "Vacuum floor",                            "checkbox", 12),
    ("chk_pump_basket",        "Empty pump basket",                       "checkbox", 12),
    ("chk_backwash_filter",    "Clean/backwash filter as needed",         "checkbox", 12),
    ("chk_inspect_equipment",  "Inspect equipment (pump, heater, timer)", "checkbox", 12),
    ("chk_water_level",        "Check water level; top off if needed",    "checkbox", 12),
    ("chk_no_algae",           "Confirm no visible algae or debris",      "checkbox", 12),
    ("chk_skimmer_basket",     "Emptied skimmer basket",                  "checkbox", 12),
    ("chk_leaf_canister",      "Emptied leaf canister",                   "checkbox", 12),
    ("chk_betta_skimmer",      "Emptied Betta Skimmer",                   "checkbox", 12),
]

# Mirrors ``LANDSCAPE_CHECKLIST_DEFAULT`` at
# ``routers/service_reports.py:147``.
_LANDSCAPE_CHECKLIST_FIELDS: List[tuple] = [
    ("chk_weeds",             "Sprayed or Pulled Weeds", "checkbox", 12),
    ("chk_irrigation",        "Checked Irrigation",      "checkbox", 12),
    ("chk_trim_bushes",       "Trimmed Bushes",          "checkbox", 12),
    ("chk_mow",               "Mowed Grass",             "checkbox", 12),
    ("chk_edge",              "Edged Grass",             "checkbox", 12),
    ("chk_blow",              "Blow Property",           "checkbox", 12),
    ("chk_rake_rocks",        "Raked Rocks",             "checkbox", 12),
    ("chk_lock_gate",         "Locked Gate",             "checkbox", 12),
    ("chk_trim_trees",        "Trimmed Trees",           "checkbox", 12),
    ("chk_irrigation_repair", "Irrigation Repair",       "checkbox", 12),
]

# Mirrors ``GENERIC_CHECKLIST_DEFAULT`` at
# ``routers/service_reports.py:160``.
_GENERIC_CHECKLIST_FIELDS: List[tuple] = [
    ("chk_confirm_scope",   "Confirm scope with customer", "checkbox", 12),
    ("chk_perform_service", "Perform requested service",   "checkbox", 12),
    ("chk_clean_up",        "Clean up work area",          "checkbox", 12),
    ("chk_before_after",    "Take before/after photos",    "checkbox", 12),
    ("chk_followup",        "Log any follow-up needed",    "checkbox", 12),
]

# Estimate — totals row columns take 4 / 12 cols each so the full
# ``[subtotal | taxes | total]`` row sits on one grid line.
_ESTIMATE_FIELDS: List[tuple] = [
    ("header_customer",  "Customer Info Header",  "readonly_text",    12),
    ("line_items_table", "Line Items",            "line_items_table", 12),
    ("subtotal",         "Subtotal",              "currency",          4),
    ("taxes",            "Taxes",                 "currency",          4),
    ("total",            "Total Estimated Cost",  "currency",          4),
    ("notes",            "Notes",                 "textarea",         12),
    ("signature",        "Customer Signature",    "signature",        12),
]

_INVOICE_FIELDS: List[tuple] = [
    ("header_customer",  "Customer Info Header", "readonly_text",    12),
    ("line_items_table", "Line Items",           "line_items_table", 12),
    ("subtotal",         "Subtotal",             "currency",          4),
    ("taxes",            "Taxes",                "currency",          4),
    # Phase 7A — ``total_due`` is the ONLY field in any seed with
    # ``locked_reorder=True``.  Rationale: the invoice renderer places
    # the Total Due row at the bottom of the totals block on every
    # historical invoice and on QuickBooks exports.  Reordering it
    # would break printed-invoice parity with existing PDFs filed by
    # customers.  Every other field across all 8 form_types defaults
    # to ``locked_reorder=False``.
    ("total_due",        "Total Due",            "currency",          4),
    ("payment_status",   "Payment Status",       "readonly_text",    12),
]

# CAD editor overlay — PHASE 7A PLACEHOLDER SEED.
#
# The CAD editor at ``frontend/src/pages/.../cad-editor*`` is a canvas
# tool (shapes, icons, map backdrops, vertex drag, scale bar) and does
# NOT render a flat field list today — there is no "form" to reorder
# or restyle in the Phase 7A sense.  We seed a minimal placeholder so
# the enum is complete and GET always returns a shape.  Phase 7B/7C
# will either (a) wire these as the real editable overlay-settings
# strip, or (b) drop the ``cad_overlay`` form_type if the canvas path
# never grows a form surface.  See brief for the agreed placeholder.
_CAD_OVERLAY_FIELDS: List[tuple] = [
    ("overlay_bg",     "Overlay Background",  "cad_overlay_bg", 12),
    ("grid_opacity",   "Grid Opacity",        "slider",          6),
    ("snap_grid_size", "Snap Grid Size (px)", "number",          6),
]


_SEED_MAP: Dict[str, List[tuple]] = {
    "pool_service_report":      _POOL_SR_FIELDS,
    "landscape_service_report": _LANDSCAPE_SR_FIELDS,
    "job_checklist_pool":       _POOL_CHECKLIST_FIELDS,
    "job_checklist_landscape":  _LANDSCAPE_CHECKLIST_FIELDS,
    "job_checklist_generic":    _GENERIC_CHECKLIST_FIELDS,
    "estimate":                 _ESTIMATE_FIELDS,
    "invoice":                  _INVOICE_FIELDS,
    "cad_overlay":              _CAD_OVERLAY_FIELDS,
}

# Fields seeded with ``locked_reorder=True``.  Default False for
# every ``field_id`` not listed here.  See the ``total_due``
# rationale above the ``_INVOICE_FIELDS`` block.
_LOCKED_FIELD_IDS: Dict[str, set] = {
    "invoice": {"total_due"},
}


def build_default_form_template(form_type: str) -> Dict[str, Any]:
    """Return the seed field list for ``form_type``.

    The caller supplies tenant / version / timestamp metadata around
    the returned ``{"fields": [...]}`` payload.  Public helper so the
    editor UI (Phase 7B) can preview a reset-to-default without
    hitting the DB.
    """
    if form_type not in FORM_TYPES:
        raise ValueError(f"unknown form_type: {form_type!r}")
    locked = _LOCKED_FIELD_IDS.get(form_type, set())
    seed = _SEED_MAP[form_type]
    fields: List[Dict[str, Any]] = []
    for order, (field_id, label, field_type, width_cols) in enumerate(seed):
        fields.append({
            "field_id":       field_id,
            "label":          label,
            "field_type":     field_type,
            "order":          order,
            "locked_reorder": field_id in locked,
            "style":          _col_style(width_cols),
        })
    return {"fields": fields}


# ──────────────────────────────────────────────────────────────────
#  Role gates
# ──────────────────────────────────────────────────────────────────

_READ_ROLES   = {"admin", "super_admin", "owner", "manager"}
_MUTATE_ROLES = {"admin", "super_admin", "owner"}


def _read_or_403(user: dict) -> dict:
    if (user or {}).get("role") not in _READ_ROLES:
        raise HTTPException(403, "Admin, owner, or manager required")
    return user


def _mutate_or_403(user: dict) -> dict:
    if (user or {}).get("role") not in _MUTATE_ROLES:
        raise HTTPException(403, "Admin or owner required")
    return user


def _tenant_or_400(user: dict) -> str:
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "No tenant on token")
    return tid


# ──────────────────────────────────────────────────────────────────
#  DB helpers
# ──────────────────────────────────────────────────────────────────

async def _get_current(tenant_id: str, form_type: str) -> Optional[dict]:
    return await db.form_templates.find_one(
        {"tenant_id": tenant_id, "form_type": form_type, "is_current": True},
        {"_id": 0},
    )


async def _max_version(tenant_id: str, form_type: str) -> int:
    cursor = db.form_templates.find(
        {"tenant_id": tenant_id, "form_type": form_type},
        {"_id": 0, "version": 1},
    ).sort("version", -1).limit(1)
    async for doc in cursor:
        return int(doc.get("version") or 0)
    return 0


async def _ensure_seed(tenant_id: str, form_type: str, user_id: str) -> dict:
    """Lazy-init: return the current doc if it exists, else insert v1
    from ``build_default_form_template`` and return it."""
    cur = await _get_current(tenant_id, form_type)
    if cur:
        return cur
    body = build_default_form_template(form_type)
    doc = {
        "id":         new_id(),
        "tenant_id":  tenant_id,
        "form_type":  form_type,
        "version":    1,
        "is_current": True,
        "updated_by": user_id or "",
        "updated_at": now_iso(),
        "fields":     body["fields"],
    }
    await db.form_templates.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ──────────────────────────────────────────────────────────────────
#  Validation (PUT)
# ──────────────────────────────────────────────────────────────────

def _validate_style(idx: int, style: Dict[str, Any]) -> None:
    if not isinstance(style, dict):
        raise HTTPException(400, f"fields[{idx}].style must be an object")
    for key in ("bg_color", "text_color", "border_color"):
        val = style.get(key)
        if not isinstance(val, str) or not HEX_RE.match(val):
            raise HTTPException(400, f"fields[{idx}].style.{key} must be #RRGGBB")
    width_cols = style.get("width_cols")
    if (not isinstance(width_cols, int) or isinstance(width_cols, bool)
            or width_cols < 1 or width_cols > 12):
        raise HTTPException(400, f"fields[{idx}].style.width_cols must be an integer in 1..12")
    padding_y = style.get("padding_y")
    if (not isinstance(padding_y, int) or isinstance(padding_y, bool)
            or padding_y < 1 or padding_y > 8):
        raise HTTPException(400, f"fields[{idx}].style.padding_y must be an integer in 1..8")
    bg_alpha = style.get("bg_alpha")
    if isinstance(bg_alpha, bool) or not isinstance(bg_alpha, (int, float)):
        raise HTTPException(400, f"fields[{idx}].style.bg_alpha must be a number in 0.0..1.0")
    if bg_alpha < 0.0 or bg_alpha > 1.0:
        raise HTTPException(400, f"fields[{idx}].style.bg_alpha must be between 0.0 and 1.0")


def _validate_fields_against_seed(form_type: str, incoming: List[Dict[str, Any]]) -> None:
    """Phase 7A — reorder-and-restyle only.

    Enforces every rule from the brief:
      * no duplicate ``field_id``
      * every incoming ``field_id`` must be present in the seed
        (adding fields is out of scope)
      * every seed ``field_id`` must be present in the payload
        (removing fields is out of scope)
      * style payload must be well-formed and bounded
    """
    seed_fields = build_default_form_template(form_type)["fields"]
    seed_ids = {f["field_id"] for f in seed_fields}
    seen_ids: set = set()
    for idx, f in enumerate(incoming):
        if not isinstance(f, dict):
            raise HTTPException(400, f"fields[{idx}] must be an object")
        fid = f.get("field_id")
        if not fid or not isinstance(fid, str):
            raise HTTPException(400, f"fields[{idx}].field_id missing or non-string")
        if fid in seen_ids:
            raise HTTPException(400, f"duplicate field_id: {fid!r}")
        seen_ids.add(fid)
        if fid not in seed_ids:
            raise HTTPException(
                400,
                f"unknown field_id {fid!r} — Phase 7A is reorder+restyle only; "
                "adding new fields is out of scope",
            )
        _validate_style(idx, f.get("style") or {})
    missing = seed_ids - seen_ids
    if missing:
        raise HTTPException(
            400,
            f"missing field_id(s) {sorted(missing)!r} — Phase 7A is reorder+restyle only; "
            "removing fields is out of scope",
        )


# ──────────────────────────────────────────────────────────────────
#  Request body
# ──────────────────────────────────────────────────────────────────

class FormTemplatePut(BaseModel):
    fields: List[Dict[str, Any]]


# ──────────────────────────────────────────────────────────────────
#  Endpoints
# ──────────────────────────────────────────────────────────────────

@router.get("/form-templates", operation_id="formTemplates.listCurrent")
async def list_current_templates(user: dict = Depends(get_current_user)):
    _read_or_403(user)
    tenant_id = _tenant_or_400(user)
    out: Dict[str, dict] = {}
    for ft in FORM_TYPES:
        out[ft] = await _ensure_seed(tenant_id, ft, user.get("id") or "")
    return {"templates": out}


@router.get(
    "/form-templates/{form_type}",
    operation_id="formTemplates.getCurrent",
)
async def get_template(
    form_type: str,
    user: dict = Depends(get_current_user),
):
    _read_or_403(user)
    if form_type not in FORM_TYPES:
        raise HTTPException(404, "Unknown form_type")
    tenant_id = _tenant_or_400(user)
    return await _ensure_seed(tenant_id, form_type, user.get("id") or "")


@router.get(
    "/form-templates/{form_type}/versions",
    operation_id="formTemplates.listVersions",
)
async def list_versions(
    form_type: str,
    user: dict = Depends(get_current_user),
):
    # Version history is admin / super_admin / owner only — manager
    # has read-the-current-template access but NOT the full timeline.
    _mutate_or_403(user)
    if form_type not in FORM_TYPES:
        raise HTTPException(404, "Unknown form_type")
    tenant_id = _tenant_or_400(user)
    # Lazy-init so a never-opened form_type returns ``[v1]`` not ``[]``.
    await _ensure_seed(tenant_id, form_type, user.get("id") or "")
    rows: List[dict] = []
    cursor = db.form_templates.find(
        {"tenant_id": tenant_id, "form_type": form_type},
        {"_id": 0},
    ).sort("version", -1)
    async for doc in cursor:
        rows.append(doc)
    return {"versions": rows}


@router.put(
    "/form-templates/{form_type}",
    operation_id="formTemplates.put",
)
async def put_template(
    form_type: str,
    body: FormTemplatePut,
    user: dict = Depends(get_current_user),
):
    _mutate_or_403(user)
    if form_type not in FORM_TYPES:
        raise HTTPException(404, "Unknown form_type")
    tenant_id = _tenant_or_400(user)
    # Ensure v1 exists first so the version bump is monotonic.
    await _ensure_seed(tenant_id, form_type, user.get("id") or "")
    _validate_fields_against_seed(form_type, body.fields)
    await db.form_templates.update_many(
        {"tenant_id": tenant_id, "form_type": form_type, "is_current": True},
        {"$set": {"is_current": False}},
    )
    next_version = (await _max_version(tenant_id, form_type)) + 1
    doc = {
        "id":         new_id(),
        "tenant_id":  tenant_id,
        "form_type":  form_type,
        "version":    next_version,
        "is_current": True,
        "updated_by": user.get("id") or "",
        "updated_at": now_iso(),
        "fields":     body.fields,
    }
    await db.form_templates.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.post(
    "/form-templates/{form_type}/revert/{version}",
    operation_id="formTemplates.revert",
)
async def revert_template(
    form_type: str,
    version: int,
    user: dict = Depends(get_current_user),
):
    _mutate_or_403(user)
    if form_type not in FORM_TYPES:
        raise HTTPException(404, "Unknown form_type")
    tenant_id = _tenant_or_400(user)
    target = await db.form_templates.find_one(
        {"tenant_id": tenant_id, "form_type": form_type, "version": version},
        {"_id": 0},
    )
    if not target:
        raise HTTPException(404, f"Version {version} not found")
    await db.form_templates.update_many(
        {"tenant_id": tenant_id, "form_type": form_type, "is_current": True},
        {"$set": {"is_current": False}},
    )
    now = now_iso()
    actor = user.get("id") or ""
    await db.form_templates.update_one(
        {"tenant_id": tenant_id, "form_type": form_type, "version": version},
        {"$set": {"is_current": True, "updated_at": now, "updated_by": actor}},
    )
    target.update({"is_current": True, "updated_at": now, "updated_by": actor})
    return target
