"""Phase 54e · Feb-2026 — Wholesale supplier sync cron.

Two APScheduler triggers wired from ``server.py`` on startup:

* Hourly (top of every hour, UTC): syncs supplier rows whose
  ``sync_frequency == "hourly"``.
* Daily at **03:00 UTC**: syncs supplier rows whose
  ``sync_frequency == "daily"``; on Sunday also syncs
  ``sync_frequency == "weekly"``.

Gated by ``SUPPLIER_SYNC_LIVE=1`` — default OFF everywhere. When the
flag is unset the cron logs a dry-run summary and never touches
Playwright / wholesalers. Mirrors the Phase 49 ``LANA_SMS_LIVE`` gate.

Guardrails:

* Skips supplier rows without saved credentials (silently).
* Skips supplier rows whose last successful sync was **< 6 h** ago
  (avoids double-syncing manual runs).
* Skips supplier rows whose ``sync_frequency == "manual"``.
* Skips supplier slugs that don't have a wired connector runner yet.
* Calls the sync service functions **directly** — never self-HTTPs.

All logs use the prefix ``supplier.cron.*`` so operators can grep.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from config import db, logger
from services.suppliers.crypto import decrypt
from services.suppliers.sync import start_sync_job


ENV_LIVE = "SUPPLIER_SYNC_LIVE"
RECENT_SYNC_SKIP_HOURS = 6


def _is_live() -> bool:
    return os.environ.get(ENV_LIVE, "") == "1"


async def _runner_for(slug: str):
    """Return the sync-runner coroutine for a slug, or ``None``."""
    if slug == "poolcorp":
        from services.suppliers.sync import run_poolcorp_sync
        return run_poolcorp_sync
    if slug == "siteone":
        from services.suppliers.sync import run_siteone_sync
        return run_siteone_sync
    if slug == "ewing":
        from services.suppliers.sync import run_ewing_sync
        return run_ewing_sync
    if slug == "heritage":
        from services.suppliers.sync import run_heritage_sync
        return run_heritage_sync
    if slug == "epoolsupply":
        from services.suppliers.sync import run_epoolsupply_sync
        return run_epoolsupply_sync
    return None


async def _should_sync_now(cadence: str, now: Optional[datetime] = None) -> bool:
    """Return True iff ``cadence`` matches the current tick.

    The cron enum values map to:

    * ``hourly`` — always match (invoked from the hourly tick).
    * ``daily``  — always match (invoked from the daily tick).
    * ``weekly`` — match iff ``now.weekday() == 6`` (Sunday).
    * ``manual`` — never match.
    """
    if cadence == "hourly":
        return True
    if cadence == "daily":
        return True
    if cadence == "weekly":
        n = now or datetime.now(timezone.utc)
        return n.weekday() == 6  # Sunday
    return False  # manual / unknown


async def _skip_recent(supplier: Dict[str, Any], now: datetime) -> bool:
    """Skip if the last SUCCESSFUL sync completed < RECENT_SYNC_SKIP_HOURS
    ago. Prevents manual+cron double-syncs."""
    last = await db.supplier_sync_jobs.find_one(
        {"tenant_id": supplier["tenant_id"], "supplier_id": supplier["id"],
          "status": "success"},
        {"_id": 0, "finished_at": 1},
        sort=[("finished_at", -1)],
    )
    if not last:
        return False
    finished_at = last.get("finished_at")
    if not finished_at:
        return False
    if isinstance(finished_at, str):
        try:
            finished_at = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
        except Exception:
            return False
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=timezone.utc)
    delta = now - finished_at
    return delta < timedelta(hours=RECENT_SYNC_SKIP_HOURS)


async def _sync_one(supplier: Dict[str, Any], live: bool, now: datetime) -> str:
    """Kick off one supplier sync. Returns a short status token:

    * ``no_credentials`` — no saved creds row
    * ``recent`` — last-success within 6 h, skipped
    * ``no_runner`` — slug isn't wired to a sync runner
    * ``dry_run`` — ``SUPPLIER_SYNC_LIVE`` unset, logged only
    * ``running`` — background sync launched
    """
    tenant_id = supplier["tenant_id"]
    slug = supplier["slug"]
    cred = await db.supplier_credentials.find_one(
        {"tenant_id": tenant_id, "supplier_id": supplier["id"]}, {"_id": 0})
    if not cred:
        return "no_credentials"
    if await _skip_recent(supplier, now):
        return "recent"
    runner = await _runner_for(slug)
    if runner is None:
        return "no_runner"
    if not live:
        logger.info(
            f"supplier.cron.dry_run tenant={tenant_id[:8]} slug={slug} "
            f"cadence={supplier.get('sync_frequency', 'daily')}")
        return "dry_run"

    credentials = {
        "username": decrypt(cred.get("encrypted_username")),
        "password": decrypt(cred.get("encrypted_password")),
        "api_key":  decrypt(cred.get("encrypted_api_key")),
    }
    job = await start_sync_job(tenant_id, supplier)
    # Fire and forget — the runner writes to supplier_sync_jobs.
    import asyncio as _asyncio
    _asyncio.create_task(
        runner(tenant_id, supplier, credentials, job["id"]))
    logger.info(
        f"supplier.cron.launch tenant={tenant_id[:8]} slug={slug} "
        f"job={job['id']}")
    return "running"


async def _run_tick(cadence_filter: str) -> Dict[str, Any]:
    """Common code for the hourly + daily ticks. ``cadence_filter`` is
    one of ``"hourly"`` / ``"daily"``. Weekly rows also run inside the
    daily tick on Sundays (see ``_should_sync_now``).

    Returns a summary dict for the tests. In production the counts
    are logged; nobody reads the return value.
    """
    live = _is_live()
    now = datetime.now(timezone.utc)
    counts = {"no_credentials": 0, "recent": 0, "no_runner": 0,
              "dry_run": 0, "running": 0, "skipped_cadence": 0}

    async for supplier in db.suppliers.find({"active": True}):
        cadence = supplier.get("sync_frequency", "daily")
        # For the daily tick, accept both "daily" and "weekly" (with
        # weekly filtered further by ``_should_sync_now``).
        if cadence_filter == "hourly" and cadence != "hourly":
            counts["skipped_cadence"] += 1
            continue
        if cadence_filter == "daily" and cadence not in ("daily", "weekly"):
            counts["skipped_cadence"] += 1
            continue
        if not await _should_sync_now(cadence, now):
            counts["skipped_cadence"] += 1
            continue

        status = await _sync_one(supplier, live, now)
        counts[status] = counts.get(status, 0) + 1

    logger.info(
        f"supplier.cron.summary cadence={cadence_filter} live={live} "
        f"{counts}")
    return {"cadence": cadence_filter, "live": live, **counts,
            "at": now.isoformat()}


async def run_hourly_tick():
    """APScheduler entry-point — runs on the hourly trigger."""
    return await _run_tick("hourly")


async def run_daily_tick():
    """APScheduler entry-point — runs daily at 03:00 UTC."""
    return await _run_tick("daily")


def register_supplier_cron_jobs(scheduler) -> None:
    """Wire the two triggers onto the given APScheduler singleton.

    Called from ``server.py`` at startup. Idempotent — the scheduler
    library dedupes by job id.
    """
    try:
        scheduler.add_job(
            run_hourly_tick, "cron", minute=0,
            id="supplier_sync_hourly", replace_existing=True,
        )
        scheduler.add_job(
            run_daily_tick, "cron", hour=3, minute=0,
            id="supplier_sync_daily", replace_existing=True,
        )
        logger.info(
            f"supplier.cron.registered hourly=@0min daily=@03:00UTC "
            f"live={_is_live()}")
    except Exception as e:
        logger.warning(f"supplier.cron.register_failed err={e}")
