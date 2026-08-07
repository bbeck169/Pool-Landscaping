"""Phase 51d · Feb-2026 — Walkie-Talkie 24h cleanup cron.

Defense-in-depth for the Phase 51a Mongo TTL index on
``walkie_messages.expires_at``. The TTL index deletes messages
natively at the 24h mark but Mongo does NOT cascade to the
companion collections (receipts) or to the file-storage blobs. This
cron sweeps orphans once a minute:

  1. ``walkie_receipts`` where ``message_id`` no longer resolves to
     a message row (message was TTL-deleted).
  2. ``files`` rows tagged ``purpose == "walkie_audio"`` whose
     ``id`` is no longer referenced by any live walkie_messages
     row's ``audio_file_id`` field.

Idempotent, safe to run every minute — the sweeps are pure ``$nin``
queries and delete-many operations. Logs a summary line only when
something actually gets cleaned so quiet minutes stay quiet in
the log stream.

Attaches to the EXISTING ``AsyncIOScheduler`` singleton owned by
``server.py``. Mirrors ``services/lana/reminder_cron.py`` (Phase 49)
including feeding the coroutine function directly to APScheduler.

Env-gated by ``WALKIE_CLEANUP_ENABLED`` (default: on). QA can set
``WALKIE_CLEANUP_ENABLED=0`` to disable the cron without touching
code.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("walkie.cleanup.cron")


async def _sweep_orphan_receipts(db) -> int:
    """Delete walkie_receipts rows whose message no longer exists."""
    # Pull current live message ids, then delete receipts whose
    # message_id is NOT in that set. Uses a bounded pull (500k) to
    # stay memory-safe on huge tenants; well beyond any realistic
    # 24h walkie volume.
    live_ids = await db.walkie_messages.distinct("id")
    result = await db.walkie_receipts.delete_many(
        {"message_id": {"$nin": live_ids}}
    )
    return int(result.deleted_count or 0)


async def _sweep_orphan_walkie_files(db) -> int:
    """Delete file rows tagged ``walkie_audio`` whose id is no longer
    referenced by any walkie_messages row.

    We only ever touch rows tagged ``purpose == "walkie_audio"`` —
    other file purposes (invoices, before-afters, etc.) are never
    inspected, so this can never nuke unrelated data.
    """
    referenced = await db.walkie_messages.distinct("audio_file_id")
    result = await db.files.delete_many(
        {"purpose": "walkie_audio", "id": {"$nin": referenced}}
    )
    return int(result.deleted_count or 0)


async def run_walkie_cleanup_once(db) -> dict:
    """One-shot cleanup pass — returns a summary dict, useful for
    tests. Never raises: exceptions are logged + swallowed so the
    scheduler's next tick still fires."""
    try:
        receipts = await _sweep_orphan_receipts(db)
        files = await _sweep_orphan_walkie_files(db)
    except Exception as exc:  # pragma: no cover — best-effort loop
        logger.warning("[walkie.cleanup.cron] sweep failed: %s", exc)
        return {"error": str(exc)[:120], "receipts": 0, "files": 0}
    if receipts or files:
        logger.info("walkie cleanup: %d receipts, %d files", receipts, files)
    return {"receipts": receipts, "files": files}


async def _tick():
    if os.environ.get("WALKIE_CLEANUP_ENABLED", "1") != "1":
        return {"skipped": True, "reason": "disabled"}
    from server import db
    return await run_walkie_cleanup_once(db)


def register_walkie_cleanup_cron(scheduler) -> None:
    """Register the 1-minute tick on the app's ``AsyncIOScheduler``.

    Feeding a coroutine function directly is safe because the
    singleton is ``AsyncIOScheduler`` — same pattern as
    ``services/lana/reminder_cron.py``.
    """
    if scheduler is None:
        return
    from apscheduler.triggers.interval import IntervalTrigger
    try:
        scheduler.add_job(
            _tick,
            IntervalTrigger(minutes=1),
            id="walkie.cleanup.tick",
            replace_existing=True,
        )
        logger.info("[walkie.cleanup.cron] minute-cadence cleanup tick registered")
    except Exception as exc:
        logger.warning("[walkie.cleanup.cron] scheduler registration failed: %s", exc)
