"""Backlog #iv · Feb-2026 — Notification dispatch log migration.

Sentinel: ``notification_dispatch_log_v1``.  Idempotent + sentinel-
guarded.  Creates the collection with the compound unique index that
makes the ``dispatch_guard.guard_and_log`` insert-then-send pattern
race-safe:

    unique on (tenant_id, notification_type, recipient_id, dedupe_key)

Also creates the ``scheduler_leases`` compound unique index +
TTL index (delegated to ``scheduler_lease.ensure_indexes``).

Runs on every boot; the sentinel guards against re-creation cost.
The super-admin admin endpoint ``POST /admin/migrations/
notification-dispatch-log`` allows an ops force-run after a manual
Mongo intervention.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import db


logger = logging.getLogger("notification_dispatch_log_migration")


_SENTINEL_ID = "notification_dispatch_log_v1"


async def _sentinel_row() -> Optional[Dict[str, Any]]:
    return await db.migrations.find_one({"id": _SENTINEL_ID}, {"_id": 0})


async def _write_sentinel(summary: Dict[str, Any]) -> None:
    await db.migrations.update_one(
        {"id": _SENTINEL_ID},
        {"$set": {
            "id": _SENTINEL_ID,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
        }},
        upsert=True,
    )


async def run_notification_dispatch_log_migration(
    *, force: bool = False,
) -> Dict[str, Any]:
    """Create the collection + unique index if missing.  Idempotent.

    Returns a summary dict::

        {"status": "ok" | "skipped",
         "summary": {
             "collections_created": <int>,
             "indexes_created":     <int>,
             "already_present":     <int>,
             "errors":              [...],
         }}
    """
    if not force:
        sentinel = await _sentinel_row()
        if sentinel:
            return {"status": "skipped",
                    "reason": "sentinel_present",
                    "sentinel": sentinel}

    summary: Dict[str, Any] = {
        "collections_created": 0,
        "indexes_created": 0,
        "already_present": 0,
        "errors": [],
    }

    # 1. Collection creation — Mongo lazy-creates on first insert,
    #    so we only ensure the index (which creates the collection
    #    as a side effect).
    try:
        existing_indexes = set()
        async for idx in db.notification_dispatch_log.list_indexes():
            existing_indexes.add(idx.get("name") or "")
        if "notif_dispatch_dedup_idx" in existing_indexes:
            summary["already_present"] += 1
        else:
            await db.notification_dispatch_log.create_index(
                [("tenant_id", 1), ("notification_type", 1),
                  ("recipient_id", 1), ("dedupe_key", 1)],
                name="notif_dispatch_dedup_idx",
                unique=True,
            )
            summary["indexes_created"] += 1
            summary["collections_created"] += 1
        # Non-unique speedup index for read-back queries (audit /
        # dashboard reads).
        if "notif_dispatch_tenant_type_idx" not in existing_indexes:
            await db.notification_dispatch_log.create_index(
                [("tenant_id", 1), ("notification_type", 1),
                  ("reserved_at", -1)],
                name="notif_dispatch_tenant_type_idx",
            )
            summary["indexes_created"] += 1
    except Exception as exc:                                    # noqa: BLE001
        summary["errors"].append({"stage": "dispatch_log_index",
                                    "error": str(exc)})
        logger.warning(
            "[notification_dispatch_log] dispatch_log index failed: %s", exc,
        )

    # 2. Scheduler-lease compound unique + TTL.
    try:
        from services.comms_hardening.scheduler_lease import ensure_indexes
        await ensure_indexes()
        summary["indexes_created"] += 2  # unique + TTL, best-effort
    except Exception as exc:                                    # noqa: BLE001
        summary["errors"].append({"stage": "scheduler_lease_indexes",
                                    "error": str(exc)})
        logger.warning(
            "[scheduler_lease] index bootstrap failed: %s", exc,
        )

    await _write_sentinel(summary)
    logger.info(
        "[notification_dispatch_log] indexes_created=%s already_present=%s "
        "errors=%s",
        summary["indexes_created"], summary["already_present"],
        len(summary["errors"]),
    )
    return {"status": "ok", "summary": summary}
