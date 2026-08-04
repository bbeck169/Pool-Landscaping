"""Phase 49 · Feb-2026 — Lana reminder cron registration.

Attaches a minute-cadence job to the EXISTING APScheduler singleton
that ``server.py`` already owns (an ``AsyncIOScheduler``). No new
scheduler.

Phase 49 hotfix — the earlier revision wrapped the coroutine in a
sync ``_run()`` that called ``asyncio.get_event_loop()`` from an
APScheduler worker thread, which reliably failed with
``There is no current event loop in thread 'asyncio_0'`` and left the
cron silently broken. ``AsyncIOScheduler`` supports coroutine jobs
natively; we now hand it the coroutine function directly (Option (c)
in the P0 fix — safe because the shared scheduler is confirmed
``AsyncIOScheduler`` in ``server.py::scheduler``).
"""
from __future__ import annotations

import logging

logger = logging.getLogger("lana.reminders.cron")


async def _tick():
    # Late DB import so this module doesn't require a live db handle
    # at import time (keeps the pytest surface hermetic).
    from server import db
    from services.lana.reminders import fire_due_reminders
    try:
        fired = await fire_due_reminders(db)
        if fired:
            logger.info("[lana.reminders.cron] fired %d reminder(s)", fired)
    except Exception as exc:  # pragma: no cover — best-effort loop
        logger.warning("[lana.reminders.cron] tick failed: %s", exc)


def register_lana_reminders_cron(scheduler) -> None:
    """Register the minute-tick job on the app's ``AsyncIOScheduler``.
    Feeding a coroutine function directly is safe because
    ``AsyncIOScheduler`` runs jobs on its own event loop; no thread /
    loop bridging needed."""
    if scheduler is None:
        return
    from apscheduler.triggers.interval import IntervalTrigger
    try:
        scheduler.add_job(
            _tick,
            IntervalTrigger(minutes=1),
            id="lana.reminders.tick",
            replace_existing=True,
        )
        logger.info("[lana.reminders.cron] minute-cadence reminder tick registered")
    except Exception as exc:
        logger.warning("[lana.reminders.cron] scheduler registration failed: %s", exc)
