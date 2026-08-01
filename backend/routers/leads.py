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

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user, new_id, now_iso, require_admin
from models import *  # noqa: F403,F405  # LeadIn / LeadUpdate / etc.

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
_VALID_INTERESTS = {"Pool", "Landscape", "Both"}
_INBOUND_MANAGER_ROLES = {"admin", "super_admin", "manager"}


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
    if status and status != "all":
        q["status"] = _normalize_status(status)
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
    return row


# ═══════════════════════════ CREATE ═════════════════════════════════
@router.post("/leads")
async def create_lead(body: LeadIn,
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
    interest = body.service_interest
    if interest and interest not in _VALID_INTERESTS:
        interest = None
    doc = body.dict()
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
        "archived_at": None,
        "loss_reason": None,
        "converted_customer_id": None,
        "timeline": [
            _timeline_entry("created", actor_user_id=user.get("id"),
                             source=src, status="New"),
        ],
    })
    await db.leads.insert_one(doc)
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
                "email", "notes"):
        if k in upd and upd[k] is not None:
            fields[k] = upd[k]
    if fields:
        fields["updated_at"] = now_iso()
        ops: Dict[str, Any] = {"$set": fields}
        if new_events:
            ops["$push"] = {"timeline": {"$each": new_events}}
        await db.leads.update_one({"id": lid, "tenant_id": tenant_id}, ops)
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
    res = await db.leads.delete_one(
        {"id": lid, "tenant_id": tenant["id"]},
    )
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
async def public_lead_intake(body: PublicLeadIn, request: "Request"):
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
    interest = body.service_interest
    if interest and interest not in _VALID_INTERESTS:
        interest = None

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
