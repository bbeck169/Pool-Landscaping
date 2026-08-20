"""Queue Item 5c · Feb-2026 — Homeworks import dispatcher.

APScheduler job that replaces the operator-driven nohup workflow.
Polls ``db.homeworks_import_runs`` every 30 seconds for docs with
``status="queued"``, picks one per tenant, transitions it to
``status="running"`` atomically, and drives the correct importer's
``run_full`` inline.

Design constraints (from user brief):

* **Atomic transition** — the queued → running flip uses
  ``update_one({run_id, status:"queued"}, {$set:{status:"running"}})``
  so a second dispatcher tick can never double-execute a run.
* **Per-tenant concurrency guard** — dispatcher skips any queued
  run whose tenant already has another run in ``status="running"``.
  Cheap check, keeps a slow tenant from blocking the whole cluster.
* **Resume on restart** — if the process crashes mid-run, the doc's
  ``status`` stays ``running`` and the ``resume_cursor`` is at the
  last checkpoint. On next dispatcher tick we would NOT re-pick it
  (it's ``running``, not ``queued``). An operator can flip it to
  ``queued`` to resume, or the importer's own poison-pill logic
  will halt with ``paused_needs_attention`` and stay visible in the
  status endpoint. This is the same behaviour the launcher scripts
  had — the dispatcher just automates the initial launch.
* **Terminal statuses** — importers write ``completed``,
  ``cancelled``, ``failed``, or ``paused_needs_attention`` on their
  own via ``_checkpoint``. The dispatcher wraps the call in a
  try/except that pushes an error_log entry + flips to
  ``failed`` on unhandled crash.
* **Manual launcher scripts kept** — ``scripts/homeworks_run_*.py``
  stay in-tree for debugging; the dispatcher is the standard path
  triggered by the FE's ``POST /run``.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

logger = logging.getLogger("homeworks_mcp.dispatcher")

# Poll cadence — every 30s. Matches user brief.
DISPATCHER_INTERVAL_S = 30

# Feb-2026 · Watchdog — a job that sat in {queued, running} for more
# than ``WATCHDOG_STALE_MINUTES`` with zero forward progress
# (``counters.customers_scanned == 0``) is auto-transitioned to
# ``failed_stale`` on the next dispatcher tick.  Prevents a silent
# hang from a crashed pod / lost claim from clogging the queue
# indefinitely (root cause of the Feb-2026 P0 "QUEUED · Running… ·
# Scanned 0" bug reported by ops).
WATCHDOG_STALE_MINUTES = 15

# Importer routing table — kind → module. Kept flat + explicit so
# adding a new importer is a one-line append.
_IMPORTER_KIND_MAP: Dict[str, str] = {
    "inactive_customers": "services.homeworks_mcp.inactive_customers_importer",
    "active_customers":   "services.homeworks_mcp.active_customers_importer",
    "delta_sync":         "services.homeworks_mcp.delta_sync_importer",
    "pricebook":          "services.homeworks_mcp.pricebook_importer",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _try_start_run(db, doc: Dict[str, Any]) -> bool:
    """Atomic queued → running flip. Returns True if this dispatcher
    tick won the race and should execute the run; False otherwise.
    """
    r = await db.homeworks_import_runs.update_one(
        {"run_id": doc["run_id"], "status": "queued"},
        {"$set": {"status": "running",
                   "started_at": _now_iso(),
                   "updated_at": _now_iso(),
                   "dispatcher_pid": _pid_tag(),
                   "dispatcher_claimed_at": _now_iso()}},
    )
    if r.modified_count == 1:
        # Feb-2026 · Structured transition log (queued → running).
        # Same shape as the terminal-status logs the importers emit
        # so a single ``grep '[dispatcher]'`` reconstructs a run's
        # lifecycle from the supervisor log.
        logger.info(
            "[dispatcher] transition queued->running kind=%s tenant=%s run_id=%s",
            doc.get("kind"), doc.get("tenant_id"), doc.get("run_id"),
        )
        return True
    return False


async def _watchdog_sweep(db) -> Dict[str, int]:
    """Auto-fail every {queued, running} run whose ``updated_at`` is
    older than :data:`WATCHDOG_STALE_MINUTES` AND whose customer
    scan count has not advanced (``customers_scanned == 0``).

    Rationale:
      * A doc stuck in ``queued`` past the threshold means the
        dispatcher never claimed it (pod died between insert + tick,
        or scheduler was never wired) — safe to auto-fail and let
        the operator resubmit.
      * A doc stuck in ``running`` past the threshold with zero
        rows scanned means ``run_full`` crashed before its first
        checkpoint — the dispatcher's own try/except would have
        marked it ``failed`` if the crash bubbled out of
        ``_run_one``; a doc that stays ``running`` means the
        coroutine hung silently (network deadlock, event-loop
        rebind, etc.).  Either way, unblock the queue.

    Idempotent — a follow-up tick with no eligible docs is a no-op.
    Returns ``{stale_transitioned: N}``.
    """
    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(minutes=WATCHDOG_STALE_MINUTES)
    ).isoformat()
    q = {
        "status": {"$in": ["queued", "running"]},
        "updated_at": {"$lt": cutoff},
        "$or": [
            {"counters.customers_scanned": {"$in": [0, None]}},
            {"counters.customers_scanned": {"$exists": False}},
        ],
    }
    stale = 0
    async for doc in db.homeworks_import_runs.find(
        q, {"_id": 0, "run_id": 1, "tenant_id": 1, "kind": 1,
             "status": 1, "updated_at": 1},
    ):
        r = await db.homeworks_import_runs.update_one(
            {"run_id": doc["run_id"],
             "status": {"$in": ["queued", "running"]}},
            {"$set": {"status": "failed_stale",
                       "finished_at": _now_iso(),
                       "updated_at": _now_iso()},
             "$push": {"error_log": {
                 "stage": "watchdog",
                 "reason": (
                     f"stale_{doc.get('status')}_"
                     f"{WATCHDOG_STALE_MINUTES}min_no_progress"),
                 "prev_status": doc.get("status"),
                 "prev_updated_at": doc.get("updated_at"),
                 "at": _now_iso(),
             }}},
        )
        if r.modified_count:
            stale += 1
            logger.warning(
                "[dispatcher] transition %s->failed_stale kind=%s "
                "tenant=%s run_id=%s prev_updated_at=%s",
                doc.get("status"), doc.get("kind"),
                doc.get("tenant_id"), doc.get("run_id"),
                doc.get("updated_at"),
            )
    return {"stale_transitioned": stale}


def _pid_tag() -> str:
    """Human-readable claim tag. Not used for correctness — the
    atomic flip is the correctness boundary — but useful for
    debugging which pod grabbed a run in a multi-replica deploy.
    """
    import os
    import socket
    return f"{socket.gethostname()}:{os.getpid()}"


async def _run_one(kind: str, tenant_id: str, run_id: str,
                     user_id: str | None) -> None:
    """Dispatch a single run's execution. Isolated so tests can hit
    it directly without going through the polling loop."""
    module_path = _IMPORTER_KIND_MAP.get(kind)
    if not module_path:
        # Unknown kind — mark failed, log loudly. The doc was inserted
        # by a router we control, so this branch really shouldn't fire.
        from config import db
        await db.homeworks_import_runs.update_one(
            {"run_id": run_id},
            {"$set": {"status": "failed",
                       "finished_at": _now_iso(),
                       "updated_at": _now_iso()},
             "$push": {"error_log": {
                 "stage": "dispatcher",
                 "reason": f"unknown_kind:{kind}",
                 "at": _now_iso(),
             }}},
        )
        logger.error("[dispatcher] unknown kind=%s run_id=%s", kind, run_id)
        return

    import importlib
    imp = importlib.import_module(module_path)
    logger.info("[dispatcher] executing kind=%s tenant=%s run_id=%s",
                 kind, tenant_id, run_id)
    try:
        await imp.run_full(
            tenant_id=tenant_id, user_id=user_id, run_id=run_id,
        )
        # Feb-2026 · Structured terminal-transition log.  Read back the
        # doc so we surface whichever status the importer's own
        # ``_checkpoint`` chose: ``completed`` / ``succeeded`` /
        # ``cancelled`` / ``paused_needs_attention``.
        from config import db
        end_doc = await db.homeworks_import_runs.find_one(
            {"run_id": run_id},
            {"_id": 0, "status": 1, "counters": 1},
        ) or {}
        logger.info(
            "[dispatcher] transition running->%s kind=%s tenant=%s "
            "run_id=%s counters=%s",
            end_doc.get("status"), kind, tenant_id, run_id,
            end_doc.get("counters"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[dispatcher] run_full crashed kind=%s run_id=%s",
                          kind, run_id)
        from config import db
        await db.homeworks_import_runs.update_one(
            {"run_id": run_id},
            {"$set": {"status": "failed",
                       "finished_at": _now_iso(),
                       "updated_at": _now_iso()},
             "$push": {"error_log": {
                 "stage": "dispatcher_crash",
                 "error": str(exc)[:500],
                 "at": _now_iso(),
             }}},
        )
        logger.warning(
            "[dispatcher] transition running->failed kind=%s tenant=%s "
            "run_id=%s error=%s",
            kind, tenant_id, run_id, str(exc)[:200],
        )


async def _tenant_has_running(db, tenant_id: str,
                                 exclude_run_id: str) -> bool:
    """Concurrency guard — one live run per tenant."""
    n = await db.homeworks_import_runs.count_documents(
        {"tenant_id": tenant_id,
         "status": "running",
         "run_id": {"$ne": exclude_run_id}},
    )
    return n > 0


async def dispatcher_tick() -> Dict[str, Any]:
    """One pass over queued runs. Returns a summary dict so the
    scheduler log stays readable + tests can assert behaviour.
    """
    from config import db  # local import — matches other cron jobs
    # Feb-2026 · Watchdog sweep BEFORE the queued scan so a doc that
    # just aged past the stale threshold gets marked ``failed_stale``
    # instead of being re-claimed for another useless run.
    watchdog = await _watchdog_sweep(db)
    started = 0
    skipped_concurrency = 0
    unknown_kind = 0
    # Sort by started_at ASC so the oldest queued run wins.
    cursor = db.homeworks_import_runs.find(
        {"status": "queued"},
        {"_id": 0, "run_id": 1, "tenant_id": 1, "kind": 1,
         "started_by_user_id": 1},
    ).sort("started_at", 1)
    async for doc in cursor:
        run_id = doc.get("run_id")
        tenant_id = doc.get("tenant_id")
        kind = doc.get("kind")
        if not (run_id and tenant_id and kind):
            continue
        if kind not in _IMPORTER_KIND_MAP:
            unknown_kind += 1
            # Fall through anyway so _run_one marks it failed and
            # the dispatcher doesn't keep re-picking a poisoned doc.
        if await _tenant_has_running(db, tenant_id, exclude_run_id=run_id):
            skipped_concurrency += 1
            continue
        if not await _try_start_run(db, doc):
            # Someone else claimed it between the find + update.
            continue
        started += 1
        # Fire-and-forget the run: we don't want the tick coroutine
        # to hold the scheduler slot while a multi-hour import runs.
        import asyncio
        asyncio.create_task(
            _run_one(kind, tenant_id, run_id, doc.get("started_by_user_id")),
        )
    return {"started": started,
              "skipped_concurrency": skipped_concurrency,
              "unknown_kind": unknown_kind,
              "stale_transitioned": watchdog.get("stale_transitioned", 0),
              "at": _now_iso()}


def register_dispatcher(scheduler) -> None:
    """Wire the dispatcher tick into the app-wide APScheduler.
    Mirrors ``register_lumino_reconciler_job`` etc. Called from
    ``server.py`` startup."""
    scheduler.add_job(
        dispatcher_tick,
        "interval", seconds=DISPATCHER_INTERVAL_S,
        id="homeworks_import_dispatcher",
        replace_existing=True,
        max_instances=1,      # keep ticks strictly serialised
        coalesce=True,
    )
    logger.info(
        "[dispatcher] homeworks_import_dispatcher registered "
        "(interval=%ds)", DISPATCHER_INTERVAL_S,
    )
