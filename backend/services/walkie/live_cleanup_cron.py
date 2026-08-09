"""Phase 52.1a · Feb-2026 — Live-session stale-connection cleanup cron.

Room state for the walkie signaling WebSocket is kept in-process on
the FastAPI worker. A server restart wipes the ``ROOMS`` dict but
leaves the corresponding ``walkie_live_sessions`` Mongo rows with
``ended_at = None`` forever — those rows are the source of truth for
"who's live right now" so the client roster stays sane through
reconnects, but they need reaping when the process dies.

This cron runs every 5 minutes and closes any row whose channel no
longer has a live in-process room. Because ``ROOMS`` is per-process
we do NOT cross-check against other workers (there's only one
FastAPI process per pod in this deployment). If we ever scale to
multiple workers this cron becomes race-prone and needs a heartbeat
column — deferred to that phase.

Env-gated by ``WALKIE_LIVE_CLEANUP_ENABLED`` (default: ``1``).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("walkie.live.cleanup.cron")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_live_cleanup_once(db, live_channel_ids: set[str] | None = None) -> dict:
    """Close every ``walkie_live_sessions`` row (``ended_at=None``)
    whose ``channel_id`` is not in the caller-supplied set of live
    in-process rooms. Returns a small summary for logs / tests.

    Accepting ``live_channel_ids`` as a parameter lets the test suite
    simulate an in-process room state without importing the router
    (which drags a WebSocket dependency graph into every test)."""
    if live_channel_ids is None:
        # Lazy-import to avoid circulars during test collection.
        try:
            from routers.walkie_signaling import ROOMS  # type: ignore
            live_channel_ids = set(ROOMS.keys())
        except Exception:
            live_channel_ids = set()

    q: dict = {"ended_at": None}
    if live_channel_ids:
        q["channel_id"] = {"$nin": list(live_channel_ids)}
    now = _now_iso()
    result = await db.walkie_live_sessions.update_many(q, {"$set": {"ended_at": now}})
    closed = int(result.modified_count or 0)
    if closed:
        logger.info(
            "[walkie.live.cleanup.cron] closed %d stale session(s) at %s",
            closed, now,
        )
    return {"closed": closed, "at": now, "live_channel_ids": len(live_channel_ids or [])}


async def _tick():
    if os.environ.get("WALKIE_LIVE_CLEANUP_ENABLED", "1") != "1":
        return {"skipped": True, "reason": "disabled"}
    from server import db
    return await run_live_cleanup_once(db)


def register_live_cleanup_cron(scheduler) -> None:
    """Register the 5-minute tick on the app's ``AsyncIOScheduler``.

    Mirrors ``services/walkie/cleanup_cron.py`` (which runs at the
    minute cadence for a different sweep) — feeding the coroutine
    function directly is safe because the singleton is
    ``AsyncIOScheduler``.
    """
    if scheduler is None:
        return
    from apscheduler.triggers.interval import IntervalTrigger
    try:
        scheduler.add_job(
            _tick,
            IntervalTrigger(minutes=5),
            id="walkie.live.cleanup.tick",
            replace_existing=True,
        )
        logger.info("[walkie.live.cleanup.cron] 5-min cleanup tick registered")
    except Exception as exc:
        logger.warning(
            "[walkie.live.cleanup.cron] scheduler registration failed: %s", exc,
        )
