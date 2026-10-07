# ruff: noqa: F403,F405
"""Phase 8 · Feb 2026 — Leads System Overhaul.

Consolidated router for the leads collection. Legacy behaviors (the
Phase 2 ``PUT /api/leads/{lid}`` update path + the two
``convert-to-job`` / ``convert-to-quote`` shortcuts) are preserved so
older frontend code keeps working.

New in Phase 8:
* Timeline events on every mutation (created / status_change /
  note_added / converted_to_customer / archived).
* Six canonical statuses (New, Contacted, Quoted, Closed Won,
  Closed Lost, On Hold) — write-time normalization tolerates the old
  lowercase forms so historical rows keep loading.
* Sources auto-tagged (website_form, admin_manual, phone, walk_in,
  referral, widget_chat, import).
* ``close-won`` runs a proper conversion pipeline (customer
  merge-or-create → notes/timeline copy → welcome email + SMS +
  Sales Won drip enrollment). Idempotent.
* ``close-lost`` requires a ≥3-char ``loss_reason``.
* ``GET /api/leads`` supports status/source/service_interest filters,
  search, date range, pagination, and archive inclusion.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user, new_id, now_iso, require_admin
from models import (
    ConvertJobIn, ConvertQuoteIn, LeadCloseLostIn, LeadIn,
    LeadNoteIn, LeadUpdate, PublicLeadIn,
)  # LeadIn / LeadUpdate / etc.

router = APIRouter()

_CANONICAL_STATUSES = {
    # Phase 34 · Task CC · Feb 2026 — status enum standardization.
    # The five values below are the ONLY values accepted going forward.
    # Anything else is mapped via ``_STATUS_ALIASES`` on write and by the
    # boot-time ``migrate_lead_statuses()`` sweep on read.
    "new", "contacted", "quoted", "closed_won", "closed_lost",
}
_STATUS_ALIASES = {
    # New → new
    "new": "new", "new_lead": "new", "open": "new", "untouched": "new",
    "fresh": "new", "New": "new",
    # Contacted → contacted
    "contacted": "contacted", "contact_made": "contacted",
    "follow_up": "contacted", "attempted": "contacted",
    "Contacted": "contacted",
    # Quoted → quoted
    "quoted": "quoted", "estimate_sent": "quoted",
    "proposal_sent": "quoted", "estimated": "quoted",
    "Quoted": "quoted",
    # Closed Won → closed_won
    "won": "closed_won", "closed_won": "closed_won",
    "converted": "closed_won", "accepted": "closed_won",
    "Closed Won": "closed_won", "closed won": "closed_won",
    # Closed Lost → closed_lost
    "lost": "closed_lost", "closed_lost": "closed_lost",
    "rejected": "closed_lost", "declined": "closed_lost",
    "disqualified": "closed_lost", "Closed Lost": "closed_lost",
    "closed lost": "closed_lost",
    # Legacy "On Hold" → contacted (still actively working the deal).
    "on_hold": "contacted", "on hold": "contacted", "On Hold": "contacted",
}
_VALID_SOURCES = {
    "website_form", "admin_manual", "phone", "walk_in",
    "referral", "widget_chat", "import",
}
# LS-C · Feb-2026 — System-source whitelist. Machine-generated
# lead entries (Lead-Sense conversions, future pixel-source
# ingestions) tag ``source`` from this set. NEVER accepted from
# the authenticated admin form (``create_lead`` continues to
# validate strictly against ``_VALID_SOURCES`` only). Consumed
# by the LS-C conversion endpoint at ``/api/lead-sense/convert``
# which persists rows directly to ``db.leads`` — the code path
# is the trust boundary, not the source string. Kept as a
# separate frozenset (not merged into ``_VALID_SOURCES``) so
# the admin manual-add dropdown stays curated to human-generated
# labels.
_SYSTEM_SOURCES = frozenset({"MARCO Lead-Sense"})
_VALID_INTERESTS = {"Pool", "Landscape", "Both"}
_INBOUND_MANAGER_ROLES = {"admin", "super_admin", "manager"}

# Feb-2026 · Public-lead form widened acceptance. The historical
# whitelist above silently coerced any interest string outside
# {"Pool","Landscape","Both"} to ``null`` — new form copy uses
# free-form phrases like "Pool cleaning" or "Landscape design +
# monthly maintenance", so the coercion truncates real intent.
# ``_normalize_interest`` keeps the enum accept-list for the
# common cases (short badge rendering + segment reporting) but
# passes any non-empty free-form string through verbatim (bounded
# to 120 chars to keep the ``leads`` column indexable).
_INTEREST_MAX_LEN = 120


def _normalize_interest(raw: Optional[str]) -> Optional[str]:
    """Return the caller's ``service_interest`` verbatim when set,
    truncated to 120 chars. Empty / whitespace-only → ``None``.

    Historical enum coercion is gone (see the ``_VALID_INTERESTS``
    docstring above). The frontend memo promised verbatim
    persistence — this helper is what makes that true.
    """
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    return s[:_INTEREST_MAX_LEN]


def _normalize_status(raw: Optional[str]) -> str:
    """Phase 34 · Task CC — every lead-status write funnels through here.
    Unknown values fall back to ``"new"`` and the caller SHOULD log the
    original value if it wants an audit trail (the migration function
    below does exactly that on the boot-time sweep)."""
    if not raw:
        return "new"
    s = str(raw).strip()
    if s in _CANONICAL_STATUSES:
        return s
    mapped = _STATUS_ALIASES.get(s) or _STATUS_ALIASES.get(s.lower())
    return mapped or "new"


async def migrate_lead_statuses() -> Dict[str, Any]:
    """Phase 34 · Task CC · Feb 2026 — idempotent status enum migration.
    Rewrites every ``leads.status`` value to the canonical snake_case
    set. Returns per-bucket counts + a list of unrecognised legacy
    values so an admin can audit them from the boot log.
    """
    per_bucket: Dict[str, int] = {k: 0 for k in _CANONICAL_STATUSES}
    unknown: List[Dict[str, str]] = []
    total = 0
    async for row in db.leads.find(
        {}, {"_id": 0, "id": 1, "status": 1, "tenant_id": 1},
    ):
        total += 1
        current = row.get("status")
        canonical = _normalize_status(current)
        if not current or (
            str(current) not in _CANONICAL_STATUSES
            and str(current).lower() not in _STATUS_ALIASES
            and str(current) not in _STATUS_ALIASES
        ):
            unknown.append({"lead_id": row.get("id") or "",
                              "tenant_id": row.get("tenant_id") or "",
                              "original": str(current)})
        if current != canonical:
            await db.leads.update_one(
                {"id": row["id"]},
                {"$set": {"status": canonical}},
            )
        per_bucket[canonical] = per_bucket.get(canonical, 0) + 1
    logger.info(
        f"[phase34-task-cc] lead status migration total={total} "
        f"buckets={per_bucket} unknown={len(unknown)}"
    )
    for u in unknown[:20]:
        logger.warning(
            f"[phase34-task-cc] lead {u['lead_id']} had unknown "
            f"status={u['original']!r} → mapped to 'new'"
        )
    return {
        "total": total,
        "per_bucket": per_bucket,
        "unknown_count": len(unknown),
        "unknown_samples": unknown[:20],
    }


def _require_leads_role(user: dict) -> None:
    if (user or {}).get("role") not in _INBOUND_MANAGER_ROLES:
        raise HTTPException(403, "Not allowed")


def _timeline_entry(kind: str, actor_user_id: Optional[str] = None,
                     **payload) -> Dict[str, Any]:
    return {"ts": now_iso(), "kind": kind,
             "actor_user_id": actor_user_id,
             "payload": payload}


def _digits_only(s: Optional[str]) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _phone_tail(s: Optional[str], n: int = 10) -> str:
    d = _digits_only(s)
    return d[-n:] if len(d) >= n else d


# ═══════════════════════════ LIST + DETAIL ══════════════════════════
@router.get("/leads")
async def list_leads(user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant),
                       status: Optional[str] = None,
                       source: Optional[str] = None,
                       service_interest: Optional[str] = None,
                       search: Optional[str] = None,
                       date_from: Optional[str] = None,
                       date_to: Optional[str] = None,
                       include_archived: int = 0,
                       page: int = Query(1, ge=1),
                       page_size: int = Query(50, ge=1, le=200)):
    _require_leads_role(user)
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    # Phase 34 · Task BB · Feb 2026 — hide soft-deleted leads by default.
    q["$and"] = [{"$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]}]
    # ── Phase P48 · Feb-2026 · multi-status CSV support ────────────
    # Pre-P48 this branch only accepted a single canonical status.
    # The Leads page now ships an Active/Archive tab switcher that
    # queries multi-value groups (Active tab → new,contacted,quoted;
    # Archive tab → closed_won,closed_lost).  Accept a
    # comma-separated list; each token normalises through the same
    # ``_normalize_status`` helper.  Unknown tokens are silently
    # dropped (a typo shouldn't surface ``new`` leads).  When no
    # valid tokens survive, treat as no-status-filter — same
    # semantics as ``status="all"``.  Single-value callers keep
    # working byte-identically because a single token has no commas.
    # ──────────────────────────────────────────────────────────────
    if status and status != "all":
        raw_tokens = [t.strip() for t in str(status).split(",") if t.strip()]
        # ``_normalize_status`` maps unknowns to ``"new"`` — that's
        # WRONG for a multi-status filter (it would pollute the
        # Active tab with matches for a typo).  Filter through
        # ``_STATUS_ALIASES`` explicitly + ``_VALID_STATUSES`` set
        # so unknowns get dropped.  De-dupe with dict.fromkeys to
        # preserve insertion order for stable test output.
        canonical = []
        for tok in raw_tokens:
            mapped = _STATUS_ALIASES.get(tok) or (
                tok if tok in _CANONICAL_STATUSES else None
            )
            if mapped:
                canonical.append(mapped)
        canonical = list(dict.fromkeys(canonical))
        if len(canonical) == 1:
            q["status"] = canonical[0]
        elif len(canonical) > 1:
            q["status"] = {"$in": canonical}
        # else: fall through to "no status filter" — same as "all".
    elif not status:
        # Phase 16 · Addition E · Feb-2026 — exclude rejected leads
        # from the default inbox view. Callers who want the reject
        # tab pass ?status=rejected explicitly.
        q["status"] = {"$ne": "rejected"}
    if source and source != "all":
        q["source"] = source
    if service_interest and service_interest != "all":
        q["service_interest"] = service_interest
    if not include_archived:
        q["archived_at"] = {"$in": [None, ""]}
    if date_from or date_to:
        rng: Dict[str, Any] = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        q["created_at"] = rng
    if search:
        s = search.strip()
        if s:
            q["$or"] = [
                {"name": {"$regex": s, "$options": "i"}},
                {"email": {"$regex": s, "$options": "i"}},
                {"phone": {"$regex": s, "$options": "i"}},
            ]
    skip = (page - 1) * page_size
    total = await db.leads.count_documents(q)
    rows = await db.leads.find(q, {"_id": 0}).sort("created_at", -1) \
        .skip(skip).limit(page_size).to_list(page_size)
    return {"rows": rows, "total": total, "page": page,
             "page_size": page_size}


@router.get("/leads/{lid}")
async def get_lead(lid: str,
                     user: dict = Depends(get_current_user),
                     tenant: dict = Depends(get_current_tenant)):
    _require_leads_role(user)
    row = await db.leads.find_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Lead not found")
    # LEAD-CREATE-QUOTE · Feb-2026 — attached-quote count badge. The
    # lead-detail "Create Quote" button renders a small count badge
    # when ``quotes_count > 0`` so staff can see at a glance that
    # quotes exist on this lead without opening a drill-down. Cheap
    # ``count_documents`` on the Phase-2 ``(tenant_id,
    # recipient_type, recipient_id)`` compound index — see
    # ``migrations/quotes_recipient_index_v1``. Additive to the
    # response envelope (not persisted) so writers remain untouched.
    row["quotes_count"] = int(await db.quotes.count_documents(
        {"tenant_id": tenant["id"], "recipient_type": "lead",
         "recipient_id": lid},
    ))
    return row


# Feb-2026 · Lead detail drawer · Raw form submission lazy-load.
# The detail drawer fetches this on-demand when ``lead.meta.submission_id``
# exists so admins can inspect every question the visitor answered
# without ballooning the list-endpoint payload (submissions can be
# ~100+ KB when the form has file uploads referenced by URL).
#
# Contract:
#   * 200 → ``{"submission_id": str, "form_id": str|None,
#              "created_at": str, "values": dict}``.
#   * 404 → lead not found OR lead has no linked submission.
#   * 403 → caller lacks the leads role (already enforced by
#           ``_require_leads_role`` — matches ``/leads/{lid}``).
#   * Tenant scope: BOTH the lead AND the submission are re-queried
#     with ``tenant_id`` — a lead can never surface a submission from
#     a different tenant even if the id happens to collide.
@router.get("/leads/{lid}/raw-submission")
async def get_lead_raw_submission(
    lid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_leads_role(user)
    lead = await db.leads.find_one(
        {"id": lid, "tenant_id": tenant["id"]},
        {"_id": 0, "meta": 1},
    )
    if not lead:
        raise HTTPException(404, "Lead not found")
    submission_id = ((lead.get("meta") or {}).get("submission_id")) or None
    if not submission_id:
        # Legacy pre-P17 leads have no submission reference. Return
        # 404 so the frontend hides the panel cleanly — same treatment
        # as a truly missing submission.
        raise HTTPException(404, "No linked submission")
    sub = await db.form_submissions.find_one(
        {"id": submission_id, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "form_id": 1, "created_at": 1,
         "values": 1, "answers": 1, "data": 1, "page_url": 1},
    )
    if not sub:
        raise HTTPException(404, "Submission not found")
    # ``form_submissions`` writes ``answers`` (new widget path) OR
    # ``values`` (legacy marketing.py path) — normalise so the client
    # always reads a single ``values`` key. ``data`` is the pre-GH
    # mirror kept for backwards-compat.
    values = sub.get("answers") or sub.get("values") or sub.get("data") or {}
    return {
        "submission_id": sub.get("id"),
        "form_id": sub.get("form_id"),
        "created_at": sub.get("created_at"),
        "page_url": sub.get("page_url"),
        "values": values,
    }


# ═══════════════════════════ CREATE ═════════════════════════════════
@router.post("/leads")
async def create_lead(body: LeadIn,
                        background_tasks: BackgroundTasks,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    _require_leads_role(user)
    if not (body.name or "").strip():
        raise HTTPException(400, "Name is required")
    if not (body.email or "").strip() and not (body.phone or "").strip():
        raise HTTPException(400, "One of email or phone is required")
    src = (body.source or "admin_manual").strip()
    if src not in _VALID_SOURCES:
        src = "admin_manual"
    # Feb-2026 · widened acceptance — see ``_normalize_interest``.
    interest = _normalize_interest(body.service_interest)
    doc = body.dict()
    # Feb-2026 · P0 — accept autocomplete-supplied lat/lng under the
    # canonical ``latitude``/``longitude`` keys. Legacy ``lat``/``lng``
    # is folded in as a fallback so older clients keep working.
    _lat_in = body.latitude if body.latitude is not None else body.lat
    _lng_in = body.longitude if body.longitude is not None else body.lng
    doc.update({
        "id": new_id(),
        "tenant_id": tenant["id"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": user.get("id"),
        "source": src,
        "status": _normalize_status(body.status),
        "service_interest": interest,
        "service_address": body.service_address or body.address or "",
        "latitude": _lat_in,
        "longitude": _lng_in,
        "archived_at": None,
        "loss_reason": None,
        "converted_customer_id": None,
        "timeline": [
            _timeline_entry("created", actor_user_id=user.get("id"),
                             source=src, status="New"),
        ],
    })
    await db.leads.insert_one(doc)
    # Feb-2026 · P0 · on-save geocode backfill — only fires when the
    # client didn't supply lat/lng (autocomplete already resolved
    # coordinates, so a second round-trip is wasted).
    _maybe_backfill_lead_geocode(background_tasks, doc)
    # Feb-2026 · Fire the ``new_lead`` marketing-sequence trigger.
    # Real-time via ``BackgroundTasks`` so this manual admin POST
    # never waits on enrolment latency.
    try:
        from services.marketing.lead_triggers import (
            fire_new_lead_sequence_trigger,
        )
        await fire_new_lead_sequence_trigger(
            lead=doc, tenant_id=tenant["id"],
            background_tasks=background_tasks,
        )
    except Exception:
        pass
    # Feb 2026 · Phase 1 Custom Trigger Builder — additive schema-v2
    # emission. The legacy fanout above still runs for v1 sequences;
    # this hook enrols any schema_version>=2 sequence whose trigger
    # names ``new_lead``. Ledger dedupe guarantees no double-fire.
    try:
        from services.marketing.event_dispatcher import emit_event
        background_tasks.add_task(
            emit_event,
            event="new_lead",
            tenant_id=tenant["id"],
            entity_id=doc.get("id"),
            customer_id=None,
            payload_extras={"lead": doc,
                              "correlation_id": doc.get("id")},
        )
    except Exception:
        pass
    # Phase 16 · Additions E + F · Feb-2026 — internal notification
    # to Brian + auto-reject out-of-state. Best-effort; a failure
    # never blocks lead creation.
    try:
        from services.leads_side_effects import apply_lead_post_create
        updates = await apply_lead_post_create(doc)
        if updates:
            doc.update(updates)
    except Exception as _e:  # pragma: no cover - defensive
        logger.warning(f"[leads] post-create side effects crashed: {_e}")
    doc.pop("_id", None)
    return doc


# ═══════════════════════════ PATCH / PUT ═══════════════════════════
async def _apply_lead_update(lid: str, tenant_id: str, upd: Dict[str, Any],
                                actor_user_id: Optional[str]) -> Dict[str, Any]:
    current = await db.leads.find_one({"id": lid, "tenant_id": tenant_id},
                                          {"_id": 0})
    if not current:
        raise HTTPException(404, "Lead not found")
    fields: Dict[str, Any] = {}
    new_events: List[Dict[str, Any]] = []
    if "status" in upd and upd["status"] is not None:
        new_status = _normalize_status(upd["status"])
        if new_status != current.get("status"):
            fields["status"] = new_status
            if new_status == "Contacted" and not current.get("contacted_at"):
                fields["contacted_at"] = now_iso()
            if new_status == "Quoted" and not current.get("quoted_at"):
                fields["quoted_at"] = now_iso()
            new_events.append(_timeline_entry(
                "status_change", actor_user_id=actor_user_id,
                **{"from": current.get("status"), "to": new_status},
            ))
    for k in ("service_interest", "service_address", "phone",
                "email", "notes", "latitude", "longitude"):
        if k in upd and upd[k] is not None:
            fields[k] = upd[k]
    if fields:
        fields["updated_at"] = now_iso()
        ops: Dict[str, Any] = {"$set": fields}
        if new_events:
            ops["$push"] = {"timeline": {"$each": new_events}}
        await db.leads.update_one({"id": lid, "tenant_id": tenant_id}, ops)
    # Feb 2026 · Phase 1 Custom Trigger Builder — emit lead_status_changed
    # when the status actually flipped. Fire-and-forget. Correlation
    # key is (lead_id, new_status) so re-runs on the same status
    # transition dedupe cleanly.
    if fields.get("status"):
        try:
            from services.marketing.event_dispatcher import emit_event
            await emit_event(
                event="lead_status_changed",
                tenant_id=tenant_id,
                entity_id=lid,
                customer_id=None,
                payload_extras={
                    "from": current.get("status"),
                    "to": fields["status"],
                    "lead": {**current, **fields},
                    "correlation_id": f"{lid}:status:{fields['status']}",
                },
            )
        except Exception:
            pass
    return await db.leads.find_one({"id": lid, "tenant_id": tenant_id},
                                      {"_id": 0})


@router.patch("/leads/{lid}")
async def patch_lead(lid: str, body: LeadUpdate,
                      user: dict = Depends(get_current_user),
                      tenant: dict = Depends(get_current_tenant)):
    _require_leads_role(user)
    return await _apply_lead_update(
        lid, tenant["id"], body.dict(exclude_unset=True),
        actor_user_id=user.get("id"),
    )


@router.put("/leads/{lid}")
async def update_lead(lid: str, body: LeadUpdate,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    """Legacy PUT — Phase 2 shipped this shape. Kept for compatibility."""
    _require_leads_role(user)
    return await _apply_lead_update(
        lid, tenant["id"], body.dict(exclude_unset=True),
        actor_user_id=user.get("id"),
    )


# ═══════════════════════════ NOTE ═══════════════════════════════════
@router.post("/leads/{lid}/note")
async def add_note(lid: str, body: LeadNoteIn,
                    user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant)):
    _require_leads_role(user)
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "note text is required")
    lead = await db.leads.find_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"_id": 0, "notes": 1},
    )
    if not lead:
        raise HTTPException(404, "Lead not found")
    combined = (lead.get("notes") or "").rstrip()
    combined = (combined + "\n\n" if combined else "") + text
    await db.leads.update_one(
        {"id": lid, "tenant_id": tenant["id"]},
        {"$set": {"notes": combined, "updated_at": now_iso()},
         "$push": {"timeline": _timeline_entry(
             "note_added", actor_user_id=user.get("id"), text=text,
         )}},
    )
    return await db.leads.find_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"_id": 0},
    )


# ═══════════════════════════ CLOSE LOST ════════════════════════════
@router.post("/leads/{lid}/close-lost")
async def close_lost(lid: str, body: LeadCloseLostIn,
                       user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    _require_leads_role(user)
    reason = (body.loss_reason or "").strip()
    if len(reason) < 3:
        raise HTTPException(400, "loss_reason must be at least 3 characters")
    lead = await db.leads.find_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not lead:
        raise HTTPException(404, "Lead not found")
    now = now_iso()
    await db.leads.update_one(
        {"id": lid, "tenant_id": tenant["id"]},
        {"$set": {"status": "Closed Lost", "closed_at": now,
                    "loss_reason": reason, "updated_at": now},
         "$push": {"timeline": _timeline_entry(
             "status_change", actor_user_id=user.get("id"),
             **{"from": lead.get("status"), "to": "Closed Lost",
                 "loss_reason": reason},
         )}},
    )
    return await db.leads.find_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"_id": 0},
    )


# ═══════════════════════════ CONVERT (CLOSE WON) ═══════════════════
async def _match_customer_for_conversion(tenant_id: str,
                                            lead: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Match a lead to an existing customer by email OR normalized phone."""
    email = (lead.get("email") or "").strip().lower()
    phone_tail = _phone_tail(lead.get("phone"))
    or_clauses: List[Dict[str, Any]] = []
    if email:
        or_clauses.append({"email": {"$regex": f"^{email}$",
                                        "$options": "i"}})
    if phone_tail and len(phone_tail) >= 7:
        or_clauses.append({"phone": {"$regex": phone_tail + "$"}})
        or_clauses.append({"phones": {"$regex": phone_tail + "$"}})
    if not or_clauses:
        return None
    return await db.customers.find_one(
        {"tenant_id": tenant_id, "$or": or_clauses}, {"_id": 0},
    )


async def _run_close_won_pipeline(lead: Dict[str, Any], tenant_id: str,
                                     actor_user_id: Optional[str]) -> Dict[str, Any]:
    """Phase 8 conversion pipeline. Returns
    ``{customer_id, was_merged, notifications: {email, sms, drip_enrollment_id}}``.
    Idempotent — calling on an already-converted lead short-circuits and
    returns the previously-stored customer_id without re-sending
    notifications."""
    if lead.get("converted_customer_id"):
        return {"customer_id": lead["converted_customer_id"],
                 "was_merged": bool(lead.get("_was_merged")),
                 "notifications": {"email": None, "sms": None,
                                     "drip_enrollment_id": None},
                 "idempotent": True}

    existing = await _match_customer_for_conversion(tenant_id, lead)
    was_merged = bool(existing)
    now = now_iso()
    lead_timeline = lead.get("timeline") or []
    lead_notes = (lead.get("notes") or "").strip()
    # ─────────── Merge branch
    if existing:
        cid = existing["id"]
        set_ops: Dict[str, Any] = {}
        for src_key, dst_key in (
            ("name", "name"), ("email", "email"), ("phone", "phone"),
            ("service_address", "address"),
        ):
            if not existing.get(dst_key) and lead.get(src_key):
                set_ops[dst_key] = lead[src_key]
        push_events: List[Dict[str, Any]] = []
        if lead_notes:
            push_events.append({
                "id": new_id(), "ts": now, "kind": "note_from_lead",
                "text": lead_notes, "lead_id": lead["id"],
            })
        for ev in lead_timeline:
            push_events.append({
                "id": new_id(), "ts": ev.get("ts") or now,
                "kind": "lead_history", "original": ev,
                "lead_id": lead["id"],
            })
        ops: Dict[str, Any] = {}
        if set_ops:
            ops["$set"] = set_ops
        if push_events:
            ops["$push"] = {"timeline": {"$each": push_events}}
        if ops:
            await db.customers.update_one(
                {"id": cid, "tenant_id": tenant_id}, ops,
            )
    else:
        # ─────────── Create branch
        cid = new_id()
        events: List[Dict[str, Any]] = []
        if lead_notes:
            events.append({
                "id": new_id(), "ts": now, "kind": "note_from_lead",
                "text": lead_notes, "lead_id": lead["id"],
            })
        for ev in lead_timeline:
            events.append({
                "id": new_id(), "ts": ev.get("ts") or now,
                "kind": "lead_history", "original": ev,
                "lead_id": lead["id"],
            })
        events.append({
            "id": new_id(), "ts": now,
            "kind": "created_from_lead", "lead_id": lead["id"],
        })
        customer_doc = {
            "id": cid, "tenant_id": tenant_id,
            "name": lead.get("name") or "Unknown",
            "email": lead.get("email") or "",
            "phone": lead.get("phone") or "",
            "address": lead.get("service_address") or lead.get("address") or "",
            "gate_code": "", "notes": lead_notes,
            "created_at": now, "timeline": events,
        }
        await db.customers.insert_one(customer_doc)
        existing = customer_doc

    # ─────────── Mark lead converted + archived
    await db.leads.update_one(
        {"id": lead["id"], "tenant_id": tenant_id},
        {"$set": {"status": "Closed Won", "closed_at": now,
                    "archived_at": now,
                    "converted_customer_id": cid,
                    "updated_at": now},
         "$push": {"timeline": _timeline_entry(
             "converted_to_customer", actor_user_id=actor_user_id,
             customer_id=cid, was_merged=was_merged,
         )}},
    )

    # ─────────── LEAD-CREATE-QUOTE · Feb-2026 — Reparent lead-recipient
    # quotes (and invoices — ``db.quotes`` holds both doc_types) onto
    # the newly-materialised customer. Phase-2 Quote-to-Lead
    # Recipient ships customer_id=None on these docs; without this
    # reparent, revenue/aging/portal queries that scope by
    # ``customer_id`` would silently miss everything the lead was
    # quoted BEFORE conversion.
    #
    # Full-reparent write shape (G2=c per ticket brief):
    #   * customer_id          → cid           (fills Phase-2 null)
    #   * recipient_type       → "customer"    (flips polymorphic tag)
    #   * recipient_id         → cid           (new owner)
    #   * converted_from_lead_id → <lid>       (provenance preserved
    #                                           for audit + future
    #                                           drill-down)
    #
    # Idempotent at TWO layers:
    #   1. The pipeline-level ``converted_customer_id`` short-circuit
    #      at the top of this function already prevents a second
    #      pipeline run.
    #   2. The filter is scoped to ``recipient_type="lead" +
    #      recipient_id=<lid>``; a second call (e.g. if the pipeline
    #      is retried mid-notification) finds zero matching docs
    #      because the first reparent flipped the recipient_type to
    #      "customer".  modified_count==0 on retry.
    try:
        _reparent_result = await db.quotes.update_many(
            {"tenant_id": tenant_id, "recipient_type": "lead",
             "recipient_id": lead["id"]},
            {"$set": {
                "customer_id": cid,
                "recipient_type": "customer",
                "recipient_id": cid,
                "converted_from_lead_id": lead["id"],
            }},
        )
        logger.info(
            "[phase8] close-won reparented %d lead-recipient quotes/"
            "invoices lead_id=%s → customer_id=%s",
            int(_reparent_result.modified_count or 0),
            lead["id"], cid,
        )
    except Exception as _exc:  # pragma: no cover - defensive
        # Reparent is best-effort — a Mongo hiccup here should NOT
        # block the welcome bundle + referral hook below. The lead
        # is already flagged ``converted_customer_id`` so a repair
        # script can re-run the same ``update_many`` safely.
        logger.warning(
            "[phase8] quote reparent failed lead_id=%s → %s: %s",
            lead["id"], cid, _exc,
        )

    # ─────────── Notifications (best-effort, non-blocking)
    email_id, sms_id, drip_id = None, None, None
    try:
        from services.lead_conversion_notifications import fire_welcome_bundle
        result = await fire_welcome_bundle(
            tenant_id=tenant_id, lead=lead, customer=existing,
            actor_user_id=actor_user_id,
        )
        email_id = result.get("email_id")
        sms_id = result.get("sms_id")
        drip_id = result.get("drip_enrollment_id")
    except Exception as exc:
        logger.warning(f"[phase8] welcome bundle failed: {exc}")

    # ─────────── Slice O.2 · Referral reward hook (pre-existing).
    # Fires only for referral-sourced leads; no-op otherwise. Kept
    # separate from the welcome bundle so referral thank-you emails
    # continue to land even for leads that skipped the M5c drip.
    try:
        from routers.referral_rewards import fire_referral_conversion_hook
        await fire_referral_conversion_hook(
            tenant_id=tenant_id, lead=lead, new_customer_id=cid,
        )
    except Exception as exc:
        logger.warning(f"[leads] referral hook failed: {exc}")

    return {"customer_id": cid, "was_merged": was_merged,
             "notifications": {"email": email_id, "sms": sms_id,
                                 "drip_enrollment_id": drip_id},
             "idempotent": False}


@router.post("/leads/{lid}/close-won")
@router.post("/leads/{lid}/convert-to-customer")
async def close_won(lid: str,
                      user: dict = Depends(get_current_user),
                      tenant: dict = Depends(get_current_tenant)):
    _require_leads_role(user)
    lead = await db.leads.find_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not lead:
        raise HTTPException(404, "Lead not found")
    result = await _run_close_won_pipeline(lead, tenant["id"],
                                              actor_user_id=user.get("id"))
    return {"ok": True, **result}


# Legacy alias — the pre-Phase-8 ``/convert`` endpoint kept working.
@router.post("/leads/{lid}/convert")
async def convert_lead(lid: str,
                         user: dict = Depends(get_current_user),
                         tenant: dict = Depends(get_current_tenant)):
    _require_leads_role(user)
    lead = await db.leads.find_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not lead:
        raise HTTPException(404, "Lead not found")
    result = await _run_close_won_pipeline(lead, tenant["id"],
                                              actor_user_id=user.get("id"))
    # Return the customer doc for backward compatibility with old callers.
    cust = await db.customers.find_one(
        {"id": result["customer_id"]}, {"_id": 0},
    )
    return cust or {"id": result["customer_id"]}


# ═══════════════════════════ Legacy shortcuts ═══════════════════════
async def _ensure_customer_from_lead(lead: dict, tenant_id: str) -> dict:
    """Find or create a customer for the legacy convert-to-job/quote
    shortcuts — bypasses the full conversion pipeline so it doesn't
    trigger welcome notifications (those routes are Phase-2 helpers,
    not the modern conversion path)."""
    existing = await _match_customer_for_conversion(tenant_id, lead)
    if existing:
        return existing
    cust = {
        "id": new_id(), "tenant_id": tenant_id,
        "name": lead.get("name") or "Unknown",
        "email": lead.get("email") or "",
        "phone": lead.get("phone") or "",
        "address": lead.get("service_address") or lead.get("address") or "",
        "gate_code": "", "notes": lead.get("notes") or "",
        "created_at": now_iso(),
    }
    await db.customers.insert_one(cust)
    cust.pop("_id", None)
    return cust


@router.post("/leads/{lid}/convert-to-job")
async def convert_lead_to_job(lid: str, body: ConvertJobIn,
                                 user: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    lead = await db.leads.find_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not lead:
        raise HTTPException(404, "Lead not found")
    cust = await _ensure_customer_from_lead(lead, tenant["id"])
    price = body.price if body.price is not None else float(lead.get("est_value") or 0)
    tech_name = tech_avatar = None
    if body.technician_id:
        tech = await db.technicians.find_one(
            {"id": body.technician_id, "tenant_id": tenant["id"]},
            {"_id": 0},
        )
        tech_name = tech["name"] if tech else None
        tech_avatar = tech.get("avatar", "") if tech else ""
    job = {
        "id": new_id(), "tenant_id": tenant["id"],
        "customer_id": cust["id"], "customer_name": cust["name"],
        "address": cust.get("address", ""),
        "service_type": body.service_type or "Pool Service",
        "scheduled_date": body.scheduled_date,
        "notes": lead.get("notes", ""),
        "technician_id": body.technician_id, "technician_name": tech_name,
        "technician_avatar": tech_avatar, "price": price,
        "status": "pending", "photos": [], "created_at": now_iso(),
    }
    await db.jobs.insert_one(job)
    await db.leads.update_one(
        {"id": lid, "tenant_id": tenant["id"]},
        {"$set": {"status": "Quoted",
                    "converted": {"type": "job", "id": job["id"]},
                    "updated_at": now_iso()}},
    )
    job.pop("_id", None)
    return job


@router.post("/leads/{lid}/convert-to-quote")
async def convert_lead_to_quote(lid: str, body: ConvertQuoteIn,
                                   user: dict = Depends(require_admin),
                                   tenant: dict = Depends(get_current_tenant)):
    lead = await db.leads.find_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not lead:
        raise HTTPException(404, "Lead not found")
    cust = await _ensure_customer_from_lead(lead, tenant["id"])
    up = body.unit_price if body.unit_price is not None else float(lead.get("est_value") or 0)
    title = body.title or f"Estimate for {lead['name']}"
    line_items = [{"description": lead.get("notes") or title,
                     "quantity": 1, "unit_price": up}]
    subtotal = round(up, 2)
    tax = round(subtotal * ((body.tax_rate or 0) / 100.0), 2)
    total = round(subtotal + tax, 2)
    quote = {
        "id": new_id(), "tenant_id": tenant["id"],
        "customer_id": cust["id"], "customer_name": cust["name"],
        "title": title, "doc_type": "quote", "line_items": line_items,
        "tax_rate": body.tax_rate or 0, "subtotal": subtotal, "tax": tax,
        "total": total, "status": "sent", "payment_status": "unpaid",
        "notes": lead.get("notes", ""), "created_at": now_iso(),
    }
    await db.quotes.insert_one(quote)
    await db.leads.update_one(
        {"id": lid, "tenant_id": tenant["id"]},
        {"$set": {"status": "Quoted",
                    "converted": {"type": "quote", "id": quote["id"]},
                    "updated_at": now_iso()}},
    )
    quote.pop("_id", None)
    return quote


@router.delete("/leads/{lid}")
async def delete_lead(lid: str,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    # Phase P6 · Feb-2026 — retrofit the pre-P6 hard-delete so
    # every lead removal — single OR bulk — leaves a full snapshot
    # in ``deletion_audit`` (parity with the invoice / payment /
    # customer flows).  Order is snapshot-then-delete so a failed
    # audit write blocks the destructive op.  ``bulk_op_id=None``
    # for single-row calls; the bulk endpoint below stamps a shared
    # UUID on every row it audits.
    from routers.deletion_audit import write_deletion_audit_entry

    lead = await db.leads.find_one(
        {"id": lid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not lead:
        # Idempotent 200 (matches the pre-P6 shape: 200 w/ deleted:0
        # when the id was already gone).  No audit row on a no-op.
        return {"ok": True, "deleted": 0}

    audit_id = await write_deletion_audit_entry(
        tenant_id=tenant["id"],
        resource_type="lead",
        resource_id=lid,
        user=user,
        snapshot=lead,
        cascade_deleted_ids=[],
        bulk_op_id=None,
    )
    if not audit_id:
        # ``write_deletion_audit_entry`` returns "" on write failure
        # and logs the exception.  The P6 order-of-operations rule
        # says "audit first, then delete" — abort the delete rather
        # than lose the audit trail.
        raise HTTPException(500, "audit_write_failed")

    try:
        res = await db.leads.delete_one(
            {"id": lid, "tenant_id": tenant["id"]},
        )
    except Exception as exc:                          # noqa: BLE001
        # Best-effort audit rollback so a stray audit row doesn't
        # imply a delete that never happened.  If the rollback
        # itself fails we log and let the caller retry — the audit
        # row is still safer than a phantom delete.
        try:
            await db.deletion_audit.delete_one({"id": audit_id})
        except Exception as rb_exc:                    # noqa: BLE001
            logger.error(
                "delete_lead: audit rollback failed for audit_id=%s: %s",
                audit_id, rb_exc,
            )
        raise HTTPException(500, f"delete_failed: {exc}")

    return {"ok": True, "deleted": res.deleted_count}


# ═════════════════════════════════════════════════════════════════════════
# Phase 34 · Task BB · Feb 2026 — Leads bulk-select soft-delete.
# Mirrors the shared pattern in routers/quotes.py + routers/estimates.py.
# Guardrails:
#   * Refuse leads that have already been converted (converted_customer_id
#     is set) — deleting them would orphan the downstream customer/job.
#     Admins wanting to clean up should archive instead.
#   * Refuse leads with converted_job_id, converted_quote_id or an active
#     follow-up task (open_task_ids non-empty) for the same reason.
# ═════════════════════════════════════════════════════════════════════════
from pydantic import BaseModel as _LeadBulkBase


class _LeadBulkDeleteIn(_LeadBulkBase):
    # Phase 34 · Task EE — either explicit ``ids`` OR the filter shape.
    ids: Optional[List[str]] = None
    query_selector: Optional[Dict[str, Any]] = None
    exclude_ids: Optional[List[str]] = None


_LEAD_BULK_DELETE_CAP = 400  # Phase 34 · Task DD · raised 100 → 400


async def _perform_soft_delete_lead(lid: str, user: dict, tenant: dict) -> dict:
    doc = await db.leads.find_one(
        {"id": lid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "deleted_at": 1, "status": 1,
         "converted_customer_id": 1, "converted_job_id": 1,
         "converted_quote_id": 1, "open_task_ids": 1},
    )
    if not doc:
        raise HTTPException(404, "Lead not found")
    if doc.get("deleted_at"):
        return {"ok": True, "id": lid, "already_deleted": True}
    # Converted-lead protection — do not orphan downstream records.
    # Phase 34 · Task CC · Feb 2026 — status enum standardization.
    # ``closed_won`` leads with linked jobs/customers are protected;
    # ``closed_lost`` can be freely bulk-deleted (no downstream state
    # to preserve).
    if (doc.get("converted_customer_id")
        or doc.get("converted_job_id")
        or doc.get("converted_quote_id")
        or (doc.get("status") or "").lower() == "closed_won"):
        raise HTTPException(
            409,
            "Closed–Won leads (with linked jobs/customers) cannot be bulk-deleted — archive instead to preserve the audit trail",
        )
    open_tasks = doc.get("open_task_ids") or []
    if isinstance(open_tasks, list) and open_tasks:
        raise HTTPException(
            409,
            f"Lead has {len(open_tasks)} open follow-up task(s) — close or reassign them first",
        )
    deleted_at = now_iso()
    await db.leads.update_one(
        {"id": lid, "tenant_id": tenant["id"]},
        {"$set": {"deleted_at": deleted_at,
                    "deleted_by_user_id": user.get("id")}},
    )
    try:
        await db.audit_log.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "action": "lead.soft_delete",
            "target_id": lid,
            "at": deleted_at,
        })
    except Exception as e:
        logger.warning(f"lead.soft_delete audit failed: {e}")
    return {"ok": True, "id": lid, "deleted_at": deleted_at}


@router.post("/leads/{lid}/soft-delete",
              operation_id="leads.softDelete")
async def soft_delete_lead(lid: str,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    return await _perform_soft_delete_lead(lid, user, tenant)


@router.post("/leads/bulk-delete",
              operation_id="leads.bulkDelete")
async def bulk_delete_leads(body: _LeadBulkDeleteIn,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    # Phase 34 · Task EE — accept either explicit ``ids`` OR the
    # ``query_selector`` shape. ``_resolve_ids_from_selector`` is defined
    # further down in this module (bulk-update-status uses the same
    # helper).
    if body.query_selector is not None:
        ids = await _resolve_ids_from_selector(
            body.query_selector, body.exclude_ids or [], tenant["id"],
        )
    else:
        ids = list(body.ids or [])
    if not ids:
        raise HTTPException(400, "ids is empty")
    if len(ids) > _LEAD_BULK_DELETE_CAP:
        raise HTTPException(400, f"bulk-delete capped at {_LEAD_BULK_DELETE_CAP} rows per call")
    deleted: List[str] = []
    failed: List[dict] = []
    for lid in ids:
        try:
            r = await _perform_soft_delete_lead(lid, user, tenant)
            deleted.append(r["id"])
        except HTTPException as e:
            failed.append({"id": lid, "reason": str(e.detail),
                              "status_code": e.status_code})
        except Exception as e:                                # noqa: BLE001
            failed.append({"id": lid, "reason": str(e), "status_code": 500})
    return {"ok": True, "deleted_count": len(deleted),
              "deleted": deleted, "failed": failed}


# ═════════════════════════════════════════════════════════════════════════
# Phase LD1 · Feb 2026 — Leads bulk HARD delete.
#
# The Task-BB ``bulk-delete`` endpoint above is a SOFT delete
# (``deleted_at`` timestamp; recoverable). Admins asked for a
# permanent purge path for scrubbing junk / duplicate leads that
# will never be restored. This endpoint is deliberately kept
# separate so the soft-delete tests / mobile clients / archive
# tab semantics are untouched.
#
# Guardrails identical to the soft-delete helper: converted leads
# (``converted_customer_id`` / ``converted_job_id`` / ``converted_quote_id``
# / status ``closed_won``) and leads with open follow-up tasks are
# refused — the UI surfaces those in ``results[]`` with ``ok=false``
# and a human-readable ``reason`` so admins see exactly why a row
# was skipped.
#
# Role gate: ``require_admin`` (admin / super_admin / owner).
# Managers are intentionally NOT allowed — hard delete is
# irrecoverable.
# ═════════════════════════════════════════════════════════════════════════


class _LeadBulkHardDeleteIn(_LeadBulkBase):
    """Phase LD1 · new distinct payload shape (``lead_ids``) so the
    endpoint contract can't be confused with the soft-delete's
    ``ids`` selector shape.

    Phase P6 · Feb-2026 — additional optional ``deletion_reason``
    passed through to the ``deletion_audit`` snapshot so admins
    can annotate WHY a batch was purged.  Legacy callers may omit
    it.
    """
    lead_ids: List[str]
    deletion_reason: Optional[str] = None


# Phase P6 · Feb-2026 — bulk-hard-delete cap tightened from the
# soft-delete's 400 down to 100. The pair is intentionally
# asymmetric: a permanent purge deserves a smaller blast radius
# per call.
_LEAD_BULK_HARD_DELETE_CAP = 100


async def _hard_delete_lead(
    lid: str, actor: dict, tenant_id: str,
    bulk_op_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Single-row hard delete with converted-lead / open-tasks
    guardrails, tenant-scoped, audit-first, delete-second.

    Phase P6 · Feb-2026 — response shape aligned to the bulk
    endpoint's ``skipped[]`` codes so partial-failure batches can
    build their response without translating strings.  Also
    switched from the legacy ``audit_log`` collection to the
    canonical ``deletion_audit`` collection via
    ``write_deletion_audit_entry`` — same one the invoice /
    payment / customer hard-deletes use — so every hard-delete
    in the app funnels through one audit pipeline.  The legacy
    ``audit_log`` write is kept as a best-effort side channel so
    downstream analytics jobs that read from it don't silently
    lose the "lead.hard_delete" action.

    Returns exactly ONE of these two shapes:
      * ``{"lead_id", "ok": True, "deleted_at", "audit_id"}``
      * ``{"lead_id", "ok": False, "code": <c>}`` where ``<c>``
        is one of the P6 whitelist:
          - ``"not_found_or_cross_tenant"``  (also swallows
            audit-write / delete-race internal failures — the
            server-side ``logger.error`` keeps them observable
            without leaking the failure mode to the caller).
          - ``"converted_lock"``
          - ``"open_tasks_lock"``

    Never raises; always returns a dict.
    """
    from routers.deletion_audit import write_deletion_audit_entry

    # ── Step 1: tenant + not-found check.
    full_doc = await db.leads.find_one(
        {"id": lid, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not full_doc:
        return {"lead_id": lid, "ok": False,
                 "code": "not_found_or_cross_tenant"}

    # ── Step 2: converted-lock (Closed-Won w/ downstream state).
    if (full_doc.get("converted_customer_id")
        or full_doc.get("converted_job_id")
        or full_doc.get("converted_quote_id")
        or (full_doc.get("status") or "").lower() == "closed_won"):
        return {"lead_id": lid, "ok": False, "code": "converted_lock"}

    # ── Step 3: open-tasks-lock.
    open_tasks = full_doc.get("open_task_ids") or []
    if isinstance(open_tasks, list) and open_tasks:
        return {"lead_id": lid, "ok": False,
                 "code": "open_tasks_lock"}

    # ── Step 4: audit write FIRST (order-of-operations from the
    #    P6 brief — if this fails we do NOT delete).
    audit_id = await write_deletion_audit_entry(
        tenant_id=tenant_id,
        resource_type="lead",
        resource_id=lid,
        user=actor or {},
        snapshot=full_doc,
        cascade_deleted_ids=[],
        bulk_op_id=bulk_op_id,
    )
    if not audit_id:
        # Helper already logged the exception.  Block the delete
        # rather than lose the audit trail.  Surface as the
        # ambiguous whitelisted code — the failure mode is a
        # server-side infra problem, not a client-observable
        # distinction.
        logger.error(
            "_hard_delete_lead: audit write failed lead_id=%s "
            "tenant_id=%s bulk_op_id=%s — treating as "
            "not_found_or_cross_tenant on the wire",
            lid, tenant_id, bulk_op_id,
        )
        return {"lead_id": lid, "ok": False,
                 "code": "not_found_or_cross_tenant"}

    # ── Step 5: delete SECOND.
    deleted_at = now_iso()
    try:
        res = await db.leads.delete_one(
            {"id": lid, "tenant_id": tenant_id},
        )
    except Exception as exc:                          # noqa: BLE001
        # Best-effort rollback of the audit row so a stray audit
        # doesn't imply a delete that never happened.
        try:
            await db.deletion_audit.delete_one({"id": audit_id})
        except Exception as rb_exc:                    # noqa: BLE001
            logger.error(
                "_hard_delete_lead: audit rollback failed "
                "audit_id=%s lead_id=%s: %s", audit_id, lid, rb_exc,
            )
        logger.error(
            "_hard_delete_lead: delete_one raised lead_id=%s: %s",
            lid, exc,
        )
        return {"lead_id": lid, "ok": False,
                 "code": "not_found_or_cross_tenant"}

    if res.deleted_count == 0:
        # Race — doc disappeared between our find_one and delete_one.
        # Roll back the audit row so it stays 1:1 with reality.
        try:
            await db.deletion_audit.delete_one({"id": audit_id})
        except Exception as rb_exc:                    # noqa: BLE001
            logger.error(
                "_hard_delete_lead: audit rollback (race) failed "
                "audit_id=%s lead_id=%s: %s", audit_id, lid, rb_exc,
            )
        return {"lead_id": lid, "ok": False,
                 "code": "not_found_or_cross_tenant"}

    # ── Step 6: best-effort side channel to the legacy
    #    ``audit_log`` collection so pre-existing analytics jobs
    #    that grep for ``action="lead.hard_delete"`` don't silently
    #    lose the row.  Never blocks the delete on failure.
    try:
        await db.audit_log.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "actor_user_id": (actor or {}).get("id"),
            "actor_email": (actor or {}).get("email"),
            "action": "lead.hard_delete",
            "resource_type": "lead",
            "target_id": lid,
            "deleted_ids": [lid],
            "snapshot": [full_doc],
            "bulk_op_id": bulk_op_id,
            "at": deleted_at,
        })
    except Exception as e:                            # noqa: BLE001
        logger.warning(f"lead.hard_delete legacy audit failed: {e}")

    return {"lead_id": lid, "ok": True,
             "deleted_at": deleted_at, "audit_id": audit_id}


@router.post("/leads/bulk-hard-delete",
              operation_id="leads.bulkHardDelete")
async def bulk_hard_delete_leads(body: _LeadBulkHardDeleteIn,
                                    user: dict = Depends(require_admin),
                                    tenant: dict = Depends(get_current_tenant)):
    """Phase P6 · Feb-2026 — Leads bulk hard delete on the selection bar.

    Response shape:
        {
            "requested": <int>,
            "deleted":   <int>,
            "skipped":   [{"lead_id": "...",
                            "code":
                              "not_found_or_cross_tenant" |
                              "converted_lock" |
                              "open_tasks_lock"}, ...],
            "bulk_op_id": "<uuid4>",
        }

    Cap: 100 rows per call.  HTTP **422** with
    ``code=empty_ids`` on an empty list, ``code=bulk_cap_exceeded``
    on > 100.  Every successful delete pairs 1:1 with a
    ``deletion_audit`` row stamped with the same ``bulk_op_id`` —
    the batch is queryable as a group.

    The three skip codes are the ONLY values a caller can see on
    the wire.  Internal failures (audit-write failed, delete
    race) fold into ``not_found_or_cross_tenant`` — the
    server-side ``logger.error`` in ``_hard_delete_lead`` keeps
    them observable without leaking the failure mode to the
    caller.
    """
    from uuid import uuid4 as _p6_uuid4

    ids = list(body.lead_ids or [])
    if not ids:
        raise HTTPException(
            422, {"code": "empty_ids",
                    "detail": "lead_ids is required"},
        )
    if len(ids) > _LEAD_BULK_HARD_DELETE_CAP:
        raise HTTPException(
            422,
            {"code": "bulk_cap_exceeded",
              "detail": f"lead_ids cap is {_LEAD_BULK_HARD_DELETE_CAP}",
              "attempted": len(ids),
              "cap": _LEAD_BULK_HARD_DELETE_CAP},
        )

    bulk_op_id = str(_p6_uuid4())
    deleted = 0
    skipped: List[Dict[str, str]] = []

    # De-dupe while preserving order so an accidental duplicate id
    # in the payload doesn't produce two audit rows.
    seen: set = set()
    for lid in ids:
        if lid in seen:
            continue
        seen.add(lid)

        try:
            r = await _hard_delete_lead(
                lid, user, tenant["id"], bulk_op_id=bulk_op_id,
            )
        except Exception as e:                        # noqa: BLE001
            # ``_hard_delete_lead`` is documented "never raises",
            # but defense-in-depth: any escape gets folded into the
            # ambiguous whitelisted code so the batch keeps moving.
            # The audit-first / delete-second order guarantees no
            # lead was mutated on this path.
            logger.error(
                "bulk_hard_delete_leads: unexpected error lead_id=%s: %s",
                lid, e,
            )
            skipped.append(
                {"lead_id": lid,
                  "code": "not_found_or_cross_tenant"},
            )
            continue

        if r.get("ok"):
            deleted += 1
        else:
            skipped.append(
                {"lead_id": lid,
                  "code": r.get("code")
                            or "not_found_or_cross_tenant"},
            )

    return {
        "requested": len(ids),
        "deleted": deleted,
        "skipped": skipped,
        "bulk_op_id": bulk_op_id,
    }


# ═════════════════════════════════════════════════════════════════════════
# Phase 34 · Task HH · Feb 2026 — Leads bulk status change.
# Change many leads to a canonical status in one call. Same role gate /
# tenant scope / cap / audit-log as the bulk-delete endpoints. Uses the
# canonical enum from Task CC — anything outside the five values 422s.
#
# Task EE · Feb 2026 — this endpoint also accepts the filter-selector
# shape ``{query_selector, exclude_ids, new_status}`` so the "Select all
# N matching this filter" UX can operate without listing every id. The
# selector is sanitised server-side — only whitelisted keys pass through
# (status, source_kind, search, has_email, has_phone) — and the resolved
# set is capped at 400 rows to match Task DD.
# ═════════════════════════════════════════════════════════════════════════


class _LeadBulkStatusIn(_LeadBulkBase):
    ids: Optional[List[str]] = None
    query_selector: Optional[Dict[str, Any]] = None
    exclude_ids: Optional[List[str]] = None
    new_status: str


_QUERY_SELECTOR_ALLOWED_KEYS = {"status", "source_kind", "search",
                                 "has_email", "has_phone"}


async def _resolve_ids_from_selector(selector: Dict[str, Any],
                                       exclude_ids: List[str],
                                       tenant_id: str) -> List[str]:
    """Task EE — safely translate the frontend's filter shape into a
    concrete list of lead ids. Only whitelisted keys are honoured; the
    query is always tenant-scoped and always skips soft-deleted rows."""
    q: Dict[str, Any] = {"tenant_id": tenant_id,
                            "$and": [{"$or": [{"deleted_at": None},
                                                  {"deleted_at": {"$exists": False}}]}]}
    clean: Dict[str, Any] = {}
    for k, v in (selector or {}).items():
        if k not in _QUERY_SELECTOR_ALLOWED_KEYS:
            continue
        clean[k] = v
    if clean.get("status") and clean["status"] != "all":
        q["status"] = _normalize_status(clean["status"])
    if clean.get("source_kind"):
        q["source_kind"] = clean["source_kind"]
    if clean.get("has_email"):
        q["email"] = {"$nin": [None, ""]}
    if clean.get("has_phone"):
        q["phone"] = {"$nin": [None, ""]}
    if clean.get("search"):
        s = str(clean["search"]).strip()
        if s:
            q.setdefault("$and", []).append({
                "$or": [
                    {"name": {"$regex": s, "$options": "i"}},
                    {"email": {"$regex": s, "$options": "i"}},
                    {"phone": {"$regex": s, "$options": "i"}},
                ]
            })
    ids: List[str] = []
    excl = set(exclude_ids or [])
    async for row in db.leads.find(q, {"_id": 0, "id": 1}).limit(_LEAD_BULK_DELETE_CAP + 1):
        rid = row.get("id")
        if rid and rid not in excl:
            ids.append(rid)
    return ids


@router.post("/leads/bulk-update-status",
              operation_id="leads.bulkUpdateStatus")
async def bulk_update_lead_status(body: _LeadBulkStatusIn,
                                       user: dict = Depends(require_admin),
                                       tenant: dict = Depends(get_current_tenant)):
    """Bulk-set the status on many leads. Accepts either an explicit
    ``ids`` list OR the Task EE ``query_selector`` shape.

    * ``new_status`` must be one of the canonical five values (Task CC).
    * Cap enforced at 400 (Task DD).
    * Leads already at ``new_status`` are surfaced in ``failed[]`` with
      a friendly reason so the UI can toast "3 already at Closed–Won"
      without treating them as errors.
    """
    # Validate canonical status FIRST — cheap check, fail fast.
    if body.new_status not in _CANONICAL_STATUSES:
        raise HTTPException(
            422,
            f"new_status must be one of {sorted(_CANONICAL_STATUSES)}",
        )

    # Resolve the target id list — either explicit OR via selector.
    if body.query_selector is not None:
        ids = await _resolve_ids_from_selector(
            body.query_selector, body.exclude_ids or [], tenant["id"],
        )
    else:
        ids = list(body.ids or [])
    if not ids:
        raise HTTPException(400, "ids is empty")
    if len(ids) > _LEAD_BULK_DELETE_CAP:
        raise HTTPException(
            400,
            f"bulk-update-status capped at {_LEAD_BULK_DELETE_CAP} rows per call",
        )

    updated: List[str] = []
    failed: List[dict] = []
    for lid in ids:
        try:
            doc = await db.leads.find_one(
                {"id": lid, "tenant_id": tenant["id"]},
                {"_id": 0, "id": 1, "status": 1, "deleted_at": 1},
            )
            if not doc:
                failed.append({"id": lid, "reason": "Lead not found",
                                  "status_code": 404})
                continue
            if doc.get("deleted_at"):
                failed.append({"id": lid, "reason": "Lead is soft-deleted",
                                  "status_code": 409})
                continue
            current = doc.get("status")
            if current == body.new_status:
                failed.append({"id": lid,
                                  "reason": f"already {body.new_status}",
                                  "status_code": 200})
                continue
            update_ts = now_iso()
            await db.leads.update_one(
                {"id": lid, "tenant_id": tenant["id"]},
                {"$set": {"status": body.new_status,
                            "status_updated_at": update_ts,
                            "status_updated_by_user_id": user.get("id")}},
            )
            try:
                await db.audit_log.insert_one({
                    "id": new_id(),
                    "tenant_id": tenant["id"],
                    "actor_user_id": user.get("id"),
                    "actor_email": user.get("email"),
                    "action": "lead.bulk_status_change",
                    "target_id": lid,
                    "from_status": current,
                    "to_status": body.new_status,
                    "at": update_ts,
                })
            except Exception as ae:
                logger.warning(f"lead.bulk_status_change audit failed: {ae}")
            updated.append(lid)
        except HTTPException as e:
            failed.append({"id": lid, "reason": str(e.detail),
                              "status_code": e.status_code})
        except Exception as e:                                # noqa: BLE001
            failed.append({"id": lid, "reason": str(e), "status_code": 500})
    return {"ok": True, "updated_count": len(updated),
              "updated": updated, "failed": failed,
              "new_status": body.new_status}




# ═══════════════════════════ PUBLIC INTAKE ══════════════════════════
@router.post("/public/leads")
async def public_lead_intake(body: PublicLeadIn,
                                request: "Request",
                                background_tasks: BackgroundTasks):
    """Phase 8 · Feb 2026 — public leads intake.

    * NO auth required.
    * Cloudflare Turnstile token required when ``TURNSTILE_SECRET_KEY``
      is populated (unset in dev/preview).
    * **Origin allowlist enforced (Phase 9 hotfix).** The request MUST
      carry an ``Origin`` (or ``Referer`` as fallback) that matches
      either:
        · ``tenant.widget_allowed_domains`` (shared with the widget),
          or
        · ``$PUBLIC_LEADS_ORIGIN_ALLOWLIST`` env (comma-separated),
      unioned. Empty allowlist == deny-by-default, matching the widget
      posture. To bypass in local dev, set ``ALLOW_TEST_HOOKS=1``
      explicitly (logged as a warning so it's obvious in tenant logs).
    * ``source`` is force-tagged ``website_form``.
    * Per-IP rate limit (10/min/IP).
    * Response NEVER leaks internal fields (only ``{ok, lead_id}``).
    """
    import os as _os
    # Rate limit (early — cheap check).
    ip = ""
    try:
        ip = request.client.host if request.client else ""
    except Exception:
        ip = ""
    if ip:
        await _rate_limit_public_leads(ip)

    # Resolve tenant now so we can consult widget_allowed_domains.
    tenant = await db.tenants.find_one(
        {"slug": "aquaterra", "active": {"$ne": False}},
        {"_id": 0, "id": 1, "widget_allowed_domains": 1},
    )
    if not tenant:
        raise HTTPException(500, "No tenant available")

    # ─────────── Origin allowlist enforcement
    origin = (request.headers.get("origin") or "").strip()
    referer = (request.headers.get("referer") or "").strip()
    x_fwd_origin = (request.headers.get("x-forwarded-origin") or "").strip()
    # Phase 18 hotfix (follow-up) · Feb-2026 — Cloudflare Worker at
    # preview.emergentagent.com rewrites the ``Origin`` header to the
    # internal cluster hostname (…cluster-12.preview.emergentcf.cloud)
    # before it reaches FastAPI, so the browser-supplied public origin
    # is preserved ONLY in ``X-Forwarded-Host``. Add a synthesized
    # candidate ``https://{x-forwarded-host}`` so the tenant allowlist
    # (which lists the public host) can still match.
    x_fwd_host = (request.headers.get("x-forwarded-host") or "").strip()
    x_fwd_proto = (request.headers.get("x-forwarded-proto") or "https").strip()
    x_fwd_host_origin = f"{x_fwd_proto}://{x_fwd_host}" if x_fwd_host else ""
    env_allow = {o.strip() for o in
                    (_os.environ.get("PUBLIC_LEADS_ORIGIN_ALLOWLIST") or "").split(",")
                    if o.strip()}
    tenant_allow = {d.strip() for d in
                       (tenant.get("widget_allowed_domains") or [])
                       if d and d.strip()}
    allowed = env_allow | tenant_allow
    if _os.environ.get("ALLOW_TEST_HOOKS") == "1" and not allowed:
        logger.warning(
            "[public-leads] Origin allowlist BYPASSED — ALLOW_TEST_HOOKS=1 "
            "and no allowlist configured. Configure "
            "tenant.widget_allowed_domains before going to production."
        )
    else:
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail="Origin allowlist not configured for this tenant",
            )
        candidates = [c for c in (origin, x_fwd_origin, x_fwd_host_origin, referer) if c]
        if not candidates:
            raise HTTPException(
                status_code=403,
                detail="Missing Origin/Referer header",
            )

        def _matches(candidate: str) -> bool:
            candidate = candidate.rstrip("/")
            # Phase 18 hotfix · Feb-2026 — normalize scheme + trailing
            # slash on BOTH sides so a bare-host allowlist entry
            # ("example.com") matches a schemed browser Origin
            # ("https://example.com"). This is the root cause of the
            # "webform not creating leads" bug — allowlists in
            # ``tenant.widget_allowed_domains`` are stored bare, but
            # browsers always send ``https://…``.
            def _host(s: str) -> str:
                s = s.strip().rstrip("/")
                for prefix in ("https://", "http://"):
                    if s.startswith(prefix):
                        s = s[len(prefix):]
                        break
                # Strip any path component so a Referer with a path
                # still compares by host.
                s = s.split("/", 1)[0]
                return s.lower()
            cand_host = _host(candidate)
            for a in allowed:
                a2 = a.rstrip("/")
                if candidate == a2 or candidate.startswith(a2 + "/"):
                    return True
                if cand_host and cand_host == _host(a2):
                    return True
            return False
        if not any(_matches(c) for c in candidates):
            raise HTTPException(
                status_code=403,
                detail="Origin not allowed",
            )
    # Turnstile.
    ts_secret = _os.environ.get("TURNSTILE_SECRET_KEY") or ""
    if ts_secret:
        if not (body.turnstile_token or ""):
            raise HTTPException(400, "Turnstile token required")
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                    data={"secret": ts_secret,
                           "response": body.turnstile_token,
                           "remoteip": ip},
                )
                if not (r.json() or {}).get("success"):
                    raise HTTPException(400, "Turnstile verification failed")
        except HTTPException:
            raise
        except Exception as exc:  # pragma: no cover
            logger.warning(f"[public-leads] turnstile check errored: {exc}")

    # Payload validation.
    if not (body.name or "").strip():
        raise HTTPException(400, "Name is required")
    if not (body.email or "").strip() and not (body.phone or "").strip():
        raise HTTPException(400, "One of email or phone is required")
    # Feb-2026 · widened acceptance — see ``_normalize_interest``.
    interest = _normalize_interest(body.service_interest)

    now = now_iso()
    lid = new_id()
    # Phase 10 · Feb 2026 — referral capture. Accepts either a body
    # field (``referral_code``) OR a ``?ref=<code>`` query param.
    # Invalid codes are silently dropped so an inquiry is never
    # rejected because a customer mistyped a link.
    referred_by_customer_id: Optional[str] = None
    ref_code_raw = (body.referral_code or "").strip()
    if not ref_code_raw:
        try:
            ref_code_raw = (request.query_params.get("ref") or "").strip()
        except Exception:
            ref_code_raw = ""
    if ref_code_raw:
        ref_upper = ref_code_raw.upper()
        # ``referral_code`` lives on the customer document (see
        # routers/referrals.py::_get_or_create_code). Lookup is
        # case-insensitive and tenant-scoped.
        referrer = await db.customers.find_one(
            {"tenant_id": tenant["id"], "referral_code": ref_upper},
            {"_id": 0, "id": 1},
        )
        if referrer:
            referred_by_customer_id = referrer["id"]
        else:
            logger.info(
                f"[phase10] public-leads received unknown referral_code "
                f"{ref_upper!r} — silently ignoring"
            )

    lead_doc = {
        "id": lid, "tenant_id": tenant["id"],
        "name": body.name.strip(), "email": (body.email or "").strip(),
        "phone": (body.phone or "").strip(),
        "service_address": (body.service_address or "").strip(),
        "service_interest": interest,
        "notes": (body.notes or "").strip(),
        # Feb-2026 · P0 · lat/lng from widget's Places autocomplete.
        "latitude": body.latitude,
        "longitude": body.longitude,
        "source": (
            f"referral_from_customer:{referred_by_customer_id}"
            if referred_by_customer_id else "website_form"
        ),
        "status": "New",
        "created_at": now, "updated_at": now,
        "archived_at": None, "loss_reason": None,
        "converted_customer_id": None,
        "created_by": None,
        "created_ip": ip,
        "referred_by_customer_id": referred_by_customer_id,
        "timeline": [
            _timeline_entry("created",
                              source=("referral_from_customer"
                                       if referred_by_customer_id
                                       else "website_form"),
                              status="New", ip=ip,
                              referrer_id=referred_by_customer_id),
        ],
    }
    await db.leads.insert_one(lead_doc)
    # Feb-2026 · P0 · on-save geocode backfill — skipped when both
    # ``latitude`` and ``longitude`` came in from the widget's
    # autocomplete selection.
    _maybe_backfill_lead_geocode(background_tasks, lead_doc)
    # Feb-2026 · Fire the ``new_lead`` marketing-sequence trigger for
    # public form / referral inbound. Real-time via ``BackgroundTasks``.
    try:
        from services.marketing.lead_triggers import (
            fire_new_lead_sequence_trigger,
        )
        await fire_new_lead_sequence_trigger(
            lead=lead_doc, tenant_id=lead_doc.get("tenant_id") or "",
            background_tasks=background_tasks,
        )
    except Exception:
        pass
    # Phase 16 · Additions E + F · Feb-2026 — same side-effect
    # pipeline the admin create path uses. Runs BEFORE the referral
    # bookkeeping so a rejected out-of-state referral still notifies
    # Brian AND creates the referral pending-conversion row (the
    # referrer earns credit only on close-won, which won't happen
    # for a rejected lead, but the audit trail is clean).
    try:
        from services.leads_side_effects import apply_lead_post_create
        await apply_lead_post_create(lead_doc)
    except Exception as _e:  # pragma: no cover
        logger.warning(f"[public-leads] post-create side effects crashed: {_e}")
    # Phase K63.dispatcher-ingress-fix · Feb-2026 — dispatch the
    # rich per-tenant K63 recipient list (email + SMS fan-out).
    # This is the sixth ingress path — the ``/api/public/leads``
    # widget-form entry — that was missing the hook. Fire-and-
    # forget via BackgroundTasks; a Resend / RingCentral outage
    # cannot bound this handler's response latency and cannot
    # fail the insert. The K63 idempotency table
    # (``lead_notification_dispatches``) still gates repeat sends
    # if the same lead is somehow re-submitted.
    try:
        full_tenant = await db.tenants.find_one(
            {"id": tenant["id"]}, {"_id": 0},
        ) or {}
        from services.lead_notifications import send_lead_alert_notifications
        await send_lead_alert_notifications(
            lead=lead_doc, tenant=full_tenant,
            background_tasks=background_tasks,
        )
    except Exception as _e:  # pragma: no cover
        logger.warning(f"[k63] public-leads dispatch failed: {_e}")
    # Feb-2026 · Admin lead-notification fan-out — see
    # ``services.lead_admin_notifications``. Broadens the recipient
    # set beyond the tenant's explicit K63 rich list to include every
    # admin/manager user + ``business_settings.notification_email`` so
    # a mis-configured K63 list doesn't silently drop inbounds. Dedupe
    # against the K63 fan-out is handled via a distinct ``:admin-fanout``
    # target suffix on the shared idempotency table.
    try:
        from services.lead_admin_notifications import (
            dispatch_admin_lead_email,
        )
        await dispatch_admin_lead_email(
            lead=lead_doc,
            tenant=full_tenant if 'full_tenant' in locals() else (
                await db.tenants.find_one({"id": tenant["id"]},
                                              {"_id": 0}) or {}),
            background_tasks=background_tasks,
        )
    except Exception as _e:  # pragma: no cover
        logger.warning(
            f"[lead-admin-fanout] public-leads dispatch failed: {_e}"
        )
    # If we captured a referrer, ALSO insert a referrals row in
    # ``pending_conversion`` so the admin dashboard reflects the
    # inbound pipeline. The paid-window transition happens on
    # close-won conversion via the existing hook.
    if referred_by_customer_id:
        try:
            await db.referrals.insert_one({
                "id": new_id(),
                "tenant_id": tenant["id"],
                "referrer_customer_id": referred_by_customer_id,
                "lead_id": lid,
                "status": "pending_conversion",
                "created_at": now,
                "updated_at": now,
            })
        except Exception as exc:
            logger.warning(f"[phase10] referrals row insert failed: {exc}")
    return {"ok": True, "lead_id": lid}


# ─── Simple in-process rate limiter for the public intake ────────────
import asyncio  # noqa: E402
import time  # noqa: E402
_PUBLIC_LEADS_RATE = 10
_PUBLIC_LEADS_WINDOW_S = 60.0
_public_hits: Dict[str, List[float]] = {}
_public_lock = asyncio.Lock()


# ─── Feb-2026 · P0 · Lead form address autofill (Google Places) ──────
# On-save geocode fan-out. Skipped when the client already supplied
# ``latitude`` + ``longitude`` (widget autocomplete resolved them),
# so the server never spends a second Places round-trip on a lead
# whose coordinates are already known.
async def _run_lead_geocode(lid: str, tenant_id: str, addr: str) -> None:
    try:
        from services.google_maps.geocoding import geocode_address
        hit = await geocode_address(addr, tenant_id=tenant_id)
        if hit and hit.get("latitude") and hit.get("longitude"):
            await db.leads.update_one(
                {"id": lid, "tenant_id": tenant_id},
                {"$set": {"latitude": hit["latitude"],
                           "longitude": hit["longitude"],
                           "updated_at": now_iso()}},
            )
    except Exception as _e:  # pragma: no cover
        logger.warning(f"[leads] geocode backfill failed for lid={lid}: {_e}")


def _maybe_backfill_lead_geocode(background_tasks: BackgroundTasks,
                                    lead: Dict[str, Any]) -> None:
    """Fire a background geocode ONLY when the lead is missing
    coordinates. Autocomplete-supplied lat/lng short-circuit the call
    so we don't waste a Google Places round-trip we've already done
    client-side."""
    if lead.get("latitude") is not None and lead.get("longitude") is not None:
        return
    addr = (lead.get("service_address") or lead.get("address") or "").strip()
    if not addr:
        return
    background_tasks.add_task(
        _run_lead_geocode, lead["id"], lead["tenant_id"], addr,
    )


async def _rate_limit_public_leads(ip: str) -> None:
    now = time.monotonic()
    async with _public_lock:
        bucket = _public_hits.setdefault(ip, [])
        cutoff = now - _PUBLIC_LEADS_WINDOW_S
        i = 0
        while i < len(bucket) and bucket[i] < cutoff:
            i += 1
        if i:
            del bucket[:i]
        if len(bucket) >= _PUBLIC_LEADS_RATE:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit — max {_PUBLIC_LEADS_RATE}/minute",
            )
        bucket.append(now)


# fastapi.Request re-import at runtime (kept out of top-level imports so
# this file's public surface stays minimal).
from fastapi import Request  # noqa: E402, F401
