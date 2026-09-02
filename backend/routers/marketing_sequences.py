"""Feb-2026 · Marketing Slice M5a — Drip sequences: CRUD, enrolment,
tick handler.  Scheduler wiring + event hooks + frontend come in M5b/c.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from config import db, logger
from utils import new_id, now_iso, require_admin
from routers.tenants import get_current_tenant
from services.marketing.render import render_subject_and_body, strip_html, DEFAULT_SAMPLE_CONTEXT
from services.marketing.merge_tags import render_context

router = APIRouter()

TRIGGER_REGISTRY: List[Dict[str, Any]] = [
    {"type": "service_completed",         "config_schema": {}},
    {"type": "invoice_sent",              "config_schema": {}},
    {"type": "invoice_past_due_N_days",   "config_schema": {"days_past_due": "int"}},
    {"type": "customer_created",          "config_schema": {}},
    {"type": "birthday",                  "config_schema": {}},
    {"type": "review_left",               "config_schema": {}},
    # Slice O.2 companion — fires from customer/admin/token accept paths.
    {"type": "estimate_accepted",         "config_schema": {}},
    # Feb-2026 · Day-before service reminder. Fires 24h before a job's
    # ``scheduled_date`` from the daily 09:00 UTC sweep. Applies to
    # BOTH ``work_class == service`` and ``work_class == repair``.
    # Deduped by (tenant, sequence, customer, job_id, scheduled_date)
    # so a re-run on the same day doesn't double-enrol; reschedule
    # after enrol does NOT retroactively "unfire".
    {"type": "job_scheduled_reminder_1d", "config_schema": {}},
    # Feb-2026 · New-lead trigger — fires on ANY lead insert path
    # (widget, public forms, admin POST, RingCentral sync, portal
    # referral, D2D, property intake). Config-less. Fan-out in
    # ``services/marketing/lead_triggers.py::fire_new_lead_sequence_trigger``
    # is real-time via ``BackgroundTasks`` so the parent lead-create
    # response never waits on enrolment latency.
    {"type": "new_lead",                  "config_schema": {}},
    {"type": "manual",                    "config_schema": {}},
    {"type": "segment_join",              "config_schema": {"segment_id": "str"}},
]
_ALLOWED_TRIGGERS = {t["type"] for t in TRIGGER_REGISTRY}


class Step(BaseModel):
    order: int = 0
    channel: str
    template_id: str
    delay_from: str = "previous_step"   # or "trigger"
    delay_hours: int = 24
    condition: Optional[Dict[str, Any]] = None


class SequenceIn(BaseModel):
    name: str
    description: Optional[str] = ""
    trigger_type: str
    trigger_config: Dict[str, Any] = {}
    steps: List[Step] = []
    active: bool = False
    stop_on_reply: bool = True
    stop_on_unsubscribe: bool = True


class SequencePatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    trigger_type: Optional[str] = None
    trigger_config: Optional[Dict[str, Any]] = None
    # Feb 2026 · Phase 2 Custom Trigger Builder — schema-v2 nested
    # trigger doc. Additive: legacy ``trigger_type`` + ``trigger_config``
    # remain accepted so the M5c editor UI keeps working.
    trigger: Optional[Dict[str, Any]] = None
    steps: Optional[List[Step]] = None
    active: Optional[bool] = None
    stop_on_reply: Optional[bool] = None
    stop_on_unsubscribe: Optional[bool] = None


class EnrolIn(BaseModel):
    customer_ids: Optional[List[str]] = None
    segment_id: Optional[str] = None


async def _validate_sequence(tenant_id: str, trigger_type: str, steps: List[Dict[str, Any]]):
    if trigger_type not in _ALLOWED_TRIGGERS:
        raise HTTPException(422, f"Unknown trigger_type {trigger_type!r}")
    for i, s in enumerate(steps):
        ch = s.get("channel")
        tid = s.get("template_id")
        if ch not in ("email", "sms"):
            raise HTTPException(422, f"step[{i}]: channel must be email or sms")
        if not tid:
            raise HTTPException(422, f"step[{i}]: template_id required")
        tpl = await db.marketing_templates.find_one(
            {"id": tid, "tenant_id": tenant_id}, {"_id": 0, "channel": 1, "active": 1},
        )
        if not tpl:
            raise HTTPException(422, f"step[{i}]: template not found")
        if tpl.get("channel") != ch:
            raise HTTPException(
                422,
                f"step[{i}]: channel {ch} doesn't match template channel {tpl.get('channel')}",
            )


# ── Static-path routes first ──────────────────────────────────────────────
@router.get("/marketing/sequences/triggers/registry")
async def triggers_registry(user: dict = Depends(require_admin)):
    return {"triggers": TRIGGER_REGISTRY}


# Feb 2026 · Phase 1 Custom Trigger Builder — canonical event catalog.
#
# Phase 2 UI reads this endpoint to render the "which event fires
# this?" dropdown. The legacy ``/triggers/registry`` above is kept
# UNTOUCHED for backwards compatibility (its consumers still rely on
# the M5c legacy shape). This new endpoint is the source of truth
# going forward and returns every canonical event with the four
# metadata fields the Phase 2 UI needs to render properly.
class EventCatalogItem(BaseModel):
    """Wire shape for one entry in the Phase-1 event catalog.

    Kept explicit (not TypedDict) so FastAPI's ``response_model``
    handler auto-documents these fields in openapi.json — the Phase 2
    UI's client generator picks them up unmodified.
    """
    id: str
    label: str
    entity: str
    scheduled: bool
    allow_negative_offset: bool


class EventCatalogOut(BaseModel):
    events: List[EventCatalogItem]
    count: int


@router.get("/marketing/sequences/event-catalog",
             response_model=EventCatalogOut,
             tags=["marketing_sequences"])
async def event_catalog(user: dict = Depends(require_admin)):
    """Return the full canonical event catalog for the Phase-1
    Custom Trigger Builder.

    Every entry carries the four metadata fields the Phase 2 UI
    needs:

    * ``id``    — canonical wire-format event key (matches
      ``trigger.conditions[i].event``).
    * ``label`` — human-friendly display string for the picker.
    * ``entity`` — which document the event is about (``lead`` /
      ``job`` / ``estimate`` / ``invoice`` / ``customer`` /
      ``payment``). Phase 2 UI groups the picker by this field.
    * ``scheduled`` — whether the event has a native ``scheduled_at``
      (drives whether ``delay: {mode: "before"}`` is a valid choice
      in the UI).
    * ``allow_negative_offset`` — explicit gate for the "before"
      delay mode.

    Sort order is deterministic: primary key ``entity`` (grouping
    lead / job / estimate / invoice / customer / payment), secondary
    key ``id`` alphabetical. Phase 2 UI can render sections cleanly
    without any client-side re-sorting.
    """
    from services.marketing.event_registry import EVENT_CATALOG
    _ENTITY_ORDER = {
        "lead": 0, "estimate": 1, "job": 2,
        "invoice": 3, "payment": 4, "customer": 5,
    }
    rows: List[Dict[str, Any]] = []
    for key, meta in EVENT_CATALOG.items():
        rows.append({
            "id": key,
            "label": meta.get("label") or key,
            "entity": meta.get("entity") or "",
            "scheduled": bool(meta.get("scheduled")),
            "allow_negative_offset": bool(meta.get("allow_negative_offset")),
        })
    rows.sort(key=lambda r: (
        _ENTITY_ORDER.get(r["entity"], 99),
        r["id"],
    ))
    return {"events": rows, "count": len(rows)}


@router.get("/marketing/sequences")
async def list_sequences(
    active: Optional[bool] = Query(None),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if active is not None:
        q["active"] = active
    rows = await db.marketing_sequences.find(q, {"_id": 0}).sort(
        [("system", -1), ("updated_at", -1)],
    ).to_list(500)
    # Attach active enrolment counts for the table.
    for r in rows:
        r["active_enrolment_count"] = await db.marketing_drip_enrolments.count_documents({
            "tenant_id": tenant["id"], "sequence_id": r["id"], "status": "active",
        })
    return {"sequences": rows, "count": len(rows)}


@router.post("/marketing/sequences", status_code=201)
async def create_sequence(
    body: SequenceIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    steps = [s.model_dump() for s in body.steps]
    await _validate_sequence(tenant["id"], body.trigger_type, steps)
    doc = {
        "id": new_id(), "tenant_id": tenant["id"],
        "name": body.name.strip(),
        "description": (body.description or "").strip(),
        "trigger_type": body.trigger_type,
        "trigger_config": body.trigger_config or {},
        "steps": steps,
        "active": bool(body.active),
        "stop_on_reply": bool(body.stop_on_reply),
        "stop_on_unsubscribe": bool(body.stop_on_unsubscribe),
        "system": False,
        "created_at": now_iso(), "updated_at": now_iso(),
        "created_by": user.get("id"),
    }
    await db.marketing_sequences.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ── {sid}-scoped routes ───────────────────────────────────────────────────
@router.get("/marketing/sequences/{sid}")
async def get_sequence(sid: str, user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    row = await db.marketing_sequences.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row: raise HTTPException(404, "Sequence not found")
    return row


@router.patch("/marketing/sequences/{sid}")
async def patch_sequence(sid: str, body: SequencePatch,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    row = await db.marketing_sequences.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row: raise HTTPException(404, "Sequence not found")
    patch: Dict[str, Any] = {}
    for field in ("name", "description", "trigger_type", "trigger_config",
                   "active", "stop_on_reply", "stop_on_unsubscribe"):
        val = getattr(body, field)
        if val is not None:
            patch[field] = val
    # Feb 2026 · Phase 2 Custom Trigger Builder — accept + validate
    # the nested ``trigger`` doc. Sanity-checked here (logic + shape,
    # canonical event ids on every condition, delay validated by the
    # evaluator). Empty conditions are LEGAL (manual / segment_join
    # sequences) — the evaluator returns False and they never fire.
    if body.trigger is not None:
        from services.marketing.event_registry import is_valid_event
        from services.marketing.trigger_evaluator import _validate_delay
        t = body.trigger
        if not isinstance(t, dict):
            raise HTTPException(422, "trigger must be an object")
        logic = str(t.get("logic") or "AND").upper()
        if logic not in ("AND", "OR"):
            raise HTTPException(422, "trigger.logic must be AND or OR")
        conds = t.get("conditions") or []
        if not isinstance(conds, list):
            raise HTTPException(422, "trigger.conditions must be an array")
        clean_conds: List[Dict[str, Any]] = []
        for i, c in enumerate(conds):
            if not isinstance(c, dict):
                raise HTTPException(422, f"trigger.conditions[{i}] must be an object")
            ev = str(c.get("event") or "").strip()
            if not ev or not is_valid_event(ev):
                raise HTTPException(422, f"trigger.conditions[{i}].event {ev!r} is not a canonical event")
            delay = c.get("delay") or {"mode": "immediate"}
            try:
                _validate_delay(delay)
            except ValueError as ve:
                raise HTTPException(422, f"trigger.conditions[{i}].delay: {ve}")
            filters = c.get("filters") or {}
            if not isinstance(filters, dict):
                raise HTTPException(422, f"trigger.conditions[{i}].filters must be an object")
            clean_conds.append({"event": ev, "delay": delay, "filters": filters})
        patch["trigger"] = {"logic": logic, "conditions": clean_conds}
        patch["schema_version"] = 2
    if body.steps is not None:
        patch["steps"] = [s.model_dump() for s in body.steps]
    trig = patch.get("trigger_type", row["trigger_type"])
    steps = patch.get("steps", row["steps"])
    if "steps" in patch or "trigger_type" in patch:
        await _validate_sequence(tenant["id"], trig, steps)
    if not patch: return row
    patch["updated_at"] = now_iso()
    await db.marketing_sequences.update_one({"id": sid}, {"$set": patch})
    row.update(patch)
    return row


@router.delete("/marketing/sequences/{sid}", status_code=204)
async def delete_sequence(sid: str, user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    """Soft-delete cascades: halt all active enrolments, then flip
    ``active=false``.  Explicitly NOT blocking on active enrolments —
    per spec, delete cascades cleanly.

    Feb 2026 · Task B — soft-lock ``system_template: true`` sequences.
    Ships pre-installed and cannot be deleted (admin can deactivate
    instead — same button, different payload)."""
    row = await db.marketing_sequences.find_one(
        {"id": sid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "system_template": 1, "system_template_id": 1},
    )
    if not row: raise HTTPException(404, "Sequence not found")
    if row.get("system_template"):
        raise HTTPException(
            status_code=409,
            detail={
                "detail": "system_template_cannot_be_deleted",
                "hint": "deactivate instead",
                "system_template_id": row.get("system_template_id"),
            },
        )
    await db.marketing_drip_enrolments.update_many(
        {"tenant_id": tenant["id"], "sequence_id": sid, "status": "active"},
        {"$set": {"status": "halted", "halt_reason": "sequence_deleted",
                    "next_send_at": None}},
    )
    await db.marketing_sequences.update_one(
        {"id": sid}, {"$set": {"active": False, "updated_at": now_iso()}},
    )
    return Response(status_code=204)


@router.post("/marketing/sequences/{sid}/enrol")
async def enrol_customers(
    sid: str, body: EnrolIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    row = await db.marketing_sequences.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row: raise HTTPException(404, "Sequence not found")

    # Resolve customer_ids from either explicit list or segment.
    ids: List[str] = list(body.customer_ids or [])
    if body.segment_id:
        seg = await db.marketing_audience_segments.find_one(
            {"id": body.segment_id, "tenant_id": tenant["id"]},
            {"_id": 0, "conditions": 1},
        )
        if not seg:
            raise HTTPException(422, "segment_id not found")
        from services.marketing.segments import evaluate_conditions
        r = await evaluate_conditions(seg.get("conditions") or [], tenant["id"])
        ids.extend(r["matched_ids"])
    ids = list({i for i in ids if i})

    enrolled = 0; skipped = 0; sample = []
    for cid in ids:
        # Duplicate active enrolment → skip
        existing = await db.marketing_drip_enrolments.find_one({
            "tenant_id": tenant["id"], "sequence_id": sid,
            "customer_id": cid, "status": "active",
        }, {"_id": 0, "id": 1})
        if existing:
            skipped += 1
            continue
        first_delay = 0
        if row.get("steps"):
            first_delay = int(row["steps"][0].get("delay_hours") or 0)
        next_at = (datetime.now(timezone.utc) + timedelta(hours=first_delay)).isoformat()
        doc = {
            "id": new_id(), "tenant_id": tenant["id"],
            "sequence_id": sid, "customer_id": cid,
            "trigger_source": "manual",
            "enrolled_at": now_iso(),
            "current_step": 0,
            "next_send_at": next_at if row.get("steps") else None,
            "status": "active" if row.get("steps") else "completed",
            "halt_reason": None,
            "history": [],
        }
        await db.marketing_drip_enrolments.insert_one(doc)
        enrolled += 1
        if len(sample) < 5:
            doc.pop("_id", None); sample.append(doc)
    return {"enrolled_count": enrolled, "skipped_count": skipped, "sample": sample}


@router.post("/marketing/sequences/{sid}/halt/{eid}", status_code=200)
async def halt_enrolment(
    sid: str, eid: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    r = await db.marketing_drip_enrolments.update_one(
        {"id": eid, "sequence_id": sid, "tenant_id": tenant["id"], "status": "active"},
        {"$set": {"status": "halted", "halt_reason": "manual", "next_send_at": None}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Enrolment not found or not active")
    return {"ok": True}


@router.get("/marketing/sequences/{sid}/enrolments")
async def list_enrolments(
    sid: str, status: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    q: Dict[str, Any] = {"tenant_id": tenant["id"], "sequence_id": sid}
    if status: q["status"] = status
    total = await db.marketing_drip_enrolments.count_documents(q)
    rows = await db.marketing_drip_enrolments.find(q, {"_id": 0}).sort(
        "enrolled_at", -1,
    ).skip(offset).limit(limit).to_list(limit)
    return {"enrolments": rows, "total": total}


# ── Phase-1 Custom Trigger Builder · preview-matches ────────────────
class PreviewMatchesIn(BaseModel):
    """Optional body for the preview endpoint.

    Consumers may either:
      * omit the body entirely (or pass ``{}``) — the endpoint uses
        the sequence's own stored ``trigger`` doc; or
      * pass a ``trigger_override`` shaped exactly like the schema-v2
        ``trigger`` field (``{logic, conditions:[...]}``). This is
        how the Phase-2 builder previews an unsaved rule.

    ``limit`` caps the returned ``sample`` array (never the underlying
    scan). Server-side hard-cap is 25; clients may pass a lower value
    but not higher.
    """
    trigger_override: Optional[Dict[str, Any]] = None
    limit: int = 25


@router.post("/marketing/sequences/{sid}/preview-matches")
async def preview_matches(
    sid: str,
    body: Optional[PreviewMatchesIn] = None,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Dry-run the trigger evaluator against the tenant's customer
    base and return the count + sample of matches. No writes.

    Response shape (locked with the Phase-2 UI)::

        {
          "sequence_id": <sid>,
          "evaluated_at": <ISO now>,
          "match_count":  <int>,
          "sample": [{customer_id, name, reason}, ...],
          "truncated":    <bool>
        }

    ``reason`` is a human-readable string like
    ``"job_completed · segment=pool · zip=85387"`` — enough context
    for the operator to sanity-check why a customer matched.
    """
    from services.marketing.trigger_evaluator import (
        evaluate_conditions, find_matching_condition,
    )
    from services.marketing.event_registry import canonicalize_event_key

    row = await db.marketing_sequences.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Sequence not found")
    body = body or PreviewMatchesIn()
    limit = max(1, min(int(body.limit or 25), 25))

    # Prefer the override; fall back to the sequence's own trigger;
    # fall back to a synthetic single-condition trigger derived from
    # the legacy ``trigger_type`` so pre-migration sequences still
    # preview cleanly.
    trigger = body.trigger_override or row.get("trigger")
    if not (isinstance(trigger, dict)
            and isinstance((trigger or {}).get("conditions"), list)):
        legacy_type = row.get("trigger_type") or ""
        canonical = canonicalize_event_key(legacy_type)
        trigger = {
            "logic": "AND",
            "conditions": [{"event": canonical,
                              "delay": {"mode": "immediate"},
                              "filters": {}}],
        }

    conds = trigger.get("conditions") or []
    if not conds:
        return {
            "sequence_id": sid,
            "evaluated_at": now_iso(),
            "match_count": 0,
            "sample": [],
            "truncated": False,
        }

    # Deduce which entities to walk. If every condition names a
    # job-scoped event, walk jobs; otherwise walk customers. The
    # evaluator hydrates the rest from the customer + optional job.
    JOB_EVENTS = {"job_scheduled", "job_scheduled_reminder_1d",
                  "job_completed", "job_cancelled",
                  "chemistry_out_of_range", "repair_flagged"}
    event_keys = {canonicalize_event_key(c.get("event") or "")
                  for c in conds if c.get("event")}
    job_scoped = bool(event_keys) and event_keys.issubset(JOB_EVENTS)

    match_count = 0
    sample: List[Dict[str, Any]] = []

    if job_scoped:
        # Walk jobs (recent-completed first). We DO NOT modify jobs;
        # the evaluator receives a synthetic event payload constructed
        # from the job doc.
        cursor = db.jobs.find(
            {"tenant_id": tenant["id"],
             # Prefer the class of event's typical shape — completed
             # jobs give the richest ctx.
             "status": {"$in": ["completed", "scheduled", "pending"]}},
            {"_id": 0, "id": 1, "customer_id": 1, "work_class": 1,
             "technician_id": 1, "crew_id": 1, "job_value": 1,
             "total": 1, "customer_name": 1, "scheduled_date": 1,
             "status": 1},
        ).limit(2000)
        async for job in cursor:
            cid = job.get("customer_id")
            if not cid:
                continue
            cust = await db.customers.find_one(
                {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0},
            ) or {}
            for c in conds:
                ev = canonicalize_event_key(c.get("event") or "")
                payload = {"event": ev, "entity_id": job.get("id"),
                           "customer_id": cid,
                           "scheduled_at": job.get("scheduled_date")}
                ctx = _build_preview_ctx(cust, job)
                if evaluate_conditions(
                    {"logic": trigger.get("logic") or "AND",
                     "conditions": [c]}, payload, ctx,
                ):
                    match_count += 1
                    if len(sample) < limit:
                        sample.append({
                            "customer_id": cid,
                            "name": cust.get("name")
                                or job.get("customer_name") or "",
                            "reason": _build_reason(ev, c, ctx),
                        })
                    break
    else:
        cursor = db.customers.find(
            {"tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "name": 1, "service_line": 1,
             "segment": 1, "tags": 1, "service_zip": 1, "zip": 1,
             "billing_zip": 1, "custom_fields": 1,
             "last_service_at": 1, "last_visit_at": 1},
        ).limit(5000)
        async for cust in cursor:
            cid = cust.get("id")
            if not cid:
                continue
            for c in conds:
                ev = canonicalize_event_key(c.get("event") or "")
                payload = {"event": ev, "entity_id": cid, "customer_id": cid}
                ctx = _build_preview_ctx(cust, None)
                if evaluate_conditions(
                    {"logic": trigger.get("logic") or "AND",
                     "conditions": [c]}, payload, ctx,
                ):
                    match_count += 1
                    if len(sample) < limit:
                        sample.append({
                            "customer_id": cid,
                            "name": cust.get("name") or "",
                            "reason": _build_reason(ev, c, ctx),
                        })
                    break

    return {
        "sequence_id": sid,
        "evaluated_at": now_iso(),
        "match_count": match_count,
        "sample": sample,
        "truncated": match_count > len(sample),
    }


def _build_preview_ctx(cust: Dict[str, Any],
                        job: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Flatten the customer + optional job into the ``ctx`` shape the
    evaluator expects. Mirrors ``event_dispatcher.hydrate_event_ctx``
    but works synchronously since the preview endpoint already has
    the docs in hand."""
    ctx: Dict[str, Any] = {
        "customer_id": cust.get("id"),
        "customer_segment": cust.get("service_line") or cust.get("segment"),
        "tags": cust.get("tags") or [],
        "zip": (cust.get("service_zip") or cust.get("zip")
                 or cust.get("billing_zip")),
        "custom_fields": cust.get("custom_fields") or {},
    }
    lv = cust.get("last_service_at") or cust.get("last_visit_at")
    if lv:
        try:
            lv_dt = datetime.fromisoformat(str(lv).replace("Z", "+00:00"))
            if lv_dt.tzinfo is None:
                lv_dt = lv_dt.replace(tzinfo=timezone.utc)
            ctx["last_visit_days_ago"] = (
                datetime.now(timezone.utc) - lv_dt
            ).total_seconds() / 86400.0
        except Exception:
            pass
    if job:
        ctx["work_class"] = job.get("work_class")
        ctx["technician_id"] = job.get("technician_id")
        ctx["crew_id"] = job.get("crew_id")
        ctx["job_value"] = (job.get("job_value")
                             or (job.get("job_totals") or {}).get("total")
                             or job.get("total") or 0)
    return ctx


def _build_reason(event: str, cond: Dict[str, Any],
                   ctx: Dict[str, Any]) -> str:
    """Compose a short human-readable reason string. Only surfaces
    the filter dims that were EXPLICITLY specified on the condition —
    keeps the string short + useful for ops."""
    bits: List[str] = [event]
    f = cond.get("filters") or {}
    if f.get("customer_segment"):
        bits.append(f"segment={ctx.get('customer_segment')}")
    if f.get("work_class"):
        bits.append(f"work_class={ctx.get('work_class')}")
    if f.get("tags"):
        bits.append(f"tags={','.join((ctx.get('tags') or [])[:2])}")
    if f.get("zip"):
        bits.append(f"zip={ctx.get('zip')}")
    if f.get("job_value_gte") is not None:
        bits.append(f"job_value={ctx.get('job_value')}")
    if f.get("last_visit_gte_days") is not None:
        lv = ctx.get("last_visit_days_ago")
        bits.append(f"last_visit≈{int(lv)}d" if lv else "last_visit=n/a")
    return " · ".join(bits)


# ── Tick handler (M5c will wire the scheduler) ─────────────────────────────
async def process_due_enrolments(tenant_id: Optional[str] = None) -> Dict[str, int]:
    """Process every enrolment whose ``next_send_at <= now`` in the given
    tenant (or across all tenants if ``tenant_id`` is None).  Records
    a mock ``marketing_deliveries`` doc for each step fired, then
    advances the cursor / recomputes ``next_send_at`` / marks
    ``completed`` when the sequence exhausts."""
    now = datetime.now(timezone.utc)
    q: Dict[str, Any] = {
        "status": "active",
        "next_send_at": {"$lte": now.isoformat()},
    }
    if tenant_id:
        q["tenant_id"] = tenant_id
    due = await db.marketing_drip_enrolments.find(q, {"_id": 0}).to_list(1000)
    sent = 0; completed = 0
    for e in due:
        seq = await db.marketing_sequences.find_one(
            {"id": e["sequence_id"], "tenant_id": e["tenant_id"]}, {"_id": 0},
        )
        if not seq or not seq.get("active"):
            continue
        step_idx = int(e.get("current_step") or 0)
        steps = seq.get("steps") or []
        if step_idx >= len(steps):
            await db.marketing_drip_enrolments.update_one(
                {"id": e["id"]},
                {"$set": {"status": "completed", "next_send_at": None}},
            )
            completed += 1
            continue
        step = steps[step_idx]
        # Slice F · suppression enforcement — check the recipient's
        # opt-in state before rendering.  A suppressed contact halts
        # the enrolment cleanly with ``halt_reason="suppressed"``.
        #
        # P0 · Feb 2026 — fetch the FULL customer doc (widened from
        # ``{email, phone}`` to ``{_id: 0}`` = everything except
        # ``_id``) so ``{{customer.first_name}}`` renders the real
        # first name instead of leaking the ``DEFAULT_SAMPLE_CONTEXT``
        # placeholder ``"Sam"`` to every real recipient.  Same for the
        # tenant doc — the previous sample-only render leaked the
        # sample tenant phone ``+1 (623) 555-0100`` into every drip.
        cust = await db.customers.find_one(
            {"id": e["customer_id"], "tenant_id": e["tenant_id"]},
            {"_id": 0},
        ) or {}
        tenant_doc = await db.tenants.find_one(
            {"id": e["tenant_id"]},
            {"_id": 0},
        ) or {}
        try:
            from routers.marketing_preferences import (
                is_suppressed as _is_suppressed,
                build_unsubscribe_url as _unsub_url,
            )
            if await _is_suppressed(
                e["tenant_id"], cust,
                channel=step["channel"], category="sequences",
            ):
                await db.marketing_drip_enrolments.update_one(
                    {"id": e["id"]},
                    {"$set": {"status": "halted",
                                "halt_reason": "suppressed",
                                "next_send_at": None}},
                )
                continue
        except Exception:
            pass
        # P0 · Feb 2026 (Fix 2b) — worker claim to protect against
        # concurrent scheduler ticks double-sending the same
        # enrolment.  ``findOneAndUpdate`` under a filter that
        # allows re-claim only after a 5-minute stale window; a
        # ``None`` return means another worker already owns this
        # tick — skip silently.
        claim_now = datetime.now(timezone.utc)
        claim_cutoff = (claim_now - timedelta(minutes=5)).isoformat()
        claim_res = await db.marketing_drip_enrolments.find_one_and_update(
            {"id": e["id"],
             "$or": [
                 {"claimed_at": {"$exists": False}},
                 {"claimed_at": None},
                 {"claimed_at": {"$lt": claim_cutoff}},
             ]},
            {"$set": {"claimed_at": claim_now.isoformat(),
                       "claimed_by": os.environ.get("HOSTNAME") or "worker"}},
            projection={"_id": 0, "id": 1},
        )
        if not claim_res:
            # Another worker (or a previous crash still within the
            # 5-min stale window) owns this tick.
            continue
        # Render + record real delivery
        tpl = await db.marketing_templates.find_one(
            {"id": step["template_id"], "tenant_id": e["tenant_id"]}, {"_id": 0},
        )
        # P0 · Feb 2026 — build the render context from the REAL
        # customer + tenant docs (via the canonical ``render_context``
        # helper), not from ``DEFAULT_SAMPLE_CONTEXT``.  The old code
        # (``_ctx = dict(DEFAULT_SAMPLE_CONTEXT)``) was leaking the
        # developer preview's ``"Sam"`` / ``sam@example.com`` /
        # sample tenant number into every drip SMS + email that
        # referenced ``{{customer.*}}`` or ``{{tenant.*}}``.  The
        # unsubscribe URL is still injected as a flat-key override.
        _ctx = render_context(customer=cust, tenant=tenant_doc)
        # K31 · Feb-2026 — hydrate ``job`` + ``service_report`` when the
        # enrolment carries the ids in ``trigger_meta``. Fixes the
        # empty ``{{SERVICE_NAME}}`` / ``{{job.*}}`` merge-tag rendering
        # (Message 2 on plofv rendered "just finished your visit for ."
        # because ``ctx.job`` was ``{}``). Best-effort — a missing
        # service_report / job doc leaves the tag empty rather than
        # crashing the tick.
        _tmeta = e.get("trigger_meta") or {}
        _sr_id = _tmeta.get("service_report_id")
        _job_id = _tmeta.get("job_id")
        if _sr_id or _job_id:
            try:
                sr_doc = None
                if _sr_id:
                    sr_doc = await db.service_reports.find_one(
                        {"tenant_id": e["tenant_id"], "id": _sr_id},
                        {"_id": 0},
                    )
                if not _job_id and sr_doc:
                    _job_id = sr_doc.get("job_id")
                job_doc = None
                if _job_id:
                    job_doc = await db.jobs.find_one(
                        {"tenant_id": e["tenant_id"], "id": _job_id},
                        {"_id": 0},
                    )
                _ctx["job"] = job_doc or {}
                _ctx["service_report"] = sr_doc or {}
            except Exception as _exc:  # noqa: BLE001
                logger.warning(
                    "[k31] job/service_report hydrate failed enrol=%s: %s",
                    e.get("id"), _exc,
                )
        try:
            _ctx["unsubscribe_url"] = _unsub_url(e["customer_id"], e["tenant_id"])
        except Exception:
            pass
        subj, body, missing = render_subject_and_body(
            (tpl or {}).get("subject") or "",
            (tpl or {}).get("body") or "",
            _ctx,
        )
        if step["channel"] == "sms":
            body = strip_html(body)
        delivery_id = new_id()
        # Backlog #iv · Feb-2026 — Unified dispatch guard.
        # ``sequence_step:{sequence_id}:{step_id}:{customer_id}``
        # dedupes across scheduler ticks even if the ``claimed_at``
        # 5-minute stale window elapses (crash + immediate restart).
        # The adapter-level ``sms_send_ledger`` continues to guard
        # its own retry loop — this is the outer envelope.
        from services.comms_hardening.dispatch_guard import (
            guard_and_log as _iv_guard, mark_dispatch_result as _iv_mark,
            hash_email as _iv_hash_email, hash_phone as _iv_hash_phone,
        )
        _iv_step_id = step.get("id") or f"idx-{step_idx}"
        _iv_dedupe = (
            f"sequence_step:{seq['id']}:{_iv_step_id}:{e['customer_id']}"
        )
        _iv_recipient = e["customer_id"] or (
            _iv_hash_email(cust.get("email") or "")
            if step["channel"] == "email"
            else _iv_hash_phone(cust.get("phone") or "")
        )
        _iv_addr = (
            (cust.get("email") or "") if step["channel"] == "email"
            else (cust.get("phone") or "")
        ).strip()
        _iv_verdict = await _iv_guard(
            tenant_id=e["tenant_id"],
            notification_type=f"sequence_step_{step['channel']}",
            recipient_id=_iv_recipient or "",
            dedupe_key=_iv_dedupe,
            channel=step["channel"],
            resolved_address=_iv_addr,
            subject=None,
            metadata={"sequence_id": seq["id"], "step_index": step_idx,
                       "enrolment_id": e["id"]},
        )
        if not _iv_verdict["allowed"]:
            logger.info(
                "[m5c] sequence_step dedupe skip · seq=%s step=%s cust=%s "
                "reason=%s",
                seq["id"], _iv_step_id, e["customer_id"],
                _iv_verdict["reason"],
            )
            # Advance the cursor so the enrolment isn't stuck retrying.
            next_idx = step_idx + 1
            history = list(e.get("history") or [])
            history.append({
                "step_index": step_idx,
                "action_type": step.get("channel"),
                "fired_at": now.isoformat(),
                "dedupe_skipped": True,
                "dedupe_reason": _iv_verdict["reason"],
            })
            done = next_idx >= len(steps)
            await db.marketing_drip_enrolments.update_one(
                {"id": e["id"]},
                {"$set": {"current_step": next_idx,
                            "next_send_at": None if done else (now + timedelta(days=1)).isoformat(),
                            "status": "completed" if done else "active",
                            "history": history,
                            "claimed_at": None}},
            )
            if done:
                completed += 1
            continue
        # Slice N / S · route email through Resend, SMS through RingCentral.
        provider_status = None
        provider = "mock"
        provider_response_id = None
        attempts = 0
        if step["channel"] == "email":
            recipient = (cust.get("email") or "").strip()
            try:
                from services.email.resend_adapter import send as _resend_send
                res = await _resend_send(
                    to=recipient,
                    subject=subj,
                    html=body,
                    category="drip",
                    tenant_id=e["tenant_id"],
                    customer_id=e["customer_id"],
                    idempotency_key=f"drip:{e['id']}:{step_idx}",
                )
                provider = res.get("provider") or "mock"
                provider_status = res.get("provider_status")
                provider_response_id = res.get("provider_response_id")
                attempts = res.get("attempts") or 0
            except Exception as exc:  # pragma: no cover
                logger.warning("[m5c] resend adapter failed: %s", exc)
                provider_status = "failed"
        elif step["channel"] == "sms":
            try:
                from services.sms.rc_adapter import send as _sms_send
                res = await _sms_send(
                    to=(cust.get("phone") or "").strip(),
                    body=body,
                    category="drip",
                    tenant_id=e["tenant_id"],
                    customer_id=e["customer_id"],
                    idempotency_key=f"drip:{e['id']}:{step_idx}",
                )
                provider = res.get("provider") or "mock"
                provider_status = res.get("provider_status")
                provider_response_id = res.get("provider_response_id")
                attempts = res.get("attempts") or 0
            except Exception as exc:  # pragma: no cover
                logger.warning("[m5c] rc adapter failed: %s", exc)
                provider_status = "failed"
        await db.marketing_deliveries.insert_one({
            "id": delivery_id,
            "tenant_id": e["tenant_id"],
            "sequence_id": seq["id"],
            "enrolment_id": e["id"],
            "step_index": step_idx,
            "customer_id": e["customer_id"],
            "channel": step["channel"],
            "template_id": step["template_id"],
            "subject_rendered": subj if step["channel"] == "email" else None,
            "body_rendered": body,
            "mock": provider == "mock",
            "provider": provider,
            "provider_status": provider_status,
            "provider_response_id": provider_response_id,
            "attempts": attempts,
            "sent_at": now.isoformat(),
            "provider_response_stub": {"ok": True, "id": f"mock-{delivery_id[:8]}"},
        })
        # Backlog #iv · Stamp outcome on the dispatch-log envelope.
        await _iv_mark(
            _iv_verdict.get("dispatch_id"),
            status=(provider_status or "unknown"),
            provider_id=provider_response_id,
            attempt_count=attempts,
        )
        # Advance
        next_idx = step_idx + 1
        history = list(e.get("history") or [])
        history.append({
            "step_index": step_idx,
            "channel": step["channel"],
            "template_id": step["template_id"],
            "sent_at": now.isoformat(),
            "status": "sent",
            "mock_delivery_id": delivery_id,
        })
        if next_idx >= len(steps):
            await db.marketing_drip_enrolments.update_one(
                {"id": e["id"]},
                {"$set": {"status": "completed",
                            "current_step": next_idx,
                            "next_send_at": None,
                            "history": history}},
            )
            completed += 1
        else:
            nxt_step = steps[next_idx]
            delay = int(nxt_step.get("delay_hours") or 0)
            next_at = (now + timedelta(hours=delay)).isoformat()
            await db.marketing_drip_enrolments.update_one(
                {"id": e["id"]},
                {"$set": {"current_step": next_idx,
                            "next_send_at": next_at,
                            "history": history}},
            )
        sent += 1
    return {"processed": len(due), "sent": sent, "completed": completed}


# ── Seed ──────────────────────────────────────────────────────────────────
async def seed_sequences_for_tenant(tenant_id: str) -> int:
    if await db.marketing_sequences.count_documents({"tenant_id": tenant_id}) > 0:
        return 0
    # Look up the seeded templates so we can wire the step references.
    tpls = await db.marketing_templates.find(
        {"tenant_id": tenant_id, "system": True}, {"_id": 0, "id": 1, "channel": 1, "category": 1},
    ).to_list(50)
    by = {(t["category"], t["channel"]): t["id"] for t in tpls}
    now = now_iso()
    seeds = []
    if ("service_completed", "email") in by and ("review_request", "sms") in by:
        seeds.append({
            "id": new_id(), "tenant_id": tenant_id,
            "name": "Post-service follow-up",
            "description": "Follow up 24h after service, then nudge for a review 48h later.",
            "trigger_type": "service_completed", "trigger_config": {},
            "steps": [
                {"order": 0, "channel": "email",
                 "template_id": by[("service_completed", "email")],
                 "delay_from": "trigger", "delay_hours": 24, "condition": None},
                {"order": 1, "channel": "sms",
                 "template_id": by[("review_request", "sms")],
                 "delay_from": "previous_step", "delay_hours": 48, "condition": None},
            ],
            "active": False, "stop_on_reply": True, "stop_on_unsubscribe": True,
            "system": True, "created_at": now, "updated_at": now, "created_by": None,
        })
    if ("past_due", "email") in by and ("past_due", "sms") in by:
        seeds.append({
            "id": new_id(), "tenant_id": tenant_id,
            "name": "Past-due reminder",
            "description": "Email at 3 days past-due, SMS at 7 days.",
            "trigger_type": "invoice_past_due_N_days",
            "trigger_config": {"days_past_due": 3},
            "steps": [
                {"order": 0, "channel": "email",
                 "template_id": by[("past_due", "email")],
                 "delay_from": "trigger", "delay_hours": 0, "condition": None},
                {"order": 1, "channel": "sms",
                 "template_id": by[("past_due", "sms")],
                 "delay_from": "previous_step", "delay_hours": 96, "condition": None},
            ],
            "active": False, "stop_on_reply": True, "stop_on_unsubscribe": True,
            "system": True, "created_at": now, "updated_at": now, "created_by": None,
        })
    if seeds:
        await db.marketing_sequences.insert_many(seeds)
    return len(seeds)


async def seed_sequences_all_tenants() -> Dict[str, int]:
    total = 0; tenants = 0
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        tenants += 1
        try: total += await seed_sequences_for_tenant(t["id"])
        except Exception as exc:  # pragma: no cover
            logger.warning("m5 seed for tenant %s failed: %s", t.get("id"), exc)
    return {"tenants": tenants, "inserted": total}
