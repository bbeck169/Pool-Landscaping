"""HARD-DELETE · HD-B · Feb-2026 — APScheduler binding for the
nightly purge.

Design notes
------------
* Uses ``apscheduler.schedulers.asyncio.AsyncIOScheduler`` — no new
  dependency (pinned at 3.11.3 in ``requirements.txt``).
* The scheduler is a MODULE-LEVEL singleton. ``start()`` binds the
  cron job once; a second call is a no-op (guarded).
* ``stop()`` shuts the scheduler down non-blockingly.
* All parameters honour env vars for ops flexibility:
    * ``HD_NIGHTLY_PURGE_ENABLED`` — ``"false"`` skips the bind
      entirely (dev/local sanity).
    * ``HD_NIGHTLY_PURGE_HOUR`` — 24h hour (default 3).
    * ``HD_NIGHTLY_PURGE_MINUTE`` — minute (default 0).
    * ``HD_RETENTION_DAYS`` — passed through to the worker
      (default 30).
    * ``SCHEDULER_TZ`` — pytz-compatible tz string (default
      ``America/Los_Angeles``).
* Test-mode bypass — when ``PYTEST_CURRENT_TEST`` is set OR the
  enabled flag is ``"false"``, ``start()`` returns ``None`` and
  leaves the module-level singleton at ``None``. Tests observing
  the singleton get a deterministic answer.
* The manual endpoint ``POST /api/hard-delete/admin/run-nightly-purge``
  keeps working — it's independent of the scheduler binding.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("scheduler.hard_delete")

_JOB_ID = "hard_delete_nightly_purge"
_scheduler: Optional[AsyncIOScheduler] = None


def _flag_true(name: str, default: str = "true") -> bool:
    raw = os.environ.get(name, default)
    if raw is None or raw == "":
        raw = default
    return (raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _in_test_mode() -> bool:
    """Detect pytest — presence of the env var is the canonical
    signal pytest sets for every collected test.
    """
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


async def _tick() -> None:
    """Coroutine the scheduler dispatches on cron fire.

    Wraps the existing ``run_nightly_purge`` so all logic stays
    in one module — this file is just the binding.
    """
    # Local import — services.hard_delete.nightly_purge imports
    # from config which imports Motor which imports asyncio in a
    # way that's easier to keep out of module top-level.
    from .nightly_purge import run_nightly_purge
    retention_days = _env_int("HD_RETENTION_DAYS", 30)
    logger.info(
        "[scheduler.hard_delete] tick — running nightly_purge retention=%sd",
        retention_days,
    )
    try:
        result = await run_nightly_purge(days=retention_days)
        logger.info(
            "[scheduler.hard_delete] tick complete purged=%s blocked=%s errors=%s",
            result.get("purged"), len(result.get("blocked") or []),
            len(result.get("errors") or []),
        )
    except Exception:                                              # noqa: BLE001
        logger.exception("[scheduler.hard_delete] tick failed")


def start() -> Optional[AsyncIOScheduler]:
    """Bind the cron job to a fresh ``AsyncIOScheduler``.

    Returns:
        The scheduler instance when bound, ``None`` when skipped
        (either the enabled flag is off or we're inside pytest).

    Guarded — if a scheduler is already running for this process,
    the existing one is returned unchanged.
    """
    global _scheduler

    if not _flag_true("HD_NIGHTLY_PURGE_ENABLED"):
        logger.info(
            "[scheduler.hard_delete] HD_NIGHTLY_PURGE_ENABLED=false — skipping bind",
        )
        return None

    if _in_test_mode():
        logger.info(
            "[scheduler.hard_delete] PYTEST_CURRENT_TEST detected — skipping bind (deterministic tests)",
        )
        return None

    if _scheduler is not None and _scheduler.running:
        return _scheduler

    tz = os.environ.get("SCHEDULER_TZ") or "America/Los_Angeles"
    hour = _env_int("HD_NIGHTLY_PURGE_HOUR", 3)
    minute = _env_int("HD_NIGHTLY_PURGE_MINUTE", 0)
    retention_days = _env_int("HD_RETENTION_DAYS", 30)

    sched = AsyncIOScheduler(timezone=tz)
    sched.add_job(
        _tick,
        CronTrigger(hour=hour, minute=minute, timezone=tz),
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60 * 60,   # 1h — a delayed pod boot at 3am is OK.
    )
    sched.start()
    _scheduler = sched
    logger.info(
        "[scheduler.hard_delete] bound nightly_purge at cron=%02d:%02d %s, retention=%sd",
        hour, minute, tz, retention_days,
    )
    return sched


async def stop() -> None:
    """Graceful shutdown — called from FastAPI lifespan.

    Safe to call when ``start()`` was never invoked (returns
    silently). ``wait=False`` so shutdown doesn't hang on a
    misbehaving job.
    """
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:                                              # noqa: BLE001
        logger.exception("[scheduler.hard_delete] shutdown failed")
    finally:
        _scheduler = None
    logger.info("[scheduler.hard_delete] shut down")


def get_scheduler() -> Optional[AsyncIOScheduler]:
    """Test hook — return the current module singleton (may be
    ``None``)."""
    return _scheduler


def is_bound() -> bool:
    """Test hook — True when the cron job is currently registered."""
    return _scheduler is not None and bool(
        _scheduler.get_job(_JOB_ID),
    )


def cron_config() -> dict:
    """Return the current cron config parameters — exposed for
    diagnostics and tests. Reads the env, doesn't rely on the
    scheduler being running."""
    return {
        "enabled": _flag_true("HD_NIGHTLY_PURGE_ENABLED"),
        "hour": _env_int("HD_NIGHTLY_PURGE_HOUR", 3),
        "minute": _env_int("HD_NIGHTLY_PURGE_MINUTE", 0),
        "timezone": os.environ.get("SCHEDULER_TZ") or "America/Los_Angeles",
        "retention_days": _env_int("HD_RETENTION_DAYS", 30),
        "test_mode_bypass": _in_test_mode(),
        "job_id": _JOB_ID,
    }
