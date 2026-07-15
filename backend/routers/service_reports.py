"""Phase 18B.follow-up · Auto-open service checklist on tech clock-in.

Every clocked-in job gets an in-progress "service report" — a template-detected
form the tech fills as they work. Chemical readings + chemicals-added for pool,
grooming checklist for landscape, plain checklist for anything else.

Endpoints (all tenant-scoped):
- GET   /api/jobs/{jid}/service-report                 (bootstrap or reload)
- PATCH /api/jobs/{jid}/service-report                 (autosave-friendly)
- POST  /api/jobs/{jid}/service-report/submit          (lock + mark completed)
- GET   /api/settings/service-templates                (admin — see defaults)
- PUT   /api/settings/service-templates                (admin — override)
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, get_current_user, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()

# ─── Default templates ─────────────────────────────────────────────────────
POOL_CHECKLIST_DEFAULT = [
    "Skim surface and empty baskets",
    "Brush walls and steps",
    "Vacuum floor",
    "Empty pump basket",
    "Clean/backwash filter as needed",
    "Inspect equipment (pump, heater, timer)",
    "Check water level; top off if needed",
    "Confirm no visible algae or debris",
]
POOL_READING_FIELDS_DEFAULT = [
    # key=machine, name=user label, ideal=text hint, min/max=picker range, step=picker step
    {"key": "ph",                "name": "pH",                "unit": "",     "type": "select",
     "ideal": "7.4–7.6",  "min": 6,    "max": 8.5,  "step": 0.1},
    {"key": "chlorine",          "name": "Free Chlorine",     "unit": "ppm",  "type": "select",
     "ideal": "1–3",      "min": 0,    "max": 20,   "step": 0.1},
    {"key": "combined_chlorine", "name": "Combined Chlorine", "unit": "ppm",  "type": "select",
     "ideal": "0–0.2",    "min": 0,    "max": 20,   "step": 0.1},
    {"key": "alkalinity",        "name": "Total Alkalinity",  "unit": "ppm",  "type": "select",
     "ideal": "80–120",   "min": 0,    "max": 500,  "step": 20},
    {"key": "calcium_hardness",  "name": "Calcium Hardness",  "unit": "ppm",  "type": "select",
     "ideal": "200–400",  "min": 0,    "max": 1000, "step": 50},
    {"key": "cyanuric",          "name": "Cyanuric Acid",     "unit": "ppm",  "type": "select",
     "ideal": "30–50",    "min": 0,    "max": 600,  "step": 10},
    {"key": "salt",              "name": "Salt",              "unit": "ppm",  "type": "select",
     "ideal": "2700–3400","min": 0,    "max": 5000, "step": 100},
    {"key": "tds",               "name": "Total Dissolved Solids", "unit": "ppm", "type": "select",
     "ideal": "250–1500", "min": 0,    "max": 3000, "step": 100},
    {"key": "phosphates",        "name": "Phosphates",        "unit": "ppb",  "type": "select",
     "ideal": "0–100",    "min": 0,    "max": 1000, "step": 50},
    {"key": "water_temp",        "name": "Water Temp",        "unit": "°F",   "type": "select",
     "ideal": "78–82",    "min": 50,   "max": 105,  "step": 1},
]


def _build_options(min_v, max_v, step):
    """Precompute the picker option list (strings) exactly like the source repo."""
    dec = 1 if step < 1 else 0
    count = int(round((max_v - min_v) / step))
    out = []
    for i in range(count + 1):
        v = min_v + i * step
        out.append(f"{v:.1f}" if dec else str(int(round(v))))
    return out


# Attach the ready-to-render options[] to each field.
for _f in POOL_READING_FIELDS_DEFAULT:
    if _f.get("type") == "select":
        _f["options"] = _build_options(_f["min"], _f["max"], _f["step"])


# ── Source-repo chemical amount pickers ────────────────────────────────────
# Chemicals measured in gal/lbs/oz use a 0.5-step dropdown (up to 10);
# tabs use whole numbers 1..10.
CHEM_STEP_OPTIONS = [f"{(i + 1) * 0.5:g}" for i in range(20)]
CHEM_TAB_OPTIONS = [str(i + 1) for i in range(10)]

CHEMICAL_UNITS_DEFAULT = ["gal", "lbs", "oz", "tabs"]

POOL_CHEMICALS_CATALOG_DEFAULT = [
    {"name": "Liquid Chlorine",    "default_unit": "gal",  "common_units": ["gal", "oz"],
     "amount_options": CHEM_STEP_OPTIONS},
    {"name": "Chlorine Tablets",   "default_unit": "tabs", "common_units": ["tabs"],
     "amount_options": CHEM_TAB_OPTIONS},
    {"name": "Shock (Cal-Hypo)",   "default_unit": "lbs",  "common_units": ["lbs", "oz"],
     "amount_options": CHEM_STEP_OPTIONS},
    {"name": "Muriatic Acid",      "default_unit": "oz",   "common_units": ["oz", "gal"],
     "amount_options": CHEM_STEP_OPTIONS},
    {"name": "Soda Ash",           "default_unit": "lbs",  "common_units": ["lbs", "oz"],
     "amount_options": CHEM_STEP_OPTIONS},
    {"name": "Sodium Bicarbonate", "default_unit": "lbs",  "common_units": ["lbs", "oz"],
     "amount_options": CHEM_STEP_OPTIONS},
    {"name": "Calcium Chloride",   "default_unit": "lbs",  "common_units": ["lbs", "oz"],
     "amount_options": CHEM_STEP_OPTIONS},
    {"name": "Cyanuric Acid",      "default_unit": "lbs",  "common_units": ["lbs", "oz"],
     "amount_options": CHEM_STEP_OPTIONS},
    {"name": "Pool Salt",          "default_unit": "lbs",  "common_units": ["lbs"],
     "amount_options": CHEM_STEP_OPTIONS},
    {"name": "Algaecide",          "default_unit": "oz",   "common_units": ["oz", "gal"],
     "amount_options": CHEM_STEP_OPTIONS},
    {"name": "Clarifier",          "default_unit": "oz",   "common_units": ["oz"],
     "amount_options": CHEM_STEP_OPTIONS},
    {"name": "Phosphate Remover",  "default_unit": "oz",   "common_units": ["oz"],
     "amount_options": CHEM_STEP_OPTIONS},
    {"name": "Enzymes",            "default_unit": "oz",   "common_units": ["oz"],
     "amount_options": CHEM_STEP_OPTIONS},
]
LANDSCAPE_CHECKLIST_DEFAULT = [
    "Mow all turf areas",
    "Edge sidewalks and driveways",
    "Trim shrubs/hedges as needed",
    "Blow all hard surfaces",
    "Pull/spray visible weeds",
    "Check irrigation heads",
    "Empty and haul debris",
    "Report any damage or issues",
]
GENERIC_CHECKLIST_DEFAULT = [
    "Confirm scope with customer",
    "Perform requested service",
    "Clean up work area",
    "Take before/after photos",
    "Log any follow-up needed",
]

_KIND_KEYWORDS = {
    "pool":     ["pool", "chem"],
    "landscape":["landscap", "mow", "lawn", "garden", "trim", "blow"],
}


def _detect_template(job: dict) -> str:
    hay = " ".join(str(job.get(k) or "") for k in ("service_type", "job_type", "title")).lower()
    for kw in _KIND_KEYWORDS["pool"]:
        if kw in hay:
            return "pool"
    for kw in _KIND_KEYWORDS["landscape"]:
        if kw in hay:
            return "landscape"
    return "generic"


def _default_template(kind: str) -> dict:
    if kind == "pool":
        return {
            "kind": "pool",
            "checklist_items": list(POOL_CHECKLIST_DEFAULT),
            "chemical_reading_fields": [dict(x) for x in POOL_READING_FIELDS_DEFAULT],
            "chemicals_catalog": [dict(x) for x in POOL_CHEMICALS_CATALOG_DEFAULT],
            "chemical_units": list(CHEMICAL_UNITS_DEFAULT),
        }
    if kind == "landscape":
        return {
            "kind": "landscape",
            "checklist_items": list(LANDSCAPE_CHECKLIST_DEFAULT),
            "chemical_reading_fields": [],
            "chemicals_catalog": [],
            "chemical_units": [],
        }
    return {
        "kind": "generic",
        "checklist_items": list(GENERIC_CHECKLIST_DEFAULT),
        "chemical_reading_fields": [],
        "chemicals_catalog": [],
        "chemical_units": [],
    }


async def _get_template(tenant_id: str, kind: str) -> dict:
    """Merge tenant customizations onto built-in defaults. This is critical:
    a partial admin PUT (e.g. only checklist_items) must not wipe the
    chemical_reading_fields / chemicals_catalog / chemical_units sections that
    the tech UI depends on.
    """
    defaults = _default_template(kind)
    doc = await db.service_report_templates.find_one(
        {"tenant_id": tenant_id, "kind": kind}, {"_id": 0}
    )
    if not doc:
        return defaults
    merged = dict(defaults)
    for field in ("checklist_items", "chemical_reading_fields",
                  "chemicals_catalog", "chemical_units"):
        if doc.get(field) is not None:
            merged[field] = doc[field]
    # Also carry admin audit fields.
    for f in ("updated_by", "updated_at", "created_at"):
        if doc.get(f) is not None:
            merged[f] = doc[f]
    return merged


async def _bootstrap_report(tenant_id: str, job: dict, tech_id: str) -> dict:
    kind = _detect_template(job)
    tpl = await _get_template(tenant_id, kind)
    now = now_iso()
    return {
        "id": new_id(),
        "tenant_id": tenant_id,
        "job_id": job["id"],
        "tech_id": tech_id,
        "template": kind,
        "chemical_readings": [
            {"key": f.get("key") or f["name"], "name": f["name"],
             "unit": f.get("unit"), "value": None, "ts": None}
            for f in tpl.get("chemical_reading_fields", [])
        ],
        "chemicals_added": [],
        "checklist_items": [
            {"id": new_id(),
             "label": (x if isinstance(x, str) else x.get("label", "")),
             "required": (False if isinstance(x, str) else bool(x.get("required"))),
             "checked": False, "notes": None}
            for x in tpl.get("checklist_items", [])
        ],
        "notes": "",
        "photos": [],  # mirror; canonical photo store stays on jobs.photos
        "started_at": now,
        "submitted_at": None,
        "created_at": now,
        "updated_at": now,
    }


async def _authorize_report(job: dict, user: dict) -> str:
    """Returns the tech_id whose report should be scoped."""
    role = user.get("role")
    if role == "customer":
        raise HTTPException(403, "Not allowed")
    if role == "technician":
        # The `jobs.technician_id` field may point at either the user row (older
        # seeds) or the technicians-table row (newer seeds). Match either.
        assigned = job.get("technician_id")
        if assigned not in (user.get("id"), user.get("technician_id")):
            raise HTTPException(403, "Not your job")
        return assigned or user.get("technician_id") or user["id"]
    # admin / super_admin — pick the job's assigned tech (falls back to admin's id)
    return job.get("technician_id") or user["id"]


# ─── GET (bootstrap-or-reload) ─────────────────────────────────────────────
@router.get("/jobs/{jid}/service-report")
async def get_service_report(jid: str,
                             user: dict = Depends(get_current_user),
                             tenant: dict = Depends(get_current_tenant)):
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    tech_id = await _authorize_report(job, user)
    existing = await db.service_reports.find_one(
        {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id}, {"_id": 0}
    )
    if not existing:
        try:
            await db.service_reports.create_index(
                [("tenant_id", 1), ("job_id", 1), ("tech_id", 1)]
            )
        except Exception:
            pass
        existing = await _bootstrap_report(tenant["id"], job, tech_id)
        await db.service_reports.insert_one(existing)
        existing.pop("_id", None)
    # Attach live job.photos + tenant template metadata so the UI can render
    # dropdowns for chemical readings + chemicals-added catalog.
    existing["photos"] = job.get("photos") or []
    tpl = await _get_template(tenant["id"], existing.get("template", "generic"))
    existing["chemical_reading_fields"] = tpl.get("chemical_reading_fields", [])
    existing["chemicals_catalog"] = tpl.get("chemicals_catalog", [])
    existing["chemical_units"] = tpl.get("chemical_units", [])
    existing["job"] = {
        "id": job["id"],
        "title": job.get("title"),
        "service_type": job.get("service_type"),
        "job_type": job.get("job_type"),
        "customer_id": job.get("customer_id"),
        "customer_name": job.get("customer_name"),
        "address": job.get("address"),
        "gate_code": job.get("gate_code"),
        "status": job.get("status"),
        "scheduled_start": job.get("scheduled_start"),
        "scheduled_end": job.get("scheduled_end"),
    }
    return existing


# ─── PATCH (autosave-friendly) ─────────────────────────────────────────────
class ServiceReportPatch(BaseModel):
    chemical_readings: Optional[List[Dict[str, Any]]] = None
    chemicals_added: Optional[List[Dict[str, Any]]] = None
    checklist_items: Optional[List[Dict[str, Any]]] = None
    notes: Optional[str] = None


@router.patch("/jobs/{jid}/service-report")
async def patch_service_report(jid: str, body: ServiceReportPatch,
                               user: dict = Depends(get_current_user),
                               tenant: dict = Depends(get_current_tenant)):
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    tech_id = await _authorize_report(job, user)
    rep = await db.service_reports.find_one(
        {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id}, {"_id": 0}
    )
    if not rep:
        raise HTTPException(404, "Service report not started — GET first to bootstrap")
    if rep.get("submitted_at"):
        raise HTTPException(409, "Report has already been submitted and is locked")
    upd = {k: v for k, v in body.dict(exclude_unset=True).items()}
    if not upd:
        raise HTTPException(400, "No fields to update")
    upd["updated_at"] = now_iso()
    await db.service_reports.update_one(
        {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id},
        {"$set": upd},
    )
    return await db.service_reports.find_one(
        {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id}, {"_id": 0}
    )


# ─── POST submit (lock + mark job status) ──────────────────────────────────
@router.post("/jobs/{jid}/service-report/submit")
async def submit_service_report(jid: str,
                                user: dict = Depends(get_current_user),
                                tenant: dict = Depends(get_current_tenant)):
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    tech_id = await _authorize_report(job, user)
    rep = await db.service_reports.find_one(
        {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id}, {"_id": 0}
    )
    if not rep:
        raise HTTPException(404, "No report to submit — GET first")
    if rep.get("submitted_at"):
        return rep  # idempotent
    now = now_iso()
    await db.service_reports.update_one(
        {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id},
        {"$set": {"submitted_at": now, "updated_at": now}},
    )
    # Roll job status forward. Preserve existing lifecycle: use `completed` since
    # that already exists across the codebase.
    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"]},
        {"$set": {"status": "completed",
                  "service_report_submitted_at": now,
                  "updated_at": now}},
    )
    # Mandatory clock-out when the entry originated from GPS auto-clock-in;
    # best-effort for manual entries (unchanged behavior for that case).
    clock_out_summary = None
    try:
        from routers.workforce import force_clock_out_if_auto
        clock_out_summary = await force_clock_out_if_auto(
            tenant["id"], user["id"], jid
        )
    except Exception as e:
        logger.warning(f"submit-driven clock-out failed: {e}")

    # Phase 23 · Inventory tracker — decrement stock from chemicals/parts.
    # NB: chemicals_added / parts_used live on the SERVICE REPORT, not on
    # the job. Re-fetch after our own $set so the latest PATCHed values are
    # visible even if a client PATCHed and POST-submit'd back-to-back.
    inventory_result = None
    try:
        from routers.inventory import decrement_from_service_report
        fresh_rep = await db.service_reports.find_one(
            {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id},
            {"_id": 0},
        ) or rep
        inventory_result = await decrement_from_service_report(
            tenant["id"], fresh_rep, fresh_rep.get("id") or rep.get("id"),
            user["id"],
        )
        if inventory_result and (inventory_result.get("misses")
                                  or inventory_result.get("decremented")):
            await db.service_reports.update_one(
                {"tenant_id": tenant["id"], "job_id": jid,
                  "tech_id": tech_id},
                {"$set": {
                    "inventory_decremented":
                        inventory_result.get("decremented") or [],
                    "inventory_misses":
                        inventory_result.get("misses") or [],
                }},
            )
    except Exception as e:
        logger.warning(f"inventory decrement failed: {e}")

    # Phase 39 · Algae-risk auto-flag — if this and the previous service
    # report both show free_chlorine <= 0.5 ppm, write an algae_risk_flags
    # entry so the office sees the at-risk customer on the retention report.
    try:
        from routers.reports import evaluate_algae_risk
        await evaluate_algae_risk(tenant["id"], job.get("customer_id"))
    except Exception as e:
        logger.warning(f"algae-risk evaluation failed: {e}")

    # Phase 20A.2 — auto-generate an invoice when the tenant setting allows,
    # the job is billable, and it has a positive price. Reuses the referral-
    # credit application path so 50%-off credits still land correctly.
    invoice_id = None
    try:
        settings = (tenant.get("settings") or {})
        auto_invoice = settings.get("auto_invoice_on_submit", True)
        billable = job.get("billable") is not False
        price = float(job.get("price") or job.get("total_price") or 0)
        skip_types = {"warranty callback", "estimate", "warranty",
                       "quote", "service call — warranty"}
        service_type = (job.get("service_type") or "").strip().lower()
        if (auto_invoice and billable and price > 0
                and service_type not in skip_types):
            inv_id = new_id()
            line_items = [{
                "description": job.get("title") or job.get("service_type") or "Service",
                "quantity": 1, "unit_price": price,
            }]
            subtotal = round(price, 2)
            invoice = {
                "id": inv_id,
                "tenant_id": tenant["id"],
                "customer_id": job.get("customer_id"),
                "customer_name": job.get("customer_name"),
                "job_id": jid,
                "doc_type": "invoice",
                "title": f"Service — {job.get('title') or service_type or 'Job'}",
                "line_items": line_items,
                "tax_rate": 0, "subtotal": subtotal, "tax": 0.0, "total": subtotal,
                "amount_paid": 0.0, "payment_status": "unpaid", "status": "draft",
                "auto_created_from_report": True,
                "created_at": now_iso(),
            }
            # Apply any pending referral credits — same helper Phase 19 uses.
            try:
                from routers.referrals import apply_referral_credits_to_invoice
                invoice = await apply_referral_credits_to_invoice(invoice)
            except Exception as e:
                logger.warning(f"invoice credit apply skipped: {e}")
            await db.quotes.insert_one(invoice)
            invoice_id = inv_id
    except Exception as e:
        logger.warning(f"auto-invoice failed: {e}")

    out = await db.service_reports.find_one(
        {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id}, {"_id": 0}
    )
    if clock_out_summary:
        out["clock_out_summary"] = {
            "entry_id": clock_out_summary.get("id"),
            "duration_minutes": clock_out_summary.get("duration_minutes"),
            "mileage_miles": clock_out_summary.get("mileage_miles"),
            "origin": clock_out_summary.get("origin"),
        }
    if invoice_id:
        out["invoice_id"] = invoice_id
    return out


# ─── Admin template settings (stubs — full editor UI can land later) ───────
class TemplateSetIn(BaseModel):
    kind: str  # pool | landscape | generic
    checklist_items: Optional[List[Any]] = None  # allow either List[str] or List[dict]
    chemical_reading_fields: Optional[List[Dict[str, Any]]] = None
    chemicals_catalog: Optional[List[Dict[str, Any]]] = None
    chemical_units: Optional[List[str]] = None


def _validate_template_payload(body: "TemplateSetIn") -> None:
    """Server-side validation. Raises HTTPException(422) on any bad shape."""
    if body.kind not in ("pool", "landscape", "generic"):
        raise HTTPException(422, "kind must be pool | landscape | generic")

    # Checklist items — accept `["label", ...]` or `[{label, required?, id?}, ...]`.
    if body.checklist_items is not None:
        for i, it in enumerate(body.checklist_items):
            if isinstance(it, str):
                if not it.strip():
                    raise HTTPException(422, f"checklist item #{i}: empty label")
            elif isinstance(it, dict):
                if not (it.get("label") or "").strip():
                    raise HTTPException(422, f"checklist item #{i}: label required")
            else:
                raise HTTPException(422, f"checklist item #{i}: unsupported shape")

    if body.chemical_reading_fields is not None:
        seen_keys = set()
        for i, f in enumerate(body.chemical_reading_fields):
            name = (f.get("name") or "").strip()
            if not name:
                raise HTTPException(422, f"reading field #{i}: name required")
            key = (f.get("key") or name).lower().replace(" ", "_")
            if key in seen_keys:
                raise HTTPException(422, f"reading field #{i}: duplicate key '{key}'")
            seen_keys.add(key)
            ftype = f.get("type") or "number"
            if ftype not in ("number", "select"):
                raise HTTPException(422, f"reading field '{name}': type must be number|select")
            if ftype == "select":
                opts = f.get("options") or []
                if not opts:
                    raise HTTPException(422, f"reading field '{name}': options required for select type")
            # Numeric bounds check (only if provided)
            mn, mx, st = f.get("min"), f.get("max"), f.get("step")
            if mn is not None and mx is not None and mn > mx:
                raise HTTPException(422, f"reading field '{name}': min > max")
            if st is not None and st <= 0:
                raise HTTPException(422, f"reading field '{name}': step must be > 0")

    if body.chemicals_catalog is not None:
        for i, c in enumerate(body.chemicals_catalog):
            if not (c.get("name") or "").strip():
                raise HTTPException(422, f"chemical #{i}: name required")

    if body.chemical_units is not None:
        for u in body.chemical_units:
            if not (u or "").strip():
                raise HTTPException(422, "chemical unit cannot be empty")


@router.get("/settings/service-templates")
async def list_service_templates(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    out = {}
    for kind in ("pool", "landscape", "generic"):
        out[kind] = await _get_template(tenant["id"], kind)
    return out


@router.put("/settings/service-templates")
async def upsert_service_template(
    body: TemplateSetIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    _validate_template_payload(body)
    upd = {k: v for k, v in body.dict(exclude_unset=True).items() if k != "kind"}
    upd["tenant_id"] = tenant["id"]
    upd["kind"] = body.kind
    upd["updated_by"] = user["id"]
    upd["updated_at"] = now_iso()
    await db.service_report_templates.update_one(
        {"tenant_id": tenant["id"], "kind": body.kind},
        {"$set": upd, "$setOnInsert": {"created_at": now_iso()}},
        upsert=True,
    )
    return await _get_template(tenant["id"], body.kind)


# ─── Billing settings (Phase 20A.2) ─────────────────────────────────────────
class BillingSettingsIn(BaseModel):
    auto_invoice_on_submit: bool


@router.get("/settings/billing")
async def get_billing_settings(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    settings = (tenant.get("settings") or {})
    return {
        "auto_invoice_on_submit": bool(settings.get("auto_invoice_on_submit", True)),
    }


@router.put("/settings/billing")
async def put_billing_settings(
    body: BillingSettingsIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {"settings.auto_invoice_on_submit": body.auto_invoice_on_submit,
                  "updated_at": now_iso()}},
    )
    return {"auto_invoice_on_submit": body.auto_invoice_on_submit}


@router.post("/settings/service-templates/{kind}/reset-defaults")
async def reset_template_defaults(
    kind: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Restore the built-in defaults for `kind` on this tenant only."""
    if kind not in ("pool", "landscape", "generic"):
        raise HTTPException(400, "kind must be pool | landscape | generic")
    await db.service_report_templates.delete_one(
        {"tenant_id": tenant["id"], "kind": kind}
    )
    return _default_template(kind)


# ═══════════ Phase 27.3 · Photo-based Chemical Dosing ══════════════════

import json as _json
import re as _re


class WaterPhotoIn(BaseModel):
    photo_url: str
    current_readings: Optional[Dict[str, Any]] = None
    pool_gallons: Optional[float] = None
    job_id: Optional[str] = None


_WATER_SYSTEM = (
    "You are a pool-chemistry analyst. Given a water photo and (optionally) "
    "current readings, assess visual clarity, identify likely issues, and "
    "recommend exact chemical doses. If current_readings + pool_gallons are "
    "provided, compute PRECISE doses; otherwise provide typical ranges. "
    "Return STRICT JSON only, no prose:\n"
    "{\n"
    '  "clarity": "crystal" | "clear" | "hazy" | "cloudy" | "green" | "black",\n'
    '  "issues": [<str>, ...],\n'
    '  "recommendations": [\n'
    '    {"chemical": <str>, "amount": <float>, "unit": <str>, '
    '"urgency": "now" | "next_visit" | "monitor", '
    '"reasoning": <str>}\n'
    '  ],\n'
    '  "overall_assessment": <str>,\n'
    '  "mocked": false\n'
    "}"
)


@router.post("/service-report/analyze-water-photo")
async def analyze_water_photo(body: WaterPhotoIn,
                                     user: dict = Depends(get_current_user),
                                     tenant: dict = Depends(get_current_tenant)):
    role = user.get("role") or ""
    if role not in {"admin", "super_admin", "technician"}:
        raise HTTPException(403, "Techs and admins only")

    from config import EMERGENT_LLM_KEY as _KEY
    if not _KEY:
        result = {"mocked": True,
                    "reason": "EMERGENT_LLM_KEY not configured",
                    "clarity": None, "issues": [],
                    "recommendations": [],
                    "overall_assessment": None}
    else:
        try:
            from emergentintegrations.llm.chat import (
                LlmChat, UserMessage, ImageContent,
            )
            # Current SDK requires base64. Fetch remote URL first.
            import base64, httpx
            try:
                async with httpx.AsyncClient(timeout=15,
                                                  follow_redirects=True) as c:
                    r = await c.get(body.photo_url)
                if r.status_code != 200:
                    raise RuntimeError(f"photo fetch http {r.status_code}")
                image_b64 = base64.b64encode(r.content).decode("ascii")
            except Exception as ex:
                raise RuntimeError(f"photo fetch failed: {ex}")
            chat = (LlmChat(api_key=_KEY, session_id=new_id(),
                             system_message=_WATER_SYSTEM)
                    .with_model("anthropic", "claude-sonnet-4-6"))
            ctx_lines = []
            if body.current_readings:
                ctx_lines.append(
                    f"Current readings: {_json.dumps(body.current_readings)}")
            if body.pool_gallons:
                ctx_lines.append(f"Pool gallons: {body.pool_gallons}")
            if not ctx_lines:
                ctx_lines.append("No readings provided — provide ranges.")
            msg = UserMessage(text="\n".join(ctx_lines),
                                file_contents=[ImageContent(image_base64=image_b64)])
            raw = await chat.send_message(msg)
            text = raw if isinstance(raw, str) else str(raw)
            text = text.strip()
            if text.startswith("```"):
                text = _re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "",
                                  text).strip()
            try: data = _json.loads(text)
            except Exception:
                m = _re.search(r"(\{.*\})", text, _re.S)
                data = _json.loads(m.group(1)) if m else {}
            result = {
                "mocked": False,
                "clarity": data.get("clarity"),
                "issues": data.get("issues") or [],
                "recommendations": data.get("recommendations") or [],
                "overall_assessment": data.get("overall_assessment"),
            }
        except Exception as ex:
            logger.warning(f"Water photo analysis failed: {ex}")
            result = {"mocked": True, "reason": f"llm error: {ex}",
                        "clarity": None, "issues": [],
                        "recommendations": [],
                        "overall_assessment": None}

    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "job_id": body.job_id,
        "technician_id": user.get("technician_id") or user["id"],
        "photo_url": body.photo_url,
        "current_readings": body.current_readings,
        "pool_gallons": body.pool_gallons,
        "clarity": result["clarity"],
        "issues": result["issues"],
        "recommendations": result["recommendations"],
        "overall_assessment": result["overall_assessment"],
        "mocked": result.get("mocked", False),
        "reason": result.get("reason"),
        "created_at": now_iso(),
    }
    await db.water_photo_analyses.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc



# ─── Phase 34e · Deterministic Chemical Dose Recommender ─────────────────
from services.pool_dosing import compute as _pool_compute


class RecommendChemicalsBody(BaseModel):
    job_id: Optional[str] = None
    readings: Dict[str, Any] = {}
    pool_gallons: Optional[int] = None
    use_llm_phrasing: bool = True


_DOSING_LLM_SYSTEM = (
    "You are a friendly pool-service assistant. Rewrite each 'reason' string "
    "in one short natural-language sentence (max 25 words). Do NOT change "
    "quantities, chemicals, or the order of items. Return a JSON array with "
    "the SAME length as the input, where each element has a single key "
    "'reason'. No extra keys, no wrapper object, no code fences."
)


async def _llm_rephrase_reasons(recs: list[dict]) -> tuple[list[dict], int, Optional[str]]:
    """Best-effort — returns (new_recs, tokens_used, error_or_None).
    On any failure returns the recs untouched."""
    if not recs:
        return recs, 0, None
    try:
        from config import EMERGENT_LLM_KEY
    except Exception as e:
        return recs, 0, f"llm import failed: {e}"
    if not EMERGENT_LLM_KEY:
        return recs, 0, "EMERGENT_LLM_KEY not configured"
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:
        return recs, 0, f"llm import failed: {e}"
    import json as _json2, re as _re2
    payload = [
        {"chemical": r["chemical"], "quantity": r["quantity"], "unit": r["unit"],
         "reason": r["reason"]}
        for r in recs
    ]
    prompt = "Rewrite each 'reason' below. Return the JSON array only.\n" + _json2.dumps(payload)
    try:
        chat = (LlmChat(api_key=EMERGENT_LLM_KEY, session_id=new_id(),
                         system_message=_DOSING_LLM_SYSTEM)
                .with_model("anthropic", "claude-sonnet-4-6")
                .with_params(max_tokens=800))
        raw = await chat.send_message(UserMessage(text=prompt))
        text = raw if isinstance(raw, str) else str(raw)
        text = text.strip()
        if text.startswith("```"):
            text = _re2.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
        arr = _json2.loads(text)
        if not isinstance(arr, list) or len(arr) != len(recs):
            return recs, 0, "llm returned mismatched array"
        out = []
        for orig, r_new in zip(recs, arr):
            r2 = dict(orig)
            new_reason = (r_new or {}).get("reason")
            if isinstance(new_reason, str) and new_reason.strip():
                r2["reason"] = new_reason.strip()
            out.append(r2)
        return out, int(len(text) / 4), None
    except Exception as ex:
        logger.warning(f"Dosing LLM rephrase failed: {ex}")
        return recs, 0, f"llm error: {ex}"


@router.post("/service-report/recommend-chemicals")
async def recommend_chemicals(body: RecommendChemicalsBody,
                                user: dict = Depends(get_current_user),
                                tenant: dict = Depends(get_current_tenant)):
    role = user.get("role") or ""
    if role not in {"admin", "super_admin", "technician"}:
        raise HTTPException(403, "Techs and admins only")

    # Resolve pool_gallons: request → job → customer.
    gallons: Optional[int] = None
    if body.pool_gallons and body.pool_gallons > 0:
        gallons = int(body.pool_gallons)
    elif body.job_id:
        job = await db.jobs.find_one(
            {"id": body.job_id, "tenant_id": tenant["id"]},
            {"_id": 0, "customer_id": 1},
        )
        if job and job.get("customer_id"):
            cust = await db.customers.find_one(
                {"id": job["customer_id"], "tenant_id": tenant["id"]},
                {"_id": 0, "pool_gallons": 1},
            )
            if cust and cust.get("pool_gallons"):
                gallons = int(cust["pool_gallons"])

    if not gallons:
        return {
            "recommendations": [],
            "mocked": True,
            "reason": "pool_gallons unknown — set on customer profile",
            "tokens_used": 0,
            "source": "deterministic-only",
            "pool_gallons": None,
        }

    recs = _pool_compute(body.readings or {}, gallons)
    source = "deterministic-only"
    tokens = 0
    llm_error: Optional[str] = None
    if body.use_llm_phrasing and recs:
        recs, tokens, llm_error = await _llm_rephrase_reasons(recs)
        source = "deterministic+llm" if not llm_error else "deterministic-only"

    return {
        "recommendations": recs,
        "mocked": False,
        "reason": llm_error,  # informational only — data is still real
        "tokens_used": tokens,
        "source": source,
        "pool_gallons": gallons,
    }


# ─── Phase 36 · Previously-tested-at helper ──────────────────────────────
@router.get("/service-reports/last-readings")
async def last_readings(
    customer_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Return the most recent non-null value + submission date per
    `chemical_readings` key for the given customer. Used by the pool
    checklist chip UI to render the "Previously tested at: X" caption
    under each reading."""
    if not customer_id:
        raise HTTPException(400, "customer_id required")
    # All the customer's jobs.
    jobs = await db.jobs.find(
        {"customer_id": customer_id, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1},
    ).to_list(2000)
    jids = [j["id"] for j in jobs]
    if not jids:
        return {"customer_id": customer_id, "readings": {}}
    # Reports for those jobs, submitted, most recent first.
    reports = await db.service_reports.find(
        {"job_id": {"$in": jids}, "submitted_at": {"$ne": None}},
        {"_id": 0, "chemical_readings": 1, "submitted_at": 1},
    ).sort("submitted_at", -1).to_list(200)
    out: dict[str, dict] = {}
    for rep in reports:
        submitted = rep.get("submitted_at")
        for r in rep.get("chemical_readings") or []:
            key = r.get("key") or r.get("name")
            if not key or r.get("value") in (None, ""):
                continue
            if key not in out:
                out[key] = {"value": r["value"], "at": submitted, "unit": r.get("unit")}
    return {"customer_id": customer_id, "readings": out}
