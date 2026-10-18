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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, get_current_user, require_admin
from routers.tenants import get_current_tenant
# Feb-2026 · Phase F1 — crew-aware tech authorization helper.
from services.authz import is_tech_authorized_on_job
from services.chemistry import classify_reading, classify_readings
from services.water_bodies import (
    BODY_TYPE_LABELS,
    WaterBodyValidationError,
    apply_water_bodies_payload,
    build_default_body_from_report,
    flatten_chemicals_used,
    flatten_pool_readings,
    iter_water_bodies,
    summarize_body,
    validate_water_bodies,
)

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
    # Phase CHK1 · Feb-2026 — three optional "emptied" items added.
    # NEVER add to the chemistry gate / required-fields list — techs
    # must be able to close a job with these unchecked.
    "Emptied skimmer basket",
    "Emptied leaf canister",
    "Emptied Betta Skimmer",
]
POOL_READING_FIELDS_DEFAULT = [
    # key=machine, name=user label, ideal=text hint, min/max=picker range, step=picker step
    #
    # Phase CHEM1 · Feb-2026 — the Total Chlorine (``total_cl``) field
    # was removed. The Required set is now the "Required Four":
    # free_chlorine, ph, alkalinity, cyanuric_acid. See
    # ``services/chemistry_gate.CORE_READINGS``. Combined Chlorine
    # remains a customer-facing optional reading; other rows stay
    # exactly as they were.
    {"key": "combined_chlorine", "name": "Combined Chlorine", "unit": "ppm",  "type": "select",
     "ideal": "0–0.2",    "min": 0,    "max": 20,   "step": 0.1},
    # Phase P17.1 · Feb-2026 — canonical rename: ``free_chlorine`` →
    # ``chlorine`` end-to-end. Legacy spellings (``free_chlorine``,
    # ``free_cl``, ``fc``) remain as source aliases in
    # ``chemistry_gate.ALIAS_MAP`` so persisted templates continue
    # to resolve to the new canonical key.
    {"key": "chlorine",          "name": "Chlorine",          "unit": "ppm",  "type": "select",
     "ideal": "1–3",      "min": 0,    "max": 20,   "step": 0.1},
    {"key": "ph",                "name": "pH",                "unit": "",     "type": "select",
     "ideal": "7.4–7.6",  "min": 6,    "max": 8.5,  "step": 0.1},
    {"key": "alkalinity",        "name": "Alkalinity",        "unit": "ppm",  "type": "select",
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
    # Feb-2026 · Repair-mode service log — inherit ``work_class`` from
    # the parent job so downstream consumers (frontend form branch,
    # workstream badge, portal renderer, chemistry gate skip) can
    # key off the report doc without re-querying the job.
    from services.work_class import infer_work_class as _iwc
    work_class = _iwc(job)
    initial_readings = [
        {"key": f.get("key") or f["name"], "name": f["name"],
         "unit": f.get("unit"), "value": None, "ts": None}
        for f in tpl.get("chemical_reading_fields", [])
    ]
    # Feb-2026 · Multi-body Phase 1 — every new report bootstraps with
    # a single default ``water_bodies[0]`` mirroring the legacy top-level
    # fields. Type is inferred from the parent job (pool jobs → "pool",
    # anything else → "other"). Backward compatible: legacy top-level
    # ``chemical_readings`` / ``chemicals_added`` / ``photos`` / ``notes``
    # remain the mirror source and are kept in sync by PATCH.
    default_body_type = "pool" if kind == "pool" else "other"
    default_body = {
        "id": new_id(),
        "type": default_body_type,
        "label": BODY_TYPE_LABELS[default_body_type],
        "sequence": 0,
        "readings": list(initial_readings),
        "chemicals_used": [],
        "media": [],
        "notes": "",
    }
    return {
        "id": new_id(),
        "tenant_id": tenant_id,
        "job_id": job["id"],
        "tech_id": tech_id,
        "work_class": work_class,
        # Phase 22 · Feb 2026 — opaque public UUID keys the public
        # /portal/service/{uuid} page used by the SERVICE_RECORD_IMAGES
        # merge tag. Generated at bootstrap so every submitted report
        # has one; kept independent from the internal ``id`` so we can
        # rotate it without touching primary keys.
        "public_uuid": new_id(),
        # Phase 27 · Feb 2026 — service-report media pool. Photos
        # already mirror ``job.photos``; ``videos`` is new (max 3 per
        # report, 60s each, 100MB each — enforced by the media router).
        "videos": [],
        "template": kind,
        "chemical_readings": initial_readings,
        "chemicals_added": [],
        # Feb-2026 · Multi-body Phase 1 — canonical per-body array.
        "water_bodies": [default_body],
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
    """Returns the tech_id whose report should be scoped.

    Feb-2026 · Phase F1 — technicians on the assigned crew (but not
    the direct ``technician_id`` on the row) are now authorized via
    ``is_tech_authorized_on_job``. Previously crew-only jobs
    returned 403 for every crew member.
    """
    role = user.get("role")
    if role == "customer":
        raise HTTPException(403, "Not allowed")
    if role == "technician":
        if not await is_tech_authorized_on_job(user, job, db, job.get("tenant_id")):
            raise HTTPException(403, "Not your job")
        # ``jobs.technician_id`` may be null (crew-only job) or point at
        # a teammate; scope the report to THIS tech in that case.
        assigned = job.get("technician_id")
        return assigned or user.get("technician_id") or user["id"]
    # admin / super_admin — pick the job's assigned tech (falls back to admin's id)
    return job.get("technician_id") or user["id"]


# ─── GET (bootstrap-or-reload) ─────────────────────────────────────────────
# ─── POST create (Phase O4 — Client-UUID acceptance) ───────────────────────
# The mobile app mints a UUID for a fresh service report while
# offline, then when the offline queue drains it POSTs here to
# create the row on the server.  The endpoint is idempotent by both
# ``client_uuid`` (row-level) AND ``X-Idempotency-Key`` (request-
# level) — hitting it twice with the same body returns the same row.
class ServiceReportCreateIn(BaseModel):
    job_id: str
    # ``client_uuid`` becomes the canonical ``id`` on the persisted
    # row when provided.  If a report with that id already exists we
    # return it verbatim (no re-bootstrap, no template redetection).
    client_uuid: Optional[str] = None


@router.post("/service-reports", status_code=201)
async def create_service_report(body: ServiceReportCreateIn,
                                     request: Request,
                                     user: dict = Depends(get_current_user),
                                     tenant: dict = Depends(get_current_tenant)):
    from utils_idempotency import replay_or_reserve, store_response
    idem_body = body.dict(exclude_unset=False)
    idem_key, cached = await replay_or_reserve(
        request, tenant["id"], "POST /service-reports", idem_body,
    )
    if cached is not None:
        return cached
    job = await db.jobs.find_one(
        {"id": body.job_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    tech_id = await _authorize_report(job, user)

    # Phase O4 — client-UUID lookup MUST short-circuit before the
    # (tenant, job, tech) uniqueness check so a mobile client that
    # already synced this row gets its own row back (not a different
    # tech's report on the same job).
    if body.client_uuid:
        existing_by_uuid = await db.service_reports.find_one(
            {"id": body.client_uuid, "tenant_id": tenant["id"]}, {"_id": 0},
        )
        if existing_by_uuid:
            if idem_key:
                await store_response(idem_key, "POST /service-reports",
                                      tenant["id"], existing_by_uuid, idem_body)
            return existing_by_uuid

    # Fall through to (tenant, job, tech) uniqueness — a report may
    # already exist for this triple even without a client_uuid match
    # (e.g. the tech opened the report on the web first).
    existing = await db.service_reports.find_one(
        {"tenant_id": tenant["id"], "job_id": body.job_id, "tech_id": tech_id},
        {"_id": 0},
    )
    if existing:
        if idem_key:
            await store_response(idem_key, "POST /service-reports",
                                  tenant["id"], existing, idem_body)
        return existing

    # Fresh bootstrap.  Force the row's ``id`` to the client-minted
    # UUID when provided so mobile can cross-reference locally
    # without a server round-trip.
    fresh = await _bootstrap_report(tenant["id"], job, tech_id)
    if body.client_uuid:
        fresh["id"] = body.client_uuid
        fresh["client_uuid"] = body.client_uuid
    await db.service_reports.insert_one(fresh)
    fresh.pop("_id", None)
    if idem_key:
        await store_response(idem_key, "POST /service-reports",
                              tenant["id"], fresh, idem_body)
    return fresh


@router.get("/jobs/{jid}/service-report")
async def get_service_report(jid: str,
                             user: dict = Depends(get_current_user),
                             tenant: dict = Depends(get_current_tenant)):
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0, "photos.data": 0})
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
    else:
        # Feb-2026 · Checklist reclassifier — if the tech (or admin) has
        # since retagged the job's ``service_type``/``job_type``/``title``
        # via the empty-state picker in the Chemical Readings section, the
        # bootstrap-time ``template`` field on the report is stale. Auto-
        # heal for open reports so the field list on the next line
        # reflects the CURRENT classification. Submitted reports are
        # locked and keep whatever template was frozen at submit.
        if not existing.get("submitted_at"):
            current_kind = _detect_template(job)
            if existing.get("template") != current_kind:
                await db.service_reports.update_one(
                    {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id},
                    {"$set": {"template": current_kind, "updated_at": now_iso()}},
                )
                existing["template"] = current_kind
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
    # Feb-2026 · Water-bodies autosave-wipe recovery — legacy top-level
    # ``chemicals_added`` / ``chemical_readings`` can be an empty list
    # on docs that were corrupted by the pre-fix autosave race (empty
    # top-level clobbered the persisted list; see the guard in
    # ``services.water_bodies.apply_water_bodies_payload``).  Hydrate
    # the empty mirror from ``water_bodies[0]`` at read time so a
    # freshly-loaded checklist shows the chemicals/readings the tech
    # actually recorded.  This is READ-ONLY hydration; persistence
    # stays untouched.  New writes go through the fixed pipeline and
    # keep both channels in sync without needing this fallback.
    _bodies = existing.get("water_bodies") or []
    if _bodies:
        _body0 = _bodies[0] or {}
        _top_chems = existing.get("chemicals_added") or []
        _body_chems = _body0.get("chemicals_used") or []
        if not _top_chems and _body_chems:
            existing["chemicals_added"] = list(_body_chems)
        _top_readings = existing.get("chemical_readings") or []
        _body_readings = _body0.get("readings") or []
        if not _top_readings and _body_readings:
            existing["chemical_readings"] = list(_body_readings)
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
    # Feb-2026 · Repair-mode service log — allow the tech (or a bug-
    # fix admin script) to retag the report between service/repair
    # after bootstrap. Normalized on write; unknown values → 400 in
    # the handler.
    work_class: Optional[str] = None
    # Feb-2026 · Multi-body Phase 1 — canonical per-body array.
    # When present, replaces the ``water_bodies`` on the report doc
    # and mirrors ``chemicals_used`` across all bodies back into the
    # legacy top-level ``chemicals_added`` (so auto-invoice + chemistry
    # usage snapshots continue to see every chemical). The primary
    # ``pool``-typed body's readings become the top-level
    # ``chemical_readings`` so the chemistry required-readings gate
    # keeps operating unchanged.
    water_bodies: Optional[List[Dict[str, Any]]] = None
    # Mobile Phase 2 · Feb-2026 — tech-wins conflict marker. When
    # set, the flush worker declares this write reflects a tech's
    # local edit taken while offline. The handler compares this to
    # the server's current ``updated_at`` and, if the server is
    # newer, logs the overwrite to ``mobile_write_conflicts`` for
    # audit — the tech's write is ACCEPTED regardless (per user
    # directive). Never persisted onto the report document.
    client_updated_at: Optional[str] = None


@router.patch("/jobs/{jid}/service-report")
async def patch_service_report(jid: str, body: ServiceReportPatch,
                               request: Request,
                               background_tasks: BackgroundTasks,
                               user: dict = Depends(get_current_user),
                               tenant: dict = Depends(get_current_tenant)):
    # Phase 40 · Idempotency — offline mobile queues retry on reconnect.
    from utils_idempotency import replay_or_reserve, store_response
    key, cached = await replay_or_reserve(
        request, tenant["id"], "PATCH /jobs/{jid}/service-report",
        body.dict(exclude_unset=True))
    if cached is not None:
        return cached
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0, "photos.data": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    tech_id = await _authorize_report(job, user)
    rep = await db.service_reports.find_one(
        {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id}, {"_id": 0}
    )
    if not rep:
        raise HTTPException(404, "Service report not started — GET first to bootstrap")
    # Feb-2026 · PS-A — technicians on the assigned crew (already
    # vetted upstream by ``_authorize_report`` via
    # ``is_tech_authorized_on_job``) may edit their OWN report even
    # after submit; every post-submit write lands an audit row.
    # Admins / super_admins retain their pre-PS-A behaviour (locked
    # by the 409) — no regression to their existing edit path.
    _post_submit_edit = False
    if rep.get("submitted_at"):
        if (user.get("role") or "") == "technician":
            _post_submit_edit = True
        else:
            raise HTTPException(
                409, "Report has already been submitted and is locked",
            )
    upd = {k: v for k, v in body.dict(exclude_unset=True).items()}
    # Mobile Phase 2 · Feb-2026 — tech-wins conflict audit. Strip
    # ``client_updated_at`` from the persisted payload; use it only
    # to decide whether to write an audit row. Tech's write is
    # ALWAYS accepted per user directive.
    _client_updated_at = upd.pop("client_updated_at", None)
    if _client_updated_at:
        from services.mobile_offline_sync import (
            log_write_conflict, should_log_conflict,
        )
        _srv_upd = rep.get("updated_at")
        if should_log_conflict(_srv_upd, _client_updated_at):
            await log_write_conflict(
                tenant_id=tenant["id"],
                entity_type="service_report",
                entity_id=str(rep.get("id") or jid),
                tech_user_id=user.get("id"),
                fields_overwritten=list(upd.keys()),
                client_updated_at_iso=_client_updated_at,
                server_updated_at_iso=_srv_upd,
            )
    if not upd:
        raise HTTPException(400, "No fields to update")
    # Feb-2026 · Repair retag — normalize + validate before write.
    if "work_class" in upd:
        try:
            from services.work_class import normalize_work_class
            upd["work_class"] = normalize_work_class(upd["work_class"])
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    # Feb-2026 · Multi-body Phase 1 + Chemistry-gate ship — route
    # through the shared ``apply_water_bodies_payload`` helper so
    # the mobile-sync ``service_report.upsert`` handler picks up
    # the exact same semantics. Presence check is ``in upd``
    # (not ``upd.get(...)``) so ``water_bodies: []`` is a
    # deliberate clear, a missing key preserves the persisted
    # value, and legacy top-level ``chemical_readings`` /
    # ``chemicals_added`` / ``notes`` writes sync back into
    # ``water_bodies[0]`` to keep the multi-body surface aligned.
    try:
        apply_water_bodies_payload(upd, rep)
    except WaterBodyValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.detail)
    upd["updated_at"] = now_iso()
    await db.service_reports.update_one(
        {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id},
        {"$set": upd},
    )
    resp = await db.service_reports.find_one(
        {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id}, {"_id": 0}
    )
    # Feb-2026 · PS-A — audit trail for post-submit tech edits.
    # Shallow field-diff (per ruling #2 — no deep-diff library) over
    # only the fields the tech actually wrote.  Metadata columns
    # (``updated_at``) are excluded from the visible diff since
    # they're bookkeeping.  Each save writes a new audit row (per
    # ruling #3 — simpler to query than versioned arrays).
    if _post_submit_edit:
        try:
            _diffs: dict = {}
            for _k in upd.keys():
                if _k in ("updated_at",):
                    continue
                _old = (rep or {}).get(_k)
                _new = (resp or {}).get(_k, upd.get(_k))
                if _old != _new:
                    _diffs[_k] = {"old": _old, "new": _new}
            import uuid as _uuid_pkg
            await db.audit_logs.insert_one({
                "id": _uuid_pkg.uuid4().hex,
                "tenant_id": tenant["id"],
                "actor_id": user.get("id"),
                "actor_email": user.get("email"),
                "actor_role": user.get("role"),
                "event": "service_report_post_submit_edit",
                "at": now_iso(),
                "payload": {
                    "report_id": (resp or rep or {}).get("id"),
                    "job_id": jid,
                    "tech_id": tech_id,
                    "field_diffs": _diffs,
                },
            })
        except Exception as _audit_exc:                          # noqa: BLE001
            # Never fail the tech's PATCH on an audit-write hiccup;
            # the write already landed.  Surfaces in logs so ops
            # can investigate.
            logger.warning(
                f"[ps-a] audit write failed for report {rep.get('id')}"
                f": {_audit_exc}"
            )
    # Task N Round 2 · Phase N.6 — note-transition notifier.  Compares
    # ``rep`` (pre-write snapshot at line 551) against ``resp`` (post-
    # write re-read) and fires email + SMS to the tenant's notification
    # recipients on any empty→populated flip of ``notes`` /
    # ``internal_notes`` / ``customer_notes``.  Debounce collection
    # ``notification_debounce`` guarantees at-most-once delivery per
    # (tenant, SR, field, transition_kind) within 24h.  Never fails the
    # PATCH response — closure catches all exceptions locally.
    try:
        _cust_name = (job.get("customer_name")
                      or (await db.customers.find_one(
                          {"id": job.get("customer_id"),
                            "tenant_id": tenant["id"]},
                          {"_id": 0, "name": 1}) or {}).get("name")
                      or "Customer")
        async def _notify_note_tx(
            _tid=tenant["id"], _tenant=tenant, _rep=rep, _resp=resp or {},
            _sr_id=(resp or rep or {}).get("id") or "",
            _job_id=jid, _cust_name=_cust_name,
            _template=(resp or rep or {}).get("template"),
        ):
            try:
                from services.notes_notifications.notes_change_notifier import (
                    notify_note_transitions as _nn,
                )
                await _nn(
                    db=db, tenant=_tenant,
                    sr_id=_sr_id, job_id=_job_id,
                    customer_name=_cust_name, template=_template,
                    old_sr=_rep or {}, new_sr=_resp,
                )
            except Exception as _e:
                logger.warning(
                    f"[notes-notifier:patch] deferred send failed: {_e}"
                )
        background_tasks.add_task(_notify_note_tx)
    except Exception as _e_outer:
        logger.warning(
            f"[notes-notifier:patch] scheduler crashed: {_e_outer}"
        )
    if key:
        await store_response(key, "PATCH /jobs/{jid}/service-report",
                              tenant["id"], resp,
                              body.dict(exclude_unset=True))
    return resp


# ═══════════════════════════════════════════════════════════════════
# Feb-2026 · PS-A — audit history for post-submit tech edits.
# GET /api/service-reports/{report_id}/audit — admin-only (super_admin
# + manager included).  Lists every ``service_report_post_submit_edit``
# row for a given report in reverse-chronological order so an admin
# can trace exactly who changed what, when, and to what value.
# ═══════════════════════════════════════════════════════════════════
_PS_A_AUDIT_ADMIN_ROLES = {"admin", "super_admin", "manager"}


@router.get("/service-reports/{report_id}/audit")
async def list_service_report_audit(
    report_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if (user.get("role") or "") not in _PS_A_AUDIT_ADMIN_ROLES:
        raise HTTPException(403, "admin_only")
    # Tenant-scoped lookup — confirm the report exists here before
    # exposing audit rows (defence-in-depth against cross-tenant id
    # guessing).
    exists = await db.service_reports.find_one(
        {"id": report_id, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1},
    )
    if not exists:
        raise HTTPException(404, "service_report_not_found")
    cursor = db.audit_logs.find(
        {
            "tenant_id": tenant["id"],
            "event": "service_report_post_submit_edit",
            "payload.report_id": report_id,
        },
        {"_id": 0},
    ).sort("at", -1).limit(500)
    items = await cursor.to_list(500)
    return {"items": items, "total": len(items)}


# ─── POST submit (lock + mark job status) ──────────────────────────────────
@router.post("/jobs/{jid}/service-report/submit")
async def submit_service_report(
    jid: str,
    background_tasks: BackgroundTasks,
    request: Request,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    # Phase O4 · Feb-2026 — Idempotency wiring.  The submit endpoint
    # takes no request body but is the heaviest side-effect surface
    # in the CRM (invoice auto-create, review-request enqueue, drip
    # emit, chemistry snapshot).  A mobile queue that replays this
    # after a 30s timeout MUST see the cached response — otherwise
    # we double-invoice, double-email, and re-snapshot the chemistry.
    from utils_idempotency import replay_or_reserve, store_response
    idem_body: Dict[str, Any] = {}
    idem_key, cached = await replay_or_reserve(
        request, tenant["id"],
        "POST /jobs/{jid}/service-report/submit", idem_body,
    )
    if cached is not None:
        return cached
    # Feb-2026 · P12A — Preventive 520 mitigation.  Cloudflare's
    # 100-second origin timeout was firing on prod (``app.plofv.com``)
    # even though the same handler ran in ~650ms on preview — heavy
    # side-effects (Resend email, RingCentral SMS, automation-engine
    # emits) were pushing the tail past the ingress limit.  This
    # handler now:
    #   1. Runs only inline work needed for the response body +
    #      state mutations that gate future requests.
    #   2. Fires every downstream HTTP-driven side-effect via
    #      ``BackgroundTasks`` so the ingress-level TTL is only
    #      bounded by Mongo write latency.
    #   3. Logs structured ``start`` / ``end`` events with
    #      ``elapsed_ms`` so ops can see the sync path duration in
    #      the prod log stream on any future regression.
    import time as _time_p12a
    _sr_start = _time_p12a.monotonic()
    logger.info(
        f"service_report_submit start job={jid} tenant={tenant['id']}"
    )
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0, "photos.data": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    tech_id = await _authorize_report(job, user)
    rep = await db.service_reports.find_one(
        {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id}, {"_id": 0}
    )
    if not rep:
        raise HTTPException(404, "No report to submit — GET first")
    if rep.get("submitted_at"):
        # App-level idempotency already caught this; still cache the
        # response so the header-level idempotency dedupe path also
        # returns instantly on a subsequent replay.
        if idem_key:
            await store_response(idem_key,
                                  "POST /jobs/{jid}/service-report/submit",
                                  tenant["id"], rep, idem_body)
        return rep  # idempotent
    # Feb-2026 · Chemistry required-readings gate.  Pool jobs MUST
    # have the Required Four (Free Cl, Alkalinity, pH, CYA — see
    # Phase CHEM1) before we accept the submit.  Landscape jobs skip
    # the gate — no chemistry surface on that checklist. Feb-2026 ·
    # Repair-mode addition — a job tagged ``work_class == "repair"``
    # ALSO skips (repair visits are photo/video/notes only per the
    # locked product spec).
    from services.chemistry_gate import (
        assert_bodies_required_readings_present,
        assert_core_readings_present, gather_readings_for_job, is_pool_job,
        missing_core_reading_labels,
    )
    _report_wc = (rep.get("work_class") or "").lower()
    _job_wc = (job.get("work_class") or "").lower()
    _is_repair = "repair" in (_report_wc, _job_wc)
    # Sprint 3b · Feb-2026 — tenant-configurable gate mode.
    #   strict     → block submit if any Required Four missing (current)
    #   warn_only  → allow submit + attach warnings[] on the response
    #   off        → skip the gate entirely
    # Falls back to ``strict`` when the tenant hasn't configured it —
    # zero-regression posture for AZ tenants.
    from services.chemistry_tenant_targets import (
        get_tenant_chemistry_settings,
    )
    _chem_cfg = await get_tenant_chemistry_settings(tenant["id"], db)
    _gate_mode = _chem_cfg.get("gate_mode", "strict")
    _gate_warnings: List[str] = []
    if is_pool_job(job) and not _is_repair and _gate_mode != "off":
        _readings_for_gate = gather_readings_for_job(job, rep)
        if _gate_mode == "warn_only":
            _missing = missing_core_reading_labels(_readings_for_gate)
            if _missing:
                _gate_warnings.append(
                    "chemistry_core_readings_missing: " + ", ".join(_missing),
                )
                logger.info(
                    "[chem-gate-warn] job=%s tenant=%s missing=%s "
                    "gate_mode=warn_only",
                    jid, tenant["id"], _missing,
                )
        else:
            assert_core_readings_present(_readings_for_gate)
            # Phase CHEM1 · Feb-2026 — multi-body enforcement. Iterates
            # every water body whose type requires readings (currently
            # ``pool``) and raises 422 with per-body detail when any
            # Required Four value is missing on any such body.
            assert_bodies_required_readings_present(rep.get("water_bodies"))
    # Phase MI1 · Feb 2026 — required-checklist-item gate for the
    # six non-pool industries (Landscaping / HVAC / Pest Control /
    # Cleaning / Solar / Handyman). Pool jobs continue to use the
    # chemistry gate above and skip this branch. Repair jobs skip
    # entirely — same posture as the chemistry gate. A missing
    # required item raises 400 naming the first unchecked label.
    if not is_pool_job(job) and not _is_repair:
        try:
            from routers.industry_checklists import (
                assert_required_items_present,
                derive_industry_for_job,
                get_industry_checklist,
            )
            _ind = derive_industry_for_job(job, tenant)
            if _ind != "pool":
                _resolved = await get_industry_checklist(tenant["id"], _ind)
                _completed = rep.get("checklist_completed") or rep.get("checklist_items") or []
                _checked_keys: List[str] = []
                for _c in _completed:
                    if isinstance(_c, dict) and _c.get("done"):
                        _checked_keys.append(str(_c.get("key") or _c.get("label") or ""))
                assert_required_items_present(_ind, _checked_keys, _resolved)
        except HTTPException:
            raise
        except Exception as _mi1_e:                              # noqa: BLE001
            logger.warning(f"[mi1] required-items gate errored: {_mi1_e}")
    now = now_iso()
    # ── Phase P45 · Feb-2026 · atomic claim gate ──────────────────
    # The atomic gate is the ONLY writer of ``submitted_at`` on the
    # service-report row.  Prior to P45 the write below at line
    # ``_submit_updates`` set ``submitted_at`` unconditionally,
    # which produced a TOCTOU race between the ``rep.get("submitted_at")``
    # read at ~L667 and the write here — two concurrent submits could
    # both pass the read + both write, then both enqueue email/SMS
    # background tasks (double customer email).  The gate below
    # replaces that unconditional write with a
    # ``findOneAndUpdate`` that only matches when ``submitted_at`` is
    # null/empty; the second concurrent submit gets ``claim=None``
    # and is short-circuited as idempotent — exactly the response
    # shape the historic ``if rep.get("submitted_at"): return rep``
    # branch produced.  Also stamps ``email_pending_at`` +
    # ``sms_pending_at`` in the same write for the notification
    # enqueue gate later in the handler.
    from services.service_report_submit_gate import claim_submit_or_none
    _p45_claim = await claim_submit_or_none(
        tenant_id=tenant["id"],
        report_id=rep.get("id"),
        job_id=jid, tech_id=tech_id,
        now_iso=now,
    )
    if _p45_claim is None:
        logger.info(
            "[p45] concurrent-submit idempotency: job=%s tech=%s tenant=%s"
            " — returning cached report shape",
            jid, tech_id, tenant["id"],
        )
        # Return the current row so callers get a coherent response.
        _cached = await db.service_reports.find_one(
            {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id},
            {"_id": 0},
        )
        if idem_key and _cached:
            await store_response(idem_key,
                                  "POST /jobs/{jid}/service-report/submit",
                                  tenant["id"], _cached, idem_body)
        return _cached or rep
    # ── /Phase P45 ────────────────────────────────────────────────
    # Phase 22 · Feb 2026 — backfill ``public_uuid`` on submit for
    # reports that were bootstrapped before the field existed. Safe
    # for freshly-bootstrapped reports too (idempotent when set).
    # NB (P45): ``submitted_at`` is intentionally NOT in
    # ``_submit_updates`` anymore — the atomic gate above owns it.
    _submit_updates: Dict[str, Any] = {"updated_at": now}
    if not rep.get("public_uuid"):
        _submit_updates["public_uuid"] = new_id()
        rep["public_uuid"] = _submit_updates["public_uuid"]
    # CHEM-LOCK · Feb-2026 — resubmit stale-report flag.
    # If this SR was previously submitted and then admin-unlocked
    # (``previously_submitted_at`` set by ``POST /jobs/{jid}/unlock``),
    # stamp ``superseded_at`` with the ORIGINAL submitted_at so the
    # portal renderer can show the "Report updated after original
    # send" banner. Also clear ``previously_submitted_at`` so a
    # third submit cycle doesn't re-stamp with a stale value.
    _p45_claim_rep = _p45_claim or {}
    if _p45_claim_rep.get("previously_submitted_at"):
        _submit_updates["superseded_at"] = _p45_claim_rep[
            "previously_submitted_at"]
        _submit_updates["superseded_by_submit_at"] = now
    await db.service_reports.update_one(
        {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id},
        {"$set": _submit_updates},
    )
    # Roll job status forward. Preserve existing lifecycle: use `completed` since
    # that already exists across the codebase.
    _prev_status = (job.get("status") or "").lower()
    # Feb-2026 · P37a — auto-stop the job timer on service-report
    # submit path. Mirrors the PUT /jobs/{jid} status→completed
    # branch. Only stamps if the timer is currently running.
    _stop_updates: dict = {"status": "completed",
                                "service_report_submitted_at": now,
                                "updated_at": now}
    if job.get("timer_started_at") and not job.get("timer_stopped_at"):
        try:
            from datetime import datetime as _dt
            _st = _dt.fromisoformat(str(job["timer_started_at"]).replace("Z", "+00:00"))
            _en = _dt.fromisoformat(now.replace("Z", "+00:00"))
            _dur = int(max(0, (_en - _st).total_seconds()))
        except Exception:
            # 2026-10-02 · duration_seconds=0 fix — parse failure
            # yields ``None`` (not ``0``) so a malformed
            # ``timer_started_at`` is diagnostically distinct from
            # a legitimate 0-second duration. Mongo stores ``null``;
            # the ``{"duration_seconds": {"$gt": 0}}`` dashboard
            # filter naturally excludes it.
            _dur = None
        _stop_updates["timer_stopped_at"] = now
        _stop_updates["timer_duration_seconds"] = _dur
        _stop_updates["timer_stop_method"] = "service_report_submitted"
        # Audit-log breadcrumb (best-effort; never blocks submit).
        try:
            await db.audit_logs.insert_one({
                "id": _submit_updates.get("id") or None,
                "tenant_id": tenant["id"],
                "actor_id": user.get("id"),
                "actor_email": user.get("email"),
                "event": "job_timer_auto_stop",
                "at": now,
                "payload": {"job_id": jid, "method": "service_report_submitted",
                                "duration_seconds": _dur},
            })
        except Exception:
            pass

    # ── P0 · Feb-2026 · Chemical snapshot BEFORE status flip ─────
    # Prior implementation ran ``snapshot_chemical_usage`` AFTER
    # the ``db.jobs.update_one({"status": "completed"})`` call
    # below AND silently swallowed any snapshot failure via
    # ``logger.warning``. Result: chemicals were silently missing
    # from customer reports on every transient snapshot failure
    # (Mongo write pressure, catalog drift, per-line coerce
    # errors, ...) while the job was already marked completed.
    #
    # Fix:
    #   1. Snapshot fires HERE — after the P45 atomic claim
    #      (which stamps ``submitted_at`` on the report row) but
    #      BEFORE the job status flips to ``completed``.
    #   2. On failure, ``rollback_submit_claim`` unsets the P45
    #      stamps (``submitted_at`` / ``email_pending_at`` /
    #      ``sms_pending_at``) so the L708 idempotency
    #      short-circuit does NOT fire on retry — the client can
    #      re-submit and the snapshot re-fires cleanly.
    #   3. HTTPException(500) propagates so the caller knows the
    #      ledger commit failed. Diagnostic log line preserved
    #      for ops triage (not swallowed).
    #
    # Snapshot is idempotent per ``service_report_id`` (delete_many
    # + insert loop inside the helper), so a legitimate double-fire
    # never double-counts. The retry-after-rollback path is safe.
    #
    # See ``services.service_report_submit_gate.rollback_submit_claim``
    # for the exact field-list mirrored from ``claim_submit_or_none``.
    try:
        from routers.chemical_products import snapshot_chemical_usage
        # Re-fetch to catch any client PATCH that landed between the
        # initial L703 fetch and the P45 claim write at L840. The
        # snapshot must see the freshest ``chemicals_added`` /
        # ``water_bodies`` on the report doc.
        _sr_for_snapshot = await db.service_reports.find_one(
            {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id},
            {"_id": 0},
        ) or rep
        # Feb-2026 · Multi-body Phase 1 · Option 2 · Bug 2 rework —
        # prefer ``water_bodies`` so each event carries a
        # ``water_body_id`` for the chemical-cost report's
        # per-body rollup. Legacy top-level ``chemicals_added`` is
        # kept as the fallback so a single-body report (or a
        # report loaded from cache with only the legacy fields)
        # still snapshots correctly under the ``Legacy`` bucket.
        _snapshot_bodies = _sr_for_snapshot.get("water_bodies") or None
        await snapshot_chemical_usage(
            tenant_id=tenant["id"],
            job_id=jid,
            service_report_id=_sr_for_snapshot.get("id") or rep.get("id"),
            customer_id=job.get("customer_id"),
            chemicals_added=(
                None if _snapshot_bodies
                else (_sr_for_snapshot.get("chemicals_added") or [])
            ),
            water_bodies=_snapshot_bodies,
            occurred_at=job.get("scheduled_date")
                         or job.get("scheduled_start")
                         or now,
            actor_user_id=user.get("id"),
        )
    except Exception as _snap_e:                                # noqa: BLE001
        # Preserve the diagnostic log line — ops needs the report/
        # tenant/exception surface to triage. Then roll back the
        # P45 claim so a retry re-fires the snapshot cleanly, and
        # raise 500 so the caller knows the submit was NOT applied.
        logger.warning(
            "chemistry snapshot failed job=%s tenant=%s report=%s"
            " — rolling back P45 claim: %s",
            jid, tenant["id"], rep.get("id"), _snap_e,
        )
        try:
            from services.service_report_submit_gate import (
                rollback_submit_claim,
            )
            await rollback_submit_claim(
                tenant_id=tenant["id"],
                report_id=rep.get("id"),
                job_id=jid, tech_id=tech_id,
            )
        except Exception as _rb_e:                              # noqa: BLE001
            # Rollback failure ON TOP of snapshot failure — surface
            # both in the 500 payload so ops can triage without a
            # log-dive. Doc row may now be in a mixed state
            # (submitted_at set, no ledger, no status flip) — the
            # next submit retry will hit L708 idempotency and
            # return the cached rep; ops must manually unstamp.
            logger.error(
                "P45 rollback also failed job=%s tenant=%s report=%s"
                " — MANUAL INTERVENTION REQUIRED: %s",
                jid, tenant["id"], rep.get("id"), _rb_e,
            )
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "chemistry_snapshot_failed_rollback_failed",
                    "message": (
                        "Chemistry ledger commit failed AND P45"
                        " claim rollback failed — manual"
                        " intervention required."
                    ),
                    "snapshot_error": str(_snap_e),
                    "rollback_error": str(_rb_e),
                },
            ) from _snap_e
        raise HTTPException(
            status_code=500,
            detail={
                "code": "chemistry_snapshot_failed",
                "message": (
                    "Chemistry ledger commit failed — submit"
                    " rolled back. Please retry."
                ),
                "error": str(_snap_e),
            },
        ) from _snap_e
    # ── /P0 · Chemical snapshot BEFORE status flip ───────────────

    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"]},
        {"$set": _stop_updates,
         # CHEM-LOCK · Feb-2026 — auto-relock on resubmit. Clear
         # the admin-unlock stamps so the job returns to the
         # "submitted and locked" state; the SR's ``submitted_at``
         # (just set by the P45 claim gate) IS the lock.
         "$unset": {"unlocked_at": "", "unlocked_by": "",
                    "unlocked_by_email": "", "unlocked_reason": ""}},
    )
    # Feb-2026 · Job Timers Phase 1 — close every open ``job_timers``
    # row for this job. Runs after the job doc has been flipped to
    # ``completed`` so ``ended_at`` and ``duration_seconds`` on
    # timers stay aligned with the job lifecycle. Best-effort — a
    # timer-close failure MUST NOT block the service-report submit.
    try:
        from routers.job_timers import close_open_timers_for_job
        _closed = await close_open_timers_for_job(
            job_id=jid, tenant_id=tenant["id"],
            actor_user_id=user.get("id"),
        )
        if _closed:
            logger.info(
                f"[job_timers.auto_close] job={jid} closed={_closed}",
            )
    except Exception as _tc_exc:                                # noqa: BLE001
        logger.warning(
            f"[job_timers.auto_close] job={jid} failed: {_tc_exc}",
        )
    # Feb-2026 · Recurring-jobs on-complete safety net.
    # Fires on the pending→completed transition only (resubmit of an
    # already-completed service report is a no-op for the recurring
    # cadence). If the parent job was recurring and the nightly cron
    # hasn't materialized the next occurrence yet, insert it here so
    # the Schedule view never shows a gap. Idempotent via
    # ``(tenant, template, scheduled_date)`` dedupe inside the helper.
    # Failures are NON-FATAL — the service-report submit already
    # succeeded; we must not surface a 500 on a background self-heal.
    if _prev_status != "completed":
        try:
            from services.recurring_jobs_backfill import (
                materialize_next_from_completed_job,
            )
            await materialize_next_from_completed_job(
                job={**job, **_stop_updates, "id": jid},
                tenant_id=tenant["id"],
                actor_user_id=user.get("id"),
            )
        except Exception as _sn_exc:                            # noqa: BLE001
            logger.warning(
                "recurring_job.on_complete_safety_net.failed "
                "tenant=%s parent_job=%s error=%s:%s",
                tenant["id"], jid, type(_sn_exc).__name__, _sn_exc,
            )
    # Feb-2026 · Door-hanger auto-send on completion transition.
    # ── Phase P45 · Feb-2026 · SUPERSEDED ─────────────────────────
    # The auto ``schedule_auto_send_door_hanger`` call that used to
    # live here fired IN ADDITION to ``_bg_send_visit_summary_email``
    # (below at ~L1306), producing TWO customer-facing emails per
    # submit.  P45 kills the auto door-hanger schedule; the manual
    # ``POST /api/jobs/{jid}/email-door-hanger`` endpoint keeps
    # ``schedule_auto_send_door_hanger`` as its send helper.
    # The atomic gate ``claim_submit_or_none`` (invoked at the
    # bg-tasks enqueue block below) now guarantees exactly-once
    # notification enqueue across concurrent submit/completion
    # races.
    # ──────────────────────────────────────────────────────────────
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

    # Feb-2026 · Bug 2 fix — Chemistry Profitability was reading $0
    # for every customer on production because the legacy PUT
    # /jobs/{jid} field-report path was the ONLY caller of
    # ``snapshot_chemical_usage``.  The modern tech-facing flow
    # writes ``chemicals_added`` onto the service_report doc via
    # PATCH and locks with this submit — but never emitted the
    # per-line ``chemical_usage_events`` rows that the
    # ``GET /pools/{pool_id}/chemical-profitability`` rollup (and
    # the Chemistry History page) aggregate over.
    #
    # ── P0 · Feb-2026 · MOVED ─────────────────────────────────────
    # The ``snapshot_chemical_usage`` call previously ran HERE
    # (AFTER the ``db.jobs.update_one`` status flip above and
    # wrapped in a silent ``logger.warning`` swallow).  It was
    # relocated to fire BEFORE the status flip so a snapshot
    # failure no longer leaves the job marked completed with no
    # ledger.  On snapshot failure the P45 claim is rolled back
    # and a 500 propagates so the tech can retry cleanly.  See
    # the ``P0 · Feb-2026 · Chemical snapshot BEFORE status flip``
    # comment block earlier in this handler for the reasoning +
    # the exact call site.
    # ──────────────────────────────────────────────────────────────

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
    # report both show chlorine <= 0.5 ppm, write an algae_risk_flags
    # entry so the office sees the at-risk customer on the retention report.
    try:
        from routers.reports import evaluate_algae_risk
        await evaluate_algae_risk(tenant["id"], job.get("customer_id"))
    except Exception as e:
        logger.warning(f"algae-risk evaluation failed: {e}")

    # Phase 20A.2 — auto-generate an invoice when the tenant setting allows,
    # the job is billable, and it has a positive price. Reuses the referral-
    # credit application path so 50%-off credits still land correctly.
    #
    # Task M+P · Feb-2026 · Commit 3 — Reopen re-submit idempotency.
    # A job that already has ``auto_invoice_id`` / ``auto_invoice_created_at``
    # stamped went through this branch on an earlier submit; the reopen
    # → re-submit cycle must NOT create a duplicate invoice.  Check
    # both sentinels (B2 decision) — either one being set is enough
    # to prove we already fired.  On skip, emit an ``activity_logs``
    # row (B3) with ``type=auto_invoice_skipped_duplicate`` so ops can
    # grep how often the guard fires post-launch.  Downstream events
    # (``invoice.created``, ``service_report.finalized``) still fire on
    # re-submit per D1 — their consumers own idempotency (matches the
    # drip ledger's unique-index pattern already in place).
    invoice_id = None
    prior_invoice_id = job.get("auto_invoice_id")
    prior_invoice_at = job.get("auto_invoice_created_at")
    if prior_invoice_id or prior_invoice_at:
        # Skip — invoice already fired on a prior submit.  Emit the
        # audit row fire-and-forget so a Mongo blip on activity_logs
        # never fails the submit response.
        try:
            await db.activity_logs.insert_one({
                "id": new_id(),
                "tenant_id": tenant["id"],
                "job_id": jid,
                "sr_id": rep.get("id"),
                "type": "auto_invoice_skipped_duplicate",
                "actor_id": user.get("id"),
                "actor_name": user.get("name", ""),
                "reason": "reopen_resubmit",
                "metadata": {
                    "prior_invoice_id": prior_invoice_id,
                    "prior_invoice_at": prior_invoice_at,
                },
                "at": now_iso(),
                "created_at": now_iso(),
            })
        except Exception as _audit_exc:  # noqa: BLE001
            logger.warning(
                "[task-mp] auto_invoice_skipped_duplicate audit "
                "insert failed job=%s tenant=%s err=%s",
                jid, tenant["id"], _audit_exc,
            )
        logger.info(
            "[task-mp] auto_invoice skipped on re-submit "
            "job=%s tenant=%s prior_invoice_id=%s",
            jid, tenant["id"], prior_invoice_id,
        )
    else:
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
                # Task SS/RR Phase 2 · Feb 2026 — cents-denominated credit
                # auto-apply. Runs AFTER the legacy referral percent-off
                # hook so the two are additive: percent-off shrinks the
                # invoice first, then the flat credit consumes what's left.
                try:
                    from services.credits_apply import apply_and_persist
                    invoice = await apply_and_persist(db, tenant["id"], invoice)
                except Exception as e:
                    logger.warning(f"cents-credit apply skipped: {e}")
                # Feb-2026 · P0 fix — the service-report auto-invoice path
                # was the primary source of ``invoice_number: null`` rows on
                # production (see Hector Guerrero's "Service — Filter
                # Service" invoice). Route through the canonical
                # ``insert_invoice`` helper so the number gets assigned +
                # validated before Motor sees the doc.
                from services.invoice_numbering import insert_invoice
                invoice = await insert_invoice(invoice, tenant)
                invoice_id = inv_id
                # Task M+P · Feb-2026 · Commit 3 — Stamp the sentinel
                # fields on the job so the next submit (post-reopen) can
                # short-circuit via the ``prior_invoice_id`` /
                # ``prior_invoice_at`` guard above.  Matches the
                # ``services/auto_invoice.py::run`` stamping pattern
                # (see L261-265 of that file) so both auto-invoice
                # writers share a consistent sentinel shape.
                try:
                    await db.jobs.update_one(
                        {"id": jid, "tenant_id": tenant["id"]},
                        {"$set": {
                            "auto_invoice_id": inv_id,
                            "auto_invoice_created_at": now_iso(),
                        }},
                    )
                except Exception as _stamp_exc:  # noqa: BLE001
                    logger.warning(
                        "[task-mp] auto_invoice_id stamp failed "
                        "job=%s inv=%s err=%s",
                        jid, inv_id, _stamp_exc,
                    )
                # Comms Phase 3 — auto-invoice from a submitted service
                # report still fires invoice.created so admins can wire a
                # confirmation email/SMS on it.
                # Feb-2026 · P12A — fired as a BackgroundTask so a slow
                # Resend / webhook adapter cannot push the request past
                # Cloudflare's 100s edge timeout on prod.
                try:
                    async def _emit_invoice_created(_inv=invoice, _tid=tenant["id"], _cid=invoice.get("customer_id")):
                        try:
                            from services.automation_engine import emit as _emit
                            await _emit(
                                "invoice.created",
                                {"invoice": _inv,
                                  "customer": {"id": _cid,
                                                "name": _inv.get("customer_name")},
                                  "source": "service_report_auto"},
                                tenant_id=_tid,
                                entity_kind="invoice", entity_id=_inv["id"],
                                customer_id=_cid,
                            )
                        except Exception as e:  # noqa: BLE001
                            logger.warning(f"[p12a-bg] invoice.created emit failed: {e}")
                    background_tasks.add_task(_emit_invoice_created)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"auto-invoice failed: {e}")

    out = await db.service_reports.find_one(
        {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id}, {"_id": 0}
    )
    # Comms Phase 3 — fire service_report.finalized. Non-blocking.
    # Feb-2026 · P12A — deferred to BackgroundTasks so Resend /
    # webhook fan-out cannot bound the response tail latency.
    try:
        async def _emit_finalized(_out=out or rep, _job=job, _tid=tenant["id"]):
            try:
                from services.automation_engine import emit as _emit
                await _emit(
                    "service_report.finalized",
                    {"service_report": _out, "job": _job,
                      "customer": {"id": _job.get("customer_id"),
                                    "name": _job.get("customer_name")}},
                    tenant_id=_tid,
                    entity_kind="service_report",
                    entity_id=(_out or {}).get("id") or "",
                    customer_id=_job.get("customer_id"),
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[p12a-bg] service_report.finalized emit failed: {e}")
        background_tasks.add_task(_emit_finalized)
    except Exception:
        pass
    # Task N Round 2 · Phase N.6 — submit-time note notifier.  Fires
    # a distinct "[Industry] Service report submitted — notes attached
    # — Customer" fanout if ANY of the 3 note fields is non-empty at
    # submit.  Debounce composite key differs from the patch-time
    # kind (``submit_finalize`` vs ``patch_transition``) so this
    # belt-and-suspenders send always gets a chance to fire even if
    # a per-field patch_transition already fired earlier.
    try:
        async def _notify_submit_finalize(
            _tenant=tenant, _job=job, _out=out or rep,
            _tid=tenant["id"],
        ):
            try:
                from services.notes_notifications.notes_change_notifier import (
                    notify_submit_finalize as _nsf,
                )
                _cust = (_job.get("customer_name")
                          or (await db.customers.find_one(
                              {"id": _job.get("customer_id"),
                                "tenant_id": _tid},
                              {"_id": 0, "name": 1}) or {}).get("name")
                          or "Customer")
                await _nsf(
                    db=db, tenant=_tenant,
                    sr_id=(_out or {}).get("id") or "",
                    job_id=jid, customer_name=_cust,
                    template=(_out or {}).get("template"),
                    new_sr=_out or {},
                )
            except Exception as _e:
                logger.warning(
                    f"[notes-notifier:submit] deferred send failed: {_e}"
                )
        background_tasks.add_task(_notify_submit_finalize)
    except Exception as _e_outer:
        logger.warning(
            f"[notes-notifier:submit] scheduler crashed: {_e_outer}"
        )
    # Feb-2026 · Marketing Slice M5c — drip event bus (service_completed).
    # P0 Fix 2a — pass the service_report id so the event ledger's
    # unique index dedupes retries against the same submission.
    # Feb-2026 · P12A — deferred; drip fan-out talks to Resend / SMS
    # adapters downstream so must not bound response latency.
    try:
        if job.get("customer_id"):
            async def _drip_bg(_tid=tenant["id"], _cid=job["customer_id"],
                                 _sr_id=(out or rep or {}).get("id"), _jid=jid):
                try:
                    from services.marketing.drip_events import on_event as _drip_on_event
                    await _drip_on_event(
                        "service_completed", _tid, _cid,
                        meta={"service_report_id": _sr_id, "job_id": _jid},
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[p12a-bg] drip service_completed failed: {e}")
            background_tasks.add_task(_drip_bg)
    except Exception:
        pass
    # Feb 2026 · Phase 1 Custom Trigger Builder — chemistry_out_of_range
    # emission. Fires only when at least one banded core reading falls
    # OUTSIDE the "Average" band on this submitted report. Fire-and-
    # forget via BackgroundTasks so we never bound the submit
    # response.
    try:
        if job.get("customer_id"):
            async def _phase1_chem_bg(_tenant_id=tenant["id"],
                                        _cid=job["customer_id"],
                                        _jid=jid,
                                        _sr_id=(out or rep or {}).get("id"),
                                        _rep=out or rep):
                try:
                    from services.chemistry_bands import (
                        band_for_reading, BAND_AVERAGE,
                    )
                    from services.chemistry_gate import (
                        gather_readings_for_job,
                    )
                    readings = gather_readings_for_job(
                        {"id": _jid}, _rep or {},
                    ) or {}
                    out_of_range: List[str] = []
                    for k, v in (readings.items() if isinstance(readings, dict) else []):
                        band = band_for_reading(k, v)
                        if band and band != BAND_AVERAGE:
                            out_of_range.append(k)
                    if out_of_range:
                        from services.marketing.event_dispatcher import (
                            emit_event,
                        )
                        await emit_event(
                            event="chemistry_out_of_range",
                            tenant_id=_tenant_id,
                            entity_id=_jid,
                            customer_id=_cid,
                            payload_extras={
                                "job_id": _jid,
                                "service_report_id": _sr_id,
                                "out_of_range": out_of_range,
                                "correlation_id":
                                    f"{_jid}:chem_oor:{_sr_id or ''}",
                            },
                        )
                except Exception as _ce:  # noqa: BLE001
                    logger.warning(
                        "[phase1] chemistry_out_of_range emit failed: %s",
                        _ce,
                    )
            background_tasks.add_task(_phase1_chem_bg)
    except Exception:
        pass
    # Feb-2026 · Marketing Slice M6 — enqueue automated review request
    # when the tenant has opted in.  Non-blocking + duplicate-guarded.
    # Feb-2026 · P12A — deferred.  Enqueue itself writes to a Mongo
    # queue collection which is fast, but the underlying scheduler
    # sometimes flushes an immediate first-send inline — deferring
    # here removes that tail from the request path unconditionally.
    try:
        if job.get("customer_id"):
            async def _review_bg(_tid=tenant["id"], _cid=job["customer_id"],
                                    _sr_id=(out or rep or {}).get("id")):
                try:
                    from routers.marketing_review_requests import (
                        enqueue_from_service_completed,
                    )
                    await enqueue_from_service_completed(_tid, _cid, _sr_id)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[p12a-bg] review request enqueue failed: {e}")
            background_tasks.add_task(_review_bg)
    except Exception:
        pass
    # Phase 56.20 — Auto End-of-Visit Customer Email.
    # Non-blocking: any exception is caught + logged inside the service.
    # Phase 34 · Task U · Feb 2026 — this is now ALWAYS fired on job
    # completion (no "Do you want to send?" prompt / opt-in checkbox).
    # Idempotent: if a prior submit already stamped
    # ``customer_notified.email_sent_at`` we skip. Tenant opt-out via
    # ``settings.notifications.auto_send_completion`` (default TRUE).
    tenant_notify = ((tenant.get("settings") or {}).get("notifications") or {})
    auto_send_completion = tenant_notify.get("auto_send_completion")
    if auto_send_completion is None:
        auto_send_completion = True
    # Feb-2026 · Ticket #3 · Org toggle. Independent of the legacy
    # ``auto_send_completion`` — either being OFF suppresses the
    # summary. Admin flips this from Org Settings → Notifications.
    from services.org_settings import (
        is_org_notification_enabled, log_notification_skipped,
    )
    if not is_org_notification_enabled(tenant, "job_completion_summary"):
        log_notification_skipped(tenant.get("id") or "",
                                    "job_completion_summary")
        auto_send_completion = False
    already_notified = (out or rep or {}).get("customer_notified") or {}

    # Belt-and-braces: legacy clients may still send
    # ``also_notify_customer=false`` in the request body. Task U
    # removed the opt-out UI — the tech can no longer skip the send.
    # Log a WARN so ops can spot stale mobile builds.
    try:
        legacy_opt_out = False
        # ``body`` isn't in scope for every submit path; guard.
        if "body" in locals():
            _b = locals().get("body")
            if _b and (
                getattr(_b, "also_notify_customer", None) is False
                or getattr(_b, "send_email", None) is False
                or getattr(_b, "send_sms", None) is False
            ):
                legacy_opt_out = True
        if legacy_opt_out:
            logger.warning(
                "[task-u] legacy opt-out flag ignored on job=%s tenant=%s — "
                "notifications will still fire", jid, tenant["id"],
            )
    except Exception:  # pragma: no cover
        pass

    email_result_status = None
    sms_result_status = None
    # Feb-2026 · P12A — Resend (visit-summary email) + RingCentral
    # (companion SMS) are the two biggest external HTTP calls in
    # this endpoint.  Both are deferred to BackgroundTasks so
    # neither can hold the request past Cloudflare's 100s edge
    # timeout on prod.  We stamp ``queued`` inline so the response
    # shape (``customer_notified.email_status`` / ``sms_status``)
    # stays populated for the client; the background task later
    # UPDATE_ONE's the persisted row with the real provider status.
    _tech_uid = user["id"]
    _tenant_id = tenant["id"]

    async def _bg_send_visit_summary_email(_tenant=tenant, _job=job,
                                              _report=out or rep,
                                              _tid=_tenant_id, _jid=jid,
                                              _uid=_tech_uid):
        try:
            from services.auto_visit_email import send_visit_summary_email
            email_row = await send_visit_summary_email(_tenant, _job, _report)
            if email_row:
                await db.service_reports.update_one(
                    {"tenant_id": _tid, "job_id": _jid, "tech_id": _uid},
                    {"$set": {
                        "visit_summary_email_id": email_row.get("id"),
                        "visit_summary_email_status": email_row.get("status"),
                        "customer_notified.email_status": email_row.get("status") or "sent",
                        "customer_notified.email_sent_at":
                            now_iso() if email_row.get("status") in (
                                "sent", "queued", "dry_run", "mocked",
                            ) else None,
                    }},
                )
                # ── Phase P45 · Feb-2026 · sent-marker migration ──
                # Move ``email_pending_at`` → ``email_sent_at`` so
                # the atomic gate's pending queue drains as sends
                # complete.  Best-effort; a stamp failure MUST NOT
                # crash the bg task.
                if email_row.get("status") in (
                    "sent", "queued", "dry_run", "mocked",
                ):
                    from services.service_report_submit_gate import (
                        stamp_email_sent,
                    )
                    await stamp_email_sent(
                        tenant_id=_tid, job_id=_jid, tech_id=_uid,
                    )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[p12a-bg] auto visit-summary email failed: {e}")
            await db.service_reports.update_one(
                {"tenant_id": _tid, "job_id": _jid, "tech_id": _uid},
                {"$set": {"customer_notified.email_status": "failed"}},
            )

    async def _bg_send_completion_sms(_tenant=tenant, _job=job, _tid=_tenant_id,
                                          _jid=jid, _uid=_tech_uid):
        # ── Phase P45 · Feb-2026 · SMS-body defensive contract ────
        # The SMS path MUST NOT include any image, logo, HTML tag,
        # or asset URL.  SMS is plain text only — logo/branding
        # lives EXCLUSIVELY in the email path
        # (``services.auto_visit_email``).  The body is composed by
        # ``services.completion_sms_template.build_completion_sms_body``,
        # which is enforced plain-text by
        # ``test_sms_body_contains_no_html_or_image_references`` in
        # ``test_p45_visit_summary_dedup_and_absolute_urls.py``.
        # ──────────────────────────────────────────────────────────
        # ── P2 #10e · Feb-2026 — tenant-wide kill switch ──────────
        # Default True on unset; admin opts out via
        # ``PATCH /tenants/mine/settings {completion_followup_sms_enabled: false}``.
        # When False, the background task returns before any DB
        # work, deny-list scan, or RC send — mirrors the gate posture
        # of ``services.lead_conversion_notifications::_send_welcome_email``.
        try:
            from services.completion_sms_template import (
                should_send_completion_followup_sms,
            )
            if not await should_send_completion_followup_sms(_tid):
                await db.service_reports.update_one(
                    {"tenant_id": _tid, "job_id": _jid, "tech_id": _uid},
                    {"$set": {"customer_notified.sms_status":
                                "tenant_disabled"}},
                )
                return
        except Exception as _gate_exc:  # noqa: BLE001
            # Fail-open posture — a gate-helper failure must never
            # blank the SMS. Log + fall through to the normal path.
            logger.warning(
                "[task-u] completion-sms gate helper failed, falling "
                "through to send: %s", _gate_exc,
            )
        try:
            customer = await db.customers.find_one(
                {"id": _job.get("customer_id"), "tenant_id": _tid},
                {"_id": 0, "phone": 1, "name": 1, "first_name": 1, "last_name": 1},
            ) or {}
            phone = customer.get("phone") or ""
            if not phone:
                await db.service_reports.update_one(
                    {"tenant_id": _tid, "job_id": _jid, "tech_id": _uid},
                    {"$set": {"customer_notified.sms_status": "no_phone"}},
                )
                return
            # SMS-RECIPIENT-FIX · Feb-2026 — customer-facing deny-list
            # guardrail. If the resolved recipient maps to a workforce
            # user, the tenant business-card phone, the RC_FROM_NUMBER
            # env, or the COMMS_TEST_ALLOWLIST_PHONES overlap, strip
            # and record ``denied_admin_owned_recipient`` instead of
            # delivering. See
            # ``services/comms_hardening/deny_list.py`` for the
            # scanner logic and ``on_my_way.py:321-333`` for the
            # original pattern.
            from services.comms_hardening.deny_list import (
                strip_admin_owned_recipients,
            )
            _kept, _stripped = await strip_admin_owned_recipients(
                tenant_id=_tid, kind="customer_facing", channel="sms",
                recipients=[phone],
                context={"trigger": "completion_sms",
                          "job_id": _jid,
                          "customer_id": _job.get("customer_id")},
            )
            if _stripped:
                logger.warning(
                    "[task-u] completion SMS denied_admin_owned_recipient "
                    "tenant=%s job=%s customer=%s phone=%s",
                    _tid, _jid, _job.get("customer_id"), phone,
                )
                await db.service_reports.update_one(
                    {"tenant_id": _tid, "job_id": _jid, "tech_id": _uid},
                    {"$set": {"customer_notified.sms_status":
                                "denied_admin_owned_recipient"}},
                )
                return
            phone = _kept[0] if _kept else phone
            import os as _os_task_u
            app_url = _os_task_u.environ.get("APP_PUBLIC_URL", "").rstrip("/")
            portal_link = f"{app_url}/portal/service-reports"
            # Phase COMM1 · Feb-2026 — build the concise template.
            # See ``services.completion_sms_template.build_completion_sms_body``
            # for the rules (first-name derivation, title trim,
            # per-tenant business name).
            #
            # TE-portal-job · Feb-2026 — DB-first path. Resolve the
            # tenant's ``marketing_templates`` row (``code=
            # job_completion_sms``) BEFORE the sync build; passing
            # ``body_template=`` short-circuits the loader with the
            # DB body. Missing/inactive row → the sync function
            # falls back to its i18n loader → inline hardcoded chain.
            from services.completion_sms_template import (
                build_completion_sms_body,
            )
            _db_tpl_body = None
            try:
                from services.marketing_template_lookup import (
                    get_template_by_code,
                )
                _tpl = await get_template_by_code(
                    "job_completion_sms", _tid,
                )
                if _tpl and _tpl.get("body"):
                    _db_tpl_body = _tpl["body"]
            except Exception as _te_exc:  # noqa: BLE001
                logger.warning(
                    "[te-portal-job] job_completion_sms DB lookup "
                    "failed for tenant=%s: %s", _tid, _te_exc,
                )
            sms_body = build_completion_sms_body(
                tenant=_tenant, job=_job, customer=customer,
                portal_link=portal_link,
                body_template=_db_tpl_body,
            )
            from services.sms.rc_adapter import send as _send_sms
            sms_res = await _send_sms(
                to=phone, body=sms_body,
                category="transactional",
                tenant_id=_tid,
                customer_id=_job.get("customer_id"),
            )
            provider_status = sms_res.get("provider_status") or "sent"
            logger.info(
                "[task-u] completion sms to=%s status=%s job=%s",
                phone, provider_status, _jid,
            )
            await db.service_reports.update_one(
                {"tenant_id": _tid, "job_id": _jid, "tech_id": _uid},
                {"$set": {
                    "customer_notified.sms_status": provider_status,
                    "customer_notified.sms_sent_at":
                        now_iso() if provider_status in (
                            "sent", "queued", "dry_run", "mocked",
                        ) else None,
                }},
            )
            # ── Phase P45 · Feb-2026 · sent-marker migration ──
            # Move ``sms_pending_at`` → ``sms_sent_at`` on success.
            if provider_status in ("sent", "queued", "dry_run", "mocked"):
                from services.service_report_submit_gate import (
                    stamp_sms_sent,
                )
                await stamp_sms_sent(
                    tenant_id=_tid, job_id=_jid, tech_id=_uid,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[task-u] completion SMS failed: {e}")
            await db.service_reports.update_one(
                {"tenant_id": _tid, "job_id": _jid, "tech_id": _uid},
                {"$set": {"customer_notified.sms_status": "failed"}},
            )

    if auto_send_completion and not already_notified.get("email_sent_at"):
        # ── Phase P45 · Feb-2026 · notification enqueue ────────────
        # The atomic gate at the top of this handler already claimed
        # ``submitted_at`` + ``email_pending_at`` + ``sms_pending_at``;
        # since we're past that gate the current caller IS the
        # canonical winner — safe to enqueue.  The bg tasks below
        # will migrate ``_pending_at`` → ``_sent_at`` on success
        # (see ``services.service_report_submit_gate.stamp_email_sent``
        # + ``stamp_sms_sent``).
        background_tasks.add_task(_bg_send_visit_summary_email)
        email_result_status = "queued"
    else:
        email_result_status = "skipped_idempotent" if already_notified.get("email_sent_at") else "tenant_disabled"

    # Phase 34 · Task U — companion SMS. Uses the tenant setting SMS
    # template if present; otherwise a sensible default. Runs through
    # the guarded RC adapter so preview only sends live to allow-
    # listed recipients.
    # Phase P45 · Feb-2026 — SMS enqueue is protected by the same
    # atomic gate that ran at the top of this handler.  We reach
    # here only when the current caller won the claim, so it's
    # safe to enqueue without a second gate check.
    if auto_send_completion and not already_notified.get("sms_sent_at"):
        background_tasks.add_task(_bg_send_completion_sms)
        sms_result_status = "queued"
    else:
        sms_result_status = "skipped_idempotent" if already_notified.get("sms_sent_at") else "tenant_disabled"

    # Audit record on the service report so ops + tests can inspect
    # what path was hit for this completion.
    try:
        cn_patch = {"customer_notified": {
            "email_status": email_result_status,
            "email_sent_at": now if email_result_status in ("sent", "queued", "dry_run", "mocked") else None,
            "sms_status": sms_result_status,
            "sms_sent_at": now if sms_result_status in ("sent", "queued", "dry_run", "mocked") else None,
            "auto_send_completion_setting": auto_send_completion,
        }}
        await db.service_reports.update_one(
            {"tenant_id": tenant["id"], "job_id": jid, "tech_id": tech_id},
            {"$set": cn_patch},
        )
        out["customer_notified"] = cn_patch["customer_notified"]
    except Exception as e:  # pragma: no cover — audit is best-effort
        logger.warning(f"[task-u] customer_notified audit write failed: {e}")

    if clock_out_summary:
        out["clock_out_summary"] = {
            "entry_id": clock_out_summary.get("id"),
            "duration_minutes": clock_out_summary.get("duration_minutes"),
            "mileage_miles": clock_out_summary.get("mileage_miles"),
            "origin": clock_out_summary.get("origin"),
        }
    if invoice_id:
        out["invoice_id"] = invoice_id
    # Sprint 3b · Feb-2026 — surface chemistry-gate warnings when
    # ``gate_mode=warn_only`` and the Required Four had gaps. The
    # submit still succeeded; this lets the UI + FE consumers flag
    # the missing readings without blocking close.
    if _gate_warnings:
        out["warnings"] = list((out or {}).get("warnings") or []) + _gate_warnings
    # Feb-2026 · P12A — structured end log with elapsed_ms so the
    # tail duration of the SYNC path is greppable in the prod log
    # stream on any future 520 regression.  WARN when > 50s so the
    # log processor picks up the outlier automatically.
    _sr_elapsed_ms = int((_time_p12a.monotonic() - _sr_start) * 1000)
    if _sr_elapsed_ms > 50_000:
        logger.warning(
            f"service_report_submit slow job={jid} tenant={tenant['id']} "
            f"elapsed_ms={_sr_elapsed_ms}"
        )
    else:
        logger.info(
            f"service_report_submit end job={jid} tenant={tenant['id']} "
            f"elapsed_ms={_sr_elapsed_ms}"
        )
    if idem_key:
        await store_response(idem_key,
                              "POST /jobs/{jid}/service-report/submit",
                              tenant["id"], out, idem_body)
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
            # Phase I1.7.e · Chunk 2.b · Feb-2026 — routed through the
            # central AI chokepoint so per-tenant BYO keys + AI spend
            # caps apply. ``image_b64s`` plumbs the base64 photo
            # through to ``ImageContent`` inside the chokepoint. On
            # cap-exceeded / error we degrade to the same
            # ``mocked=True`` shape the pre-migration code produced.
            from services.llm_provider import call_llm_with_fallback
            from services.ai.cap_http import is_ai_cap_exceeded
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
            ctx_lines = []
            if body.current_readings:
                ctx_lines.append(
                    f"Current readings: {_json.dumps(body.current_readings)}")
            if body.pool_gallons:
                ctx_lines.append(f"Pool gallons: {body.pool_gallons}")
            if not ctx_lines:
                ctx_lines.append("No readings provided — provide ranges.")
            llm_result = await call_llm_with_fallback(
                system_prompt=_WATER_SYSTEM,
                user_text="\n".join(ctx_lines),
                provider="anthropic", model="claude-sonnet-4-6",
                tenant_id=tenant["id"],
                image_b64s=[image_b64],
                parse_json=False,
            )
            if is_ai_cap_exceeded(llm_result):
                result = {"mocked": True, "reason": "ai_spend_cap_exceeded",
                            "clarity": None, "issues": [],
                            "recommendations": [],
                            "overall_assessment": None}
            elif llm_result.get("error"):
                raise RuntimeError(str(llm_result.get("error")))
            else:
                text = ((llm_result.get("raw") or {}).get("text") or "").strip()
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


async def _llm_rephrase_reasons(recs: list[dict],
                                    tenant_id: Optional[str] = None) -> tuple[list[dict], int, Optional[str]]:
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
    import json as _json2, re as _re2
    payload = [
        {"chemical": r["chemical"], "quantity": r["quantity"], "unit": r["unit"],
         "reason": r["reason"]}
        for r in recs
    ]
    prompt = "Rewrite each 'reason' below. Return the JSON array only.\n" + _json2.dumps(payload)
    try:
        # Phase I1.7.e · Chunk 2.b · Feb-2026 — routed through the
        # central AI chokepoint so per-tenant BYO keys + AI spend
        # caps apply. ``max_tokens=800`` maps through to
        # ``LlmChat.with_max_tokens``.  On cap-exceeded / error we
        # return the recs untouched (same as the pre-migration
        # graceful degradation).
        from services.llm_provider import call_llm_with_fallback
        from services.ai.cap_http import is_ai_cap_exceeded
        result_llm = await call_llm_with_fallback(
            system_prompt=_DOSING_LLM_SYSTEM, user_text=prompt,
            provider="anthropic", model="claude-sonnet-4-6",
            tenant_id=tenant_id,
            parse_json=False,
            max_tokens=800,
        )
        if is_ai_cap_exceeded(result_llm):
            return recs, 0, "ai_spend_cap_exceeded"
        if result_llm.get("error"):
            return recs, 0, f"llm error: {result_llm.get('error')}"
        text = ((result_llm.get("raw") or {}).get("text") or "").strip()
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

    # Sprint 3b · Feb-2026 — fetch tenant chemistry settings so
    # tenant-authored targets + formulas can override the AZ defaults
    # inside ``_pool_compute``. Merged shape is always populated
    # (falls back to AZ defaults when the tenant hasn't customised).
    from services.chemistry_tenant_targets import (
        get_tenant_chemistry_settings,
    )
    chem_cfg = await get_tenant_chemistry_settings(tenant["id"], db)
    # ``_pool_compute`` expects the ``total_alkalinity`` key
    # internally; the tenant settings block uses ``alkalinity``
    # (canonical gate key). Bridge them here so the dosing engine
    # sees the right shape without leaking the naming into the
    # tenant-facing surface.
    _dosing_targets = dict(chem_cfg["targets"])
    if "alkalinity" in _dosing_targets:
        _dosing_targets["total_alkalinity"] = _dosing_targets["alkalinity"]

    recs = _pool_compute(
        body.readings or {}, gallons,
        customer=customer_doc,
        service_date=service_date_for_dosing,
        recent_service_reports=recent_reports,
        visible_algae=(body.visible_algae or "none"),
        tenant_targets=_dosing_targets,
        tenant_formulas=chem_cfg.get("dosing_formulas") or {},
    )
    source = "deterministic-only"
    tokens = 0
    llm_error: Optional[str] = None
    if body.use_llm_phrasing and recs:
        recs, tokens, llm_error = await _llm_rephrase_reasons(recs, tenant_id=tenant["id"])
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
    from utils import not_deleted_filter as _nd
    # All the customer's jobs.
    jobs = await db.jobs.find(
        {"customer_id": customer_id, "tenant_id": tenant["id"], **_nd()},
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


# ─── Task N · Phase N.1 · Feb-2026 — Notes Archive (admin) ───────────────
# Task N Round 2 · Phase N.6 — pipeline builder extracted to
# ``services/notes/archive_query.py`` so the per-customer
# notes-history endpoint reuses the same aggregation shape verbatim.
from services.notes.archive_query import (
    NOTES_ARCHIVE_MAX_PAGE_SIZE as _NOTES_ARCHIVE_MAX_PAGE_SIZE,
    build_archive_pipeline as _build_archive_pipeline,
    normalise_row as _normalise_archive_row,
)
_NOTES_ARCHIVE_INDEX_NAME = "service_reports_archive_idx"


async def ensure_indexes() -> None:
    """Create the Notes Archive partial index at server-startup.

    Keys: ``(tenant_id: 1, submitted_at: -1)`` — supports the archive
    query's tenant scope + newest-first sort in a single index scan.

    Partial filter: submitted rows only that have at least one populated
    note field.  Keeps the index tiny; grows only with note-bearing
    filed SRs (13 rows across all tenants at ship-time; a rounding
    error on the collection).

    Idempotent: ``background=True`` + a stable index name so a second
    boot after the ship is a no-op.
    """
    try:
        await db.service_reports.create_index(
            [("tenant_id", 1), ("submitted_at", -1)],
            name=_NOTES_ARCHIVE_INDEX_NAME,
            background=True,
            partialFilterExpression={
                "submitted_at": {"$type": "string"},
                "$or": [
                    {"notes": {"$type": "string"}},
                    {"internal_notes": {"$type": "string"}},
                    {"customer_notes": {"$type": "string"}},
                ],
            },
        )
    except Exception as _e:  # pragma: no cover — defensive
        logger.warning(f"[notes-archive] ensure_indexes crashed: {_e}")


@router.get("/service-reports/archive")
async def notes_archive(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1),
    customer_search: Optional[str] = None,
    tech_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    industry: Optional[str] = None,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Admin-gated read of submitted service reports with any of
    ``notes`` / ``internal_notes`` / ``customer_notes`` populated.

    Delegates aggregation building to
    ``services.notes.archive_query.build_archive_pipeline`` so the
    per-customer notes-history endpoint stays in shape-parity.
    """
    if page_size > _NOTES_ARCHIVE_MAX_PAGE_SIZE:
        raise HTTPException(
            400,
            {"error": "page_size_too_large",
             "max": _NOTES_ARCHIVE_MAX_PAGE_SIZE},
        )
    try:
        pipeline = _build_archive_pipeline(
            tenant_id=tenant["id"], page=page, page_size=page_size,
            customer_search=customer_search, tech_id=tech_id,
            date_from=date_from, date_to=date_to, industry=industry,
        )
    except ValueError as e:
        field = str(e).split(":", 1)[0] or "date"
        raise HTTPException(
            400,
            {"error": "invalid_date_format",
             "field": field, "expected": "YYYY-MM-DD"},
        )
    if pipeline is None:
        # Unknown industry label — empty response, don't crash.
        return {"rows": [], "total_count": 0,
                 "page": page, "page_size": page_size}

    cursor = db.service_reports.aggregate(pipeline)
    facet_result = await cursor.to_list(1)
    facet = facet_result[0] if facet_result else {"rows": [], "total_count": []}
    rows_out = [_normalise_archive_row(r) for r in (facet.get("rows") or [])]
    total_count = 0
    _tc = facet.get("total_count") or []
    if _tc:
        total_count = int(_tc[0].get("n") or 0)
    return {
        "rows": rows_out,
        "total_count": total_count,
        "page": page,
        "page_size": page_size,
    }


# ─── Phase 39 · Send Visit Recap ────────────────────────────────────────
# Fired after a tech closes a job. Composes a short summary of the visit
# (chemicals added, water readings, up to 3 photos) and sends it to the
# customer via RingCentral SMS and/or Resend email. If either channel isn't
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
    "chlorine":         (1.0, 3.0),
    "free_chlorine":    (1.0, 3.0),
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


# ─── LANDSCAPE-EMAIL-FIX · Feb-2026 — shared helpers ───────────────
# The Phase-39 ``send_visit_recap`` dispatcher historically hard-
# coded the "Your pool visit recap" subject and composed a pool-
# only body (chemicals + readings) regardless of job type.  For a
# landscape job the chem/reading blocks were empty so the customer
# received a mis-subjected email with just the header lines.
#
# These helpers power the type-branch inside ``_compose_recap``:
#   * ``_absolute_photo_url`` promotes a relative photo URL from
#     ``inject_photo_url_on_doc`` (JOB-PHOTOS-FIX) to an absolute
#     URL for email clients which do not resolve same-origin
#     paths.  ``APP_PUBLIC_URL`` is the canonical absolute-base
#     config and is already used by every other outbound-email
#     path (see ``services.auto_visit_email._absolute_url``,
#     ``routers.csat._cta_url``, ``routers.referrals``).
#   * ``_completed_checklist_labels`` extracts the labels of items
#     the tech checked off during the visit.  Accepts BOTH the
#     tech-portal shape ``{"label", "checked"}`` and the
#     redacted/customer shape ``{"label", "done"}`` so a key
#     normalisation hiccup can't blank the section (same posture
#     as ``services.auto_visit_email._checklist_is_done``).
def _absolute_photo_url(url: str) -> str:
    """Promote a relative ``/api/public/...`` photo URL to an
    absolute URL rooted at ``APP_PUBLIC_URL`` so email clients can
    resolve it.  Already-absolute URLs are returned unchanged;
    empty / falsy input returns ``""``.
    """
    if not url:
        return ""
    u = str(url).strip()
    if not u:
        return ""
    if u.startswith("http://") or u.startswith("https://"):
        return u
    try:
        from config import APP_PUBLIC_URL
    except Exception:
        APP_PUBLIC_URL = ""
    base = (APP_PUBLIC_URL or "").rstrip("/")
    if not base:
        # No absolute base configured — ship the relative URL
        # verbatim rather than mangling it.  Same-origin webmail
        # (e.g. Gmail-in-iframe test fixtures) still resolves it.
        return u
    if u.startswith("/"):
        return f"{base}{u}"
    return f"{base}/{u}"


def _completed_checklist_labels(report: dict) -> list:
    """Return the labels of every checklist item the tech checked
    off.  Reads both ``checklist_completed`` (canonical) and
    ``checklist_items`` (legacy).  Honors both ``done`` and
    ``checked`` key shapes.  Falls back to the ``key`` or
    ``name`` field when the item lacks a human label.
    """
    items = (report.get("checklist_completed")
             or report.get("checklist_items")
             or [])
    out: list = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if not (it.get("done") or it.get("checked")):
            continue
        label = (it.get("label") or it.get("name") or it.get("key") or "")
        label = str(label).strip()
        if label:
            out.append(label)
    return out


def _recap_kind(job: dict) -> str:
    """Return ``"pool"`` / ``"landscape"`` / ``"non_pool"`` for a
    job doc using the canonical ``routers.jobs._derive_checklist_kind``
    priority chain.  Falls back to ``"pool"`` on import / runtime
    error so the Phase-39 default remains the safe fallback (pre-
    NON-POOL-EMAIL-FIX behaviour).

    NON-POOL-EMAIL-FIX · Feb-2026 — shared source of truth for both
    ``_compose_recap``'s 3-way branch and the kept-for-backward-
    compat ``_is_landscape_job`` wrapper below.
    """
    try:
        from routers.jobs import _derive_checklist_kind
    except Exception:
        return "pool"
    try:
        return _derive_checklist_kind(job or {}, None)
    except Exception:
        return "pool"


def _is_landscape_job(job: dict) -> bool:
    """Thin wrapper over ``_recap_kind``.  Preserved verbatim for the
    LANDSCAPE-EMAIL-FIX test file + any other downstream consumer
    pinned to this signature.
    """
    return _recap_kind(job) == "landscape"


def _compose_recap(report: dict, job: dict, customer: dict, tech_name: str,
                    include_photos: bool, next_visit: str | None,
                    tenant: dict, photo_limit: int = 3):
    """Return `{plain, html, photo_urls, subject}` for the recap message.

    LANDSCAPE-EMAIL-FIX · Feb-2026 — branches on job type.  Landscape
    jobs ship a landscape-specific subject + body (completed grooming
    checklist + photos, NO pool-chemistry sections).  Pool / non-pool
    jobs keep the historical Phase-39 composition unchanged.  Photo
    URLs are promoted to absolute URLs via ``APP_PUBLIC_URL`` so
    email clients can resolve them.

    NON-POOL-EMAIL-FIX · Feb-2026 — the else-branch is now itself a
    2-way split: ``_recap_kind`` returning ``"non_pool"`` picks a
    generic service-visit recap (service_type line + checklist +
    photos, NO chemistry); ``"pool"`` keeps the historical pool
    composition (chemicals + readings + photos).  Priority:
    landscape → non_pool → pool.
    """
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
    # Photos.  LANDSCAPE-EMAIL-FIX · Feb-2026 — promote to absolute
    # URLs so mail clients (which don't resolve relative paths) can
    # follow the ``/api/public/job-photo/...`` link produced by the
    # JOB-PHOTOS-FIX serializer.
    photo_urls = []
    if include_photos:
        for p in (report.get("photos") or [])[:photo_limit]:
            raw = p.get("url") or p.get("public_url") or p.get("thumbnail_url")
            abs_url = _absolute_photo_url(raw)
            if abs_url:
                photo_urls.append(abs_url)

    date_str = str(job.get("scheduled_at") or job.get("service_report_submitted_at") or "")[:10]
    biz_name = tenant.get("name") or "Your pool service"

    # LANDSCAPE-EMAIL-FIX · Feb-2026 — type branch.
    # NON-POOL-EMAIL-FIX · Feb-2026 — 3-way branch over
    # ``_recap_kind`` so non-pool / non-landscape service types
    # (tree_service, hvac, pest_control, irrigation, fencing,
    # snow_removal) no longer fall through to the pool composition.
    kind = _recap_kind(job)
    is_landscape = kind == "landscape"
    is_non_pool = kind == "non_pool"
    needs_checklist = is_landscape or is_non_pool
    checklist_labels = _completed_checklist_labels(report) if needs_checklist else []
    service_type_line = ""
    if is_non_pool:
        _svc = str(job.get("service_type") or job.get("job_type") or "").strip()
        if _svc:
            service_type_line = f"Service type: {_svc}"

    if is_landscape:
        # Landscape jobs use ``"<Business> service"`` as the default
        # biz-name fallback instead of the pool-specific literal so
        # a tenant without ``tenant.name`` doesn't leak pool framing.
        biz_name_display = tenant.get("name") or "Your landscape service"
        subject = f"Your landscape visit recap — {date_str}"
    elif is_non_pool:
        # Generic non-pool branch — subject uses the tenant's name
        # when available ("Your <Business> service visit recap"),
        # otherwise a neutral fallback that doesn't leak either the
        # pool or landscape framing.
        _biz = tenant.get("name")
        biz_name_display = _biz or "Your service"
        subject = (f"Your {_biz} service visit recap — {date_str}"
                   if _biz
                   else f"Your service visit recap — {date_str}")
    else:
        biz_name_display = biz_name
        subject = f"Your pool visit recap — {date_str}"

    lines = [
        f"Hi {customer.get('name') or 'there'},",
        f"Your {date_str} visit with {biz_name_display} is complete.",
    ]
    if tech_name:
        lines.append(f"Tech: {tech_name}")
    if service_type_line:
        lines.append(service_type_line)
    if needs_checklist:
        # ── Landscape / non-pool body ─────────────────────────────
        # Checklist first (the only service artifact a customer
        # sees for a non-chemistry visit), photos next, next visit
        # at the end.  Chemistry / readings blocks are intentionally
        # suppressed — these service types have neither.
        if checklist_labels:
            lines.append("")
            lines.append("Completed:")
            lines.extend(f"• {label}" for label in checklist_labels)
    else:
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
                  f"<p>Your <b>{date_str}</b> visit with <b>{biz_name_display}</b> is complete.</p>"]
    if tech_name:
        html_parts.append(f"<p>Tech: <b>{tech_name}</b></p>")
    if service_type_line:
        html_parts.append(f"<p>{service_type_line}</p>")
    if needs_checklist:
        if checklist_labels:
            html_parts.append(
                "<p><b>Completed:</b></p><ul>"
                + "".join(f"<li>{label}</li>" for label in checklist_labels)
                + "</ul>"
            )
    else:
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
             "subject": subject}


async def _send_recap_sms(customer: dict, plain: str,
                            *, tenant_id: str | None = None) -> dict:
    """Feb-2026 · Twilio→RC consolidation — route through the shipped
    RingCentral adapter. Fails-closed with a neutral reason string
    when RC creds are absent.

    APR-II · Feb-2026 — the after-hours ``alert_phone`` channel was
    removed from ``CustomerIn``; routing now resolves to the single
    primary ``phone`` field.  Customers without a primary phone fall
    through to the no-phone-on-file reason string.

    SMS-RECIPIENT-FIX · Feb-2026 — accepts ``tenant_id`` so the
    customer-facing deny-list (``services.comms_hardening.deny_list``)
    can strip workforce/tenant-owned phones before delivery. If the
    resolved recipient maps to an admin line, the function returns
    ``{"sent": False, "mocked": True, "reason":
    "denied_admin_owned_recipient"}`` without hitting the adapter.
    """
    to = customer.get("phone")
    if not to:
        return {"sent": False, "mocked": True,
                 "reason": "customer has no phone on file"}
    # SMS-RECIPIENT-FIX · Feb-2026 — belt-and-suspenders strip.
    if tenant_id:
        from services.comms_hardening.deny_list import (
            strip_admin_owned_recipients,
        )
        _kept, _stripped = await strip_admin_owned_recipients(
            tenant_id=tenant_id, kind="customer_facing", channel="sms",
            recipients=[to],
            context={"trigger": "visit_recap_sms",
                      "customer_id": customer.get("id")},
        )
        if _stripped:
            logger.warning(
                "[visit_recap] denied_admin_owned_recipient "
                "tenant=%s customer=%s phone=%s",
                tenant_id, customer.get("id"), to,
            )
            return {"sent": False, "mocked": True,
                     "reason": "denied_admin_owned_recipient"}
        to = _kept[0] if _kept else to
    from services.sms.rc_adapter import send as _sms_send
    res = await _sms_send(
        to=to, body=plain[:1500], category="transactional",
        tenant_id=tenant_id,
        customer_id=customer.get("id"),
    )
    provider = res.get("provider")
    status = res.get("provider_status")
    if provider == "ringcentral" and status in ("queued", "sent", "delivered", "accepted"):
        return {"sent": True, "mocked": False,
                 "sms_message_id": res.get("provider_response_id")}
    if provider == "mock" or status == "dry_run":
        return {"sent": False, "mocked": True,
                 "reason": "sms not configured"}
    return {"sent": False, "mocked": True,
             "reason": f"sms error: {res.get('error') or 'send_failed'}"}


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
        # safe-send: allowlist because legacy direct SDK call is gated by sdk_intercept.install_resend_gate() at the Resend SDK boundary; SAFE-SEND-D full migration pending
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
    # APR-II · Feb-2026 — collapsed to primary phone + email only.
    if not (cust.get("phone") or cust.get("email")):
        raise HTTPException(400, "Customer has neither phone nor email on file")

    tech = None
    if rep.get("tech_id"):
        tech = await db.users.find_one({"id": rep["tech_id"]}, {"_id": 0}) \
            or await db.users.find_one({"technician_id": rep["tech_id"]}, {"_id": 0})
    tech_name = (tech or {}).get("name") or (tech or {}).get("email") or ""

    # "Next visit" — cheap lookup of the next scheduled pool job for this customer.
    next_visit = None
    from utils import not_deleted_filter as _nd_next
    upcoming = await db.jobs.find(
        {"tenant_id": tenant["id"], "customer_id": job.get("customer_id"),
         "status": {"$in": ["scheduled", "open"]},
         "scheduled_at": {"$gt": now_iso()},
         **_nd_next()},
        {"_id": 0, "scheduled_at": 1},
    ).sort("scheduled_at", 1).to_list(1)
    if upcoming:
        next_visit = str(upcoming[0].get("scheduled_at"))[:10]

    composed = _compose_recap(rep, job, cust, tech_name,
                                bool(body.include_photos), next_visit, tenant)

    results = {}
    mocked_channels = []
    if channel in ("sms", "both"):
        # SMS-RECIPIENT-FIX · Feb-2026 — plumb tenant_id so the
        # customer-facing deny-list fires inside ``_send_recap_sms``.
        results["sms"] = await _send_recap_sms(cust, composed["plain"],
                                                 tenant_id=tenant["id"])
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
# Feb-2026 · Slice 4 — Chemical-cost-hide. Any field on a
# ``chemicals_added`` row that carries pricing/cost signal MUST be
# stripped before the payload reaches a customer surface. We take the
# whitelist approach (opposite of blacklist) — a customer only sees
# the semantic descriptors of the chemical + how much was added.
_CUSTOMER_CHEM_KEEP_FIELDS = frozenset({
    "name", "chemical",           # display name
    "quantity", "amount", "qty",  # numeric amount
    "unit", "default_unit",       # unit of measure
    "raw_label",                  # freeform label like "2 tabs"
})


def _strip_chem_costs_for_customer(chems):
    """Return a list of chemical rows with all cost/price fields
    stripped. Non-dict rows pass through unchanged."""
    if not chems:
        return chems
    out = []
    for c in chems:
        if not isinstance(c, dict):
            out.append(c)
            continue
        out.append({k: v for k, v in c.items() if k in _CUSTOMER_CHEM_KEEP_FIELDS})
    return out


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

    Feb-2026 · Slice 4 — Chemical cost hide. ``chemicals_added`` rows
    are passed through :func:`_strip_chem_costs_for_customer` so
    fields like ``unit_cost`` / ``line_total`` / ``cost_cents`` /
    ``price_cents`` never surface. Top-level ``chem_total_cents`` and
    ``chemicals_total_cents`` are also dropped.
    """
    if not sr:
        return sr
    sr = dict(sr)
    sr.pop("internal_notes", None)
    # Feb-2026 · Slice 4 — hide chemical costs from customer views.
    sr["chemicals_added"] = _strip_chem_costs_for_customer(sr.get("chemicals_added") or [])
    for _cost_field in (
        "chem_total_cents", "chemicals_total_cents", "chemicals_cost_cents",
        "chemicals_total", "chemical_cost", "chemicals_cost",
    ):
        sr.pop(_cost_field, None)
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
    # Feb-2026 · Slice 3E — drop checklist items that weren't checked.
    # The tech didn't perform them, so surfacing them on the customer
    # report would either confuse (looks like a missed task) or leak
    # detail the customer doesn't need. Admin retains the full list
    # via ``_annotate_report_for_admin`` so incomplete work is still
    # visible internally.
    checklist = sr.get("checklist_items") or []
    sr["checklist_items"] = [
        it for it in checklist
        if isinstance(it, dict) and bool(it.get("checked"))
    ]
    # Feb-2026 · Multi-body Phase 1 — mirror redaction across every
    # ``water_bodies[i]``. Each body has its own readings/chemicals/
    # media so the same customer-safe transforms (strip chemical
    # costs, drop internal photos, convert readings to bands) must
    # apply per body — otherwise a stray unit cost in body[1] would
    # bypass the top-level scrub.
    bodies = sr.get("water_bodies") or []
    if bodies:
        redacted_bodies: List[Dict[str, Any]] = []
        for b in bodies:
            if not isinstance(b, dict):
                continue
            rb = dict(b)
            rb["chemicals_used"] = _strip_chem_costs_for_customer(
                rb.get("chemicals_used") or rb.get("chemicals_added") or [])
            rb.pop("chemicals_added", None)
            for _cf in ("chem_total_cents", "chemicals_total_cents",
                          "chemicals_cost_cents", "chemicals_total",
                          "chemical_cost", "chemicals_cost"):
                rb.pop(_cf, None)
            b_readings = rb.get("readings") or []
            b_labelled: List[Dict[str, Any]] = []
            b_labels: Dict[str, str] = {}
            for r in b_readings:
                if not isinstance(r, dict):
                    continue
                key = r.get("key") or ""
                band = classify_reading(key, r.get("value"))
                if band is None:
                    continue
                b_labels[str(key)] = band
                b_labelled.append({
                    "key": key,
                    "name": r.get("name"),
                    "unit": r.get("unit"),
                    "label": band,
                })
            rb["readings"] = b_labelled
            rb["readings_label"] = b_labels
            b_media = rb.get("media") or []
            rb["media"] = [
                m for m in b_media
                if isinstance(m, dict) and not any(
                    str(t).lower() in ("internal", "issue", "private")
                    for t in (m.get("tags") or []))
            ]
            redacted_bodies.append(rb)
        sr["water_bodies"] = redacted_bodies
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
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: Optional[str] = Query(None, description="Case-insensitive substring — notes + customer name + address"),
    service_type: Optional[str] = Query(None),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Customer-facing service-report list with search, filters, and
    pagination.

    Feb-2026 · Enhancements ship — the prior implementation hard-
    capped at 200 rows with no filtering. New contract: page/page_size
    (max 100), ``q`` substring search across notes + customer name +
    address, ``service_type`` exact match, ``from``/``to`` inclusive
    ISO date range on ``service_date``. Response shape:
    ``{items, page, page_size, total, total_pages}``.
    """
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customer portal only")

    from utils import not_deleted_filter as _nd_portal
    import math
    import re as _re

    # Match the job filter — customer-owned jobs are the sole
    # source-of-truth for what reports this customer can see.
    job_filter: Dict[str, Any] = {
        "tenant_id": tenant["id"],
        "customer_id": user["customer_id"],
        **_nd_portal(),
    }
    if service_type:
        # Match either ``service_type`` OR the legacy ``job_type``
        # field — both writes exist in the wild.
        job_filter["$or"] = [
            {"service_type": service_type},
            {"job_type": service_type},
        ]
    jobs = [j async for j in db.jobs.find(
        job_filter,
        {"_id": 0, "id": 1, "title": 1, "service_type": 1, "job_type": 1,
         "scheduled_start": 1, "customer_name": 1, "address": 1,
         "customer_id": 1},
    )]
    if not jobs:
        return {"items": [], "page": page, "page_size": page_size,
                 "total": 0, "total_pages": 0}
    job_by_id = {j["id"]: j for j in jobs}
    job_ids = list(job_by_id.keys())

    # Report filter — pin to the submitted set + optional date range on
    # ``service_date`` (falls back to ``submitted_at`` when the report
    # doesn't carry an explicit ``service_date``).
    report_filter: Dict[str, Any] = {
        "tenant_id": tenant["id"],
        "job_id": {"$in": job_ids},
        "submitted_at": {"$ne": None},
    }
    date_clause: Dict[str, Any] = {}
    if from_:
        date_clause["$gte"] = str(from_)
    if to:
        # Inclusive upper bound — pad to end-of-day so a bare date
        # string doesn't skip reports submitted later that same day.
        date_clause["$lte"] = f"{to}T23:59:59.999Z"
    if date_clause:
        # Match against submitted_at (canonical write-side signal —
        # ``service_date`` isn't consistently populated in the wild).
        report_filter["submitted_at"] = {**report_filter["submitted_at"],
                                           **date_clause}

    # Substring search — Mongo ``$or`` with case-insensitive $regex
    # (input escaped via ``re.escape`` so bad-actor input can't break
    # the query).
    if q and q.strip():
        _safe = _re.escape(q.strip())
        _pat = {"$regex": _safe, "$options": "i"}
        # Restrict job_ids to those whose customer_name / address match
        # the substring (the report doc doesn't carry those fields).
        matched_job_ids = [
            j["id"] for j in jobs
            if _re.search(_safe, str(j.get("customer_name") or ""), _re.I)
            or _re.search(_safe, str(j.get("address") or ""), _re.I)
        ]
        _or_clauses = [{"notes": _pat}, {"customer_notes": _pat}]
        if matched_job_ids:
            _or_clauses.append({"job_id": {"$in": matched_job_ids}})
        report_filter["$or"] = _or_clauses

    total = await db.service_reports.count_documents(report_filter)
    if total == 0:
        return {"items": [], "page": page, "page_size": page_size,
                 "total": 0, "total_pages": 0}
    total_pages = math.ceil(total / page_size)
    skip = (page - 1) * page_size
    rows = await db.service_reports.find(
        report_filter, {"_id": 0},
    ).sort("submitted_at", -1).skip(skip).limit(page_size).to_list(page_size)

    from services.service_report_view import resolve_technician_names
    _tech_ids = list({r.get("tech_id") for r in rows if r.get("tech_id")})
    _name_map = await resolve_technician_names(
        db, tenant["id"], _tech_ids,
    ) if _tech_ids else {}

    items = []
    for sr in rows:
        job = job_by_id.get(sr.get("job_id")) or {}
        bodies = iter_water_bodies(sr)
        body_summaries = [summarize_body(b) for b in bodies]
        items.append({
            "id": sr.get("id"),
            "job_id": sr.get("job_id"),
            "job_title": job.get("title"),
            "service_type": job.get("service_type") or job.get("job_type"),
            "scheduled_start": job.get("scheduled_start"),
            "submitted_at": sr.get("submitted_at"),
            "tech_name": _name_map.get(sr.get("tech_id")) or "",
            "customer_notes": sr.get("customer_notes") or "",
            "water_bodies_summary": body_summaries,
            "water_body_count": len(body_summaries),
        })
    return {"items": items, "page": page, "page_size": page_size,
             "total": total, "total_pages": total_pages}


@router.get("/customers/me/service-reports/{report_id}")
async def get_my_service_report(
    report_id: str,
    request: Request,
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
    # Feb-2026 · Customer service-report enhancements — merge
    # ``job.photos`` into a SEPARATE ``job_photos`` array on the
    # customer detail response so tech-attached photos (already
    # exposed under ``photos``) stay attributed independently.
    # Each entry carries the compact display shape + a token-scoped
    # ABSOLUTE URL pointing at the customer-session streaming route
    # below — customers hit the portal from mobile clients that
    # can't resolve relative URLs against the API host.
    sr["job_photos"] = _build_customer_job_photos(job,
                                                    _resolve_photo_url_base(request))
    # Feb-2026 · P1 hotfix — populate ``tech_name`` (never persisted on
    # the report doc; see the list-endpoint comment above). Falls back
    # to ``effective_tid(job)`` when the report's ``tech_id`` doesn't
    # resolve — covers legacy reports where ``tech_id`` was never
    # stamped or points at a shape the cascade misses.
    from services.service_report_view import resolve_technician_names
    from services.job_assignee import effective_tid
    _tid = sr.get("tech_id") or effective_tid(job)
    if _tid:
        _names = await resolve_technician_names(db, tenant["id"], [_tid])
        sr["tech_name"] = _names.get(_tid) or ""
    else:
        sr["tech_name"] = ""
    return sr


# ═══════════════════════════════════════════════════════════════════════
# Feb-2026 · Customer service-report enhancements — job.photos helpers +
# customer-session photo streaming route.
# ═══════════════════════════════════════════════════════════════════════
def _resolve_photo_url_base(request: Request) -> str:
    """Return the absolute URL prefix for the customer photo stream.

    Mirrors ``routers/estimate_viewer._resolve_url_base`` — prefers
    ``APP_PUBLIC_URL`` (production canonical host), falls back to
    ``request.base_url`` for preview/local. Empty string on failure
    (caller emits a relative URL and the browser fills in origin).
    """
    import os as _os_env
    _env = (_os_env.environ.get("APP_PUBLIC_URL") or "").strip().rstrip("/")
    if _env:
        return _env
    try:
        return str(request.base_url).rstrip("/")
    except Exception:  # noqa: BLE001
        return ""


def _build_customer_job_photos(job: dict, base_url: str = "") -> list:
    """Return the customer-safe display shape for ``job.photos``.

    * Filters soft-deleted entries.
    * Emits an embedded ``thumb`` (data-URI) only when the photo
      carries a pre-generated thumbnail — those work as ``<img src>``
      on the customer viewer without any auth handshake. The field is
      omitted (not emitted as an empty string) when absent so the
      client can cleanly branch on ``photo.thumb`` presence.
      Server-side thumbnail generation on the admin
      ``POST /api/jobs/{jid}/photos`` upload path is a larger change
      tracked separately; today, thumbs only exist for photos taken
      through the tech app.
    * Emits an ABSOLUTE token-scoped ``url`` that hits the customer-
      session streaming route below. The endpoint verifies job
      ownership, so anon → 401, wrong-customer session → 403.
    * Never returns raw base64 originals (kept off the wire so the
      list detail response stays small).
    """
    out = []
    for p in (job.get("photos") or []):
        if not isinstance(p, dict) or p.get("is_deleted"):
            continue
        _pid = p.get("id")
        if not _pid:
            continue
        _rel = f"/api/customers/me/jobs/{job.get('id')}/photos/{_pid}"
        _full = f"{base_url}{_rel}" if base_url else _rel
        entry: dict = {
            "id":            _pid,
            "caption":       p.get("caption") or p.get("label") or "",
            "created_at":    (p.get("uploaded_at") or p.get("created_at")
                                or p.get("taken_at")),
            "uploader_role": p.get("uploader_role") or "technician",
            # TD-76c · canonical FE fields. ``full_url`` + ``thumb_url``
            # are what the FE reads directly in Phase A. Legacy ``url``
            # kept as an additive alias (mobile parity — Phase B
            # removes after a dedicated mobile dispatch).
            "thumb_url":     _full,
            "full_url":      _full,
            "url":           _full,
        }
        _thumb = p.get("thumb") or ""
        if _thumb:
            # Embedded thumbnail (data-URI) — no auth handshake for the
            # ``<img>`` tag. Omitted entirely when absent. When present,
            # we prefer it as the ``thumb_url`` so the browser renders
            # inline bytes instead of streaming — but ``full_url`` stays
            # on the authenticated streaming route for the lightbox.
            entry["thumb"] = _thumb
            entry["thumb_url"] = _thumb
        out.append(entry)
    return out


@router.get("/customers/me/jobs/{jid}/photos/{photo_id}")
async def stream_customer_job_photo(
    jid: str,
    photo_id: str,
    request: Request,
    auth: Optional[str] = Query(
        None,
        description="Bearer-token fallback for <img src> use "
                    "(headers can't be attached to image/video src).",
    ),
):
    """Stream a single ``job.photos[]`` entry to the owning customer.

    Auth: standard ``Authorization: Bearer <token>`` header OR
    ``?auth=<token>`` query param (same contract as
    ``routers/files.py`` download endpoints — required so the portal
    can render these as ``<img src>`` from
    ``PortalServiceReportDetail``, where headers cannot be attached).
    Returns:
      * 200 — photo found + customer owns the job (streams from S3
        when ``s3_key`` is set, else decodes the embedded base64).
      * 401 — missing / invalid credentials, or non-customer role.
      * 403 — session valid but the customer doesn't own the job,
              or no tenant on the user.
      * 404 — photo id not found on this job.
      * 410 — photo soft-deleted.
      * 502 — S3 read failure.
      * 503 — storage not configured (embedded fallback also empty).

    TD-67 · Feb-2026 — pre-TD-67 the handler used
    ``user: dict = Depends(get_current_user)`` AND
    ``tenant: dict = Depends(get_current_tenant)``, both of which
    reject ``<img src>`` loads because browsers can't send the
    Authorization header on image requests. The portal detail page
    therefore rendered broken thumbnails for every job-attached
    photo. Both ``Depends`` are now resolved manually inside the
    body so the ``?auth=`` query-param fallback can run before any
    header-only auth check. Mirrors
    ``routers/files.py::_resolve_bearer_or_query_auth`` + its
    ``user.get('tenant_id')`` direct-read pattern.
    """
    # Resolve auth from Bearer header OR ``?auth=`` query param.
    # Mirrors ``routers/files.py::_resolve_bearer_or_query_auth`` —
    # intentionally duplicated here (not imported from a sibling
    # router module) so the two surfaces stay independently testable.
    # Cross-ref logged under TD-F7-2 in /app/memory/TECH_DEBT.md.
    from fastapi.security import HTTPAuthorizationCredentials
    header = request.headers.get("authorization") \
        or request.headers.get("Authorization")
    token = None
    if header and header.lower().startswith("bearer "):
        token = header.split(" ", 1)[1].strip()
    if not token and auth:
        token = auth.strip()
    if not token:
        raise HTTPException(401, "not_authenticated")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user = await get_current_user(creds)

    # Tenant resolution — read directly off the user doc (same
    # pattern as ``routers/files.py``). Avoids re-entering
    # ``get_current_tenant`` which itself ``Depends(get_current_user)``
    # from a header-only auth source and would 401 the request
    # before the ``?auth=`` body resolution runs.
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(403, "tenant_required")

    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(401, "customer_only")
    job = await db.jobs.find_one(
        {"id": jid, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "customer_id": 1, "photos": 1},
    )
    if not job:
        raise HTTPException(404, "job_not_found")
    if job.get("customer_id") != user["customer_id"]:
        raise HTTPException(403, "not_your_job")
    photo = next(
        (p for p in (job.get("photos") or [])
         if isinstance(p, dict) and p.get("id") == photo_id),
        None,
    )
    if not photo:
        raise HTTPException(404, "photo_not_found")
    if photo.get("is_deleted"):
        raise HTTPException(410, "photo_deleted")

    # ── Prefer S3 stream if the photo has an ``s3_key`` ──
    s3_key = photo.get("s3_key")
    if s3_key:
        try:
            from services.aws_s3.photos import read_object as _s3_read
            data = _s3_read(s3_key)
        except Exception as e:  # noqa: BLE001
            # Import-error / unexpected raise — fall through to the
            # embedded-base64 branch below so a partial S3 outage or
            # a stale module symbol never 502s a legitimate request.
            logger.warning("[customer-job-photo] s3 read raised: %s", e)
            data = None
        if data is not None:
            mime = photo.get("s3_mime") or photo.get("mime") \
                or photo.get("content_type") or "image/jpeg"
            return Response(content=data, media_type=mime, headers={
                "Cache-Control": "private, no-store",
            })
        # ``read_object`` returned ``None`` — S3 disabled / misconfigured
        # / read failed. Fall through to the embedded-base64 branch.
        logger.warning(
            "[customer-job-photo] s3 read returned None key=%s — "
            "falling back to embedded base64", s3_key,
        )

    # ── Fall back to the embedded base64 data URI ──
    embedded = photo.get("data") or photo.get("data_url") \
        or photo.get("preview") or photo.get("thumb")
    if isinstance(embedded, str) and embedded.startswith("data:"):
        import base64 as _b64
        try:
            _hdr, _b64part = embedded.split(",", 1)
            _mime = _hdr.split(";")[0].split(":", 1)[1]
        except Exception:  # noqa: BLE001
            _b64part = embedded.split(",", 1)[-1]
            _mime = photo.get("mime") or "image/jpeg"
        try:
            data = _b64.b64decode(_b64part)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, "base64_decode_failed") from e
        return Response(content=data, media_type=_mime, headers={
            "Cache-Control": "private, no-store",
        })
    raise HTTPException(503, "no_storage_backing")



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

