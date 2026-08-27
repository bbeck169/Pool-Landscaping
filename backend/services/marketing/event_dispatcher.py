"""Feb 2026 · Marketing · Phase 1 — Event dispatcher + enrollment
engine.

Central entry point for every domain-event hook. Callers do::

    from services.marketing.event_dispatcher import emit_event
    await emit_event(
        event="job_completed",
        tenant_id=tid,
        entity_id=job["id"],
        customer_id=customer_id,
        payload_extras={"job": job_snapshot, "customer": cust_snapshot},
    )

The dispatcher runs BOTH paths in a single fan-out:

  1. **Legacy path** — ``drip_events.on_event`` for sequences that
     still carry the old ``trigger_type`` scalar. Zero-regression for
     the ``new_lead`` and ``job_scheduled_reminder_1d`` flows that
     already shipped.
  2. **Phase-1 path** — for sequences whose ``schema_version >= 2``
     and ``trigger`` doc encodes the rich AND/OR + filter shape,
     runs the :func:`evaluate_conditions` matcher and enrols
     matches at :func:`resolve_enrollment_time`.

Both paths dedupe against the same ``marketing_event_ledger`` unique
index so replay is safe.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import db
from utils import new_id, now_iso

from services.marketing.drip_events import (
    _ensure_event_ledger_index,
    _correlation_from_meta,
    on_event as legacy_on_event,
)
from services.marketing.event_registry import (
    canonicalize_event_key,
    is_valid_event,
)
from services.marketing.trigger_evaluator import (
    evaluate_conditions,
    find_matching_condition,
    resolve_enrollment_time,
)


logger = logging.getLogger(__name__)


# ─── Ctx hydration ───────────────────────────────────────────────────
async def hydrate_event_ctx(
    tenant_id: str,
    event: str,
    entity_id: Optional[str],
    customer_id: Optional[str],
    payload_extras: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Load the customer + optionally the job/lead/invoice referenced
    by the event, then flatten into the ``ctx`` shape the trigger
    evaluator consumes.

    Best-effort — missing docs return ``None`` on their respective
    fields.  Filters treat missing values as "does not match" so a
    hydrate failure fails closed.
    """
    ctx: Dict[str, Any] = {}
    payload_extras = payload_extras or {}
    # Customer fields — read once and populate segment/tags/zip/etc.
    cust = payload_extras.get("customer")
    if not cust and customer_id:
        cust = await db.customers.find_one(
            {"id": customer_id, "tenant_id": tenant_id},
            {"_id": 0},
        )
    if cust:
        ctx["customer_id"] = cust.get("id")
        ctx["customer_segment"] = cust.get("service_line") or cust.get("segment")
        ctx["tags"] = cust.get("tags") or []
        ctx["zip"] = (cust.get("service_zip")
                       or cust.get("zip")
                       or cust.get("billing_zip"))
        ctx["custom_fields"] = cust.get("custom_fields") or {}
        lv = cust.get("last_service_at") or cust.get("last_visit_at")
        if lv:
            try:
                lv_dt = datetime.fromisoformat(
                    str(lv).replace("Z", "+00:00"),
                )
                if not lv_dt.tzinfo:
                    lv_dt = lv_dt.replace(tzinfo=timezone.utc)
                ctx["last_visit_days_ago"] = (
                    datetime.now(timezone.utc) - lv_dt
                ).total_seconds() / 86400.0
            except Exception:
                pass
    # Job fields — for job-scoped events.
    job = payload_extras.get("job")
    if not job and entity_id and event in {
        "job_scheduled", "job_scheduled_reminder_1d",
        "job_completed", "job_cancelled",
        "chemistry_out_of_range", "repair_flagged",
    }:
        job = await db.jobs.find_one(
            {"id": entity_id, "tenant_id": tenant_id},
            {"_id": 0},
        )
    if job:
        ctx["work_class"] = job.get("work_class")
        ctx["technician_id"] = job.get("technician_id")
        ctx["crew_id"] = job.get("crew_id")
        ctx["job_value"] = (
            job.get("job_value")
            or (job.get("job_totals") or {}).get("total")
            or job.get("total")
            or 0
        )
        if not ctx.get("customer_id"):
            ctx["customer_id"] = job.get("customer_id")
    return ctx


# ─── Emit ────────────────────────────────────────────────────────────
async def emit_event(
    event: str,
    tenant_id: str,
    entity_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    scheduled_at: Optional[str] = None,
    payload_extras: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Domain-event hook. Returns a summary dict::

        {"event": ..., "enrolled": N, "matched_sequences": N,
         "deduped": 0|1, "legacy_enrolled": N}

    Never raises. Callers should not gate parent behaviour on the
    return — this is a fan-out helper, not a critical path.
    """
    event = canonicalize_event_key(event)
    outcome = {
        "event": event, "enrolled": 0, "matched_sequences": 0,
        "deduped": 0, "legacy_enrolled": 0,
    }
    if not (event and is_valid_event(event) and tenant_id):
        return outcome

    payload = {
        "event": event,
        "entity_id": entity_id,
        "customer_id": customer_id,
        "tenant_id": tenant_id,
        "occurred_at": now_iso(),
        "scheduled_at": scheduled_at,
        **(payload_extras or {}),
    }

    # 1. Dedupe barrier — same ledger as legacy on_event uses. The
    #    key includes the event name so different events on the same
    #    entity don't collide with each other, but a replay of the
    #    same event on the same entity does.
    await _ensure_event_ledger_index()
    corr_id = correlation_id or _correlation_from_meta(
        event, customer_id or entity_id or "anon",
        {"correlation_id": correlation_id, **(payload_extras or {})},
    )
    event_key = f"{event}:{corr_id}"
    try:
        await db.marketing_event_ledger.insert_one({
            "id": new_id(), "tenant_id": tenant_id,
            "customer_id": customer_id or entity_id,
            "event_key": event_key, "trigger_type": event,
            "correlation_id": corr_id,
            "processed_at": now_iso(),
            "meta": payload_extras or {},
        })
    except Exception as exc:
        if type(exc).__name__ == "DuplicateKeyError":
            outcome["deduped"] = 1
            return outcome
        logger.warning(
            "[emit_event] ledger insert crashed: %s (continuing)", exc,
        )

    # 2. Phase-1 path — hydrate ctx, walk sequences that use the new
    #    schema, evaluate + enrol.
    try:
        ctx = await hydrate_event_ctx(
            tenant_id, event, entity_id, customer_id, payload_extras,
        )
        seqs = await db.marketing_sequences.find(
            {
                "tenant_id": tenant_id,
                "active": True,
                "schema_version": {"$gte": 2},
                "trigger.conditions.event": event,
            },
            {"_id": 0, "id": 1, "trigger": 1, "steps": 1},
        ).to_list(500)
        outcome["matched_sequences"] = len(seqs)
        for s in seqs:
            trig = s.get("trigger") or {}
            if not evaluate_conditions(trig, payload, ctx):
                continue
            eid = await _enrol_into_phase1_sequence(
                tenant_id=tenant_id,
                sequence=s,
                condition=find_matching_condition(trig, payload, ctx),
                payload=payload,
                customer_id=customer_id or ctx.get("customer_id"),
            )
            if eid:
                outcome["enrolled"] += 1
    except Exception as exc:
        logger.warning(
            "[emit_event] phase-1 fan-out crashed for %s: %s", event, exc,
        )

    # 3. Legacy path — sequences that still carry ``trigger_type``.
    #    on_event dedupes internally via the same ledger; because we
    #    inserted our ledger row above with the SAME event_key, the
    #    legacy path will register ``deduped=1`` and no-op on Phase-1
    #    events. We still call it for the immediate-trigger set the
    #    M5c pipeline shipped with (``service_completed``, etc.) —
    #    those are aliased on the phase-1 side too, so this is
    #    strictly redundant AFTER the boot migration lands. Kept for
    #    belt-and-braces during the migration window.
    try:
        legacy = await legacy_on_event(
            event, tenant_id, customer_id or entity_id,
            meta={"correlation_id": corr_id, **(payload_extras or {})},
        )
        outcome["legacy_enrolled"] = legacy.get("enrolled", 0)
    except Exception:
        pass

    return outcome


# ─── Phase-1 enrolment writer ────────────────────────────────────────
async def _enrol_into_phase1_sequence(
    tenant_id: str,
    sequence: Dict[str, Any],
    condition: Optional[Dict[str, Any]],
    payload: Dict[str, Any],
    customer_id: Optional[str],
) -> Optional[str]:
    """Insert one enrolment row. Dedupes on ``(tenant_id, sequence_id,
    customer_id)`` (only active rows) — replays never double-enrol
    the same contact into the same sequence."""
    if not (tenant_id and sequence.get("id") and customer_id):
        return None
    sid = sequence["id"]
    exists = await db.marketing_drip_enrolments.find_one(
        {"tenant_id": tenant_id, "sequence_id": sid,
          "customer_id": customer_id, "status": "active"},
        {"_id": 0, "id": 1},
    )
    if exists:
        return None
    # Delay resolution — pick the matched condition's ``delay``, or
    # fall back to immediate.
    if condition:
        next_at_dt = resolve_enrollment_time(condition, payload)
    else:
        next_at_dt = datetime.now(timezone.utc)
    next_at_iso = next_at_dt.astimezone(timezone.utc).isoformat()
    steps = sequence.get("steps") or []
    doc = {
        "id": new_id(), "tenant_id": tenant_id,
        "sequence_id": sid, "customer_id": customer_id,
        "trigger_source": payload.get("event") or "event",
        "trigger_correlation": payload.get("entity_id"),
        "enrolled_at": now_iso(),
        "current_step": 0,
        "next_send_at": next_at_iso if steps else None,
        "status": "active" if steps else "completed",
        "halt_reason": None,
        "history": [],
    }
    await db.marketing_drip_enrolments.insert_one(doc)
    return doc["id"]
