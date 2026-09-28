"""MTH-C · Feb-2026 — APScheduler binding for deferred-comms flush
+ escalation SLA breach jobs.

Mirrors the HD-B binding pattern: pytest-mode + explicit env-flag
bypass, module-level singleton, guarded start / graceful stop.
Every 5 min the ``flush_due`` job runs; every 1 min the escalation
SLA-breach scan runs.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("scheduler.mth_c")

_JOB_DEFER_FLUSH = "mth_c_deferred_comms_flush"
_JOB_ESCALATION_BREACH = "mth_c_escalation_sla_breach"

_scheduler: Optional[AsyncIOScheduler] = None


def _flag_true(name: str, default: str = "true") -> bool:
    raw = os.environ.get(name, default)
    if raw is None or raw == "":
        raw = default
    return (raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _in_test_mode() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


async def _tick_deferred_flush() -> None:
    """Coroutine the scheduler dispatches every 5 min."""
    try:
        from services.ai_comms.deferred_queue import flush_due
        stats = await flush_due()
        logger.info(
            "[scheduler.mth_c] deferred_flush scanned=%s delivered=%s "
            "master_off=%s employee_off=%s errors=%s",
            stats.get("scanned"), stats.get("delivered"),
            stats.get("dropped_master_switch"),
            stats.get("dropped_employee_disabled"),
            stats.get("dispatch_errors"),
        )
    except Exception:                                              # noqa: BLE001
        logger.exception("[scheduler.mth_c] deferred_flush tick failed")


async def _tick_escalation_breach() -> None:
    """Coroutine the scheduler dispatches every 1 min."""
    try:
        from services.ai_hub.escalation_detector import (
            scan_sla_breaches,
        )
        stats = await scan_sla_breaches()
        if stats.get("breached", 0) > 0:
            logger.info(
                "[scheduler.mth_c] escalation_sla_breach scanned=%s "
                "notified=%s",
                stats.get("scanned"), stats.get("breached"),
            )
    except Exception:                                              # noqa: BLE001
        logger.exception("[scheduler.mth_c] escalation_breach tick failed")


def start() -> Optional[AsyncIOScheduler]:
    """Bind both jobs to a fresh ``AsyncIOScheduler``.  Returns the
    scheduler on success or ``None`` when skipped (env flag off or
    pytest mode)."""
    global _scheduler
    if not _flag_true("MTH_C_SCHEDULERS_ENABLED"):
        logger.info(
            "[scheduler.mth_c] MTH_C_SCHEDULERS_ENABLED=false — skipping bind",
        )
        return None
    if _in_test_mode():
        logger.info(
            "[scheduler.mth_c] PYTEST_CURRENT_TEST — skipping bind",
        )
        return None
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    tz = os.environ.get("SCHEDULER_TZ") or "America/Los_Angeles"
    sched = AsyncIOScheduler(timezone=tz)

    flush_minutes = int(os.environ.get("MTH_C_DEFERRED_FLUSH_MINUTES") or "5")
    breach_seconds = int(
        os.environ.get("MTH_C_ESCALATION_BREACH_SECONDS") or "60"
    )
    sched.add_job(
        _tick_deferred_flush,
        IntervalTrigger(minutes=flush_minutes, timezone=tz),
        id=_JOB_DEFER_FLUSH,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60 * 30,
    )
    sched.add_job(
        _tick_escalation_breach,
        IntervalTrigger(seconds=breach_seconds, timezone=tz),
        id=_JOB_ESCALATION_BREACH,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60 * 5,
    )
    sched.start()
    _scheduler = sched
    logger.info(
        "[scheduler.mth_c] bound deferred_flush=%smin escalation_breach=%ss",
        flush_minutes, breach_seconds,
    )
    return sched


async def stop() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:                                              # noqa: BLE001
        logger.exception("[scheduler.mth_c] shutdown failed")
    finally:
        _scheduler = None


def is_bound() -> bool:
    return (
        _scheduler is not None
        and bool(_scheduler.get_job(_JOB_DEFER_FLUSH))
        and bool(_scheduler.get_job(_JOB_ESCALATION_BREACH))
    )


def get_scheduler() -> Optional[AsyncIOScheduler]:
    return _scheduler


def job_ids() -> tuple:
    return (_JOB_DEFER_FLUSH, _JOB_ESCALATION_BREACH)
