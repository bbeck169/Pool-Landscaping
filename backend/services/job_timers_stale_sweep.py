"""Feb-2026 · Job Timers · stale-timer sweep (Ask 3).

Mobile-location-services BE Ask 3 — a periodic cron that closes
``job_timers`` rows that were opened on arrival but never got
closed by the shipped service-report-submit or job-completed
auto-close paths (asks 1 + 2, both already shipped in Job Timers
Phase 1 / Phase 6).

Trigger: APScheduler hourly interval tick, registered from
``server.py`` lifespan alongside the other feature crons
(``inventory_alerts``, ``renewal_scan``, etc.).

Threshold: 16h since ``started_at``.  Rationale from pre-audit —
the longest shift shape observed in ``time_entries`` fixtures is
~12h, so 16h gives emergency after-hours work (snow removal,
after-hours pool-pump emergencies) a buffer before auto-closing
while still catching the forgot-to-stop case before next business
day.  Override via env ``JOB_TIMERS_STALE_THRESHOLD_HOURS``.

Close path: calls the internal
``routers.job_timers.close_open_timers_for_job`` helper with
``reason="stale_sweep"`` (bypasses the public ``CloseTimerIn
.source`` regex per the audit).  The helper writes the base
``job_timer_audit`` crumb ``event="auto_close"`` with
``payload.reason="stale_sweep"``.  This module writes an
ADDITIONAL supplementary crumb per closed timer with
``event="stale_sweep"`` carrying ``payload.threshold_hours`` +
``payload.sweep_run_id`` for cross-row run correlation.

Isolation: iterates tenants from ``db.tenants`` (same pattern
as ``inventory_alerts.run_daily_low_stock_scan``) and calls the
helper per (tenant, job) pair so a tenant-A sweep never touches
a tenant-B row.

Idempotency: re-running the sweep is a no-op because the
tenant-scoped ``close_open_timers_for_job`` query filters on
``ended_at: None`` — rows closed in the previous run have a
non-null ``ended_at`` and are naturally excluded.
"""
from __future__ import annotations

import os
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from config import db, logger


_DEFAULT_THRESHOLD_HOURS = 16


def _threshold_hours() -> int:
    """Env-overridable threshold.  Falls back to 16 on parse
    failure or any value <= 0."""
    raw = os.environ.get("JOB_TIMERS_STALE_THRESHOLD_HOURS")
    if not raw:
        return _DEFAULT_THRESHOLD_HOURS
    try:
        v = int(raw)
        return v if v > 0 else _DEFAULT_THRESHOLD_HOURS
    except (TypeError, ValueError):
        return _DEFAULT_THRESHOLD_HOURS


def _parse_iso(value: Any) -> datetime | None:
    """ISO-8601 → aware datetime; naive strings are treated as
    UTC to match the shipped ``job_timers._parse_iso`` posture."""
    if not value:
        return None
    if isinstance(value, datetime):
        return (value if value.tzinfo
                  else value.replace(tzinfo=timezone.utc))
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:                                            # noqa: BLE001
        return None


async def sweep_stale_job_timers() -> Dict[str, Any]:
    """APScheduler entry point — hourly interval tick.

    Returns a compact run summary ``{tenants, scanned, closed,
    run_id, threshold_hours}`` so log scrapers can diff run-over-
    run drift.  Never raises; each tenant iteration is wrapped
    in its own try/except so one bad row doesn't poison the
    rest of the sweep.
    """
    run_id = str(uuid.uuid4())
    threshold_hours = _threshold_hours()
    now_dt = datetime.now(timezone.utc)
    cutoff_dt = now_dt - timedelta(hours=threshold_hours)
    # Lazy import — the helper is in a router module and routers
    # import this file via APScheduler registration during
    # ``server.py`` lifespan boot; avoiding a top-level circular.
    from routers.job_timers import close_open_timers_for_job

    tenants = await db.tenants.find(
        {"active": {"$ne": False}}, {"_id": 0, "id": 1},
    ).to_list(5000)

    scanned = 0
    closed_total = 0
    for t in tenants:
        tid = t.get("id")
        if not tid:
            continue
        try:
            # Candidate rows: open timers on this tenant with a
            # parseable ``started_at`` older than cutoff.
            cursor = db.job_timers.find(
                {"tenant_id": tid, "ended_at": None},
                {"_id": 0, "id": 1, "job_id": 1,
                 "started_at": 1},
            )
            rows: List[Dict[str, Any]] = [r async for r in cursor]
            scanned += len(rows)
            # Group timer rows by job_id so the helper can close
            # the whole job in one call (and so we only make one
            # helper call per job even if a job has multiple open
            # tech/crew rows).
            by_job: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for r in rows:
                started = _parse_iso(r.get("started_at"))
                if not started or started > cutoff_dt:
                    continue
                jid = r.get("job_id")
                if not jid:
                    continue
                by_job[jid].append(r)
            for jid, stale_rows in by_job.items():
                closed = await close_open_timers_for_job(
                    job_id=jid, tenant_id=tid,
                    actor_user_id=None,
                    reason="stale_sweep",
                )
                closed_total += int(closed or 0)
                # Supplementary per-timer crumb carrying the
                # run-level correlation metadata.  The base
                # ``event="auto_close"`` crumb was already written
                # by the helper for each closed row; this crumb
                # layers ``threshold_hours`` + ``sweep_run_id`` so
                # a single run's closures can be queried as a set.
                for sr in stale_rows:
                    try:
                        await db.job_timer_audit.insert_one({
                            "id": str(uuid.uuid4()),
                            "tenant_id": tid,
                            "timer_id": sr["id"],
                            "event": "stale_sweep",
                            "actor_user_id": None,
                            "at": now_dt.isoformat(),
                            "payload": {
                                "reason": "stale_sweep",
                                "threshold_hours": threshold_hours,
                                "sweep_run_id": run_id,
                                "job_id": jid,
                            },
                        })
                    except Exception as exc:                     # noqa: BLE001
                        logger.warning(
                            "[job-timers-stale-sweep] audit crumb "
                            "failed tenant=%s timer=%s: %s",
                            tid, sr.get("id"), exc,
                        )
        except Exception as exc:                                 # noqa: BLE001
            logger.warning(
                "[job-timers-stale-sweep] tenant=%s failed: %s",
                tid, exc,
            )

    summary = {
        "run_id":           run_id,
        "threshold_hours":  threshold_hours,
        "tenants":          len(tenants),
        "scanned":          scanned,
        "closed":           closed_total,
    }
    logger.info(f"[job-timers-stale-sweep] run complete: {summary}")
    return summary
