# ruff: noqa: F403,F405
from fastapi import APIRouter, HTTPException, Depends, Query, Response, Request
from pydantic import BaseModel, ConfigDict
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response,
                   create_staff_notification)
from routers.tenants import get_current_tenant
from models import *  # noqa: F403,F405
from emailer import send_completion_email

router = APIRouter()


# ─── Response models for OpenAPI docs (Feb-2026 AE1 T4 fix) ────────────
# JobListItem documents the visible fields on GET /api/jobs so generated
# clients discover the shape. ``extra="allow"`` keeps the endpoint
# backwards-compatible with dynamic legacy fields still consumed by
# older UI/mobile builds.

class JobListItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    technician_id: Optional[str] = None
    technician_name: Optional[str] = None
    technician_avatar: Optional[str] = None
    technician_department: Optional[str] = None
    title: Optional[str] = None
    service_type: Optional[str] = None
    address: Optional[str] = None
    status: Optional[str] = None
    scheduled_date: Optional[str] = None
    notes: Optional[str] = None
    price: Optional[float] = None
    photos: Optional[List[Any]] = None
    videos: Optional[List[Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    checklist_kind: Optional[str] = None
    account_notes: Optional[str] = None
    gate_code: Optional[str] = None
    # Feb-2026 MP2 UI enrichments — always present (null when absent).
    property_id: Optional[str] = None
    property_label: Optional[str] = None
    property_address: Optional[str] = None
    # Customer denormalization — surfaced so schedule cards render
    # without an N+1 fetch.
    customer_is_vip: Optional[bool] = None
    customer_gate_code: Optional[str] = None
    customer_notes: Optional[str] = None
    service_note: Optional[str] = None
    # Recent-activity flags (Phase 56.11 add-on).
    has_water_readings: Optional[bool] = None
    has_chemicals_added: Optional[bool] = None
    has_checklist: Optional[bool] = None
    has_private_note: Optional[bool] = None
    has_public_note: Optional[bool] = None
    has_repair_request: Optional[bool] = None
    has_shopping_request: Optional[bool] = None
    last_activity_at: Optional[str] = None
    service_report_submitted_at: Optional[str] = None
    chemicals_added: Optional[List[Any]] = None


def _timer_seconds(start_iso: str, stop_iso: str) -> int:
    try:
        a = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        b = datetime.fromisoformat(stop_iso.replace("Z", "+00:00"))
        return max(0, int((b - a).total_seconds()))
    except Exception:
        return 0



# ----------------------- Jobs -----------------------
POOL_CHECKLIST = [
    # Phase 5A · Feb 2026 — canonical pool checklist (7 items). Kept in
    # sync with routers/checklists.py DEFAULT_POOL_ITEMS. Whitespace and
    # capitalisation are preserved verbatim from the product brief.
    "Skimmed Pool",
    "Brush Pool",
    "Checked Skimmer Basket",
    "Checked Pump Basket",
    "Tested Chemicals",
    "Checked Equipment",
    "Secured all Gates",
]
LANDSCAPING_CHECKLIST = [
    # Phase 5A · Feb 2026 — canonical landscape checklist (10 items).
    # Kept in sync with routers/checklists.py DEFAULT_LANDSCAPE_ITEMS.
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
POOL_READINGS = [
    # Phase 56.3 follow-up — first-five order mirrors POOL_READING_FIELDS_DEFAULT
    # in service_reports.py so legacy Field Report + Pool Checklist share
    # the same top-of-form sequence.
    {"key": "combined_chlorine", "label": "Combined Chlorine", "unit": "ppm", "ideal": "0–0.2", "min": 0, "max": 0.2},
    {"key": "chlorine", "label": "Free Chlorine", "unit": "ppm", "ideal": "1–3", "min": 1, "max": 3},
    {"key": "ph", "label": "pH", "unit": "", "ideal": "7.4–7.6", "min": 7.4, "max": 7.6},
    {"key": "alkalinity", "label": "Total Alkalinity", "unit": "ppm", "ideal": "80–120", "min": 80, "max": 120},
    {"key": "cyanuric", "label": "Cyanuric Acid", "unit": "ppm", "ideal": "30–50", "min": 30, "max": 50},
    {"key": "calcium_hardness", "label": "Calcium Hardness", "unit": "ppm", "ideal": "200–400", "min": 200, "max": 400},
    {"key": "salt", "label": "Salt", "unit": "ppm", "ideal": "2700–3400", "min": 2700, "max": 3400},
    {"key": "tds", "label": "Total Dissolved Solids", "unit": "ppm", "ideal": "250–1500", "min": 250, "max": 1500},
    {"key": "phosphates", "label": "Phosphates", "unit": "ppb", "ideal": "0–100", "min": 0, "max": 100},
    {"key": "water_temp", "label": "Water Temp", "unit": "°F", "ideal": "78–82", "min": 78, "max": 82},
]

# Common pool chemicals technicians log as individual line items (name + default unit).
CHEMICAL_CATALOG = [
    {"name": "Liquid Chlorine", "unit": "gal"},
    {"name": "Chlorine Tablets", "unit": "tabs"},
    {"name": "Shock (Cal-Hypo)", "unit": "lbs"},
    {"name": "Muriatic Acid", "unit": "oz"},
    {"name": "Soda Ash", "unit": "lbs"},
    {"name": "Sodium Bicarbonate", "unit": "lbs"},
    {"name": "Calcium Chloride", "unit": "lbs"},
    {"name": "Cyanuric Acid", "unit": "lbs"},
    {"name": "Pool Salt", "unit": "lbs"},
    {"name": "Algaecide", "unit": "oz"},
    {"name": "Clarifier", "unit": "oz"},
    {"name": "Phosphate Remover", "unit": "oz"},
    {"name": "Enzymes", "unit": "oz"},
]


def rate_reading(value: float, mn: float, mx: float) -> str:
    """Qualitative rating shown to customers: Below Average / Average / Above Average / High."""
    if value < mn:
        return "Below Average"
    if value <= mx:
        return "Average"
    if value <= mx + (mx - mn):
        return "Above Average"
    return "High"


def classify_job(service_type: Optional[str]) -> str:
    return "landscaping" if "landscap" in (service_type or "").lower() else "pool"


def with_field_report(doc: dict) -> dict:
    """Attach job_type + default checklist/reading template so technicians always
    get the correct field report (pool vs landscaping). Also attaches customer-friendly
    qualitative ratings for any recorded chemical readings."""
    jt = classify_job(doc.get("service_type"))
    doc["job_type"] = jt
    if not doc.get("checklist"):
        template = LANDSCAPING_CHECKLIST if jt == "landscaping" else POOL_CHECKLIST
        doc["checklist"] = [{"id": f"c{i}", "label": lbl, "done": False} for i, lbl in enumerate(template)]
    if jt == "pool":
        doc["reading_fields"] = POOL_READINGS
        doc["chemical_catalog"] = CHEMICAL_CATALOG
        readings = doc.setdefault("chemical_readings", {})
        doc.setdefault("chemicals_added", [])
        report = []
        for f in POOL_READINGS:
            v = readings.get(f["key"])
            if v is None or v == "":
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            report.append({
                "key": f["key"], "label": f["label"], "value": fv,
                "unit": f["unit"], "ideal": f["ideal"], "rating": rate_reading(fv, f["min"], f["max"]),
            })
        doc["reading_report"] = report
    return doc


def scope_jobs_query(user: dict, tenant: dict, status: Optional[str], technician_id: Optional[str]) -> dict:
    q = {"tenant_id": tenant["id"]}
    if user.get("role") == "technician" and user.get("technician_id"):
        q["technician_id"] = user["technician_id"]
    elif user.get("role") == "customer":
        q["customer_id"] = user.get("customer_id")
    elif technician_id:
        q["technician_id"] = technician_id
    if status and status != "all":
        q["status"] = status
    return q


_LANDSCAPE_KEYWORDS = ("landscap", "lawn", "mow", "garden", "trim", "blow", "cleanup")


def _derive_checklist_kind(job: dict, tech_department: Optional[str]) -> str:
    """Phase 57.d / 56.3.B · read-time derivation of which checklist form
    to render.

    Priority: explicit override → tech department → service_type keyword →
    ``"pool"`` (safest default for this business).

    Department semantics (Phase 56.3.B):
      • ``pool``        → pool checklist
      • ``landscaping`` → landscape checklist
      • ``both``        → the tech can service either; we look at the
        service_type keywords first, and fall back to pool (safe default)
        when nothing landscape-specific is detected.
    """
    override = (job.get("checklist_kind_override") or "").strip().lower()
    if override in ("pool", "landscape", "landscaping"):
        return "landscape" if override.startswith("landscap") else "pool"
    dept = (tech_department or "").lower()
    if dept == "landscaping":
        return "landscape"
    if dept == "pool":
        return "pool"
    if dept == "both":
        hay_both = " ".join(str(job.get(k) or "") for k in ("service_type", "job_type", "title")).lower()
        if any(k in hay_both for k in _LANDSCAPE_KEYWORDS):
            return "landscape"
        return "pool"
    hay = " ".join(str(job.get(k) or "") for k in ("service_type", "job_type", "title")).lower()
    if any(k in hay for k in _LANDSCAPE_KEYWORDS):
        return "landscape"
    return "pool"


async def _enrich_job_dept_and_kind(doc: dict, tenant_id: str) -> None:
    """Mutates ``doc`` to add ``technician_department``, ``checklist_kind``,
    and ``assignee_photo_url`` at READ-TIME. Never persists — the stored
    job doc is untouched."""
    tid = doc.get("technician_id")
    dept = None
    photo = None
    if tid:
        u = await db.users.find_one(
            {"technician_id": tid, "tenant_id": tenant_id},
            {"_id": 0, "department": 1, "technician_photo_url": 1},
        ) or {}
        dept = u.get("department")
        photo = u.get("technician_photo_url") or None
    doc["technician_department"] = dept
    doc["checklist_kind"] = _derive_checklist_kind(doc, dept)
    # Phase 19 · Feb-2026 · Sub-item A — expose the assignee's photo so
    # every job-card surface can render a real headshot with the
    # existing UserAvatar initials fallback. Null when the tech has no
    # photo (26/26 today; will fill in over time via user-edit UI).
    doc["assignee_photo_url"] = photo


async def _enrich_jobs_dept_and_kind(docs: list, tenant_id: str) -> None:
    """Batch variant — single ``users`` query for the whole page."""
    tech_ids = list({d.get("technician_id") for d in docs if d.get("technician_id")})
    dept_map: Dict[str, Optional[str]] = {}
    # Phase 19 · Feb-2026 · Sub-item A — piggyback the photo lookup on
    # the same batched users query. Zero additional round-trips.
    photo_map: Dict[str, Optional[str]] = {}
    if tech_ids:
        users = await db.users.find(
            {"technician_id": {"$in": tech_ids}, "tenant_id": tenant_id},
            {"_id": 0, "technician_id": 1, "department": 1,
              "technician_photo_url": 1},
        ).to_list(1000)
        for u in users:
            tid = u.get("technician_id")
            if not tid:
                continue
            dept_map[tid] = u.get("department")
            photo_map[tid] = u.get("technician_photo_url") or None
    for d in docs:
        tid = d.get("technician_id")
        dept = dept_map.get(tid)
        d["technician_department"] = dept
        d["checklist_kind"] = _derive_checklist_kind(d, dept)
        d["assignee_photo_url"] = photo_map.get(tid) if tid else None




@router.get("/jobs",
    response_model=List[JobListItem],
    summary="List jobs",
    responses={200: {"description": (
        "Job rows scoped to the caller's role + tenant. Beyond the "
        "standard job fields, every row includes the following Feb-2026 "
        "MP2 UI enrichments (present as ``null`` when not applicable):\n\n"
        "- ``property_label`` (str | null) — display label of the linked "
        "property when ``property_id`` is set.\n"
        "- ``property_address`` (str | null) — comma-joined address of "
        "the linked property.\n"
        "- ``customer_is_vip`` (bool), ``customer_gate_code`` (str | "
        "null), ``customer_notes`` (str | null), ``service_note`` (str | "
        "null) — surfaced from the customer doc so schedule cards render "
        "without an N+1 fetch."
    )}})
async def list_jobs(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
    status: Optional[str] = None,
    technician_id: Optional[str] = Query(None),
    start: Optional[str] = Query(None, description="Phase 30: inclusive lower bound on scheduled_date (YYYY-MM-DD)"),
    end: Optional[str] = Query(None, description="Phase 30: inclusive upper bound on scheduled_date (YYYY-MM-DD)"),
    scheduled_date: Optional[str] = Query(None, description="Phase 51.0/52: exact date (YYYY-MM-DD) — matches bare date or ISO datetime prefix"),
    recurring_template_id: Optional[str] = Query(None, description="Phase 51.I: filter by recurring template origin"),
    limit: int = Query(1000, ge=1, le=5000, description="Feb-2026: cap on returned rows; default 1000"),
    include_deleted: bool = Query(False, description="Feb-2026 · super_admin only — include soft-deleted jobs"),
):
    q = scope_jobs_query(user, tenant, status, technician_id)
    # Feb-2026 · Schedule multi-select soft-delete — hide rows with
    # ``deleted_at`` set by default. Only a ``super_admin`` may pass
    # ``?include_deleted=true`` to view (and later undelete) previously-
    # removed jobs. Any other role that passes the flag is silently
    # ignored — defense in depth.
    is_super = (user.get("role") or "").lower() == "super_admin"
    if not (include_deleted and is_super):
        q["$or"] = [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]
    # Phase 30 · optional inclusive date-range filter so the new calendar
    # can ask the backend for a bounded window instead of pulling all 1000
    # jobs and filtering client-side. Both ends are optional.
    if start or end:
        rng: Dict[str, str] = {}
        if start: rng["$gte"] = start
        if end:   rng["$lte"] = end
        q["scheduled_date"] = rng
    # Phase 51.0 fix — exact scheduled_date match. Some jobs store the
    # value as bare `YYYY-MM-DD`, others as full ISO datetime — regex
    # covers both. Overrides the range filter above when explicitly set.
    if scheduled_date:
        q["scheduled_date"] = {"$regex": f"^{scheduled_date}"}
    # Phase 51.I fix — recurring-template origin filter.
    if recurring_template_id:
        q["recurring_template_id"] = recurring_template_id
    # Feb-2026 hygiene fix — ``limit`` param now actually caps the
    # to_list() call. Previously the query silently returned 1000
    # regardless of ``?limit=X``.
    docs = await db.jobs.find(q, {"_id": 0}).sort("scheduled_date", 1).to_list(limit)
    # Phase 57.d — enrich every returned job with the assigned tech's
    # department + derived checklist_kind so schedule/dispatch cards +
    # mobile clients see the right form without a per-job GET.
    await _enrich_jobs_dept_and_kind(docs, tenant["id"])
    if user.get("role") == "customer":
        for d in docs:
            d.pop("internal_notes", None)
    else:
        # Surface account-level gate code + notes on each job so techs see them on the
        # schedule without opening the job.
        cids = list({d.get("customer_id") for d in docs if d.get("customer_id")})
        if cids:
            custs = await db.customers.find(
                {"id": {"$in": cids}, "tenant_id": tenant["id"]},
                {"_id": 0, "id": 1, "notes": 1, "gate_code": 1, "is_vip": 1,
                  "service_notes": 1},
            ).to_list(1000)
            cmap = {c["id"]: c for c in custs}
            for d in docs:
                c = cmap.get(d.get("customer_id"))
                if c:
                    d["account_notes"] = c.get("notes", "")
                    d["gate_code"] = c.get("gate_code", "")
                    # Phase 34d-follow — surface VIP flag on the job payload
                    # so schedule/dispatch cards can render a badge without an
                    # extra roundtrip. Missing/legacy docs → False.
                    d["customer_is_vip"] = bool(c.get("is_vip"))
                    # Phase 34d-follow-b — expose gate_code + notes under
                    # `customer_*` aliases so newer schedule surfaces can rely
                    # on a single, consistent naming convention. Legacy
                    # `gate_code` / `account_notes` keys are retained above
                    # for backward-compat with older consumers.
                    d["customer_gate_code"] = c.get("gate_code") or None
                    d["customer_notes"] = c.get("notes") or None
                    # Feb-2026 service-notes ship + tester fix — surface the note
                    # matching this job's service_type OR job_type (legacy
                    # alias). Substring match survives values like
                    # "Weekly Pool Service". Only the relevant snippet
                    # is returned so mobile payloads stay cheap.
                    from routers.customers import _resolve_service_note
                    d["service_note"] = _resolve_service_note(
                        c, d.get("service_type") or d.get("job_type"), user,
                    )
                else:
                    d["customer_is_vip"] = False
                    d["customer_gate_code"] = None
                    d["customer_notes"] = None
                    d["service_note"] = None
    # Feb-2026 MP2 UI — enrich each job with the property label so
    # mobile schedule rows can render a chip without an N+1 fetch. The
    # property doc's address is also surfaced under ``property_address``
    # for the tech's Job Detail hero card. AE1 hygiene fix — both keys
    # are ALWAYS present (null when the job has no property_id) so
    # admin + tech responses share a consistent shape.
    for d in docs:
        d.setdefault("property_label", None)
        d.setdefault("property_address", None)
    try:
        pids = list({d.get("property_id") for d in docs if d.get("property_id")})
        if pids:
            props = await db.properties.find(
                {"id": {"$in": pids}, "tenant_id": tenant["id"]},
                {"_id": 0, "id": 1, "label": 1, "address": 1},
            ).to_list(len(pids) * 2)
            pmap = {p["id"]: p for p in props}
            for d in docs:
                pid = d.get("property_id")
                if pid and pid in pmap:
                    p = pmap[pid]
                    d["property_label"] = p.get("label") or None
                    addr = p.get("address") or {}
                    d["property_address"] = ", ".join(
                        [x for x in (addr.get("line1"), addr.get("city"),
                                          addr.get("state"), addr.get("postal_code")) if x]
                    ) or None
    except Exception:
        # Non-fatal — the chip just doesn't render.
        pass
    # Phase 16C add-on: strip revenue/pricing fields for technicians.
    if user.get("role") == "technician":
        for d in docs:
            for k in ("price", "cost", "total", "subtotal", "tax_amount",
                      "revenue", "invoice_total", "quote_total", "margin",
                      "labor_cost", "materials_cost", "gross_margin"):
                d.pop(k, None)

    # Phase 46.2 closeout — augment each job with pill-state booleans so the
    # mobile Workstream card can render green/gray without extra roundtrips.
    # Reads the latest service report per job (best-effort).
    try:
        jids = [d.get("id") for d in docs if d.get("id")]
        if jids:
            reports = await db.service_reports.find(
                {"tenant_id": tenant["id"], "job_id": {"$in": jids}},
                {"_id": 0, "job_id": 1, "chemical_readings": 1, "chemicals_added": 1,
                 "checklist_items": 1, "notes": 1, "updated_at": 1},
            ).to_list(len(jids) * 2)
            by_job: dict = {}
            for r in reports:
                # Keep the last write per job.
                by_job[r.get("job_id")] = r
            for d in docs:
                rep = by_job.get(d.get("id"))
                readings = (rep or {}).get("chemical_readings") or []
                chems = (rep or {}).get("chemicals_added") or []
                checks = (rep or {}).get("checklist_items") or []
                d["has_water_readings"] = any(
                    (r.get("value") not in (None, "")) for r in readings
                )
                d["has_chemicals_added"] = len(chems) > 0
                d["has_checklist"] = any(bool(c.get("checked")) for c in checks)
                d["has_private_note"] = bool(d.get("account_notes") or (rep or {}).get("notes"))
                d["has_public_note"] = bool(d.get("customer_note"))
                d["has_repair_request"] = bool(d.get("repair_request"))
                d["has_shopping_request"] = bool(d.get("shopping_request"))
                # Phase 50.F — expose the newest activity timestamp on the
                # job so the mobile JobCard can render a red-dot badge when
                # updates land after the tech's last-viewed timestamp
                # (stored client-side in AsyncStorage).
                candidates = [
                    d.get("updated_at"),
                    d.get("last_activity_at"),
                    (rep or {}).get("updated_at"),
                ]
                # Include the tech's most recent note if it's a datetime
                # string (rare but possible on legacy schemas).
                candidates = [c for c in candidates if isinstance(c, str) and c]
                if candidates:
                    d["last_activity_at"] = max(candidates)
    except Exception as _e:
        # Never let this augmentation break the jobs list — pills just render gray.
        for d in docs:
            d.setdefault("has_water_readings", False)
            d.setdefault("has_chemicals_added", False)
            d.setdefault("has_checklist", False)
    return docs


@router.post("/jobs")
async def create_job(body: JobIn,
                     user: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    doc = body.dict()
    customer = await db.customers.find_one(
        {"id": body.customer_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not customer:
        raise HTTPException(400, "Customer not found")
    doc["customer_name"] = customer["name"]
    if not doc.get("address"):
        doc["address"] = customer.get("address", "")
    # Feb-2026 MP1 — property_id validation. If the customer has ≥2
    # active properties, the caller MUST specify which property this
    # job is for. If the customer has exactly 1 active property, we
    # auto-assign to it. If 0 properties exist (legacy customers), we
    # don't touch the field.
    if not doc.get("property_id"):
        active_props = await db.properties.find(
            {"tenant_id": tenant["id"], "customer_id": body.customer_id,
              "active": {"$ne": False}},
            {"_id": 0, "id": 1},
        ).to_list(10)
        if len(active_props) >= 2:
            raise HTTPException(400, (
                "property_id required — this customer has multiple "
                f"active properties ({len(active_props)}). Specify "
                "which property this job is for."
            ))
        if len(active_props) == 1:
            doc["property_id"] = active_props[0]["id"]
    tech_name = None
    if body.technician_id:
        tech = await db.technicians.find_one(
            {"id": body.technician_id, "tenant_id": tenant["id"]}, {"_id": 0}
        )
        tech_name = tech["name"] if tech else None
        doc["technician_avatar"] = tech.get("avatar", "") if tech else ""
    doc["technician_name"] = tech_name
    doc.update({"id": new_id(), "tenant_id": tenant["id"], "photos": [], "created_at": now_iso()})
    await db.jobs.insert_one(doc)
    # Phase 26.1 — auto-assign on create if enabled.
    try:
        from routers.dispatch import maybe_auto_assign_on_create
        assignment = await maybe_auto_assign_on_create(
            tenant["id"], doc, user["id"])
        if assignment:
            doc["technician_id"] = assignment["tech_id"]
            doc["technician_name"] = assignment["tech_name"]
            doc["assigned_to"] = assignment["assigned_to"]
            doc["auto_assigned"] = True
    except Exception:
        pass
    doc.pop("_id", None)
    # Comms Phase 3 — fire job.scheduled when the new job already has a
    # concrete schedule. Non-blocking.
    try:
        if doc.get("scheduled_date"):
            from services.automation_engine import emit as _emit
            await _emit(
                "job.scheduled",
                {"job": doc, "customer": {"id": doc.get("customer_id"),
                                             "name": doc.get("customer_name")}},
                tenant_id=tenant["id"],
                entity_kind="job", entity_id=doc["id"],
                customer_id=doc.get("customer_id"),
            )
    except Exception:
        pass
    return doc


# ─── Phase 2 additive endpoints ────────────────────────────────────────────

@router.post("/jobs/recurrence-preview")
async def jobs_recurrence_preview(body: dict, user: dict = Depends(require_admin)):
    """Preview the next N visits for a recurring job (weekly / biweekly / monthly).
    body: { start_date: "YYYY-MM-DD", cadence: "weekly|biweekly|monthly", count?: int }
    """
    from datetime import date, timedelta
    start_raw = body.get("start_date")
    cadence = body.get("cadence", "weekly")
    count = int(body.get("count", 4))
    if not start_raw:
        raise HTTPException(400, "start_date is required")
    try:
        start = date.fromisoformat(start_raw)
    except ValueError:
        raise HTTPException(400, "start_date must be YYYY-MM-DD")
    step = {"weekly": 7, "biweekly": 14}.get(cadence)
    dates: list[str] = []
    cur = start
    for _ in range(max(1, min(24, count))):
        dates.append(cur.isoformat())
        if step:
            cur = cur + timedelta(days=step)
        elif cadence == "monthly":
            m = cur.month + 1
            y = cur.year + (1 if m > 12 else 0)
            m = m if m <= 12 else m - 12
            try:
                cur = cur.replace(year=y, month=m)
            except ValueError:
                # e.g. Jan 31 -> Feb 28
                cur = cur.replace(year=y, month=m, day=28)
        else:
            raise HTTPException(400, f"Unknown cadence: {cadence}")
    return {"cadence": cadence, "count": len(dates), "dates": dates}


@router.post("/jobs/{jid}/reopen")
async def reopen_job(jid: str,
                     user: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    """Flip a completed job back to 'active' and log an activity entry."""
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    if job.get("status") not in ("completed", "cancelled"):
        raise HTTPException(400, "Only completed or cancelled jobs can be reopened")
    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"]},
        {"$set": {"status": "active", "reopened_at": now_iso()}, "$unset": {"completed_at": ""}},
    )
    try:
        await db.activity_logs.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "job_id": jid,
            "type": "reopen",
            "actor_id": user["id"],
            "actor_name": user.get("name", ""),
            "at": now_iso(),
            "note": "Job reopened by admin",
        })
    except Exception:
        pass
    updated = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
    return updated


async def _build_work_order_pdf(job: dict, tenant: dict) -> bytes:
    """Shared PDF builder so both work_order_pdf and email_work_order can produce
    the same output without one calling the other (avoiding tenant-plumbing pain)."""
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors as rlcolors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    )

    jid = job["id"]
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, title=f"Work Order {jid[:8]}")
    styles = getSampleStyleSheet()
    story = []
    story.append(Paragraph("<b>Work Order</b>", styles["Title"]))
    story.append(Paragraph(
        "Pool &amp; Landscaping of Vistancia", styles["Normal"]
    ))
    story.append(Spacer(1, 12))
    rows = [
        ["Work Order #", jid[:8].upper()],
        ["Job Title", job.get("title", "")],
        ["Service Type", job.get("service_type", "")],
        ["Status", (job.get("status") or "").title()],
        ["Scheduled", job.get("scheduled_date") or "—"],
        ["Customer", job.get("customer_name", "")],
        ["Address", job.get("address", "")],
        ["Technician", job.get("technician_name") or "Unassigned"],
        ["Notes", job.get("notes", "") or "—"],
    ]
    t = Table(rows, colWidths=[1.4 * inch, 5.0 * inch])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 10),
        ("BACKGROUND", (0, 0), (0, -1), rlcolors.HexColor("#F4F4F5")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, rlcolors.HexColor("#E4E4E7")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 18))
    checklist = (job.get("field_report") or {}).get("checklist") or []
    if checklist:
        story.append(Paragraph("<b>Checklist</b>", styles["Heading3"]))
        for item in checklist:
            mark = "[x]" if item.get("done") else "[ ]"
            story.append(Paragraph(f"{mark} {item.get('label', '')}", styles["Normal"]))
        story.append(Spacer(1, 12))
    # Terms & Conditions — pulled from a linked quote/invoice if the job has one,
    # otherwise from tenant defaults so every work order still carries our terms.
    linked_quote_id = job.get("quote_id") or job.get("invoice_id")
    terms_text = None
    if linked_quote_id:
        linked = await db.quotes.find_one(
            {"id": linked_quote_id, "tenant_id": tenant["id"]},
            {"_id": 0, "terms": 1},
        )
        if linked:
            terms_text = linked.get("terms")
    if not terms_text:
        try:
            from routers.finances import get_terms_defaults
            terms_text = (await get_terms_defaults())["default_quote_terms"]
        except Exception:
            terms_text = ""
    if terms_text:
        story.append(Paragraph("<b>Terms &amp; Conditions</b>", styles["Heading3"]))
        story.append(Paragraph(terms_text.replace("\n", "<br/>"), styles["Normal"]))
        story.append(Spacer(1, 12))
    story.append(Spacer(1, 40))
    story.append(Paragraph("Technician Signature: ______________________________", styles["Normal"]))
    story.append(Spacer(1, 20))
    story.append(Paragraph("Customer Signature: ________________________________", styles["Normal"]))
    doc.build(story)
    pdf = buf.getvalue()
    buf.close()
    return pdf


@router.get("/jobs/{jid}/work-order.pdf")
async def work_order_pdf(jid: str,
                         user: dict = Depends(get_current_user),
                         tenant: dict = Depends(get_current_tenant)):
    """Streams a printable work-order PDF for the given job."""
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    # role scoping
    if user.get("role") == "technician" and job.get("technician_id") != user.get("technician_id"):
        raise HTTPException(403, "Not your job")
    if user.get("role") == "customer" and job.get("customer_id") != user.get("customer_id"):
        raise HTTPException(403, "Not your job")
    pdf = await _build_work_order_pdf(job, tenant)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="work-order-{jid[:8]}.pdf"'},
    )


@router.post("/jobs/{jid}/work-order/email")
async def email_work_order(jid: str, body: dict,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    """Emails the work-order PDF to the given address via Resend.
    body: { to?: str, subject?: str, message?: str }
    Falls back gracefully with `sent=False, reason='resend-not-configured'` if RESEND_API_KEY absent."""
    import base64
    from config import RESEND_API_KEY
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    to = (body.get("to") or "").strip().lower()
    if not to:
        customer = await db.customers.find_one(
            {"id": job["customer_id"], "tenant_id": tenant["id"]}, {"_id": 0}
        ) or {}
        to = (customer.get("email") or "").strip().lower()
    if not to:
        raise HTTPException(400, "No recipient email available")
    if not RESEND_API_KEY:
        return {"sent": False, "reason": "resend-not-configured", "to": to}
    pdf_bytes = await _build_work_order_pdf(job, tenant)
    try:
        import resend
        from config import EMAIL_FROM
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from": EMAIL_FROM or "onboarding@resend.dev",
            "to": [to],
            "subject": body.get("subject") or f"Work Order · {job.get('title', 'Service')}",
            "html": body.get("message") or f"<p>Attached is the work order for <strong>{job.get('title', '')}</strong>.</p>",
            "attachments": [{
                "filename": f"work-order-{jid[:8]}.pdf",
                "content": base64.b64encode(pdf_bytes).decode("ascii"),
            }],
        })
        return {"sent": True, "to": to}
    except Exception as e:
        logger.warning(f"Work-order email failed: {e}")
        return {"sent": False, "reason": str(e), "to": to}


@router.post("/service-requests")
async def create_service_request(body: ServiceRequestIn,
                                 user: dict = Depends(get_current_user),
                                 tenant: dict = Depends(get_current_tenant)):
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Only customers can request services")
    customer = await db.customers.find_one(
        {"id": user["customer_id"], "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not customer:
        raise HTTPException(404, "Customer profile not found")
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "title": body.title or f"{body.service_type} Request",
        "customer_id": customer["id"],
        "customer_name": customer["name"],
        "technician_id": None,
        "technician_name": None,
        "address": customer.get("address", ""),
        "service_type": body.service_type,
        "scheduled_date": body.scheduled_date,
        "notes": body.notes,
        "price": 0.0,
        "status": "requested",
        "photos": [],
        "created_at": now_iso(),
    }
    await db.jobs.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/jobs/{jid}")
async def get_job(jid: str,
                  user: dict = Depends(get_current_user),
                  tenant: dict = Depends(get_current_tenant)):
    doc = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Job not found")
    if user.get("role") == "technician" and doc.get("technician_id") != user.get("technician_id"):
        raise HTTPException(403, "Not your job")
    if user.get("role") == "customer" and doc.get("customer_id") != user.get("customer_id"):
        raise HTTPException(403, "Not your job")
    doc = with_field_report(doc)
    # Phase 57.d · read-time enrichment — tech department + derived
    # checklist_kind. Never mutates the stored job doc.
    await _enrich_job_dept_and_kind(doc, tenant["id"])
    if user.get("role") == "customer":
        doc.pop("internal_notes", None)
    # Phase 16C add-on: strip revenue/pricing fields from technician responses.
    if user.get("role") == "technician":
        for k in ("price", "cost", "total", "subtotal", "tax_amount",
                  "revenue", "invoice_total", "quote_total", "margin",
                  "labor_cost", "materials_cost", "gross_margin"):
            doc.pop(k, None)
    return doc


@router.put("/jobs/{jid}/field-report")
async def update_field_report(jid: str, body: FieldReportUpdate,
                              user: dict = Depends(get_current_user),
                              tenant: dict = Depends(get_current_tenant)):
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]})
    if not job:
        raise HTTPException(404, "Job not found")
    if user.get("role") == "technician" and job.get("technician_id") != user.get("technician_id"):
        raise HTTPException(403, "Not your job")
    update = {k: v for k, v in body.dict().items() if v is not None}
    if update:
        await db.jobs.update_one({"id": jid, "tenant_id": tenant["id"]}, {"$set": update})
    # Auto-bill: when chemicals are logged, accrue them onto the customer's monthly invoice.
    if "chemicals_added" in update:
        from routers.finances import accrue_chem_invoice
        job_fresh = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
        await accrue_chem_invoice(job_fresh)
        # QuoteIQ Q1-B — snapshot chemical usage for profitability rollups.
        # Idempotent per (tenant, service_report_id=jid): re-submits replace
        # prior events instead of double-counting.
        try:
            from routers.chemical_products import snapshot_chemical_usage
            await snapshot_chemical_usage(
                tenant_id=tenant["id"],
                job_id=jid,
                service_report_id=jid,
                customer_id=(job_fresh or {}).get("customer_id"),
                chemicals_added=update.get("chemicals_added") or [],
                occurred_at=(job_fresh or {}).get("scheduled_date")
                             or (job_fresh or {}).get("updated_at"),
                actor_user_id=user.get("id"),
            )
        except Exception as _e:
            pass  # snapshot failure never blocks the field-report write
    return with_field_report(
        await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
    )


@router.get("/reports/log-history")
async def log_history(customer_id: str,
                      admin: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    """Admin service-log report for one customer: every visit's water-test readings + chemical usage."""
    cust = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "name": 1, "address": 1},
    )
    if not cust:
        raise HTTPException(404, "Customer not found")
    techs = {t["id"]: t.get("name", "") async for t in db.technicians.find(
        {"tenant_id": tenant["id"]}, {"_id": 0, "id": 1, "name": 1}
    )}
    jobs = await db.jobs.find(
        {"customer_id": customer_id, "tenant_id": tenant["id"]}, {"_id": 0}
    ).to_list(3000)
    entries = []
    for j in jobs:
        j = with_field_report(j)
        readings = j.get("reading_report") or []
        chemicals = [c for c in (j.get("chemicals_added") or []) if c.get("amount") not in (None, "", 0, "0")]
        if not readings and not chemicals:
            continue
        entries.append({
            "job_id": j["id"],
            "title": j.get("title", ""),
            "service_type": j.get("service_type", ""),
            "status": j.get("status", ""),
            "date": j.get("scheduled_date") or (j.get("created_at") or "")[:10],
            "technician": j.get("technician_name") or techs.get(j.get("technician_id"), ""),
            "readings": readings,
            "chemicals": chemicals,
        })
    entries.sort(key=lambda e: e.get("date") or "", reverse=True)
    return {"customer": cust, "count": len(entries), "entries": entries}



@router.put("/jobs/{jid}")
async def update_job(jid: str, body: JobUpdate,
                     user: dict = Depends(get_current_user),
                     tenant: dict = Depends(get_current_tenant)):
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]})
    if not job:
        raise HTTPException(404, "Job not found")
    if user.get("role") == "technician" and job.get("technician_id") != user.get("technician_id"):
        raise HTTPException(403, "Not your job")
    update = {k: v for k, v in body.dict().items() if v is not None}
    if "technician_id" in update:
        tech = await db.technicians.find_one(
            {"id": update["technician_id"], "tenant_id": tenant["id"]}, {"_id": 0}
        )
        update["technician_name"] = tech["name"] if tech else None
        update["technician_avatar"] = tech.get("avatar", "") if tech else ""
    if update:
        await db.jobs.update_one({"id": jid, "tenant_id": tenant["id"]}, {"$set": update})

    # Phase 15C — realtime broadcast of status changes to assigned tech + admins.
    if update.get("status") and update["status"] != job.get("status"):
        try:
            from routers.realtime import bus
            payload = {
                "job_id": jid,
                "old_status": job.get("status"),
                "new_status": update["status"],
                "customer_name": job.get("customer_name"),
                "title": job.get("title"),
            }
            tid = update.get("technician_id") or job.get("technician_id")
            if tid:
                tech_user = await db.users.find_one(
                    {"technician_id": tid, "tenant_id": tenant["id"]}, {"_id": 0}
                )
                if tech_user:
                    await bus.broadcast(tech_user["id"], {"type": "job_status_change", "payload": payload})
            admins = await db.users.find(
                {"role": "admin", "tenant_id": tenant["id"]}, {"_id": 0, "id": 1}
            ).to_list(100)
            for a in admins:
                await bus.broadcast(a["id"], {"type": "job_status_change", "payload": payload})
        except Exception as e:
            logger.warning(f"realtime job_status_change broadcast failed: {e}")

    # Notify the customer of meaningful changes (in-app + optional SMS)
    cid = job.get("customer_id")
    if cid:
        if update.get("status") == "pending" and job.get("status") == "requested":
            when = update.get("scheduled_date") or job.get("scheduled_date") or "soon"
            await notify_customer(cid, "Appointment confirmed",
                                  f"Your {job.get('service_type', 'service')} is confirmed for {when}.", job_id=jid, sms=True)
            # Close the booking loop: drop a confirmation into the customer's chat thread.
            await db.messages.insert_one({
                "id": new_id(), "tenant_id": tenant["id"],
                "customer_id": cid, "sender": "business",
                "sender_name": "Marina (AI)", "ai": True,
                "text": f"🎉 Good news! Your {job.get('service_type', 'service')} is confirmed for {when}. See you then!",
                "read_by_customer": False, "read_by_staff": True, "created_at": now_iso(),
            })
        if update.get("technician_id") and update.get("technician_id") != job.get("technician_id"):
            await notify_customer(cid, "Technician assigned",
                                  f"{update.get('technician_name')} was assigned to your {job.get('service_type', 'service')}.", job_id=jid)
        if update.get("scheduled_date") and update.get("scheduled_date") != job.get("scheduled_date"):
            await notify_customer(cid, "Service scheduled",
                                  f"Your service is scheduled for {update['scheduled_date']}.", job_id=jid)
        if update.get("status") == "completed" and job.get("status") != "completed":
            # Auto-stop the job timer (no manual stop): record duration if it was running.
            if job.get("timer_started_at") and not job.get("timer_stopped_at"):
                stopped = now_iso()
                dur = _timer_seconds(job["timer_started_at"], stopped)
                await db.jobs.update_one({"id": jid, "tenant_id": tenant["id"]}, {"$set": {
                    "timer_stopped_at": stopped,
                    "timer_duration_seconds": dur,
                    "timer_stop_method": "job_completed",
                }})
            await notify_customer(cid, "Service complete",
                                  f"Your {job.get('service_type', 'service')} is complete. View your report in the app.", job_id=jid)
            fresh = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
            await send_completion_email(fresh)
            # True recurrence: auto-book the next filter/salt-cell cleaning on the cadence.
            from routers.maintenance import create_recurring_maintenance
            await create_recurring_maintenance(fresh)
            # Phase 11 · Feb 2026 — auto-log the cleaning against the
            # unified equipment_service_trackers collection. Idempotent
            # + never raises (see log_cleaning_from_job).
            try:
                from routers.equipment_trackers import log_cleaning_from_job
                await log_cleaning_from_job(fresh)
            except Exception as _et:
                logger.warning(f"equipment tracker auto-log failed: {_et}")
            # Phase 22 · 2026-08-02 · Sub-item C — auto-create + charge
            # invoice on job complete. Never crashes this handler:
            # the helper swallows all exceptions and writes an audit row.
            try:
                from services.auto_invoice import create_invoice_from_job
                await create_invoice_from_job(jid, tenant["id"])
            except Exception as _ai:
                logger.warning(f"auto_invoice hook failed: {_ai}")
            # Phase 15A: schedule a CSAT survey 24h after completion.
            try:
                from routers.csat import maybe_schedule_survey_for_job
                await maybe_schedule_survey_for_job(fresh)
            except Exception as e:
                logger.warning(f"csat schedule failed: {e}")
            # Comms Phase 3 — job.completed automation.
            try:
                from services.automation_engine import emit as _emit
                await _emit(
                    "job.completed",
                    {"job": fresh, "customer": {"id": fresh.get("customer_id"),
                                                   "name": fresh.get("customer_name")}},
                    tenant_id=tenant["id"],
                    entity_kind="job", entity_id=jid,
                    customer_id=fresh.get("customer_id"),
                )
            except Exception:
                pass
            # Feb-2026 · Item 8 · auto-trigger a review request when a
            # job is marked completed, unless the tenant opted out via
            # ``settings.review_auto_request_after_job=False``. Own
            # dedup logic (14 days) inside the helper.
            try:
                from services.review_auto_request import maybe_auto_request_after_job
                await maybe_auto_request_after_job(tenant, fresh)
            except Exception as _e_r:
                logger.warning(f"review auto-request skipped: {_e_r}")

    # Comms Phase 3 — job.scheduled automation. Fires when the update
    # newly assigns/changes ``scheduled_date`` (transition semantics
    # keep repeated saves idempotent thanks to the engine's 24h dedup).
    try:
        new_sched = update.get("scheduled_date")
        if new_sched and new_sched != job.get("scheduled_date"):
            fresh_j = await db.jobs.find_one(
                {"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
            if fresh_j:
                from services.automation_engine import emit as _emit
                await _emit(
                    "job.scheduled",
                    {"job": fresh_j, "customer": {"id": fresh_j.get("customer_id"),
                                                     "name": fresh_j.get("customer_name")}},
                    tenant_id=tenant["id"],
                    entity_kind="job", entity_id=jid,
                    customer_id=fresh_j.get("customer_id"),
                )
    except Exception:
        pass

    return await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.get("/public/job-photo/{jid}/{pid}")
async def public_job_photo(jid: str, pid: str):
    """Unauthenticated image endpoint for embedding job photos in emails (UUID-gated).
    Intentionally NOT tenant-scoped — the {jid}+{pid} pair acts as the magic token."""
    job = await db.jobs.find_one({"id": jid}, {"_id": 0, "photos": 1})
    if not job:
        raise HTTPException(404, "Not found")
    photo = next((p for p in (job.get("photos") or []) if p["id"] == pid), None)
    if not photo:
        raise HTTPException(404, "Not found")
    data = photo["data"]
    if "," in data:
        header, b64 = data.split(",", 1)
        media = header.split(";")[0].replace("data:", "") or "image/jpeg"
    else:
        b64, media = data, "image/jpeg"
    import base64
    return Response(content=base64.b64decode(b64), media_type=media)


@router.delete("/jobs/{jid}")
async def delete_job(jid: str,
                     user: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    res = await db.jobs.delete_one({"id": jid, "tenant_id": tenant["id"]})
    await db.notifications.delete_many({"job_id": jid, "tenant_id": tenant["id"]})
    return {"ok": True, "deleted": res.deleted_count}


# ═════════════════════════════════════════════════════════════════════════
# Feb-2026 · Schedule multi-select soft-delete
# ═════════════════════════════════════════════════════════════════════════
class BulkSoftDeleteIn(BaseModel):
    job_ids: List[str]


_HISTORICAL_COMPLETED_DAYS = 30


async def _perform_soft_delete_job(jid: str, user: dict, tenant: dict) -> dict:
    """Shared soft-delete helper — enforces the historical-completed
    guardrail and writes the audit row. Called from both the single
    and bulk endpoints so behavior is identical.

    Raises HTTPException on any refusal; returns the response dict on
    success. Caller decides how to surface failures (single endpoint
    re-raises; bulk endpoint captures the ``detail`` into ``failed``).
    """
    job = await db.jobs.find_one(
        {"id": jid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "status": 1, "deleted_at": 1,
          "completed_at": 1, "scheduled_date": 1},
    )
    if not job:
        raise HTTPException(404, "Job not found")
    if job.get("deleted_at"):
        return {"ok": True, "job_id": jid, "already_deleted": True}

    # Historical-completed guardrail — protect audit trail. If the job
    # is ``completed`` AND its ``completed_at`` (or falling back to
    # ``scheduled_date``) is more than 30 days ago, refuse.
    if (job.get("status") or "").lower() == "completed":
        pivot = job.get("completed_at") or job.get("scheduled_date")
        if pivot:
            try:
                # Support both ``yyyy-mm-dd`` and full ISO strings.
                pivot_dt = datetime.fromisoformat(str(pivot).replace("Z", "+00:00"))
                if pivot_dt.tzinfo is None:
                    pivot_dt = pivot_dt.replace(tzinfo=timezone.utc)
                age = datetime.now(timezone.utc) - pivot_dt
                if age > timedelta(days=_HISTORICAL_COMPLETED_DAYS):
                    raise HTTPException(400,
                        "Cannot delete historical completed jobs older than 30 days")
            except HTTPException:
                raise
            except Exception:
                # Malformed date → be conservative and allow the delete
                # (the audit log still records the operation).
                pass

    deleted_at = now_iso()
    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"]},
        {"$set": {"deleted_at": deleted_at,
                    "deleted_by_user_id": user.get("id")}},
    )
    # Cascade — cancel any pending notifications tied to this job.
    try:
        await db.notifications.update_many(
            {"job_id": jid, "tenant_id": tenant["id"], "read_at": None},
            {"$set": {"read_at": deleted_at, "cancelled_by": "job.soft_delete"}},
        )
    except Exception as e:
        logger.warning(f"job.soft_delete notification cancel failed: {e}")

    # Audit row — best-effort.
    try:
        await db.audit_log.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "action": "job.soft_delete",
            "target_job_id": jid,
            "at": deleted_at,
        })
    except Exception as e:
        logger.warning(f"job.soft_delete audit failed: {e}")

    return {"ok": True, "job_id": jid,
              "deleted_at": deleted_at,
              "deleted_by_user_id": user.get("id")}


@router.post("/jobs/{jid}/soft-delete",
              operation_id="jobs.softDelete")
async def soft_delete_job(jid: str,
                             user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    """Feb-2026 · Schedule multi-select — soft-delete a single job.

    Sets ``deleted_at`` + ``deleted_by_user_id``, cancels any pending
    notifications tied to the job, and writes an audit row. Refuses
    if the job is a completed job older than 30 days (protects the
    audit trail from tampering).
    """
    return await _perform_soft_delete_job(jid, user, tenant)


@router.post("/jobs/bulk-soft-delete",
              operation_id="jobs.bulkSoftDelete")
async def bulk_soft_delete_jobs(body: BulkSoftDeleteIn,
                                  user: dict = Depends(require_admin),
                                  tenant: dict = Depends(get_current_tenant)):
    """Feb-2026 · Schedule multi-select — bulk soft-delete wrapper.

    Iterates the shared helper so per-job guardrails still apply.
    Caps at 100 rows per call to keep the request bounded. Response
    surfaces both successes and failures so the UI can toast a summary
    like "Deleted 8 of 10 (2 failed)".
    """
    ids = list(body.job_ids or [])
    if not ids:
        raise HTTPException(400, "job_ids is empty")
    if len(ids) > 100:
        raise HTTPException(400, "bulk soft-delete capped at 100 rows per call")

    deleted: List[str] = []
    failed: List[Dict[str, Any]] = []
    for jid in ids:
        try:
            r = await _perform_soft_delete_job(jid, user, tenant)
            deleted.append(r["job_id"])
        except HTTPException as e:
            failed.append({"job_id": jid, "reason": str(e.detail),
                              "status_code": e.status_code})
        except Exception as e:                                # noqa: BLE001
            failed.append({"job_id": jid, "reason": str(e), "status_code": 500})

    return {"ok": True, "count": len(deleted),
              "deleted": deleted, "failed": failed}


# ═════════════════════════════════════════════════════════════════════════
# Phase 28 · Feb-2026 · Schedule multi-select — bulk reassign to a new tech
# ═════════════════════════════════════════════════════════════════════════
class BulkReassignIn(BaseModel):
    job_ids: List[str]
    new_tech_id: str


_TECH_ROLES = {"pool_tech", "landscape_tech", "technician", "tech"}
_BULK_REASSIGN_CAP = 100


async def _lookup_tech_user(tenant_id: str, tech_id: str) -> Optional[dict]:
    """Resolve a tech identifier to its user row. The frontend may pass
    either ``users.technician_id`` (preferred — matches the job schema)
    or ``users.id`` — try both so callers don't have to disambiguate."""
    if not tech_id:
        return None
    row = await db.users.find_one(
        {"technician_id": tech_id, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "technician_id": 1, "role": 1,
          "name": 1, "first_name": 1, "email": 1},
    )
    if row:
        return row
    return await db.users.find_one(
        {"id": tech_id, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "technician_id": 1, "role": 1,
          "name": 1, "first_name": 1, "email": 1},
    )


@router.post("/jobs/bulk-reassign", operation_id="jobs.bulkReassign")
async def bulk_reassign_jobs(body: BulkReassignIn,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    """Phase 28 · Feb-2026 · Schedule multi-select — reassign N jobs
    to a single tech in one call. Response mirrors the bulk-soft-delete
    shape: ``{ok, count, reassigned, failed}``.

    Per-job behavior:
      * Skipped when the job is not found or is soft-deleted → recorded
        in ``failed`` with a reason string.
      * ``assigned_tech_id`` (legacy alias) + ``technician_id`` (current
        canonical field) are both written so downstream code that
        reads either sees the new value.
      * Writes an ``audit_log`` row and a bell-channel notification to
        BOTH the outgoing (if any) and incoming techs.
    """
    ids = list(dict.fromkeys(body.job_ids or []))
    if not ids:
        raise HTTPException(400, "job_ids is empty")
    if len(ids) > _BULK_REASSIGN_CAP:
        raise HTTPException(
            400, f"bulk reassign capped at {_BULK_REASSIGN_CAP} rows per call")

    if not body.new_tech_id:
        raise HTTPException(400, "new_tech_id is required")

    new_user = await _lookup_tech_user(tenant["id"], body.new_tech_id)
    if not new_user:
        raise HTTPException(400, "new_tech_id does not resolve to a user")
    role = (new_user.get("role") or "").lower()
    if role not in _TECH_ROLES:
        raise HTTPException(
            400, f"new_tech_id role {role!r} is not a technician role")
    canonical_tech_id = new_user.get("technician_id") or new_user.get("id")

    reassigned: List[str] = []
    failed: List[Dict[str, Any]] = []
    outgoing_touches: Dict[str, List[str]] = {}   # old_user_id → [job_title]
    incoming_titles: List[str] = []
    now = now_iso()
    audit_rows: List[Dict[str, Any]] = []

    for jid in ids:
        job = await db.jobs.find_one(
            {"id": jid, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "technician_id": 1, "assigned_tech_id": 1,
              "title": 1, "service_type": 1, "deleted_at": 1},
        )
        if not job:
            failed.append({"job_id": jid, "reason": "not found",
                            "status_code": 404})
            continue
        if job.get("deleted_at"):
            failed.append({"job_id": jid, "reason": "job is deleted",
                            "status_code": 409})
            continue

        old_tech_id = (job.get("technician_id")
                         or job.get("assigned_tech_id") or None)
        if old_tech_id == canonical_tech_id:
            # No-op — already assigned. Not an error, just record it
            # into the success bucket so counts add up.
            reassigned.append(jid)
            continue

        try:
            await db.jobs.update_one(
                {"id": jid, "tenant_id": tenant["id"]},
                {"$set": {"technician_id": canonical_tech_id,
                            "assigned_tech_id": canonical_tech_id,
                            "reassigned_at": now,
                            "reassigned_by_user_id": user.get("id"),
                            "updated_at": now}},
            )
        except Exception as e:                                    # noqa: BLE001
            failed.append({"job_id": jid, "reason": str(e)[:200],
                            "status_code": 500})
            continue

        reassigned.append(jid)
        title = str(job.get("title") or job.get("service_type") or f"Job {jid[:8]}")
        incoming_titles.append(title)
        audit_rows.append({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "action": "job.reassign",
            "target_job_id": jid,
            "old_tech_id": old_tech_id,
            "new_tech_id": canonical_tech_id,
            "at": now,
        })
        if old_tech_id and old_tech_id != canonical_tech_id:
            # Resolve outgoing tech user_id for notification.
            old_user = await _lookup_tech_user(tenant["id"], old_tech_id)
            if old_user and old_user.get("id"):
                outgoing_touches.setdefault(old_user["id"], []).append(title)

    # Persist audit rows in one batch — non-fatal if it fails.
    if audit_rows:
        try:
            await db.audit_log.insert_many(audit_rows)
        except Exception as e:
            logger.warning(f"job.reassign audit insert failed: {e}")

    # In-app notifications. NO SMS / email — per Phase 28 brief.
    if reassigned:
        try:
            from services.notifications import emit as _emit_notif
            # New tech — one aggregate notification.
            new_user_id = new_user.get("id")
            if new_user_id:
                preview = ", ".join(incoming_titles[:3])
                more = len(incoming_titles) - 3
                if more > 0:
                    preview = f"{preview}, +{more} more"
                await _emit_notif(
                    user_ids=[new_user_id], kind="job_assigned",
                    title=f"You've been assigned {len(incoming_titles)} job(s)",
                    body=preview or "See your schedule for details.",
                    source_ref={"kind": "bulk_reassign",
                                 "count": len(incoming_titles)},
                    href="/schedule", priority="normal",
                    tenant_id=tenant["id"])
            # Old techs — one aggregate notification per outgoing user.
            for old_uid, titles in outgoing_touches.items():
                preview = ", ".join(titles[:3])
                more = len(titles) - 3
                if more > 0:
                    preview = f"{preview}, +{more} more"
                await _emit_notif(
                    user_ids=[old_uid], kind="job_unassigned",
                    title=f"{len(titles)} job(s) reassigned away from you",
                    body=preview or "Your schedule has been updated.",
                    source_ref={"kind": "bulk_reassign",
                                 "count": len(titles)},
                    href="/schedule", priority="normal",
                    tenant_id=tenant["id"])
        except Exception as e:
            logger.warning(f"job.reassign notification fan-out failed: {e}")

    return {"ok": True, "count": len(reassigned),
              "reassigned": reassigned, "failed": failed,
              "new_tech_id": canonical_tech_id,
              "new_tech_name": (new_user.get("name")
                                  or new_user.get("first_name") or "")}


@router.post("/jobs/{jid}/undelete",
              operation_id="jobs.undelete")
async def undelete_job(jid: str,
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    """Feb-2026 · Schedule multi-select — restore a soft-deleted job.

    Phase 34 · Task X · Feb 2026 — restore is now available to any
    admin-equivalent role (admin, super_admin, owner) on the acting
    tenant. Idempotent — returns ``already_active=true`` when
    the job wasn't deleted in the first place.
    """
    if (user.get("role") or "").lower() not in ("admin", "super_admin", "owner"):
        raise HTTPException(403, "Admin role required to undelete jobs")
    job = await db.jobs.find_one(
        {"id": jid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1, "deleted_at": 1})
    if not job:
        raise HTTPException(404, "Job not found")
    if not job.get("deleted_at"):
        return {"ok": True, "job_id": jid, "already_active": True}
    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"]},
        {"$set": {"deleted_at": None, "deleted_by_user_id": None,
                    "undeleted_at": now_iso(),
                    "undeleted_by_user_id": user.get("id")}},
    )
    try:
        await db.audit_log.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "action": "job.undelete",
            "target_job_id": jid,
            "at": now_iso(),
        })
    except Exception as e:
        logger.warning(f"job.undelete audit failed: {e}")
    return {"ok": True, "job_id": jid, "restored_at": now_iso()}


@router.post("/jobs/{jid}/on-my-way")
async def on_my_way(jid: str,
                    user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant)):
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    if user.get("role") == "technician" and job.get("technician_id") != user.get("technician_id"):
        raise HTTPException(403, "Not your job")
    tech_name = job.get("technician_name") or user.get("name", "Your technician")
    await notify_customer(
        job.get("customer_id"),
        "Technician on the way",
        f"{tech_name} is on the way to your {job.get('service_type', 'service')} appointment.",
        job_id=jid,
        sms=True,
    )
    return {"ok": True, "notified": True}


@router.post("/jobs/{jid}/arrive")
async def job_arrive(jid: str, body: JobArriveIn,
                     user: dict = Depends(get_current_user),
                     tenant: dict = Depends(get_current_tenant)):
    """Auto-start the job timer on GPS arrival (idempotent). No manual start/stop."""
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    if user.get("role") == "technician" and job.get("technician_id") != user.get("technician_id"):
        raise HTTPException(403, "Not your job")
    # persist geocoded site coords for geofencing/reporting if provided
    site = {}
    if body.site_lat is not None and body.site_lng is not None:
        site = {"site_lat": body.site_lat, "site_lng": body.site_lng}
    if job.get("timer_started_at"):
        if site:
            await db.jobs.update_one({"id": jid, "tenant_id": tenant["id"]}, {"$set": site})
        return {"started": True, "already_running": True, "timer_started_at": job["timer_started_at"]}
    if job.get("status") == "completed":
        return {"started": False, "reason": "job_completed"}
    started = now_iso()
    upd = {"timer_started_at": started, "timer_start_method": "gps_arrival",
           "arrival_lat": body.lat, "arrival_lng": body.lng, **site}
    if job.get("status") in (None, "pending", "requested", "scheduled"):
        upd["status"] = "in_progress"
    await db.jobs.update_one({"id": jid, "tenant_id": tenant["id"]}, {"$set": upd})
    return {"started": True, "already_running": False, "timer_started_at": started}


@router.get("/reports/job-timers")
async def job_timers_report(technician_id: Optional[str] = None, customer_id: Optional[str] = None,
                            q: Optional[str] = None,
                            admin: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    """Admin report of automated job timers, filterable by technician, customer, and free text."""
    query: dict = {"tenant_id": tenant["id"], "timer_started_at": {"$exists": True, "$ne": None}}
    if technician_id:
        query["technician_id"] = technician_id
    if customer_id:
        query["customer_id"] = customer_id
    jobs = await db.jobs.find(query, {"_id": 0}).to_list(5000)
    cust_ids = list({j.get("customer_id") for j in jobs if j.get("customer_id")})
    custs = {c["id"]: c async for c in db.customers.find(
        {"id": {"$in": cust_ids}, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "name": 1, "address": 1},
    )}
    now = now_iso()
    rows = []
    qlc = (q or "").strip().lower()
    for j in jobs:
        c = custs.get(j.get("customer_id"), {})
        running = bool(j.get("timer_started_at")) and not j.get("timer_stopped_at")
        dur = j.get("timer_duration_seconds")
        if running:
            dur = _timer_seconds(j["timer_started_at"], now)
        row = {
            "job_id": j["id"],
            "title": j.get("title", ""),
            "service_type": j.get("service_type", ""),
            "customer_id": j.get("customer_id", ""),
            "customer_name": c.get("name", ""),
            "address": j.get("address") or c.get("address", ""),
            "technician_id": j.get("technician_id", ""),
            "technician_name": j.get("technician_name", ""),
            "date": j.get("scheduled_date") or (j.get("created_at") or "")[:10],
            "started_at": j.get("timer_started_at"),
            "stopped_at": j.get("timer_stopped_at"),
            "duration_seconds": dur or 0,
            "running": running,
            "status": j.get("status", ""),
        }
        if qlc and qlc not in f"{row['customer_name']} {row['technician_name']} {row['address']} {row['service_type']}".lower():
            continue
        rows.append(row)
    rows.sort(key=lambda r: r.get("started_at") or "", reverse=True)
    total = sum(r["duration_seconds"] for r in rows)
    return {"count": len(rows), "total_seconds": total, "rows": rows}


@router.get("/reports/avg-job-time")
async def avg_job_time_report(q: Optional[str] = None,
                              admin: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    """Average on-site time per customer, from completed automated job timers."""
    jobs = await db.jobs.find(
        {
            "tenant_id": tenant["id"],
            "timer_duration_seconds": {"$gt": 0},
            "timer_stopped_at": {"$exists": True, "$ne": None},
        },
        {"_id": 0, "customer_id": 1, "timer_duration_seconds": 1, "timer_stopped_at": 1, "scheduled_date": 1},
    ).to_list(10000)
    cust_ids = list({j.get("customer_id") for j in jobs if j.get("customer_id")})
    custs = {c["id"]: c async for c in db.customers.find(
        {"id": {"$in": cust_ids}, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "name": 1, "address": 1},
    )}
    agg: dict = {}
    for j in jobs:
        cid = j.get("customer_id")
        if not cid:
            continue
        a = agg.setdefault(cid, {"visits": 0, "total": 0, "last": ""})
        a["visits"] += 1
        a["total"] += int(j.get("timer_duration_seconds") or 0)
        last = j.get("timer_stopped_at") or j.get("scheduled_date") or ""
        if last > a["last"]:
            a["last"] = last
    qlc = (q or "").strip().lower()
    rows = []
    for cid, a in agg.items():
        c = custs.get(cid, {})
        name, addr = c.get("name", ""), c.get("address", "")
        if qlc and qlc not in f"{name} {addr}".lower():
            continue
        rows.append({
            "customer_id": cid,
            "customer_name": name,
            "address": addr,
            "visits": a["visits"],
            "total_seconds": a["total"],
            "avg_seconds": round(a["total"] / a["visits"]) if a["visits"] else 0,
            "last_visit": (a["last"] or "")[:10],
        })
    rows.sort(key=lambda r: r["avg_seconds"], reverse=True)
    total_secs = sum(r["total_seconds"] for r in rows)
    total_visits = sum(r["visits"] for r in rows)
    return {
        "count": len(rows),
        "total_visits": total_visits,
        "overall_avg_seconds": round(total_secs / total_visits) if total_visits else 0,
        "rows": rows,
    }


SKIPPED_STATUSES = ["skipped", "cancelled", "canceled", "no_show", "missed"]


def _service_week(anchor_iso: str | None):
    """Return (monday, sunday) ISO dates for the week containing anchor (default today)."""
    d = datetime.fromisoformat(anchor_iso[:10]).date() if anchor_iso else datetime.now(timezone.utc).date()
    monday = d - timedelta(days=d.weekday())
    return monday.isoformat(), (monday + timedelta(days=6)).isoformat()


@router.get("/reports/pool-service")
async def pool_service_report(date_from: Optional[str] = Query(None),
                              date_to: Optional[str] = Query(None),
                              admin: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    """Weekly pool-service summary: pools completed per technician (excluding skipped visits).

    Meant to be pulled every Friday. Defaults to the current service week (Mon-Sun).
    """
    return await compute_pool_service(tenant["id"], date_from, date_to)


# ─── Phase 50.G · Auto-Friday email delivery history ─────────────────
@router.get("/reports/pool-service/email-history")
async def pool_service_email_history(
    limit: int = Query(10, ge=1, le=50),
    admin: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Return the most recent Pool Service Report auto-email attempts
    (success + MOCKED) for this tenant."""
    rows = await db.email_delivery_log.find(
        {"tenant_id": tenant["id"], "kind": "pool_service_report"},
        {"_id": 0},
    ).sort("sent_at", -1).to_list(limit)
    return {"items": rows, "count": len(rows)}


# ─── Phase 52.A · Monthly pricing digest email history ──────────────
@router.get("/reports/pricing-insights/email-history")
async def pricing_insights_email_history(
    limit: int = Query(10, ge=1, le=50),
    admin: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    rows = await db.email_delivery_log.find(
        {"tenant_id": tenant["id"], "kind": "monthly_pricing_digest"},
        {"_id": 0},
    ).sort("sent_at", -1).to_list(limit)
    return {"items": rows, "count": len(rows)}


# ─── Phase 50.D · Job Margin Leaderboard ─────────────────────────────
@router.get("/reports/job-margin-leaderboard")
async def job_margin_leaderboard(
    days: int = Query(60, ge=7, le=365),
    limit: int = Query(20, ge=1, le=100),
    admin: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Rank closed jobs in the last `days` by margin percentage.

    Uses the same live costing logic as `GET /api/jobs/{id}/costing`
    so numbers stay consistent with the per-job drilldown page. Only
    jobs marked `completed` in the window are considered."""
    from routers.budgets import job_costing  # avoid circular at import time
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    jobs_cur = db.jobs.find(
        {"tenant_id": tenant["id"], "status": "completed",
         "$or": [
             {"service_report_submitted_at": {"$gte": cutoff}},
             {"updated_at": {"$gte": cutoff}},
             {"scheduled_date": {"$gte": cutoff[:10]}},
         ]},
        {"_id": 0},
    )
    jobs_list = await jobs_cur.to_list(1000)
    rows: List[dict] = []
    for j in jobs_list:
        try:
            costing = await job_costing(j["id"], admin, tenant)
        except HTTPException:
            continue
        except Exception as e:
            logger.warning(f"margin_leaderboard costing skip: {e}")
            continue
        revenue = int((costing.get("baseline") or {}).get("revenue_cents") or 0)
        cost = int(((costing.get("actual") or {}).get("labor_cents") or 0)
                   + ((costing.get("actual") or {}).get("materials_cents") or 0)
                   + ((costing.get("actual") or {}).get("equipment_cents") or 0))
        margin = revenue - cost
        pct = round(margin / revenue * 100, 2) if revenue > 0 else 0.0
        rows.append({
            "job_id": j["id"],
            "customer": j.get("customer_name") or "—",
            "service_type": j.get("service_type") or j.get("job_type") or "",
            "title": j.get("title") or "",
            "revenue_cents": revenue,
            "cost_cents": cost,
            "margin_cents": margin,
            "margin_pct": pct,
            "service_date": (j.get("service_report_submitted_at")
                             or j.get("scheduled_date")
                             or (j.get("updated_at") or "")[:10]),
        })
    # Sort by margin_pct desc, then clip to `limit`.
    rows.sort(key=lambda r: r["margin_pct"], reverse=True)
    return {"items": rows[:limit], "count": len(rows[:limit]),
            "window_days": days, "total_evaluated": len(rows)}


# ─── Phase 52.A · Monthly Least-Profitable Service Type Digest ──────
@router.get("/reports/least-profitable-services")
async def least_profitable_services(
    month: Optional[str] = Query(None, description="YYYY-MM; defaults to previous month"),
    limit: int = Query(3, ge=1, le=10),
    admin: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Aggregate closed jobs in the given month by service_type and rank
    ascending by margin_pct so the operator can spot the least-profitable
    service lines. Cost math uses the same per-job costing helper as the
    Job Margin Leaderboard."""
    from routers.budgets import job_costing
    # Default to previous month.
    now = datetime.now(timezone.utc)
    if month:
        try:
            y, m = month.split("-")
            y, m = int(y), int(m)
        except Exception:
            raise HTTPException(422, "month must be YYYY-MM")
    else:
        y = now.year if now.month > 1 else now.year - 1
        m = now.month - 1 if now.month > 1 else 12
    period_start = datetime(y, m, 1, tzinfo=timezone.utc)
    period_end = (datetime(y, m + 1, 1, tzinfo=timezone.utc)
                    if m < 12 else datetime(y + 1, 1, 1, tzinfo=timezone.utc))
    start_iso = period_start.isoformat()
    end_iso = period_end.isoformat()

    # Fetch completed jobs in that window.
    jobs_cur = db.jobs.find(
        {"tenant_id": tenant["id"], "status": "completed",
         "$or": [
             {"service_report_submitted_at": {"$gte": start_iso, "$lt": end_iso}},
             {"updated_at": {"$gte": start_iso, "$lt": end_iso}},
         ]},
        {"_id": 0},
    )
    jobs_list = await jobs_cur.to_list(2000)

    agg: Dict[str, Dict[str, Any]] = {}
    for j in jobs_list:
        try:
            costing = await job_costing(j["id"], admin, tenant)
        except Exception:
            continue
        stype = (j.get("service_type") or j.get("title") or "Unknown").strip() or "Unknown"
        revenue = int((costing.get("baseline") or {}).get("revenue_cents") or 0)
        cost = int(((costing.get("actual") or {}).get("labor_cents") or 0)
                   + ((costing.get("actual") or {}).get("materials_cents") or 0)
                   + ((costing.get("actual") or {}).get("equipment_cents") or 0))
        hours = float((costing.get("actual") or {}).get("labor_hours") or 0)
        row = agg.setdefault(stype, {
            "service_type": stype, "job_count": 0,
            "revenue_cents": 0, "cost_cents": 0,
            "total_hours": 0.0,
        })
        row["job_count"] += 1
        row["revenue_cents"] += revenue
        row["cost_cents"] += cost
        row["total_hours"] += hours

    services: List[Dict[str, Any]] = []
    for row in agg.values():
        margin = row["revenue_cents"] - row["cost_cents"]
        pct = round(margin / row["revenue_cents"] * 100, 2) if row["revenue_cents"] > 0 else 0.0
        avg_hours = round(row["total_hours"] / row["job_count"], 2) if row["job_count"] else 0.0
        services.append({
            "service_type": row["service_type"],
            "job_count": row["job_count"],
            "revenue_cents": row["revenue_cents"],
            "cost_cents": row["cost_cents"],
            "margin_cents": margin,
            "margin_pct": pct,
            "avg_hours_per_job": avg_hours,
        })
    services.sort(key=lambda r: r["margin_pct"])
    return {"month": f"{y:04d}-{m:02d}", "services": services[:limit],
             "total_evaluated": len(services)}


async def compute_pool_service(tenant_id: str,
                               date_from: Optional[str] = None,
                               date_to: Optional[str] = None):
    if date_from and date_to:
        week_start, week_end = date_from, date_to
    else:
        week_start, week_end = _service_week(date_from or date_to)

    date_range = {"$gte": week_start, "$lte": week_end}
    jobs = await db.jobs.find(
        {"tenant_id": tenant_id, "scheduled_date": date_range},
        {"_id": 0, "technician_id": 1, "technician_name": 1, "status": 1, "scheduled_date": 1},
    ).to_list(10000)

    techs = {t["id"]: t["name"] async for t in db.technicians.find(
        {"tenant_id": tenant_id}, {"_id": 0, "id": 1, "name": 1}
    )}
    agg: dict = {}
    for j in jobs:
        tid = j.get("technician_id")
        if not tid:
            continue
        a = agg.setdefault(tid, {"completed": 0, "skipped": 0})
        status = (j.get("status") or "").lower()
        if status == "completed":
            a["completed"] += 1
        elif status in SKIPPED_STATUSES:
            a["skipped"] += 1
    rows = []
    for tid, a in agg.items():
        rows.append({
            "technician_id": tid,
            "technician_name": techs.get(tid, "Unknown"),
            "completed": a["completed"],
            "skipped": a["skipped"],
        })
    rows.sort(key=lambda r: r["completed"], reverse=True)
    return {
        "week_start": week_start,
        "week_end": week_end,
        "total_completed": sum(r["completed"] for r in rows),
        "total_skipped": sum(r["skipped"] for r in rows),
        "rows": rows,
    }




@router.get("/notifications")
async def list_notifications(user: dict = Depends(get_current_user),
                             tenant: dict = Depends(get_current_tenant)):
    q = {"customer_id": user.get("customer_id")} if user.get("role") == "customer" else {"user_id": user["id"]}
    q["tenant_id"] = tenant["id"]
    return await db.notifications.find(q, {"_id": 0}).sort("created_at", -1).to_list(100)


@router.get("/notifications/unread-count")
async def unread_count(user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    q = {"customer_id": user.get("customer_id")} if user.get("role") == "customer" else {"user_id": user["id"]}
    q["tenant_id"] = tenant["id"]
    q["read"] = False
    return {"count": await db.notifications.count_documents(q)}


@router.post("/notifications/read-all")
async def read_all(user: dict = Depends(get_current_user),
                   tenant: dict = Depends(get_current_tenant)):
    q = {"customer_id": user.get("customer_id")} if user.get("role") == "customer" else {"user_id": user["id"]}
    q["tenant_id"] = tenant["id"]
    await db.notifications.update_many(q, {"$set": {"read": True}})
    return {"ok": True}


@router.post("/jobs/{jid}/photos")
async def add_job_photo(jid: str, body: PhotoIn,
                        request: Request,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    # Phase 40 · Idempotency — offline mobile queues retry photo uploads
    # on reconnect with the same X-Idempotency-Key so a flaky signal
    # can't create duplicate images against the same job. Fingerprint the
    # full body (data + label) so a re-key on a different photo is
    # correctly flagged as a body_mismatch.
    from utils_idempotency import replay_or_reserve, store_response
    idem_body = {"data": body.data, "label": body.label or "photo"}
    idem_key, cached = await replay_or_reserve(
        request, tenant["id"], "POST /jobs/{jid}/photos", idem_body,
    )
    if cached is not None:
        return cached
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]})
    if not job:
        raise HTTPException(404, "Job not found")
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    if user.get("role") == "technician":
        assigned = job.get("technician_id")
        if assigned not in (user.get("id"), user.get("technician_id")):
            raise HTTPException(403, "Not your job")
    existing = len(job.get("photos") or [])
    if existing >= 10:
        raise HTTPException(
            status_code=400,
            detail={
                "msg": "10-photo cap reached — remove one before uploading another",
                "remaining_slots": 0,
                "existing": existing,
            },
        )
    photo = {"id": new_id(), "data": body.data, "label": body.label or "photo", "created_at": now_iso()}
    await db.jobs.update_one({"id": jid, "tenant_id": tenant["id"]}, {"$push": {"photos": photo}})
    resp = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
    if idem_key:
        await store_response(idem_key, "POST /jobs/{jid}/photos",
                              tenant["id"], resp, idem_body)
    return resp


@router.delete("/jobs/{jid}/photos/{pid}")
async def delete_job_photo(jid: str, pid: str,
                           user: dict = Depends(get_current_user),
                           tenant: dict = Depends(get_current_tenant)):
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"]}, {"$pull": {"photos": {"id": pid}}}
    )
    return await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})


# ----------------------- Service Issues -----------------------
@router.post("/jobs/{jid}/issues")
async def add_service_issue(jid: str, body: ServiceIssueIn,
                            user: dict = Depends(get_current_user),
                            tenant: dict = Depends(get_current_tenant)):
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]})
    if not job:
        raise HTTPException(404, "Job not found")
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    if user.get("role") == "technician" and job.get("technician_id") != user.get("technician_id"):
        raise HTTPException(403, "Not your job")
    issue = {
        "id": new_id(), "description": body.description, "cost": body.cost,
        "photo": body.photo, "status": "open", "reported_by": user.get("name", "Staff"),
        "created_at": now_iso(), "approved_at": None,
    }
    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"]}, {"$push": {"service_issues": issue}}
    )
    return with_field_report(
        await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
    )


@router.post("/jobs/{jid}/issues/{iid}/approve")
async def approve_service_issue(jid: str, iid: str,
                                user: dict = Depends(get_current_user),
                                tenant: dict = Depends(get_current_tenant)):
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]})
    if not job:
        raise HTTPException(404, "Job not found")
    if user.get("role") == "customer" and job.get("customer_id") != user.get("customer_id"):
        raise HTTPException(403, "Not your job")
    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"], "service_issues.id": iid},
        {"$set": {"service_issues.$.status": "approved", "service_issues.$.approved_at": now_iso()}},
    )
    updated = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
    issue = next((i for i in updated.get("service_issues", []) if i["id"] == iid), None)
    if issue:
        await create_staff_notification(
            "Repair approved",
            f"{job.get('customer_name', 'A customer')} approved the fix: {issue['description'][:60]}",
        )
    return with_field_report(updated)


@router.delete("/jobs/{jid}/issues/{iid}")
async def delete_service_issue(jid: str, iid: str,
                               user: dict = Depends(get_current_user),
                               tenant: dict = Depends(get_current_tenant)):
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"]},
        {"$pull": {"service_issues": {"id": iid}}},
    )
    return with_field_report(
        await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
    )
