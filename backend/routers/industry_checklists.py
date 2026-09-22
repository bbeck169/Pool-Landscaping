"""Phase MI1 · Feb 2026 — Multi-industry checklist templates.

Ships six new industry-agnostic checklist templates (Landscaping,
HVAC, Pest Control, Cleaning, Solar, Handyman) alongside the
existing Pool default. Pool behaviour is untouched — the legacy
Pool constants in ``routers/service_reports.py`` (``POOL_CHECKLIST_DEFAULT``),
``routers/jobs.py`` (``POOL_CHECKLIST``), ``routers/document_generators.py``
(``CANONICAL_POOL_CHECKLIST``), and ``routers/checklists.py``
(``DEFAULT_POOL_ITEMS``) are preserved for legacy callers/tests.

Data model
==========
* ``industry_checklist_templates`` — tenant-agnostic seed defaults.
* ``tenant_checklist_overrides`` — per-tenant customization.

Resolution
==========
``get_industry_checklist(tenant_id, industry)`` returns the tenant
override when present, otherwise the tenant-agnostic default.

Gating
======
``assert_required_items_present(industry, checked_keys, resolved)``
raises HTTPException(400) naming the first missing required item.
Wired into ``submit_service_report`` for the six new industries;
Pool jobs continue to use the chemistry gate unchanged.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user, new_id, now_iso, require_admin

router = APIRouter()


# ─── Canonical industry slugs ────────────────────────────────────────
INDUSTRY_SLUGS = (
    # ── Phase MI1 · Feb 2026 ── original 7 ─────────────────────────
    "pool", "landscaping", "hvac", "pest_control",
    "cleaning", "solar", "handyman",
    # ── Phase D1 · Feb 2026 ── +16 = 23 total ──────────────────────
    "plumbing", "electrical", "roofing", "painting",
    "garage_door", "appliance_repair", "locksmith",
    "chimney_sweep", "gutter", "window_cleaning",
    "carpet_cleaning", "pressure_washing", "tree_service",
    "snow_removal", "fencing", "irrigation",
)


# ─── Tenant-agnostic defaults ────────────────────────────────────────
# Each item: ``{key, label, required, group?}``. Original wording —
# generic to any tenant in the industry. Do NOT copy verbatim from
# any competitor checklist.
DEFAULT_TEMPLATES: Dict[str, List[Dict[str, Any]]] = {
    "pool": [
        # Mirrors ``routers/checklists.DEFAULT_POOL_ITEMS`` so the
        # unified endpoint returns the same Pool defaults every other
        # surface has been reading for a year.
        {"key": "skimmed_pool",           "label": "Skimmed Pool",              "required": True},
        {"key": "brush_pool",             "label": "Brush Pool",                "required": True},
        {"key": "checked_skimmer_basket", "label": "Checked Skimmer Basket",    "required": True},
        {"key": "checked_pump_basket",    "label": "Checked Pump Basket",       "required": True},
        {"key": "tested_chemicals",       "label": "Tested Chemicals",          "required": True},
        {"key": "checked_equipment",      "label": "Checked Equipment",         "required": True},
        {"key": "secured_all_gates",      "label": "Secured all Gates",         "required": True},
        {"key": "emptied_skimmer_basket", "label": "Emptied skimmer basket",    "required": False},
        {"key": "emptied_leaf_canister",  "label": "Emptied leaf canister",     "required": False},
        {"key": "emptied_betta_skimmer",  "label": "Emptied Betta Skimmer",     "required": False},
    ],
    "landscaping": [
        # P29 · Feb-2026 — required=False so landscape jobs close with empty
        # checklist; techs opt in per site. Pool template + all other
        # industries UNTOUCHED. Corresponding stored template + tenant
        # override docs are re-seeded / cleared by
        # ``backend/migrations/p29_clear_landscape_required_overrides.py``
        # (wired into the P21 structural boot block).
        {"key": "mowed_lawn_areas",         "label": "Mowed lawn areas",                    "required": False},
        {"key": "edged_walkways_driveways", "label": "Edged walkways and driveways",        "required": False},
        {"key": "trimmed_shrubs_hedges",    "label": "Trimmed shrubs and hedges",           "required": False},
        {"key": "blew_off_hardscape",       "label": "Blew off hardscape surfaces",         "required": False},
        {"key": "removed_weeds_from_beds",  "label": "Removed weeds from beds",             "required": False},
        {"key": "cleared_debris",           "label": "Cleared debris from work area",       "required": False},
        {"key": "inspected_irrigation",     "label": "Inspected irrigation heads",          "required": False},
        {"key": "bagged_removed_clippings", "label": "Bagged and removed clippings",        "required": False},
        {"key": "applied_fertilizer",       "label": "Applied fertilizer or treatment",     "required": False},
    ],
    "hvac": [
        {"key": "replaced_air_filter",       "label": "Replaced air filter",                "required": False},
        {"key": "checked_thermostat",        "label": "Checked thermostat calibration",     "required": False},
        {"key": "inspected_condensate_drain","label": "Inspected condensate drain line",    "required": False},
        {"key": "cleaned_condenser_coils",   "label": "Cleaned condenser coils",            "required": False},
        {"key": "measured_refrigerant",      "label": "Measured refrigerant pressure",      "required": False},
        {"key": "checked_electrical",        "label": "Checked electrical connections",     "required": False},
        {"key": "verified_airflow",          "label": "Verified system airflow",            "required": False},
        {"key": "tested_startup_shutdown",   "label": "Tested startup and shutdown cycle",  "required": False},
        {"key": "recorded_temp_differential","label": "Recorded temperature differential",  "required": False},
    ],
    "pest_control": [
        {"key": "treated_exterior_perimeter","label": "Treated exterior perimeter",         "required": False},
        {"key": "applied_interior_treatment","label": "Applied interior treatment where accessible", "required": False},
        {"key": "inspected_bait_stations",   "label": "Inspected bait stations",            "required": False},
        {"key": "removed_spider_webs",       "label": "Removed accessible spider webs",     "required": False},
        {"key": "identified_entry_points",   "label": "Identified entry points",            "required": False},
        {"key": "documented_pest_activity",  "label": "Documented pest activity",           "required": False},
        {"key": "applied_granular_soil",     "label": "Applied granular treatment to soil", "required": False},
        {"key": "placed_monitoring_devices", "label": "Placed monitoring devices",          "required": False},
        # Phase D1 · Feb 2026 — legally-critical additions. Most
        # states require the applicator to log EPA reg # + amount
        # for each product AND to notify the customer of the
        # re-entry interval before leaving the site.
        {"key": "documented_products_epa",   "label": "Products applied documented (EPA reg # + amount)", "required": False},
        {"key": "informed_reentry_time",     "label": "Client informed of re-entry time",   "required": False},
    ],
    "cleaning": [
        {"key": "high_dusted_surfaces",      "label": "High-dusted surfaces",               "required": False},
        {"key": "wiped_countertops_surfaces","label": "Wiped down countertops and surfaces","required": False},
        {"key": "vacuumed_mopped_floors",    "label": "Vacuumed and mopped floors",         "required": False},
        {"key": "cleaned_restrooms",         "label": "Cleaned restrooms",                  "required": False},
        {"key": "emptied_trash_bins",        "label": "Emptied trash bins",                 "required": False},
        {"key": "restocked_supplies",        "label": "Restocked supplies",                 "required": False},
        {"key": "cleaned_windows_glass",     "label": "Cleaned interior windows and glass", "required": False},
        {"key": "deodorized_common_areas",   "label": "Deodorized common areas",            "required": False},
    ],
    "solar": [
        {"key": "inspected_panel_condition", "label": "Inspected panel physical condition", "required": False},
        {"key": "verified_inverter_status",  "label": "Verified inverter status",           "required": False},
        {"key": "recorded_system_output",    "label": "Recorded system output",             "required": False},
        {"key": "cleaned_panel_surfaces",    "label": "Cleaned panel surfaces if needed",   "required": False},
        {"key": "checked_wiring_connections","label": "Checked wiring and connections",     "required": False},
        {"key": "inspected_mounting",        "label": "Inspected mounting hardware",        "required": False},
        {"key": "reviewed_monitoring_portal","label": "Reviewed monitoring app / portal",   "required": False},
        {"key": "documented_anomalies",      "label": "Documented anomalies",               "required": False},
    ],
    "handyman": [
        {"key": "confirmed_scope",           "label": "Confirmed scope with customer",      "required": False},
        {"key": "verified_tools_materials",  "label": "Verified tools and materials on site","required": False},
        {"key": "completed_agreed_work",     "label": "Completed agreed work",              "required": False},
        {"key": "post_work_safety_walk",     "label": "Performed post-work safety walk",    "required": False},
        {"key": "cleaned_work_area",         "label": "Cleaned work area",                  "required": False},
        {"key": "reviewed_with_customer",    "label": "Reviewed completed work with customer","required": False},
        {"key": "documented_before_after",   "label": "Documented before/after photos",     "required": False},
    ],
    # ═══════════════════════════════════════════════════════════════
    # Phase D1 · Feb 2026 — 16 new industry defaults.
    # Every template stays 5-7 rows; required=True is reserved for
    # rows that carry safety / legal / warranty exposure so admins
    # can override the visual list without accidentally softening
    # a compliance gate.
    # ═══════════════════════════════════════════════════════════════
    "plumbing": [
        {"key": "shutoff_valve_tested",     "label": "Shut-off valve tested",              "required": False},
        {"key": "water_pressure_checked",   "label": "Water pressure checked (PSI)",       "required": False},
        {"key": "fixtures_inspected_leaks", "label": "Fixtures inspected for leaks",       "required": False},
        {"key": "drain_flow_verified",      "label": "Drain flow verified",                "required": False},
        {"key": "water_heater_inspected",   "label": "Water heater inspected",             "required": False},
        {"key": "parts_materials_documented","label": "Parts / materials used documented", "required": False},
    ],
    "electrical": [
        {"key": "panel_labeled_accessible", "label": "Panel labeled & accessible",         "required": False},
        {"key": "voltage_readings_recorded","label": "Voltage readings recorded",          "required": False},
        {"key": "gfci_afci_tested",         "label": "GFCI / AFCI outlets tested",         "required": False},
        {"key": "wiring_inspected_damage",  "label": "Wiring inspected for damage",        "required": False},
        {"key": "grounding_verified",       "label": "Grounding verified",                 "required": False},
        {"key": "circuits_load_tested",     "label": "Circuits load-tested",               "required": False},
        {"key": "client_walkthrough_done",  "label": "Client walk-through completed",      "required": False},
    ],
    "roofing": [
        {"key": "roof_surface_inspection",  "label": "Roof surface inspection",            "required": False},
        {"key": "flashings_penetrations",   "label": "Flashings & penetrations checked",   "required": False},
        {"key": "gutters_drainage_clear",   "label": "Gutters / drainage clear",           "required": False},
        {"key": "attic_ventilation",        "label": "Attic ventilation verified",         "required": False},
        {"key": "debris_removed",           "label": "Debris removed",                     "required": False},
        {"key": "trouble_spots_photos",     "label": "Photos of trouble spots captured",   "required": False},
        {"key": "warranty_items_noted",     "label": "Warranty items noted",               "required": False},
    ],
    "painting": [
        {"key": "surface_prep_completed",   "label": "Surface prep completed",             "required": False},
        {"key": "primer_applied",           "label": "Primer applied where needed",        "required": False},
        {"key": "coat_count_documented",    "label": "Coat count documented",              "required": False},
        {"key": "trim_edging_completed",    "label": "Trim / edging completed",            "required": False},
        {"key": "cleanup_completed",        "label": "Cleanup completed",                  "required": False},
        {"key": "client_walkthrough_signoff","label": "Client walk-through & sign-off",    "required": False},
    ],
    "garage_door": [
        {"key": "springs_cables_inspected", "label": "Springs & cables inspected",         "required": False},
        {"key": "opener_force_tested",      "label": "Opener force setting tested",        "required": False},
        {"key": "safety_sensors_aligned",   "label": "Safety sensors aligned & tested",    "required": False},
        {"key": "rollers_hinges_lubed",     "label": "Rollers & hinges lubed",             "required": False},
        {"key": "weather_seal_condition",   "label": "Weather seal condition",             "required": False},
        {"key": "manual_release_tested",    "label": "Manual release tested",              "required": False},
    ],
    "appliance_repair": [
        {"key": "model_serial_recorded",    "label": "Model / serial recorded",            "required": False},
        {"key": "symptom_reproduced",       "label": "Symptom reproduced",                 "required": False},
        {"key": "parts_replaced_documented","label": "Parts replaced documented",          "required": False},
        {"key": "voltage_continuity",       "label": "Voltage / continuity readings",      "required": False},
        {"key": "function_tested_postrepair","label": "Function tested post-repair",       "required": False},
        {"key": "client_demoed_operation",  "label": "Client demoed operation",            "required": False},
    ],
    "locksmith": [
        {"key": "lock_type_make_recorded",  "label": "Lock type & make recorded",          "required": False},
        {"key": "keys_cut_rekeyed_count",   "label": "Keys cut / rekeyed count",           "required": False},
        {"key": "deadbolt_verified",        "label": "Deadbolt operation verified",        "required": False},
        {"key": "master_sub_keys_docs",     "label": "Master / sub keys documented if applicable", "required": False},
        {"key": "client_id_verified",       "label": "Client ID verification completed",   "required": False},
    ],
    "chimney_sweep": [
        {"key": "firebox_smoke_chamber",    "label": "Firebox & smoke chamber inspected",  "required": False},
        {"key": "creosote_level_noted",     "label": "Creosote level noted (0/1/2/3)",     "required": False},
        {"key": "cap_crown_inspected",      "label": "Cap & crown inspected",              "required": False},
        {"key": "damper_operation",         "label": "Damper operation tested",            "required": False},
        {"key": "ash_debris_removed",       "label": "Ash / debris removed",               "required": False},
        {"key": "draft_test_performed",     "label": "Draft test performed",               "required": False},
    ],
    "gutter": [
        {"key": "debris_cleared_runs",      "label": "Debris cleared from runs",           "required": False},
        {"key": "downspouts_flushed",       "label": "Downspouts flushed",                 "required": False},
        {"key": "flow_verified_outlets",    "label": "Flow verified at outlets",           "required": False},
        {"key": "hangers_brackets",         "label": "Hangers / brackets inspected",       "required": False},
        {"key": "fascia_condition",         "label": "Fascia condition noted",             "required": False},
        {"key": "screens_guards_checked",   "label": "Screens / guards checked if installed", "required": False},
    ],
    "window_cleaning": [
        {"key": "exterior_glass_cleaned",   "label": "Exterior glass cleaned",             "required": False},
        {"key": "interior_glass_cleaned",   "label": "Interior glass cleaned",             "required": False},
        {"key": "screens_removed_cleaned",  "label": "Screens removed & cleaned",          "required": False},
        {"key": "sills_tracks_wiped",       "label": "Sills & tracks wiped",               "required": False},
        {"key": "cracks_seal_issues",       "label": "Cracks / seal issues noted",         "required": False},
        {"key": "streak_spot_recheck",      "label": "Streak / spot re-check completed",   "required": False},
    ],
    "carpet_cleaning": [
        {"key": "pretreatment_applied",     "label": "Pre-treatment applied",              "required": False},
        {"key": "hot_water_extraction",     "label": "Hot-water extraction completed",     "required": False},
        {"key": "spot_stain_treatments",    "label": "Spot / stain treatments logged",     "required": False},
        {"key": "furniture_moved_restored", "label": "Furniture moved / restored",         "required": False},
        {"key": "drying_time_communicated", "label": "Drying time communicated to client", "required": False},
        {"key": "damage_noted_preservice",  "label": "Damage noted pre-service",           "required": False},
    ],
    "pressure_washing": [
        {"key": "psi_setting_recorded",     "label": "PSI setting recorded",               "required": False},
        {"key": "detergent_documented",     "label": "Detergent / chemicals used documented", "required": False},
        {"key": "surface_types_cleaned",    "label": "Surface types cleaned",              "required": False},
        {"key": "runoff_drainage_plan",     "label": "Runoff / drainage plan followed",    "required": False},
        {"key": "damage_noted_preservice_pw","label": "Damage noted pre-service",          "required": False},
        {"key": "final_rinse_completed",    "label": "Final rinse completed",              "required": False},
    ],
    "tree_service": [
        {"key": "trees_serviced_species",   "label": "Trees serviced (species / count)",   "required": False},
        {"key": "work_performed_type",      "label": "Work performed (trim / removal / stump)", "required": False},
        {"key": "debris_hauled_chipped",    "label": "Debris hauled or chipped",           "required": False},
        {"key": "drop_zone_verified",       "label": "Property protection / drop-zone verified", "required": False},
        {"key": "overhead_line_clearance",  "label": "Overhead line clearance verified",   "required": False},
        {"key": "client_walkthrough_tree",  "label": "Client walk-through",                "required": False},
    ],
    "snow_removal": [
        {"key": "areas_cleared_documented", "label": "Areas cleared documented",           "required": False},
        {"key": "deicer_applied",           "label": "De-icer applied (product & amount)", "required": False},
        {"key": "site_conditions_arrival",  "label": "Site conditions on arrival",         "required": False},
        {"key": "site_conditions_departure","label": "Site conditions on departure",       "required": False},
        {"key": "photos_property_damage",   "label": "Photos taken (required if property damage)", "required": False},
        {"key": "hazards_noted",            "label": "Hazards noted",                      "required": False},
    ],
    "fencing": [
        {"key": "posts_set_plumb",          "label": "Posts set / verified plumb",         "required": False},
        {"key": "rails_pickets",            "label": "Rails & pickets installed / repaired","required": False},
        {"key": "gate_operation_tested",    "label": "Gate operation tested",              "required": False},
        {"key": "hardware_installed",       "label": "Hardware installed",                 "required": False},
        {"key": "debris_cleaned_fence",     "label": "Debris cleaned up",                  "required": False},
        {"key": "client_walkthrough_fence", "label": "Client walk-through & sign-off",     "required": False},
    ],
    "irrigation": [
        {"key": "zones_cycled_tested",      "label": "All zones cycled & tested",          "required": False},
        {"key": "heads_adjusted_aligned",   "label": "Heads adjusted & aligned",           "required": False},
        {"key": "leaks_breaks_noted",       "label": "Leaks / breaks noted",               "required": False},
        {"key": "controller_programmed",    "label": "Controller programmed & documented", "required": False},
        {"key": "backflow_tested",          "label": "Backflow tested (required if applicable)", "required": False},
        {"key": "winterize_step_logged",    "label": "Winterize / de-winterize step logged","required": False},
    ],
}


# ─── Public helpers ──────────────────────────────────────────────────
def _normalize_industry(v: Optional[str]) -> str:
    if not v:
        raise HTTPException(400, "industry is required")
    s = str(v).strip().lower()
    # Accept a couple of common aliases so callers can pass the
    # frontend-friendly plural / hyphenated forms.
    aliases = {
        "pools": "pool",
        "pest-control": "pest_control",
        "pestcontrol": "pest_control",
    }
    s = aliases.get(s, s)
    if s not in INDUSTRY_SLUGS:
        raise HTTPException(
            400,
            f"industry must be one of {sorted(INDUSTRY_SLUGS)} (got {v!r})",
        )
    return s


def _sanitize_items(items: Iterable[Any]) -> List[Dict[str, Any]]:
    """Coerce a caller-supplied items list into the canonical shape.
    Drops malformed rows silently — the endpoint layer already gates
    on ``items`` being a non-empty list."""
    out: List[Dict[str, Any]] = []
    seen_keys: set = set()
    for row in items or ():
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        label = str(row.get("label") or "").strip()
        if not key or not label:
            continue
        if key in seen_keys:
            continue
        seen_keys.add(key)
        item: Dict[str, Any] = {
            "key": key,
            "label": label[:120],
            "required": bool(row.get("required") or False),
        }
        group = row.get("group")
        if group:
            item["group"] = str(group).strip()[:60]
        out.append(item)
    return out


async def get_industry_checklist(tenant_id: str,
                                    industry: str) -> Dict[str, Any]:
    """Resolve the checklist for ``(tenant_id, industry)``.

    Return shape:
        {"industry": str, "items": [...], "source": "override"|"default"|"missing"}
    """
    ind = _normalize_industry(industry)
    override = await db.tenant_checklist_overrides.find_one(
        {"tenant_id": tenant_id, "industry": ind}, {"_id": 0},
    )
    if override and override.get("items"):
        return {"industry": ind, "items": override["items"],
                 "source": "override", "updated_at": override.get("updated_at")}
    default_doc = await db.industry_checklist_templates.find_one(
        {"industry": ind, "is_default": True}, {"_id": 0},
    )
    if default_doc and default_doc.get("items"):
        return {"industry": ind, "items": default_doc["items"],
                 "source": "default", "updated_at": default_doc.get("updated_at")}
    # In-memory fallback if the seeder hasn't run yet.
    if ind in DEFAULT_TEMPLATES:
        return {"industry": ind, "items": DEFAULT_TEMPLATES[ind],
                 "source": "default"}
    return {"industry": ind, "items": [], "source": "missing"}


def assert_required_items_present(industry: str,
                                     checked_keys: Iterable[str],
                                     resolved_template: Dict[str, Any]) -> None:
    """Raise HTTPException(400) with the first missing required item.

    ``checked_keys`` — iterable of keys/labels the submitting client
    already marked ``done``. Both are accepted so legacy callers that
    persist checklist entries as ``{"label": ..., "done": True}`` (no
    ``key``) still pass. Pool never routes here — the chemistry gate
    handles pool submissions.
    """
    ind = str(industry or "").lower()
    if ind == "pool":
        # Guard: pool jobs use the chemistry gate; don't gate on
        # required checkbox completion here.
        return
    checked = {str(k or "").strip() for k in (checked_keys or ()) if k}
    checked_lower = {k.lower() for k in checked}
    items = (resolved_template or {}).get("items") or []
    for it in items:
        if not it.get("required"):
            continue
        key = str(it.get("key") or "").strip()
        label = str(it.get("label") or "").strip()
        # Match on key OR label — cover both the new schema and the
        # legacy "label + done" persistence shape.
        if key.lower() in checked_lower or label.lower() in checked_lower:
            continue
        raise HTTPException(
            400,
            f"Required checklist item not completed: {label or key}",
        )


def derive_industry_for_job(job: Optional[Dict[str, Any]],
                                tenant: Optional[Dict[str, Any]]) -> str:
    """Best-effort mapping from a job → one of :data:`INDUSTRY_SLUGS`.

    Priority chain (loosest → strictest wins on tie):

    1. Explicit ``job.checklist_industry`` (Phase D3 · Feb 2026 —
       front-end back-compat alias) when present + valid.
    2. Explicit ``job.industry`` when present + valid.
    3. Keyword match on ``service_type`` / ``job_type`` / ``title``.
    4. Tenant primary industry (``tenant.industries[0]`` or
       ``tenant.industry``) when it maps to a known slug.
    5. Fallback to ``"pool"`` — matches the historical checklist
       default so existing Pool tenants keep working when nobody
       has classified their jobs yet.

    An INVALID ``checklist_industry`` (non-canonical) does NOT error
    — the function falls through to ``industry`` (and onwards) so
    stale clients emitting a bad override key still land on a
    sensible slug.
    """
    if isinstance(job, dict):
        # Phase D3 · Feb 2026 — ``checklist_industry`` wins over
        # ``industry`` when both are present + valid, matching the
        # web deriver in ``frontend/src/lib/deriveIndustry.js``.
        override = str(job.get("checklist_industry") or "").strip().lower()
        if override in INDUSTRY_SLUGS:
            return override
        explicit = str(job.get("industry") or "").strip().lower()
        if explicit in INDUSTRY_SLUGS:
            return explicit
        hay = " ".join(
            str(job.get(k) or "") for k in ("service_type", "job_type", "title")
        ).lower()
        keyword_map = [
            # ═══════════════════════════════════════════════════════
            # Phase D1 · Feb 2026 — 16 new industries.
            # Ordering rule: compound keywords must match BEFORE
            # their component words. e.g. "Window Cleaning" must
            # resolve to ``window_cleaning``, NOT ``cleaning``.
            # ═══════════════════════════════════════════════════════
            # Compound / multi-word matches — narrowest first.
            ("garage door", "garage_door"), ("garage-door", "garage_door"),
            ("chimney", "chimney_sweep"),
            ("window clean", "window_cleaning"), ("window wash", "window_cleaning"),
            ("carpet", "carpet_cleaning"),
            ("pressure wash", "pressure_washing"), ("power wash", "pressure_washing"),
            ("tree", "tree_service"),
            ("snow", "snow_removal"),
            # Original Phase-MI1 industries — order preserved.
            ("solar", "solar"), ("pv panel", "solar"), ("photovoltaic", "solar"),
            ("hvac", "hvac"), ("heating", "hvac"), ("cooling", "hvac"),
            ("air conditioning", "hvac"),
            ("pest", "pest_control"), ("exterminator", "pest_control"),
            ("handyman", "handyman"),
            ("landscape", "landscaping"), ("landscap", "landscaping"),
            ("mowing", "landscaping"), ("lawn", "landscaping"),
            ("pool", "pool"), ("chem", "pool"),
            # Phase D1 · single-keyword new industries. Placed AFTER
            # the pool / solar / cleaning-compound matches so an
            # "electrical solar panel install" still resolves to
            # ``solar`` (electrical is the trade, solar is the product).
            ("appliance", "appliance_repair"),
            ("locksmith", "locksmith"), ("rekey", "locksmith"),
            ("plumb", "plumbing"),
            ("electric", "electrical"),
            ("roof", "roofing"),
            ("paint", "painting"),
            ("gutter", "gutter"),
            ("fenc", "fencing"),
            ("irrigat", "irrigation"), ("sprinkler", "irrigation"),
            # Broader matches last so they don't preempt an industry
            # keyword earlier in the string.
            ("clean", "cleaning"), ("janitorial", "cleaning"),
            ("housekeep", "cleaning"),
            ("repair", "handyman"),
        ]
        for needle, slug in keyword_map:
            if needle in hay:
                return slug
    if isinstance(tenant, dict):
        primary: Optional[str] = None
        inds = tenant.get("industries")
        if isinstance(inds, list) and inds:
            primary = str(inds[0]).strip().lower()
        elif tenant.get("industry"):
            primary = str(tenant["industry"]).strip().lower()
        # Aliases from ``services.industries.INDUSTRIES`` → local slugs.
        alias = {"pools": "pool"}
        primary = alias.get(primary or "", primary or "")
        if primary in INDUSTRY_SLUGS:
            return primary
    return "pool"


# ─── HTTP surface ────────────────────────────────────────────────────
_SUPPORTED_LOCALES = ("en", "es", "fr")


def resolve_row_label(row: Dict[str, Any], locale: str) -> str:
    """Phase D4 · Feb 2026 — return the localized label for a row.

    Fallback chain (loosest → strictest):
        label_i18n[locale] → label_i18n["en"] → label → key
    Empty strings are treated as missing. Unknown locales collapse
    to ``en`` before the chain runs.
    """
    if not isinstance(row, dict):
        return ""
    loc = str(locale or "en").strip().lower()
    if loc not in _SUPPORTED_LOCALES:
        loc = "en"
    i18n = row.get("label_i18n") or {}
    if isinstance(i18n, dict):
        val = i18n.get(loc)
        if isinstance(val, str) and val.strip():
            return val
        # ``en`` intra-i18n fallback — used when a caller stored the
        # English translation inside ``label_i18n`` rather than the
        # authoritative ``label`` field.
        en_val = i18n.get("en")
        if isinstance(en_val, str) and en_val.strip():
            return en_val
    label = row.get("label")
    if isinstance(label, str) and label.strip():
        return label
    return str(row.get("key") or "")


def _parse_accept_language(header: Optional[str]) -> Optional[str]:
    """Return the first supported locale from an ``Accept-Language``
    header, or ``None`` when none match. Very lightweight — enough
    for our 3-locale surface."""
    if not header:
        return None
    for tok in header.split(","):
        code = tok.split(";", 1)[0].strip().lower()
        if not code:
            continue
        # Region-stripped match (``es-419`` → ``es``).
        base = code.split("-", 1)[0]
        if base in _SUPPORTED_LOCALES:
            return base
    return None


def _resolve_effective_locale(
    *, query_locale: Optional[str], user: Optional[Dict[str, Any]],
    request: Optional[Request],
) -> str:
    """Priority: query param → user record → Accept-Language → ``en``."""
    for candidate in (
        (query_locale or "").strip().lower(),
        (user or {}).get("locale") or "",
    ):
        c = str(candidate or "").strip().lower()
        if c in _SUPPORTED_LOCALES:
            return c
    if request is not None:
        hdr = _parse_accept_language(
            request.headers.get("accept-language")
            or request.headers.get("Accept-Language"),
        )
        if hdr:
            return hdr
    return "en"


def _localize_items(items: List[Dict[str, Any]], locale: str) -> List[Dict[str, Any]]:
    """Return a list of rows with ``label`` replaced by the localized
    string, ``label_en`` set to the authoritative English, and
    ``label_i18n_available`` populated with the locales that have a
    non-empty entry."""
    out: List[Dict[str, Any]] = []
    for row in items or ():
        if not isinstance(row, dict):
            continue
        localized = dict(row)
        english = str(row.get("label") or "").strip()
        i18n = row.get("label_i18n") or {}
        available = ["en"] if english else []
        if isinstance(i18n, dict):
            for code in _SUPPORTED_LOCALES:
                if code == "en":
                    continue
                v = i18n.get(code)
                if isinstance(v, str) and v.strip() and code not in available:
                    available.append(code)
        localized["label"] = resolve_row_label(row, locale)
        localized["label_en"] = english or localized["label"]
        localized["label_i18n_available"] = available
        out.append(localized)
    return out


@router.get("/checklists/industry/{industry}",
              operation_id="industryChecklists.get")
async def get_checklist_endpoint(
    industry: str,
    request: Request,
    locale: Optional[str] = Query(default=None,
                                     pattern="^[a-zA-Z-]{2,10}$"),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Any authed user can read the resolved template.

    Phase D4 · Feb 2026 — locale-aware rendering.
    Priority: ``?locale`` query → ``user.locale`` → ``Accept-Language``
    → ``en``. Every returned row carries ``label`` (localized),
    ``label_en`` (authoritative), and ``label_i18n_available`` (list of
    locales that ship a translation for the row).
    """
    body = await get_industry_checklist(tenant["id"], industry)
    eff = _resolve_effective_locale(
        query_locale=locale, user=user, request=request,
    )
    body["items"] = _localize_items(body.get("items") or [], eff)
    body["locale"] = eff
    return body


@router.put("/checklists/industry/{industry}",
              operation_id="industryChecklists.upsertOverride")
async def upsert_override_endpoint(
    industry: str,
    body: Dict[str, Any],
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Create OR update the tenant override for this industry. Admin
    and Super Admin only (``require_admin`` gate). Idempotent — the
    same payload can be re-PUT safely."""
    ind = _normalize_industry(industry)
    items = _sanitize_items((body or {}).get("items") or [])
    if not items:
        raise HTTPException(400, "items is empty")
    now = now_iso()
    existing = await db.tenant_checklist_overrides.find_one(
        {"tenant_id": tenant["id"], "industry": ind}, {"_id": 0, "id": 1},
    )
    if existing:
        await db.tenant_checklist_overrides.update_one(
            {"tenant_id": tenant["id"], "industry": ind},
            {"$set": {"items": items, "updated_at": now,
                       "updated_by": user.get("id")}},
        )
    else:
        await db.tenant_checklist_overrides.insert_one({
            "id": new_id(), "tenant_id": tenant["id"], "industry": ind,
            "items": items, "created_at": now, "updated_at": now,
            "created_by": user.get("id"),
        })
    try:
        await db.audit_log.insert_one({
            "id": new_id(), "tenant_id": tenant["id"],
            "actor_user_id": user.get("id"), "actor_email": user.get("email"),
            "action": "industry_checklist.override_upsert",
            "target_id": ind, "at": now,
        })
    except Exception as e:                                      # noqa: BLE001
        logger.warning(f"industry_checklist audit failed: {e}")
    return await get_industry_checklist(tenant["id"], ind)


@router.delete("/checklists/industry/{industry}",
                 operation_id="industryChecklists.clearOverride")
async def clear_override_endpoint(
    industry: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Clear the tenant override — subsequent GET returns the default."""
    ind = _normalize_industry(industry)
    res = await db.tenant_checklist_overrides.delete_one(
        {"tenant_id": tenant["id"], "industry": ind},
    )
    try:
        await db.audit_log.insert_one({
            "id": new_id(), "tenant_id": tenant["id"],
            "actor_user_id": user.get("id"), "actor_email": user.get("email"),
            "action": "industry_checklist.override_clear",
            "target_id": ind, "at": now_iso(),
            "deleted_count": res.deleted_count,
        })
    except Exception as e:                                      # noqa: BLE001
        logger.warning(f"industry_checklist audit failed: {e}")
    return await get_industry_checklist(tenant["id"], ind)


# ─── Boot-time seeder (idempotent) ───────────────────────────────────
async def seed_industry_checklist_templates() -> Dict[str, int]:
    """Insert one ``industry_checklist_templates`` row per canonical
    industry when a default doesn't already exist. Safe to call every
    boot — the second run inserts 0 rows.

    Returns ``{"inserted": N, "kept": M}`` for logging.
    """
    inserted = 0
    kept = 0
    for slug in INDUSTRY_SLUGS:
        existing = await db.industry_checklist_templates.find_one(
            {"industry": slug, "is_default": True},
            {"_id": 0, "id": 1},
        )
        if existing:
            kept += 1
            continue
        try:
            await db.industry_checklist_templates.insert_one({
                "id": new_id(),
                "industry": slug,
                "version": 1,
                "items": DEFAULT_TEMPLATES[slug],
                "is_default": True,
                "updated_at": now_iso(),
            })
            inserted += 1
        except Exception as e:                                  # noqa: BLE001
            logger.warning(
                f"[mi1] industry_checklist seed failed for {slug}: {e}"
            )
    logger.info(
        f"[mi1] industry_checklist_templates seed: "
        f"inserted={inserted} kept={kept}"
    )
    return {"inserted": inserted, "kept": kept}
