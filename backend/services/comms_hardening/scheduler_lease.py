"""Backlog #iv · Feb-2026 — Mongo advisory lease for scheduler ticks.

The audit for Backlog #iv identified two duplicate-fire failure modes:

  1. Multiple processes each register the APScheduler tick (dev
     multi-worker or misconfigured ``ENABLE_SCHEDULER``).
  2. Fatal race where a single tick could re-fire during process
     recovery.

Layer defense: the :func:`try_acquire_lease` helper is called at the
TOP of each scheduled job.  Only the winner runs the job body; the
losers no-op.  Combined with the ``notification_dispatch_log`` guard
(which catches the survivor race), duplicates are impossible even
under adversarial multi-process scheduling.

Lease semantics
---------------
* Key: ``(tenant_id, job_id, tick_iso)`` — the timestamp is the
  cron's expected fire time, floor-rounded to the minute so all
  callers within the same tick converge on the same lease.
* Lifetime: default 55s TTL (typical cron tick is a few seconds; the
  short TTL cleans up quickly even without a Mongo TTL index).
* Acquisition: single ``insert_one`` under a compound unique index
  ``(tenant_id, job_id, tick_iso)``.  DuplicateKeyError → someone
  else got it → we no-op.  The winner returns ``{"acquired": True,
  "lease_id": ...}`` for optional release-on-completion.
* Optional cleanup: ``release_lease`` deletes the row so a
  subsequent same-key tick can re-run.  Not required for
  correctness — the TTL index cleans stale rows automatically.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import db
from utils import new_id, now_iso


logger = logging.getLogger("notifications.scheduler_lease")


DEFAULT_LEASE_TTL_SECONDS = 55


async def ensure_indexes() -> None:
    """Idempotent — safe to call on every boot.  Establishes the
    compound unique index that makes the lease acquisition
    race-safe."""
    try:
        await db.scheduler_leases.create_index(
            [("tenant_id", 1), ("job_id", 1), ("tick_iso", 1)],
            name="scheduler_leases_unique_idx",
            unique=True,
        )
        # TTL index — Mongo purges expired rows automatically. The
        # index is created with expireAfterSeconds=0 and the value
        # of ``expires_at`` must be a BSON date for the reaper to
        # pick it up.
        await db.scheduler_leases.create_index(
            [("expires_at", 1)],
            name="scheduler_leases_ttl_idx",
            expireAfterSeconds=0,
        )
    except Exception as exc:                                    # noqa: BLE001
        logger.warning(
            "[scheduler_lease] index bootstrap skipped: %s", exc,
        )


def _tick_key(when: Optional[datetime] = None) -> str:
    """Truncate to the minute so all callers within one cron fire
    converge on the same lease key."""
    dt = when or datetime.now(timezone.utc)
    return dt.replace(second=0, microsecond=0).isoformat()


async def try_acquire_lease(
    *,
    job_id: str,
    tenant_id: str = "__global__",
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
    when: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Attempt to acquire the lease for one cron tick.

    Returns:
        ``{"acquired": True, "lease_id": <uuid>, "tick_iso": <iso>}``
        when this caller is the winner.

        ``{"acquired": False, "reason": "already_held", "tick_iso":
        <iso>, "holder": <hostname>}`` when another process already
        holds the lease.

        ``{"acquired": True, "lease_id": None, "reason": "fail_open"}``
        on unexpected Mongo error — the caller proceeds (the
        dispatch_log guard is our second line of defence, so
        fail-open here is safe).
    """
    tick_iso = _tick_key(when)
    now = datetime.now(timezone.utc)
    expires_at = datetime.fromtimestamp(now.timestamp() + ttl_seconds, tz=timezone.utc)
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "job_id": job_id,
        "tick_iso": tick_iso,
        "holder": os.environ.get("HOSTNAME") or "unknown",
        "acquired_at": now_iso(),
        # Store as BSON date so the TTL index actually reaps.
        "expires_at": expires_at,
    }
    try:
        await db.scheduler_leases.insert_one(doc)
        logger.info(
            "[scheduler_lease] acquired · job=%s tenant=%s tick=%s holder=%s",
            job_id, tenant_id, tick_iso, doc["holder"],
        )
        return {"acquired": True, "lease_id": doc["id"],
                "tick_iso": tick_iso}
    except Exception as exc:                                    # noqa: BLE001
        if type(exc).__name__ == "DuplicateKeyError":
            other = await db.scheduler_leases.find_one(
                {"tenant_id": tenant_id, "job_id": job_id,
                  "tick_iso": tick_iso},
                {"_id": 0, "holder": 1},
            ) or {}
            logger.info(
                "[scheduler_lease] contested · job=%s tick=%s "
                "other_holder=%s — no-op",
                job_id, tick_iso, other.get("holder"),
            )
            return {"acquired": False, "reason": "already_held",
                    "tick_iso": tick_iso, "holder": other.get("holder")}
        logger.warning(
            "[scheduler_lease] insert crashed · job=%s tick=%s: %s "
            "— fail-open",
            job_id, tick_iso, exc,
        )
        return {"acquired": True, "lease_id": None, "reason": "fail_open",
                "tick_iso": tick_iso}


async def release_lease(lease_id: Optional[str]) -> None:
    """Optional — delete the lease row so a same-key re-fire (e.g.,
    minute rolls over) can re-run.  Safe no-op on ``None`` / already-
    reaped."""
    if not lease_id:
        return
    try:
        await db.scheduler_leases.delete_one({"id": lease_id})
    except Exception as exc:                                    # noqa: BLE001
        logger.warning(
            "[scheduler_lease] release failed · lease_id=%s: %s",
            lease_id, exc,
        )
