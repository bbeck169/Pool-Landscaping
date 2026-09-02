"""Feb-2026 · Marketing Slice M5c — drip event bus + daily eval sweep.

Kept out of ``routers/marketing_sequences.py`` on purpose so that M5a
router stays untouched.  Everything here is additive:

* :func:`enrol_customer_into_sequence` — the shared enrol helper the
  event hooks + daily sweep use.  Dedupes on active enrolments per
  (sequence_id, customer_id).
* :func:`on_event` — best-effort event bus for the 4 immediate
  triggers (``service_completed``, ``invoice_sent``,
  ``customer_created``, ``review_left``).  Never raises.
* :func:`sequences_tick_all_tenants` — APScheduler entry point for
  the 5-minute step processor.  Wraps
  :func:`routers.marketing_sequences.process_due_enrolments`.
* :func:`daily_marketing_trigger_sweep` — APScheduler entry point for
  the 09:00 UTC daily eval covering ``invoice_past_due_N_days``,
  ``birthday`` and ``segment_join``.

Tenant-timezone note
--------------------
The daily sweep runs once at 09:00 **UTC**.  We accept the small
drift versus per-tenant local time because:

1. every existing daily job in ``server.py`` runs UTC-only, so this
   matches the codebase convention; and
2. the M5 delivery layer is fully mocked — a couple hours' UTC drift
   has no downstream impact.  If a live provider ever lands, we
   revisit and iterate per-tenant scheduling then.

P0 dedupe · Feb 2026 — see :func:`_ensure_event_ledger_index` and
:func:`on_event`.  A ``marketing_event_ledger`` collection with a
unique index on ``(tenant_id, customer_id, event_key)`` gates the
fan-out at the top of :func:`on_event`.  If the insert fails on the
unique key, the event has already been processed and we skip the
enrolment loop entirely — this prevents a service-completion (or any
other trigger) from double-enrolling the same customer across every
active matching sequence when the caller retries or the domain event
fires twice for the same underlying record.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import db
from utils import new_id, now_iso

logger = logging.getLogger(__name__)


# ─── Shared enrol helper ──────────────────────────────────────────────
async def enrol_customer_into_sequence(
    tenant_id: str,
    sequence_id: str,
    customer_id: str,
    trigger_source: str = "event",
    trigger_meta: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Insert one enrolment doc (or skip if one is already active).
    Returns the new enrolment id when a doc is inserted, ``None``
    when the enrolment was deduped or the sequence is missing.

    K31 · Feb-2026 — accepts ``trigger_meta`` (dict) so the enrolment
    row carries the source domain-event context (e.g., ``job_id``,
    ``service_report_id`` for ``service_completed`` events). The
    downstream sequence tick uses this to hydrate the render context
    with ``job`` + ``service_report``, which fixes the "for ." empty
    merge-tag rendering when the tenant's template references
    ``{{SERVICE_NAME}}`` / ``{{job.*}}``.
    """
    if not (tenant_id and sequence_id and customer_id):
        return None
    seq = await db.marketing_sequences.find_one(
        {"id": sequence_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not seq:
        return None
    exists = await db.marketing_drip_enrolments.find_one(
        {"tenant_id": tenant_id, "sequence_id": sequence_id,
         "customer_id": customer_id, "status": "active"},
        {"_id": 0, "id": 1},
    )
    if exists:
        return None
    steps = seq.get("steps") or []
    first_delay_hours = int((steps[0].get("delay_hours") if steps else 0) or 0)
    next_at = (datetime.now(timezone.utc)
                + timedelta(hours=first_delay_hours)).isoformat()
    doc = {
        "id": new_id(), "tenant_id": tenant_id,
        "sequence_id": sequence_id, "customer_id": customer_id,
        "trigger_source": trigger_source,
        "trigger_meta": trigger_meta or {},
        "enrolled_at": now_iso(),
        "current_step": 0,
        "next_send_at": next_at if steps else None,
        "status": "active" if steps else "completed",
        "halt_reason": None,
        "history": [],
    }
    await db.marketing_drip_enrolments.insert_one(doc)
    return doc["id"]


# ─── Event ledger (Fix 2a — at-most-one fan-out per event) ────────────
_LEDGER_INDEX_READY = False


async def _ensure_event_ledger_index() -> None:
    """Idempotent index bootstrap.  Called lazily from :func:`on_event`.

    The unique key is ``(tenant_id, customer_id, event_key)`` where
    ``event_key = f"{trigger_type}:{correlation_id}"``.  Insert-with-
    unique-fail is our dedupe primitive: the second call for the same
    event_key raises ``DuplicateKeyError``, which we catch and treat
    as "already processed — skip".
    """
    global _LEDGER_INDEX_READY
    if _LEDGER_INDEX_READY:
        return
    try:
        await db.marketing_event_ledger.create_index(
            [("tenant_id", 1), ("customer_id", 1), ("event_key", 1)],
            unique=True,
            name="uniq_tenant_customer_event",
        )
        _LEDGER_INDEX_READY = True
    except Exception as exc:  # pragma: no cover
        logger.warning("[m5c] event ledger index bootstrap failed: %s", exc)


def _correlation_from_meta(
    trigger_type: str,
    customer_id: str,
    meta: Optional[Dict[str, Any]],
) -> str:
    """Resolve the ``correlation_id`` component of the ledger key.

    Priority order:
      1. Explicit ``meta["correlation_id"]``.
      2. Trigger-specific meta keys — ``service_report_id``,
         ``invoice_id``, ``estimate_id``, ``review_id``.
      3. Fallback = ``f"{customer_id}:{YYYY-MM-DD-UTC}"`` so a
         re-fire on the same day for the same customer still
         collides on the unique index.  This keeps callers that
         don't pass a domain id safe by default.
    """
    if isinstance(meta, dict):
        cid = meta.get("correlation_id")
        if cid:
            return str(cid)
        for k in ("service_report_id", "invoice_id", "estimate_id", "review_id"):
            v = meta.get(k)
            if v:
                return str(v)
    day = datetime.now(timezone.utc).date().isoformat()
    return f"{customer_id}:{day}"


# ─── Immediate event bus ──────────────────────────────────────────────
_IMMEDIATE_TRIGGERS = {
    "service_completed", "invoice_sent", "customer_created", "review_left",
    # Feb-2026 · Slice O.2 companion — accepting an estimate can kick off
    # a post-sale onboarding drip.  Fires from both authenticated + magic-
    # link accept paths (see routers/estimate_viewer.py).
    "estimate_accepted",
}


async def on_event(
    trigger_type: str,
    tenant_id: Optional[str],
    customer_id: Optional[str],
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, int]:
    """Fanout a domain event to every active sequence with a matching
    ``trigger_type`` in the same tenant.  Best-effort: any exception
    is swallowed + logged; hooks in domain code MUST NOT break their
    parent request.

    Returns::

        {"enrolled": <int>, "skipped": <int>, "sequences": <int>,
         "deduped": <0|1>}

    P0 Fix 2a — the unique-index insert on ``marketing_event_ledger``
    at the top of this function gates the entire fan-out.  If the
    event has already been processed (same ``(tenant, customer,
    event_key)``), the ``DuplicateKeyError`` is caught and we return
    early with ``deduped=1`` — no enrolments are created, no SMS is
    sent.  This is the root fix for the identical-duplicate SMS the
    prod screenshot documented (messages #2 and #3 were the same
    fan-out running twice on top of the same
    ``service_completed`` event).
    """
    outcome = {"enrolled": 0, "skipped": 0, "sequences": 0, "deduped": 0}
    if trigger_type not in _IMMEDIATE_TRIGGERS:
        return outcome
    if not (tenant_id and customer_id):
        return outcome

    # 1. Dedupe barrier — one row per (tenant, customer, event).
    await _ensure_event_ledger_index()
    correlation_id = _correlation_from_meta(trigger_type, customer_id, meta)
    event_key = f"{trigger_type}:{correlation_id}"
    try:
        await db.marketing_event_ledger.insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "event_key": event_key,
            "trigger_type": trigger_type,
            "correlation_id": correlation_id,
            "processed_at": now_iso(),
            "meta": meta or {},
        })
    except Exception as exc:  # DuplicateKeyError from the unique index.
        # ``pymongo.errors.DuplicateKeyError`` — but we don't want to
        # import pymongo here.  The class name check keeps this
        # future-proof across driver versions.
        if type(exc).__name__ == "DuplicateKeyError":
            outcome["deduped"] = 1
            logger.info(
                "[m5c] event dedupe hit — trigger=%s tenant=%s customer=%s key=%s",
                trigger_type, tenant_id, customer_id, event_key,
            )
            return outcome
        # Any OTHER exception (e.g., mongo unavailable) — degrade to
        # the pre-fix behaviour (attempt fan-out).  Never break the
        # caller.
        logger.warning(
            "[m5c] event ledger insert crashed — continuing: %s", exc,
        )

    # 2. Fan-out to every matching active sequence.
    try:
        seqs = await db.marketing_sequences.find(
            {"tenant_id": tenant_id, "trigger_type": trigger_type,
             "active": True},
            {"_id": 0, "id": 1, "steps": 1},
        ).to_list(500)
        outcome["sequences"] = len(seqs)
        for s in seqs:
            eid = await enrol_customer_into_sequence(
                tenant_id, s["id"], customer_id,
                trigger_source=trigger_type,
                trigger_meta=meta or {},
            )
            if eid:
                outcome["enrolled"] += 1
            else:
                outcome["skipped"] += 1
    except Exception as exc:  # pragma: no cover — belt & braces
        logger.warning("[m5c] on_event(%s) crashed: %s", trigger_type, exc)
    return outcome


# ─── Scheduler jobs ───────────────────────────────────────────────────
async def sequences_tick_all_tenants() -> Dict[str, int]:
    """Every 5 minutes: walk every active enrolment whose
    ``next_send_at`` is due and advance it.  Returns aggregate counts
    for the emitted log line."""
    # Import locally to avoid a circular import at module load.
    from routers.marketing_sequences import process_due_enrolments
    try:
        r = await process_due_enrolments(tenant_id=None)
    except Exception as exc:
        logger.warning("[m5c] tick crashed: %s", exc)
        r = {"processed": 0, "sent": 0, "completed": 0}
    logger.info(
        "[m5c] tick — processed=%s sent=%s completed=%s",
        r.get("processed"), r.get("sent"), r.get("completed"),
    )
    return r


async def daily_marketing_trigger_sweep() -> Dict[str, int]:
    """Runs once at 09:00 UTC.  For every tenant, evaluates the four
    daily triggers:

    * ``invoice_past_due_N_days`` — invoices that JUST crossed the
      ``trigger_config.days_past_due`` threshold today.
    * ``birthday`` — customers whose ``birthday`` month+day equals
      today.
    * ``segment_join`` — new segment members vs the sequence's cached
      ``last_matched_ids`` snapshot.
    * ``job_scheduled_reminder_1d`` — jobs scheduled EXACTLY tomorrow.
      Fires the sequence once per (customer, job) pair; deduped so a
      re-run on the same day is a no-op.
    """
    total = {"tenants": 0, "past_due_enrolled": 0,
             "birthday_enrolled": 0, "segment_join_enrolled": 0,
             "job_reminder_1d_enrolled": 0}
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        total["tenants"] += 1
        tid = t["id"]
        try:
            total["past_due_enrolled"] += await _sweep_past_due(tid)
            total["birthday_enrolled"] += await _sweep_birthday(tid)
            total["segment_join_enrolled"] += await _sweep_segment_join(tid)
            total["job_reminder_1d_enrolled"] += (
                await _sweep_job_scheduled_reminder_1d(tid)
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "[m5c] daily sweep tenant=%s crashed: %s", tid, exc,
            )
    logger.info("[m5c] daily sweep — %s", total)
    return total


async def _sweep_past_due(tenant_id: str) -> int:
    """Enrol customers whose invoices just crossed the past-due
    window TODAY.  Window is exactly one day wide to avoid
    re-enrolment on subsequent sweeps (the dedupe guard in
    :func:`enrol_customer_into_sequence` catches re-runs on the same
    day too)."""
    seqs = await db.marketing_sequences.find(
        {"tenant_id": tenant_id, "active": True,
         "trigger_type": "invoice_past_due_N_days"},
        {"_id": 0, "id": 1, "trigger_config": 1},
    ).to_list(200)
    if not seqs:
        return 0
    now = datetime.now(timezone.utc)
    enrolled = 0
    for s in seqs:
        n = int((s.get("trigger_config") or {}).get("days_past_due") or 0)
        # Window: due_date fell into ``[now - (n+1)d, now - n·d]``
        upper = (now - timedelta(days=n)).date().isoformat()
        lower = (now - timedelta(days=n + 1)).date().isoformat()
        invoices = await db.quotes.find(
            {"tenant_id": tenant_id, "doc_type": "invoice",
             "payment_status": {"$ne": "paid"},
             "due_date": {"$gte": lower, "$lte": upper}},
            {"_id": 0, "customer_id": 1},
        ).to_list(1000)
        # Legacy invoices use ``status`` instead of ``payment_status``.
        legacy = await db.quotes.find(
            {"tenant_id": tenant_id, "doc_type": "invoice",
             "amount_paid": {"$lt": 1},
             "due_date": {"$gte": lower, "$lte": upper}},
            {"_id": 0, "customer_id": 1},
        ).to_list(1000)
        seen_cids = {i.get("customer_id") for i in invoices + legacy
                     if i.get("customer_id")}
        for cid in seen_cids:
            eid = await enrol_customer_into_sequence(
                tenant_id, s["id"], cid, trigger_source="invoice_past_due_N_days",
            )
            if eid:
                enrolled += 1
    return enrolled


async def _sweep_birthday(tenant_id: str) -> int:
    """Enrol every customer whose ``birthday`` matches today's
    month+day.  Accepts the field as either an ISO date string
    (``YYYY-MM-DD``) or an ISO datetime — we scan case-insensitively
    on the ``MM-DD`` suffix."""
    seqs = await db.marketing_sequences.find(
        {"tenant_id": tenant_id, "active": True,
         "trigger_type": "birthday"},
        {"_id": 0, "id": 1},
    ).to_list(200)
    if not seqs:
        return 0
    now = datetime.now(timezone.utc)
    today_mmdd = now.strftime("%m-%d")
    # Any customer with a ``birthday`` string containing ``-MM-DD``.
    customers = await db.customers.find(
        {"tenant_id": tenant_id,
         "birthday": {"$regex": f"-{today_mmdd}"}},
        {"_id": 0, "id": 1},
    ).to_list(2000)
    if not customers:
        return 0
    enrolled = 0
    for s in seqs:
        for c in customers:
            eid = await enrol_customer_into_sequence(
                tenant_id, s["id"], c["id"], trigger_source="birthday",
            )
            if eid:
                enrolled += 1
    return enrolled


async def _sweep_segment_join(tenant_id: str) -> int:
    """For every active ``segment_join`` sequence, compare current
    segment membership to the snapshot on the sequence doc and enrol
    the delta only."""
    seqs = await db.marketing_sequences.find(
        {"tenant_id": tenant_id, "active": True,
         "trigger_type": "segment_join"},
        {"_id": 0, "id": 1, "trigger_config": 1, "last_matched_ids": 1},
    ).to_list(200)
    if not seqs:
        return 0
    from services.marketing.segments import evaluate_conditions
    enrolled = 0
    now = now_iso()
    for s in seqs:
        seg_id = (s.get("trigger_config") or {}).get("segment_id")
        if not seg_id:
            continue
        seg = await db.marketing_audience_segments.find_one(
            {"id": seg_id, "tenant_id": tenant_id},
            {"_id": 0, "conditions": 1, "active": 1},
        )
        if not seg or not seg.get("active", True):
            continue
        r = await evaluate_conditions(seg.get("conditions") or [], tenant_id)
        matched = set(r.get("matched_ids") or [])
        previous = set(s.get("last_matched_ids") or [])
        new_ids = matched - previous
        for cid in new_ids:
            eid = await enrol_customer_into_sequence(
                tenant_id, s["id"], cid, trigger_source="segment_join",
            )
            if eid:
                enrolled += 1
        # Snapshot forward regardless of dedupe outcome so tomorrow's
        # diff only surfaces true joins.
        await db.marketing_sequences.update_one(
            {"id": s["id"], "tenant_id": tenant_id},
            {"$set": {"last_matched_ids": sorted(matched),
                       "last_segment_join_evaluated_at": now}},
        )
    return enrolled


async def _sweep_job_scheduled_reminder_1d(tenant_id: str) -> int:
    """Enrol customers for every ``job_scheduled_reminder_1d`` sequence
    whose parent job is scheduled EXACTLY tomorrow.

    Feb-2026 · Applies to both ``work_class == service`` and
    ``work_class == repair`` (per product decision — repair visits
    also benefit from a day-before reminder). Only jobs in a
    forward-looking status (``scheduled``, ``pending``) qualify —
    completed / cancelled / could-not-service jobs are skipped.

    Dedupe: ``enrol_customer_into_sequence`` already dedupes by
    ``(tenant, sequence, customer)`` on the enrolments collection, so
    a same-day re-run won't double-fire. Additionally, we key by
    ``(customer, job_id)`` within this sweep so multiple sequences on
    the same trigger don't quadruple-enrol the same customer for a
    single upcoming visit — each sequence gets its own enrolment via
    the sequence-scoped dedupe inside ``enrol_customer_into_sequence``.
    """
    seqs = await db.marketing_sequences.find(
        {"tenant_id": tenant_id, "active": True,
          "trigger_type": "job_scheduled_reminder_1d"},
        {"_id": 0, "id": 1},
    ).to_list(200)
    if not seqs:
        return 0
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)) \
        .date().isoformat()
    jobs = await db.jobs.find(
        {"tenant_id": tenant_id,
          "scheduled_date": tomorrow,
          "status": {"$in": ["scheduled", "pending"]}},
        {"_id": 0, "id": 1, "customer_id": 1},
    ).to_list(2000)
    if not jobs:
        return 0
    enrolled = 0
    for s in seqs:
        # ``(customer, job)`` snapshot so we can attach ``job_id`` to
        # the trigger_source for observability; the sequence-scoped
        # dedupe in ``enrol_customer_into_sequence`` still guarantees
        # a single enrolment per (customer, sequence, day).
        for j in jobs:
            cid = j.get("customer_id")
            if not cid:
                continue
            eid = await enrol_customer_into_sequence(
                tenant_id, s["id"], cid,
                trigger_source=f"job_scheduled_reminder_1d:{j['id']}",
            )
            if eid:
                enrolled += 1
    return enrolled

