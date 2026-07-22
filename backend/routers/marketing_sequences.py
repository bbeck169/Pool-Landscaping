"""Feb-2026 · Marketing Slice M5a — Drip sequences: CRUD, enrolment,
tick handler.  Scheduler wiring + event hooks + frontend come in M5b/c.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from config import db, logger
from utils import new_id, now_iso, require_admin
from routers.tenants import get_current_tenant
from services.marketing.render import render_subject_and_body, strip_html, DEFAULT_SAMPLE_CONTEXT

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
    per spec, delete cascades cleanly."""
    row = await db.marketing_sequences.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1},
    )
    if not row: raise HTTPException(404, "Sequence not found")
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
        cust = await db.customers.find_one(
            {"id": e["customer_id"], "tenant_id": e["tenant_id"]},
            {"_id": 0, "email": 1, "phone": 1},
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
        # Render + record mock delivery
        tpl = await db.marketing_templates.find_one(
            {"id": step["template_id"], "tenant_id": e["tenant_id"]}, {"_id": 0},
        )
        # Per-recipient render context — include unsubscribe URL.
        _ctx = dict(DEFAULT_SAMPLE_CONTEXT)
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
        # Slice N / S · route email through Resend, SMS through Twilio.
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
                from services.sms.twilio_adapter import send as _twilio_send
                res = await _twilio_send(
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
                logger.warning("[m5c] twilio adapter failed: %s", exc)
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
