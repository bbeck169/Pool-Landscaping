"""Feb-2026 · New-lead sequence trigger fan-out.

Fires the ``new_lead`` marketing-sequence trigger the instant a lead
is inserted into ``db.leads`` — regardless of the ingestion path
(public widget, marketing forms, manual admin POST, RingCentral
contact sync, portal referral, D2D field capture, property intake,
etc.). Every call site is expected to invoke
:func:`fire_new_lead_sequence_trigger` immediately after a
successful ``db.leads.insert_one`` and pass its ``BackgroundTasks``
handle so the enrolment fan-out never bounds request latency.

Idempotency: dedupe keyed on
``(tenant_id, sequence_id, "lead:{lead_id}")`` inside
``enrol_customer_into_sequence`` — the sequence-scoped guard
prevents the same lead from being enrolled twice into the same
sequence even if the caller mistakenly fires this helper more than
once. A lead that later converts to a real customer keeps the
enrolment intact (the customer_id on the enrolment doc is the
lead's id — sequence sends still resolve via the merge-tag context
which will look through the ``leads`` collection).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks

from config import db, logger


async def _enrol_lead_into_sequence(
    tenant_id: str, sequence_id: str, lead_id: str,
) -> None:
    """Background task — enrols one lead into one sequence, deduped."""
    try:
        from services.marketing.drip_events import (
            enrol_customer_into_sequence,
        )
        await enrol_customer_into_sequence(
            tenant_id=tenant_id,
            sequence_id=sequence_id,
            customer_id=lead_id,      # lead id is stored as customer_id
            trigger_source=f"new_lead:{lead_id}",
        )
    except Exception as exc:  # pragma: no cover
        logger.warning(
            f"[new_lead trigger] enrolment failed tenant={tenant_id} "
            f"seq={sequence_id} lead={lead_id}: {exc}"
        )


async def fire_new_lead_sequence_trigger(
    *,
    lead: Dict[str, Any],
    tenant_id: str,
    background_tasks: Optional[BackgroundTasks] = None,
) -> Dict[str, int]:
    """Fan-out helper. Enrols the lead into every ACTIVE tenant
    sequence whose ``trigger_type == "new_lead"``.

    * Cross-tenant safe: the caller MUST pass the ``tenant_id`` that
      owns the lead — this helper never re-derives it.
    * Dedupes at the sequence-scope via
      :func:`enrol_customer_into_sequence`.
    * When ``background_tasks`` is provided every enrolment is
      dispatched via ``BackgroundTasks.add_task`` (real-time-ish, sub-
      second after the parent request completes). When not (e.g.
      when the caller is itself a background task or a scheduled
      job), enrolments run inline.

    Returns ``{sequences_matched, enrolments_dispatched}`` for
    observability + tests. No-op when the lead has no id or the
    tenant has no active new-lead sequences.
    """
    lead_id = str(lead.get("id") or "").strip()
    if not (lead_id and tenant_id):
        return {"sequences_matched": 0, "enrolments_dispatched": 0}

    seqs: List[Dict[str, Any]] = await db.marketing_sequences.find(
        {"tenant_id": tenant_id, "active": True,
          "trigger_type": "new_lead"},
        {"_id": 0, "id": 1},
    ).to_list(200)
    if not seqs:
        return {"sequences_matched": 0, "enrolments_dispatched": 0}

    dispatched = 0
    for s in seqs:
        sid = s.get("id")
        if not sid:
            continue
        if background_tasks is not None:
            background_tasks.add_task(
                _enrol_lead_into_sequence, tenant_id, sid, lead_id,
            )
        else:
            await _enrol_lead_into_sequence(tenant_id, sid, lead_id)
        dispatched += 1
    return {"sequences_matched": len(seqs),
             "enrolments_dispatched": dispatched}
