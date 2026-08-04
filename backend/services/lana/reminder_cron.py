"""Phase 49 · Feb-2026 — Lana reminder cron registration.

Attaches a minute-cadence job to the EXISTING APScheduler singleton
that ``server.py`` already owns. No new scheduler.
"""
from __future__ import annotations

import asyncio
import logging

from services.lana.reminders import fire_due_reminders

logger = logging.getLogger("lana.reminders.cron")


def register_lana_reminders_cron(scheduler) -> None:
    if scheduler is None:
        return
    from apscheduler.triggers.interval import IntervalTrigger

    def _run():
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(fire_due_reminders_wrapper())
            else:
                loop.run_until_complete(fire_due_reminders_wrapper())
        except Exception as exc:
            logger.warning("[lana.reminders.cron] tick failed: %s", exc)

    async def fire_due_reminders_wrapper():
        # Late import so the DB handle isn't touched at module import time.
        from server import db
        fired = await fire_due_reminders(db)
        if fired:
            logger.info("[lana.reminders.cron] fired %d reminder(s)", fired)

    try:
        scheduler.add_job(
            _run,
            IntervalTrigger(minutes=1),
            id="lana.reminders.tick",
            replace_existing=True,
        )
        logger.info("[lana.reminders.cron] minute-cadence reminder tick registered")
    except Exception as exc:
        logger.warning("[lana.reminders.cron] scheduler registration failed: %s", exc)
