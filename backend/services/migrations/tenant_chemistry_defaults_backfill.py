"""Sprint 3b · Feb-2026 — Chemistry defaults backfill migration.

Idempotently seeds every tenant missing ``settings.chemistry.*`` with
the AZ defaults (targets + gate_mode). Existing custom values are
preserved via per-key ``$exists: false`` guards.

Usage (CLI):
    python -m services.migrations.tenant_chemistry_defaults_backfill --dry-run
    python -m services.migrations.tenant_chemistry_defaults_backfill

Or via the admin endpoint:
    POST /api/admin/chemistry/backfill-tenant-defaults
        (super_admin-only; body: {"dry_run": true|false})
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from typing import Any, Dict

from motor.motor_asyncio import AsyncIOMotorClient

from services.chemistry_tenant_targets import (
    AZ_DEFAULT_TARGETS,
    CHEMICAL_KEYS,
    DEFAULT_GATE_MODE,
    UNITS,
)


log = logging.getLogger("migrations.tenant_chemistry_defaults")


def _target_row(chemical: str) -> Dict[str, Any]:
    row = AZ_DEFAULT_TARGETS[chemical]
    return {
        "min":  float(row["min"]),
        "max":  float(row["max"]),
        "unit": UNITS.get(chemical, row.get("unit") or ""),
    }


async def backfill(db, *, dry_run: bool = False) -> Dict[str, int]:
    """Backfill missing keys. Returns per-field counts."""
    counts: Dict[str, int] = {}
    # Targets — per-chemical guard so a tenant with a PARTIAL block
    # keeps its custom rows.
    for chem in CHEMICAL_KEYS:
        path = f"settings.chemistry.targets.{chem}"
        default_row = _target_row(chem)
        if dry_run:
            n = await db.tenants.count_documents({path: {"$exists": False}})
        else:
            res = await db.tenants.update_many(
                {path: {"$exists": False}},
                {"$set": {path: default_row}},
            )
            n = res.modified_count
        counts[f"targets.{chem}"] = int(n)
    # gate_mode
    path = "settings.chemistry.gate_mode"
    if dry_run:
        n = await db.tenants.count_documents({path: {"$exists": False}})
    else:
        res = await db.tenants.update_many(
            {path: {"$exists": False}},
            {"$set": {path: DEFAULT_GATE_MODE}},
        )
        n = res.modified_count
    counts["gate_mode"] = int(n)
    # dosing_formulas key — write an empty object if missing so tenant
    # PATCHes don't fail on unknown-parent path.
    path = "settings.chemistry.dosing_formulas"
    if dry_run:
        n = await db.tenants.count_documents({path: {"$exists": False}})
    else:
        res = await db.tenants.update_many(
            {path: {"$exists": False}},
            {"$set": {path: {}}},
        )
        n = res.modified_count
    counts["dosing_formulas"] = int(n)
    total = sum(counts.values())
    log.info(
        "[tenant_chemistry_defaults_backfill] dry_run=%s counts=%s total=%d",
        dry_run, counts, total,
    )
    return {"dry_run": dry_run, "counts": counts, "total_writes": total}


async def _main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                    help="Count rows that would be updated without persisting")
    args = p.parse_args()
    url = os.environ["MONGO_URL"]
    name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(url)
    try:
        result = await backfill(client[name], dry_run=args.dry_run)
        print(result)
    finally:
        client.close()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
