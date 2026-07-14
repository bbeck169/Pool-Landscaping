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
    {"name": "pH",              "unit": "",     "type": "number"},
    {"name": "Total Chlorine",  "unit": "ppm",  "type": "number"},
    {"name": "Free Chlorine",   "unit": "ppm",  "type": "number"},
    {"name": "Alkalinity",      "unit": "ppm",  "type": "number"},
    {"name": "Cyanuric Acid",   "unit": "ppm",  "type": "number"},
    {"name": "Calcium Hardness","unit": "ppm",  "type": "number"},
    {"name": "Water Temp",      "unit": "°F",   "type": "number"},
    {"name": "Salt",            "unit": "ppm",  "type": "number"},
]
POOL_CHEMICALS_CATALOG_DEFAULT = [
    {"name": "Chlorine tabs",       "default_unit": "tabs"},
    {"name": "Liquid chlorine",     "default_unit": "gal"},
    {"name": "Muriatic acid",       "default_unit": "gal"},
    {"name": "Sodium bicarb",       "default_unit": "lb"},
    {"name": "Cal-Hypo shock",      "default_unit": "lb"},
    {"name": "Cyanuric acid",       "default_unit": "lb"},
    {"name": "Salt",                "default_unit": "lb"},
    {"name": "Algaecide",           "default_unit": "oz"},
    {"name": "DE powder",           "default_unit": "lb"},
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
        }
    if kind == "landscape":
        return {
            "kind": "landscape",
            "checklist_items": list(LANDSCAPE_CHECKLIST_DEFAULT),
            "chemical_reading_fields": [],
            "chemicals_catalog": [],
        }
    return {
        "kind": "generic",
        "checklist_items": list(GENERIC_CHECKLIST_DEFAULT),
        "chemical_reading_fields": [],
        "chemicals_catalog": [],
    }


async def _get_template(tenant_id: str, kind: str) -> dict:
    doc = await db.service_report_templates.find_one(
        {"tenant_id": tenant_id, "kind": kind}, {"_id": 0}
    )
    if doc:
        return doc
    return _default_template(kind)


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
            {"name": f["name"], "unit": f.get("unit"), "value": None, "ts": None}
            for f in tpl.get("chemical_reading_fields", [])
        ],
        "chemicals_added": [],
        "checklist_items": [
            {"id": new_id(), "label": x, "checked": False, "notes": None}
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
    # Attach live job.photos so the UI shows the canonical count/state.
    existing["photos"] = job.get("photos") or []
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
    return await db.service_reports.find_one(
        {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id}, {"_id": 0}
    )


# ─── Admin template settings (stubs — full editor UI can land later) ───────
class TemplateSetIn(BaseModel):
    kind: str  # pool | landscape | generic
    checklist_items: Optional[List[str]] = None
    chemical_reading_fields: Optional[List[Dict[str, Any]]] = None
    chemicals_catalog: Optional[List[Dict[str, Any]]] = None


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
    if body.kind not in ("pool", "landscape", "generic"):
        raise HTTPException(400, "kind must be pool | landscape | generic")
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
