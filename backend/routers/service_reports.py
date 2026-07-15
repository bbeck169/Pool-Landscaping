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
