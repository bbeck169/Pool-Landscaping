"""PB1 · Feb-2026 — Wholesale + labor cost backfill.

One-shot idempotent backfill script.

1. For every ``db.items`` doc where ``wholesale_price`` is missing /
   null → set it to 0. Same for ``labor_cost_default``.
2. For every line item on every ``db.quotes`` doc whose 3 snapshot
   fields are missing, fill them from the current linked item master
   (via ``item_id``) or default 0 when the item id doesn't resolve.
   ``retail_price_snapshot`` always mirrors the current ``unit_price``
   on that line, since that's the price the customer already saw.

Idempotent — re-running never overwrites an existing snapshot.

Usage
-----
    python -m scripts.backfill_wholesale_price [--dry-run]

Or programmatically ``from scripts.backfill_wholesale_price import run``.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict

# Ensure the backend module root is importable when the script is
# invoked directly.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from config import db, logger  # noqa: E402


async def _backfill_items(dry_run: bool) -> Dict[str, int]:
    added_wholesale = 0
    added_labor = 0
    total = 0
    async for it in db.items.find(
        {}, {"_id": 0, "id": 1,
              "wholesale_price": 1, "labor_cost_default": 1},
    ):
        total += 1
        upd: Dict[str, Any] = {}
        if it.get("wholesale_price") in (None, ""):
            upd["wholesale_price"] = 0.0
        if it.get("labor_cost_default") in (None, ""):
            upd["labor_cost_default"] = 0.0
        if upd:
            if not dry_run:
                await db.items.update_one({"id": it["id"]}, {"$set": upd})
            if "wholesale_price" in upd:
                added_wholesale += 1
            if "labor_cost_default" in upd:
                added_labor += 1
    return {"items_total": total,
            "items_wholesale_filled": added_wholesale,
            "items_labor_filled": added_labor}


async def _backfill_line_items(dry_run: bool) -> Dict[str, int]:
    invoices_touched = 0
    lines_touched = 0
    total_docs = 0
    # Preload item master into memory once — the profit-report path
    # does the same but online. Here we can afford the cache because
    # backfill is a one-shot job.
    master: Dict[str, Dict[str, Any]] = {}
    async for it in db.items.find(
        {}, {"_id": 0, "id": 1,
              "wholesale_price": 1, "labor_cost_default": 1,
              "unit_price": 1},
    ):
        master[it["id"]] = it

    async for doc in db.quotes.find(
        {}, {"_id": 0, "id": 1, "tenant_id": 1, "line_items": 1},
    ):
        total_docs += 1
        lines = doc.get("line_items") or []
        if not lines:
            continue
        changed = False
        for li in lines:
            item_master = master.get(li.get("item_id") or "") or {}
            if li.get("retail_price_snapshot") in (None, ""):
                try:
                    li["retail_price_snapshot"] = float(
                        li.get("unit_price") or 0)
                except (TypeError, ValueError):
                    li["retail_price_snapshot"] = 0.0
                changed = True
                lines_touched += 1
            if li.get("wholesale_price_snapshot") in (None, ""):
                try:
                    li["wholesale_price_snapshot"] = float(
                        item_master.get("wholesale_price") or 0)
                except (TypeError, ValueError):
                    li["wholesale_price_snapshot"] = 0.0
                changed = True
            if li.get("labor_cost_snapshot") in (None, ""):
                try:
                    li["labor_cost_snapshot"] = float(
                        item_master.get("labor_cost_default") or 0)
                except (TypeError, ValueError):
                    li["labor_cost_snapshot"] = 0.0
                changed = True
        if changed:
            invoices_touched += 1
            if not dry_run:
                await db.quotes.update_one(
                    {"id": doc["id"]},
                    {"$set": {"line_items": lines}},
                )
    return {"quotes_total": total_docs,
            "quotes_touched": invoices_touched,
            "lines_touched": lines_touched}


async def run(dry_run: bool = False) -> Dict[str, Any]:
    logger.info(
        "[PB1 backfill] starting (dry_run=%s) …", dry_run,
    )
    items_summary = await _backfill_items(dry_run)
    lines_summary = await _backfill_line_items(dry_run)
    summary = {**items_summary, **lines_summary, "dry_run": dry_run}
    logger.info("[PB1 backfill] complete: %s", summary)
    return summary


def _cli() -> None:
    parser = argparse.ArgumentParser(description="PB1 wholesale/labor backfill")
    parser.add_argument("--dry-run", action="store_true",
                          help="Report row counts without writing.")
    args = parser.parse_args()
    result = asyncio.get_event_loop().run_until_complete(
        run(dry_run=bool(args.dry_run)))
    # Emit a machine-readable summary line for CI.
    for k, v in result.items():
        print(f"{k}={v}")


if __name__ == "__main__":
    _cli()
