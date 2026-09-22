"""Phase P23 · Feb-2026 — Restore two hard-deleted technicians.

One-shot data restoration. Two technicians (Ethan Smith and Steven
Martinez) were hard-deleted from ``db.technicians`` at some prior
point; the ~600+ jobs stamped with their ``technician_id`` FK still
reference those exact ids and are consequently invisible in every
technician-scoped read (Schedule blank lanes, Dispatch missing rows,
Reports null-owned).

Fix: idempotently re-insert both rows under their ORIGINAL IDs. Jobs
relink AUTOMATICALLY because the FK doesn't change — no jobs
collection mutation is required or performed.

Idempotence contract
--------------------
* ``update_one({"id": <id>}, {"$setOnInsert": <full doc>}, upsert=True)``
  is the shape used per row. On first run: the row is inserted with
  the full spec + ``created_at`` / ``updated_at`` timestamps. On any
  subsequent run: nothing changes (``$setOnInsert`` is a no-op when
  the row already exists), so the migration can be safely called on
  every pod boot from the P21 structural block.
* No existing field is EVER overwritten — if an admin has since
  updated Ethan's phone number, or a later migration renames a field,
  the values persisted at that write are preserved.

Diagnostic
----------
After the upsert pass runs a count of active (non-soft-deleted) jobs
whose ``technician_id`` matches either restored id. The user's note
expects 600+ across both. The count is logged at INFO and returned
in the summary dict so the P21 lifespan can log it as a boot signal.

Called from ``server._run_boot_sequence`` — see the P21 lifespan
comment thread. Structural (pre-yield): the pod must have those two
rows in ``db.technicians`` before it serves the first Schedule fetch
or the tech-lane filter will still return an empty list on the
freshly-migrated FK.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from config import db, logger


# The exact rows the user provided. IDs are the ORIGINAL primary keys
# of the two hard-deleted rows — DO NOT regenerate. The jobs
# collection still carries these values on ``technician_id``.
_RESTORE_ROWS: List[Dict[str, Any]] = [
    {
        "id": "b728523e-533d-40b4-b33a-dbd3592c0e39",
        "name": "Ethan Smith",
        "department": "pool_tech",
        "email": "ej3015@hotmail.com",
        "tenant_id": "67752881-7a80-4a2c-a03e-5d1aff4861a4",
        "active": True,
    },
    {
        "id": "ed4a4b04-d153-490c-bb17-3c402c72c8cb",
        "name": "Steven Martinez",
        "department": "landscape_tech",
        "email": "landscape7@plofv.com",
        "tenant_id": "67752881-7a80-4a2c-a03e-5d1aff4861a4",
        "active": True,
    },
]


async def run() -> Dict[str, Any]:
    """Perform the restoration. Idempotent — see module docstring.

    Returns a summary dict with per-id ``inserted`` / ``already_present``
    booleans plus the post-migration active-jobs count for diagnostics.
    """
    now = datetime.now(timezone.utc).isoformat()
    report: Dict[str, Any] = {
        "inserted": [],
        "already_present": [],
        "active_job_count": 0,
    }

    for row in _RESTORE_ROWS:
        full_doc = dict(row)
        full_doc["created_at"] = now
        full_doc["updated_at"] = now
        # ``$setOnInsert`` writes the doc ONLY if this upsert creates
        # a new row. On subsequent runs Mongo matches the existing row
        # via ``{"id": <id>}`` and no-ops — existing fields (including
        # any admin edits between boots) are preserved verbatim.
        result = await db.technicians.update_one(
            {"id": row["id"]},
            {"$setOnInsert": full_doc},
            upsert=True,
        )
        if result.upserted_id is not None:
            report["inserted"].append(row["id"])
            logger.info(
                "[p23-restore] technician inserted id=%s name=%s "
                "department=%s tenant=%s",
                row["id"], row["name"], row["department"], row["tenant_id"],
            )
        else:
            report["already_present"].append(row["id"])

    # Sanity-check the FK relink expectation. The count of active,
    # non-soft-deleted jobs stamped with either restored ``technician_id``
    # should be 600+ per the user's note. Missing / small counts DO
    # NOT block boot — the diagnostic is purely a signal for ops to
    # confirm the restore worked as designed.
    ids = [r["id"] for r in _RESTORE_ROWS]
    try:
        report["active_job_count"] = await db.jobs.count_documents({
            "technician_id": {"$in": ids},
            "$or": [
                {"deleted_at": None},
                {"deleted_at": {"$exists": False}},
            ],
        })
    except Exception as exc:  # noqa: BLE001 — diagnostic only
        logger.warning(
            "[p23-restore] active-job count failed: %s", exc,
        )

    logger.info(
        "[p23-restore] summary inserted=%s already_present=%s "
        "active_jobs_relinked=%s",
        len(report["inserted"]),
        len(report["already_present"]),
        report["active_job_count"],
    )
    return report
