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
) -> Optional[str]:
    """Insert one enrolment doc (or skip if one is already active).
    Returns the new enrolment id when a doc is inserted, ``None``
    when the enrolment was deduped or the sequence is missing."""
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
        "enrolled_at": now_iso(),
        "current_step": 0,
        "next_send_at": next_at if steps else None,
        "status": "active" if steps else "completed",
        "halt_reason": None,
        "history": [],
    }
    await db.marketing_drip_enrolments.insert_one(doc)
    return doc["id"]


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

        {"enrolled": <int>, "skipped": <int>, "sequences": <int>}
    """
    outcome = {"enrolled": 0, "skipped": 0, "sequences": 0}
    if trigger_type not in _IMMEDIATE_TRIGGERS:
        return outcome
    if not (tenant_id and customer_id):
        return outcome
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
    """Runs once at 09:00 UTC.  For every tenant, evaluates the three
    daily triggers:

    * ``invoice_past_due_N_days`` — invoices that JUST crossed the
      ``trigger_config.days_past_due`` threshold today.
    * ``birthday`` — customers whose ``birthday`` month+day equals
      today.
    * ``segment_join`` — new segment members vs the sequence's cached
      ``last_matched_ids`` snapshot.
    """
    total = {"tenants": 0, "past_due_enrolled": 0,
             "birthday_enrolled": 0, "segment_join_enrolled": 0}
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        total["tenants"] += 1
        tid = t["id"]
        try:
            total["past_due_enrolled"] += await _sweep_past_due(tid)
            total["birthday_enrolled"] += await _sweep_birthday(tid)
            total["segment_join_enrolled"] += await _sweep_segment_join(tid)
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
