"""Ticket AA · Step 2 · Feb-2026 — Admin runner for the two-step
service_category backfill.

Runs the AA tag→customers backfill, then force-reruns the P2 #6
property-inheritance migration so the newly-populated customer
rows cascade to properties.

Usage::

    cd /app/backend && python -m scripts.aa_run_service_category_backfill
    cd /app/backend && python -m scripts.aa_run_service_category_backfill --dry-run

Both migrations are idempotent:
  * Step 1 bypasses its sentinel with ``force=True`` and uses an
    ``$or`` null-guard at the write site so no previously-filled
    customer row is clobbered.
  * Step 2 (``seed_property_service_category_from_customer``)
    scans properties where ``service_category`` is null / missing /
    empty — admin PATCH writes (``source=admin_override``) have
    the field set and are therefore skipped by the scan filter.

This runner was executed once in Step 2 of Ticket AA with the
following result (committed as the "AFTER" spot-check in the
ticket receipt):

    Step 1: 234 customers mapped (pool=127, landscaping=78, both=29)
    Step 2: 237 properties inherited (pool=128, landscaping=80, both=29)
    Vista tenant: pool=65 properties / landscaping=43 / both=15

The runner is kept in-tree as a reproducible artifact so operators
can re-run both passes together after any future bulk tag edit.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys


async def _main(dry_run: bool) -> int:
    # Patch config.db to the real Mongo client before importing the
    # migration modules — matches the boot-time wiring in server.py.
    import config  # noqa: F401
    from services.migrations.aa_tag_to_service_category_backfill import (
        run_tag_to_service_category_backfill,
    )
    from services.migrations.seed_property_service_category_from_customer import (
        run_property_service_category_inheritance,
    )

    print("=== Step 1 · tag → customers.service_category ===")
    r1 = await run_tag_to_service_category_backfill(
        force=True, dry_run=dry_run,
    )
    print(json.dumps(r1.get("summary") or r1, indent=2, default=str))

    if dry_run:
        print("\n(dry-run — skipping Step 2 property cascade)")
        return 0

    print("\n=== Step 2 · P2 #6 property inheritance (force) ===")
    r2 = await run_property_service_category_inheritance(force=True)
    print(json.dumps(r2.get("summary") or r2, indent=2, default=str))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview the counts without writing to DB.",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(dry_run=args.dry_run)))
