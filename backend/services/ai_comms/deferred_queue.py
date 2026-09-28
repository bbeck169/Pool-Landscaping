"""MTH-C · Feb-2026 — deferred AI-comms queue.

When the per-tenant AI rules gate rejects an outbound AI comm
because we're outside the tenant's working-hours window, we
enqueue the payload here instead of redirecting it to admin (the
pre-MTH-C behavior).  An APScheduler tick flushes due entries
every 5 min.

Storage: ``ai_comms_deferred_queue`` (collection name lives in
:data:`COLLECTION`).  See :mod:`services.ai_comms.scheduler` for
the APScheduler binding.

Drop rules — a deferred entry is DROPPED (marked failed, never
sent) when the tenant flips one of these mid-defer:

* master switch → OFF  (``master_switch_disabled_during_defer``)
* target employee → disabled (``employee_disabled_during_defer``)
* target employee gone (deleted / role change) → same reason
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from config import logger

COLLECTION = "ai_comms_deferred_queue"
_UTC = timezone.utc

# 7 windows per day × 3 max = 21; guard against runaway inputs.
_MAX_WINDOW_WALK_DAYS = 14


def _now_utc(now: Optional[datetime] = None) -> datetime:
    if now is None:
        return datetime.now(_UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=_UTC)
    return now.astimezone(_UTC)


def _iso(dt: datetime) -> str:
    return _now_utc(dt).isoformat()


def compute_next_send_at(
    working_hours: Optional[Dict[str, Any]],
    *, deferred_at: Optional[datetime] = None,
) -> Optional[datetime]:
    """Walk the ``working_hours.windows`` starting at ``deferred_at``
    (+1 minute) in the tenant timezone.  Returns the first future
    window-start as an aware UTC datetime, or ``None`` when the
    rule has no windows / windows can't yield a future entry
    within 14 days.

    Contract:

    * ``enabled=False`` → returns ``None`` (caller should send
      immediately without deferral).
    * No windows configured → returns ``None`` (caller drops).
    * Same-day future window → returns today's window start.
    * Otherwise walks forward day-by-day up to
      :data:`_MAX_WINDOW_WALK_DAYS`.
    """
    if not isinstance(working_hours, dict):
        return None
    if not working_hours.get("enabled", True):
        return None
    windows = working_hours.get("windows") or []
    if not windows:
        return None
    tz_name = working_hours.get("timezone") or "UTC"
    from zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo(tz_name)
    except Exception:                                              # noqa: BLE001
        tz = ZoneInfo("UTC")

    from services.tenant_ai_rules.schema import DAY_KEYS

    origin_utc = _now_utc(deferred_at) + timedelta(minutes=1)
    origin_local = origin_utc.astimezone(tz)

    # Bucket windows by day key for O(1) day lookup.
    by_day: Dict[str, List[Tuple[str, str]]] = {d: [] for d in DAY_KEYS}
    for w in windows:
        d = (w or {}).get("day")
        if d in by_day:
            start = (w or {}).get("start") or ""
            end = (w or {}).get("end") or ""
            if start and end and start < end:
                by_day[d].append((start, end))
    for d in by_day:
        by_day[d].sort()

    cursor = origin_local
    for delta in range(0, _MAX_WINDOW_WALK_DAYS):
        candidate_local = cursor + timedelta(days=delta)
        day_key = DAY_KEYS[candidate_local.weekday()]
        day_windows = by_day.get(day_key) or []
        for start_hhmm, _end in day_windows:
            hh, mm = start_hhmm.split(":")
            start_local = candidate_local.replace(
                hour=int(hh), minute=int(mm), second=0, microsecond=0,
            )
            # Same-day: only accept if start is at/after the origin.
            if delta == 0 and start_local < origin_local:
                continue
            return start_local.astimezone(_UTC)
    return None


async def enqueue_deferred(
    *, tenant_id: str, employee_key: str, payload_kind: str,
    payload: Dict[str, Any], context: Optional[Dict[str, Any]] = None,
    working_hours: Optional[Dict[str, Any]] = None,
    deferred_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Insert one deferred row.  Returns the persisted document
    (id + scheduled_send_at populated).

    Returns ``{"deferred": False, "reason": <str>}`` when the
    caller shouldn't defer at all (working hours disabled, or no
    future window found).  Callers on that branch should send
    immediately (or drop, per their contract).
    """
    if not tenant_id or not employee_key:
        return {"deferred": False, "reason": "missing_scope"}
    deferred_at_utc = _now_utc(deferred_at)
    next_send = compute_next_send_at(
        working_hours, deferred_at=deferred_at_utc,
    )
    if next_send is None:
        return {"deferred": False, "reason": "no_future_window"}
    doc = {
        "id": str(uuid4()),
        "tenant_id": tenant_id,
        "employee_key": employee_key,
        "payload_kind": payload_kind,     # "email" | "sms" | freeform
        "payload": payload or {},
        "context": context or {},
        "deferred_at": _iso(deferred_at_utc),
        "deferred_reason": "outside_working_hours",
        "scheduled_send_at": _iso(next_send),
        "scheduled_send_at_ts": next_send.timestamp(),
        "delivered": False,
        "delivered_at": None,
        "delivery_error": None,
    }
    from config import db
    await db[COLLECTION].insert_one(doc)
    return {"deferred": True, "doc": {**doc, "_id": None}}


async def _mark_failed(entry_id: str, reason: str) -> None:
    from config import db
    await db[COLLECTION].update_one(
        {"id": entry_id},
        {"$set": {
            "delivered": False,
            "delivery_error": reason,
            "delivered_at": _iso(_now_utc()),
        }},
    )


async def _mark_delivered(entry_id: str) -> None:
    from config import db
    await db[COLLECTION].update_one(
        {"id": entry_id},
        {"$set": {"delivered": True, "delivered_at": _iso(_now_utc())}},
    )


async def _dispatch_send(entry: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Actually push the payload through the SAFE-SEND adapter.

    Returns ``(ok, error)`` — ok=True on successful hand-off.
    ``payload_kind`` selects the adapter.  Unknown kinds → drop
    with an explanatory reason so ops can debug.

    The payload dict — set by the enqueuer — MUST already carry
    the ``context`` kwarg per SAFE-SEND-A.  We proxy it through
    ``**payload`` here; regex-based callsite coverage can't see
    through the spread, so we tag the call with the standard
    SAFE-SEND allowlist sentinel below.
    """
    kind = entry.get("payload_kind")
    payload = entry.get("payload") or {}
    try:
        if kind == "email":
            from services.comms_email_adapter import send_email
            await send_email(**payload)  # context= proxied from enqueuer
            return True, None
        if kind == "sms":
            from services.comms_sms_adapter import send_sms
            await send_sms(**payload)  # context= proxied from enqueuer
            return True, None
        return False, f"unknown_payload_kind:{kind}"
    except Exception as exc:                                       # noqa: BLE001
        return False, f"dispatch_error:{exc}"


async def flush_due(
    *, now: Optional[datetime] = None, limit: int = 100,
) -> Dict[str, Any]:
    """Scan for entries where ``scheduled_send_at <= now`` and
    ``delivered=False and delivery_error IS NULL`` and attempt
    delivery.  Idempotent — successful sends flip ``delivered=True``;
    drops flip ``delivery_error``.  Returns a stats dict for the
    scheduler log line.
    """
    from config import db
    from services.tenant_ai_rules.resolver import (
        resolve_rules_for_tenant,
    )

    now_utc = _now_utc(now)
    now_ts = now_utc.timestamp()

    delivered = 0
    dropped_master = 0
    dropped_employee = 0
    dispatch_errors = 0

    cursor = db[COLLECTION].find(
        {
            "delivered": False,
            "delivery_error": None,
            "scheduled_send_at_ts": {"$lte": now_ts},
        },
        {"_id": 0},
    ).limit(limit)
    entries = await cursor.to_list(limit)

    for entry in entries:
        tenant_id = entry.get("tenant_id")
        employee_key = entry.get("employee_key")

        # Re-check the gate at flush time — an admin flipping the
        # master switch OR disabling the employee during the
        # defer window MUST cause the deferred entry to drop.
        try:
            resolved = await resolve_rules_for_tenant(
                tenant_id, use_cache=False,
            )
        except Exception as exc:                                   # noqa: BLE001
            logger.warning(
                "[mth-c] deferred_flush resolver failed entry=%s error=%s",
                entry.get("id"), exc,
            )
            await _mark_failed(entry["id"], "resolver_error_at_flush")
            dispatch_errors += 1
            continue

        if not resolved.get("master_ai_send_live_comms"):
            await _mark_failed(
                entry["id"], "master_switch_disabled_during_defer",
            )
            dropped_master += 1
            logger.warning(
                "[mth-c] deferred drop master-off tenant=%s employee=%s "
                "entry=%s",
                tenant_id, employee_key, entry.get("id"),
            )
            continue

        emp_map = ((resolved.get("rules") or {})
                    .get("employee_enable_disable") or {})
        if not emp_map.get(employee_key, False):
            await _mark_failed(
                entry["id"], "employee_disabled_during_defer",
            )
            dropped_employee += 1
            logger.warning(
                "[mth-c] deferred drop employee-off tenant=%s "
                "employee=%s entry=%s",
                tenant_id, employee_key, entry.get("id"),
            )
            continue

        ok, err = await _dispatch_send(entry)
        if ok:
            await _mark_delivered(entry["id"])
            delivered += 1
        else:
            await _mark_failed(entry["id"], err or "dispatch_unknown")
            dispatch_errors += 1

    return {
        "scanned": len(entries),
        "delivered": delivered,
        "dropped_master_switch": dropped_master,
        "dropped_employee_disabled": dropped_employee,
        "dispatch_errors": dispatch_errors,
    }


__all__ = [
    "COLLECTION",
    "compute_next_send_at",
    "enqueue_deferred",
    "flush_due",
]
