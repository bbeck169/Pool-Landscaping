"""K15 · Feb-2026 — Jobs schedule/status/crew indexes.

Sentinel: ``k15_jobs_indexes_v1``. Idempotent + sentinel-guarded.
Creates the two indexes identified by the K15 RCA of the mobile
Schedule screen latency:

  1. ``k15_jobs_tech_schedule_status``
     — ``(tenant_id ASC, technician_id ASC, scheduled_date ASC, status ASC)``
     — covers the admin/tech schedule list queries filtered by tech
       + date-range + status (the dominant mobile Schedule read).
  2. ``k15_jobs_crew_schedule``
     — ``(tenant_id ASC, crew_id ASC, scheduled_date ASC)``
     — covers the crew-filter schedule reads introduced in Feb-2026
       Crew Phase A.

K33 · Feb-2026 — boot-wired counterpart to the standalone
``scripts.k15_seed_jobs_indexes`` seed. Both paths are safe to
co-exist: ``create_index`` is idempotent at the driver level, and
this migration is additionally sentinel-guarded so a second boot
after a successful first run is an early-return no-op.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import db


logger = logging.getLogger("k15_jobs_indexes_migration")

_SENTINEL_ID = "k15_jobs_indexes_v1"

# Each entry: (index_name, key_spec). ``db.jobs`` is the sole target.
_INDEXES: List[Tuple[str, List[Tuple[str, int]]]] = [
    ("k15_jobs_tech_schedule_status",
     [("tenant_id", 1), ("technician_id", 1),
      ("scheduled_date", 1), ("status", 1)]),
    ("k15_jobs_crew_schedule",
     [("tenant_id", 1), ("crew_id", 1), ("scheduled_date", 1)]),
]


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


async def run_k15_jobs_indexes_migration(
    *, force: bool = False,
) -> Dict[str, Any]:
    """Create the two K15 indexes on ``db.jobs`` if missing.

    Returns::

        {"status": "ok" | "skipped",
         "summary": {
             "created": <int>,
             "already_present": <int>,
             "errors": [...],
             "targets": [...],
         }}
    """
    if not force:
        sentinel = await _sentinel_row()
        if sentinel:
            return {"status": "skipped",
                    "reason": "sentinel_present",
                    "sentinel": sentinel}

    summary: Dict[str, Any] = {
        "created": 0,
        "already_present": 0,
        "errors": [],
        "targets": [],
    }

    existing = set()
    async for idx in db.jobs.list_indexes():
        existing.add(idx.get("name") or "")

    for idx_name, keys in _INDEXES:
        target_result: Dict[str, Any] = {"index": idx_name}
        try:
            if idx_name in existing:
                target_result["status"] = "already_present"
                summary["already_present"] += 1
            else:
                await db.jobs.create_index(
                    keys, name=idx_name, background=True,
                )
                target_result["status"] = "created"
                summary["created"] += 1
        except Exception as exc:  # noqa: BLE001
            target_result["status"] = "error"
            target_result["error"] = str(exc)
            summary["errors"].append(target_result)
            logger.warning(
                "[k15] index jobs.%s failed: %s", idx_name, exc,
            )
        summary["targets"].append(target_result)

    if not summary["errors"]:
        await _write_sentinel(summary)

    logger.info(
        "[k15] created=%s already_present=%s errors=%s",
        summary["created"], summary["already_present"],
        len(summary["errors"]),
    )
    return {"status": "ok", "summary": summary}
