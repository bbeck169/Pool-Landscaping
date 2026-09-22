"""Phase 31 · Step 1 — Workstream events (tap-job → checklist telemetry spine).

A tenant-scoped append-only stream that the UI (web + mobile) will use to
record structured "workstream" moments as techs move through the tap-job
flow — e.g. `checklist.opened`, `checklist.item_toggled`, `report.submitted`,
`photo.uploaded`. This step ships **only the backend spine + resolver**.
The UI wiring (checklist modal, mobile screen, tap-job handler, /workstream
web page) lands in Phase 31 · Step 2.

Endpoints (all `/api`-prefixed via server.py):
- POST /api/workstream/events   — admin | super_admin | technician
- GET  /api/workstream/events   — admin | super_admin (list, tenant-scoped)

Discovery pass (Feb 15 2026) confirmed there is no pre-existing
"workstream" or "activity_events" collection. `GET /api/activity`
(operations.py) is a **read-only synthesized feed** off jobs/quotes/leads —
it has no write endpoint, no collection, and cannot be reused for
structured tap-job telemetry. That's why we mint a new router here.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant
from services.job_assignee import effective_tid

router = APIRouter()

# Roles allowed to WRITE an event. Customers/portal users are excluded on purpose:
# workstream is technician/operations telemetry, never customer surface.
_WRITER_ROLES = {"admin", "super_admin", "technician"}
# Roles allowed to LIST events (management surface only).
_READER_ROLES = {"admin", "super_admin"}
# Phase 5A.2 · Feb 2026 — Workstream jobs feed is now admin-only.
# Techs, managers, and customers all get 403. Techs continue to use
# their own /schedule + /jobs surfaces; managers use the standard
# Jobs page. Workstream is the "completed service log" surface.
_JOBS_READER_ROLES = {"admin", "super_admin"}
# Phase 5A.2 — the Workstream feed only surfaces completed jobs. When
# no explicit status is passed we default to this; anything else is
# rejected with 400 so the feed's meaning stays unambiguous.
_WORKSTREAM_ONLY_STATUS = "completed"

# ── Slice M pricing invariants ───────────────────────────────────────
# Fields that MUST NEVER be surfaced to technicians. Applied on every
# job payload emitted by the aggregator + detail endpoints. This mirrors
# the Slice K2 rule for line-item projection (see job_media_line_items.py).
_TECH_HIDDEN_JOB_FIELDS = (
    "price", "cost", "total", "subtotal", "tax_amount", "revenue",
    "invoice_total", "quote_total", "margin", "labor_cost",
    "materials_cost", "gross_margin", "job_totals",
)
_TECH_HIDDEN_LINE_FIELDS = ("unit_price", "subtotal", "tax_rate", "cost")

_SORT_OPTIONS = {
    "newest", "oldest",
    "tech_asc", "tech_desc",
    "customer_asc", "customer_desc",
}


class WorkstreamEventIn(BaseModel):
    """Wire body for POST /api/workstream/events.

    `type` is required and free-form (e.g. `checklist.opened`,
    `report.submitted`, `photo.uploaded`) so downstream UI features can
    add new moments without a schema migration. `payload` is an opaque
    JSON blob the caller owns — we do not validate its shape here.
    """
    type: str = Field(..., min_length=1, max_length=120)
    payload: Optional[Dict[str, Any]] = None
    # Optional structured link to the resource the event is about
    # (e.g. `{ "type": "job", "id": "<jid>" }`). Free-form on purpose.
    related_ref: Optional[Dict[str, Any]] = None


@router.post("/workstream/events")
async def create_event(
    body: WorkstreamEventIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if user.get("role") not in _WRITER_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to create workstream events")

    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "type": body.type,
        "actor_user_id": user["id"],
        "actor_role": user.get("role"),
        "payload": body.payload or {},
        "related_ref": body.related_ref or None,
        "created_at": now_iso(),
    }
    await db.workstream_events.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


# ══════════════════════════════════════════════════════════════════
# Phase P25 · Feb-2026 — Internal emitter helper for the tap-job
# job-completion signal.
#
# Pre-P25 the job-completion side-effect fan-out (in
# ``routers/jobs.py`` at the ``status flips to completed`` transition
# block) fired the ``services.automation_engine`` "job.completed"
# event AND the ``services.marketing.event_dispatcher``
# "job_completed" schema-v2 event, but never wrote to
# ``db.workstream_events`` — so the /workstream feed and the
# workstream-job-detail timeline endpoint had no server-side row
# for job closures. The office/dispatch's Workstream activity feed
# was blank for anything closed from mobile.
#
# The offline-replay path in ``routers/mobile_sync.py::_handle_job_close``
# ALSO didn't emit — that's the reported P25 symptom
# ("technicians closing jobs offline replay the completion later,
# but the Workstream activity feed never gets the job.completed
# event"). This helper is called from both write sites so the
# emission shape stays consistent — schema drift here would break
# the workstream-job-detail timeline resolver.
#
# Idempotency contract: caller (each write path) MUST gate on
# whatever dedupe key they already use — online path guards on
# ``prev_status != "completed"`` (transition semantic), replay path
# guards on ``pending_sync_receipts.client_op_id`` (short-circuits
# before the handler runs) plus its own transition guard. This
# helper does NOT re-check dedupe internally so the caller is the
# single source of truth for "is this a real transition".
#
# ``completed_at`` argument policy: caller passes the field
# verbatim from the completion payload (offline queue's captured
# timestamp, NOT the replay's ``now_iso()``). This preserves the
# event's causal timestamp so the dispatch timeline reflects
# real-world completion time, not sync replay time.
# ══════════════════════════════════════════════════════════════════
async def emit_job_completed_event(
    tenant_id: str,
    actor_user_id: Optional[str],
    actor_role: Optional[str],
    job: Dict[str, Any],
    completed_at: Optional[str] = None,
    source: str = "online",
) -> Optional[dict]:
    """Insert a ``job.completed`` row into ``db.workstream_events``.

    Parameters
    ----------
    tenant_id:
        Owning tenant id (from ``get_current_tenant``).
    actor_user_id:
        The user id that closed the job. Optional so the automation
        engine's system-triggered closures (rare) still emit.
    actor_role:
        The user's role at close time. Stored on the event for the
        management feed's actor badge.
    job:
        The job doc AS PERSISTED (post-completion — includes the
        stamped ``completed_at``, ``status="completed"``, and any
        totals). Used to populate the event's ``payload.job``
        summary.
    completed_at:
        The completion timestamp to store on the event. On the
        offline path this is the OFFLINE-CAPTURED timestamp (from
        ``op.payload.completed_at``), NOT ``now_iso()``. Falls
        back to ``job.completed_at`` if the caller omits.
    source:
        Free-form tag ("online" | "mobile_sync_replay" | ...) so
        downstream filters can distinguish paths.

    Returns
    -------
    The inserted event doc (minus ``_id``), or ``None`` on
    insert failure (logged, never raised — job completion path
    must not fail because a telemetry write failed).
    """
    try:
        job_id = job.get("id") or job.get("job_id")
        completed_at_val = (
            completed_at
            or job.get("completed_at")
            or now_iso()
        )
        doc = {
            "id": new_id(),
            "tenant_id": tenant_id,
            "type": "job.completed",
            "actor_user_id": actor_user_id,
            "actor_role": actor_role,
            "payload": {
                "job_id": job_id,
                "customer_id": job.get("customer_id"),
                "customer_name": job.get("customer_name"),
                "technician_id": job.get("technician_id"),
                "completed_at": completed_at_val,
                "source": source,
            },
            "related_ref": {"type": "job", "id": job_id} if job_id else None,
            "created_at": now_iso(),
        }
        await db.workstream_events.insert_one(dict(doc))
        doc.pop("_id", None)
        return doc
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[workstream] job.completed emit failed for job=%s "
            "tenant=%s source=%s: %s",
            (job.get("id") if isinstance(job, dict) else "?"),
            tenant_id, source, exc,
        )
        return None


@router.get("/workstream/events")
async def list_events(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
    limit: int = Query(50, ge=1, le=500),
    type: Optional[str] = Query(None, description="Exact-match filter on `type`"),
):
    if user.get("role") not in _READER_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to list workstream events")

    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if type:
        q["type"] = type

    cur = db.workstream_events.find(q, {"_id": 0}).sort("created_at", -1).limit(limit)
    return await cur.to_list(limit)


# ── Python mirror of the JS `getChecklistType(job)` helper ────────────────
# Kept here (not in service_reports.py) so the checklist-type resolver has
# a single, testable home that mirrors the JS/TS helpers on web + mobile.
# Distinct from service_reports._detect_template() which returns
# "pool" | "landscape" | "generic" (backend template key). The client-facing
# names are "pool" | "landscaping" | "generic" per the Phase 31 brief.
_POOL_KEYWORDS = ("pool", "chem")
_LANDSCAPING_KEYWORDS = ("landscap", "lawn", "mow", "garden", "trim", "blow")


def get_checklist_type(job: Dict[str, Any] | None) -> str:
    if not job:
        return "generic"
    hay = " ".join(
        str(job.get(k) or "") for k in ("service_type", "job_type", "title")
    ).lower()
    for kw in _POOL_KEYWORDS:
        if kw in hay:
            return "pool"
    for kw in _LANDSCAPING_KEYWORDS:
        if kw in hay:
            return "landscaping"
    return "generic"


# ═══════════════════════════════════════════════════════════════════════
# Slice M · Workstream Jobs aggregator (Feb 2026).
#
# GET /api/workstream/jobs — a full job feed used by the refreshed
# Workstream page (Slice M2/M3/M4). This lives ALONGSIDE the telemetry
# endpoints above; it does not replace them.
#
# Filters (AND-combined):
#   • since         — inclusive lower bound on scheduled_date (YYYY-MM-DD or ISO)
#   • until         — inclusive upper bound on scheduled_date
#   • tech_id       — technician_id filter (admin only; techs are auto-scoped)
#   • customer_id   — customer_id filter
#   • status        — job status (default: all)
#
# Sort (default: newest):
#   • newest / oldest → scheduled_date desc / asc
#   • tech_asc / tech_desc → technician_name
#   • customer_asc / customer_desc → customer_name
#
# Pagination: limit (default 100, max 500) + offset.
#
# RBAC:
#   • customer            → 403
#   • technician          → auto-scoped to their assigned jobs; tech_id
#                            override is ignored (never allowed to peek at
#                            other techs' work).
#   • admin / super_admin → tenant-scoped, all filters honoured.
#
# Pricing invariance:
#   • Technicians never receive job_totals, unit_price, cost, subtotal,
#     tax_rate on any embedded line item or job field. This is server-
#     side projection — the frontend is a hint, not the security boundary.
# ═══════════════════════════════════════════════════════════════════════
def _project_job_for_tech(doc: Dict[str, Any]) -> None:
    """Mutates ``doc`` in place, stripping every pricing field a
    technician must never see. Called for every row emitted by the
    aggregator / detail endpoints when the caller has role tech."""
    for k in _TECH_HIDDEN_JOB_FIELDS:
        doc.pop(k, None)
    lis = doc.get("line_items")
    if isinstance(lis, list):
        for li in lis:
            if isinstance(li, dict):
                for k in _TECH_HIDDEN_LINE_FIELDS:
                    li.pop(k, None)


def _photo_thumb(jid: str, pid: str) -> str:
    """Public-token URL used to embed job photos in the Workstream feed.
    Matches the existing route at /api/public/job-photo/{jid}/{pid}."""
    return f"/api/public/job-photo/{jid}/{pid}"


def _video_url(storage_path: str) -> str:
    """Stream URL for a stored video (matches /api/media/videos/{path:path})."""
    return f"/api/media/videos/{storage_path}"


def _media_summary(job: Dict[str, Any], *,
                    max_photos: int = 4, max_videos: int = 2) -> Dict[str, Any]:
    """Extract a compact media summary for the Workstream card:
    thumbnails (up to N images + N videos), counts, and the +extra
    overflow badge count. Videos are filtered to non-deleted only."""
    photos = job.get("photos") or []
    videos = [v for v in (job.get("videos") or []) if not v.get("is_deleted")]
    jid = job.get("id") or ""
    p_thumbs: List[Dict[str, Any]] = []
    for p in photos[:max_photos]:
        pid = p.get("id")
        if not pid:
            continue
        p_thumbs.append({
            "id": pid,
            "url": _photo_thumb(jid, pid),
            "label": p.get("label"),
        })
    v_thumbs: List[Dict[str, Any]] = []
    for v in videos[:max_videos]:
        sp = v.get("storage_path")
        if not sp:
            continue
        v_thumbs.append({
            "id": v.get("id"),
            "url": _video_url(sp),
            "mime": v.get("mime"),
            "caption": v.get("caption"),
        })
    total_media = len(photos) + len(videos)
    shown = len(p_thumbs) + len(v_thumbs)
    return {
        "photos_count": len(photos),
        "videos_count": len(videos),
        "photo_thumbs": p_thumbs,
        "video_thumbs": v_thumbs,
        "extra_count": max(0, total_media - shown),
    }


def _apply_sort(rows: List[Dict[str, Any]], sort: str) -> List[Dict[str, Any]]:
    """Client-side sort so we can order on enriched (customer_name /
    technician_name) fields that are not native to the ``jobs``
    collection. Cost is negligible with the aggregator page size (<=500)."""
    if sort == "oldest":
        rows.sort(key=lambda r: r.get("scheduled_date") or r.get("created_at") or "")
    elif sort == "tech_asc":
        rows.sort(key=lambda r: (r.get("technician_name") or "").lower())
    elif sort == "tech_desc":
        rows.sort(key=lambda r: (r.get("technician_name") or "").lower(), reverse=True)
    elif sort == "customer_asc":
        rows.sort(key=lambda r: (r.get("customer_name") or "").lower())
    elif sort == "customer_desc":
        rows.sort(key=lambda r: (r.get("customer_name") or "").lower(), reverse=True)
    else:
        # newest (default)
        rows.sort(
            key=lambda r: r.get("scheduled_date") or r.get("created_at") or "",
            reverse=True,
        )
    return rows


@router.get("/workstream/jobs")
async def list_workstream_jobs(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
    since: Optional[str] = Query(None, description="Inclusive lower bound on scheduled_date (YYYY-MM-DD or ISO)."),
    until: Optional[str] = Query(None, description="Inclusive upper bound on scheduled_date."),
    tech_id: Optional[str] = Query(None, description="Technician filter (admin only; ignored for tech callers)."),
    customer_id: Optional[str] = Query(None, description="Customer filter."),
    status: Optional[str] = Query(None, description="Job status filter (default: all statuses)."),
    sort: str = Query("newest", description="newest | oldest | tech_asc | tech_desc | customer_asc | customer_desc"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    role = user.get("role") or ""
    if role not in _JOBS_READER_ROLES:
        raise HTTPException(status_code=403, detail="Workstream is admin-only")
    if sort not in _SORT_OPTIONS:
        raise HTTPException(status_code=400, detail=f"Invalid sort: {sort}")

    # Phase 5A.2 — enforce the completed-jobs-only invariant. When the
    # caller passes no status, default to 'completed'. Any other status
    # is rejected outright so the endpoint's meaning stays honest.
    effective_status = (status or _WORKSTREAM_ONLY_STATUS).strip().lower()
    if effective_status != _WORKSTREAM_ONLY_STATUS:
        raise HTTPException(
            status_code=400,
            detail=(
                "Workstream lists only completed jobs. "
                f"Pass status='{_WORKSTREAM_ONLY_STATUS}' or omit."
            ),
        )

    from utils import not_deleted_filter
    q: Dict[str, Any] = {"tenant_id": tenant["id"], **not_deleted_filter()}

    # RBAC: tech is ALWAYS auto-scoped, tech_id filter is ignored for them.
    if role == "technician":
        tid = user.get("technician_id") or user.get("id")
        q["technician_id"] = tid
    elif tech_id:
        q["technician_id"] = tech_id

    if customer_id:
        q["customer_id"] = customer_id
    # Phase P27 · Feb-2026 — case-insensitive status match. The
    # pre-P27 shape was ``q["status"] = "completed"`` (exact-match)
    # which silently dropped any doc written with a
    # ``"Completed"`` (title-case) or ``"COMPLETED"`` casing. Preview
    # data currently only ships lowercase, but ops migrations +
    # legacy CSV imports have written mixed cases historically.
    # Regex anchors ``^`` and ``$`` are required — a bare
    # ``completed`` substring would false-positive on
    # ``completed_by_automation`` / ``completed_at`` legacy strings.
    q["status"] = {"$regex": r"^completed$", "$options": "i"}

    if since or until:
        rng: Dict[str, str] = {}
        if since:
            rng["$gte"] = since
        if until:
            rng["$lte"] = until
        q["scheduled_date"] = rng

    # Pull a wider slice from Mongo since we sort on enriched fields
    # (customer_name / tech_name) after the join. Cap to a safe upper
    # bound; the aggregator is not intended for full-table exports.
    fetch_cap = min(500, max(limit + offset, limit) * 2)
    docs = await db.jobs.find(q, {"_id": 0, "photos.data": 0}).sort(
        "scheduled_date", -1
    ).to_list(fetch_cap)

    # Join customer + technician + property in a single roundtrip each.
    cids = list({d.get("customer_id") for d in docs if d.get("customer_id")})
    # Feb-2026 · P1 hotfix — read-path union across all four tech-id
    # field shapes (see ``services/job_assignee.py``). Reading only
    # ``technician_id`` silently dropped every completed job whose
    # assignment lived in ``assigned_to`` / ``assigned_technician_id`` /
    # ``tech_user_id`` — producing "Assigned to Unassigned" on the
    # Workstream page.
    tids = list({t for t in (effective_tid(d) for d in docs) if t})
    pids = list({d.get("property_id") for d in docs if d.get("property_id")})

    cmap: Dict[str, Dict[str, Any]] = {}
    if cids:
        cust_rows = await db.customers.find(
            {"id": {"$in": cids}, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "name": 1, "is_vip": 1, "gate_code": 1},
        ).to_list(len(cids) * 2)
        cmap = {c["id"]: c for c in cust_rows}

    tmap: Dict[str, Dict[str, Any]] = {}
    if tids:
        from services.service_report_view import resolve_technicians
        tmap = await resolve_technicians(db, tenant["id"], tids)

    pmap: Dict[str, Dict[str, Any]] = {}
    if pids:
        prop_rows = await db.properties.find(
            {"id": {"$in": pids}, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "label": 1, "address": 1},
        ).to_list(len(pids) * 2)
        pmap = {p["id"]: p for p in prop_rows}

    is_tech = role == "technician"
    rows: List[Dict[str, Any]] = []
    for d in docs:
        cid = d.get("customer_id")
        tid = effective_tid(d)
        pid = d.get("property_id")
        cust = cmap.get(cid) if cid else None
        # Feb 2026 · Resolver is source-of-truth. If the resolver
        # returns a value it wins over stored ``technician_name``
        # (self-healing before the boot backfill lands).  When the
        # resolver has nothing, fall back to the ID string per
        # the resolver-cascade contract — never crash.
        tinfo = tmap.get(tid) if tid else None
        tech_name = (tinfo or {}).get("name") if tinfo else None
        tech_active = (tinfo or {}).get("active", True) if tinfo else True
        prop = pmap.get(pid) if pid else None

        addr = (prop or {}).get("address") or {}
        prop_addr = ", ".join(
            [x for x in (addr.get("line1"), addr.get("city"),
                          addr.get("state"), addr.get("postal_code")) if x]
        ) or None

        line_items = d.get("line_items") or []
        row: Dict[str, Any] = {
            "id": d.get("id"),
            "title": d.get("title") or "",
            "status": d.get("status") or "",
            "service_type": d.get("service_type") or d.get("job_type") or "",
            "scheduled_date": d.get("scheduled_date"),
            "created_at": d.get("created_at"),
            "updated_at": d.get("updated_at"),
            # Phase K12 · Feb-2026 — surface the completion timestamp so
            # the Workstream table can render a "Completed" column
            # (super_admin / admin / manager only — frontend gates the
            # column render).  Written by the tech's mark-complete flow.
            "completed_at": d.get("completed_at"),
            "customer_id": cid,
            "customer_name": (cust or {}).get("name") or d.get("customer_name") or "",
            "customer_is_vip": bool((cust or {}).get("is_vip")),
            "technician_id": tid,
            "technician_name": tech_name
                or (d.get("technician_name") if not tinfo else None)
                or (tid or ""),
            # Feb 2026 · Deactivated-tech badge signal. UI can render
            # a "Inactive" pill next to the name when this is False.
            # Missing tinfo (unresolved tid) defaults to True so
            # legacy rows don't accidentally show as inactive.
            "technician_active": tech_active,
            "property_id": pid,
            "property_label": (prop or {}).get("label"),
            "property_address": prop_addr,
            "line_items_count": len(line_items),
            "media": _media_summary(d),
        }
        # Admin gets job_totals; tech never sees them (server side).
        if not is_tech and d.get("job_totals"):
            row["job_totals"] = d.get("job_totals")
        rows.append(row)

    _apply_sort(rows, sort)

    total = len(rows)
    page = rows[offset:offset + limit]

    if is_tech:
        for r in page:
            _project_job_for_tech(r)

    # Phase P27 · Feb-2026 — explicit ``counts`` block so the FE
    # tile doesn't need to re-derive from the paginated slice
    # (``page``) — that would silently undercount by ``limit``
    # once a tenant crosses the pagination boundary. Semantics:
    #   * ``completed_count`` — every row this handler returned
    #     (Workstream is completed-only, so this equals ``total``
    #     for now; broken out as a distinct key so a future
    #     multi-status Workstream doesn't shift the wire shape).
    #   * ``total_count``     — total matching rows (pre-slice).
    #   * ``services_count``  — rows whose ``service_type`` matches
    #     the shared jobCategory ``_SERVICES_RX`` regex OR fell
    #     through to the completed-service fallback (empty
    #     ``service_type`` + status=completed).
    #   * ``repairs_count``   — rows whose ``service_type`` matches
    #     the ``_REPAIRS_RX`` regex. Repairs win on ambiguous
    #     matches (a "pool repair" job counts as repair, not
    #     service) — mirrors ``frontend/src/lib/jobCategory.js``.
    #
    # The FE STILL derives tile totals from the returned list
    # (client-side ``computePillCounts``) — this ``counts`` block
    # is a redundant sanity check + a hook for future analytics.
    import re as _re
    _SERVICES_RX = _re.compile(
        r"(service|maintenance|cleaning|pool|landscap|inspection|"
        r"weekly|monthly)",
        _re.IGNORECASE,
    )
    _REPAIRS_RX = _re.compile(
        r"(repair|fix|replace|install)", _re.IGNORECASE,
    )
    services_count = 0
    repairs_count = 0
    for r in rows:
        st = str(r.get("service_type") or "")
        if _REPAIRS_RX.search(st):
            repairs_count += 1
        elif _SERVICES_RX.search(st):
            services_count += 1
        elif (r.get("status") or "").lower() == "completed":
            # Completed job with an idiosyncratic service_type — falls
            # into services per the frontend classifier's rule #4.
            services_count += 1

    return {
        "jobs": page,
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort": sort,
        "counts": {
            "total_count": total,
            "completed_count": total,
            "services_count": services_count,
            "repairs_count": repairs_count,
        },
        "filters": {
            "since": since,
            "until": until,
            "tech_id": None if is_tech else tech_id,
            "customer_id": customer_id,
            "status": status,
        },
    }
