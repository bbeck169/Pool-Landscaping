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

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, get_current_user, require_admin
from routers.tenants import get_current_tenant
from services.chemistry import classify_reading, classify_readings

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
    #
    # Phase 56.3 follow-up — first-five reorder per operations request:
    #   1. Combined/Total Chlorine  2. Free Chlorine  3. pH
    #   4. Total Alkalinity  5. Cyanuric Acid
    # The remaining rows (calcium_hardness, salt, tds, phosphates,
    # water_temp) keep their existing order after the top five. This is
    # a UI order change only — no data migration required.
    {"key": "combined_chlorine", "name": "Combined Chlorine", "unit": "ppm",  "type": "select",
     "ideal": "0–0.2",    "min": 0,    "max": 20,   "step": 0.1},
    {"key": "chlorine",          "name": "Free Chlorine",     "unit": "ppm",  "type": "select",
     "ideal": "1–3",      "min": 0,    "max": 20,   "step": 0.1},
    {"key": "ph",                "name": "pH",                "unit": "",     "type": "select",
     "ideal": "7.4–7.6",  "min": 6,    "max": 8.5,  "step": 0.1},
    {"key": "alkalinity",        "name": "Total Alkalinity",  "unit": "ppm",  "type": "select",
     "ideal": "80–120",   "min": 0,    "max": 500,  "step": 20},
    {"key": "cyanuric",          "name": "Cyanuric Acid",     "unit": "ppm",  "type": "select",
     "ideal": "30–50",    "min": 0,    "max": 600,  "step": 10},
    {"key": "calcium_hardness",  "name": "Calcium Hardness",  "unit": "ppm",  "type": "select",
     "ideal": "200–400",  "min": 0,    "max": 1000, "step": 50},
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
    # Phase 56.16 — canonical 10-item list (see config_landscape_checklist).
    "Sprayed or Pulled Weeds",
    "Checked Irrigation",
    "Trimmed Bushes",
    "Mowed Grass",
    "Edged Grass",
    "Blow Property",
    "Raked Rocks",
    "Locked Gate",
    "Trimmed Trees",
    "Irrigation Repair",
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
        val = doc.get(field)
        if val is None:
            continue
        # Feb 2026 regression fix — for pool templates, treat an empty
        # ``chemical_reading_fields`` list as "use defaults" rather than
        # "hide every chemistry row." Prior admin PUTs that landed
        # ``chemical_reading_fields=[]`` (accidentally, during the Phase
        # 56.16 landscape-checklist rewrite) wiped chemistry from every
        # subsequent pool report for that tenant. Coalescing here
        # restores the defaults without breaking legit customizations
        # (there is no legitimate reason to configure a pool template
        # with zero chemistry rows).
        if (kind == "pool" and field in ("chemical_reading_fields",
                                            "chemicals_catalog",
                                            "chemical_units")
                and isinstance(val, list) and len(val) == 0):
            continue
        merged[field] = val
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
        # Phase 46.1 — starts empty; PATCH populates with `{key: True}`
        # when the tech explicitly toggles "Not tested" on a reading.
        "not_tested_flags": {},
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
    # Feb-2026 · Slice 3C — attach classification bands next to the raw
    # numeric readings so admin/tech UI can show "3.2 ppm · Average"
    # without repeating the threshold logic in the frontend.
    existing = _annotate_report_for_admin(existing)
    return existing


# ─── PATCH (autosave-friendly) ─────────────────────────────────────────────
class ServiceReportPatch(BaseModel):
    chemical_readings: Optional[List[Dict[str, Any]]] = None
    chemicals_added: Optional[List[Dict[str, Any]]] = None
    checklist_items: Optional[List[Dict[str, Any]]] = None
    notes: Optional[str] = None
    # Phase 46.1 — explicit "not tested" flags per reading key so the UI
    # can distinguish 0 from "did not test this visit". Dosing + algae
    # risk already skip null values (see services/pool_dosing._normalize
    # and reports._chlorine_ppm), so this dict is purely for UI recall.
    not_tested_flags: Optional[Dict[str, bool]] = None
    # Phase 56.6 — Pool Job Wizard fields. `wizard_step` is the tech's
    # persistent cursor (1..6) so Save-&-Exit resumes at the right step.
    # `internal_notes` is a private textarea rendered only on step 6.
    # `photos` are already an array on the doc — including it here lets
    # the wizard step-4 photo pool round-trip through the same PATCH.
    wizard_step: Optional[int] = None
    internal_notes: Optional[str] = None
    # Phase 56.16 — customer-facing notes rendered on the customer
    # portal service-report view. Distinct from `internal_notes` (which
    # is admin/tech-only). Empty string is fine — clears the field.
    customer_notes: Optional[str] = None
    photos: Optional[List[Dict[str, Any]]] = None
    # Phase 56.10 — visible-algae observation (and any future observation
    # dict fields). Persisted verbatim; the AI dosing recommender reads
    # `observations.visible_algae` to emit algae_remediation entries.
    observations: Optional[Dict[str, Any]] = None


@router.patch("/jobs/{jid}/service-report")
async def patch_service_report(jid: str, body: ServiceReportPatch,
                               request: Request,
                               user: dict = Depends(get_current_user),
                               tenant: dict = Depends(get_current_tenant)):
    # Phase 40 · Idempotency — offline mobile queues retry on reconnect.
    from utils_idempotency import replay_or_reserve, store_response
    key, cached = await replay_or_reserve(
        request, tenant["id"], "PATCH /jobs/{jid}/service-report",
        body.dict(exclude_unset=True))
    if cached is not None:
        return cached
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
    resp = await db.service_reports.find_one(
        {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id}, {"_id": 0}
    )
    if key:
        await store_response(key, "PATCH /jobs/{jid}/service-report",
                              tenant["id"], resp,
                              body.dict(exclude_unset=True))
    return resp


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

    # Phase 39 · Step 3b — Flip reservations for this job → consumed.
    # `decrement_from_service_report()` above already reduced the shared
    # `inventory_items.current_qty`, so we pass `skip_item_writes=True`
    # to avoid double-counting; consume() just closes the reservation
    # audit trail and stamps `consumed_by:"submit-flow"`.
    try:
        from routers.inventory import _consume_job_reservations_impl
        await _consume_job_reservations_impl(
            tenant["id"], job.get("id"),
            skip_item_writes=True, actor="submit-flow")
    except Exception as e:
        logger.warning(f"reservation consume failed: {e}")

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
            # Comms Phase 3 — auto-invoice from a submitted service
            # report still fires invoice.created so admins can wire a
            # confirmation email/SMS on it.
            try:
                from services.automation_engine import emit as _emit
                await _emit(
                    "invoice.created",
                    {"invoice": invoice,
                      "customer": {"id": invoice.get("customer_id"),
                                    "name": invoice.get("customer_name")},
                      "source": "service_report_auto"},
                    tenant_id=tenant["id"],
                    entity_kind="invoice", entity_id=inv_id,
                    customer_id=invoice.get("customer_id"),
                )
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"auto-invoice failed: {e}")

    out = await db.service_reports.find_one(
        {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id}, {"_id": 0}
    )
    # Comms Phase 3 — fire service_report.finalized. Non-blocking.
    try:
        from services.automation_engine import emit as _emit
        await _emit(
            "service_report.finalized",
            {"service_report": out or rep, "job": job,
              "customer": {"id": job.get("customer_id"),
                            "name": job.get("customer_name")}},
            tenant_id=tenant["id"],
            entity_kind="service_report",
            entity_id=(out or rep or {}).get("id") or "",
            customer_id=job.get("customer_id"),
        )
    except Exception:
        pass
    # Phase 56.20 — Auto End-of-Visit Customer Email.
    # Non-blocking: any exception is caught + logged inside the service.
    try:
        from services.auto_visit_email import send_visit_summary_email
        email_row = await send_visit_summary_email(tenant, job, out or rep)
        if email_row and email_row.get("id"):
            out["visit_summary_email_id"] = email_row["id"]
            out["visit_summary_email_status"] = email_row.get("status")
    except Exception as e:
        logger.warning(f"auto visit-summary email failed: {e}")
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
    # Phase 56.10 — "none" | "light" | "heavy". Drives the algae
    # remediation branch of the dosing engine.
    visible_algae: Optional[str] = "none"


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

    # Resolve pool_gallons + customer doc + recent reports for Phase 56.5
    # seasonal dosing rules. All lookups scoped by tenant.
    gallons: Optional[int] = None
    customer_doc: Optional[dict] = None
    recent_reports: list = []
    if body.pool_gallons and body.pool_gallons > 0:
        gallons = int(body.pool_gallons)
    if body.job_id:
        job = await db.jobs.find_one(
            {"id": body.job_id, "tenant_id": tenant["id"]},
            {"_id": 0, "customer_id": 1, "scheduled_date": 1},
        )
        if job and job.get("customer_id"):
            customer_doc = await db.customers.find_one(
                {"id": job["customer_id"], "tenant_id": tenant["id"]},
                {"_id": 0, "pool_gallons": 1, "chemical_preferences": 1},
            )
            if not gallons and customer_doc and customer_doc.get("pool_gallons"):
                gallons = int(customer_doc["pool_gallons"])
            # Last 3 submitted reports for tab-rotation guard.
            recent_reports = await db.service_reports.find(
                {"tenant_id": tenant["id"], "customer_id": job["customer_id"],
                 "submitted_at": {"$ne": None}},
                {"_id": 0, "chemicals_added": 1, "submitted_at": 1},
            ).sort("submitted_at", -1).limit(3).to_list(3)
        service_date_for_dosing = (job or {}).get("scheduled_date")
    else:
        service_date_for_dosing = None

    if not gallons:
        return {
            "recommendations": [],
            "mocked": True,
            "reason": "pool_gallons unknown — set on customer profile",
            "tokens_used": 0,
            "source": "deterministic-only",
            "pool_gallons": None,
        }

    recs = _pool_compute(
        body.readings or {}, gallons,
        customer=customer_doc,
        service_date=service_date_for_dosing,
        recent_service_reports=recent_reports,
        visible_algae=(body.visible_algae or "none"),
    )
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
        return {"customer_id": customer_id, "readings": {}, "recent_readings": {}}
    # Reports for those jobs, submitted, most recent first.
    reports = await db.service_reports.find(
        {"job_id": {"$in": jids}, "submitted_at": {"$ne": None}},
        {"_id": 0, "chemical_readings": 1, "submitted_at": 1},
    ).sort("submitted_at", -1).to_list(200)
    out: dict[str, dict] = {}
    recent: dict[str, list] = {}
    for rep in reports:
        submitted = rep.get("submitted_at")
        for r in rep.get("chemical_readings") or []:
            key = r.get("key") or r.get("name")
            if not key or r.get("value") in (None, ""):
                continue
            if key not in out:
                out[key] = {"value": r["value"], "at": submitted, "unit": r.get("unit")}
            # Phase 49.6 — capture up to the last 4 values per key so the
            # client can compute a rolling median for the outlier "Recheck?"
            # hint. Reports are already sorted most-recent-first.
            arr = recent.setdefault(key, [])
            if len(arr) < 4:
                try:
                    arr.append(float(r["value"]))
                except (TypeError, ValueError):
                    pass
    return {"customer_id": customer_id, "readings": out, "recent_readings": recent}


# ─── Phase 39 · Send Visit Recap ────────────────────────────────────────
# Fired after a tech closes a job. Composes a short summary of the visit
# (chemicals added, water readings, up to 3 photos) and sends it to the
# customer via Twilio SMS and/or Resend email. If either channel isn't
# configured we return an honest `mocked:true, reason` for that channel
# instead of silently pretending to send. Every attempt (real or mocked)
# is written to `visit_recaps_sent` for the audit trail.
import os as _os

# Preset labels for the chemicals-added rows. Mirrors the web/mobile
# `CHEM_TYPES` config so tech-facing labels match what the customer sees.
_CHEM_UNIT_LABELS = {
    "tabs": "Tabs", "gal": "Gallon", "lbs": "lbs", "oz": "Ounces",
    "bags": "bags",
}


def _chem_added_line(row: dict) -> str:
    if row.get("raw_label"):
        return f"{row['raw_label']} of {row.get('chemical') or row.get('name')}"
    qty = row.get("quantity") or row.get("amount")
    unit = row.get("unit") or ""
    name = row.get("chemical") or row.get("name") or "Chemical"
    if not qty:
        return name
    return f"{qty} {unit} of {name}".strip()


# Water-target ranges — very deliberately conservative; only used to add
# a [low|target|high] indicator to each reading in the recap. If the key
# isn't in here we just show the value with no indicator.
_TARGET_RANGES = {
    "ph":               (7.2, 7.6),
    "free_chlorine":    (1.0, 3.0),
    "chlorine":         (1.0, 3.0),
    "total_chlorine":   (1.0, 3.0),
    "combined_chlorine":(0.0, 0.2),
    "alkalinity":       (80, 120),
    "total_alkalinity": (80, 120),
    "cyanuric_acid":    (30, 50),
    "cya":              (30, 50),
    "calcium_hardness": (200, 400),
    "salt":             (2700, 3400),
}


def _reading_indicator(key: str, value) -> str:
    rng = _TARGET_RANGES.get(str(key or "").lower())
    if not rng or value in (None, ""):
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    lo, hi = rng
    if v < lo:  return "[low]"
    if v > hi:  return "[high]"
    return "[target]"


def _compose_recap(report: dict, job: dict, customer: dict, tech_name: str,
                    include_photos: bool, next_visit: str | None,
                    tenant: dict, photo_limit: int = 3):
    """Return `{plain, html, photo_urls}` for the recap message."""
    # Chemicals-added block.
    chems = report.get("chemicals_added") or []
    chem_lines = [f"• {_chem_added_line(c)}" for c in chems if
                   (c.get("raw_label") or c.get("quantity") or c.get("amount"))]
    # Water readings block.
    readings = report.get("chemical_readings") or []
    reading_lines = []
    for r in readings:
        v = r.get("value")
        if v in (None, ""):
            continue
        key = r.get("key") or r.get("name")
        ind = _reading_indicator(key, v)
        unit = r.get("unit") or ""
        reading_lines.append(f"  {r.get('name') or key}: {v}{(' ' + unit) if unit else ''} {ind}".rstrip())
    # Photos.
    photo_urls = []
    if include_photos:
        for p in (report.get("photos") or [])[:photo_limit]:
            url = p.get("url") or p.get("public_url") or p.get("thumbnail_url")
            if url:
                photo_urls.append(url)

    date_str = str(job.get("scheduled_at") or job.get("service_report_submitted_at") or "")[:10]
    biz_name = tenant.get("name") or "Your pool service"

    lines = [
        f"Hi {customer.get('name') or 'there'},",
        f"Your {date_str} visit with {biz_name} is complete.",
    ]
    if tech_name:
        lines.append(f"Tech: {tech_name}")
    if chem_lines:
        lines.append("")
        lines.append("Chemicals added:")
        lines.extend(chem_lines)
    if reading_lines:
        lines.append("")
        lines.append("Water readings:")
        lines.extend(reading_lines)
    if next_visit:
        lines.append("")
        lines.append(f"Next visit: {next_visit}")
    if photo_urls:
        lines.append("")
        lines.append("Photos:")
        for u in photo_urls:
            lines.append(f"  {u}")
    lines.append("")
    lines.append("Reply to this message with any questions.")
    plain = "\n".join(lines)

    # HTML for email — very lightweight, no external assets.
    html_parts = [f"<p>Hi {customer.get('name') or 'there'},</p>",
                  f"<p>Your <b>{date_str}</b> visit with <b>{biz_name}</b> is complete.</p>"]
    if tech_name:
        html_parts.append(f"<p>Tech: <b>{tech_name}</b></p>")
    if chem_lines:
        html_parts.append("<p><b>Chemicals added:</b></p><ul>"
                           + "".join(f"<li>{_chem_added_line(c)}</li>" for c in chems
                                      if c.get('raw_label') or c.get('quantity') or c.get('amount'))
                           + "</ul>")
    if reading_lines:
        html_parts.append("<p><b>Water readings:</b></p><ul>"
                           + "".join(f"<li>{line.strip()}</li>" for line in reading_lines)
                           + "</ul>")
    if photo_urls:
        html_parts.append("<p><b>Photos:</b></p>"
                           + "".join(f'<img src="{u}" style="max-width:300px;margin-right:8px;">'
                                      for u in photo_urls))
    if next_visit:
        html_parts.append(f"<p>Next visit: <b>{next_visit}</b></p>")
    html_parts.append("<p>Reply to this message with any questions.</p>")
    html = "".join(html_parts)

    return {"plain": plain, "html": html, "photo_urls": photo_urls,
             "subject": f"Your pool visit recap — {date_str}"}


async def _send_recap_sms(customer: dict, plain: str) -> dict:
    sid = _os.environ.get("TWILIO_ACCOUNT_SID")
    tok = _os.environ.get("TWILIO_AUTH_TOKEN")
    frm = _os.environ.get("TWILIO_FROM_NUMBER")
    to  = customer.get("alert_phone") or customer.get("phone")
    if not to:
        return {"sent": False, "mocked": True,
                 "reason": "customer has no phone on file"}
    if not (sid and tok and frm):
        return {"sent": False, "mocked": True,
                 "reason": "twilio not configured (TWILIO_ACCOUNT_SID/TOKEN/FROM_NUMBER)"}
    try:
        from twilio.rest import Client
        msg = Client(sid, tok).messages.create(to=to, from_=frm, body=plain[:1500])
        return {"sent": True, "mocked": False, "twilio_sid": msg.sid}
    except Exception as e:
        return {"sent": False, "mocked": True, "reason": f"twilio error: {e}"}


async def _send_recap_email(customer: dict, subject: str, html: str) -> dict:
    from config import RESEND_API_KEY, EMAIL_FROM
    to = customer.get("email")
    if not to:
        return {"sent": False, "mocked": True,
                 "reason": "customer has no email on file"}
    if not RESEND_API_KEY:
        return {"sent": False, "mocked": True,
                 "reason": "resend not configured (RESEND_API_KEY missing)"}
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        r = resend.Emails.send({
            "from": EMAIL_FROM or "onboarding@resend.dev",
            "to": [to], "subject": subject, "html": html,
        })
        return {"sent": True, "mocked": False, "resend_id": (r or {}).get("id")}
    except Exception as e:
        return {"sent": False, "mocked": True, "reason": f"resend error: {e}"}


class RecapReq(BaseModel):
    channel: str = "both"
    include_photos: bool = True


@router.post("/service-reports/{sr_id}/send-recap")
async def send_visit_recap(sr_id: str, body: RecapReq,
                             user: dict = Depends(get_current_user),
                             tenant: dict = Depends(get_current_tenant)):
    if user.get("role") not in ("admin", "super_admin", "technician"):
        raise HTTPException(403, "Not allowed")
    channel = body.channel or "both"
    if channel not in ("sms", "email", "both"):
        raise HTTPException(400, "channel must be sms | email | both")

    rep = await db.service_reports.find_one({"id": sr_id,
                                               "tenant_id": tenant["id"]},
                                              {"_id": 0})
    if not rep:
        raise HTTPException(404, "Service report not found")
    job = await db.jobs.find_one({"id": rep.get("job_id"),
                                    "tenant_id": tenant["id"]}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    cust = await db.customers.find_one({"id": job.get("customer_id"),
                                          "tenant_id": tenant["id"]}, {"_id": 0}) or {}
    if not (cust.get("phone") or cust.get("alert_phone") or cust.get("email")):
        raise HTTPException(400, "Customer has neither phone nor email on file")

    tech = None
    if rep.get("tech_id"):
        tech = await db.users.find_one({"id": rep["tech_id"]}, {"_id": 0}) \
            or await db.users.find_one({"technician_id": rep["tech_id"]}, {"_id": 0})
    tech_name = (tech or {}).get("name") or (tech or {}).get("email") or ""

    # "Next visit" — cheap lookup of the next scheduled pool job for this customer.
    next_visit = None
    upcoming = await db.jobs.find(
        {"tenant_id": tenant["id"], "customer_id": job.get("customer_id"),
         "status": {"$in": ["scheduled", "open"]},
         "scheduled_at": {"$gt": now_iso()}},
        {"_id": 0, "scheduled_at": 1},
    ).sort("scheduled_at", 1).to_list(1)
    if upcoming:
        next_visit = str(upcoming[0].get("scheduled_at"))[:10]

    composed = _compose_recap(rep, job, cust, tech_name,
                                bool(body.include_photos), next_visit, tenant)

    results = {}
    mocked_channels = []
    if channel in ("sms", "both"):
        results["sms"] = await _send_recap_sms(cust, composed["plain"])
        if results["sms"].get("mocked"):
            mocked_channels.append("sms")
    if channel in ("email", "both"):
        results["email"] = await _send_recap_email(cust, composed["subject"],
                                                       composed["html"])
        if results["email"].get("mocked"):
            mocked_channels.append("email")

    sent_any = any(r.get("sent") for r in results.values())
    log_doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "service_report_id": sr_id,
        "job_id": job.get("id"),
        "customer_id": job.get("customer_id"),
        "channel": channel,
        "include_photos": bool(body.include_photos),
        "photo_count": len(composed.get("photo_urls") or []),
        "sent_at": now_iso(),
        "sent": sent_any,
        "mocked_channels": mocked_channels,
        "results": results,
        "actor_user_id": user.get("id"),
    }
    await db.visit_recaps_sent.insert_one(log_doc)

    return {
        "sent": sent_any,
        "channel": channel,
        "results": results,
        "mocked_channels": mocked_channels,
        "photo_count": len(composed.get("photo_urls") or []),
    }


# ─── Phase 56.16 — Customer portal: service reports (read-only) ────────────
def _redact_report_for_customer(sr: dict) -> dict:
    """Strip fields a customer must NEVER see.

    - `internal_notes` is admin/tech-only.
    - Photos tagged `internal` / `issue` (any flavor of the moderator
      tag) are dropped from the returned array.
    - `chemicals_added` remains visible so customers can see what went
      into their pool. Readings + checklist items are already
      customer-safe.

    Feb-2026 · Slice 3C — Chemistry readings are converted from raw
    numeric values to qualitative bands. Customers see ``below /
    average / above / elevated`` chips only; raw values are stripped.
    """
    if not sr:
        return sr
    sr = dict(sr)
    sr.pop("internal_notes", None)
    # Drop private/issue photos.
    photos = sr.get("photos") or []
    sr["photos"] = [
        p for p in photos
        if not any(str(t).lower() in ("internal", "issue", "private")
                   for t in ((p.get("tags") or []) if isinstance(p, dict) else []))
    ]
    # Feb-2026 · Slice 3C — replace numeric readings with labelled bands.
    readings = sr.get("chemical_readings") or []
    labels_map: Dict[str, str] = {}
    labelled_readings: List[Dict[str, Any]] = []
    for r in readings:
        if not isinstance(r, dict):
            continue
        key = r.get("key") or ""
        band = classify_reading(key, r.get("value"))
        if band is None:
            # Unclassifiable chemicals (salt, calcium hardness, water
            # temp, combined chlorine, …) are hidden from the customer
            # entirely — no numeric leakage.
            continue
        labels_map[str(key)] = band
        labelled_readings.append({
            "key": key,
            "name": r.get("name"),
            "unit": r.get("unit"),
            "label": band,
        })
    sr["chemical_readings"] = labelled_readings
    sr["readings_label"] = labels_map
    return sr


def _annotate_report_for_admin(sr: dict) -> dict:
    """Feb-2026 · Slice 3C — Admin/tech callers still see the raw
    numeric readings; we additionally attach a ``readings_label`` map
    so admin UI can render the classification band as a tooltip next
    to the number. No stored fields are mutated.
    """
    if not sr:
        return sr
    sr = dict(sr)
    sr["readings_label"] = classify_readings(sr.get("chemical_readings") or [])
    return sr


@router.get("/customers/me/service-reports")
async def list_my_service_reports(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customer portal only")

    # Find all jobs for this customer's id, then all completed reports.
    job_ids = [j["id"] async for j in db.jobs.find(
        {"tenant_id": tenant["id"], "customer_id": user["customer_id"]},
        {"_id": 0, "id": 1},
    )]
    if not job_ids:
        return []
    rows = await db.service_reports.find(
        {"tenant_id": tenant["id"], "job_id": {"$in": job_ids},
         "status": {"$in": ["submitted", "completed", "final"]}},
        {"_id": 0},
    ).sort("submitted_at", -1).to_list(200)

    out = []
    for sr in rows:
        job = await db.jobs.find_one({"id": sr.get("job_id")}, {"_id": 0}) or {}
        out.append({
            "id": sr.get("id"),
            "job_id": sr.get("job_id"),
            "job_title": job.get("title"),
            "service_type": job.get("service_type") or job.get("job_type"),
            "scheduled_start": job.get("scheduled_start"),
            "submitted_at": sr.get("submitted_at"),
            "tech_name": sr.get("tech_name"),
            "customer_notes": sr.get("customer_notes") or "",
        })
    return out


@router.get("/customers/me/service-reports/{report_id}")
async def get_my_service_report(
    report_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customer portal only")

    sr = await db.service_reports.find_one(
        {"tenant_id": tenant["id"], "id": report_id}, {"_id": 0},
    )
    if not sr:
        raise HTTPException(404, "Service report not found")

    # Confirm the report's job belongs to this customer.
    job = await db.jobs.find_one(
        {"tenant_id": tenant["id"], "id": sr.get("job_id"),
         "customer_id": user["customer_id"]}, {"_id": 0},
    )
    if not job:
        # A stranger customer cannot read another customer's report even
        # if they know the id.
        raise HTTPException(403, "Not your service report")

    sr = _redact_report_for_customer(sr)
    sr["job"] = {
        "id": job.get("id"),
        "title": job.get("title"),
        "service_type": job.get("service_type") or job.get("job_type"),
        "address": job.get("address"),
        "scheduled_start": job.get("scheduled_start"),
    }
    return sr



# ═══════════════════════════════════════════════════════════════════════
# Phase 56.20 — Auto End-of-Visit Email settings + Calculator attach hook
# ═══════════════════════════════════════════════════════════════════════

class AutoVisitEmailIn(BaseModel):
    enabled: Optional[bool] = None
    include_reviews_cta: Optional[bool] = None
    google_review_link: Optional[str] = None
    footer_text: Optional[str] = None


@router.get("/settings/auto-visit-email")
async def get_auto_visit_email_settings(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin only")
    settings = (tenant.get("settings") or {}).get("auto_visit_email") or {}
    return {
        "enabled": bool(settings.get("enabled", False)),
        "include_reviews_cta": bool(settings.get("include_reviews_cta", True)),
        "google_review_link": settings.get("google_review_link") or "",
        "footer_text": settings.get("footer_text") or "",
    }


@router.put("/settings/auto-visit-email")
async def set_auto_visit_email_settings(
    body: AutoVisitEmailIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin only")
    existing = (tenant.get("settings") or {}).get("auto_visit_email") or {}
    upd = {k: v for k, v in body.dict().items() if v is not None}
    merged = {**existing, **upd}
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {"settings.auto_visit_email": merged, "updated_at": now_iso()}},
    )
    return merged


@router.post("/settings/auto-visit-email/preview")
async def preview_auto_visit_email(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Render the email using the tenant's most recent submitted service
    report so admin can eyeball the layout before flipping the toggle."""
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin only")
    sr = await db.service_reports.find_one(
        {"tenant_id": tenant["id"], "submitted_at": {"$ne": None}},
        {"_id": 0}, sort=[("submitted_at", -1)],
    )
    if not sr:
        raise HTTPException(404, "No submitted service reports available for preview")
    job = await db.jobs.find_one(
        {"tenant_id": tenant["id"], "id": sr.get("job_id")}, {"_id": 0}) or {}
    customer = await db.customers.find_one(
        {"tenant_id": tenant["id"], "id": job.get("customer_id")}, {"_id": 0}) or {}
    safe_sr = _redact_report_for_customer(dict(sr))
    from services.auto_visit_email import render_email
    rendered = render_email(tenant, job, safe_sr, customer)
    return {
        "subject": rendered["subject"],
        "html": rendered["html"],
        "text": rendered["text"],
        "kind": rendered["kind"],
        "based_on_report_id": sr.get("id"),
        "based_on_job_id": sr.get("job_id"),
    }


class AttachNoteIn(BaseModel):
    text: str
    report_id: Optional[str] = None


@router.post("/service-report/attach-note")
async def attach_calculator_note(
    body: AttachNoteIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Phase 56.20 bundle — append a plain-text summary (produced by a
    tool like the Pool Calculators) to the tech's active open service
    report's `internal_notes`. Techs+admins only. Never touches
    customer-facing `customer_notes`.

    Behavior:
    - If `report_id` supplied → target that report (must belong to caller).
    - Else find caller's open (unsubmitted) service reports; if exactly
      one, use it; if none → 404; if multiple → 409 with the list so the
      UI can render a picker.
    """
    if user.get("role") not in ("admin", "super_admin", "technician"):
        raise HTTPException(403, "Techs and admins only")
    if not body.text.strip():
        raise HTTPException(422, "text is required")
    tech_id = user.get("technician_id") or user.get("id")
    q = {"tenant_id": tenant["id"], "tech_id": tech_id, "submitted_at": None}
    if body.report_id:
        q["id"] = body.report_id
    reports = await db.service_reports.find(q, {"_id": 0}).to_list(20)
    if body.report_id:
        if not reports:
            raise HTTPException(404, "Service report not found or not yours")
        target = reports[0]
    else:
        if not reports:
            raise HTTPException(404, "No open service report — start a job first")
        if len(reports) > 1:
            return {
                "status": "multiple_open_reports",
                "reports": [{"id": r["id"], "job_id": r.get("job_id"),
                             "tech_name": r.get("tech_name")} for r in reports],
            }
        target = reports[0]
    now = now_iso()
    stamped = f"\n[Calculator @ {now[:16].replace('T', ' ')}] {body.text.strip()}"
    prev = target.get("internal_notes") or ""
    new_notes = (prev + stamped).strip()
    await db.service_reports.update_one(
        {"tenant_id": tenant["id"], "id": target["id"]},
        {"$set": {"internal_notes": new_notes, "updated_at": now}},
    )
    # Audit trail (simple history append; separate from `service_report_history` if that exists).
    await db.service_report_notes_audit.insert_one({
        "id": new_id(),
        "tenant_id": tenant["id"],
        "service_report_id": target["id"],
        "actor_user_id": user["id"],
        "actor_name": user.get("name") or user.get("email"),
        "source": "calculator",
        "text": body.text.strip(),
        "created_at": now,
    })
    return {"status": "attached", "report_id": target["id"], "internal_notes_len": len(new_notes)}

