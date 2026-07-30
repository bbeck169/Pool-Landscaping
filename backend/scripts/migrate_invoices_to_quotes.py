"""Phase 11 · Feb-2026 — Invoice dual-collection migration.

One-shot idempotent script that moves any orphan rows from ``db.invoices``
into ``db.quotes`` (with ``doc_type="invoice"``) and logs any drift on
rows that are present in both. Prints a summary.

Usage:
    python -m scripts.migrate_invoices_to_quotes            # real run
    python -m scripts.migrate_invoices_to_quotes --dry-run  # no writes
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _load_quote_index(db) -> Tuple[set, set]:
    q_ids: set = set()
    q_inv_id_ids: set = set()
    async for r in db.quotes.find({"doc_type": "invoice"},
                                     {"_id": 0, "id": 1, "invoice_id": 1}):
        if r.get("id"):
            q_ids.add(r["id"])
        if r.get("invoice_id"):
            q_inv_id_ids.add(r["invoice_id"])
    return q_ids, q_inv_id_ids


def _project_invoice_row(inv: Dict[str, Any]) -> Dict[str, Any]:
    """Fill schema gaps between ``db.invoices`` and ``db.quotes``.

    Never loses source data — the ``db.invoices`` row's own keys always
    win over synthesized defaults."""
    total_cents = int(inv.get("total_cents") or 0)
    projected: Dict[str, Any] = {
        "doc_type": "invoice",
        "line_items": [],
        "payment_status": "unpaid",
        "total": round(total_cents / 100.0, 2),
        "created_at": _now_iso(),
        # Never set invoice_number unless the source had one — leaves the
        # `tenant_invoice_number_unique` sparse index alone.
    }
    for k, v in inv.items():
        if k == "_id":
            continue
        projected[k] = v
    # Migration markers.
    projected["migrated_from_invoices"] = True
    projected["migration_needs_review"] = True
    projected["migrated_at"] = _now_iso()
    return projected


async def _log_drift(db, invoice_id: str, i_doc: Dict[str, Any],
                        q_doc: Dict[str, Any]) -> None:
    """Compare fields present in ``db.invoices`` against ``db.quotes``
    (the source of truth) and log any drift. Never overwrites."""
    diffs: Dict[str, Dict[str, Any]] = {}
    for k in i_doc.keys():
        if k in ("_id",):
            continue
        iv = i_doc.get(k)
        qv = q_doc.get(k)
        if iv != qv:
            diffs[k] = {"invoices_value": iv, "quotes_value": qv}
    if not diffs:
        return
    await db.invoice_reconciliation_log.update_one(
        {"invoice_id": invoice_id, "kind": "duplicate_drift"},
        {"$set": {
            "invoice_id": invoice_id,
            "tenant_id": q_doc.get("tenant_id") or i_doc.get("tenant_id"),
            "kind": "duplicate_drift",
            "field_drift": diffs,
            "resolved_by": "prefer_quotes",  # quotes wins per policy
            "logged_at": _now_iso(),
        }},
        upsert=True,
    )


async def run_migration(*, dry_run: bool) -> Dict[str, int]:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    q_ids, q_inv_id_ids = await _load_quote_index(db)
    stats = {"scanned": 0, "migrated": 0, "already_present": 0,
              "drift_logged": 0, "missing_id": 0}

    async for inv in db.invoices.find({}):
        stats["scanned"] += 1
        rid = inv.get("id") or inv.get("invoice_id")
        if not rid:
            stats["missing_id"] += 1
            print(f"  · row _id={inv['_id']} has no `id` or `invoice_id` — skipped")
            continue

        # Is this row already in db.quotes?
        already = None
        if rid in q_ids or rid in q_inv_id_ids:
            already = await db.quotes.find_one(
                {"$or": [{"id": rid}, {"invoice_id": rid}],
                  "doc_type": "invoice"},
                {"_id": 0})
        if already:
            stats["already_present"] += 1
            drift_before = await db.invoice_reconciliation_log.find_one(
                {"invoice_id": rid, "kind": "duplicate_drift"})
            if not dry_run:
                await _log_drift(db, rid, inv, already)
            drift_after = await db.invoice_reconciliation_log.find_one(
                {"invoice_id": rid, "kind": "duplicate_drift"})
            if drift_after and not drift_before:
                stats["drift_logged"] += 1
            continue

        # True orphan → migrate.
        projected = _project_invoice_row(inv)
        if not dry_run:
            try:
                await db.quotes.insert_one(projected)
            except Exception as e:
                # Idempotency guard — if a concurrent run already inserted
                # this id, treat as already_present.
                if "duplicate key" in str(e).lower():
                    stats["already_present"] += 1
                    continue
                raise
        stats["migrated"] += 1
        print(f"  · {'[DRY]' if dry_run else '[MIGR]'} {rid} "
              f"tenant={inv.get('tenant_id')} status={inv.get('status')} "
              f"total_cents={inv.get('total_cents')}")

    print()
    print("=" * 60)
    print(f"{'DRY-RUN' if dry_run else 'MIGRATION'} SUMMARY")
    print("=" * 60)
    print(f"scanned:         {stats['scanned']}")
    print(f"migrated:        {stats['migrated']}")
    print(f"already_present: {stats['already_present']}")
    print(f"drift_logged:    {stats['drift_logged']}")
    if stats["missing_id"]:
        print(f"missing_id:      {stats['missing_id']}  (skipped)")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                     help="Print what would happen without writing.")
    args = ap.parse_args()
    asyncio.run(run_migration(dry_run=bool(args.dry_run)))


if __name__ == "__main__":
    main()
