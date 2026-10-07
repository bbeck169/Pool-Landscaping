# ruff: noqa: F403,F405
from fastapi import APIRouter, HTTPException, Depends, Query, Response, Request, BackgroundTasks
from pydantic import BaseModel, ConfigDict, field_validator
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
import re

from pymongo.errors import DuplicateKeyError

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, require_admin_or_manager,
                   send_sms, notify_customer, auth_response,
                   create_staff_notification)
from routers.tenants import get_current_tenant
# Feb-2026 · Phase F1 — shared crew-aware tech authorization helper.
# Every "Not your job" gate below routes through this so crew-only
# jobs (crew_id set, technician_id null OR pointing at a teammate)
# open for every member of the assigned crew. See services/authz.py.
from services.authz import is_tech_authorized_on_job
from services.geo_resolver import (
    COORD_SOURCE_JOB,
    COORD_SOURCE_CUSTOMER,
    resolve_job_coordinates,
)
from models import (
    FieldReportUpdate, JobArriveIn, JobIn, JobUpdate,
    PhotoIn, ServiceIssueIn, ServiceRequestIn,
)
from emailer import send_completion_email

router = APIRouter()


# Feb 2026 · Task B — perf index for the schedule window query.
# ``list_jobs`` filters primarily on ``(tenant_id, scheduled_date)``
# when no per-tech scoping applies (admin views). Without this
# compound index the winning plan is a collection scan across the
# tenant's entire jobs history, which balloons quadratically as
# tenants accumulate history. Idempotent — MongoDB dedupes the
# ``create_index`` call at boot. Registered via
# ``scripts/ensure_indexes.py`` so it runs once per pod start.
async def ensure_indexes() -> None:
    """Idempotent boot helper — registers the ``(tenant_id, scheduled_date)``
    compound index used by every /jobs and /schedule read path."""
    await db.jobs.create_index(
        [("tenant_id", 1), ("scheduled_date", 1)],
        name="tenant_id_1_scheduled_date_1",
        background=True,
    )


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
    # Feb-2026 · Slim-photos ship — the list endpoint drops the full
    # ``photos`` array by default and surfaces just the count + ids so
    # mobile job cards can lazy-load thumbnails without pulling ~100 KB
    # of base64 per job. Opt back in with ``?include_photos=true`` on
    # the list endpoint; the full ``photos`` field is then preserved as
    # an ``extra`` on the response (see ``model_config extra="allow"``
    # at the top of this model). Single-job detail
    # (``GET /api/jobs/{id}``) is unchanged and always ships the full
    # ``photos`` array.
    photo_count: Optional[int] = None
    photo_ids: Optional[List[str]] = None
    videos: Optional[List[Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    checklist_kind: Optional[str] = None
    account_notes: Optional[str] = None
    gate_code: Optional[str] = None
    # Feb-2026 · Schedule notes surface — ``notes`` is job-level free
    # text, capped at 500 chars server-side. ``notes_truncated`` is
    # True when the original was longer, so the client can render a
    # "…" hint / expand affordance without needing a HEAD roundtrip.
    notes_truncated: Optional[bool] = None
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

    # Phase P14 · Feb-2026 · Item 1 — address serialization safety
    # net. If a stored value slipped past the write-side gate + the
    # ``_coerce_job_address_for_read`` mutation (e.g. a bare-dict
    # value coming through a code path that doesn't call the
    # mutator), coerce here at pydantic serialization time so the
    # model NEVER emits a non-string address field.
    # ``mode="before"`` runs BEFORE type-validation, so a dict input
    # is normalised to a string before pydantic complains about it.
    @field_validator(
        "address", "property_address",
        mode="before",
    )
    @classmethod
    def _coerce_address_fields(cls, v):
        if v is None or isinstance(v, str):
            return v
        # Late-bound import to avoid a self-referential import at
        # module load time; the coercer lives further down the
        # same file.
        return _coerce_address_to_str(v)


def _timer_seconds(start_iso: str, stop_iso: str) -> Optional[int]:
    """Return the elapsed seconds between the two ISO timestamps or
    ``None`` on parse failure.

    2026-10-02 · duration_seconds=0 fix — previously returned ``0``
    on exception, which was indistinguishable from a legitimate
    0-second duration (clock skew, same-timestamp close).  Callers
    that pass the return value directly into a Mongo ``$set``
    (``routers/jobs.py::update_job`` status→completed branch) now
    land ``null`` instead of ``0``; the dashboard filter
    ``{"duration_seconds": {"$gt": 0}}`` naturally excludes
    ``null``.  The read-side report path at
    ``routers/jobs.py:5039`` display-coerces via ``dur or 0`` so a
    ``None`` falls back to ``0`` in the UI without any arithmetic
    error on the sum reducer at L5047.
    """
    try:
        a = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        b = datetime.fromisoformat(stop_iso.replace("Z", "+00:00"))
        return max(0, int((b - a).total_seconds()))
    except Exception:
        return None



# ----------------------- Jobs -----------------------
POOL_CHECKLIST = [
    # Phase 5A · Feb 2026 — canonical pool checklist. Kept in sync with
    # routers/checklists.py DEFAULT_POOL_ITEMS. Whitespace and
    # capitalisation are preserved verbatim from the product brief.
    "Skimmed Pool",
    "Brush Pool",
    "Checked Skimmer Basket",
    "Checked Pump Basket",
    "Tested Chemicals",
    "Checked Equipment",
    "Secured all Gates",
    # Phase CHK1 · Feb-2026 — three optional "emptied" items added.
    # These are OPTIONAL by design; the chemistry / required-fields
    # gate must NOT block completion when they are unchecked.
    "Emptied skimmer basket",
    "Emptied leaf canister",
    "Emptied Betta Skimmer",
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
    # Phase CHEM1 · Feb-2026 — Total Chlorine (``total_cl``) removed.
    # The chemistry gate now requires the "Required Four" only
    # (chlorine, ph, alkalinity, cyanuric_acid).
    # Phase P17.1 · Feb-2026 — canonical rename: ``free_chlorine`` →
    # ``chlorine`` end-to-end. Legacy spellings still resolve via
    # the gate's ALIAS_MAP so persisted docs / legacy templates
    # keep working; the seed uses the new canonical.
    {"key": "chlorine", "label": "Chlorine", "unit": "ppm", "ideal": "1–3", "min": 1, "max": 3},
    {"key": "ph", "label": "pH", "unit": "", "ideal": "7.4–7.6", "min": 7.4, "max": 7.6},
    {"key": "alkalinity", "label": "Alkalinity", "unit": "ppm", "ideal": "80–120", "min": 80, "max": 120},
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
    # Phase L1.2 · Feb-2026 — legacy 2-way keyword classifier.
    # Preserved as a safety-net fallback (see
    # ``services.industry_derivation.derive_industry_for_job``).
    # ``derive_industry_for_job`` is now the canonical entry point;
    # callers that want tenant-aware resolution should use it
    # directly.  This shim only runs when the derivation returns
    # ``None`` AND the caller has no other signal.
    return "landscaping" if "landscap" in (service_type or "").lower() else "pool"


def with_field_report(doc: dict, tenant: Optional[Dict[str, Any]] = None) -> dict:
    """Attach job_type + default checklist/reading template so technicians always
    get the correct field report (pool vs landscaping). Also attaches customer-friendly
    qualitative ratings for any recorded chemical readings.

    Phase L1.2 · Feb-2026 — tenant-aware derivation.  Accepts an
    optional ``tenant`` doc; if supplied, prefers
    ``derive_industry_for_job(job, tenant)`` and only falls back to
    the legacy ``classify_job`` keyword match when the derivation
    returns ``None``.  A debug metric fires on every fallback so we
    can track adoption of tenant-configured defaults.
    """
    # Lazy import to avoid a circular between routers/jobs and the
    # newly-added service module.
    from services.industry_derivation import derive_industry_for_job

    derived = derive_industry_for_job(doc, tenant)
    if derived is None:
        # Legacy safety-net.  ``classify_job`` always returns one of
        # ``"pool"`` / ``"landscaping"`` so downstream template
        # picks still work.  Log a debug metric so we can measure
        # how often the fallback fires post-migration.
        try:
            from config import logger as _logger
            _logger.debug(
                "[industry_derivation] fallback fired tenant=%s job=%s "
                "service_type=%s",
                (tenant or {}).get("id"),
                doc.get("id"),
                doc.get("service_type"),
            )
        except Exception:                                   # noqa: BLE001
            pass
        derived = classify_job(doc.get("service_type"))

    jt = derived
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


async def scope_jobs_query(user: dict, tenant: dict, status: Optional[str], technician_id: Optional[str]) -> dict:
    """Feb-2026 · Backlog Item 3 — technicians now see crew-only jobs
    (jobs with a ``crew_id`` but no ``technician_id``) when they are
    a member of that crew. Previously the ``technician_id`` filter
    dropped every crew-assigned job from the individual tech's
    schedule view. The query now uses ``$or`` when the caller is a
    tech in one-or-more crews so a job matches if EITHER
    ``technician_id == user's tech id`` OR
    ``crew_id IN <user's crews>``.

    Async because the crew lookup requires a Motor call. The single
    call site (``list_jobs``) is already async.

    Phase P9-A · Feb-2026 — Technician Visibility Jail (Option B).
      • Identity-resolution: build ``tech_ids`` = ordered dedup of
        ``[user.technician_id, user.id]`` (both variants — this
        codebase carries both shapes; see K42 module docstring).
        Scoping over the full union preserves R1.1 crew-visibility
        for legacy techs stamped under ``users.id`` while also
        matching modern jobs stamped under ``technicians.id``.
      • Fail-closed: only when BOTH ids are missing (truly
        identity-less session). Returns an impossible-id sentinel
        query so Mongo yields 0 rows without touching the covered
        index plan. Silent 200 + WARN — never 403 (leak-avoidance:
        we don't reveal that the caller is a technician in a
        broken state).
      • Un-bypassable: the ``elif technician_id`` admin filter is
        unreachable for a technician caller — the tech branch
        always returns (either fail-closed or full-union scope),
        so a tech passing ``?technician_id=<other>`` can never hop
        onto the admin lane. The incoming param is silently
        ignored (pinned to the tech's own ``tech_ids`` union).
    """
    tid = tenant["id"]
    q: dict = {"tenant_id": tid}
    _role = (user.get("role") or "").lower()
    if _role == "technician":
        # ── Phase P9-A · Build the full identity union for scoping ──
        tech_ids: list = []
        for _candidate in (user.get("technician_id"), user.get("id")):
            if _candidate and _candidate not in tech_ids:
                tech_ids.append(_candidate)
        if not tech_ids:
            # Truly identity-less session → fail-closed empty.
            logger.warning(
                "[p9.jail] technician with no resolvable identity — "
                "fail-closed. tenant_id=%s endpoint=list_jobs",
                tid,
            )
            q["id"] = "__p9_jail_no_technician_id__"
            if status and status != "all":
                q["status"] = status
            return q
        tech_pk = tech_ids[0]  # kept for the crew lookup below
        # Find every crew the tech is a member of.  ``tech_ids`` on
        # crews may carry either ``technicians.id`` (modern) or
        # ``users.id`` (legacy fixture / older seeds), so match via
        # ``$in`` over the full identity union — otherwise a legacy
        # crew keyed on ``user.id`` would be invisible to a modern
        # tech resolved by ``technician_id``, and vice versa.
        #
        # CREW-SCHEDULE-FANOUT · Feb-2026 — crew branch is now
        # per-crew with each caller's ``member_added_at`` floor
        # (same contract shipped on ``routers/schedule.py``).
        # Fallback floor on legacy / un-migrated rows =
        # ``crew.created_at``.
        crew_ids: list = []
        crew_branches: list = []
        try:
            async for row in db.crews.find(
                {"tenant_id": tid, "tech_ids": {"$in": tech_ids}},
                {"_id": 0, "id": 1, "member_added_at": 1, "created_at": 1},
            ):
                if row.get("id"):
                    crew_ids.append(row["id"])
                    _added_at = None
                    _mam = row.get("member_added_at") or {}
                    for _tid_var in tech_ids:
                        if _mam.get(_tid_var):
                            _added_at = _mam[_tid_var]
                            break
                    if not _added_at:
                        _added_at = row.get("created_at")
                    _floor = str(_added_at or "")[:10]  # YYYY-MM-DD
                    _branch = {"crew_id": row["id"]}
                    if _floor:
                        _branch["scheduled_date"] = {"$gte": _floor}
                    crew_branches.append(_branch)
        except Exception:  # noqa: BLE001 — never block on membership lookup
            crew_ids = []
            crew_branches = []
        # Phase K42 / Phase P9-A · Feb-2026 — the tech's OWN jobs may
        # be persisted under either variant (technicians.id or
        # users.id) across any of :data:`JOB_TECH_FIELDS`.  Build a
        # single ``$or`` over EVERY field × EVERY id in ``tech_ids``
        # so both legacy and modern write shapes are matched.
        from services.tech_id_resolver import build_tech_field_or_clause
        _tech_or = build_tech_field_or_clause(tech_ids)
        tech_or_clauses: list = []
        if _tech_or:
            tech_or_clauses.extend(_tech_or["$or"])
        if crew_branches:
            tech_or_clauses.extend(crew_branches)
        # Preserve the single-key shape when possible so downstream
        # $and merges stay clean.
        if len(tech_or_clauses) == 1:
            q.update(tech_or_clauses[0])
        elif tech_or_clauses:
            q["$or"] = tech_or_clauses
        else:
            # Defensive — should never reach here (tech_ids is
            # non-empty at this point) but keep the sentinel so a
            # future refactor can't silently widen to tenant-scope.
            q["id"] = "__p9_jail_no_scope__"
        # NOTE: any incoming ``?technician_id=<other>`` param is
        # silently ignored — the tech branch always returns above,
        # so the ``elif technician_id`` admin lane below is
        # unreachable for a technician caller.
    elif user.get("role") == "customer":
        q["customer_id"] = user.get("customer_id")
    elif technician_id:
        # Phase K42 · Feb-2026 — tech-ID normalization.  A filter can
        # arrive as either ``technicians.id`` (legacy, authoritative)
        # or ``users.id`` (modern write path).  Historically jobs
        # were persisted under either variant across four field
        # names (see :data:`JOB_TECH_FIELDS`).  Match via ``$or`` over
        # every field × every id-variant so the operator sees every
        # job for the person regardless of write-path era.
        from services.tech_id_resolver import (  # inline import — util module lifecycle
            resolve_and_build_filter,
        )
        _variants, _or = await resolve_and_build_filter(
            technician_id, tenant_id=tenant.get("id"),
        )
        if _or:
            q.update(_or)
        else:
            # Fallback — resolver could not find the id in either
            # collection.  Preserve legacy behaviour so the caller
            # still gets an empty set (not a full-scan blow-out).
            q["technician_id"] = technician_id
    if status and status != "all":
        q["status"] = status
    return q


_LANDSCAPE_KEYWORDS = ("landscap", "lawn", "mow", "garden", "trim", "blow", "cleanup")
# Phase J1 · Feb-2026 — pool keywords mirror the frontend list at
# frontend/src/lib/checklistType.js so a job whose service_type/title
# clearly says "pool" is classified accordingly BEFORE we consult the
# assigned tech's department. Kept in lockstep with that file.
_POOL_KEYWORDS = ("pool", "chem")


def _derive_checklist_kind(job: dict, tech_department: Optional[str]) -> str:
    """Phase 57.d / 56.3.B · read-time derivation of which checklist form
    to render.

    Priority (Phase P36.1 · Feb-2026 — non-pool fallback):
      1. explicit override on the job (``pool``, ``landscape``, or
         ``non_pool``)
      2. explicit ``industry`` field on the job (``pool`` → pool,
         ``landscaping`` → landscape, anything else → ``non_pool``)
      3. **Job Title / Service Type keywords** — promoted above tech
         department so the work being performed drives the checklist
         choice (a landscaping job gets the landscape checklist even
         when assigned to a Pool tech, and vice versa)
      4. tech department
      5. ``"non_pool"`` fallback (P36.1) — the safe default for a
         multi-industry deploy. Was ``"pool"`` pre-P36.1, which
         caused every non-pool job (tree_service, hvac, pest_control,
         irrigation, fencing, snow_removal, …) to be dragged through
         the pool chemistry gate on close and rejected with
         ``chemistry_core_readings_missing``. Chemistry-gate consumers
         all fire on ``is_pool_job(job) == True`` which reduces to
         ``kind == "pool"`` — non-pool jobs now correctly bypass.

    Department semantics (Phase 56.3.B):
      • ``pool``        → pool checklist
      • ``landscaping`` → landscape checklist
      • ``both``        → tech can service either; falls through to the
        default when neither the service_type nor department is
        conclusive.

    Sync note: keep in lockstep with the web mirror
    ``frontend/src/lib/checklistType.js :: getChecklistType`` (Phase J1
    priority chain).
    """
    # 1) Explicit override on the job — always wins.
    override = (job.get("checklist_kind_override") or "").strip().lower()
    if override in ("pool", "landscape", "landscaping", "non_pool"):
        if override.startswith("landscap"):
            return "landscape"
        if override == "non_pool":
            return "non_pool"
        return "pool"
    # 2) Phase P36.1 · explicit ``industry`` field on the job — first
    # class multi-industry hint. ``pool`` → pool (chemistry gate);
    # landscape-style industries → landscape; every other known
    # industry key → non_pool (bypasses chemistry).
    industry = (job.get("industry") or "").strip().lower()
    if industry in ("pool", "pools"):
        return "pool"
    if industry in ("landscaping", "landscape"):
        return "landscape"
    if industry:
        # Any other explicit industry (tree_service, hvac, fencing,
        # snow_removal, irrigation, pest_control, ...): non_pool.
        return "non_pool"
    # 3) Job Title / Service Type / Job Type keywords — Phase J1
    #    promoted above the tech-department block. Landscape signal
    #    is checked first (historical order preserved), then pool.
    hay = " ".join(str(job.get(k) or "") for k in ("service_type", "job_type", "title")).lower()
    if any(k in hay for k in _LANDSCAPE_KEYWORDS):
        return "landscape"
    if any(k in hay for k in _POOL_KEYWORDS):
        return "pool"
    # 4) Tech department — only consulted when the job itself gave no
    #    landscape/pool signal.
    dept = (tech_department or "").lower()
    if dept == "landscaping":
        return "landscape"
    if dept == "pool":
        return "pool"
    # ``both`` (tech services either) falls through to the safe default
    # below when no service_type keyword hit.
    # 5) Fallback default (Phase P36.1) — see docstring.
    return "non_pool"


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


# ═══════════════════════════════════════════════════════════════════
# Phase P1 · Feb-2026 — Multi-Property Support on Job Create / Edit.
# ═══════════════════════════════════════════════════════════════════
# Two invariants this block locks:
#
#   1. ``jobs.address`` is ALWAYS persisted as a plain string.  A
#      previous ship let the ``property_id`` retag path in
#      ``update_job`` copy ``prop["address"]`` (a dict — see
#      ``routers/properties.py :: _AddressIn``) verbatim onto the
#      job document.  Downstream Schedule readers dereferenced
#      ``.split()`` on that dict and 500-ed.  Every write path now
#      routes through ``_stringify_property_address`` before
#      touching ``update["address"]`` / ``doc["address"]``.
#
#   2. ``property_id`` — when provided on create/update — MUST
#      belong to the SAME tenant AND the SAME customer.  Mismatch
#      returns 422 with a machine-parseable code
#      (``property_customer_mismatch`` or
#      ``property_tenant_mismatch``).  The tenant-mismatch case
#      returns the SAME 422 code + message as an unknown property
#      id so a caller can NEVER discover that a property exists
#      under another tenant.  R1 posture — cross-tenant reads /
#      writes are architecturally impossible.
# ═══════════════════════════════════════════════════════════════════
def _stringify_property_address(prop: Dict[str, Any]) -> str:
    """Canonical property-address → string formatter.

    Mirrors the pattern already used at
    ``routers/on_my_way.py:108-110`` — join ``line1``, ``city``,
    ``state`` with commas so the string reads as a human address
    on the schedule card.  Returns an empty string when every
    field is empty (caller decides whether to write it or not).

    Accepts either the canonical embedded shape
    (``{"line1": ..., "city": ..., "state": ...}``) OR a legacy
    flat string (which some tenants still carry on the customer
    doc).  ``None`` / non-dict / non-str inputs coerce safely to
    an empty string.
    """
    if prop is None:
        return ""
    addr = prop.get("address") if isinstance(prop, dict) else None
    if isinstance(addr, str):
        return addr.strip()
    if isinstance(addr, dict):
        parts = [
            addr.get(k) for k in ("line1", "city", "state")
            if addr.get(k)
        ]
        return ", ".join(str(p).strip() for p in parts if p)
    # Prop had no ``address`` field — fall through so caller can
    # decide (typically preserves the existing job address).
    return ""


# ─────────────────────────────────────────────────────────────────
# Phase P14 · Feb-2026 · Item 1 — Address-string coercion helper.
# ─────────────────────────────────────────────────────────────────
#
# Root-cause helper for the "``address`` shipped as a dict crashes
# GET /api/jobs" symptom. Never raises. Returns ``""`` on any
# unknown / falsy input.
#
#   * ``None`` / non-string / non-dict           → ``""``
#   * ``str``                                    → stripped as-is
#   * ``dict`` with ``formatted`` / ``full`` /
#     ``line1`` (having a comma)                 → prefer that
#   * otherwise concat ``street``/``line1``,
#     ``city``, ``state`` ``zip`` in that order  → comma-joined
#
# Deliberately NOT a general-purpose formatter — i18n / non-US
# postal shapes / country codes are not handled. Extending the
# concat order is the only thing that should ever change here.
def _coerce_address_to_str(value: Any) -> str:
    """Coerce any address-shaped value to a display string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""

    def _prefer(keys):
        for k in keys:
            v = value.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    preformatted = _prefer(("formatted", "full", "line1"))
    if preformatted and "," in preformatted:
        return preformatted

    street = preformatted or _prefer(
        ("street", "line1", "address", "address1", "line_1")
    )
    city   = _prefer(("city", "town", "municipality", "locality"))
    state  = _prefer(("state", "province", "region", "state_code"))
    zip_   = _prefer(("zip", "postal_code", "postcode", "zipcode", "zip_code"))

    parts: List[str] = []
    if street: parts.append(street)
    if city:   parts.append(city)
    state_zip = " ".join(x for x in (state, zip_) if x).strip()
    if state_zip: parts.append(state_zip)
    joined = ", ".join(parts)
    return " ".join(joined.split()).strip()


# Address-shaped fields on the read wire — every one gets coerced
# to a string per ``_coerce_address_to_str``. ``property_address``
# and ``address`` are typed on ``JobListItem``; the rest are
# ``extra="allow"`` passthroughs (still coerced defensively).
_ADDRESS_SHAPED_FIELDS: Tuple[str, ...] = (
    "address",
    "property_address",
    "service_address",
    "billing_address",
)


# ─────────────────────────────────────────────────────────────────
# Phase P2 · Feb-2026 — read-path safety net for legacy dict
# ``jobs.address`` values.
# ─────────────────────────────────────────────────────────────────
#
# Phase P1 locked ``jobs.address``-is-a-string on the WRITE path
# (POST / PUT / property-retag). Latent legacy docs — created before
# P1 landed OR through one of the still-unfixed write paths audited
# in ``/app/memory/PHASE_P1_ADDRESS_LEAK_AUDIT.md`` — may still
# carry a dict.  When the schedule read handlers ship such a doc to
# the frontend, ``String.split`` / ``includes`` on the client
# crashes and the whole screen is locked out.
#
# Fix: coerce on the way OUT to the client only.  Never write back
# to Mongo from a read path (Step A of the P0 triage handled the
# one bad doc surgically; ongoing writes are already covered by
# P1).
#
# Phase P14 · Feb-2026 — the coercion now runs through
# ``_coerce_address_to_str`` (above) so all address-shaped fields
# — ``address``, ``property_address``, ``service_address``,
# ``billing_address`` — share the same output contract.
#
# A WARN is logged at most once per (request, job_id, field) tuple
# so operators can find and repair any remaining latent bad docs
# without spamming the log on a large schedule fetch.
def _coerce_job_address_for_read(
    doc: Dict[str, Any],
    tenant_id: str,
    warned_ids: set,
) -> None:
    """Mutates every address-shaped field on ``doc`` so it is
    guaranteed to be a string on the wire.  No-op when they
    already are."""
    if doc is None:
        return
    for field in _ADDRESS_SHAPED_FIELDS:
        raw = doc.get(field)
        if raw is None or isinstance(raw, str):
            continue
        doc[field] = _coerce_address_to_str(raw)
        jid = doc.get("id")
        _wid = f"{jid}::{field}" if jid else None
        if _wid and _wid not in warned_ids:
            warned_ids.add(_wid)
            logger.warning(
                "jobs.read.address_coerced job_id=%s tenant_id=%s "
                "field=%s offending_type=%s",
                jid, tenant_id, field, type(raw).__name__,
            )


async def _resolve_property_for_job(
    tenant_id: str,
    customer_id: str,
    property_id: str,
) -> Dict[str, Any]:
    """Fetch + validate a ``property_id`` in a single place.

    Returns the property doc on success.  On failure raises an
    HTTPException 422 with a machine-parseable code:

      * ``property_tenant_mismatch``   — property does not exist
        under ``tenant_id``.  Also fires when the property does
        NOT exist at all (defense in depth — a caller cannot
        distinguish "wrong tenant" from "unknown id" and thus
        cannot enumerate cross-tenant property ids).
      * ``property_customer_mismatch`` — property exists in this
        tenant but belongs to a DIFFERENT customer.
    """
    prop = await db.properties.find_one(
        {"id": property_id, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "customer_id": 1, "address": 1,
          "site_lat": 1, "site_lng": 1, "latitude": 1,
          "longitude": 1, "lat": 1, "lng": 1, "label": 1},
    )
    if not prop:
        # Do NOT reveal whether the id exists under another
        # tenant — we return the same 422 as unknown-id so a
        # caller cannot enumerate.
        raise HTTPException(
            status_code=422,
            detail={"code": "property_tenant_mismatch",
                     "message": "property_id does not resolve to a "
                                 "property in this tenant"},
        )
    if prop.get("customer_id") != customer_id:
        raise HTTPException(
            status_code=422,
            detail={"code": "property_customer_mismatch",
                     "message": "property_id belongs to a different "
                                 "customer"},
        )
    return prop




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
    customer_id: Optional[str] = Query(None, description="Phase F3.5 · Feb-2026 — filter to a single customer's jobs; drops CustomerDetail's tenant-wide job fetch."),
    crew_id: Optional[str] = Query(None, description="Feb-2026 · Crew Phase A · filter by crew_id (admin-equivalent only; techs remain scoped to their own jobs by scope_jobs_query)"),
    start: Optional[str] = Query(None, description="Phase 30: inclusive lower bound on scheduled_date (YYYY-MM-DD)"),
    end: Optional[str] = Query(None, description="Phase 30: inclusive upper bound on scheduled_date (YYYY-MM-DD)"),
    scheduled_date: Optional[str] = Query(None, description="Phase 51.0/52: exact date (YYYY-MM-DD) — matches bare date or ISO datetime prefix"),
    recurring_template_id: Optional[str] = Query(None, description="Phase 51.I: filter by recurring template origin"),
    limit: int = Query(1000, ge=1, le=5000, description="Feb-2026: cap on returned rows; default 1000"),
    offset: int = Query(0, ge=0, le=100_000, description="Phase P37 · Feb-2026 — server-side offset pagination. Skips the first ``offset`` rows AFTER sorting. Composes with ``limit`` so a caller can page through by incrementing ``offset += limit``."),
    sort: Optional[str] = Query(None, description="Phase P37 · Feb-2026 — override the default sort. Accepted: ``scheduled_date_asc`` (default, preserved for existing callers), ``scheduled_date_desc`` (used by CustomerDetail jobs history). Any other value is ignored + the default is applied."),
    include_deleted: bool = Query(False, description="Feb-2026 · super_admin only — include soft-deleted jobs"),
    include_photos: bool = Query(False, description="Feb-2026 · Slim-photos ship — opt back into the full ``photos`` array on list rows. Default (``false``) drops ``photos`` and returns only ``photo_count`` + ``photo_ids`` for cheap lazy-loading."),
    response: Response = None,
):
    q = await scope_jobs_query(user, tenant, status, technician_id)
    # Phase F3.5 · Feb-2026 — customer_id filter. Applied AFTER scope_jobs_query
    # so a customer role (which forces its own customer_id) can never widen
    # the query, and so a tech's crew scope is preserved.
    if customer_id:
        role_lc = (user.get("role") or "").lower()
        if role_lc == "customer" and user.get("customer_id") != customer_id:
            raise HTTPException(403, "Not your customer")
        q["customer_id"] = customer_id
    # Feb-2026 · Schedule multi-select soft-delete — hide rows with
    # ``deleted_at`` set by default. Only a ``super_admin`` may pass
    # ``?include_deleted=true`` to view (and later undelete) previously-
    # removed jobs. Any other role that passes the flag is silently
    # ignored — defense in depth.
    is_super = (user.get("role") or "").lower() == "super_admin"
    if not (include_deleted and is_super):
        # Feb-2026 · Backlog Item 3 — the tech-crew scope may have
        # already stamped ``$or`` on the query (jobs matching
        # ``technician_id`` OR ``crew_id`` in the tech's crews).
        # Compose with the soft-delete gate using ``$and`` so a
        # blanket ``q["$or"] = ...`` doesn't clobber the scope.
        soft_delete_gate = [
            {"deleted_at": None},
            {"deleted_at": {"$exists": False}},
        ]
        if "$or" in q:
            q.setdefault("$and", [])
            q["$and"].append({"$or": q.pop("$or")})
            q["$and"].append({"$or": soft_delete_gate})
        else:
            q["$or"] = soft_delete_gate
    # Phase 30 · optional inclusive date-range filter so the new calendar
    # can ask the backend for a bounded window instead of pulling all 1000
    # jobs and filtering client-side. Both ends are optional.
    #
    # Phase P13 · Feb-2026 · P0 HOTFIX — tenant-local "today". The
    # ``scheduled_date`` field on the wire is a ``YYYY-MM-DD`` string
    # whose value was historically derived at WRITE-TIME. A job
    # scheduled for 8pm Phoenix (UTC-7) has ``scheduled_start =
    # …T03:00:00+00:00`` — old write paths derived
    # ``scheduled_date`` from the UTC datetime, stamping it as the
    # NEXT day. Reading with a tenant-local date filter then missed
    # that job entirely. Fix reads the union: match rows whose
    # ``scheduled_date`` string is in-window OR whose
    # ``scheduled_start`` datetime falls in the tenant-local day's
    # UTC boundaries. Uses ``tenant_scoped_filter`` so the extra
    # disjunction lands under ``$and`` — no dict-spread ``$or``
    # clobber (P10/P12/P12.2 audit posture preserved).
    from services.tenant_helpers import (
        get_tenant_timezone,
        tenant_day_utc_bounds as _tenant_day_utc_bounds_helper,
    )
    from services.query_scope import tenant_scoped_filter as _tsf
    _tz = get_tenant_timezone(tenant)

    def _tenant_day_utc_bounds(date_str: str):
        """Return ``[utc_start_iso, utc_end_iso)`` for a ``YYYY-MM-DD``
        interpreted in the tenant's local timezone.  Delegates to the
        shared :func:`services.tenant_helpers.tenant_day_utc_bounds`
        (Phase P15 · Feb-2026 · extraction of the original P13 body)
        so dashboard and job endpoints share one implementation."""
        return _tenant_day_utc_bounds_helper(tenant, date_str)

    if start or end:
        rng: Dict[str, str] = {}
        if start: rng["$gte"] = start
        if end:   rng["$lte"] = end
        # Phase P13 — union with the ``scheduled_start`` datetime window.
        # ``start`` / ``end`` are inclusive dates (YYYY-MM-DD) — take the
        # tenant-local midnight of ``start`` and the exclusive tenant-
        # local midnight of ``end + 1 day``, converted to UTC.
        try:
            utc_start_iso, _ = _tenant_day_utc_bounds(start) if start else (None, None)
            _, utc_end_iso = _tenant_day_utc_bounds(end) if end else (None, None)
        except Exception:
            utc_start_iso, utc_end_iso = None, None
        ss_range: Dict[str, str] = {}
        if utc_start_iso: ss_range["$gte"] = utc_start_iso
        if utc_end_iso:   ss_range["$lt"]  = utc_end_iso
        # Fold into the query via ``tenant_scoped_filter`` — the
        # existing tenant/tech-scope kwargs from ``scope_jobs_query``
        # already live on ``q``, so we only need to add ONE more
        # disjunction under ``$and``. Pull existing ``$and`` (if
        # present from the soft-delete gate) and re-append.
        _date_or = [{"scheduled_date": rng}]
        if ss_range:
            _date_or.append({"scheduled_start": ss_range})
        q.setdefault("$and", []).append({"$or": _date_or})
    # Phase 51.0 fix — exact scheduled_date match. Some jobs store the
    # value as bare `YYYY-MM-DD`, others as full ISO datetime — regex
    # covers both. Overrides the range filter above when explicitly set.
    #
    # Phase P13 · Feb-2026 — same tenant-local ``scheduled_start``
    # window union as the range branch above so a single-day fetch
    # never misses a job whose ``scheduled_date`` was mis-stamped at
    # write time.
    if scheduled_date:
        try:
            utc_start_iso, utc_end_iso = _tenant_day_utc_bounds(scheduled_date)
        except Exception:
            utc_start_iso, utc_end_iso = None, None
        _date_or = [{"scheduled_date": {"$regex": f"^{scheduled_date}"}}]
        if utc_start_iso and utc_end_iso:
            _date_or.append({"scheduled_start": {
                "$gte": utc_start_iso, "$lt": utc_end_iso,
            }})
        # Drop any prior ``scheduled_date`` range on ``q`` — the exact
        # match branch always wins per the pre-P13 contract.
        q.pop("scheduled_date", None)
        q.setdefault("$and", []).append({"$or": _date_or})
    # Phase 51.I fix — recurring-template origin filter.
    if recurring_template_id:
        q["recurring_template_id"] = recurring_template_id
    # K15 · Feb-2026 — defensive hard cap on tech/crew-scoped reads.
    #
    # P22 · Feb-2026 · P0 PROD HOTFIX — the original K15 cap clamped
    # ``limit`` to 300 rows unconditionally whenever a tech or crew
    # scope was in play. On multi-day schedule fetches (e.g. a 30-day
    # window that touches 400–600 jobs) the earlier rows in the
    # window filled the 300 slots and the tail of the range silently
    # dropped off — production symptom was "Schedule renders blank
    # from Sep 22 onward" for tech Ethan.
    #
    # New shape:
    #   • Caller passed a date range (``start`` OR ``end`` OR
    #     ``scheduled_date``) — the range itself is the natural
    #     bound, so we do NOT apply the K15 clamp. The base
    #     ``limit`` param (default 1000, max 5000) is still enforced
    #     downstream, so an unbounded blast is impossible.
    #   • Caller did NOT pass a date range — this is a "give me all
    #     my jobs" call; keep a sane cap at 1000 (was 300). If we
    #     end up returning exactly ``limit`` rows we set the
    #     ``X-Truncated: true`` response header so the UI can warn.
    #
    # The 300-row constant is intentionally gone from this file so
    # nothing later can silently re-introduce it. Covered indexes
    # (``k15_jobs_tech_schedule_status`` / ``k15_jobs_crew_schedule``)
    # comfortably serve 1000 rows on Aquaterra prod scale.
    _has_date_range = bool(start or end or scheduled_date)
    if (technician_id or crew_id) and not _has_date_range:
        limit = min(limit, 1000)
    # Feb-2026 · Crew Phase A · admin-equivalent crew filter. Techs are
    # already scoped to their own jobs by ``scope_jobs_query`` above,
    # so a tech passing ``?crew_id=`` would still only see THEIR jobs
    # — the explicit role gate here is defense-in-depth so an admin
    # UI accidentally leaking a tech session cookie can't enumerate
    # a foreign crew's roster via this filter.
    if crew_id:
        crew_role = (user.get("role") or "").lower()
        # Phase F6a · Feb-2026 — customer role can never crew-filter.
        if crew_role == "customer":
            raise HTTPException(
                403, "customer role may not filter by crew_id",
            )
        # Phase F6a · Feb-2026 — resolve the crew (tenant-scoped) so
        # we can:
        #   (a) fail fast with 404 on cross-tenant / missing crews,
        #   (b) 403 a non-admin tech who isn't a member,
        #   (c) expand the filter to ``crew_id == X OR technician_id
        #       IN crew.tech_ids`` so ad-hoc individual assignments
        #       to crew members are also captured.
        crew_row = await db.crews.find_one(
            {"id": crew_id, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "tech_ids": 1, "name": 1},
        )
        if not crew_row:
            raise HTTPException(404, "Crew not found")
        member_ids = list(crew_row.get("tech_ids") or [])
        if crew_role not in {"admin", "super_admin", "owner", "manager"}:
            # tech-level — must be a member of the crew.
            tech_pk = user.get("id")
            # Techs might identify by their ``technicians`` row id too.
            tech_alt = user.get("technician_id")
            if tech_pk not in member_ids and (
                tech_alt is None or tech_alt not in member_ids
            ):
                raise HTTPException(
                    403, "Only crew members may filter by this crew_id",
                )
        crew_or = [{"crew_id": crew_id}]
        if member_ids:
            crew_or.append({"technician_id": {"$in": member_ids}})
        # Compose with any existing ``$or`` (soft-delete gate or the
        # tech-in-crew widening from scope_jobs_query) via ``$and``.
        if "$or" in q:
            q.setdefault("$and", [])
            q["$and"].append({"$or": q.pop("$or")})
            q["$and"].append({"$or": crew_or})
        else:
            q["$or"] = crew_or
    # Feb-2026 · D2-hotfix — schedule reorder read-path.  The previous
    # ``.sort([("scheduled_date", 1), ("route_index", 1), ("created_at",
    # 1)])`` sorted by the FULL ``scheduled_date`` string as primary,
    # which — because most jobs persist ``scheduled_date`` as a full
    # ISO datetime like ``2026-08-22T11:00:00+00:00`` — meant
    # ``route_index`` never got a chance to influence ordering within a
    # day (the time portion of ``scheduled_date`` decided every
    # comparison first).  As a result admin-assigned reorderings via
    # ``POST /api/jobs/reorder`` persisted correctly to Mongo but
    # visually "reverted" on refresh because the CalendarSchedule +
    # mobile schedule both consume this endpoint.
    #
    # Fix: normalize ``scheduled_date`` to the ``YYYY-MM-DD`` day prefix
    # in-pipeline (so multi-day queries still order by day first), then
    # sort by ``route_index`` within that day, and only THEN fall back
    # to ``scheduled_date`` (time portion) + ``created_at`` for
    # untouched days.  ``$ifNull`` sends missing / null route indexes
    # to a large sentinel so they sink to the end within their day.
    # K65.fix · Feb-2026 — index-covered sort + Python re-sort.
    #
    # Previous shape sorted on a derived ``_day`` field
    # (``$substrCP`` of ``scheduled_date``), which no index covers →
    # in-memory blocking sort before ``$limit`` on the entire match
    # set. On Aquaterra prod scale (~3k rows in a 90-day admin
    # window) that added 300–700 ms and risked the 100 MB sort
    # memory ceiling.
    #
    # New shape sorts by ``scheduled_date`` directly — covered by
    # both ``(tenant_id, scheduled_date)`` and
    # ``k15_jobs_tech_schedule_status``. After ``to_list`` we
    # stable-sort in Python by the same
    # ``(_day, _ri, scheduled_date, created_at)`` tuple the
    # aggregation used to compute. Python sort of ≤ 1000 rows
    # costs < 2 ms and the Mongo side is now streamable +
    # index-covered.
    #
    # ``allowDiskUse=True`` is added as a defense-in-depth guard so
    # a future caller widening the window can't hard-error on a
    # sort spill.
    # Feb-2026 · PERF-MONGO-PROJECT-EXCLUDE-PHOTOS-ON-JOBS-READS.
    # The aggregate pipeline's ``$project`` narrows to ``{_id: 0}``
    # AND drops ``photos.data`` (base64 blob subfield) when the
    # caller did NOT opt into ``include_photos=true``. The opt-in
    # branch keeps the full projection so downstream consumers
    # that legitimately need full photos over the wire still get
    # them. See ``services/jobs_slim_photos.py`` module comment.
    # Phase P37 · Feb-2026 — server-side pagination + optional sort
    # override. Default sort (scheduled_date ASC) is preserved for
    # every legacy caller. ``sort=scheduled_date_desc`` flips it for
    # CustomerDetail's "most-recent first" jobs history. ``offset``
    # is inserted BETWEEN $sort and $limit so the skipped rows are
    # deterministic + tenant-scoped.
    _sort_stage: Dict[str, int] = {"scheduled_date": 1}
    if sort == "scheduled_date_desc":
        _sort_stage = {"scheduled_date": -1}
    pipeline: list[dict] = [
        {"$match": q},
        {"$sort": _sort_stage},
    ]
    if offset:
        pipeline.append({"$skip": int(offset)})
    pipeline.append({"$limit": int(limit)})
    pipeline.append(
        {"$project": ({"_id": 0} if include_photos
                        else {"_id": 0, "photos.data": 0})},
    )
    docs = await db.jobs.aggregate(pipeline, allowDiskUse=True).to_list(limit)
    # P22 · Feb-2026 — truncation signal. When the read fills the cap
    # exactly, we flag it via a response header so the UI can surface
    # a "results truncated, narrow your filter" banner. Only fires
    # for the defensive "no date range" branch — callers with an
    # explicit window are already bounded by their own range. The
    # header is a no-op for direct-function-call tests (no
    # ``response`` object injected).
    if (
        response is not None
        and not _has_date_range
        and len(docs) >= int(limit)
    ):
        response.headers["X-Truncated"] = "true"
    # In-Python re-sort to preserve the pre-K65.fix ordering
    # contract: by DAY (YYYY-MM-DD prefix of scheduled_date),
    # then by admin-assigned route_index, then by full scheduled_date
    # (time portion), then by created_at.  Missing route_index
    # sinks to the end within its day (999999 sentinel matches the
    # prior aggregation ``$ifNull`` behaviour).
    #
    # Phase P37 · Feb-2026 — respect the caller's ``sort`` override.
    # Pre-P37 this re-sort always applied ASC and silently clobbered
    # the Mongo-side ``-1`` sort. New shape: flip ``reverse=True``
    # when ``sort=scheduled_date_desc`` so the composite key is
    # inverted end-to-end (day, route_index, ts, created_at all
    # flip together).
    def _re_sort_key(d: dict) -> tuple:
        sd = d.get("scheduled_date") or ""
        day = sd[:10] if isinstance(sd, str) else ""
        ri = d.get("route_index")
        ri_val = ri if isinstance(ri, (int, float)) else 999999
        ca = d.get("created_at") or ""
        return (day, ri_val, sd, ca)
    docs.sort(key=_re_sort_key, reverse=(sort == "scheduled_date_desc"))
    # Feb-2026 · P0 — bulk read-time cascade for the ``technician_name``
    # denorm. The list surface historically returned the stored value
    # verbatim; jobs stamped before the Feb-2026 write-side denorm fix
    # carry ``None`` on that field (or a stale name if the tech was
    # renamed), and the frontend renders empty strings as "Unassigned".
    # ``bulk_enrich_technicians`` (rich variant) runs the same 5-rung
    # cascade the write helper uses, over the 4-shape ``effective_tid``
    # union, AND stamps ``technician_active`` so the schedule can
    # badge deactivated techs. Response-only — no DB mutation.
    from services.tech_assignment import bulk_enrich_technicians
    await bulk_enrich_technicians(db, tenant["id"], docs)
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
            # K65.fix · Feb-2026 — bounded-batch customer enrichment.
            #
            # The previous ``.to_list(1000)`` silently capped the
            # enrichment at 1000 customers.  At Aquaterra prod scale
            # a 90-day admin schedule window can touch 1,100–1,800
            # unique customers; the tail rows lost their
            # gate_code / notes / VIP / coord enrichment WITHOUT
            # any log or error signal.
            #
            # New shape iterates ``cids`` in chunks of 500 and
            # concatenates. Batched projection = same Mongo cost as
            # the old query for realistic tenants (both use the
            # ``id`` index and stream through matched docs); the
            # only cost is one extra round-trip per 500 customers,
            # which is negligible next to the payload size.
            #
            # A warning is logged if the total unique customer
            # count exceeds a soft ceiling (5,000) so ops sees a
            # signal before the endpoint is asked to enrich a
            # tenant-wide fan-out.
            _CUST_CHUNK = 500
            _CUST_SOFT_CEIL = 5000
            if len(cids) > _CUST_SOFT_CEIL:
                logger.warning(
                    "[k65.fix] jobs.list customer enrichment exceeded "
                    "soft ceiling: tenant=%s unique_customers=%d",
                    tenant["id"], len(cids),
                )
            custs: list = []
            for _i in range(0, len(cids), _CUST_CHUNK):
                _chunk = cids[_i:_i + _CUST_CHUNK]
                _rows = await db.customers.find(
                    {"id": {"$in": _chunk}, "tenant_id": tenant["id"]},
                    {"_id": 0, "id": 1, "notes": 1, "gate_code": 1,
                      "is_vip": 1, "service_notes": 1,
                      # Feb-2026 · Schedule map pins — surface the
                      # customer's geocoded coords so the schedule
                      # map can render a pin without an N+1 customer
                      # lookup. Both keys are aliased to
                      # ``location_lat`` / ``location_lng`` on the
                      # job payload below so consumers key on a
                      # single naming convention regardless of source.
                      "service_lat": 1, "service_lng": 1},
                ).to_list(len(_chunk))
                custs.extend(_rows)
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
                    # Feb-2026 · Schedule map pins — expose the customer's
                    # geocoded coords under the ``location_*`` alias the
                    # web + mobile schedule maps consume. ``None`` when
                    # the customer hasn't been geocoded (pin is skipped
                    # client-side; no fake coords ever rendered).
                    #
                    # K58 · Feb-2026 — this is now only the LOWEST rung
                    # of the coord resolver ladder.  The dedicated K58
                    # ladder block below may UPGRADE these values to a
                    # higher-priority source (job.site_lat/lng or
                    # job.latitude/longitude or property.latitude/
                    # longitude) if one is available.  Left in place
                    # so pre-Slice-A behaviour is preserved when no
                    # higher rung fires.
                    lat = c.get("service_lat")
                    lng = c.get("service_lng")
                    d["location_lat"] = float(lat) if lat is not None else None
                    d["location_lng"] = float(lng) if lng is not None else None
                else:
                    d["customer_is_vip"] = False
                    d["customer_gate_code"] = None
                    d["customer_notes"] = None
                    d["service_note"] = None
                    d["location_lat"] = None
                    d["location_lng"] = None
    # Feb-2026 MP2 UI — enrich each job with the property label so
    # mobile schedule rows can render a chip without an N+1 fetch. The
    # property doc's address is also surfaced under ``property_address``
    # for the tech's Job Detail hero card. AE1 hygiene fix — both keys
    # are ALWAYS present (null when the job has no property_id) so
    # admin + tech responses share a consistent shape.
    for d in docs:
        d.setdefault("property_label", None)
        d.setdefault("property_address", None)
    # K58 · Feb-2026 — hoist ``pmap`` outside the try/except so the
    # coord resolver ladder below can consume it.  Empty dict when
    # the property batch is skipped (no jobs have ``property_id``) or
    # the fetch fails (see the except clause).
    pmap: dict = {}
    try:
        pids = list({d.get("property_id") for d in docs if d.get("property_id")})
        if pids:
            props = await db.properties.find(
                {"id": {"$in": pids}, "tenant_id": tenant["id"]},
                # K58 · Feb-2026 — pull property-level coord fields into
                # the batched projection so the resolver ladder below
                # can consult ``property.latitude/longitude`` (newer
                # geocoding write path) and ``property.lat/lng`` (older
                # flat shape) without an N+1 lookup.
                {"_id": 0, "id": 1, "label": 1, "address": 1,
                 "latitude": 1, "longitude": 1, "lat": 1, "lng": 1},
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
    # K58 · Feb-2026 — Schedule-map coord resolver ladder.
    #
    # Priority (highest wins — first hit stops the ladder):
    #   1. job.site_lat / job.site_lng          — set by services/google_maps/geocoding.py
    #   2. job.latitude / job.longitude         — set by newer geocoding write paths
    #   3. property.latitude / property.longitude  (or the flat lat/lng shape)
    #   4. customer.service_lat / .service_lng  — pre-K58 baseline (already
    #                                              seeded into location_lat/lng
    #                                              in the customer block above;
    #                                              this rung is a NO-OP here
    #                                              because a lower-priority
    #                                              source is only kept when a
    #                                              higher rung didn't fire).
    #
    # Both ``location_lat/lng`` (the historical key mobile + web filter
    # on) AND ``latitude/longitude`` (dual-key output for the mobile
    # shared-helper backfill — K58 Slice B) are stamped with the
    # resolved value.  ``None`` on both keys is preserved when no rung
    # yields coords.
    #
    # Customers do not see this block — the ``else:`` branch above is
    # skipped for role=customer and no coord fields are set.  This
    # ladder therefore only fires for admin / manager / technician.
    #
    # Phase P31 · Feb-2026 — Coord resolver ladder unified with
    # ``services.geo_resolver.resolve_job_coordinates`` for parity
    # with schedule.py + dispatch_board.py. The shared helper
    # handles two rungs (job → customer); jobs.py preserves an
    # extra ``property`` rung between them (its geocoded property
    # coords are a higher-signal fallback than the customer's
    # billing-address geocode).
    #
    # Priority (highest wins — first hit stops the ladder):
    #   1. job.site_lat/lng OR job.latitude/longitude OR job.lat/lng
    #      → shared helper, source="job"
    #   2. property.latitude/longitude (or the flat lat/lng shape)
    #      → inline, jobs.py-only rung, source="property"
    #   3. customer.service_lat/lng → shared helper via ``cmap``,
    #      source="customer"
    #   4. Nothing resolves → (None, None, None); pin dropped.
    #
    # ``coord_source`` is stamped from the resolver output; the FE
    # relies on the invariant ``coord_source is None ↔ location_lat
    # is None`` to know whether to render a pin.
    #
    # Customers do not see this block — the ``else:`` branch above is
    # skipped for role=customer and no coord fields are set. This
    # ladder therefore only fires for admin / manager / technician.
    if user.get("role") != "customer":
        # ``cmap`` was built upstream (line ~1128); it carries the
        # tenant-scoped ``service_lat``/``service_lng`` projection
        # the shared helper needs for the customer fallback.
        for d in docs:
            # Rungs 1-3 via shared helper (job's own coords only —
            # empty customer_lookup so the helper cannot fall to
            # the customer rung yet, since we need to try the
            # property rung between them).
            lat, lng, source = resolve_job_coordinates(d, {})
            # Rung 3 (jobs.py-specific) — property.latitude/longitude.
            # Only tried when the job's own rungs didn't win.
            if source is None:
                pid = d.get("property_id")
                p = pmap.get(pid) if pid else None
                if p:
                    p_lat = (
                        p.get("latitude")
                        if p.get("latitude") is not None
                        else p.get("lat")
                    )
                    p_lng = (
                        p.get("longitude")
                        if p.get("longitude") is not None
                        else p.get("lng")
                    )
                    if p_lat is not None and p_lng is not None:
                        try:
                            lat = float(p_lat)
                            lng = float(p_lng)
                            source = "property"
                        except (TypeError, ValueError):
                            # Malformed property coord — fall through
                            # to customer rung.
                            pass
            # Rung 4 via shared helper — customer.service_lat/lng.
            if source is None:
                lat, lng, source = resolve_job_coordinates(d, cmap)
            # Stamp resolved value under BOTH keys.  ``None`` is
            # preserved as ``None`` — no floats-of-null.  K58: dual-
            # key output for mobile shared-helper backfill.
            try:
                d["location_lat"] = float(lat) if lat is not None else None
                d["location_lng"] = float(lng) if lng is not None else None
            except (TypeError, ValueError):
                # Malformed coord data — treat as absent.
                d["location_lat"] = None
                d["location_lng"] = None
                source = None
            d["latitude"] = d["location_lat"]
            d["longitude"] = d["location_lng"]
            # Absent-coords case (both keys None) also nulls out the
            # source so a caller can rely on
            # ``coord_source is None`` ↔ ``lat is None``.
            d["coord_source"] = (
                source if d["location_lat"] is not None else None
            )
    # Feb-2026 · Schedule notes surface — cap the free-text ``notes``
    # column at 500 chars on the wire and expose ``notes_truncated``
    # so the schedule card can render a 2-line clamp + expand hint
    # without a HEAD roundtrip. Non-strings + empty values are left
    # untouched; ``notes_truncated`` only appears when ``notes`` is a
    # non-empty string, matching the "empty → hide the row" contract
    # the web + mobile schedules enforce.
    _NOTES_CAP = 500
    for d in docs:
        n = d.get("notes")
        if isinstance(n, str) and n:
            if len(n) > _NOTES_CAP:
                d["notes"] = n[:_NOTES_CAP]
                d["notes_truncated"] = True
            else:
                d["notes_truncated"] = False
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
    # Feb-2026 · Slim-photos ship — the list endpoint historically
    # returned every job's full ``photos`` array (base64 blobs +
    # per-photo metadata). On tenants with ~200 rows × ~10 photos
    # each, that inflated the wire payload to 3–4 MB and started
    # timing out mobile clients on the post-close-job list refresh
    # (see ``/app/memory/DIAG_P0_MOBILE_CLOSE_JOB_SILENT.md``).
    #
    # Default shape now drops ``photos`` and emits:
    #   * ``photo_count`` — ``len(photos)`` (0 when absent).
    #   * ``photo_ids``  — list of stable ``id`` strings so the UI
    #                       can lazy-load individual photos via the
    #                       existing per-photo GET.
    #
    # ``GET /api/jobs/{id}`` (single-job detail) is intentionally
    # NOT touched — full ``photos`` still ship there.
    #
    # Opt-in escape hatch: ``?include_photos=true`` restores the
    # pre-slim payload for callers that haven't migrated yet.
    #
    # Feb-2026 batch-verify follow-up — the ``include_photos=true``
    # variant is a strict SUPERSET of the slim shape:
    #   * ``photo_count`` and ``photo_ids`` are ALWAYS emitted (never
    #     ``None``) so consumers can rely on their presence
    #     regardless of the projection flag.
    #   * Legacy rows where the underlying Mongo doc has no ``photos``
    #     field at all (e.g. ``demo-stale-*`` seed jobs) are
    #     normalized to ``photos: []`` so the response shape is
    #     uniform across every row.
    #
    # Feb-2026 follow-up (customer-detail slim ship) — the row-level
    # loop was extracted into ``services.jobs_slim_photos`` so the
    # embedded-jobs list on ``GET /customers/{cid}`` can reuse the
    # same shape without duplicating the loop.
    #
    # Task L+P · Feb-2026 — batched SR photo-id pre-fetch.  Runs
    # BEFORE ``slim_photos_on_rows`` so a single ``$in`` query
    # widens ``photo_ids[]`` / ``photo_thumb_urls[]`` to include
    # service_reports.photos ids for every row on the page.  See
    # ``services/jobs_slim_photos.py::enrich_docs_with_sr_photo_ids``.
    from services.jobs_slim_photos import (
        slim_photos_on_rows, enrich_docs_with_sr_photo_ids,
    )
    await enrich_docs_with_sr_photo_ids(db, docs, tenant["id"])
    slim_photos_on_rows(docs, include_photos=bool(include_photos))
    # Phase P2 · Feb-2026 — read-path safety net.  Coerce any legacy
    # dict-address rows to strings BEFORE ship so the schedule /
    # jobs list never lands a dict on the client.  See
    # ``_coerce_job_address_for_read`` above.
    _warned: set = set()
    for _d in docs:
        _coerce_job_address_for_read(_d, tenant["id"], _warned)
    # CREW-SCHEDULE-FANOUT · Feb-2026 — tag ``_crew_role`` per row
    # for tech callers so the client renders "Crew lead" (direct) vs
    # "Crew member" (via crew) badges without re-querying the crews
    # roster.  Overlay wins per the ticket's Q6 dedupe gate: if the
    # tech is BOTH on ``JOB_TECH_FIELDS`` and in the crew, the job
    # tags as ``direct``.  Non-tech callers get ``_crew_role=None``
    # so the FE suppresses the badge.
    _list_role = (user.get("role") or "").lower()
    if _list_role == "technician":
        from services.tech_id_resolver import JOB_TECH_FIELDS as _JTF
        _list_tech_ids = {
            _v for _v in (user.get("technician_id"), user.get("id")) if _v
        }
        for _d in docs:
            if any(_d.get(_f) in _list_tech_ids for _f in _JTF):
                _d["_crew_role"] = "direct"
            elif _d.get("crew_id"):
                _d["_crew_role"] = "member"
            else:
                _d["_crew_role"] = None
    return docs


@router.post("/jobs")
async def create_job(body: JobIn,
                     background_tasks: BackgroundTasks,
                     user: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    doc = body.dict()
    # Feb 2026 · Work-class validation. Normalizes case-insensitively
    # and rejects unknown values with HTTP 400 (see
    # ``services/work_class.py`` for the invariant).
    try:
        from services.work_class import normalize_work_class
        doc["work_class"] = normalize_work_class(doc.get("work_class"))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    customer = await db.customers.find_one(
        {"id": body.customer_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not customer:
        raise HTTPException(400, "Customer not found")
    doc["customer_name"] = customer["name"]
    # Phase P1 · Feb-2026 — ``jobs.address`` MUST be a plain string.
    # ``JobIn.address`` is ``Optional[str]``, so Pydantic v2 already
    # rejects dict / list inputs with a 422 before we reach here.
    # This defense-in-depth block coerces the customer-fallback +
    # empties any accidental non-string that survived (belt +
    # suspenders — a subclass of BaseModel with ``model_config``
    # extra="allow" could otherwise land a raw dict).
    inbound_addr = doc.get("address")
    if inbound_addr is None or not isinstance(inbound_addr, str):
        doc["address"] = ""
    if not doc.get("address"):
        cust_addr = customer.get("address", "")
        doc["address"] = cust_addr if isinstance(cust_addr, str) else ""
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
    # Phase P1 · Feb-2026 — if a property_id is on the doc (either
    # user-supplied or auto-assigned), validate ownership + re-
    # snapshot its address as a STRING so the schedule read path
    # never sees a dict on ``jobs.address``.
    if doc.get("property_id"):
        prop = await _resolve_property_for_job(
            tenant["id"], body.customer_id, doc["property_id"],
        )
        formatted = _stringify_property_address(prop)
        if formatted:
            doc["address"] = formatted
        # Snapshot coords with the same "only overwrite when non-
        # empty" contract the update path uses (line 1768-71).
        site_lat = prop.get("site_lat")
        if site_lat is None:
            site_lat = prop.get("latitude")
        if site_lat is None:
            site_lat = prop.get("lat")
        site_lng = prop.get("site_lng")
        if site_lng is None:
            site_lng = prop.get("longitude")
        if site_lng is None:
            site_lng = prop.get("lng")
        if site_lat is not None:
            doc["site_lat"] = site_lat
        if site_lng is not None:
            doc["site_lng"] = site_lng
    # Feb-2026 · P0 hotfix — tech-assignment write-side denorm.
    # Historic behaviour did a single ``db.technicians`` lookup and
    # stamped ``technician_name = None`` when the id was a synth-from-
    # users shape (every real team member added via the roster UI has
    # this shape). The shared helper uses the 4-rung cascade so both
    # real-tech-doc and synth-from-users ids resolve. See
    # ``services/tech_assignment.py`` for the full rationale.
    if body.technician_id:
        from services.tech_assignment import resolve_tech_write_denorms
        denorms = await resolve_tech_write_denorms(
            db, tenant["id"], body.technician_id,
        )
        doc["technician_avatar"] = denorms["avatar"]
        doc["technician_name"] = denorms["name"]
    else:
        doc["technician_name"] = None
    # Feb-2026 · Crew Phase A · create-path crew overlay. Validate in
    # the same tenant and denormalize name/color so schedule cards
    # render without a per-job crew fetch (mirrors the ``update_job``
    # crew handling). ``technician_id`` stays as-is — the crew is an
    # OVERLAY, never a replacement.
    if doc.get("crew_id"):
        crew = await db.crews.find_one(
            {"id": doc["crew_id"], "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "name": 1, "color": 1},
        )
        if not crew:
            raise HTTPException(
                400, "crew_id does not resolve to a crew in this tenant",
            )
        doc["crew_name"] = crew.get("name")
        doc["crew_color"] = crew.get("color")
    doc.update({"id": new_id(), "tenant_id": tenant["id"], "photos": [], "created_at": now_iso()})
    try:
        await db.jobs.insert_one(doc)
    except DuplicateKeyError:
        # Feb-2026 · Task B · graceful DuplicateKeyError → 409.
        # The partial-unique index on ``(recurring_template_id,
        # scheduled_date)`` is the only source of E11000 here (non-
        # recurring jobs are unconstrained). If a recurring-series
        # occurrence for this date already exists, surface it as a
        # 409 conflict instead of letting Motor's raw exception
        # bubble up as an ASGI 500.
        raise HTTPException(
            status_code=409,
            detail="A job for this recurring template already exists on this date.",
        )
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
    # Feb 2026 · Phase 1 Custom Trigger Builder — emit ``job_scheduled``
    # into schema-v2 sequences. Only fires when the job already has a
    # scheduled_date on create. Correlation key = job id.
    try:
        if doc.get("scheduled_date"):
            from services.marketing.event_dispatcher import emit_event
            await emit_event(
                event="job_scheduled",
                tenant_id=tenant["id"],
                entity_id=doc.get("id"),
                customer_id=doc.get("customer_id"),
                scheduled_at=(str(doc.get("scheduled_date"))
                                + "T09:00:00+00:00"),
                payload_extras={"job": doc,
                                  "correlation_id":
                                    f"{doc.get('id')}:scheduled:{doc.get('scheduled_date')}"},
            )
            # Repair jobs also fire ``repair_flagged`` on create.
            if str(doc.get("work_class") or "").lower() == "repair":
                await emit_event(
                    event="repair_flagged",
                    tenant_id=tenant["id"],
                    entity_id=doc.get("id"),
                    customer_id=doc.get("customer_id"),
                    payload_extras={"job": doc,
                                      "correlation_id":
                                        f"{doc.get('id')}:repair_flagged"},
                )
    except Exception:
        pass
    # Feb-2026 · P42 — "converted" threshold stamp. Safe no-op when
    # the customer doesn't (yet) meet both conditions.
    try:
        from services.customer_lifecycle import stamp_customer_since
        background_tasks.add_task(
            stamp_customer_since, body.customer_id, tenant["id"])
    except Exception:
        pass
    # Feb 2026 · Auto-learn Job Title catalog — every create with a
    # non-empty title bumps ``db.job_titles`` for the calling
    # tenant so the next tech typing the same prefix in the New
    # Job modal sees the completion. Safe no-op on empty titles.
    try:
        if doc.get("title"):
            from routers.job_titles import record_title_usage
            background_tasks.add_task(
                record_title_usage, tenant["id"], doc["title"])
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
    from services.recurrence_math import advance_months, MONTH_STEP
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
    for i in range(max(1, min(24, count))):
        dates.append(cur.isoformat())
        if step:
            cur = cur + timedelta(days=step)
        elif cadence in MONTH_STEP:
            # Feb-2026 · P47 — monthly / quarterly / semi_annual all
            # step by whole months. Anchor to ``start`` so the "Nth
            # of the month" survives month-length clamping (Jan 31
            # + quarterly → Apr 30, next → Jul 31, not Jul 30).
            cur = advance_months(start, MONTH_STEP[cadence] * (i + 1),
                                        start.day)
        else:
            raise HTTPException(400, f"Unknown cadence: {cadence}")
    return {"cadence": cadence, "count": len(dates), "dates": dates}


@router.post("/jobs/{jid}/reopen")
async def reopen_job(jid: str,
                     request: Request,
                     user: dict = Depends(get_current_user),
                     tenant: dict = Depends(get_current_tenant)):
    """Flip a completed (or, for admins, cancelled) job back to
    ``active`` and clear the service-report ``submitted_at``
    lock so downstream edits accept new writes.

    Task M+P · Feb-2026 — Access model.
      * ``admin`` / ``super_admin`` → allowed on ``completed`` OR
        ``cancelled`` jobs. Clears ``submitted_at`` on **every**
        service_reports doc for the job.
      * ``technician`` → allowed on ``completed`` jobs ONLY (per
        Task M+P decision E2 — cancelled remains admin-only).
        Must be authorised via the F1 crew-aware gate
        (``services.authz.is_tech_authorized_on_job``); non-
        assigned techs → 403.  Clears ``submitted_at`` on ONLY
        the caller's own SR (``tech_id`` derived via
        ``user.technician_id or user.id`` — matches the pattern
        used by every other tech-scoped SR endpoint).
      * ``customer`` / other roles → 403.

    Cross-collection write on ``service_reports`` is tenant-
    scoped at every rung and matches the P44 multi-SR shape
    (one SR per tech, keyed ``(tenant_id, job_id, tech_id)``).

    Idempotency envelope preserved (``replay_or_reserve`` via
    ``X-Idempotency-Key``) so an offline retry replays the same
    response.
    """
    # Phase O4 · Feb-2026 — Idempotency wiring.
    from utils_idempotency import replay_or_reserve, store_response
    idem_body: Dict[str, Any] = {}  # endpoint takes no body
    idem_key, cached = await replay_or_reserve(
        request, tenant["id"], "POST /jobs/{jid}/reopen", idem_body,
    )
    if cached is not None:
        return cached

    job = await db.jobs.find_one(
        {"id": jid, "tenant_id": tenant["id"]},
        {"_id": 0, "photos.data": 0},
    )
    if not job:
        raise HTTPException(404, "Job not found")

    # ── Role gate — Task M+P widening ────────────────────────
    role = (user.get("role") or "").lower()
    is_admin = role in ("admin", "super_admin")
    is_tech = role in ("technician", "tech")

    if not (is_admin or is_tech):
        # Customers + every other non-staff role — locked out.
        raise HTTPException(
            403,
            {"code": "reopen_forbidden", "detail": "Role not permitted"},
        )

    if is_tech:
        # F1 crew-aware gate — direct assignment OR crew
        # membership.  Non-authorised techs get the same 403
        # shape used by every tech-scoped SR endpoint.
        authorised = await is_tech_authorized_on_job(
            user, job, db, tenant_id=tenant["id"],
        )
        if not authorised:
            raise HTTPException(
                403,
                {"code": "reopen_forbidden",
                 "detail": "Not your job"},
            )

    # ── Status precondition ──────────────────────────────────
    # Task M+P E2 — techs may reopen only ``completed`` jobs;
    # ``cancelled`` remains admin-only.
    status = job.get("status")
    allowed_statuses = (
        ("completed", "cancelled") if is_admin else ("completed",)
    )
    if status not in allowed_statuses:
        # Preserve the pre-Task-M+P 400 contract (Task M+P C1).
        # Techs on a ``cancelled`` job also land here → 400 with
        # a status message that names the allowed set, so the
        # UI can surface a clear error without needing role
        # awareness.
        allowed_list = " or ".join(allowed_statuses)
        raise HTTPException(
            400,
            f"Only {allowed_list} jobs can be reopened",
        )

    # ── Cross-collection: clear service_reports.submitted_at ──
    # A2 — role-aware scope:
    #   * admin → all SRs on the job (full reopen).
    #   * tech  → only the caller's own SR (fix your own report).
    sr_filter: Dict[str, Any] = {
        "tenant_id": tenant["id"],
        "job_id": jid,
    }
    cleared_scope: str
    if is_admin:
        cleared_scope = "all"
    else:
        # Same tech id derivation pattern as
        # ``routers/service_reports.py`` (grep evidence:
        # L340 / L1707 / L2836).
        tech_id = user.get("technician_id") or user.get("id")
        sr_filter["tech_id"] = tech_id
        cleared_scope = "own"

    sr_result = await db.service_reports.update_many(
        sr_filter,
        {
            "$set": {"submitted_at": None},
            "$unset": {"submitted_by": ""},
        },
    )
    cleared_sr_count = int(getattr(sr_result, "modified_count", 0) or 0)

    # ── Job status flip ──────────────────────────────────────
    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"]},
        {"$set": {"status": "active", "reopened_at": now_iso()},
         "$unset": {"completed_at": ""}},
    )

    # ── Audit trail — Task M+P adds cleared-scope metadata ──
    try:
        actor_role_label = "admin" if is_admin else "tech"
        await db.activity_logs.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "job_id": jid,
            "type": "reopen",
            "actor_id": user.get("id"),
            "actor_name": user.get("name", ""),
            "actor_role": actor_role_label,
            "at": now_iso(),
            "note": f"Job reopened by {actor_role_label}",
            "metadata": {
                "cleared_sr_scope": cleared_scope,
                "cleared_sr_count": cleared_sr_count,
            },
        })
    except Exception:
        pass

    updated = await db.jobs.find_one(
        {"id": jid, "tenant_id": tenant["id"]},
        {"_id": 0, "photos.data": 0},
    )
    if idem_key:
        await store_response(idem_key, "POST /jobs/{jid}/reopen",
                              tenant["id"], updated, idem_body)
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
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0, "photos.data": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    # role scoping — F1 · crew-aware tech gate (was
    # ``technician_id != user.technician_id``, which dropped crew-only jobs).
    if user.get("role") == "technician" and not await is_tech_authorized_on_job(
        user, job, db, tenant["id"],
    ):
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
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0, "photos.data": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    to = (body.get("to") or "").strip().lower()
    customer = None
    if not to:
        customer = await db.customers.find_one(
            {"id": job["customer_id"], "tenant_id": tenant["id"]}, {"_id": 0}
        ) or {}
        # Feb-2026 · Multi-Contact Phase 2 · fan-out (manual).
        # Admin-triggered work-order email — bypasses the customer
        # mute (admin action). Reuse the first enabled recipient as
        # the primary target; extras fan out in the loop below.
        from services.customer_multi_contact import active_email_recipients
        _recips = active_email_recipients(customer, context="manual")
        to = (_recips[0] if _recips else "").strip().lower()
    if not to:
        raise HTTPException(400, "No recipient email available")
    if not RESEND_API_KEY:
        return {"sent": False, "reason": "resend-not-configured", "to": to}
    pdf_bytes = await _build_work_order_pdf(job, tenant)
    # If we resolved via the multi-contact helper, fan out to every
    # enabled address; otherwise fall back to the single ``to`` value
    # provided by the caller.
    _targets = [to]
    if customer is not None:
        from services.customer_multi_contact import active_email_recipients
        _extra = [a for a in active_email_recipients(customer, context="manual") if a != to]
        _targets = [to] + _extra
    sent_any = False
    _last_err: str | None = None
    _fanout_count = len(_targets)
    for _addr in _targets:
        _provider_status: str = "pending"
        _provider_error: str | None = None
        try:
            import resend
            from config import EMAIL_FROM
            resend.api_key = RESEND_API_KEY
            # safe-send: allowlist because legacy direct SDK call is gated by sdk_intercept.install_resend_gate() at the Resend SDK boundary; SAFE-SEND-D full migration pending
            resend.Emails.send({
                "from": EMAIL_FROM or "onboarding@resend.dev",
                "to": [_addr],
                "subject": body.get("subject") or f"Work Order · {job.get('title', 'Service')}",
                "html": body.get("message") or f"<p>Attached is the work order for <strong>{job.get('title', '')}</strong>.</p>",
                "attachments": [{
                    "filename": f"work-order-{jid[:8]}.pdf",
                    "content": base64.b64encode(pdf_bytes).decode("ascii"),
                }],
            })
            sent_any = True
            _provider_status = "sent"
        except Exception as e:
            logger.warning(f"Work-order email failed for {_addr}: {e}")
            _last_err = str(e)
            _provider_status = "failed"
            _provider_error = str(e)[:400]
        # Feb-2026 · Multi-Contact Phase 2 (Fix 1) — per-recipient
        # ledger row for admin work-order sends. Mirrors the shape
        # written by cluster 11 (``services/auto_visit_email.py``)
        # so ops can `db.outbound_emails.find({kind:"work_order_email"})`
        # for the audit trail. Written for BOTH success and failure
        # attempts so the observability contract is truthful.
        try:
            await db.outbound_emails.insert_one({
                "id": new_id(),
                "kind": "work_order_email",
                "tenant_id": tenant["id"],
                "customer_id": job.get("customer_id"),
                "job_id": jid,
                "recipient_email": _addr,
                "cluster": "work_order_email",
                "context": "manual",
                "attempted_at": now_iso(),
                "provider_status": _provider_status,
                "provider_error": _provider_error,
                "fanned_out": True,
                "fanout_recipient_count": _fanout_count,
                "created_at": now_iso(),
            })
        except Exception as _led_exc:
            # Ledger writes are fire-and-forget — never block the
            # send loop on an audit trouble.
            logger.warning(
                "[jobs] work-order ledger write failed cid=%s job=%s addr=%s err=%s",
                job.get("customer_id"), jid, _addr, _led_exc,
            )
    if sent_any:
        return {"sent": True, "to": to, "fanned_out": True,
                "fanout_recipient_count": _fanout_count}
    return {"sent": False, "reason": _last_err or "send-failed", "to": to}


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
    # Feb-2026 · PERF-MONGO-PROJECT-EXCLUDE-PHOTOS ship exception —
    # this is the single-job DETAIL handler; wire contract requires
    # full ``photos`` including base64 ``data``. Explicitly OPT OUT
    # of the ``{"photos.data": 0}`` projection applied everywhere
    # else. See ``services/jobs_slim_photos.py`` module comment.
    doc = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
    # Feb-2026 · Photos-in-S3 Phase 1 — strip ``photos[].s3_key`` +
    # ``photos[].s3_mime`` so the storage backend implementation
    # detail never ships over the wire.
    try:
        from services.jobs_slim_photos import strip_s3_metadata_from_photos
        strip_s3_metadata_from_photos(doc)
    except Exception:
        pass
    # JOB-PHOTOS-FIX · Feb-2026 — resolve every ``photos[].url`` so
    # the FE grid in ``JobDetail.jsx`` can render ``<img src={p.url}>``
    # instead of coercing the raw dict to ``[object Object]``.  The
    # streaming route behind the URL owns the S3/base64 cascade.
    try:
        from services.jobs_slim_photos import inject_photo_url_on_doc
        inject_photo_url_on_doc(doc, jid)
    except Exception:
        pass
    if not doc:
        raise HTTPException(404, "Job not found")
    # Feb-2026 · P4.5 — mirror the soft-delete two-branch check that the
    # PATCH edit handler uses at lines ~1286-1297.  Super_admin gets a
    # 409 so restore tooling knows the row still exists; every other
    # role gets a stock 404 so the mere existence of a soft-deleted
    # job doesn't leak.
    if doc.get("deleted_at"):
        role = (user.get("role") or "").lower()
        if role == "super_admin":
            raise HTTPException(
                status_code=409,
                detail={"detail": "job_soft_deleted",
                        "message": "Job is soft-deleted; restore first."},
            )
        raise HTTPException(404, "Job not found")
    # F1 · crew-aware tech gate — see services/authz.py.
    # Phase P9-A · Feb-2026 — leak-avoidance: return 404 (not 403) so
    # the mere existence of a foreign-tech job is not revealed to a
    # technician caller. Matches the ``list_jobs`` silent-empty
    # posture: never confirm whether the ID exists at all.
    if user.get("role") == "technician" and not await is_tech_authorized_on_job(
        user, doc, db, tenant["id"],
    ):
        raise HTTPException(404, "Job not found")
    if user.get("role") == "customer" and doc.get("customer_id") != user.get("customer_id"):
        raise HTTPException(403, "Not your job")
    doc = with_field_report(doc)
    # Phase 57.d · read-time enrichment — tech department + derived
    # checklist_kind. Never mutates the stored job doc.
    await _enrich_job_dept_and_kind(doc, tenant["id"])
    # Feb-2026 · P0 hotfix — historical jobs stamped with
    # ``technician_name = null`` (write path missed the synth-from-
    # users cascade before the ``resolve_tech_write_denorms``
    # helper landed) render "Unassigned" in the JobDetail UI even
    # though ``technician_id`` is correctly set. Enrich on read so
    # those rows recover without a backfill migration. Response-
    # only mutation — the stored doc is unchanged.
    if not doc.get("technician_name"):
        from services.job_assignee import effective_tid
        from services.service_report_view import resolve_technician_names
        _tid = effective_tid(doc)
        if _tid:
            _names = await resolve_technician_names(db, tenant["id"], [_tid])
            if _names.get(_tid):
                doc["technician_name"] = _names[_tid]
    if user.get("role") == "customer":
        doc.pop("internal_notes", None)
    # Phase 16C add-on: strip revenue/pricing fields from technician responses.
    if user.get("role") == "technician":
        for k in ("price", "cost", "total", "subtotal", "tax_amount",
                  "revenue", "invoice_total", "quote_total", "margin",
                  "labor_cost", "materials_cost", "gross_margin"):
            doc.pop(k, None)
    # Phase P2 · Feb-2026 — read-path safety net for legacy dict
    # ``jobs.address`` on the single-job DETAIL handler.  Same
    # invariant as ``list_jobs`` above; coerces on the way out so
    # the client never has to defensively type-check ``address``.
    _warned_single: set = set()
    _coerce_job_address_for_read(doc, tenant["id"], _warned_single)
    return doc


@router.put("/jobs/{jid}/field-report")
async def update_field_report(jid: str, body: FieldReportUpdate,
                              user: dict = Depends(get_current_user),
                              tenant: dict = Depends(get_current_tenant)):
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"photos.data": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    if user.get("role") == "technician" and not await is_tech_authorized_on_job(
        user, job, db, tenant["id"],
    ):
        raise HTTPException(403, "Not your job")
    update = {k: v for k, v in body.dict().items() if v is not None}
    if update:
        await db.jobs.update_one({"id": jid, "tenant_id": tenant["id"]}, {"$set": update})
    # Auto-bill: when chemicals are logged, accrue them onto the customer's monthly invoice.
    if "chemicals_added" in update:
        from routers.finances import accrue_chem_invoice
        job_fresh = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0, "photos.data": 0})
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
        await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0, "photos.data": 0})
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
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"photos.data": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    # Feb-2026 · Schedule-screen inline edit — the Edit affordance
    # on the Schedule cards uses this endpoint. Prior version only
    # gated technicians (own-job check); customer / any-other role
    # sessions could freely PATCH any job. Tighten to
    # admin-equivalent (admin / super_admin / owner / manager) OR
    # technicians restricted to their own assignments.
    role = (user.get("role") or "").lower()
    ADMIN_ROLES = {"admin", "super_admin", "owner", "manager"}
    if role in ADMIN_ROLES:
        pass  # full write access
    elif role == "technician":
        # F1 · crew-aware tech gate — see services/authz.py.
        if not await is_tech_authorized_on_job(user, job, db, tenant["id"]):
            raise HTTPException(403, "Not your job")
    else:
        raise HTTPException(403, "Not permitted to edit jobs")
    # Phase C1 hotfix · Feb-2026 — Pydantic V2 uses ``model_dump``;
    # the legacy ``.dict()`` shim still works but emits a deprecation
    # warning. Preserve the ``exclude_none``-style filter so the
    # downstream stamper + immutable-field guards see the same shape.
    update = {k: v for k, v in body.model_dump().items() if v is not None}
    # Phase C1 · Feb-2026 — follow-up controls are admin-only.
    # ``follow_up_at`` / ``needs_follow_up`` are surfaced on the
    # jobs update model so the JobDetail admin panel can PATCH
    # them, but technicians must never write them (they still
    # PATCH status/notes/etc. on their own jobs). Silent-strip
    # from the update dict would leave the caller confused, so
    # raise a 403 with a specific detail instead.
    if ("follow_up_at" in update or "needs_follow_up" in update) \
            and role not in ADMIN_ROLES:
        raise HTTPException(
            403,
            "Only admin-equivalent roles can set follow-up fields",
        )
    # Feb-2026 · Jobs Overhaul Phase 3b — ``costing_overrides``
    # admin-equivalent role gate + shape validation. The field is
    # ``$set``-written atomically (handler does not merge partials
    # — see ``models.py::JobUpdate.costing_overrides`` for the
    # locked FE/BE write contract). Non-admin callers trying to
    # set this field get a scoped 403; techs still PUT other
    # fields on their own jobs freely. Shape invariants:
    #   * top-level keys ⊆ {"labor","materials","equipment"}
    #   * inner keys ⊆ {"budgeted_cents","actual_cents"}
    #   * values are non-negative ints (``bool`` rejected since
    #     ``isinstance(True, int) is True`` in Python — we don't
    #     want ``{"budgeted_cents": True}`` sneaking through as 1).
    if "costing_overrides" in update:
        if role not in ADMIN_ROLES:
            raise HTTPException(
                403,
                "costing_overrides may only be set by admin-equivalent roles",
            )
        _co = update["costing_overrides"]
        if not isinstance(_co, dict):
            raise HTTPException(400, "costing_overrides must be an object")
        _CO_BUCKETS = {"labor", "materials", "equipment"}
        _CO_INNER = {"budgeted_cents", "actual_cents"}
        for _k, _v in _co.items():
            if _k not in _CO_BUCKETS:
                raise HTTPException(
                    400,
                    f"costing_overrides: unknown bucket {_k!r} — expected one of {sorted(_CO_BUCKETS)}",
                )
            if not isinstance(_v, dict):
                raise HTTPException(
                    400,
                    f"costing_overrides.{_k} must be an object",
                )
            for _ik, _iv in _v.items():
                if _ik not in _CO_INNER:
                    raise HTTPException(
                        400,
                        f"costing_overrides.{_k}: unknown field {_ik!r} — expected one of {sorted(_CO_INNER)}",
                    )
                if isinstance(_iv, bool) or not isinstance(_iv, int) or _iv < 0:
                    raise HTTPException(
                        400,
                        f"costing_overrides.{_k}.{_ik} must be a non-negative integer",
                    )
    # Mobile Phase 2 · Feb-2026 — tech-wins conflict audit. The
    # ``client_updated_at`` marker (if present) is stripped from
    # the persisted payload and used only to decide whether the
    # tech's write is overwriting a newer server state — an
    # ``mobile_write_conflicts`` row is written for audit but the
    # tech's write is ALWAYS accepted (per user directive).
    _client_updated_at = update.pop("client_updated_at", None)
    if _client_updated_at:
        from services.mobile_offline_sync import (
            log_write_conflict, should_log_conflict,
        )
        _srv_upd = job.get("updated_at")
        if should_log_conflict(_srv_upd, _client_updated_at):
            await log_write_conflict(
                tenant_id=tenant["id"],
                entity_type="job",
                entity_id=jid,
                tech_user_id=user.get("id"),
                fields_overwritten=list(update.keys()),
                client_updated_at_iso=_client_updated_at,
                server_updated_at_iso=_srv_upd,
            )
    # Feb 2026 · Work-class retag validation. When present, must be
    # ``"service"`` or ``"repair"`` (case-insensitive). Everything
    # else → 400.
    if "work_class" in update:
        try:
            from services.work_class import normalize_work_class
            update["work_class"] = normalize_work_class(update["work_class"])
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    # Feb 2026 · Property retag — Address picker on Job Edit. When the
    # caller sends a ``property_id`` that differs from the job's
    # current one, we (1) verify the property exists in the SAME
    # tenant AND belongs to the SAME customer as the job (cross-
    # customer references → 422), and (2) snapshot the property's
    # ``address`` + ``site_lat`` / ``site_lng`` onto the job so
    # historical accuracy is preserved even if the property record
    # is later edited or deleted.
    #
    # Phase P1 · Feb-2026 — the address snapshot now runs through
    # ``_stringify_property_address`` so a dict-shaped ``address``
    # on the property doc NEVER lands on the job.  Prior ship
    # copied ``prop["address"]`` verbatim (a dict) which crashed
    # the schedule read path on ``.split()`` downstream.  422
    # error codes replace the plain-string 400s so the frontend
    # can machine-parse the failure reason.
    if "property_id" in update and update["property_id"] != job.get("property_id"):
        new_pid = update["property_id"]
        if new_pid:
            prop = await _resolve_property_for_job(
                tenant["id"], job.get("customer_id"), new_pid,
            )
            # Re-snapshot address as a STRING only.  Empty string
            # from the formatter means the prop has no addressable
            # fields — leave the job's existing address alone.
            formatted = _stringify_property_address(prop)
            if formatted:
                update["address"] = formatted
            site_lat = prop.get("site_lat")
            if site_lat is None:
                site_lat = prop.get("latitude")
            site_lng = prop.get("site_lng")
            if site_lng is None:
                site_lng = prop.get("longitude")
            if site_lat is not None:
                update["site_lat"] = site_lat
            if site_lng is not None:
                update["site_lng"] = site_lng
    if "technician_id" in update:
        # Feb-2026 · P0 hotfix — same shared write-side cascade as
        # ``create_job``. See ``services/tech_assignment.py``.
        from services.tech_assignment import resolve_tech_write_denorms
        denorms = await resolve_tech_write_denorms(
            db, tenant["id"], update["technician_id"],
        )
        update["technician_name"] = denorms["name"]
        update["technician_avatar"] = denorms["avatar"]
    # 2026-10-02 · Jobs Overhaul Phase 3a — Customer reassignment.
    # When the inline Customer tile fires an ``onChange`` with a
    # different ``customer_id``, we must mirror the POST /jobs:1535-
    # 1540 shape so the denorm ``customer_name`` stays coherent and
    # the stale ``property_id`` + ``address`` snapshot (which both
    # belong to the OLD customer) don't follow the job onto its new
    # owner.  ``property_id`` + ``address`` are explicitly $unset on
    # the SAME ``update_one`` further below (see ``_unset_on_change``).
    _unset_on_change: dict = {}
    if ("customer_id" in update
            and update["customer_id"] != job.get("customer_id")):
        new_cid = update["customer_id"]
        new_customer = await db.customers.find_one(
            {"id": new_cid, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "name": 1},
        )
        if not new_customer:
            raise HTTPException(400, "customer_id does not resolve to a customer in this tenant")
        update["customer_name"] = new_customer.get("name", "")
        # TODO(ux): consider validating current property_id against
        # the new customer and keeping it if it still belongs — for
        # Phase 3a we unconditionally clear both so the next edit
        # explicitly re-picks the property on the new customer.
        _unset_on_change["property_id"] = ""
        _unset_on_change["address"] = ""
        # Guard against someone also PATCHing a stale property_id on
        # the SAME request — the unset below would race the $set.
        update.pop("property_id", None)
        update.pop("address", None)
    # Feb-2026 · Crew Phase A · crew assignment enrichment + RBAC gate.
    # Only admin-equivalent roles may CHANGE a crew — a technician can
    # still update their own job's status / notes / etc., but not the
    # crew binding. Cross-tenant crew ids are rejected 400 (same-tenant
    # gate mirrors the ``bulk-reassign`` path).
    if "crew_id" in update:
        if role not in ADMIN_ROLES:
            raise HTTPException(
                403, "Only admin-equivalent roles can assign crews",
            )
        crew = await db.crews.find_one(
            {"id": update["crew_id"], "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "name": 1, "color": 1},
        )
        if not crew:
            raise HTTPException(
                400,
                "crew_id does not resolve to a crew in this tenant",
            )
        # Stamp denormalized name + color so schedule cards render
        # without a per-job crew fetch (mirrors the ``technician_name``
        # / ``technician_avatar`` pattern above). ``technician_id``
        # is NOT cleared — locked product decision (overlay).
        update["crew_name"] = crew.get("name")
        update["crew_color"] = crew.get("color")
    # Feb-2026 · Chemistry required-readings gate.  Applied ONLY on
    # the ``→ completed`` transition — Could-Not-Service and other
    # status changes are NOT gated.  Landscape jobs skip the gate.
    # Feb-2026 · Repair-mode addition — repair jobs (``work_class ==
    # "repair"``) also skip: repair visits document evidence via
    # photos + videos + notes only, chemistry not required.
    if (update.get("status") == "completed"
            and job.get("status") != "completed"):
        from services.chemistry_gate import (
            assert_core_readings_present, gather_readings_for_job, is_pool_job,
        )
        _effective_wc = (update.get("work_class")
                          or job.get("work_class") or "").lower()
        if is_pool_job(job) and _effective_wc != "repair":
            rep = await db.service_reports.find_one(
                {"tenant_id": tenant["id"], "job_id": jid}, {"_id": 0},
            )
            assert_core_readings_present(
                gather_readings_for_job(job, rep),
            )
    # Phase C1 · Feb-2026 — stamp ``completed_at`` + ``follow_up_at``
    # on the ``→ completed`` transition (idempotent; respects
    # admin-supplied overrides in either field). Runs BEFORE the
    # DB write so both new fields land in the same $set. Details:
    # :mod:`services.job_completion`.
    from services.job_completion import stamp_completion_fields
    await stamp_completion_fields(
        db, tenant_id=tenant["id"], job=job, update=update,
    )
    if update:
        _write_op: dict = {"$set": update}
        if _unset_on_change:
            _write_op["$unset"] = _unset_on_change
        await db.jobs.update_one(
            {"id": jid, "tenant_id": tenant["id"]}, _write_op,
        )

    # Feb-2026 · Service Notifications Pipeline — reschedule event.
    # Fires customer-facing dual-channel notification when the
    # ``scheduled_date`` actually changed. Runs as a background
    # task so the PATCH request doesn't wait on Resend's network
    # round-trip (measured ~0.3s per send). Any failure inside the
    # helper is logged but NEVER breaks the PATCH request.
    try:
        old_sd = job.get("scheduled_date")
        new_sd = update.get("scheduled_date")
        if new_sd and str(new_sd).strip() and str(new_sd).strip() != str(old_sd or "").strip():
            import asyncio as _resched_asyncio
            from services.notifications_pipeline.service_notifications import (
                fire_reschedule_notification,
            )
            # Re-read the job so ``fire_reschedule_notification``
            # sees the POST-update state (relevant for the
            # short-window reminder-dedup branch, which reads
            # ``service_reminder_sent_at``).
            fresh = await db.jobs.find_one(
                {"id": jid, "tenant_id": tenant["id"]}, {"_id": 0},
            )
            _resched_job = fresh or {**job, **update}
            _resched_actor = user.get("id")

            async def _resched_bg():
                try:
                    await fire_reschedule_notification(
                        job=_resched_job,
                        old_scheduled_date=old_sd,
                        new_scheduled_date=new_sd,
                        actor_user_id=_resched_actor,
                    )
                except Exception as _bg_exc:  # noqa: BLE001
                    logger.warning(
                        "reschedule notification bg task failed: %s",
                        _bg_exc,
                    )

            _resched_asyncio.create_task(_resched_bg())
    except Exception as _resched_exc:  # noqa: BLE001
        logger.warning(
            "reschedule notification scheduling failed: %s",
            _resched_exc,
        )

    # Feb 2026 · Auto-learn Job Title catalog on update. Bump only
    # when the title actually changed (and is non-empty) so a
    # save-without-change doesn't double-count. Fire-and-forget —
    # a catalog write must never break the job update path.
    try:
        _new_title = (update.get("title") or "").strip()
        _old_title = (job.get("title") or "").strip()
        if _new_title and _new_title != _old_title:
            from routers.job_titles import record_title_usage
            await record_title_usage(tenant["id"], _new_title)
    except Exception as _title_exc:  # noqa: BLE001
        logger.warning(
            "[job_titles] update-path record_title_usage failed: %s",
            _title_exc,
        )

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
            fresh = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0, "photos.data": 0})
            # ── Phase P45 · Feb-2026 · atomic single-writer gate ──
            # Claim the notification enqueue window BEFORE firing
            # ``send_completion_email``.  If a concurrent tech-submit
            # (via ``service_reports.submit``) already claimed the
            # gate, this branch is a no-op — no duplicate emails.
            # The pre-P45 auto ``schedule_auto_send_door_hanger``
            # call was removed here for the same reason (see P45
            # notes).  The manual "Email Door Hanger" endpoint at
            # ``workstream_service_log.email_door_hanger`` remains
            # the only authorised path for door-hanger sends.
            from services.service_report_submit_gate import (
                claim_submit_or_none,
            )
            _p45_claim = await claim_submit_or_none(
                tenant_id=tenant["id"], job_id=jid,
            )
            if _p45_claim is not None:
                await send_completion_email(fresh)
            else:
                logger.info(
                    "[p45] jobs.status=completed skipped completion email"
                    " — gate already claimed for job=%s tenant=%s",
                    jid, tenant["id"],
                )
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
            # Feb-2026 · Auto-extend recurring series on the last
            # unfinished occurrence. Fire-and-forget so the PATCH
            # response isn't blocked on the generator round-trip.
            # Idempotent via the partial-unique jobs index + an
            # in-process per-template lock.
            try:
                import asyncio as _asyncio
                from services.recurring_autogen import (
                    maybe_extend_recurring_series,
                )
                _asyncio.create_task(
                    maybe_extend_recurring_series(jid, tenant["id"])
                )
            except Exception as _rx:
                logger.warning(f"recurring auto-extend schedule failed: {_rx}")
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
            # Phase P25 · Feb-2026 — Workstream activity-feed event.
            # Distinct from the automation_engine / marketing
            # event_dispatcher emits above; those drive
            # customer-facing automations (comms sequences, review
            # requests), while this row lands in
            # ``db.workstream_events`` for the office/dispatch
            # activity feed and the workstream-job-detail
            # timeline. Wired here on the ONLINE completion path so
            # the mobile-sync replay path
            # (``routers/mobile_sync.py::_handle_job_close``) can
            # reuse the same helper — schema drift between the two
            # paths would break the timeline resolver.
            try:
                from routers.workstream import emit_job_completed_event
                await emit_job_completed_event(
                    tenant_id=tenant["id"],
                    actor_user_id=user.get("id"),
                    actor_role=user.get("role"),
                    job=fresh,
                    completed_at=fresh.get("completed_at"),
                    source="online",
                )
            except Exception as _wf_e:
                logger.warning(
                    "[workstream] online job.completed emit failed: %s",
                    _wf_e,
                )
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

    # Feb 2026 · Phase 1 Custom Trigger Builder — schema-v2 emissions
    # on the update path. The four events fire ONLY on the transition
    # into the new state; unchanged saves are no-ops. All emits are
    # correlation-scoped to the (job, transition) pair so replays
    # dedupe cleanly.
    try:
        from services.marketing.event_dispatcher import emit_event
        cur_status = (update.get("status") or job.get("status") or "").lower()
        prev_status = (job.get("status") or "").lower()
        # job_scheduled — new/changed scheduled_date.
        new_sched = update.get("scheduled_date")
        if new_sched and new_sched != job.get("scheduled_date"):
            await emit_event(
                event="job_scheduled",
                tenant_id=tenant["id"],
                entity_id=jid,
                customer_id=job.get("customer_id"),
                scheduled_at=f"{new_sched}T09:00:00+00:00",
                payload_extras={
                    "job": {**job, **update},
                    "correlation_id": f"{jid}:scheduled:{new_sched}",
                },
            )
        # job_completed — status flip to completed.
        if cur_status == "completed" and prev_status != "completed":
            await emit_event(
                event="job_completed",
                tenant_id=tenant["id"],
                entity_id=jid,
                customer_id=job.get("customer_id"),
                payload_extras={
                    "job": {**job, **update},
                    "correlation_id": f"{jid}:completed",
                },
            )
            # Feb-2026 · Job Timers dashboard phase — close any
            # open ``job_timers`` row for this job when the status
            # flips to ``completed``. Non-fatal — the helper
            # swallows exceptions and logs a warning.
            try:
                from routers.job_timers import close_open_timers_for_job
                await close_open_timers_for_job(
                    job_id=jid, tenant_id=tenant["id"],
                    actor_user_id=user.get("id"),
                    reason="job_completed",
                )
            except Exception as _jt_exc:                        # noqa: BLE001
                logger.warning(
                    "[job-timers] job_completed close failed: %s",
                    _jt_exc,
                )
            # Feb-2026 · Widget-Embed Extension — auto-enqueue a
            # public_checkins moderation row so the map surface
            # picks up completed jobs without a tech having to
            # tap "Submit to public" first. Tenant setting
            # ``auto_enqueue_public_checkins`` (default True)
            # gates the behaviour; idempotent by
            # ``(tenant_id, source_job_id)``.
            try:
                from services.public_checkin_enqueue import (
                    enqueue_public_checkin_for_completed_job,
                )
                await enqueue_public_checkin_for_completed_job(
                    {**job, **update, "id": jid,
                     "tenant_id": tenant["id"]},
                    actor_user_id=user.get("id"),
                )
            except Exception as _enq_exc:  # noqa: BLE001
                logger.warning(
                    "public_checkin auto-enqueue failed: %s",
                    _enq_exc,
                )
        # job_cancelled — status flip to cancelled.
        if cur_status == "cancelled" and prev_status != "cancelled":
            await emit_event(
                event="job_cancelled",
                tenant_id=tenant["id"],
                entity_id=jid,
                customer_id=job.get("customer_id"),
                payload_extras={
                    "job": {**job, **update},
                    "correlation_id": f"{jid}:cancelled",
                },
            )
        # repair_flagged — work_class flip to repair.
        new_wc = str(update.get("work_class") or "").lower()
        old_wc = str(job.get("work_class") or "").lower()
        if new_wc == "repair" and old_wc != "repair":
            await emit_event(
                event="repair_flagged",
                tenant_id=tenant["id"],
                entity_id=jid,
                customer_id=job.get("customer_id"),
                payload_extras={
                    "job": {**job, **update},
                    "correlation_id": f"{jid}:repair_flagged",
                },
            )
    except Exception as _phase1_exc:  # pragma: no cover — never break parent
        logger.warning(f"[phase1] job update emit failed: {_phase1_exc}")

    return await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.get("/public/job-photo/{jid}/{pid}")
async def public_job_photo(jid: str, pid: str):
    """Unauthenticated image endpoint for embedding job photos in emails (UUID-gated).
    Intentionally NOT tenant-scoped — the {jid}+{pid} pair acts as the magic token."""
    job = await db.jobs.find_one({"id": jid}, {"_id": 0, "photos": 1, "tenant_id": 1})
    if not job:
        raise HTTPException(404, "Not found")
    photo = next((p for p in (job.get("photos") or []) if p["id"] == pid), None)
    # Task L+P · Feb-2026 — SR fallback branch.
    # Before Task L+P this endpoint only saw ``jobs.photos``, which
    # meant Phase-27-era jobs (whose techs uploaded via
    # ``POST /api/service-reports/{report_id}/media`` and therefore
    # bypassed the ``jobs.photos`` mirror) rendered as broken 404
    # ``<img>`` tags on every list surface that used this URL shape
    # (Workstream MediaStrip, JobsList Photos column). Fallback rung:
    #   * Look up the SR photo scoped to
    #     ``(tenant_id, job_id, photo_id)`` — same tenant we just
    #     derived from the job doc, so no new attack surface.
    #   * Serve via the shared ``_serve_sr_photo`` cascade (below).
    # Magic-token auth model preserved: caller still needs BOTH jid
    # AND pid, and the merge only succeeds if the photo genuinely
    # belongs to that job.
    if not photo:
        sr_photo = await _find_sr_photo_by_job_and_id(
            jid, pid, job.get("tenant_id") or "",
        )
        if sr_photo:
            return await _serve_sr_photo(sr_photo, kind="full")
        raise HTTPException(404, "Not found")
    # ─── Feb-2026 · Photos-in-S3 Phase 1 · read via presigned URL ───
    # When the photo carries an ``s3_key`` AND the feature flag is
    # ON, redirect to a short-TTL presigned GET. Otherwise fall
    # back to the base64 payload so pre-migration photos + flag-off
    # environments keep working. The ``s3_key`` field is NEVER
    # exposed to the client — only the redirect target is.
    #
    # ─── Phase P35 · Feb-2026 · renderer fallback ladder ───────────
    # (1) HEAD-check the S3 object BEFORE issuing the client redirect,
    #     so a stale ``s3_key`` (NoSuchKey) can transparently fall
    #     through to the base64 payload instead of sending the
    #     browser to a broken URL.
    # (2) Fix the pre-P35 ``KeyError('data')`` bug — use
    #     ``.get("data")`` so an S3-only row that lost its base64
    #     doesn't 500.
    # (3) When the fallback fires, emit a structured
    #     ``[p35] photo fallback base64`` WARN so ops can measure
    #     migration-needed volume via log grep.
    # (4) When BOTH S3 miss + base64 empty, return a structured
    #     404 (``code=photo_not_found``) instead of the crash.
    s3_key = photo.get("s3_key")
    s3_hit = False
    if s3_key:
        try:
            from services.aws_s3.photos import (
                check_object_exists, generate_signed_url,
            )
            if check_object_exists(s3_key):
                s3_hit = True
                signed = generate_signed_url(s3_key)
                if signed:
                    from fastapi.responses import RedirectResponse
                    return RedirectResponse(url=signed, status_code=302)
        except Exception as _s3_exc:
            logger.warning(
                "[photos-s3] read soft-fail jid=%s pid=%s err=%s",
                jid, pid, _s3_exc,
            )
    # ── Base64 fallback branch (P35 renderer ladder step 2) ──
    data = photo.get("data")
    if not data:
        # Both missing — structured 404, NOT a 500. Log so ops can
        # spot orphaned rows.
        logger.warning(
            "[p35] photo not found (s3+base64 both missing) "
            "jid=%s pid=%s tenant=%s s3_key=%s",
            jid, pid, job.get("tenant_id") or "", s3_key or "",
        )
        raise HTTPException(
            status_code=404,
            detail={"code": "photo_not_found", "photo_id": pid},
        )
    # If we're here because S3 missed (or s3_key was empty), log the
    # migration-needed sentinel. Skip when we would have gone S3 —
    # only actual base64 fallbacks earn the WARN.
    if not s3_hit:
        logger.warning(
            "[p35] photo fallback base64 for photo_id=%s job_id=%s "
            "tenant=%s — s3_key=%s",
            pid, jid, job.get("tenant_id") or "", s3_key or "",
        )
    import base64
    if "," in data:
        header, b64 = data.split(",", 1)
        media = header.split(";")[0].replace("data:", "") or (
            photo.get("s3_mime") or "image/jpeg"
        )
    else:
        b64 = data
        media = photo.get("s3_mime") or "image/jpeg"
    try:
        payload = base64.b64decode(b64)
    except Exception as _dec_exc:
        logger.warning(
            "[p35] photo base64 decode failed jid=%s pid=%s err=%s",
            jid, pid, _dec_exc,
        )
        raise HTTPException(
            status_code=404,
            detail={"code": "photo_not_found", "photo_id": pid},
        )
    return Response(content=payload, media_type=media)


# ─────────────────────────────────────────────────────────────────
# Task L+P · Feb-2026 — Service-report photo fallback helpers.
#
# The three ``/api/public/job-photo/{jid}/{pid}[/thumb|/preview]``
# routes historically read ``jobs.photos`` only.  Phase 27 (Feb
# 2026) added the SR upload path (``POST /service-reports/
# {report_id}/media``) which writes to ``service_reports.photos``
# and bypasses ``jobs.photos`` entirely.  Every consumer of the
# public URL shape (Workstream MediaStrip, JobsList Photos column,
# door-hanger email body, portal service view) therefore 404'd on
# Phase-27-era photos.  These helpers close the gap by extending
# each of the three routes with an SR fallback rung.
#
# Auth model unchanged: caller must supply BOTH ``jid`` and ``pid``
# and the SR match filter includes ``job_id`` — so the endpoint
# only returns a photo that genuinely belongs to that job.  The
# tenant filter is derived from the job doc that step 1 already
# fetched (same as legacy jobs.photos serving); no new attack
# surface.
# ─────────────────────────────────────────────────────────────────
async def _find_sr_photo_by_job_and_id(
    jid: str, pid: str, tenant_id: str,
) -> Optional[dict]:
    """Return the SR photo subdoc matching (tenant_id, job_id,
    photo_id), or ``None`` when the SR doc is missing, soft-deleted
    (``deleted_at`` set on the SR doc), the photo id is not in the
    SR's ``photos[]`` array, or the individual photo is
    ``is_deleted``.  Uses the ``photos.$`` positional projection so
    only the matching subdoc crosses the wire, not every photo on
    the report.
    """
    if not (jid and pid and tenant_id):
        return None
    sr = await db.service_reports.find_one(
        {"tenant_id": tenant_id, "job_id": jid, "photos.id": pid},
        {"_id": 0, "photos.$": 1, "deleted_at": 1},
    )
    if not sr or sr.get("deleted_at"):
        return None
    photos = sr.get("photos") or []
    if not photos:
        return None
    p = photos[0]
    if not isinstance(p, dict) or p.get("is_deleted"):
        return None
    return p


async def _serve_sr_photo(photo: dict, *, kind: str):
    """Serve a service-report photo. ``kind`` in
    ``("full", "thumb", "preview")``.

    Serving cascade for the derivative variants (thumb/preview):
      1. ``s3_thumb_key`` / ``s3_preview_key`` present on the SR
         photo → 302 redirect to a short-TTL presigned URL.  These
         keys are NOT written by the Phase-27 upload path today
         (proper SR-thumb synthesis is a deferred follow-up); the
         branch is here so a later migration that backfills them
         works without a code change.
      2. Otherwise fall through to the full-size cascade below.

    Full-size cascade:
      1. ``storage_path`` present → stream bytes via
         ``services.object_storage.get_object`` (the canonical SR
         upload output; see ``routers/service_report_media.py``).
      2. ``s3_key`` present → 302 redirect to a presigned URL
         (legacy migration path — SR docs pre-object_storage).
      3. ``data`` present (base64 or ``data:`` URI) → decode +
         return inline.  Rare — only fires on legacy manual seeds.
      4. Otherwise → 404 with a structured detail body.  Kept
         parallel to the ``jobs.photos`` 404 shape so downstream
         consumers can log-grep the same code.
    """
    from fastapi.responses import RedirectResponse
    # Rung 1 — derivative-key redirect (thumb / preview only).
    if kind == "thumb":
        deriv_key = photo.get("s3_thumb_key")
    elif kind == "preview":
        deriv_key = photo.get("s3_preview_key")
    else:
        deriv_key = None
    if deriv_key:
        try:
            from services.aws_s3.photos import generate_signed_url
            signed = generate_signed_url(deriv_key)
            if signed:
                return RedirectResponse(url=signed, status_code=302)
        except Exception as _s3_exc:
            logger.warning(
                "[task-lp] SR deriv serve soft-fail pid=%s kind=%s err=%s",
                photo.get("id"), kind, _s3_exc,
            )

    # Rung 2 — full-size via object_storage (canonical Phase-27 path).
    storage_path = photo.get("storage_path")
    if storage_path:
        try:
            from services import object_storage as _storage
            data, ctype = _storage.get_object(storage_path)
            return Response(
                content=data,
                media_type=(
                    ctype or photo.get("content_type")
                    or photo.get("mime") or "image/jpeg"
                ),
            )
        except Exception as _stor_exc:
            logger.warning(
                "[task-lp] SR storage_path serve failed pid=%s path=%s err=%s",
                photo.get("id"), storage_path, _stor_exc,
            )

    # Rung 3 — s3_key legacy redirect.
    sr_s3_key = photo.get("s3_key")
    if sr_s3_key:
        try:
            from services.aws_s3.photos import generate_signed_url
            signed = generate_signed_url(sr_s3_key)
            if signed:
                return RedirectResponse(url=signed, status_code=302)
        except Exception as _s3_exc:
            logger.warning(
                "[task-lp] SR s3_key serve soft-fail pid=%s err=%s",
                photo.get("id"), _s3_exc,
            )

    # Rung 4 — inline base64 fallback.
    inline = photo.get("data")
    if isinstance(inline, str) and inline:
        if "," in inline:
            header, b64 = inline.split(",", 1)
            media = header.split(";")[0].replace("data:", "") or (
                photo.get("mime") or "image/jpeg"
            )
        else:
            b64 = inline
            media = photo.get("mime") or "image/jpeg"
        try:
            import base64 as _b64
            return Response(content=_b64.b64decode(b64), media_type=media)
        except Exception as _dec_exc:
            logger.warning(
                "[task-lp] SR base64 decode failed pid=%s err=%s",
                photo.get("id"), _dec_exc,
            )

    raise HTTPException(
        status_code=404,
        detail={"code": "photo_not_found", "photo_id": photo.get("id")},
    )


# ─────────────────────────────────────────────────────────────────
# Feb-2026 · Thumbnails ship — derivative read endpoints.
#
# Same auth model as the parent ``/public/job-photo/{jid}/{pid}``
# route (unauthenticated, UUID-gated). Selects between:
#   * 302 → presigned S3 sibling key (``s3_thumb_key`` / ``s3_preview_key``)
#   * Embedded base64 derivative on the doc (``photos[].thumb`` /
#     ``photos[].preview``) — flag-off path.
#   * Falls back to the original photo on any miss so a legacy row
#     that hasn't been backfilled yet still shows *something*.
# ─────────────────────────────────────────────────────────────────
async def _serve_derivative(jid: str, pid: str, kind: str):
    if kind not in ("thumb", "preview"):
        raise HTTPException(404, "Not found")
    job = await db.jobs.find_one({"id": jid}, {"_id": 0, "photos": 1, "tenant_id": 1})
    if not job:
        raise HTTPException(404, "Not found")
    photo = next((p for p in (job.get("photos") or []) if p["id"] == pid), None)
    # Task L+P · Feb-2026 — SR fallback branch (mirrors the
    # ``public_job_photo`` base route). When the pid does not
    # resolve in jobs.photos, look up the SR photo and serve via
    # the shared ``_serve_sr_photo`` cascade. Auth model preserved:
    # caller must supply both jid+pid; SR match filter includes
    # ``job_id`` so no cross-job leakage possible.
    if not photo:
        sr_photo = await _find_sr_photo_by_job_and_id(
            jid, pid, job.get("tenant_id") or "",
        )
        if sr_photo:
            return await _serve_sr_photo(sr_photo, kind=kind)
        raise HTTPException(404, "Not found")
    # 1. S3 path — signed sibling URL when the derivative key is stamped.
    deriv_key = photo.get("s3_thumb_key" if kind == "thumb" else "s3_preview_key")
    if deriv_key:
        try:
            from services.aws_s3.photos import generate_signed_url
            signed = generate_signed_url(deriv_key)
            if signed:
                from fastapi.responses import RedirectResponse
                return RedirectResponse(url=signed, status_code=302)
        except Exception as _s3_exc:
            logger.warning(
                "[photos-s3] deriv read soft-fail jid=%s pid=%s kind=%s err=%s",
                jid, pid, kind, _s3_exc,
            )
    # 2. Embedded base64 derivative (flag-off write path).
    inline = photo.get(kind)
    if inline and isinstance(inline, str) and "," in inline:
        header, b64 = inline.split(",", 1)
        media = header.split(";")[0].replace("data:", "") or "image/jpeg"
        import base64
        return Response(content=base64.b64decode(b64), media_type=media)
    # 3. Fallback — legacy row with no derivative. Serve the original
    # so <img> tags don't 404 while backfill catches up.
    return await public_job_photo(jid, pid)


@router.get("/public/job-photo/{jid}/{pid}/thumb")
async def public_job_photo_thumb(jid: str, pid: str):
    return await _serve_derivative(jid, pid, "thumb")


@router.get("/public/job-photo/{jid}/{pid}/preview")
async def public_job_photo_preview(jid: str, pid: str):
    return await _serve_derivative(jid, pid, "preview")


@router.delete("/jobs/{jid}")
async def delete_job(jid: str,
                     user: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    res = await db.jobs.delete_one({"id": jid, "tenant_id": tenant["id"]})
    await db.notifications.delete_many({"job_id": jid, "tenant_id": tenant["id"]})
    return {"ok": True, "deleted": res.deleted_count}


# ═════════════════════════════════════════════════════════════════════
# Feb-2026 · 24-hour post-completion edit window (PATCH + edit history)
# ═════════════════════════════════════════════════════════════════════
class JobEditPatch(BaseModel):
    # Phase C1 hotfix · Feb-2026 — silent-drop is worse than a hard
    # fail. ``extra="forbid"`` raises 422 on unknown keys so future
    # contract drift can never go unnoticed again (matches the
    # tester's recommendation).
    model_config = ConfigDict(extra="forbid")

    # Only the mutable set — anything not listed here is REJECTED by
    # Pydantic (extra="forbid" above).  Immutable-field guard runs
    # separately (see ``edit_window``).
    chemical_readings: Optional[List[Dict[str, Any]]] = None
    chemicals_added:   Optional[List[Dict[str, Any]]] = None
    checklist:         Optional[List[Dict[str, Any]]] = None
    checklist_items:   Optional[List[Dict[str, Any]]] = None
    notes:             Optional[str] = None
    observations:      Optional[str] = None
    photos:            Optional[List[Dict[str, Any]]] = None
    title:             Optional[str] = None
    service_notes:     Optional[str] = None
    # Phase K6 · Feb-2026 — priced field on the job doc.  Gated
    # server-side against the linked invoice's paid/partial-paid
    # status before the write lands.
    price_cents:       Optional[int] = None
    # Phase C1 hotfix · Feb-2026 — follow-up controls on the 24h
    # edit-window PATCH surface. Types match ``JobUpdate`` (the
    # working PUT schema) so PATCH and PUT accept identical
    # payloads. Role gate ("admin-equivalent only") is enforced in
    # ``patch_job_edit_window`` in lock-step with the PUT path so
    # techs get the exact same 403 wording end-to-end.
    follow_up_at:      Optional[str] = None
    needs_follow_up:   Optional[bool] = None
    # Free-text reason surfaced in the audit doc.  Never mutates the
    # job itself.
    edit_reason:       Optional[str] = None
    # Source of the edit (``web`` / ``mobile`` / ``api``).  Optional
    # so a plain UI call still works.
    edit_source:       Optional[str] = None


async def _authorize_edit(
    job: Dict[str, Any], user: Dict[str, Any],
) -> None:
    """Feb-2026 · edit-window auth cascade — technicians can edit
    only their own assigned jobs; admin roles have full write access.
    Customers are always rejected.

    Feb-2026 · Phase F1 — technicians on the assigned crew (but not
    the direct ``technician_id`` on the row) are now authorized via
    ``is_tech_authorized_on_job``. Previously crew-only jobs
    incorrectly returned 403 for every crew member.
    """
    role = (user.get("role") or "").lower()
    ADMIN_ROLES = {"admin", "super_admin", "owner", "manager"}
    if role in ADMIN_ROLES:
        return
    if role == "technician":
        if not await is_tech_authorized_on_job(user, job, db, job.get("tenant_id")):
            raise HTTPException(403, "Not your job")
        return
    raise HTTPException(403, "Not permitted to edit jobs")


@router.patch("/jobs/{jid}",
              operation_id="jobs.edit_within_window")
async def patch_job_edit_window(
    jid: str, body: JobEditPatch,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Feb-2026 · 24h post-completion edit path.

    Fixes mistakes on a completed job within
    :data:`services.edit_window.EDIT_WINDOW_HOURS` of ``completed_at``
    WITHOUT re-triggering the customer-facing completion side
    effects (door hanger email, drip sequences, SMS, invoice
    re-issue, webhook fan-out).

    Deliberately DOES NOT reuse ``update_job`` (the PUT status-flow
    endpoint) — separating the code path is the primary side-effect
    suppression mechanism.  See ``services/edit_window.py`` for the
    gate helpers.
    """
    from services.edit_window import (
        EDIT_WINDOW_HOURS, IMMUTABLE_FIELDS,
        assert_immutable_fields_untouched, diff_fields,
        hours_since_completion, is_within_edit_window,
        role_bypasses_edit_window,
    )
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"photos.data": 0})
    role = (user.get("role") or "").lower()
    # Gate 1 · soft-delete visibility.
    if not job:
        raise HTTPException(404, "Job not found")
    if job.get("deleted_at"):
        if role == "super_admin":
            raise HTTPException(
                status_code=409,
                detail={"detail": "job_soft_deleted",
                        "message": "Job is soft-deleted; restore first."},
            )
        # Non-super-admins get a stock 404 so the mere existence of a
        # soft-deleted job doesn't leak.
        raise HTTPException(404, "Job not found")

    # Gate 2 · role auth.
    await _authorize_edit(job, user)

    # Gate 3 · immutable field guard — reject payloads that try to
    # sneak in an admin-only field (customer_id, technician_id, etc.).
    # Phase C1 hotfix · Feb-2026 — Pydantic V2 ``model_dump`` swap.
    incoming = body.model_dump(exclude_none=True)
    # ``edit_reason`` + ``edit_source`` are audit-only and never
    # applied to the job doc.
    audit_reason = incoming.pop("edit_reason", None)
    audit_source = incoming.pop("edit_source", "web")
    assert_immutable_fields_untouched(incoming)

    # Phase C1 hotfix · Feb-2026 — follow-up controls are admin-only,
    # mirroring the PUT ``update_job`` role gate byte-for-byte so
    # PATCH and PUT stay in lock-step. Techs authorised on the job
    # itself may still edit chemistry / notes / photos via this
    # endpoint — only the two follow-up fields are gated. Matches
    # the exact wording from ``update_job`` so clients can compare
    # ``err.data.detail`` on either surface and see the same string.
    _ADMIN_ROLES_C1 = {"admin", "super_admin", "owner", "manager"}
    if ("follow_up_at" in incoming or "needs_follow_up" in incoming) \
            and role not in _ADMIN_ROLES_C1:
        raise HTTPException(
            403,
            "Only admin-equivalent roles can set follow-up fields",
        )

    # Gate 4 · status guard — only completed jobs may be edited via
    # this endpoint.  Non-completed jobs still use the existing
    # status-flow endpoints (PUT / service-report submit).
    if (job.get("status") or "").lower() != "completed":
        raise HTTPException(
            status_code=400,
            detail={"detail": "job_not_completed",
                    "message": "Edit path is for completed jobs only. "
                                "Use the existing status-flow endpoints for "
                                "non-completed jobs."},
        )

    # Gate 5 · edit window.
    # Phase K6 · Feb-2026 — the four K6-unlocked roles bypass the
    # 24h window entirely so late fixes on completed / invoiced /
    # paid jobs remain possible.  The audit trail below fires
    # unconditionally, so every post-completion edit is discoverable
    # on the Communication Timeline.
    _k6_bypass = role_bypasses_edit_window(role)
    if not _k6_bypass and not is_within_edit_window(job):
        raise HTTPException(
            status_code=403,
            detail={
                "detail": "edit_window_expired",
                "message": (
                    f"Edits allowed within {EDIT_WINDOW_HOURS} hours "
                    f"of completion"
                ),
                "hours_since_completion": hours_since_completion(job),
                "edit_window_hours": EDIT_WINDOW_HOURS,
            },
        )

    # Phase K6 · Feb-2026 — Invoice-linkage safety.  The current
    # schema exposes TWO joins from a completed job to its invoice
    # and we must try both:
    #   1. ``job.auto_invoice_id`` — the DIRECT back-pointer written
    #      by ``services/auto_invoice.py`` at completion time.  This
    #      is the path the tester's landscape-job scenario hits;
    #      the K6 shipping cut missed it.
    #   2. ``db.quotes.scheduled_job_id == job.id`` — the fallback
    #      for quote-converted invoices where the auto-invoice
    #      pipeline didn't run.
    # Whichever resolves first wins.  Neither → treat as no linked
    # invoice and allow the priced edit with no recalc.
    priced_fields_in_patch = {"price_cents"} & set(incoming.keys())
    invoice_recalculated = False
    linked_invoice: Optional[Dict[str, Any]] = None
    if priced_fields_in_patch:
        auto_iid = job.get("auto_invoice_id")
        if auto_iid:
            linked_invoice = await db.quotes.find_one(
                {"tenant_id": tenant["id"], "id": auto_iid,
                 "doc_type": "invoice"},
                {"_id": 0},
            )
        if not linked_invoice:
            linked_invoice = await db.quotes.find_one(
                {"tenant_id": tenant["id"], "doc_type": "invoice",
                 "scheduled_job_id": jid},
                {"_id": 0},
            )
        if linked_invoice:
            # Auto-invoice pipeline stamps ``payment_status`` at
            # record-payment time; the invoice ``status`` stays
            # ``issued`` even after payment lands.  We key off the
            # payment column, NOT the doc status.
            pay_status = (linked_invoice.get("payment_status") or "").lower()
            if pay_status in ("paid", "partial", "partially_paid"):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "detail": "invoice_locked",
                        "message": (
                            f"Invoice {linked_invoice.get('id')} is "
                            f"paid — void or refund the invoice "
                            f"before editing priced fields on this "
                            f"completed job."
                        ),
                        "invoice_id": linked_invoice.get("id"),
                        "invoice_status": pay_status,
                    },
                )

    # Gate 6 · chemistry re-check.  If the edit touches any of the
    # 5 core readings, the resulting state must still satisfy the
    # chemistry gate.  Reuse the same helper — no fork.
    if "chemical_readings" in incoming:
        from services.chemistry_gate import (
            assert_core_readings_present, gather_readings_for_job, is_pool_job,
        )
        if is_pool_job(job):
            # Merge: existing service_report + patch-in readings so
            # the gate sees the RESULTING state, not the delta.
            rep = await db.service_reports.find_one(
                {"tenant_id": tenant["id"], "job_id": jid}, {"_id": 0},
            ) or {}
            merged_source = dict(rep)
            merged_source["chemical_readings"] = incoming["chemical_readings"]
            assert_core_readings_present(
                gather_readings_for_job(job, merged_source),
            )

    # Compute the diff BEFORE touching anything so the audit row
    # reflects the actual state change.
    changes = diff_fields(job, incoming, skip=("updated_at",))
    if not changes:
        # No-op edit — no audit row, but return the current job so the
        # UI can rerender cleanly.
        job.pop("_id", None)
        return job

    # Write the audit doc FIRST — if the job mutation fails afterwards
    # we roll it back so the log doesn't lie.  If the audit write
    # itself crashes, the job never gets touched.
    edit_id = new_id()
    audit_doc = {
        "id": edit_id,
        "tenant_id": tenant["id"],
        "job_id": jid,
        # CLOSED-JOB-EDIT-UNLOCK · Feb-2026 — new ``event`` tag on
        # the canonical ``db.job_edits`` audit collection so the
        # Communication Timeline + ops dashboards can distinguish
        # pre-K6 edits (window-gated), K6 bypass edits, and post-
        # CLOSED-JOB-EDIT-UNLOCK "closed job" edits.  Legacy rows
        # (no ``event``) continue to render as "Job edited".
        "event": "closed_job_edit",
        "edited_by": user.get("id"),
        "edited_by_name": user.get("name") or user.get("email"),
        "edited_by_role": role,
        "edited_at": now_iso(),
        "changes": changes,
        "reason": (audit_reason or "").strip()[:500] or None,
        "source": audit_source if audit_source in {"web", "mobile", "api"} else "web",
    }
    await db.job_edits.insert_one(audit_doc)

    try:
        incoming["updated_at"] = now_iso()
        await db.jobs.update_one(
            {"id": jid, "tenant_id": tenant["id"]}, {"$set": incoming},
        )
    except Exception:
        # Rollback the audit row so history doesn't record a change
        # that never landed.  Then bubble the 500.
        await db.job_edits.delete_one({"id": edit_id})
        raise

    fresh = await db.jobs.find_one(
        {"id": jid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    # DO NOT call ``send_completion_email`` / ``schedule_auto_send_door_hanger``
    # / ``create_recurring_maintenance`` / anything from the PUT path.
    # Belt-and-suspenders: even if a future refactor accidentally
    # imports the PUT handler, the door-hanger ledger key
    # ``door_hanger_auto:{job_id}`` still prevents a duplicate email.

    # Phase K6 (round 2) · Feb-2026 — Invoice recalc for unpaid,
    # editable invoices (payment_status == "unpaid").  Round-1 shipped
    # an additive-only fix on ``subtotal_cents`` + ``total_cents`` and
    # left the invoice's ``line_items[]`` + legacy dollar mirrors
    # (``subtotal`` / ``total``) stale — so downstream PDFs / list
    # endpoints kept rendering the pre-edit price.
    #
    # Round-2 rules:
    #   1. Compute ``delta_cents = new_price_cents - old_price_cents``.
    #   2. Update the invoice's job-priced line item's
    #      ``unit_price_cents`` + ``line_total_cents`` (quantity is
    #      preserved) so ``sum(line_total_cents) == new subtotal``.
    #      The "job-priced" line is the first row whose ``kind`` is
    #      ``service`` OR ``job_line_item`` — that's what the
    #      auto-invoice pipeline emits from ``job.price`` /
    #      ``job.line_items[]``.  Chemical rows are left alone.
    #   3. Recompute ``subtotal_cents = sum(li.line_total_cents)``.
    #      When the invoice has no line_items (legacy fixture / early
    #      auto-invoice runs), fall back to the additive delta.
    #   4. Preserve the existing tax + discount envelope by keeping
    #      ``total_cents - subtotal_cents`` constant across the edit.
    #   5. Refresh legacy float mirrors (``subtotal`` / ``total``)
    #      from the new cents fields.
    #   6. Store ``k6_last_recalc_delta_cents = delta_cents`` for
    #      the audit assertions.
    if linked_invoice and "price_cents" in incoming:
        try:
            price_delta_cents = int(incoming.get("price_cents") or 0) \
                - int(job.get("price_cents") or 0)
        except (TypeError, ValueError):
            price_delta_cents = 0
        if price_delta_cents:
            # Capture the invoice's PRE-edit subtotal so
            # ``k6_last_recalc_delta_cents`` reflects the actual
            # invoice-side change (subtotal delta) — not just the
            # job-price delta.  These coincide for single-service-line
            # invoices but the subtotal formulation is authoritative
            # on the invoice side and survives edge cases where
            # ``job.price_cents`` drifts from ``sum(line_total_cents)``.
            prev_subtotal_cents = int(
                linked_invoice.get("subtotal_cents") or 0)
            old_total_cents = int(
                linked_invoice.get("total_cents") or 0)
            # Preserve tax / discount envelope: whatever the pricing
            # engine added between subtotal and total at issue time
            # stays untouched across the K6 recalc.
            envelope_cents = old_total_cents - prev_subtotal_cents

            existing_items = list(linked_invoice.get("line_items") or [])
            updated_items: List[Dict[str, Any]] = []
            job_priced_hit = False
            new_price_cents = int(incoming.get("price_cents") or 0)
            for row in existing_items:
                kind = (row.get("kind") or "").lower()
                if not job_priced_hit and kind in ("service", "job_line_item"):
                    qty = row.get("quantity")
                    try:
                        qty_num = float(qty) if qty is not None else 1.0
                    except (TypeError, ValueError):
                        qty_num = 1.0
                    # ``price_cents`` on the job represents the priced
                    # service total for that job — mirror it as the
                    # LINE TOTAL and derive per-unit from quantity so
                    # dividing prices (qty > 1) still reconciles.
                    if qty_num and qty_num != 1.0:
                        unit_cents = int(round(new_price_cents / qty_num))
                    else:
                        unit_cents = new_price_cents
                    new_row = dict(row)
                    new_row["unit_price_cents"] = unit_cents
                    new_row["line_total_cents"] = new_price_cents
                    # Legacy dollar mirror on the line (F7 path writes
                    # both).  Keep it consistent.
                    if "unit_price" in new_row:
                        new_row["unit_price"] = unit_cents / 100.0
                    updated_items.append(new_row)
                    job_priced_hit = True
                else:
                    updated_items.append(row)

            if job_priced_hit:
                new_subtotal_cents = sum(
                    int(r.get("line_total_cents") or 0) for r in updated_items)
            else:
                # No job-priced line item to mutate (legacy fixture or
                # invoice built from chemical events only).  Fall back
                # to additive so subtotal still tracks the job edit.
                new_subtotal_cents = prev_subtotal_cents + price_delta_cents

            new_total_cents = new_subtotal_cents + envelope_cents
            # THE fix (round-2 follow-up · Feb-2026): compute the
            # persisted delta from the subtotal change so the audit
            # field always reflects the invoice-side movement,
            # including negative deltas on price decreases.
            delta_cents = new_subtotal_cents - prev_subtotal_cents

            update_set: Dict[str, Any] = {
                "subtotal_cents": new_subtotal_cents,
                "total_cents": new_total_cents,
                # Legacy float mirrors — some list / PDF paths still
                # render off these (see auto_invoice.py which stamps
                # ``total`` on issue).
                "subtotal": new_subtotal_cents / 100.0,
                "total": new_total_cents / 100.0,
                "updated_at": now_iso(),
                "k6_last_recalc_delta_cents": delta_cents,
            }
            if job_priced_hit:
                update_set["line_items"] = updated_items

            await db.quotes.update_one(
                {"id": linked_invoice["id"], "doc_type": "invoice"},
                {"$set": update_set},
            )
            invoice_recalculated = True

    # Phase K6 · Feb-2026 — Communication-timeline audit entry.
    # Written to ``db.audit_events`` with the new
    # ``job_edited_after_completion`` event_type; the timeline
    # router surfaces it under the job's customer.  Compact by
    # design — records field NAMES only, never before/after values.
    if (job.get("status") or "").lower() == "completed" \
            or job.get("completed_at"):
        try:
            fields_changed = sorted(list(changes.keys()))
            await db.audit_events.insert_one({
                "id": new_id(),
                "tenant_id": tenant["id"],
                "event_type": "job_edited_after_completion",
                "actor_id": user.get("id"),
                "actor_email": user.get("email") or user.get("name") or "",
                "timestamp": now_iso(),
                "payload": {
                    "job_id": jid,
                    "customer_id": job.get("customer_id"),
                    "user_id": user.get("id"),
                    "user_name": user.get("name") or user.get("email") or "",
                    "user_role": role,
                    "fields_changed": fields_changed,
                    "invoice_recalculated": invoice_recalculated,
                    "invoice_id": (linked_invoice or {}).get("id"),
                },
            })
        except Exception:
            # Never let an audit-write failure roll back the job
            # edit — the ``db.job_edits`` history above is the
            # primary source of truth; audit_events is the
            # timeline mirror.
            logger.warning(
                "[k6] audit_events insert failed for job %s",
                jid, exc_info=True,
            )

    return fresh


@router.get("/jobs/{jid}/edits",
            operation_id="jobs.list_edits")
async def list_job_edits(
    jid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """List the audit history for a job.  Sorted ``edited_at desc``,
    capped at 100 rows.  Enforces the same tenant + role scoping as
    the PATCH endpoint."""
    job = await db.jobs.find_one(
        {"id": jid, "tenant_id": tenant["id"]},
        # Feb-2026 · F1 fix — must include ``crew_id`` (+ ``tenant_id``)
        # so ``is_tech_authorized_on_job`` can see crew membership.
        # Without ``crew_id`` the helper's crew-branch short-circuits
        # to False and every crew-only job returns 403.
        {"_id": 0, "id": 1, "technician_id": 1, "crew_id": 1,
         "tenant_id": 1, "deleted_at": 1},
    )
    if not job or job.get("deleted_at"):
        # Same 404 mask as PATCH.
        raise HTTPException(404, "Job not found")
    role = (user.get("role") or "").lower()
    ADMIN_ROLES = {"admin", "super_admin", "owner", "manager"}
    if role == "technician":
        # F1 · crew-aware tech gate — see services/authz.py.
        if not await is_tech_authorized_on_job(user, job, db, tenant["id"]):
            raise HTTPException(403, "Not your job")
    elif role not in ADMIN_ROLES:
        raise HTTPException(403, "Not permitted to read edit history")
    rows = await db.job_edits.find(
        {"tenant_id": tenant["id"], "job_id": jid},
        {"_id": 0},
    ).sort("edited_at", -1).to_list(100)
    return {"count": len(rows), "edits": rows}


# ═════════════════════════════════════════════════════════════════════════
# CHEM-LOCK · Feb-2026 — Admin-controlled submitted-job unlock
# ═════════════════════════════════════════════════════════════════════════
#
# The service-report submit flow stamps ``submitted_at`` via the P45
# atomic claim gate (services/service_report_submit_gate.py). Once
# stamped, the report is locked — PATCH returns 409 for admin, and
# the tech FE hides edit controls.
#
# Admins occasionally need to correct a submitted visit (typo in a
# chemical quantity, wrong reading, forgot to check a box). The
# ``POST /api/jobs/{jid}/unlock`` endpoint below is the ONE surface
# that opens the door back up, with a hard-required reason string
# and full audit trail in ``db.job_edits``.
#
# Semantics:
#   1. Guard: ``admin`` / ``super_admin`` / ``owner`` / ``manager``
#      only. Tech role → 403 (that's the whole point).
#   2. Reason: required, min 8 chars, stored verbatim (max 500 chars).
#   3. Effect on service_report:
#        - Captures the current ``submitted_at`` as
#          ``previously_submitted_at`` (so a later resubmit can
#          stamp ``superseded_at`` — see the stale-report banner
#          in service_reports.submit).
#        - Unsets ``submitted_at`` + the notification queue markers
#          (``email_pending_at`` / ``sms_pending_at``) so the P45
#          claim gate will grant the next submit cleanly.
#   4. Effect on job doc:
#        - Sets ``unlocked_at`` / ``unlocked_by`` / ``unlocked_reason``.
#        - Preserves ``status: completed`` — we're not reopening.
#          (Reopen is a separate flow with its own semantics.)
#   5. Audit: writes to ``db.job_edits`` (the SAME collection K6
#      uses for the completion-edit audit sidebar) so the existing
#      ``GET /api/jobs/{jid}/edits`` surface picks it up for free.
#   6. Warnings: response includes ``warnings: [...]`` — currently
#      the single ``"invoice_paid"`` flag when the linked invoice
#      has ``payment_status in (paid, partial, partially_paid)``.
#      NOT a hard block — brief §Edge cases §3.
#   7. Auto-relock: handled by the submit path itself — the P45
#      gate re-stamps ``submitted_at`` on the next submit, which
#      is the lock.
#   8. Multiple unlocks: allowed. Each writes its own audit row
#      with ``previous_state`` capturing the ``submitted_at``
#      value BEFORE the unlock.
class JobUnlockIn(BaseModel):
    reason: str


@router.post("/jobs/{jid}/unlock",
              operation_id="jobs.unlock_submitted")
async def unlock_submitted_job(
    jid: str, body: JobUnlockIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """CHEM-LOCK · Feb-2026 — Unlock a submitted-and-locked service
    report for admin-supervised retroactive edits.

    Response
    --------
    ``{
        "ok": True,
        "warnings": ["invoice_paid"?],
        "audit_id": <db.job_edits.id>,
        "unlocked_at": <ISO>,
        "job": {..., "unlocked_at": ..., "unlocked_by": ...},
    }``

    Errors
    ------
    * ``400`` — missing / short reason (< 8 chars).
    * ``403`` — non-admin role.
    * ``404`` — job not found / soft-deleted.
    * ``409`` — job is not currently submitted (nothing to unlock).
    """
    role = (user.get("role") or "").strip().lower()
    _ADMIN_ROLES = {"admin", "super_admin", "owner", "manager"}
    if role not in _ADMIN_ROLES:
        # Tech / customer / viewer / … — hard block. This is the
        # WHOLE point of the feature; oversight belongs to admin.
        raise HTTPException(403, "Only admin roles can unlock submitted jobs")

    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(
            400,
            detail={"detail": "reason_required",
                    "message": "A reason is required to unlock a submitted job"},
        )
    if len(reason) < 8:
        raise HTTPException(
            400,
            detail={"detail": "reason_too_short",
                    "message": "Reason must be at least 8 characters"},
        )

    job = await db.jobs.find_one(
        {"id": jid, "tenant_id": tenant["id"]},
        {"_id": 0, "photos.data": 0},
    )
    if not job or job.get("deleted_at"):
        raise HTTPException(404, "Job not found")

    # Locate the associated service report(s) — a job may have one
    # SR per tech in a crew scenario. We unlock every submitted SR
    # attached to this job so the tech(s) can correct their entries.
    sr_rows = await db.service_reports.find(
        {"tenant_id": tenant["id"], "job_id": jid},
        {"_id": 0, "id": 1, "submitted_at": 1, "tech_id": 1,
         "previously_submitted_at": 1},
    ).to_list(20)
    submitted_sr = [r for r in sr_rows if r.get("submitted_at")]

    if not submitted_sr:
        # Job was completed but the SR was never stamped (unusual
        # legacy path) OR the SR was already unlocked by a prior
        # call. Idempotent 409 — nothing to do.
        raise HTTPException(
            409,
            detail={"detail": "not_locked",
                    "message": ("No submitted service report on this "
                                "job — nothing to unlock.")},
        )

    now = now_iso()

    # ── Snapshot previous_state for the audit row ─────────────────
    # ``previous_state`` captures the fields we are about to clear
    # so the audit history is reconstructable even after multiple
    # unlocks. Cheap dict copy — no PII fields.
    previous_state = {
        "service_reports": [
            {
                "id": r.get("id"),
                "tech_id": r.get("tech_id"),
                "submitted_at": r.get("submitted_at"),
                "previously_submitted_at": r.get("previously_submitted_at"),
            }
            for r in submitted_sr
        ],
        "job_unlocked_at": job.get("unlocked_at"),
    }

    # ── Unlock the service reports ────────────────────────────────
    # $set stamps the pre-unlock ``submitted_at`` as
    # ``previously_submitted_at`` so the resubmit path can flag
    # ``superseded_at`` for the portal "updated after original send"
    # banner. We keep the FIRST previously_submitted_at we've ever
    # seen (setOnInsert semantics — but we're using $set so add a
    # conditional).
    for sr in submitted_sr:
        sr_updates = {
            "$unset": {
                "submitted_at": "",
                "email_pending_at": "",
                "sms_pending_at": "",
            },
            "$set": {"updated_at": now},
        }
        # Preserve the ORIGINAL previously_submitted_at (from an
        # earlier unlock/resubmit cycle) — if it's missing, stamp
        # this unlock's cleared value.
        if not sr.get("previously_submitted_at"):
            sr_updates["$set"]["previously_submitted_at"] = sr["submitted_at"]
        # Always stamp the MOST RECENT cleared submit — the resubmit
        # flag uses this to know a delta happened.
        sr_updates["$set"]["last_unlocked_submitted_at"] = sr["submitted_at"]
        await db.service_reports.update_one(
            {"tenant_id": tenant["id"], "id": sr["id"]},
            sr_updates,
        )

    # ── Update the job doc ────────────────────────────────────────
    # Preserve ``status: completed`` — we're NOT reopening. Techs
    # correct in-place; the resubmit re-stamps submitted_at.
    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"]},
        {"$set": {
            "unlocked_at": now,
            "unlocked_by": user.get("id"),
            "unlocked_by_email": user.get("email"),
            "unlocked_reason": reason[:500],
            "updated_at": now,
        }},
    )

    # ── Paid-invoice warning ──────────────────────────────────────
    # Non-blocking: brief §Edge cases §3 requires ONLY a warning,
    # not a hard 409. FE renders a confirmation checkbox.
    warnings: List[str] = []
    auto_iid = job.get("auto_invoice_id")
    linked_invoice = None
    if auto_iid:
        linked_invoice = await db.quotes.find_one(
            {"tenant_id": tenant["id"], "id": auto_iid,
             "doc_type": "invoice"},
            {"_id": 0, "id": 1, "payment_status": 1},
        )
    if not linked_invoice:
        linked_invoice = await db.quotes.find_one(
            {"tenant_id": tenant["id"], "doc_type": "invoice",
             "scheduled_job_id": jid},
            {"_id": 0, "id": 1, "payment_status": 1},
        )
    if linked_invoice:
        pay_status = (linked_invoice.get("payment_status") or "").lower()
        if pay_status in ("paid", "partial", "partially_paid"):
            warnings.append("invoice_paid")

    # ── Audit row in db.job_edits ─────────────────────────────────
    # Reusing the K6 collection so the existing ``GET /jobs/{jid}/edits``
    # surface (JobEditPanel.jsx:97) picks up unlocks for free. The
    # ``changes`` payload uses the same {before, after} shape as
    # other job_edits rows so the FE renders naturally.
    edit_id = new_id()
    audit_doc = {
        "id": edit_id,
        "tenant_id": tenant["id"],
        "job_id": jid,
        "edited_by": user.get("id"),
        "edited_by_name": user.get("name") or user.get("email"),
        "edited_by_role": role,
        "edited_at": now,
        "action": "unlock",
        "changes": {
            "lock_state": {"before": "locked", "after": "unlocked"},
        },
        "reason": reason[:500],
        "previous_state": previous_state,
        "warnings": warnings,
        "source": "web",
    }
    await db.job_edits.insert_one(audit_doc)

    fresh = await db.jobs.find_one(
        {"id": jid, "tenant_id": tenant["id"]}, {"_id": 0, "photos.data": 0},
    )
    return {
        "ok": True,
        "warnings": warnings,
        "audit_id": edit_id,
        "unlocked_at": now,
        "job": fresh,
    }



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
                                  user: dict = Depends(require_admin_or_manager),
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
    # Feb-2026 · Crew Phase A · both optional. At least one must be
    # provided (validated in the handler). Callers can send tech-only,
    # crew-only, or both (overlay — tech stays as lead, crew members
    # get read-side visibility via ``schedule_today``'s crew clause).
    new_tech_id: Optional[str] = None
    new_crew_id: Optional[str] = None


_TECH_ROLES = {"pool_tech", "landscape_tech", "technician", "tech"}
_BULK_REASSIGN_CAP = 100

# ═══════════════════════════════════════════════════════════════════
# BULK-RESCHEDULE · Feb-2026 — bulk scheduled_date move
# ═══════════════════════════════════════════════════════════════════
# Cap intentionally matches ``_BULK_REASSIGN_CAP`` so the two schedule
# bulk actions share the same server-side ceiling.  Above the cap →
# HTTP 400 ``too_many_job_ids``.  Empty list → HTTP 400
# ``no_job_ids``.  Rows shielded from the mutation:
#
#   * ``not_found``   — id doesn't exist anywhere in Mongo.
#   * ``wrong_tenant`` — id exists but belongs to another tenant.
#     Preserved as a distinct skip reason (surfaced to the caller so
#     an FE audit / mixed-tenant clipboard paste is visible), but no
#     tenant-scope leakage — the caller already knew the id existed
#     to submit it.
#   * ``soft_deleted`` — HD-A rail; ``deleted_at`` is set.
#   * ``locked``       — CHEM-LOCK rail; ``service_reports.submitted_at``
#     is set for this job, OR the job is in a terminal
#     ``completed`` / ``cancelled`` status.  Either way we refuse to
#     move it.
#
# For every non-skipped id the per-job side-effects mirror the
# single-job PATCH reschedule path:
#
#   1. ``jobs.update_one`` — ``scheduled_date`` + ``updated_at``.
#   2. ``fire_reschedule_notification`` bg task (SAFE-SEND SYSTEM
#      customer notification — dedicated pipeline in
#      :mod:`services.notifications_pipeline.service_notifications`).
#   3. ``notify_customer`` in-app bell rung — "Service scheduled".
#   4. ``audit_log`` row per job with ``action=job.reschedule``.
#
# The bg-task fanout runs one task PER JOB (no batching / no
# notification suppression) — that's the brief's explicit contract
# ("each job's customer gets their own notification per current
# single-job behavior").
# ═══════════════════════════════════════════════════════════════════
_BULK_RESCHEDULE_CAP = 100
_BULK_RESCHEDULE_PAST_LIMIT_DAYS = 90


class BulkRescheduleIn(BaseModel):
    """Payload for POST /jobs/bulk-reschedule.

    ``scheduled_date`` is a bare ``YYYY-MM-DD`` string.  Time-of-day
    is *not* accepted here — the single-job reschedule path uses a
    date-only field on the schedule surface, and this endpoint is a
    strict bulk-superset of that flow.
    """
    model_config = ConfigDict(extra="forbid")
    job_ids: List[str]
    scheduled_date: str


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
                                user: dict = Depends(require_admin_or_manager),
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

    if not body.new_tech_id and not body.new_crew_id:
        raise HTTPException(
            400, "new_tech_id or new_crew_id is required")

    # Feb-2026 · Crew Phase A · resolve tech (only if provided).
    new_user = None
    canonical_tech_id = None
    if body.new_tech_id:
        new_user = await _lookup_tech_user(tenant["id"], body.new_tech_id)
        if not new_user:
            raise HTTPException(400, "new_tech_id does not resolve to a user")
        role = (new_user.get("role") or "").lower()
        if role not in _TECH_ROLES:
            raise HTTPException(
                400, f"new_tech_id role {role!r} is not a technician role")
        canonical_tech_id = new_user.get("technician_id") or new_user.get("id")

    # Feb-2026 · Crew Phase A · resolve crew (only if provided).
    # Same-tenant validation prevents cross-tenant crew bindings.
    new_crew = None
    if body.new_crew_id:
        new_crew = await db.crews.find_one(
            {"id": body.new_crew_id, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "name": 1, "color": 1},
        )
        if not new_crew:
            raise HTTPException(
                400, "new_crew_id does not resolve to a crew in this tenant")

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
              "title": 1, "service_type": 1, "deleted_at": 1,
              # Feb-2026 · Crew Phase A · project crew_id so we can
              # detect the crew-side no-op case + skip the write.
              "crew_id": 1},
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
        # Feb-2026 · Crew Phase A · net-no-op detection now considers
        # both tech AND crew dimensions. A caller can send tech
        # unchanged + crew changed (or vice versa) and we must still
        # write the changed dimension. Only skip when NEITHER dimension
        # moves.
        tech_changes = (canonical_tech_id is not None
                          and old_tech_id != canonical_tech_id)
        crew_changes = (new_crew is not None
                          and job.get("crew_id") != new_crew["id"])
        if not tech_changes and not crew_changes:
            reassigned.append(jid)
            continue

        set_fields: Dict[str, Any] = {
            "reassigned_at": now,
            "reassigned_by_user_id": user.get("id"),
            "updated_at": now,
        }
        if canonical_tech_id:
            set_fields["technician_id"] = canonical_tech_id
            set_fields["assigned_tech_id"] = canonical_tech_id
        if new_crew:
            set_fields["crew_id"] = new_crew["id"]
            set_fields["crew_name"] = new_crew.get("name")
            set_fields["crew_color"] = new_crew.get("color")

        try:
            await db.jobs.update_one(
                {"id": jid, "tenant_id": tenant["id"]},
                {"$set": set_fields},
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
            # Feb-2026 · Crew Phase A · record crew reassignment
            # alongside tech reassignment so audit can be filtered
            # by crew changes downstream.
            "old_crew_id": job.get("crew_id"),
            "new_crew_id": new_crew["id"] if new_crew else None,
            "at": now,
        })
        # Feb-2026 · Crew Phase A · only notify the *outgoing* tech
        # when this call actually reassigns them off the job. Crew-only
        # reassignments (``canonical_tech_id is None``) never touch
        # ``technician_id``, so the outgoing tech is still assigned
        # and should NOT get a "you lost this job" notification.
        if (canonical_tech_id and old_tech_id
                and old_tech_id != canonical_tech_id):
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
            # New tech — one aggregate notification. Feb-2026 · Crew
            # Phase A · guarded on ``new_user`` so a crew-only
            # reassignment (no new tech) skips this branch entirely.
            new_user_id = (new_user or {}).get("id")
            if new_user_id and incoming_titles:
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
              "new_tech_name": ((new_user or {}).get("name")
                                  or (new_user or {}).get("first_name") or ""),
              # Feb-2026 · Crew Phase A · surface the crew binding
              # so the caller (web dispatch board / mobile) can
              # render the confirmation toast without a re-fetch.
              "new_crew_id": new_crew["id"] if new_crew else None,
              "new_crew_name": (new_crew or {}).get("name") or ""}


# ═══════════════════════════════════════════════════════════════════
# BULK-RESCHEDULE endpoint · Feb-2026
# ═══════════════════════════════════════════════════════════════════
def _validate_bulk_reschedule_date(raw: str) -> str:
    """Validate the payload's ``scheduled_date`` string.

    Rules:
      * Must be non-empty.
      * Must match ``YYYY-MM-DD`` (strict — time-of-day rejected).
      * Must parse as a real calendar date (Feb-30 rejected).
      * Must be no more than ``_BULK_RESCHEDULE_PAST_LIMIT_DAYS``
        days in the past — protects against operator typos that
        would silently move jobs to 1970.

    Returns the normalised date string on success; raises
    :class:`HTTPException` (400 with ``error_code: invalid_scheduled_date``)
    on any failure.
    """
    if not isinstance(raw, str):
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_scheduled_date",
                     "message": "scheduled_date must be a "
                                 "YYYY-MM-DD string"},
        )
    s = raw.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_scheduled_date",
                     "message": "scheduled_date must be exactly "
                                 "YYYY-MM-DD",
                     "received": raw},
        )
    try:
        parsed = datetime.strptime(s, "%Y-%m-%d").replace(
            tzinfo=timezone.utc,
        )
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_scheduled_date",
                     "message": "scheduled_date is not a real "
                                 "calendar date",
                     "received": raw},
        )
    today_utc = datetime.now(timezone.utc)
    if (today_utc - parsed).days > _BULK_RESCHEDULE_PAST_LIMIT_DAYS:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_scheduled_date",
                     "message":
                       f"scheduled_date more than "
                       f"{_BULK_RESCHEDULE_PAST_LIMIT_DAYS} days in "
                       f"the past — refusing (typo guard).",
                     "received": raw,
                     "past_limit_days":
                        _BULK_RESCHEDULE_PAST_LIMIT_DAYS},
        )
    return s


_LOCKED_JOB_STATUSES: Tuple[str, ...] = ("completed", "cancelled")


async def _is_job_submit_locked(tenant_id: str, job_id: str) -> bool:
    """Return True when a matching ``service_reports`` row carries a
    non-null ``submitted_at`` (CHEM-LOCK rail)."""
    row = await db.service_reports.find_one(
        {"tenant_id": tenant_id, "job_id": job_id,
         "submitted_at": {"$ne": None}},
        {"_id": 0, "id": 1},
    )
    return row is not None


@router.post("/jobs/bulk-reschedule",
              operation_id="jobs.bulkReschedule")
async def bulk_reschedule_jobs(
    body: BulkRescheduleIn,
    user: dict = Depends(require_admin_or_manager),
    tenant: dict = Depends(get_current_tenant),
):
    """BULK-RESCHEDULE · Feb-2026 · Schedule multi-select move.

    Bulk equivalent of the single-job ``PATCH /jobs/{jid}`` reschedule
    path: for every valid job in ``job_ids`` we update
    ``scheduled_date`` + ``updated_at``, fire the SAFE-SEND SYSTEM
    customer-facing reschedule notification as a background task,
    ring the in-app bell channel, and write an ``audit_log`` row.

    Response shape::

        {
          "rescheduled_count": int,
          "skipped": [{"job_id": str, "reason": str}, ...],
          "target_date": "YYYY-MM-DD"
        }

    Skip reasons: ``not_found``, ``wrong_tenant``, ``soft_deleted``,
    ``locked``.  Locked = CHEM-LOCK submitted-service-report OR
    ``status in ("completed", "cancelled")``.  Every non-skipped job
    is rescheduled and receives the same fanout as if it had been
    PATCHed individually.
    """
    ids = list(dict.fromkeys(body.job_ids or []))
    if not ids:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "no_job_ids",
                     "message": "job_ids is empty"},
        )
    if len(ids) > _BULK_RESCHEDULE_CAP:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "too_many_job_ids",
                     "message":
                       f"bulk reschedule capped at "
                       f"{_BULK_RESCHEDULE_CAP} rows per call",
                     "limit": _BULK_RESCHEDULE_CAP,
                     "received": len(ids)},
        )
    target_date = _validate_bulk_reschedule_date(body.scheduled_date)

    tid = tenant["id"]
    now = now_iso()
    rescheduled: List[str] = []
    skipped: List[Dict[str, Any]] = []
    audit_rows: List[Dict[str, Any]] = []
    # Per-job (old, new) pairs so we can fanout notifications AFTER
    # the mutation writes have all persisted — mirrors the single-
    # job PATCH bg-task ordering.
    to_notify: List[Dict[str, Any]] = []

    for jid in ids:
        # Cross-tenant existence check first — surfaced as
        # ``wrong_tenant`` distinctly from ``not_found`` per brief.
        # No mutation on either branch.
        row = await db.jobs.find_one(
            {"id": jid},
            {"_id": 0, "id": 1, "tenant_id": 1, "deleted_at": 1,
             "status": 1, "scheduled_date": 1, "customer_id": 1,
             "customer_name": 1, "service_type": 1, "title": 1,
             "technician_id": 1},
        )
        if not row:
            skipped.append({"job_id": jid, "reason": "not_found"})
            continue
        if row.get("tenant_id") != tid:
            skipped.append({"job_id": jid, "reason": "wrong_tenant"})
            continue
        if row.get("deleted_at"):
            skipped.append({"job_id": jid, "reason": "soft_deleted"})
            continue
        if (row.get("status") or "").lower() in _LOCKED_JOB_STATUSES:
            skipped.append({"job_id": jid, "reason": "locked"})
            continue
        if await _is_job_submit_locked(tid, jid):
            skipped.append({"job_id": jid, "reason": "locked"})
            continue

        old_sd = row.get("scheduled_date")
        try:
            await db.jobs.update_one(
                {"id": jid, "tenant_id": tid},
                {"$set": {"scheduled_date": target_date,
                           "updated_at": now}},
            )
        except Exception as exc:                                  # noqa: BLE001
            logger.warning(
                "[bulk_reschedule] update failed job=%s tenant=%s: %s",
                jid, tid, exc,
            )
            skipped.append({"job_id": jid,
                             "reason": "update_failed",
                             "error": str(exc)[:200]})
            continue

        rescheduled.append(jid)
        # Snapshot for the fanout — we re-read the job doc once per
        # batch below to keep the SAFE-SEND helper's contract
        # identical to the single-job PATCH.
        to_notify.append({
            "job_id": jid, "old_sd": old_sd,
            "new_sd": target_date, "customer_id": row.get("customer_id"),
            "service_type": row.get("service_type"),
            "title": row.get("title"),
        })
        audit_rows.append({
            "id": new_id(),
            "tenant_id": tid,
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "action": "job.reschedule",
            "target_job_id": jid,
            "old_scheduled_date": old_sd,
            "new_scheduled_date": target_date,
            "source": "bulk_reschedule",
            "at": now,
        })

    # Persist audit rows in one batch — non-fatal if it fails.
    if audit_rows:
        try:
            await db.audit_log.insert_many(audit_rows)
        except Exception as exc:                                   # noqa: BLE001
            logger.warning(
                "[bulk_reschedule] audit insert failed: %s", exc,
            )

    # Post-mutation fanout.  Each iteration mirrors the single-job
    # PATCH's reschedule side-effect chain (SAFE-SEND bg task +
    # in-app bell notification).
    if to_notify:
        # Late-import mirrors the single-job PATCH pattern (line
        # 2500 above) — keeps the ``services.notifications_pipeline``
        # import off the router load path.
        import asyncio as _resched_asyncio
        try:
            from services.notifications_pipeline.service_notifications import (
                fire_reschedule_notification,
            )
        except Exception as exc:                                   # noqa: BLE001
            logger.warning(
                "[bulk_reschedule] pipeline import failed: %s", exc,
            )
            fire_reschedule_notification = None                     # type: ignore

        actor_uid = user.get("id")
        for pair in to_notify:
            # In-app bell — synchronous like the single-job path.
            cid = pair.get("customer_id")
            if cid:
                try:
                    await notify_customer(
                        cid, "Service scheduled",
                        f"Your service is scheduled for {target_date}.",
                        job_id=pair["job_id"],
                    )
                except Exception as exc:                           # noqa: BLE001
                    logger.warning(
                        "[bulk_reschedule] notify_customer failed "
                        "job=%s: %s", pair["job_id"], exc,
                    )

            # SAFE-SEND SYSTEM customer notification — bg task per
            # job, matching the single-job PATCH's fire-and-forget
            # posture.  Any bg failure logs but never breaks the
            # response.
            if fire_reschedule_notification is None:
                continue
            _jid = pair["job_id"]
            _old = pair["old_sd"]
            _new = pair["new_sd"]

            async def _bg(_jid=_jid, _old=_old, _new=_new):
                try:
                    fresh = await db.jobs.find_one(
                        {"id": _jid, "tenant_id": tid}, {"_id": 0},
                    )
                    if not fresh:
                        return
                    await fire_reschedule_notification(
                        job=fresh,
                        old_scheduled_date=_old,
                        new_scheduled_date=_new,
                        actor_user_id=actor_uid,
                    )
                except Exception as _bg_exc:                       # noqa: BLE001
                    logger.warning(
                        "[bulk_reschedule] SAFE-SEND bg task "
                        "failed job=%s: %s", _jid, _bg_exc,
                    )

            _resched_asyncio.create_task(_bg())

    return {
        "rescheduled_count": len(rescheduled),
        "rescheduled": rescheduled,
        "skipped": skipped,
        "target_date": target_date,
    }


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
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0, "photos.data": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    if user.get("role") == "technician" and not await is_tech_authorized_on_job(
        user, job, db, tenant["id"],
    ):
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
                     request: Request,
                     user: dict = Depends(get_current_user),
                     tenant: dict = Depends(get_current_tenant)):
    """Auto-start the job timer on GPS arrival (idempotent).

    Feb-2026 · P37a — hardened with 4 gates that all degrade to a
    200 response with a ``reason`` string (never 4xx for business
    misses) so the mobile client can keep polling as the tech moves.
    Reason ordering (short-circuits, most useful first):
      1. feature_disabled     — tenant flag off
      2. consent_required     — tech has no active grant
      3. throttled            — 60s rate limit per (user, job)
      4. out_of_radius        — beyond ``arrival_radius_meters``
      5. job_completed        — already closed
      6. already_running      — idempotent no-op
    A successful start stamps ``timer_start_method="gps_arrival"``
    and writes an audit-log row ``job_timer_auto_start``.
    """
    # Feb-2026 · Job Arrival unify · source whitelist. When the
    # mobile client sends ``source``, only allow the 3 documented
    # values; reject anything else with 400 so the enum stays
    # tight. Absent = legacy behavior (``gps_arrival``).
    _ALLOWED_SOURCES = {"geofence", "manual", "route_start"}
    _resolved_source: str = "gps_arrival"
    if body.source is not None:
        _norm = str(body.source).strip().lower()
        if _norm not in _ALLOWED_SOURCES:
            raise HTTPException(400, {
                "error": "invalid_source",
                "allowed": sorted(_ALLOWED_SOURCES),
                "provided": body.source,
            })
        _resolved_source = _norm

    # Phase O4 · Feb-2026 — Idempotency wiring.  A weekend tech whose
    # mobile queue replays a stale /arrive on reconnect must not
    # re-log the audit row, re-throttle, or re-flip the job status.
    # Cached response wins the whole path.
    from utils_idempotency import replay_or_reserve, store_response
    idem_body = body.dict(exclude_unset=False)
    idem_key, cached = await replay_or_reserve(
        request, tenant["id"], "POST /jobs/{jid}/arrive", idem_body,
    )
    if cached is not None:
        return cached

    async def _sar(_resp: dict) -> dict:
        """store-and-return helper — persists the cached response so a
        mobile replay with the same X-Idempotency-Key short-circuits."""
        if idem_key:
            await store_response(idem_key, "POST /jobs/{jid}/arrive",
                                  tenant["id"], _resp, idem_body)
        return _resp
    from routers.gps_auto_start import (
        DEFAULT_ARRIVAL_RADIUS_M,
        get_arrival_radius_m,
        has_active_consent,
        is_gps_auto_start_enabled,
        rate_limit_check,
    )
    from services.geofence_engine import haversine_m

    # Feb-2026 · P37d — every /arrive outcome now writes an audit row
    # so the ops dashboard can compute the true arrival distribution.
    # Previously only the ``started`` branch logged, which under-
    # counted throttled / out-of-radius / feature-disabled events.
    _radius_hint: Optional[int] = None
    _distance_hint: Optional[float] = None
    _consent_state_hint: str = "not_required"

    async def _log(outcome: str, *, distance_m: Optional[float] = None,
                     radius_m: Optional[int] = None,
                     consent_state: Optional[str] = None,
                     extra: Optional[dict] = None) -> None:
        try:
            payload = {
                "job_id": jid,
                "technician_id": job.get("technician_id"),
                "arrival_lat": body.lat, "arrival_lng": body.lng,
                "site_lat": (body.site_lat if body.site_lat is not None
                                else (job.get("site_lat") or job.get("latitude"))),
                "site_lng": (body.site_lng if body.site_lng is not None
                                else (job.get("site_lng") or job.get("longitude"))),
                "distance_m": (round(distance_m, 1)
                                    if distance_m is not None else None),
                "radius_m": radius_m if radius_m is not None else _radius_hint,
                "accuracy_m": body.accuracy,
                "outcome": outcome,
                "consent_state": consent_state or _consent_state_hint,
                "arrived_at": now_iso(),
            }
            if extra:
                payload.update(extra)
            await db.audit_logs.insert_one({
                "id": new_id(), "tenant_id": tenant["id"],
                "actor_id": user.get("id"), "actor_email": user.get("email"),
                "event": "job_timer_auto_start",
                "at": payload["arrived_at"],
                "payload": payload,
            })
        except Exception as _e:
            logger.warning("[p37] audit-log write failed: %s", _e)

    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0, "photos.data": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    if user.get("role") == "technician" and not await is_tech_authorized_on_job(
        user, job, db, tenant["id"],
    ):
        raise HTTPException(403, "Not your job")

    # P37a Gate 1 — tenant feature flag.
    if not is_gps_auto_start_enabled(tenant):
        await _log("feature_disabled")
        return await _sar({"started": False, "reason": "feature_disabled"})

    # P37a Gate 2 — tech consent (dispatcher / admin roles bypass).
    if user.get("role") == "technician":
        if not await has_active_consent(user["id"], tenant["id"]):
            _consent_state_hint = "missing"
            await _log("consent_required", consent_state="missing")
            return await _sar({"started": False, "reason": "consent_required"})
        _consent_state_hint = "active"

    # P37a Gate 3 — per-(user, job) 60s rate limit.
    if not rate_limit_check(user["id"], jid):
        await _log("throttled")
        return await _sar({"started": False, "reason": "throttled"})

    # P37a Gate 4 — distance check via haversine (meters).
    site_lat = body.site_lat if body.site_lat is not None else (
        job.get("site_lat") or job.get("latitude"))
    site_lng = body.site_lng if body.site_lng is not None else (
        job.get("site_lng") or job.get("longitude"))
    radius_m = get_arrival_radius_m(tenant)
    _radius_hint = radius_m
    distance_m: Optional[float] = None
    if site_lat is not None and site_lng is not None:
        distance_m = haversine_m(float(site_lat), float(site_lng),
                                          float(body.lat), float(body.lng))
        _distance_hint = distance_m
        if distance_m > radius_m:
            await _log("out_of_radius", distance_m=distance_m,
                          radius_m=radius_m)
            return await _sar({"started": False, "reason": "out_of_radius",
                     "distance_m": round(distance_m, 1),
                     "radius_m": radius_m})
    # If site coords are missing (geocode gap) we do NOT block — a job
    # without coords participates in manual start only, and this call
    # is treated as "no radius data → skip radius gate". The audit
    # log below still records ``distance_m: null``.

    # persist geocoded site coords for geofencing/reporting if provided
    site = {}
    if body.site_lat is not None and body.site_lng is not None:
        site = {"site_lat": body.site_lat, "site_lng": body.site_lng,
                 "latitude": body.site_lat, "longitude": body.site_lng}
    if job.get("timer_started_at"):
        if site:
            await db.jobs.update_one({"id": jid, "tenant_id": tenant["id"]}, {"$set": site})
        await _log("already_running", distance_m=distance_m,
                      radius_m=radius_m)
        # Feb-2026 · alias for mobile; both keys emit the same value.
        return await _sar({"started": True, "already_running": True,
                              "already_arrived": True,
                              "timer_started_at": job["timer_started_at"]})
    if job.get("status") == "completed":
        await _log("job_completed", distance_m=distance_m,
                      radius_m=radius_m)
        return await _sar({"started": False, "reason": "job_completed"})
    started = now_iso()
    upd = {"timer_started_at": started, "timer_start_method": _resolved_source,
              "arrival_lat": body.lat, "arrival_lng": body.lng, **site}
    # Feb-2026 · P37c bug-fix — snapshot the pre-arrival status when
    # /arrive auto-advances to ``in_progress`` so /timer/undo-start
    # can restore it. Only snapshot on the actual flip (not on the
    # no-op paths above, which return early). Undo consults this
    # field and unsets it after restore so nothing lingers on the
    # doc past a single arrive → undo cycle.
    if job.get("status") in (None, "pending", "requested", "scheduled"):
        upd["pre_arrival_status"] = job.get("status") or "scheduled"
        upd["status"] = "in_progress"
    await db.jobs.update_one({"id": jid, "tenant_id": tenant["id"]}, {"$set": upd})

    # P37a — audit log breadcrumb (P37d — extended to log outcome=started).
    await _log("started", distance_m=distance_m, radius_m=radius_m)

    # Feb-2026 · Job Timers dashboard phase — upsert an open
    # ``job_timers`` row so the /job-timers report picks up the
    # arrival. Idempotent: replaying ``/arrive`` (mobile queue
    # replay, retries) never spawns duplicates. Non-fatal — a
    # bookkeeping error MUST NOT break the arrival flow.
    try:
        from routers.job_timers import auto_start_timer_on_arrival
        await auto_start_timer_on_arrival(
            job_id=jid, tenant_id=tenant["id"],
            tech_id=job.get("technician_id"),
            customer_id=job.get("customer_id"),
            started_at=started,
        )
    except Exception as _jt_exc:                                # noqa: BLE001
        logger.warning("[job-timers] arrival auto-start failed: %s",
                        _jt_exc)

    return await _sar({"started": True, "already_running": False,
              # Feb-2026 · alias for mobile; both keys emit the same value.
              "already_arrived": False,
              "timer_started_at": started,
              "distance_m": round(distance_m, 1) if distance_m is not None else None,
              "radius_m": radius_m})


# ═════════════════════════════════════════════════════════════════
# Feb-2026 · P37c — undo a GPS-arrival start within the grace window.
# Called by the mobile undo banner (30s local push) and by dispatch
# fallback UIs. Server-side enforces the 60s wall so we never trust
# a stale client clock.
#
# Feb-2026 · P37c bug-fix — the grace window is 100% server-authoritative.
# The request body is intentionally empty; any client-supplied
# ``within_seconds`` is ignored (Pydantic default ``extra='ignore'``
# drops the field silently). The 60s ceiling is a module-level
# constant so accidental drift can't happen.
# ═════════════════════════════════════════════════════════════════
_P37C_UNDO_GRACE_S = 60


class JobTimerUndoIn(BaseModel):
    """Empty body — the endpoint takes no client input. Kept as a model
    so FastAPI still parses the JSON body if one is sent."""
    pass


@router.post("/jobs/{jid}/timer/undo-start")
async def undo_job_timer_start(jid: str, body: JobTimerUndoIn,
                                     request: Request,
                                     user: dict = Depends(get_current_user),
                                     tenant: dict = Depends(get_current_tenant)):
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0, "photos.data": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    if user.get("role") == "technician" and not await is_tech_authorized_on_job(
        user, job, db, tenant["id"],
    ):
        raise HTTPException(403, "Not your job")
    started_iso = job.get("timer_started_at")
    if not started_iso:
        raise HTTPException(400, {"detail": "no_active_timer",
                                       "message": "No active timer to undo."})
    if job.get("timer_stopped_at"):
        raise HTTPException(400, {"detail": "timer_already_stopped",
                                       "message": "Cannot undo a stopped timer."})
    try:
        from datetime import datetime as _dt, timezone as _tz
        _st = _dt.fromisoformat(str(started_iso).replace("Z", "+00:00"))
        _now = _dt.now(tz=_tz.utc)
        elapsed = int(max(0, (_now - _st).total_seconds()))
    except Exception:
        raise HTTPException(400, "Timer start time malformed")
    # Feb-2026 · P37c bug-fix — grace is a server constant. Ignore
    # anything a client might have tried to pass.
    grace = _P37C_UNDO_GRACE_S
    if elapsed > grace:
        raise HTTPException(
            status_code=400,
            detail={"detail": "outside_grace_window",
                      "message": f"Timer started {elapsed}s ago; grace window is {grace}s.",
                      "elapsed_seconds": elapsed, "grace_seconds": grace},
        )
    # Feb-2026 · P37c bug-fix — restore status alongside the timer
    # unset. Only restore when the row is still in the auto-advanced
    # ``in_progress`` state AND a pre-arrival snapshot exists; a
    # dispatcher flipping the row to ``completed`` inside the grace
    # window is honored (do not clobber operator decisions).
    _pre = job.get("pre_arrival_status")
    _cur = job.get("status")
    _unset = {"timer_started_at": "", "timer_start_method": "",
                 "arrival_lat": "", "arrival_lng": "",
                 "pre_arrival_status": ""}
    _set: dict = {"updated_at": now_iso()}
    if _cur == "in_progress" and _pre:
        _set["status"] = _pre
    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"]},
        {"$unset": _unset, "$set": _set},
    )
    try:
        await db.audit_logs.insert_one({
            "id": new_id(), "tenant_id": tenant["id"],
            "actor_id": user.get("id"), "actor_email": user.get("email"),
            "event": "job_timer_undo_start",
            "at": now_iso(),
            "payload": {"job_id": jid, "elapsed_seconds": elapsed,
                            "prev_method": job.get("timer_start_method"),
                            "prev_started_at": started_iso,
                            "restored_status": _set.get("status"),
                            "pre_arrival_status": _pre},
        })
    except Exception as _e:
        logger.warning("[p37c] audit-log write failed: %s", _e)
    return {"undone": True, "elapsed_seconds": elapsed,
              "restored_status": _set.get("status")}


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
    jobs = await db.jobs.find(query, {"_id": 0, "photos.data": 0}).to_list(5000)
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
    """Weekly pool-service aggregation, split by ``work_class``.

    POOL-A · Feb-2026 — landscape-industry jobs are filtered out via
    ``derive_industry_for_job(job, tenant, strict_mode=True) == "pool"``.
    Jobs whose industry doesn't classify as ``"pool"`` (landscape,
    HVAC, cleaning, other, unknown) never enter any bucket — the
    Pool Service Report is pool-only.

    POOL-B · Feb-2026 — the surviving pool jobs are split by
    ``work_class`` into three buckets:
      * ``pools_serviced`` — ``work_class == "service"``.
      * ``repairs_completed`` — ``work_class == "repair"``.
      * ``other`` — any other value (``None``, missing, or an
        unrecognised string like ``"inspection"``).  These are
        tracked but never silently counted as ``service``; when
        ``other`` exceeds 10 % of the completed pool volume for the
        period we emit a WARN so ops can spot data-integrity drift.

    ``skipped`` (existing) still counts every pool job whose status
    is in :data:`SKIPPED_STATUSES` regardless of ``work_class`` —
    a skipped visit isn't yet a completed service or repair.

    Response shape (POOL-B keeps the pre-B legacy keys for
    backward-compatibility and adds spec-preferred + brief-preferred
    fields side-by-side):

    .. code-block:: python

        {
          # Legacy — preserved verbatim
          "week_start": "YYYY-MM-DD",
          "week_end":   "YYYY-MM-DD",
          "total_completed": int,   # NEW SEMANTIC: pools_serviced only
                                     # (per SPEC §200 — a repair no
                                     # longer counts here)
          "total_skipped": int,
          "rows": [ tech-row, ... ],  # concat of maintenance+repairs+other

          # Brief-compatible additions
          "period": {"start": ..., "end": ...},
          "summary": {
            "total_pool_visits": int,     # = maintenance + repairs + other
            "maintenance_visits": int,    # work_class=service
            "repair_visits":       int,   # work_class=repair
            "other_visits":        int,   # work_class unknown
          },
          "maintenance": [ tech-row filtered to pools_serviced>0 ],
          "repairs":     [ tech-row filtered to repairs_completed>0 ],
          "other":       [ tech-row filtered to other>0 ],
          "visits":      [ maintenance + repairs + other concat ],

          # SPEC §210-228 preferred additions
          "totals": {
            "pools_serviced":    int,
            "repairs_completed": int,
          },
          "by_technician": [
            {
              "technician_id":     str,
              "technician_name":   str,
              "technician_active": bool,
              "pools_serviced":    int,
              "repairs_completed": int,
              "other":             int,
              "skipped":           int,
              # legacy alias — same value as pools_serviced so the old
              # FE reads the SPEC-correct number (repair visits no
              # longer inflate the "serviced" count).
              "completed":         int,
            }, ...
          ],
        }

    New callers should read ``by_technician`` / ``totals`` (spec) or
    ``summary`` / ``maintenance`` / ``repairs`` / ``other`` (brief).
    Legacy callers keep the ``rows`` / ``total_completed`` /
    ``total_skipped`` view; the ``completed`` semantic is intentionally
    narrowed to service-only per the SPEC.
    """
    if date_from and date_to:
        week_start, week_end = date_from, date_to
    else:
        week_start, week_end = _service_week(date_from or date_to)

    # POOL-A · Feb-2026 — Industry filter.
    # Fetch the tenant once so ``derive_industry_for_job`` has the
    # (strict-mode) context it needs to correctly bucket a job with
    # an explicit ``industry`` / ``checklist_industry`` override
    # even when ``service_type`` doesn't carry an obvious keyword.
    # Defensive read — a Mongo hiccup / test double without a
    # ``.tenants`` attribute falls through to an empty dict so the
    # strict-mode classifier still runs on keyword-only signals.
    try:
        tenant_doc = await db.tenants.find_one(
            {"id": tenant_id},
            {"_id": 0, "id": 1, "industries": 1, "industry": 1},
        ) or {"id": tenant_id}
    except Exception:  # noqa: BLE001
        tenant_doc = {"id": tenant_id}

    date_range = {"$gte": week_start, "$lte": week_end}
    from utils import not_deleted_filter as _nd
    # POOL-A · projection extended to carry every field the industry
    # classifier reads (see ``routers.industry_checklists.derive_
    # industry_for_job``): ``service_type`` / ``job_type`` / ``title``
    # for keyword match + ``industry`` / ``checklist_industry`` for
    # explicit override. Without the projection extend, every job
    # arrived at the classifier with those fields missing and the
    # classifier fell through to the (now-suppressed-in-strict-mode)
    # tenant-industry default, defeating the whole filter.
    # POOL-B · Feb-2026 — projection extended to include
    # ``work_class`` so the service/repair split has the raw value
    # per-job (we intentionally DO NOT go through ``infer_work_class``
    # here — the SPEC ruling §274 requires unknown / null values to
    # bucket into ``other`` rather than default to ``"service"``).
    jobs = await db.jobs.find(
        {"tenant_id": tenant_id, "scheduled_date": date_range, **_nd()},
        {"_id": 0, "technician_id": 1, "technician_name": 1,
         "status": 1, "scheduled_date": 1,
         "service_type": 1, "job_type": 1, "title": 1,
         "industry": 1, "checklist_industry": 1,
         "work_class": 1},
    ).to_list(10000)

    # POOL-A · industry filter — strict mode so a job with no
    # explicit industry AND no keyword hit falls to ``"other"``
    # (excluded) rather than silently inheriting the tenant's
    # primary industry. Exclusion path also covers landscape,
    # HVAC, cleaning, etc. — the Pool Service Report is a pool-
    # only surface.
    from routers.industry_checklists import (
        derive_industry_for_job as _derive_industry,
    )
    jobs = [
        j for j in jobs
        if _derive_industry(j, tenant_doc, strict_mode=True) == "pool"
    ]

    tids = list({j.get("technician_id") for j in jobs if j.get("technician_id")})
    from services.service_report_view import resolve_technicians
    tmap = await resolve_technicians(db, tenant_id, tids)

    # Feb 2026 · Effective-ID bucketing. Jobs with a raw
    # ``technician_id`` bucket on that id directly. Jobs with only a
    # stored ``technician_name`` (no id) get a best-effort ID rescue
    # via case-insensitive ``db.users.name`` lookup — unique match
    # → bucket by resolved id; ambiguous/no match → bucket under
    # "unassigned". Prevents the "Ethan Smith duplicate" scenario
    # where two id shapes for the same tech end up in different
    # buckets.
    name_to_uid: Dict[str, Optional[str]] = {}
    unique_name_candidates = list({
        (j.get("technician_name") or "").strip()
        for j in jobs
        if not j.get("technician_id")
            and (j.get("technician_name") or "").strip()
    })
    if unique_name_candidates:
        # Case-insensitive lookup — one query per unique name is
        # cheap for the small (< dozens) universe. We stash the
        # tech's technician_id on the user doc when present (that's
        # the canonical bucket key); fall back to users.id.
        for nm in unique_name_candidates:
            escaped = re.escape(nm)
            matches = await db.users.find(
                {"tenant_id": tenant_id,
                  "name": {"$regex": f"^{escaped}$", "$options": "i"}},
                {"_id": 0, "id": 1, "technician_id": 1},
            ).to_list(3)
            if len(matches) == 1:
                m = matches[0]
                # Prefer users.technician_id (canonical bucket) so
                # jobs that later got an id-shape stamp bucket
                # into the same row.
                name_to_uid[nm] = m.get("technician_id") or m.get("id")
                # Warm the rich tmap so the row renders with the
                # correct active-flag too.
                if name_to_uid[nm] and name_to_uid[nm] not in tmap:
                    _one = await resolve_technicians(
                        db, tenant_id, [name_to_uid[nm]])
                    tmap.update(_one)
            elif len(matches) > 1:
                logger.warning(
                    "[pool-service] ambiguous tech name %r — %d "
                    "matches on tenant %s; bucketing under Unassigned",
                    nm, len(matches), tenant_id,
                )
                name_to_uid[nm] = None   # explicit sentinel
            else:
                # No user match — leave in Unassigned bucket rather
                # than invent an ID.
                name_to_uid[nm] = None

    # Denormalized ``technician_name`` cache is a last-resort fallback
    # for old jobs whose ``technician_id`` no longer resolves in any
    # of the resolver cascade rungs.
    cached_name_by_tid: dict = {}
    for j in jobs:
        tid_j = j.get("technician_id")
        nm = (j.get("technician_name") or "").strip()
        if tid_j and nm and tid_j not in cached_name_by_tid:
            cached_name_by_tid[tid_j] = nm

    agg: dict = {}
    unassigned = {"pools_serviced": 0, "repairs_completed": 0,
                   "other": 0, "skipped": 0}
    # POOL-B · Feb-2026 — data-integrity counter.  When the ``other``
    # bucket exceeds 10 % of the completed pool volume for the
    # period we emit a WARN so ops can see legacy / mis-classified
    # rows drift into the report.
    _unknown_wc_period = 0
    _completed_pool_period = 0
    for j in jobs:
        tid = j.get("technician_id")
        # Feb 2026 · Effective-ID rescue for name-only jobs.
        if not tid:
            nm = (j.get("technician_name") or "").strip()
            if nm:
                tid = name_to_uid.get(nm)
        status = (j.get("status") or "").lower()
        # POOL-B · read the raw ``work_class`` value — DO NOT call
        # ``infer_work_class`` here.  Per SPEC §274 unknown / null
        # values bucket to ``other``, not to service-by-default.
        raw_wc = j.get("work_class")
        wc = str(raw_wc).strip().lower() if isinstance(raw_wc, str) else None
        bucket_key = None
        if status == "completed":
            _completed_pool_period += 1
            if wc == "service":
                bucket_key = "pools_serviced"
            elif wc == "repair":
                bucket_key = "repairs_completed"
            else:
                bucket_key = "other"
                _unknown_wc_period += 1
        elif status in SKIPPED_STATUSES:
            bucket_key = "skipped"
        else:
            continue
        if not tid:
            unassigned[bucket_key] += 1
            continue
        a = agg.setdefault(tid, {"pools_serviced": 0,
                                  "repairs_completed": 0,
                                  "other": 0, "skipped": 0})
        a[bucket_key] += 1

    # POOL-B · WARN when >10 % of completed pool jobs land in
    # ``other`` — data-integrity signal per SPEC §274-278.
    if _completed_pool_period > 0:
        _unknown_pct = _unknown_wc_period / _completed_pool_period
        if _unknown_pct > 0.10:
            logger.warning(
                "[pool-service] work_class=unknown/null count %d / %d "
                "(%.1f%%) exceeds 10%% for tenant=%s week=%s..%s — "
                "data-integrity check recommended",
                _unknown_wc_period, _completed_pool_period,
                _unknown_pct * 100, tenant_id, week_start, week_end,
            )

    rows = []
    for tid, a in agg.items():
        info = tmap.get(tid) or {}
        rows.append({
            "technician_id": tid,
            "technician_name": info.get("name")
                                 or cached_name_by_tid.get(tid)
                                 or tid,
            "technician_active": info.get("active", True),
            "pools_serviced":    a["pools_serviced"],
            "repairs_completed": a["repairs_completed"],
            "other":             a["other"],
            "skipped":           a["skipped"],
            # Legacy alias — the SPEC narrows ``completed`` to
            # ``pools_serviced`` so old FE consumers read the
            # service-only count (repairs no longer inflate it).
            "completed":         a["pools_serviced"],
        })
    # Surface the "Unassigned" bucket at the tail so it doesn't
    # crowd the top of the report but is still visible.
    if (unassigned["pools_serviced"] or unassigned["repairs_completed"]
            or unassigned["other"] or unassigned["skipped"]):
        rows.append({
            "technician_id": None,
            "technician_name": "Unassigned",
            "technician_active": True,
            "pools_serviced":    unassigned["pools_serviced"],
            "repairs_completed": unassigned["repairs_completed"],
            "other":             unassigned["other"],
            "skipped":           unassigned["skipped"],
            "completed":         unassigned["pools_serviced"],
        })
    rows.sort(key=lambda r: (r["technician_id"] is None,
                              -r["pools_serviced"],
                              -r["repairs_completed"]))

    # POOL-B · slice the rows into three brief-compatible buckets.
    # ``maintenance`` = techs with ≥1 pools_serviced, etc.  A tech
    # with pools_serviced=2, repairs_completed=1 appears in BOTH
    # the ``maintenance`` and ``repairs`` arrays — same underlying
    # row shape, filtered by which counter is non-zero.
    maintenance_rows = [r for r in rows if r["pools_serviced"] > 0]
    repairs_rows     = [r for r in rows if r["repairs_completed"] > 0]
    other_rows       = [r for r in rows if r["other"] > 0]

    total_pools_serviced    = sum(r["pools_serviced"] for r in rows)
    total_repairs_completed = sum(r["repairs_completed"] for r in rows)
    total_other             = sum(r["other"] for r in rows)
    total_skipped           = sum(r["skipped"] for r in rows)

    return {
        # ─── Legacy fields — preserved shape ─────────────────────
        "week_start": week_start,
        "week_end":   week_end,
        # NEW SEMANTIC per SPEC §200 — legacy ``total_completed``
        # now reflects service-only visits (a repair no longer
        # inflates it).  Old FE that reads this reads the correct
        # "pools serviced" count.
        "total_completed": total_pools_serviced,
        "total_skipped":   total_skipped,
        "rows": rows,

        # ─── Brief-compatible additions ──────────────────────────
        "period": {"start": week_start, "end": week_end},
        "summary": {
            "total_pool_visits": (total_pools_serviced
                                    + total_repairs_completed
                                    + total_other),
            "maintenance_visits": total_pools_serviced,
            "repair_visits":       total_repairs_completed,
            "other_visits":        total_other,
        },
        "maintenance": maintenance_rows,
        "repairs":     repairs_rows,
        "other":       other_rows,
        # Legacy top-level "visits" key populated with all three
        # concatenated for backward-compat with any consumer we
        # haven't found yet (brief mandate).
        "visits": maintenance_rows + repairs_rows + other_rows,

        # ─── SPEC §210-228 preferred additions ───────────────────
        "totals": {
            "pools_serviced":    total_pools_serviced,
            "repairs_completed": total_repairs_completed,
        },
        "by_technician": rows,
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
    # Phase O4 · Feb-2026 — added ``client_uuid`` to the fingerprint so
    # the mobile app can mint an id offline; if the row is already on
    # the job we return the existing job doc without a second upload.
    from utils_idempotency import replay_or_reserve, store_response
    idem_body = {"data": body.data, "label": body.label or "photo",
                  "client_uuid": body.client_uuid}
    idem_key, cached = await replay_or_reserve(
        request, tenant["id"], "POST /jobs/{jid}/photos", idem_body,
    )
    if cached is not None:
        return cached
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"photos.data": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    if user.get("role") == "technician":
        # F1 · crew-aware tech gate — see services/authz.py.
        if not await is_tech_authorized_on_job(user, job, db, tenant["id"]):
            raise HTTPException(403, "Not your job")
    # Phase O4 · Feb-2026 — Client-UUID lookup.  If the mobile app
    # minted an id and already synced this photo, return the existing
    # job doc verbatim — no duplicate row, no cap bump.
    if body.client_uuid:
        _existing_ids = {p.get("id") for p in (job.get("photos") or [])
                          if isinstance(p, dict)}
        if body.client_uuid in _existing_ids:
            resp_existing = await db.jobs.find_one(
                {"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
            if idem_key:
                await store_response(idem_key, "POST /jobs/{jid}/photos",
                                      tenant["id"], resp_existing, idem_body)
            return resp_existing
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
    photo = {"id": body.client_uuid or new_id(),
              "data": body.data, "label": body.label or "photo",
              "created_at": now_iso()}
    if body.client_uuid:
        photo["client_uuid"] = body.client_uuid
    # ─── Feb-2026 · Upload guardrails ───
    # Reject non-image MIMEs (415) and oversize payloads (413) up
    # front so we don't waste S3 / derivative-generation work on
    # something we're going to throw away anyway. Both checks are
    # env-tunable via ``PHOTOS_ALLOW_HEIC`` +
    # ``PHOTOS_MAX_UPLOAD_BYTES`` (see
    # ``services.photos_derivatives`` for defaults).
    try:
        from services.aws_s3.photos import decode_data_url
        _blob, _mime = decode_data_url(body.data)
    except Exception as _decode_exc:
        raise HTTPException(status_code=400, detail={
            "code": "photo_decode_failed",
            "message": f"could not decode photo payload: {_decode_exc}",
        })
    try:
        from services.photos_derivatives import (
            is_allowed_mime, max_upload_bytes,
        )
        if not is_allowed_mime(_mime):
            logger.warning(
                "[photos-upload] rejected mime tenant=%s user=%s job=%s mime=%s",
                tenant.get("id"), user.get("id"), jid, _mime,
            )
            raise HTTPException(status_code=415, detail={
                "code": "photo_unsupported_mime",
                "mime":  _mime,
                "allowed": sorted(list(__import__('services.photos_derivatives',
                                                    fromlist=['allowed_mimes']).allowed_mimes())),
            })
        _cap = max_upload_bytes()
        if len(_blob) > _cap:
            logger.warning(
                "[photos-upload] rejected size tenant=%s user=%s job=%s bytes=%s cap=%s",
                tenant.get("id"), user.get("id"), jid, len(_blob), _cap,
            )
            raise HTTPException(status_code=413, detail={
                "code": "photo_too_large",
                "max_bytes": _cap,
                "actual_bytes": len(_blob),
            })
    except HTTPException:
        raise
    except Exception as _guard_exc:
        # Guardrail helper misbehaved — log and fall through to the
        # existing write path so a helper bug can't 500 uploads.
        logger.warning("[photos-upload] guardrail soft-fail err=%s", _guard_exc)
    # ─── Feb-2026 · Photos-in-S3 Phase 1 · dual-write ───
    # Best-effort upload to S3 alongside the existing base64 DB
    # write. When ``PHOTOS_S3_ENABLED=false`` or creds missing,
    # the helper is a safe no-op and returns ``None`` — the
    # base64 DB path continues unchanged. When enabled, we stamp
    # ``photos[].s3_key`` on the doc so the read path can serve a
    # presigned URL. Never raises; failures are logged and swallowed
    # so a hiccuped S3 API never blocks the photo save.
    # See /app/memory/FEATURE_PHOTOS_S3_PHASE1.md.
    #
    # Feb-2026 · Photos-in-S3 base64-skip (post-Phase-1) ───
    # When the flag is ON AND all three S3 puts succeed (original +
    # thumb + preview), we DROP the base64 ``photos[].data`` blob
    # so we don't dual-store the payload in Mongo. If ANY put fails,
    # we retain ``data`` as a durability fallback and emit an audit
    # row (event=``photos.s3_upload_partial_failure``) so ops can
    # spot chronic S3 flakiness. Read path is unchanged — it already
    # prefers ``s3_key`` and falls back to ``data``.
    # See /app/memory/FEATURE_PHOTOS_S3_BASE64_SKIP.md.
    _s3_key: Optional[str] = None
    _s3_flag_on: bool = False
    _s3_puts_succeeded: list = []
    _s3_puts_failed: list = []
    _s3_error_class: Optional[str] = None
    try:
        from services.aws_s3 import photos as _s3mod
        _s3_flag_on = _s3mod._is_configured(_s3mod._cfg())
    except Exception:
        _s3_flag_on = False
    try:
        from services.aws_s3.photos import upload_photo
        _s3_key = upload_photo(
            tenant_id=tenant["id"], job_id=jid, photo_id=photo["id"],
            blob=_blob, mime=_mime,
        )
        if _s3_key:
            photo["s3_key"] = _s3_key
            photo["s3_mime"] = _mime
            _s3_puts_succeeded.append("original")
        elif _s3_flag_on:
            _s3_puts_failed.append("original")
    except Exception as _s3_exc:
        logger.warning(
            "[photos-s3] dual-write soft-fail tenant=%s job=%s photo=%s err=%s",
            tenant.get("id"), jid, photo["id"], _s3_exc,
        )
        if _s3_flag_on:
            _s3_puts_failed.append("original")
            _s3_error_class = type(_s3_exc).__name__
    # ─── Feb-2026 · Thumbnails + preview derivatives ───
    # Generate JPEG derivatives via Pillow (EXIF stripped). Never
    # blocks the upload — if Pillow can't parse or the S3 sibling
    # put fails, the doc still saves with only the original.
    try:
        from services.photos_derivatives import generate_derivatives
        _derivs = generate_derivatives(_blob)
        if _derivs is not None:
            _thumb_bytes, _preview_bytes = _derivs
            if _s3_key:
                # Flag-ON path — upload derivatives as sibling keys.
                from services.aws_s3.photos import (
                    derivative_key, upload_blob_at_key,
                )
                _tk = derivative_key(_s3_key, "thumb")
                _pk = derivative_key(_s3_key, "preview")
                if upload_blob_at_key(_tk, _thumb_bytes, "image/jpeg"):
                    photo["s3_thumb_key"] = _tk
                    _s3_puts_succeeded.append("thumb")
                else:
                    _s3_puts_failed.append("thumb")
                if upload_blob_at_key(_pk, _preview_bytes, "image/jpeg"):
                    photo["s3_preview_key"] = _pk
                    _s3_puts_succeeded.append("preview")
                else:
                    _s3_puts_failed.append("preview")
            else:
                # Flag-OFF path — embed base64 derivatives directly
                # on the doc so list-view thumbnails keep working
                # without an object store.
                import base64 as _b64
                photo["thumb"] = ("data:image/jpeg;base64,"
                                    + _b64.b64encode(_thumb_bytes).decode())
                photo["preview"] = ("data:image/jpeg;base64,"
                                      + _b64.b64encode(_preview_bytes).decode())
                if _s3_flag_on:
                    # Flag ON but original PUT failed → mark thumb +
                    # preview as failed too so the audit row reflects
                    # the full 3-way failure and the base64-skip gate
                    # cannot fire on the partial-fallback shape.
                    _s3_puts_failed.extend(["thumb", "preview"])
        elif _s3_flag_on and _s3_key:
            # Flag on but Pillow couldn't produce derivatives — we
            # can't fully commit to S3-only for this row. Mark
            # thumb+preview as failed so the base64 fallback fires
            # below and an audit row surfaces the derivative gap.
            _s3_puts_failed.extend(["thumb", "preview"])
    except Exception as _deriv_exc:
        logger.warning(
            "[photos-deriv] soft-fail tenant=%s job=%s photo=%s err=%s",
            tenant.get("id"), jid, photo["id"], _deriv_exc,
        )
        if _s3_flag_on and _s3_key:
            _s3_puts_failed.extend(
                [x for x in ("thumb", "preview")
                 if x not in _s3_puts_succeeded and x not in _s3_puts_failed]
            )
            if _s3_error_class is None:
                _s3_error_class = type(_deriv_exc).__name__
    # ─── Base64-skip decision ───
    # Flag ON + all three S3 puts succeeded → drop the base64 blob
    # (S3 is the sole store of the payload). Flag OFF, or ANY S3
    # put failed → keep ``data`` intact for durability, and if S3
    # was expected to work, emit an audit row for observability.
    if _s3_flag_on and not _s3_puts_failed and \
            len(_s3_puts_succeeded) == 3:
        photo.pop("data", None)
    elif _s3_flag_on and _s3_puts_failed:
        try:
            await db.audit_logs.insert_one({
                "id": new_id(), "tenant_id": tenant["id"],
                "actor_id": user.get("id"),
                "actor_email": user.get("email"),
                "event": "photos.s3_upload_partial_failure",
                "at": now_iso(),
                "payload": {
                    "customer_id": (job.get("customer_id")
                                     if isinstance(job, dict) else None),
                    "job_id": jid,
                    "photo_id": photo["id"],
                    "error_class": _s3_error_class,
                    "s3_puts_succeeded": list(_s3_puts_succeeded),
                    "s3_puts_failed": list(_s3_puts_failed),
                },
            })
        except Exception as _audit_exc:
            logger.warning(
                "[photos-s3] audit-log soft-fail tenant=%s job=%s photo=%s err=%s",
                tenant.get("id"), jid, photo["id"], _audit_exc,
            )
    await db.jobs.update_one({"id": jid, "tenant_id": tenant["id"]}, {"$push": {"photos": photo}})
    # CLOSED-JOB-EDIT-UNLOCK · Feb-2026 — audit-row parity for
    # photo adds on COMPLETED jobs.  The ``patch_job_edit_window``
    # path already writes a ``db.job_edits`` row on every post-
    # completion field edit; photos were historically silent.
    # Writing a parallel audit row with the shared row shape (plus
    # a dedicated ``event="closed_job_photo_add"`` discriminator)
    # keeps the Communication Timeline in sync so staff can audit
    # which photos were added AFTER completion.  Open jobs stay
    # silent to avoid double-logging routine work.
    if (job.get("status") or "").lower() == "completed":
        try:
            await db.job_edits.insert_one({
                "id": new_id(),
                "tenant_id": tenant["id"],
                "job_id": jid,
                "event": "closed_job_photo_add",
                "edited_by": user.get("id"),
                "edited_by_name": user.get("name") or user.get("email"),
                "edited_by_role": (user.get("role") or "").lower(),
                "edited_at": now_iso(),
                "changes": {
                    "photos": {"before": None,
                                "after": {"id": photo["id"],
                                            "label": photo.get("label")}},
                },
                "reason": None,
                "source": "web",
            })
        except Exception as _audit_exc:  # pragma: no cover - defensive
            logger.warning(
                "[closed-job-edit] photo-add audit soft-fail "
                "tenant=%s job=%s photo=%s err=%s",
                tenant.get("id"), jid, photo.get("id"), _audit_exc,
            )
    resp = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})
    # Feb-2026 · Photos-in-S3 Phase 1 — strip s3_key from the
    # wire so the storage backend key never leaks to clients.
    try:
        from services.jobs_slim_photos import strip_s3_metadata_from_photos
        strip_s3_metadata_from_photos(resp)
    except Exception:
        pass
    # JOB-PHOTOS-FIX · Feb-2026 — mirror the detail-endpoint
    # ``photos[].url`` injection on the upload response so the FE
    # grid renders the new row immediately without a reload.
    try:
        from services.jobs_slim_photos import inject_photo_url_on_doc
        inject_photo_url_on_doc(resp, jid)
    except Exception:
        pass
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
    # ─── Feb-2026 · Photos-in-S3 Phase 1 · dual-delete ───
    # Capture ``s3_key`` (if present) BEFORE the ``$pull`` so we
    # can best-effort delete the S3 object after the DB unlink. If
    # the S3 delete fails, log — do NOT block the DB delete or the
    # 200 response. Orphaned S3 objects are a garbage-collector
    # problem, not a UX problem.
    _s3_key_to_delete = None
    try:
        _existing = await db.jobs.find_one(
            {"id": jid, "tenant_id": tenant["id"]},
            {"_id": 0, "photos": 1},
        )
        if _existing:
            _p = next(
                (p for p in (_existing.get("photos") or [])
                 if isinstance(p, dict) and p.get("id") == pid),
                None,
            )
            if _p and _p.get("s3_key"):
                _s3_key_to_delete = _p["s3_key"]
    except Exception as _exc:
        logger.warning(
            "[photos-s3] pre-delete lookup soft-fail jid=%s pid=%s err=%s",
            jid, pid, _exc,
        )
    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"]}, {"$pull": {"photos": {"id": pid}}}
    )
    # CLOSED-JOB-EDIT-UNLOCK · Feb-2026 — audit-row parity for
    # photo deletes on COMPLETED jobs. Fetching the parent job
    # AFTER the pull so we can read the authoritative status
    # without a race against a concurrent transition.  Audit row
    # fires only if the status is completed — open jobs stay
    # silent to avoid double-logging routine work.
    _parent_after_pull = await db.jobs.find_one(
        {"id": jid, "tenant_id": tenant["id"]},
        {"_id": 0, "status": 1},
    )
    if _parent_after_pull and (
        (_parent_after_pull.get("status") or "").lower() == "completed"
    ):
        try:
            await db.job_edits.insert_one({
                "id": new_id(),
                "tenant_id": tenant["id"],
                "job_id": jid,
                "event": "closed_job_photo_delete",
                "edited_by": user.get("id"),
                "edited_by_name": user.get("name") or user.get("email"),
                "edited_by_role": (user.get("role") or "").lower(),
                "edited_at": now_iso(),
                "changes": {
                    "photos": {"before": {"id": pid}, "after": None},
                },
                "reason": None,
                "source": "web",
            })
        except Exception as _audit_exc:  # pragma: no cover - defensive
            logger.warning(
                "[closed-job-edit] photo-delete audit soft-fail "
                "tenant=%s job=%s photo=%s err=%s",
                tenant.get("id"), jid, pid, _audit_exc,
            )
    if _s3_key_to_delete:
        try:
            from services.aws_s3.photos import delete_photo as _s3_delete
            _s3_delete(_s3_key_to_delete)
        except Exception as _s3_exc:
            logger.warning(
                "[photos-s3] delete soft-fail key=%s err=%s",
                _s3_key_to_delete, _s3_exc,
            )
    return await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0})


# ----------------------- Service Issues -----------------------
@router.post("/jobs/{jid}/issues")
async def add_service_issue(jid: str, body: ServiceIssueIn,
                            request: Request,
                            user: dict = Depends(get_current_user),
                            tenant: dict = Depends(get_current_tenant)):
    # Phase O4 · Feb-2026 — Idempotency wiring + Client-UUID acceptance.
    # A tech marking a leaking-valve issue offline gets a UUID minted
    # locally; when the queue drains we check for an existing row with
    # that id on ``jobs.service_issues[]`` and short-circuit.  The
    # ``X-Idempotency-Key`` header protects against a duplicate POST
    # from the same replay attempt (different body → 200 with
    # body-mismatch marker so the client can surface it).
    from utils_idempotency import replay_or_reserve, store_response
    idem_body = body.dict(exclude_unset=False)
    idem_key, cached = await replay_or_reserve(
        request, tenant["id"], "POST /jobs/{jid}/issues", idem_body,
    )
    if cached is not None:
        return cached
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"photos.data": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    if user.get("role") == "technician" and not await is_tech_authorized_on_job(
        user, job, db, tenant["id"],
    ):
        raise HTTPException(403, "Not your job")
    # Phase O4 · Feb-2026 — Client-UUID lookup.  If the mobile app
    # minted an id and already synced this issue, return the existing
    # job doc verbatim — no duplicate row, no re-notify.
    if body.client_uuid:
        _existing_ids = {i.get("id") for i in (job.get("service_issues") or [])
                          if isinstance(i, dict)}
        if body.client_uuid in _existing_ids:
            resp_existing = with_field_report(
                await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0, "photos.data": 0})
            )
            if idem_key:
                await store_response(idem_key, "POST /jobs/{jid}/issues",
                                      tenant["id"], resp_existing, idem_body)
            return resp_existing
    issue = {
        "id": body.client_uuid or new_id(),
        "description": body.description, "cost": body.cost,
        "photo": body.photo, "status": "open", "reported_by": user.get("name", "Staff"),
        "created_at": now_iso(), "approved_at": None,
    }
    # Track the client-minted id (if any) so a subsequent request can
    # match on it even if some later flow rewrites the ``id`` field.
    if body.client_uuid:
        issue["client_uuid"] = body.client_uuid
    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"]}, {"$push": {"service_issues": issue}}
    )
    resp = with_field_report(
        await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0, "photos.data": 0})
    )
    if idem_key:
        await store_response(idem_key, "POST /jobs/{jid}/issues",
                              tenant["id"], resp, idem_body)
    return resp


@router.post("/jobs/{jid}/issues/{iid}/approve")
async def approve_service_issue(jid: str, iid: str,
                                user: dict = Depends(get_current_user),
                                tenant: dict = Depends(get_current_tenant)):
    job = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"photos.data": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    if user.get("role") == "customer" and job.get("customer_id") != user.get("customer_id"):
        raise HTTPException(403, "Not your job")
    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"], "service_issues.id": iid},
        {"$set": {"service_issues.$.status": "approved", "service_issues.$.approved_at": now_iso()}},
    )
    updated = await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0, "photos.data": 0})
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
        await db.jobs.find_one({"id": jid, "tenant_id": tenant["id"]}, {"_id": 0, "photos.data": 0})
    )
