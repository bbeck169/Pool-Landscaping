"""Phase 15 · Feb-2026 — Backfill Lumino ``paid_at`` from ``db.payment_events``.

Fixes historical drift from bugs B4/B5: pre-Phase-11, the Lumino return
handler + reconciler marked ``status=paid`` only on the retired
``db.invoices`` collection. Real customer invoices in ``db.quotes``
(``doc_type="invoice"``) never received the ``paid_at`` mirror.

This script scans ``db.payment_events`` for successful Lumino payments,
matches each to its ``db.quotes`` doc, and back-mirrors ``paid_at`` +
``payment_status="paid"`` + ``amount_paid=total`` when the invoice is
still unpaid on our side. Every action is logged into
``db.invoice_reconciliation_log`` (Phase 11 collection) with
``action="backfill_lumino_paid_at"``.

Design guarantees
-----------------
* **Idempotent**: subsequent runs report ``backfilled: 0`` — invoices
  already flagged ``paid`` are skipped via ``already_paid``.
* **Earliest-event wins**: when multiple ``payment.created`` events
  reference the same invoice, the earliest ``occurred_at`` (falling
  back to ``received_at``) supplies the ``paid_at``. The full event
  history is preserved in ``db.payment_events`` — the reconciliation
  log entry lists the source event id used.
* **Success signal**: ``event_type == "payment.created"``. Investigation
  confirmed this is the only success marker in the current dataset;
  ``status`` and ``kind`` fields are empty. The ``raw.data.status``
  field is also honored: if present, must be ``"succeeded"``.
* **Dry-run**: ``--dry-run`` prints the summary without touching either
  ``db.quotes`` or ``db.invoice_reconciliation_log``.

Usage
-----
    python -m backend.scripts.backfill_lumino_paid_at [--dry-run]

Prints a summary of the form::

    scanned: 5
    backfilled: 3
    already_paid: 1
    invoice_not_found: 1
    dry_run: False
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger("backfill_lumino_paid_at")

ACTION_TAG = "backfill_lumino_paid_at"
SUCCESS_EVENT_TYPE = "payment.created"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pick_event_ts(evt: Dict[str, Any]) -> str:
    """Return the best-available timestamp string for a success event.

    Order: ``occurred_at`` → ``received_at`` → current UTC as final
    fallback (only if both fields are missing/None)."""
    for k in ("occurred_at", "received_at"):
        v = evt.get(k)
        if v:
            return str(v)
    return _now_iso()


def _is_successful_event(evt: Dict[str, Any]) -> bool:
    """A Lumino/Zapier success is ``event_type == "payment.created"``.

    If the event carries an inner ``raw.data.status`` value, it must be
    ``"succeeded"``. Missing status is treated as success (matches the
    seed data confirmed during investigation)."""
    if (evt.get("event_type") or "").lower() != SUCCESS_EVENT_TYPE:
        return False
    raw = evt.get("raw") or {}
    if not isinstance(raw, dict):
        raw = {}
    inner = raw.get("data") or {}
    if not isinstance(inner, dict):
        inner = {}
    status = (inner.get("status") or "").lower()
    if status and status != "succeeded":
        return False
    return True


async def backfill(
    *, db, dry_run: bool = False
) -> Dict[str, Any]:
    """Return a summary dict with keys: ``scanned``, ``backfilled``,
    ``already_paid``, ``invoice_not_found``, ``dry_run``.

    ``db`` is an ``AsyncIOMotorDatabase`` — passed in so tests can bind
    to a per-loop client without spawning a fresh script process.
    """
    events = await db.payment_events.find({}, {"_id": 0}).to_list(10000)
    successful = [e for e in events if _is_successful_event(e)]

    # Group by invoice_id and keep the earliest by timestamp.
    earliest_by_invoice: Dict[str, Dict[str, Any]] = {}
    for e in successful:
        inv_id = e.get("invoice_id")
        if not inv_id:
            continue
        cur = earliest_by_invoice.get(inv_id)
        if cur is None or _pick_event_ts(e) < _pick_event_ts(cur):
            earliest_by_invoice[inv_id] = e

    summary = {
        "scanned": len(earliest_by_invoice),
        "backfilled": 0,
        "already_paid": 0,
        "invoice_not_found": 0,
        "dry_run": dry_run,
    }

    for invoice_id, evt in earliest_by_invoice.items():
        inv = await db.quotes.find_one(
            {"id": invoice_id, "doc_type": "invoice"},
            {"_id": 0, "id": 1, "tenant_id": 1, "total": 1,
             "amount_paid": 1, "payment_status": 1, "paid_at": 1},
        )
        if not inv:
            summary["invoice_not_found"] += 1
            continue
        already_paid = (
            (inv.get("payment_status") or "").lower() == "paid"
            or inv.get("paid_at")
        )
        if already_paid:
            summary["already_paid"] += 1
            continue

        paid_at = _pick_event_ts(evt)
        set_ops = {
            "payment_status": "paid",
            "paid_at": paid_at,
            "backfilled_from_lumino_event_at": _now_iso(),
        }
        # Only stamp amount_paid if not already set — the invoice.total
        # is authoritative for the full-paid case.
        if float(inv.get("amount_paid") or 0) == 0:
            set_ops["amount_paid"] = float(inv.get("total") or 0)

        if dry_run:
            summary["backfilled"] += 1
            continue

        await db.quotes.update_one(
            {"id": invoice_id, "doc_type": "invoice"},
            {"$set": set_ops},
        )
        await db.invoice_reconciliation_log.insert_one({
            "id": str(uuid.uuid4()),
            "action": ACTION_TAG,
            "invoice_id": invoice_id,
            "tenant_id": inv.get("tenant_id"),
            "source_event_id": evt.get("id") or evt.get("lumino_event_id"),
            "applied_paid_at": paid_at,
            "ran_at": _now_iso(),
            "logged_at": _now_iso(),
        })
        summary["backfilled"] += 1

    return summary


async def _main(dry_run: bool) -> Dict[str, Any]:
    env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    client = AsyncIOMotorClient(env["MONGO_URL"])
    db = client[env["DB_NAME"]]
    return await backfill(db=db, dry_run=dry_run)


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                          help="Print the summary without writing to Mongo")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = asyncio.run(_main(args.dry_run))
    for k in ("scanned", "backfilled", "already_paid", "invoice_not_found", "dry_run"):
        print(f"{k}: {result.get(k)}")
