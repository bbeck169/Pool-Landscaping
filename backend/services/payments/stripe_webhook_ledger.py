"""Phase B3 · Feb-2026 — Stripe webhook dedup ledger + dead-letter helpers.

Two collections back this module:

  * ``stripe_webhook_events`` — first-line dedup ledger. First
    ``event.id`` insert wins (unique index). The second attempt
    raises ``DuplicateKeyError`` → handler short-circuits with
    ``status=skipped_duplicate`` so the router returns 200 to
    Stripe (avoids infinite retries).
  * ``stripe_webhook_dead_letter`` — records handler crashes so
    operators can inspect + replay via the super_admin admin
    endpoints. Keyed by ``event_id``; ``retry_count`` auto-
    increments across dispatch attempts.

Both indexes are created by
``services/migrations/stripe_webhook_hardening.py`` on boot.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pymongo.errors import DuplicateKeyError

from config import db


logger = logging.getLogger("stripe_webhook_ledger")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_tenant_hint(event: Dict[str, Any]) -> Optional[str]:
    """Best-effort tenant resolution from the event object metadata.

    Not enforced — used for observability only. Looks in the standard
    places we stamp ``crm_tenant_id`` (metadata) across every
    Stripe object we create in this codebase.
    """
    if not isinstance(event, dict):
        return None
    obj = ((event.get("data") or {}).get("object") or {})
    if not isinstance(obj, dict):
        return None
    meta = obj.get("metadata") or {}
    if isinstance(meta, dict):
        hint = meta.get("crm_tenant_id")
        if hint:
            return str(hint)
    # Subscriptions: fall back to the linked customer metadata if
    # Stripe returned it (present when the customer was created by
    # our SDK path).
    cust_meta = ((obj.get("customer") or {}) if isinstance(obj.get("customer"), dict) else {})
    cm = cust_meta.get("metadata") or {}
    if isinstance(cm, dict) and cm.get("crm_tenant_id"):
        return str(cm["crm_tenant_id"])
    return None


async def insert_or_skip(
    event: Dict[str, Any],
    *,
    raw_payload_ref: Optional[str] = None,
) -> Dict[str, Any]:
    """Attempt to insert the event id into the ledger.

    Returns:
        ``{"status": "received", "event_id": ...}`` on first delivery.
        ``{"status": "skipped_duplicate", "event_id": ...}`` on retry.
        ``{"status": "no_event_id"}`` if the payload didn't carry an
        ``id`` (defensive — should never fire for a real Stripe event).
    """
    event_id = event.get("id") if isinstance(event, dict) else None
    if not event_id:
        return {"status": "no_event_id"}
    event_type = event.get("type") or ""
    tenant_hint = _extract_tenant_hint(event)
    row = {
        "event_id": event_id,
        "event_type": event_type,
        "tenant_id_hint": tenant_hint,
        "received_at": _now_iso(),
        "first_handled_at": None,
        "status": "received",
        "raw_payload_ref": raw_payload_ref,
        "retry_count": 0,
    }
    try:
        await db.stripe_webhook_events.insert_one(row)
        return {"status": "received", "event_id": event_id}
    except DuplicateKeyError:
        # Second attempt for the same event.id — bump retry_count for
        # visibility but do NOT re-run the handler. Stripe retries
        # after 5xx so the count is a real "network-level replay"
        # counter.
        await db.stripe_webhook_events.update_one(
            {"event_id": event_id},
            {"$inc": {"retry_count": 1},
             "$set": {"last_duplicate_at": _now_iso()}},
        )
        return {"status": "skipped_duplicate", "event_id": event_id}


async def mark_handled(event_id: str, *, result: Optional[Dict[str, Any]] = None) -> None:
    if not event_id:
        return
    upd: Dict[str, Any] = {
        "status": "handled",
        "first_handled_at": _now_iso(),
    }
    if result is not None:
        upd["handler_result"] = result
    await db.stripe_webhook_events.update_one(
        {"event_id": event_id},
        {"$set": upd},
    )


async def mark_failed(event_id: str, *, error: str) -> None:
    if not event_id:
        return
    await db.stripe_webhook_events.update_one(
        {"event_id": event_id},
        {"$set": {"status": "failed", "last_error": error[:2000]}},
    )


async def record_dead_letter(
    event: Dict[str, Any],
    *,
    error_class: str,
    error_message: str,
    stack_trace: str,
    raw_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Upsert a dead-letter row keyed on ``event_id``.

    Retry count auto-increments so operators can spot events that
    keep failing across Stripe's own retry cadence.
    """
    event_id = event.get("id") if isinstance(event, dict) else None
    if not event_id:
        return {"status": "no_event_id"}
    event_type = event.get("type") or ""
    tenant_hint = _extract_tenant_hint(event)
    now = _now_iso()
    # `$setOnInsert` fields — set only on first failure.
    insert_only = {
        "id": str(uuid.uuid4()),
        "event_id": event_id,
        "first_failed_at": now,
        "resolved": False,
        "retry_count": 1,
        "raw_payload": raw_payload,
    }
    # `$set` fields — refreshed every failure so the latest error
    # wins. ``last_retry_at`` lives only here to avoid conflicting
    # with $setOnInsert (Mongo path-uniqueness rule).
    set_fields = {
        "last_retry_at": now,
        "error_class": error_class,
        "error_message": (error_message or "")[:4000],
        "stack_trace": (stack_trace or "")[:8000],
        "event_type": event_type,
        "tenant_id_hint": tenant_hint,
    }
    try:
        await db.stripe_webhook_dead_letter.update_one(
            {"event_id": event_id},
            {
                "$setOnInsert": insert_only,
                "$set": set_fields,
                "$inc": {"retry_count_after_first": 1},
            },
            upsert=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[stripe_webhook_dead_letter] upsert failed: %s", exc)
        return {"status": "dead_letter_write_failed", "error": str(exc)}
    return {"status": "recorded", "event_id": event_id}


async def list_dead_letter(*, resolved: bool = False, limit: int = 50) -> Any:
    cursor = db.stripe_webhook_dead_letter.find(
        {"resolved": resolved},
        {"_id": 0},
    ).sort("first_failed_at", -1).limit(limit)
    return [row async for row in cursor]


async def get_dead_letter_row(event_id: str) -> Optional[Dict[str, Any]]:
    return await db.stripe_webhook_dead_letter.find_one(
        {"event_id": event_id}, {"_id": 0},
    )


async def mark_dead_letter_resolved(event_id: str) -> Dict[str, Any]:
    r = await db.stripe_webhook_dead_letter.update_one(
        {"event_id": event_id},
        {"$set": {"resolved": True, "resolved_at": _now_iso()}},
    )
    return {"matched": r.matched_count, "modified": r.modified_count}
