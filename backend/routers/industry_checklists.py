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

from fastapi import APIRouter, Depends, HTTPException

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user, new_id, now_iso, require_admin

router = APIRouter()


# ─── Canonical industry slugs ────────────────────────────────────────
INDUSTRY_SLUGS = (
    "pool", "landscaping", "hvac", "pest_control",
    "cleaning", "solar", "handyman",
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
        {"key": "mowed_lawn_areas",         "label": "Mowed lawn areas",                    "required": True},
        {"key": "edged_walkways_driveways", "label": "Edged walkways and driveways",        "required": True},
        {"key": "trimmed_shrubs_hedges",    "label": "Trimmed shrubs and hedges",           "required": False},
        {"key": "blew_off_hardscape",       "label": "Blew off hardscape surfaces",         "required": True},
        {"key": "removed_weeds_from_beds",  "label": "Removed weeds from beds",             "required": False},
        {"key": "cleared_debris",           "label": "Cleared debris from work area",       "required": True},
        {"key": "inspected_irrigation",     "label": "Inspected irrigation heads",          "required": False},
        {"key": "bagged_removed_clippings", "label": "Bagged and removed clippings",        "required": False},
        {"key": "applied_fertilizer",       "label": "Applied fertilizer or treatment",     "required": False},
    ],
    "hvac": [
        {"key": "replaced_air_filter",       "label": "Replaced air filter",                "required": True},
        {"key": "checked_thermostat",        "label": "Checked thermostat calibration",     "required": True},
        {"key": "inspected_condensate_drain","label": "Inspected condensate drain line",    "required": True},
        {"key": "cleaned_condenser_coils",   "label": "Cleaned condenser coils",            "required": False},
        {"key": "measured_refrigerant",      "label": "Measured refrigerant pressure",      "required": False},
        {"key": "checked_electrical",        "label": "Checked electrical connections",     "required": False},
        {"key": "verified_airflow",          "label": "Verified system airflow",            "required": True},
        {"key": "tested_startup_shutdown",   "label": "Tested startup and shutdown cycle",  "required": False},
        {"key": "recorded_temp_differential","label": "Recorded temperature differential",  "required": False},
    ],
    "pest_control": [
        {"key": "treated_exterior_perimeter","label": "Treated exterior perimeter",         "required": True},
        {"key": "applied_interior_treatment","label": "Applied interior treatment where accessible", "required": True},
        {"key": "inspected_bait_stations",   "label": "Inspected bait stations",            "required": False},
        {"key": "removed_spider_webs",       "label": "Removed accessible spider webs",     "required": False},
        {"key": "identified_entry_points",   "label": "Identified entry points",            "required": False},
        {"key": "documented_pest_activity",  "label": "Documented pest activity",           "required": True},
        {"key": "applied_granular_soil",     "label": "Applied granular treatment to soil", "required": False},
        {"key": "placed_monitoring_devices", "label": "Placed monitoring devices",          "required": False},
    ],
    "cleaning": [
        {"key": "high_dusted_surfaces",      "label": "High-dusted surfaces",               "required": False},
        {"key": "wiped_countertops_surfaces","label": "Wiped down countertops and surfaces","required": True},
        {"key": "vacuumed_mopped_floors",    "label": "Vacuumed and mopped floors",         "required": True},
        {"key": "cleaned_restrooms",         "label": "Cleaned restrooms",                  "required": True},
        {"key": "emptied_trash_bins",        "label": "Emptied trash bins",                 "required": True},
        {"key": "restocked_supplies",        "label": "Restocked supplies",                 "required": False},
        {"key": "cleaned_windows_glass",     "label": "Cleaned interior windows and glass", "required": False},
        {"key": "deodorized_common_areas",   "label": "Deodorized common areas",            "required": False},
    ],
    "solar": [
        {"key": "inspected_panel_condition", "label": "Inspected panel physical condition", "required": True},
        {"key": "verified_inverter_status",  "label": "Verified inverter status",           "required": True},
        {"key": "recorded_system_output",    "label": "Recorded system output",             "required": True},
        {"key": "cleaned_panel_surfaces",    "label": "Cleaned panel surfaces if needed",   "required": False},
        {"key": "checked_wiring_connections","label": "Checked wiring and connections",     "required": True},
        {"key": "inspected_mounting",        "label": "Inspected mounting hardware",        "required": False},
        {"key": "reviewed_monitoring_portal","label": "Reviewed monitoring app / portal",   "required": False},
        {"key": "documented_anomalies",      "label": "Documented anomalies",               "required": False},
    ],
    "handyman": [
        {"key": "confirmed_scope",           "label": "Confirmed scope with customer",      "required": True},
        {"key": "verified_tools_materials",  "label": "Verified tools and materials on site","required": True},
        {"key": "completed_agreed_work",     "label": "Completed agreed work",              "required": True},
        {"key": "post_work_safety_walk",     "label": "Performed post-work safety walk",    "required": True},
        {"key": "cleaned_work_area",         "label": "Cleaned work area",                  "required": True},
        {"key": "reviewed_with_customer",    "label": "Reviewed completed work with customer","required": False},
        {"key": "documented_before_after",   "label": "Documented before/after photos",     "required": False},
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

    1. Explicit ``job.industry`` when present + valid.
    2. Keyword match on ``service_type`` / ``job_type`` / ``title``.
    3. Tenant primary industry (``tenant.industries[0]`` or
       ``tenant.industry``) when it maps to a known slug.
    4. Fallback to ``"pool"`` — matches the historical checklist
       default so existing Pool tenants keep working when nobody
       has classified their jobs yet.
    """
    if isinstance(job, dict):
        explicit = str(job.get("industry") or "").strip().lower()
        if explicit in INDUSTRY_SLUGS:
            return explicit
        hay = " ".join(
            str(job.get(k) or "") for k in ("service_type", "job_type", "title")
        ).lower()
        keyword_map = [
            # Order matters — narrower matches win before broader
            # ones. e.g. "Solar Panel Cleaning" must resolve to
            # ``solar``, not ``cleaning``.
            ("solar", "solar"), ("pv panel", "solar"), ("photovoltaic", "solar"),
            ("hvac", "hvac"), ("heating", "hvac"), ("cooling", "hvac"),
            ("air conditioning", "hvac"),
            ("pest", "pest_control"), ("exterminator", "pest_control"),
            ("handyman", "handyman"),
            ("landscape", "landscaping"), ("landscap", "landscaping"),
            ("mowing", "landscaping"), ("lawn", "landscaping"),
            ("pool", "pool"), ("chem", "pool"),
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
@router.get("/checklists/industry/{industry}",
              operation_id="industryChecklists.get")
async def get_checklist_endpoint(
    industry: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Any authed user can read the resolved template."""
    return await get_industry_checklist(tenant["id"], industry)


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
