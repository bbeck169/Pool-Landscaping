"""Feb 2026 · Marketing · Phase 1 — Boot migration for the schema-v2
trigger shape on ``marketing_sequences``.

Contract:
  * Runs on every server boot.
  * Idempotent — sequences already at ``schema_version >= 2`` are
    skipped (no write). Second-and-later boots on a clean DB are a
    no-op.
  * For every legacy sequence carrying a scalar ``trigger_type`` +
    ``trigger_config``, synthesises a v2 ``trigger`` document::

        {
          "logic": "AND",
          "conditions": [
            {"event": <canonicalize(trigger_type)>,
              "delay": {"mode": "immediate"},
              "filters": {}}
          ]
        }

    and stamps ``schema_version = 2``. The legacy ``trigger_type`` +
    ``trigger_config`` fields are PRESERVED (never deleted) so the
    legacy fanout in ``drip_events.on_event`` keeps functioning
    during the migration window.
  * Emits a summary log at INFO: ``migrated=N skipped=M preserved=N``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from config import db

from services.marketing.event_registry import (
    canonicalize_event_key,
    is_valid_event,
    NON_EVENT_LEGACY_TRIGGERS,
)


logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_v2_trigger(trigger_type: str,
                      trigger_config: Dict[str, Any] | None) -> Dict[str, Any]:
    """Given a legacy scalar trigger, return the v2 nested trigger
    dict.

    The mapping is deliberately conservative — every legacy trigger
    becomes a single-condition AND with an ``immediate`` delay and
    empty filters. Preserves 100% behavioural fidelity vs the legacy
    fanout (which had no filters and always enrolled immediately).

    ``invoice_past_due_N_days`` is special: it CARRIES a
    ``days_past_due`` in ``trigger_config``. We translate that into
    a ``delay = {"mode":"after", "value":days, "unit":"day"}`` on
    the canonicalised ``invoice_overdue`` event so the day-N
    semantics survive.

    Non-event enrolment surfaces (``manual``, ``segment_join``) are
    migrated to a v2 doc with an EMPTY ``conditions`` array — the
    evaluator returns False on empty conditions, so those sequences
    never accidentally fire from :func:`emit_event`. Manual sequences
    still enrol via ``POST /marketing/sequences/{sid}/enrol`` and
    segment_join sequences still enrol via the daily M5c sweep
    (both paths bypass the trigger evaluator entirely).
    """
    legacy = (trigger_type or "").strip()
    # Non-event surfaces → empty v2 trigger.
    if legacy in NON_EVENT_LEGACY_TRIGGERS:
        return {"logic": "AND", "conditions": []}
    canonical = canonicalize_event_key(legacy)
    if not canonical or not is_valid_event(canonical):
        canonical = legacy  # keep the legacy key visible for ops review
    condition: Dict[str, Any] = {
        "event": canonical,
        "delay": {"mode": "immediate"},
        "filters": {},
    }
    # ``invoice_past_due_N_days`` — preserve the day-offset semantics
    # by lifting ``days_past_due`` into the condition's ``delay``.
    days_pd = 0
    if isinstance(trigger_config, dict):
        try:
            days_pd = int(trigger_config.get("days_past_due") or 0)
        except (TypeError, ValueError):
            days_pd = 0
    if canonical == "invoice_overdue" and days_pd > 0:
        condition["delay"] = {"mode": "after", "value": days_pd, "unit": "day"}
    return {"logic": "AND", "conditions": [condition]}


def _all_conditions_reference_canonical_events(
    trigger: Dict[str, Any] | None,
) -> bool:
    """Return True iff every ``trigger.conditions[].event`` is either
    a canonical event key OR the conditions list is empty (non-event
    surface).

    Used as the strict-idempotency guard: a v2 doc whose conditions
    reference a legacy key (e.g. leftover ``event: "manual"`` from an
    earlier migration pass) needs to be re-migrated. Empty conditions
    are always canonical.
    """
    if not isinstance(trigger, dict):
        return False
    conds = trigger.get("conditions") or []
    if not isinstance(conds, list):
        return False
    for c in conds:
        ev = str((c or {}).get("event") or "")
        if not is_valid_event(ev):
            return False
    return True


async def migrate_marketing_sequences_to_v2() -> Dict[str, Any]:
    """Idempotent boot migration. Returns a summary dict::

        {
          "scanned": int,
          "migrated": int,
          "already_v2": int,
          "unresolvable": int,       # sequences with no trigger_type at all
          "tenants_touched": int,
        }
    """
    scanned = 0
    migrated = 0
    already_v2 = 0
    unresolvable = 0
    tenants_touched: set[str] = set()

    cursor = db.marketing_sequences.find(
        {},
        {"_id": 0, "id": 1, "tenant_id": 1, "trigger_type": 1,
         "trigger_config": 1, "trigger": 1, "schema_version": 1},
    )
    async for seq in cursor:
        scanned += 1
        sid = seq.get("id")
        tid = seq.get("tenant_id")
        if not (sid and tid):
            unresolvable += 1
            continue
        version = int(seq.get("schema_version") or 1)
        has_v2_trigger = (
            isinstance(seq.get("trigger"), dict)
            and isinstance((seq.get("trigger") or {}).get("conditions"),
                             list)
        )
        legacy_type = (seq.get("trigger_type") or "").strip()
        conds_now = ((seq.get("trigger") or {}).get("conditions") or []) \
            if has_v2_trigger else []
        # Non-event trigger surfaces (manual / segment_join) must land
        # with EMPTY conditions. If they got mis-migrated with a
        # non-empty ``conditions`` array in an earlier pass (e.g. the
        # bogus ``segment_join → new_lead`` alias that was later
        # removed), force a re-migration to a clean empty-conditions
        # v2 doc.
        non_event_needs_repair = (
            legacy_type in NON_EVENT_LEGACY_TRIGGERS
            and has_v2_trigger and len(conds_now) > 0
        )
        # Strict idempotency guard — a sequence is "already v2" ONLY
        # when it satisfies ALL: schema_version>=2, well-shaped
        # trigger doc, every condition.event references a CANONICAL
        # event id (or the conditions list is empty), AND non-event
        # trigger surfaces have empty conditions.
        if (version >= 2 and has_v2_trigger
                and _all_conditions_reference_canonical_events(
                    seq.get("trigger"))
                and not non_event_needs_repair):
            already_v2 += 1
            continue
        legacy_type = seq.get("trigger_type") or ""
        if not legacy_type:
            unresolvable += 1
            continue
        v2_trigger = _build_v2_trigger(legacy_type, seq.get("trigger_config"))
        await db.marketing_sequences.update_one(
            {"id": sid, "tenant_id": tid},
            {"$set": {
                "trigger": v2_trigger,
                "schema_version": 2,
                "schema_v2_migrated_at": _now_iso(),
            }},
        )
        migrated += 1
        tenants_touched.add(tid)

    report = {
        "scanned": scanned,
        "migrated": migrated,
        "already_v2": already_v2,
        "unresolvable": unresolvable,
        "tenants_touched": len(tenants_touched),
    }
    logger.info(
        "[marketing.v2] migrated %d sequences, skipped %d (already v2), "
        "preserved trigger fidelity for all %d — tenants=%d unresolvable=%d",
        migrated, already_v2, migrated, len(tenants_touched), unresolvable,
    )
    return report
