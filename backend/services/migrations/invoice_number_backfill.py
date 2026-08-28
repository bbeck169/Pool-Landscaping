"""Feb-2026 · P0 fix — Invoice number backfill (idempotent, sentinel-guarded).

Scans every tenant for ``doc_type: 'invoice'`` docs in ``db.quotes``
that were persisted with a null / missing / empty ``invoice_number``
field and assigns each one the next available formatted number in
its tenant's sequence.

Root cause the backfill covers:
  * ``service_reports.py::submit_report`` auto-created "Service —
    {job title}" invoices via a raw ``db.quotes.insert_one`` — the
    call to ``assign_invoice_number_if_missing`` was missing.
  * ``finances.py::accrue_chem_invoice`` created chemical draft
    invoices without a number (they'd later be sent + charged with
    ``invoice_number == null`` — surfaced in Hector Guerrero's
    "Service — Filter Service" bug on prod).
  * ``reports.py::run_all_due_billing_plans`` legacy admin trigger
    skipped the helper.

The three code paths above are patched at the same time as this
backfill ships; the migration heals data already on the floor.

Contract:
  * **Idempotent** — a doc that already carries a valid
    ``invoice_number`` is untouched. Second-run scan reports 0
    updated.
  * **Ordered** — docs are numbered in ``created_at`` ASC order so
    older invoices get smaller numbers (matches operator intuition).
  * **Tenant-scoped sequences** — per-tenant, per-year, per-prefix.
    Never leaks across tenants.
  * **Soft-delete aware** — docs with ``deleted_at`` are skipped
    entirely (would otherwise "steal" a number from a live doc).
  * **Sentinel-guarded on boot** — writes
    ``db.migrations["feb2026_invoice_number_backfill_v1"]`` after a
    successful full-tenant sweep so ``force=False`` runs on
    subsequent boots are a no-op.

Sentinel: ``feb2026_invoice_number_backfill_v1``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import db


logger = logging.getLogger("invoice_number_backfill")


_SENTINEL_ID = "feb2026_invoice_number_backfill_v1"


def _needs_number_filter() -> Dict[str, Any]:
    """Query fragment matching invoice docs with a null / missing /
    empty ``invoice_number``. Soft-deleted docs are excluded."""
    return {
        "doc_type": "invoice",
        "$or": [
            {"invoice_number": None},
            {"invoice_number": ""},
            {"invoice_number": {"$exists": False}},
        ],
        # Do not steal sequence numbers on behalf of a doc the
        # operator has already tombstoned. If someone un-deletes it
        # later, the same code path that un-deletes will re-run the
        # backfill inline.
        "$and": [
            {"$or": [
                {"deleted_at": None},
                {"deleted_at": {"$exists": False}},
            ]},
        ],
    }


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


async def run_invoice_number_backfill(*, force: bool = False) -> Dict[str, Any]:
    """Full-fleet backfill entry point. See module docstring.

    ``force=True`` bypasses the sentinel — used by the super_admin
    admin endpoint to trigger an on-demand re-run (e.g. after
    fixing prod's orphaned invoices from Hector's report).
    """
    if not force:
        sentinel = await _sentinel_row()
        if sentinel:
            logger.info(
                "[invoice-number-backfill] sentinel present — "
                "skipping (completed_at=%s)",
                sentinel.get("completed_at"),
            )
            return {
                "status": "skipped",
                "reason": "sentinel_present",
                "sentinel": sentinel,
            }

    # Import lazily so unit tests can stub the numbering service.
    from services.invoice_numbering import (
        assign_by_tenant_id, ensure_uniqueness_indexes,
    )

    # Uniqueness indexes are a prerequisite — running the backfill
    # over duplicate rows would silently drop one of them.
    try:
        await ensure_uniqueness_indexes()
    except Exception as _exc:                                     # noqa: BLE001
        logger.warning(
            "[invoice-number-backfill] ensure_uniqueness_indexes: %s",
            _exc,
        )

    scanned = 0
    updated = 0
    skipped = 0
    errors: List[Dict[str, Any]] = []
    per_tenant: Dict[str, int] = {}

    # Group by tenant so we can hand ``assign_by_tenant_id`` a stable
    # tenant context per doc. ``created_at`` ASC preserves operator
    # intuition (older invoices → smaller numbers).
    cursor = db.quotes.find(
        _needs_number_filter(),
        {"_id": 0, "id": 1, "tenant_id": 1, "created_at": 1,
          "customer_name": 1, "title": 1},
    ).sort([("tenant_id", 1), ("created_at", 1)])
    async for doc in cursor:
        scanned += 1
        tid = doc.get("tenant_id")
        if not tid:
            skipped += 1
            errors.append({
                "id": doc.get("id"),
                "reason": "missing_tenant_id",
            })
            continue
        try:
            assigned = await assign_by_tenant_id({}, tid)
            number = assigned.get("invoice_number")
            if not number:
                skipped += 1
                errors.append({
                    "id": doc.get("id"),
                    "reason": "generate_returned_empty",
                })
                continue
            await db.quotes.update_one(
                {"id": doc["id"], "tenant_id": tid},
                {"$set": {"invoice_number": number}},
            )
            updated += 1
            per_tenant[tid] = per_tenant.get(tid, 0) + 1
            logger.info(
                "[invoice-number-backfill] assigned %s to inv=%s "
                "customer=%s title=%r",
                number, doc.get("id"), doc.get("customer_name"),
                (doc.get("title") or "")[:60],
            )
        except Exception as _exc:                                # noqa: BLE001
            skipped += 1
            errors.append({
                "id": doc.get("id"),
                "reason": f"assign_failed: {_exc}",
            })

    summary = {
        "scanned": scanned,
        "updated": updated,
        "skipped": skipped,
        "errors_count": len(errors),
        "per_tenant": per_tenant,
    }
    if not force and updated > 0 and not errors:
        await _write_sentinel(summary)
    elif not force and updated == 0:
        # Nothing to do — still stamp sentinel so we don't scan on
        # every boot.
        await _write_sentinel(summary)

    logger.info(
        "[invoice-number-backfill] complete · scanned=%d updated=%d "
        "skipped=%d errors=%d",
        scanned, updated, skipped, len(errors),
    )
    return {
        "status": "ok",
        "summary": summary,
        "errors": errors[:50],  # cap so the response payload stays sane
    }
