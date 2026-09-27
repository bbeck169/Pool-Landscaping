"""Feb-2026 · PDF Importer Sub-phase A — historical ``doc_date`` backfill.

Populates the newly-introduced ``doc_date`` field on every
``db.quotes`` row that was written by the PDF Importer commit path
(marked ``imported_from_pdf=True`` — see
``backend/services/imports/pdf_commit.py`` line ~477) but predates
Sub-phase A and therefore has no ``doc_date`` yet.

Per ruling R1=A:
  * Copy ``created_at`` → ``doc_date`` on every eligible row.
  * NEVER mutate ``created_at`` — the existing audit trail on
    legacy rows is treated as read-only; only the NEW field is
    populated.
  * Non-PDF rows (manual estimate creation, legacy pre-flag rows)
    are NOT touched.  ``imported_from_pdf`` must be literally
    ``True`` for a row to qualify.

Idempotency
───────────
Sentinel: ``db.migration_status.find_one({"key": MIGRATION_KEY})``.
Same pattern as ``perf_customers_indexes_v2.py`` — a second run
after a successful first pass short-circuits to
``{"ok": True, "skipped": True, "reason": "already_ran"}`` without
touching any documents.

Failure mode
────────────
A pymongo error while running the update writes an ``error`` field
on the sentinel doc but does NOT set ``completed_at``.  The next
boot's ``_REQUIRED_MIGRATIONS`` gate retries.  Ruled
``must_succeed=False`` at boot (see server.py) — a partial backfill
never crashes boot or 503's the readiness gate.

Rollback
────────
The migration is copy-forward only; there is no inverse operation.
To reverse::

    db.quotes.update_many(
        {"imported_from_pdf": True},
        {"$unset": {"doc_date": ""}},
    )
    db.migration_status.delete_one({"key": "pdf_doc_date_backfill_v1"})
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger("services.migrations.pdf_doc_date_backfill_v1")

MIGRATION_KEY = "pdf_doc_date_backfill_v1"


async def run(db: Any) -> Dict[str, Any]:
    """Backfill ``doc_date`` from ``created_at`` for every
    PDF-imported quote missing the new field.

    Args:
        db: the motor async database handle.

    Returns:
        Dict with the standard migration-report shape::

            {
                "ok": bool,
                "skipped": bool,
                "reason": str | absent,
                "matched": int,      # rows meeting the filter (only present when not skipped)
                "modified": int,     # rows actually written to (only present when not skipped)
                "error": str | absent,
            }
    """
    sentinel = await db.migration_status.find_one(
        {"key": MIGRATION_KEY}, {"_id": 0},
    )
    if sentinel and sentinel.get("completed_at"):
        return {
            "ok": True, "skipped": True,
            "reason": "already_ran",
        }

    # Filter — only PDF-imported rows that are missing ``doc_date``.
    # ``None`` and absent both qualify (``$in: [None]`` + ``$exists``
    # negation via ``$or``).  Non-PDF rows have no
    # ``imported_from_pdf`` field at all → excluded by the strict
    # equality on True.
    filt: Dict[str, Any] = {
        "imported_from_pdf": True,
        "$or": [
            {"doc_date": {"$exists": False}},
            {"doc_date": None},
        ],
    }

    # Aggregation-pipeline update (MongoDB 4.2+) — copies each
    # matched row's ``created_at`` into ``doc_date`` in a single
    # collection-scope op instead of iterate-and-update.  This is
    # the same pattern the Motor + PyMongo docs recommend for
    # per-row field copy-through.
    pipeline = [{"$set": {"doc_date": "$created_at"}}]

    try:
        result = await db.quotes.update_many(filt, pipeline)
        matched = int(getattr(result, "matched_count", 0) or 0)
        modified = int(getattr(result, "modified_count", 0) or 0)
        logger.info(
            "[pdf_doc_date_backfill_v1] matched=%s modified=%s",
            matched, modified,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[pdf_doc_date_backfill_v1] update_many failed: %s", exc,
        )
        # Record the error on the sentinel WITHOUT setting
        # ``completed_at`` so the next boot retries.
        await db.migration_status.update_one(
            {"key": MIGRATION_KEY},
            {"$set": {
                "key": MIGRATION_KEY,
                "error": str(exc)[:400],
                "last_attempt_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        return {"ok": False, "skipped": False, "error": str(exc)[:400]}

    await db.migration_status.update_one(
        {"key": MIGRATION_KEY},
        {"$set": {
            "key": MIGRATION_KEY,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "matched": matched,
            "modified": modified,
        },
         "$unset": {"error": "", "last_attempt_at": ""}},
        upsert=True,
    )
    return {
        "ok": True, "skipped": False,
        "matched": matched, "modified": modified,
    }
