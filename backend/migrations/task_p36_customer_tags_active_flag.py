"""Feb-2026 · P36 — Backfill ``is_active=True`` + ``sort_order=0`` on
every ``customer_tags`` row that predates the P36 archive contract.

Idempotent — rows already carrying ``is_active`` are skipped.
Dry-run default; ``--commit`` writes.

Usage
-----
    $ python -m migrations.task_p36_customer_tags_active_flag          # dry-run
    $ python -m migrations.task_p36_customer_tags_active_flag --commit # write
"""
from __future__ import annotations

import argparse
import asyncio

from config import db, logger


async def main(commit: bool) -> dict:
    q = {"is_active": {"$exists": False}}
    would = await db.customer_tags.count_documents(q)
    updated = 0
    if commit and would:
        r = await db.customer_tags.update_many(
            q,
            {"$set": {"is_active": True, "sort_order": 0}},
        )
        updated = int(r.modified_count)
        logger.info("[p36] backfilled %s customer_tags rows to is_active=true",
                        updated)
    return {"committed": bool(commit),
              "would_backfill": would, "backfilled": updated}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    out = asyncio.run(main(commit=args.commit))
    print("─── task_p36_customer_tags_active_flag ───")
    print(f"committed:       {out['committed']}")
    if args.commit:
        print(f"backfilled:      {out['backfilled']}")
    else:
        print(f"would_backfill:  {out['would_backfill']}")
