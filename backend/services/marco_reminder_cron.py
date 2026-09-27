"""Feb-2026 · MARCO · Sub-phase E — proactive admin_todo reminders.

Companion to :mod:`services.lana.reminder_cron` (Phase 49).  A
5-minute-cadence ``AsyncIOScheduler`` tick that scans the
``marco_admin_todos`` collection for open todos coming due within
15 minutes and fires an in-app bell notification + SSE broadcast
for each one, then stamps ``marco_pinged_at`` so subsequent ticks
don't re-fire the same reminder.

Order of operations (see Sub-phase E ruling #2)
────────────────────────────────────────────────
For every match we do, in strict order:

    1. Insert the notification row (via ``services.notifications
       .emit`` — the canonical bell/SSE fanout).
    2. Fan out over SSE (same call — ``emit`` calls
       ``routers.realtime.bus.broadcast`` internally).
    3. Stamp ``marco_pinged_at = now`` via ``findOneAndUpdate``
       gated on ``marco_pinged_at IS NULL``.  The null-check
       serves as the idempotency lock — a concurrent scanner
       won't double-stamp.  A mid-run crash between steps 1-2 and
       step 3 causes the next tick to re-fire (accepted duplicate
       risk per the brief; crash-tolerance beats silent-swallow
       for reminders).

Query semantics
───────────────
``{"marco_pinged_at": None}`` matches BOTH explicitly-null rows
AND rows missing the field entirely (MongoDB semantics).  Legacy
Sub-phase D rows that never carried the field are picked up
correctly without a migration (Sub-phase E ruling #7).

Failure handling
────────────────
If step 1/2 raise, we log a warning with ``todo_id`` + ``tenant_id``
and skip the stamp — next tick retries.  No exception ever leaks
out of the tick (best-effort loop).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("marco.reminders.cron")


# ── Severity mapping (Sub-phase E ruling #3) ──────────────────────
# admin_todo.priority → notification.priority ("severity" in the
# brief's language, but the bell UI reads the ``priority`` field on
# the notification row so we surface the semantic value there
# directly).  ``urgent`` and ``high`` get emphasised colours; ``med``
# and ``low`` land as neutral ``info``.
_SEVERITY_BY_PRIORITY = {
    "urgent": "urgent",
    "high": "warning",
    "med": "info",
    "low": "info",
}

# Default tz when the tenant has no ``timezone`` field configured.
# Matches ``services.marco_task_parser.DEFAULT_TZ`` for consistency
# across the MARCO subsystem.
_DEFAULT_TZ = "America/New_York"

# How far ahead we ping.  A 15-min horizon on a 5-min cadence means
# a due-soon todo is pinged at least 10 min before it fires.
_HORIZON_MINUTES = 15


# ══════════════════════════════════════════════════════════════════
# Public API.
# ══════════════════════════════════════════════════════════════════
async def _tick():
    """Job entrypoint — bound to APScheduler.  Late-imports ``db``
    so this module doesn't require a live DB handle at import time
    (keeps pytest fixtures hermetic + matches Lana's pattern)."""
    from server import db
    try:
        fired = await fire_due_admin_todos(db)
        if fired:
            logger.info(
                "[marco.reminders.cron] fired %d ping(s)", fired,
            )
    except Exception as exc:                                     # pragma: no cover
        logger.warning(
            "[marco.reminders.cron] tick failed: %s", exc,
        )


async def fire_due_admin_todos(
    db, now: Optional[datetime] = None,
) -> int:
    """Scan + fire.  Returns the number of successfully-stamped
    reminders.  Exposed at module scope so tests + a future
    admin-only manual-trigger endpoint can invoke a single tick
    deterministically.

    Parameters
    ----------
    db   : Motor async DB handle.
    now  : Reference "now".  Tests pass a fixed datetime; production
           callers pass ``None`` and we default to
           ``datetime.now(timezone.utc)``.
    """
    now = now or datetime.now(timezone.utc)
    horizon_iso = (now + timedelta(minutes=_HORIZON_MINUTES)).astimezone(
        timezone.utc,
    ).isoformat().replace("+00:00", "Z")
    now_iso = now.astimezone(timezone.utc).isoformat().replace(
        "+00:00", "Z",
    )

    query: Dict[str, Any] = {
        "status": "open",
        "due_at": {"$lte": horizon_iso},
        "marco_pinged_at": None,   # missing + null both match
    }

    fired = 0
    async for todo in db.marco_admin_todos.find(query, {"_id": 0}):
        try:
            await _emit_marco_reminder(db, todo, now)
        except Exception as exc:                                 # noqa: BLE001
            # Ruling #6 — do NOT stamp on emit failure; log + let
            # the next tick retry.
            logger.warning(
                "[marco.reminders.cron] emit failed for todo %s"
                " (tenant %s): %s",
                todo.get("id"), todo.get("tenant_id"), exc,
            )
            continue

        # Ruling #2 — stamp LAST via findOneAndUpdate with the
        # null-check so we can't stamp a row a concurrent scanner
        # already claimed.
        res = await db.marco_admin_todos.find_one_and_update(
            {"id": todo["id"], "marco_pinged_at": None},
            {"$set": {"marco_pinged_at": now_iso}},
        )
        if res is not None:
            fired += 1
    return fired


# ══════════════════════════════════════════════════════════════════
# Helpers.
# ══════════════════════════════════════════════════════════════════
async def _emit_marco_reminder(db, todo: Dict[str, Any],
                                  now: datetime) -> None:
    """Compose title/body/severity + route through the canonical
    notifications engine (``services.notifications.emit``).  That
    engine writes to ``db.notifications`` AND fans out through
    ``routers.realtime.bus.broadcast`` (our SSE hub).  We do NOT
    re-implement either — this is a MARCO-only compose-and-forward.
    """
    from services.notifications import emit as notif_emit

    tz = await _resolve_tenant_tz(db, todo.get("tenant_id"))
    due_local = _format_local(todo.get("due_at"), tz)
    priority = str(todo.get("priority") or "med").lower()
    severity = _SEVERITY_BY_PRIORITY.get(priority, "info")

    title = "MARCO Reminder"
    body = f"'{todo.get('title', '')}' is due at {due_local}"
    href = f"/admin/todos/{todo.get('id', '')}"
    created_by = todo.get("created_by")
    if not created_by:
        # Sub-phase D always populates created_by; a legacy row
        # without it can't be routed to a user.  Skip.
        raise ValueError("todo missing created_by — cannot route ping")

    await notif_emit(
        [created_by],
        kind="marco_todo_due",
        title=title,
        body=body,
        href=href,
        tenant_id=todo.get("tenant_id"),
        audience="internal",
        priority=severity,
        source_ref={
            "kind": "admin_todo",
            "id": todo.get("id"),
            "severity": severity,
            "priority": priority,
        },
    )


async def _resolve_tenant_tz(db, tenant_id: Optional[str]) -> str:
    """Look up the tenant's IANA timezone with a safe default.
    Reads ``tenants.timezone`` per Phase 56.17 (admin-editable
    tenant timezone).  Falls back to ``America/New_York`` when
    unset — same default as ``services.marco_task_parser`` for
    consistency across the MARCO subsystem."""
    if not tenant_id:
        return _DEFAULT_TZ
    row = await db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0, "timezone": 1},
    ) or {}
    return (row.get("timezone") or "").strip() or _DEFAULT_TZ


def _format_local(due_at_iso: Optional[str], tz: str) -> str:
    """Format an ISO datetime string into a human-readable
    tz-aware label (e.g. ``Feb 11, 3:00 PM EST``).  Falls back to
    the raw ISO string when parsing fails."""
    if not due_at_iso:
        return "an unspecified time"
    try:
        from zoneinfo import ZoneInfo
        cleaned = due_at_iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(ZoneInfo(tz))
        # ``%-d`` / ``%-I`` are POSIX-only (no leading zero); we
        # accept the platform assumption since the pod is Linux.
        return local.strftime("%b %-d, %-I:%M %p %Z")
    except Exception:                                            # noqa: BLE001
        return str(due_at_iso)


# ══════════════════════════════════════════════════════════════════
# Scheduler registration.  Called from server.py alongside Lana's
# ``register_lana_reminders_cron``.  Feeding a coroutine function
# directly is safe under ``AsyncIOScheduler`` (same pattern as the
# Phase 49 hotfix for Lana's cron).
# ══════════════════════════════════════════════════════════════════
def register_marco_reminders_cron(scheduler) -> None:
    if scheduler is None:
        return
    from apscheduler.triggers.interval import IntervalTrigger
    try:
        scheduler.add_job(
            _tick,
            IntervalTrigger(minutes=5),
            id="marco.reminders.tick",
            replace_existing=True,
        )
        logger.info(
            "[marco.reminders.cron] 5-min-cadence reminder tick"
            " registered",
        )
    except Exception as exc:                                     # pragma: no cover
        logger.warning(
            "[marco.reminders.cron] scheduler registration failed:"
            " %s", exc,
        )


__all__ = [
    "fire_due_admin_todos",
    "register_marco_reminders_cron",
]
