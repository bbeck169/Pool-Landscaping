"""Feb-2026 · P29 — seed default muted_reasons for every existing tenant.

Idempotent: tenants that already have any ``muted_reasons`` are skipped.
Dry-run by default; ``--commit`` writes.

Usage
-----
    $ python -m migrations.task_p29_seed_muted_reasons              # dry-run
    $ python -m migrations.task_p29_seed_muted_reasons --commit     # write
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any, Dict, List

from config import db, logger
from routers.muted_reasons import DEFAULT_MUTED_REASONS, seed_muted_reasons_for_tenant
from utils import new_id, now_iso


async def main(commit: bool) -> Dict[str, int]:
    seeded_tenants = 0
    seeded_rows = 0
    tenants: List[Dict[str, Any]] = await db.tenants.find(
        {}, {"_id": 0, "id": 1, "name": 1},
    ).to_list(500)
    for t in tenants:
        tid = t.get("id")
        if not tid:
            continue
        if await db.muted_reasons.count_documents({"tenant_id": tid}) > 0:
            continue
        seeded_tenants += 1
        if commit:
            inserted = await seed_muted_reasons_for_tenant(tid)
            seeded_rows += inserted
            logger.info("[p29] seeded %s reasons for tenant=%s (%s)",
                            inserted, tid, t.get("name"))
        else:
            seeded_rows += len(DEFAULT_MUTED_REASONS)
    return {"tenants_seeded": seeded_tenants, "rows_seeded": seeded_rows,
             "committed": bool(commit)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(main(commit=args.commit))
    mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"[p29] muted-reasons seed {mode}: {result}")
