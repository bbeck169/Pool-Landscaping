"""FIN-PARITY-C · Feb-2026 — backfill missing ``doc_date`` /
``due_date`` / ``paid_at`` on historic PDF-import previews.

Prior to FIN-PARITY-C, some ``mapper_previews`` rows persisted in
``db.import_batches`` may be missing one or more of the three
date fields (either the key is absent or the value is None
despite the extractor having captured a value).  Re-uploading the
source PDFs isn't practical — the raw
``import_batches.extracted_documents_full`` array still holds the
extractor's original ExtractedDocument dicts, and the FIN-PARITY-C
``services.imports.pdf_mapper.derive_pdf_dates`` helper is the
same canonical logic the live mapper uses — running it against
those historic rows produces byte-identical output to what a
re-upload would emit.

Idempotent — a second run against a row this migration already
filled reports "no change" and issues no writes.
Tenant-scoped — one tenant at a time via the ``--tenant`` flag.
Resume-safe — ``--resume-from <batch_id>`` skips every batch
whose ``id`` sorts lexicographically before the checkpoint (batch
ids are UUIDv4 strings; the migration sorts ASC by id).
Dry-run default — ``--apply`` opts in to actual writes.
Audit trail — one ``db.import_audit`` row per batch touched
(inserted only under ``--apply``).

Usage
    # Dry-run tenant A:
    python /app/backend/migrations/backfill_pdf_dates_v1.py \
        --tenant tenant_abc

    # Apply tenant A:
    python /app/backend/migrations/backfill_pdf_dates_v1.py \
        --tenant tenant_abc --apply

    # Resume from a checkpoint:
    python /app/backend/migrations/backfill_pdf_dates_v1.py \
        --tenant tenant_abc --apply --resume-from batch_id_here
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Allow ``python migrations/backfill_pdf_dates_v1.py`` invocation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import dotenv_values  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from services.imports.pdf_mapper import derive_pdf_dates  # noqa: E402


logger = logging.getLogger("migrations.backfill_pdf_dates_v1")

# Only these three keys are written by this migration.  Anything
# else on ``quote_in`` / ``payment_in`` is left untouched.
DATE_KEYS = ("doc_date", "due_date", "paid_at")

# The mapper writes ``payment_in`` with no ``due_date`` key at
# all — attempting to gap-fill ``due_date`` on a payment_in would
# reintroduce a schema drift the mapper is careful to avoid.
_PAYMENT_ELIGIBLE = ("doc_date", "paid_at")


def _make_db_from_env():
    """Instantiate a motor client the same way the app does."""
    be_env = dotenv_values(
        Path(__file__).resolve().parents[1] / ".env"
    )
    mongo_url = be_env.get("MONGO_URL") or os.environ.get("MONGO_URL")
    db_name = be_env.get("DB_NAME") or os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise RuntimeError(
            "MONGO_URL / DB_NAME not set — cannot run backfill."
        )
    client = AsyncIOMotorClient(mongo_url)
    return client[db_name]


def _target_dict_for_preview(preview: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the mutable sub-dict of ``preview`` that carries the
    date fields — ``quote_in`` or ``payment_in`` depending on
    ``mapped_target``.  Returns None when the preview has neither
    (e.g. an errored ``deferred_to_h4`` row).
    """
    mt = preview.get("mapped_target")
    if mt == "quote_in":
        return preview.get("quote_in")
    if mt == "payment_in":
        return preview.get("payment_in")
    return None


def _eligible_keys_for(preview: Dict[str, Any]) -> Tuple[str, ...]:
    """Return the tuple of date keys this preview *should* carry.

    A ``payment_in`` preview never carries ``due_date`` — the live
    mapper does not emit it.  A ``quote_in`` preview carries all
    three (invoice) or two (estimate — no ``paid_at``); the live
    ``derive_pdf_dates`` already returns ``None`` for the fields
    that don't apply, so we lean on that: an eligible key here
    means "if the derived value is not None, write it".
    """
    return _PAYMENT_ELIGIBLE if preview.get("mapped_target") == "payment_in" else DATE_KEYS


def plan_batch_changes(
    batch: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Compute the per-preview changes required to bring the
    batch's ``mapper_previews`` in line with ``derive_pdf_dates``.

    Returns ``(new_previews, change_log)`` where ``change_log`` is
    a list of dicts describing each field write (used for
    dry-run output + the audit row payload).  When no changes are
    needed ``change_log`` is empty.
    """
    previews = batch.get("mapper_previews") or []
    extracted_full = batch.get("extracted_documents_full") or []

    # Build a source_doc_index → extracted-dict map for robust
    # matching (some historic batches may have had failed
    # extractions dropped from ``mapper_previews`` but retained
    # in ``extracted_documents_full`` — we align on the
    # extractor's ``source_doc_index`` field, falling back to
    # array index when the field is absent).
    ext_by_index: Dict[int, Dict[str, Any]] = {}
    for i, ext in enumerate(extracted_full):
        if not isinstance(ext, dict):
            continue
        idx = ext.get("source_doc_index")
        ext_by_index[int(idx) if idx is not None else i] = ext

    new_previews: List[Dict[str, Any]] = []
    change_log: List[Dict[str, Any]] = []

    for i, preview in enumerate(previews):
        if not isinstance(preview, dict):
            new_previews.append(preview)
            continue
        # Deep-ish copy the mutable sub-dicts we may touch.
        preview_copy = dict(preview)
        target = _target_dict_for_preview(preview_copy)
        if target is None:
            new_previews.append(preview_copy)
            continue
        target_copy = dict(target)

        sdi = preview.get("source_doc_index")
        ext = (
            ext_by_index.get(int(sdi))
            if sdi is not None
            else ext_by_index.get(i)
        )
        if not ext:
            new_previews.append(preview_copy)
            continue

        derived = derive_pdf_dates(ext)
        eligible = _eligible_keys_for(preview_copy)

        row_changes: List[Dict[str, Any]] = []
        for key in eligible:
            new_val = derived.get(key)
            if new_val is None:
                # Nothing to backfill — the extractor didn't give
                # us a value either.
                continue
            current = target_copy.get(key)
            if current is None:
                target_copy[key] = new_val
                row_changes.append({
                    "source_doc_index": sdi if sdi is not None else i,
                    "mapped_target": preview_copy.get("mapped_target"),
                    "field": key,
                    "old_value": current,
                    "new_value": new_val,
                })

        if row_changes:
            change_log.extend(row_changes)
            if preview_copy.get("mapped_target") == "quote_in":
                preview_copy["quote_in"] = target_copy
            else:
                preview_copy["payment_in"] = target_copy

        new_previews.append(preview_copy)

    return new_previews, change_log


async def _iter_batches(
    db, *, tenant_id: str, resume_from: Optional[str],
):
    """Yield ``import_batches`` docs for one tenant, ordered by
    ``id`` ASC, optionally skipping everything up to and including
    the resume checkpoint."""
    query: Dict[str, Any] = {
        "tenant_id": tenant_id,
        # Only batches that made it past extraction — earlier
        # states have no ``mapper_previews`` array to touch.
        "mapper_previews": {"$exists": True, "$ne": []},
    }
    if resume_from:
        query["id"] = {"$gt": resume_from}
    cursor = db.import_batches.find(query).sort([("id", 1)])
    async for batch in cursor:
        yield batch


async def run_backfill(
    db,
    *,
    tenant_id: str,
    apply: bool = False,
    resume_from: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the backfill for one tenant.  Returns a summary dict
    (batches scanned / touched / fields written / audit ids).
    """
    scanned = 0
    touched = 0
    fields_written = 0
    audit_ids: List[str] = []
    last_batch_id: Optional[str] = None

    now_iso = datetime.now(timezone.utc).isoformat()

    async for batch in _iter_batches(
        db, tenant_id=tenant_id, resume_from=resume_from,
    ):
        scanned += 1
        last_batch_id = batch.get("id") or last_batch_id
        new_previews, change_log = plan_batch_changes(batch)

        if not change_log:
            continue

        touched += 1
        fields_written += len(change_log)

        logger.info(
            "[backfill_pdf_dates_v1] batch=%s tenant=%s "
            "planned_changes=%d apply=%s",
            batch.get("id"), tenant_id, len(change_log), apply,
        )
        for chg in change_log:
            logger.info(
                "  · sdi=%s target=%s %s: None → %s",
                chg["source_doc_index"], chg["mapped_target"],
                chg["field"], chg["new_value"],
            )

        if not apply:
            continue

        # ── Apply — rewrite mapper_previews atomically ─────
        await db.import_batches.update_one(
            {"id": batch["id"], "tenant_id": tenant_id},
            {"$set": {
                "mapper_previews": new_previews,
                "backfill_pdf_dates_v1_applied_at": now_iso,
            }},
        )

        # ── Audit — one row per batch touched, mirrors the
        # reconciler audit pattern (services.imports
        # .payment_reconciler.reconcile_invoice_after_payment).
        audit_id = str(uuid.uuid4())
        await db.import_audit.insert_one({
            "id": audit_id,
            "tenant_id": tenant_id,
            "batch_id": batch["id"],
            "action": "backfill_pdf_dates_v1",
            "source": "migration",
            "actor": "system",
            "changes": change_log,
            "field_count": len(change_log),
            "created_at": now_iso,
        })
        audit_ids.append(audit_id)

    summary = {
        "tenant_id": tenant_id,
        "scanned": scanned,
        "touched": touched,
        "fields_written": fields_written,
        "audit_ids": audit_ids,
        "last_batch_id": last_batch_id,
        "apply": apply,
    }
    logger.info("[backfill_pdf_dates_v1] summary=%s", summary)
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FIN-PARITY-C · backfill PDF date fields on "
                    "historic mapper_previews rows.",
    )
    parser.add_argument(
        "--tenant", required=True,
        help="Tenant id to process (one tenant per run).",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually write changes.  Default is dry-run.",
    )
    parser.add_argument(
        "--resume-from", default=None,
        help="Skip every batch whose id sorts <= this value.",
    )
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    db = _make_db_from_env()
    summary = await run_backfill(
        db,
        tenant_id=args.tenant,
        apply=args.apply,
        resume_from=args.resume_from,
    )
    print("--- summary ---")
    for k, v in summary.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
