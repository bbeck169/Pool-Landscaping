"""Phase P47 · Feb-2026 — missed-job auto-cleanup poller.

Background asyncio task (P39 lifespan pattern — NOT Celery /
APScheduler / cron).  Marks any ``status ∈ {scheduled, pending,
active, requested}`` job whose effective schedule datetime is
older than ``MISSED_JOB_STALENESS_HOURS`` as ``status="missed"``.

Why:
  * The portal "Next Service" fix in ``customer_portal.py``
    already handles the READ side by pushing a ``>= today`` guard
    into the DB query.  But leaving stale scheduled rows in the
    database means every OTHER surface that filters on
    ``status=scheduled`` (Schedule calendar, admin dashboards,
    dispatch views, reporting) still surfaces jobs that were never
    actually completed.  The cleanup poller sweeps them into a
    terminal ``missed`` bucket so operators can see + reconcile.
  * ``missed`` is a NEW status enum value (added to
    ``STATUS_PILL`` / ``STATUS_COLORS`` / ``K50_JOB_STATUS_BG`` on
    the web).  Mobile picks it up on the next sync — mobile-file
    touches out of P47 scope.

Config (env vars — declared in ``.env.example`` only; the code
falls back to defaults so ``.env`` doesn't need touching):

  * ``MISSED_JOB_CLEANUP_ENABLED``       — default ``true``.  Set
    to any of ``0/false/no/off`` to disable.
  * ``MISSED_JOB_CLEANUP_INTERVAL_SEC``  — default ``3600`` (1h);
    clamped to a floor of ``300`` (5 min) so a runaway loop can't
    hammer Mongo.
  * ``MISSED_JOB_STALENESS_HOURS``       — default ``48``.  A job
    is only marked missed if its effective schedule datetime is
    older than ``now - <this many> hours``.

Contracts:
  * Tenant scoping mandatory — every update filter includes
    ``tenant_id`` even though the poller is system-wide.  Cross-
    tenant leaks are structurally impossible because each update
    targets one specific ``(tenant_id, job_id)`` tuple.
  * ``status == "in_progress"`` is NEVER touched — a tech mid-visit
    needs human attention, not auto-cleanup.
  * Audit trail — every marked row gets a companion doc in
    ``audits`` with ``kind = "job_auto_marked_missed"`` (mirrors
    the P42 hard-delete forensic pattern).
  * Fault-tolerant — any exception per iteration is logged and
    swallowed; the next tick fires normally.  The poller MUST
    NEVER take down the backend.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import db, logger


TAG = "[p47]"

# ─── Config resolvers ────────────────────────────────────────────────
_ENABLED_ENV = "MISSED_JOB_CLEANUP_ENABLED"
_INTERVAL_ENV = "MISSED_JOB_CLEANUP_INTERVAL_SEC"
_STALENESS_ENV = "MISSED_JOB_STALENESS_HOURS"

DEFAULT_INTERVAL_SEC = 3600
MIN_INTERVAL_SEC = 300
DEFAULT_STALENESS_HOURS = 48

# Status enum surfaces treated as "still open, could go missed".
# ``in_progress`` is intentionally excluded — a tech mid-visit is
# operator business, not cleanup fodder.
OPEN_STATUSES = ["scheduled", "pending", "active", "requested"]


def _resolve_enabled() -> bool:
    raw = (os.environ.get(_ENABLED_ENV) or "true").strip().lower()
    return raw not in ("0", "false", "no", "off", "")


def _resolve_interval_sec() -> int:
    raw = os.environ.get(_INTERVAL_ENV)
    try:
        v = int(raw) if raw else DEFAULT_INTERVAL_SEC
    except ValueError:
        v = DEFAULT_INTERVAL_SEC
    return max(v, MIN_INTERVAL_SEC)


def _resolve_staleness_hours() -> int:
    raw = os.environ.get(_STALENESS_ENV)
    try:
        v = int(raw) if raw else DEFAULT_STALENESS_HOURS
    except ValueError:
        v = DEFAULT_STALENESS_HOURS
    return max(v, 1)


# ─── Effective-datetime helper ───────────────────────────────────────
def _effective_scheduled_iso(job: Dict[str, Any]) -> Optional[str]:
    """Return the job's effective schedule ISO string.

    Preference order matches the portal Next-Service query:
      1. ``scheduled_start`` (specific ts)
      2. ``scheduled_date`` + default ``08:00:00`` UTC (matches
         the P38.1 default-time helper convention when a job only
         carries a date).
    Returns ``None`` when neither field is populated.
    """
    ss = job.get("scheduled_start")
    if ss:
        return str(ss)
    sd = job.get("scheduled_date")
    if sd:
        # ``sd`` is either "YYYY-MM-DD" or a legacy full-ISO string.
        sd = str(sd)
        if "T" in sd:
            return sd
        return f"{sd}T08:00:00+00:00"
    return None


# ─── Single iteration — sweep + mark + audit ─────────────────────────
async def run_once(
    *,
    staleness_hours: Optional[int] = None,
    db_client=None,
) -> Dict[str, Any]:
    """Run one cleanup sweep.  Returns a summary dict — used by the
    caller for logging and by tests for assertion.

    ``db_client`` lets tests inject a Motor db handle bound to a
    per-test loop; default reads the module-level ``db``.
    """
    target = db_client if db_client is not None else db
    staleness_h = staleness_hours or _resolve_staleness_hours()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=staleness_h)
    cutoff_iso = cutoff.isoformat()
    # ``scheduled_date`` compares as YYYY-MM-DD strings; the cutoff
    # date is the calendar day of ``cutoff`` in UTC.  Same-day
    # cutoff-hour boundaries are handled by the ISO branch below.
    cutoff_ymd = cutoff.date().isoformat()

    # Candidates — any open-status row where the effective schedule
    # is stale.  We use the same ``$or`` shape as the portal query.
    filt = {
        "status": {"$in": OPEN_STATUSES},
        "$and": [
            {"$or": [
                {"deleted_at": None},
                {"deleted_at": {"$exists": False}},
            ]},
            {"$or": [
                {"scheduled_start": {"$lt": cutoff_iso, "$ne": None}},
                {"$and": [
                    {"$or": [
                        {"scheduled_start": None},
                        {"scheduled_start": ""},
                        {"scheduled_start": {"$exists": False}},
                    ]},
                    {"scheduled_date": {"$lt": cutoff_ymd, "$ne": None}},
                ]},
            ]},
        ],
    }

    marked = 0
    errors = 0
    cursor = target.jobs.find(
        filt,
        {"_id": 0, "id": 1, "tenant_id": 1, "status": 1,
         "scheduled_start": 1, "scheduled_date": 1, "customer_id": 1,
         "title": 1},
    )
    async for job in cursor:
        try:
            jid = job.get("id")
            tid = job.get("tenant_id")
            prior_status = job.get("status")
            eff_iso = _effective_scheduled_iso(job)
            if not jid or not tid:
                continue
            marked_at = datetime.now(timezone.utc).isoformat()
            # Atomic tenant-scoped update — the extra
            # ``status ∈ OPEN_STATUSES`` filter guards a race where
            # a tech flipped the job to ``completed`` between our
            # ``find`` and this ``update_one``.
            res = await target.jobs.update_one(
                {"id": jid, "tenant_id": tid,
                 "status": {"$in": OPEN_STATUSES}},
                {"$set": {
                    "status": "missed",
                    "missed_at": marked_at,
                    "missed_by": "auto-cleanup",
                    "missed_prior_status": prior_status,
                    "missed_effective_scheduled_at": eff_iso,
                }},
            )
            if res.modified_count != 1:
                # Race lost or no-op — don't audit.
                continue
            marked += 1
            # Audit doc for forensic trail — mirrors the P42
            # ``technicians_hard_delete`` pattern.
            try:
                await target.audits.insert_one({
                    "kind": "job_auto_marked_missed",
                    "tenant_id": tid,
                    "job_id": jid,
                    "prior_status": prior_status,
                    "effective_scheduled_at": eff_iso,
                    "marked_at": marked_at,
                    "marked_by": "auto-cleanup",
                    "staleness_hours": staleness_h,
                })
            except Exception as ax:  # noqa: BLE001
                logger.warning(
                    "%s audit insert soft-fail job=%s err=%s",
                    TAG, jid, ax,
                )
            logger.info(
                "%s auto-marked job=%s status=%s→missed effective_at=%s "
                "staleness_h=%s tenant=%s",
                TAG, jid, prior_status, eff_iso, staleness_h, tid,
            )
        except Exception as exc:  # noqa: BLE001
            # Row-level error — log LOUDLY, continue with the next.
            errors += 1
            logger.error(
                "%s auto-cleanup row failure job=%s tenant=%s err=%s",
                TAG, job.get("id"), job.get("tenant_id"), exc,
            )

    return {"marked": marked, "errors": errors,
            "staleness_hours": staleness_h,
            "cutoff_iso": cutoff_iso}


# ─── Poller loop (lifespan-registered background task) ───────────────
async def missed_job_cleanup_loop() -> None:
    """Long-running poller.  Every ``interval_sec`` seconds, run
    one sweep.  Any exception per iteration is logged and swallowed
    so a Mongo blip / index misconfig can never take down the
    backend.  Exits cleanly on ``asyncio.CancelledError`` (shutdown).
    """
    if not _resolve_enabled():
        logger.info(
            "%s missed-job cleanup disabled (%s falsy) — poller not started",
            TAG, _ENABLED_ENV,
        )
        return
    interval = _resolve_interval_sec()
    logger.info(
        "%s missed-job cleanup poller started — interval=%ss staleness=%sh",
        TAG, interval, _resolve_staleness_hours(),
    )
    while True:
        try:
            summary = await run_once()
            if summary.get("marked", 0) > 0 or summary.get("errors", 0) > 0:
                logger.info(
                    "%s cleanup sweep — marked=%s errors=%s cutoff=%s",
                    TAG, summary.get("marked"), summary.get("errors"),
                    summary.get("cutoff_iso"),
                )
        except asyncio.CancelledError:
            logger.info("%s cleanup poller cancelled — shutting down", TAG)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "%s cleanup sweep raised — swallowing so poller "
                "keeps running err=%s",
                TAG, exc,
            )
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("%s cleanup poller cancelled during sleep", TAG)
            raise
