"""Feb-2026 · CYA Over-Threshold Report — preview seed script.

Dev-only operator convenience. Seeds 3 synthetic CYA readings
(150 ppm, 120 ppm, 110 ppm) across 3 real service reports on the
aquaterra tenant so the operator can smoke-test
``/reports/cya-high`` end-to-end on preview without having to type
chemistry readings via the UI.

**NOT auto-wired to the production boot path.** This script is
only invoked manually, e.g.::

    python backend/scripts/seed_cya_high_readings.py          # apply
    python backend/scripts/seed_cya_high_readings.py --dry-run
    python backend/scripts/seed_cya_high_readings.py --clean  # purge

Idempotent — every run first ``delete_many`` purges prior rows the
script itself created (identified by the ``cya-high-seed-``
``service_reports.id`` prefix), THEN re-inserts the three fresh
rows. Running the script twice back-to-back is safe.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import db  # noqa: E402  (sys.path mutation above)


SEED_PREFIX = "cya-high-seed-"
SEED_CUSTOMER_ID = f"{SEED_PREFIX}cust-01"
SEED_JOB_IDS = [f"{SEED_PREFIX}job-{i:02d}" for i in (1, 2, 3)]
SEED_REPORT_IDS = [f"{SEED_PREFIX}sr-{i:02d}" for i in (1, 2, 3)]
SEED_VALUES = [150, 120, 110]
SEED_DATES = ["2026-07-04", "2026-07-11", "2026-07-18"]


async def _resolve_tenant(slug: str) -> dict:
    t = await db.tenants.find_one(
        {"slug": slug}, {"_id": 0, "id": 1, "slug": 1},
    )
    if not t:
        raise SystemExit(f"tenant with slug={slug!r} not found")
    return t


async def _purge() -> int:
    """Delete any artefact this script has ever written. Called
    at the top of every run so idempotence holds across repeated
    invocations."""
    deleted = 0
    for coll in ("service_reports", "jobs", "customers"):
        res = await getattr(db, coll).delete_many(
            {"id": {"$regex": f"^{SEED_PREFIX}"}},
        )
        deleted += res.deleted_count
    return deleted


async def _seed(tenant_id: str) -> None:
    await db.customers.insert_one({
        "id": SEED_CUSTOMER_ID,
        "tenant_id": tenant_id,
        "name": "CYA Seed Customer (DEMO)",
        "address": "1 CYA Seed Lane",
        "is_active": True,
        "created_at": "2026-01-01T00:00:00+00:00",
    })
    for jid, date in zip(SEED_JOB_IDS, SEED_DATES):
        await db.jobs.insert_one({
            "id": jid,
            "tenant_id": tenant_id,
            "customer_id": SEED_CUSTOMER_ID,
            "scheduled_date": date,
            "scheduled_start": f"{date}T09:00:00-07:00",
            "status": "completed",
            "created_at": "2026-01-01T00:00:00+00:00",
        })
    for rid, jid, value, date in zip(SEED_REPORT_IDS, SEED_JOB_IDS,
                                       SEED_VALUES, SEED_DATES):
        await db.service_reports.insert_one({
            "id": rid,
            "tenant_id": tenant_id,
            "customer_id": SEED_CUSTOMER_ID,
            "job_id": jid,
            "tech_id": "seed-tech",
            "submitted_at": f"{date}T15:00:00+00:00",
            "created_at":   f"{date}T14:00:00+00:00",
            "chemical_readings": [{
                "key": "cyanuric_acid",
                "name": "Cyanuric Acid",
                "unit": "ppm",
                "value": value,
            }],
        })


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tenant-slug", default="aquaterra")
    ap.add_argument("--dry-run", action="store_true",
                     help="print the plan without touching the DB")
    ap.add_argument("--clean", action="store_true",
                     help="only delete artefacts; do not re-seed")
    args = ap.parse_args()

    if args.dry_run:
        print(f"[dry-run] would target tenant_slug={args.tenant_slug}")
        print(f"[dry-run] would purge rows with id prefix "
              f"{SEED_PREFIX!r}")
        if not args.clean:
            print(f"[dry-run] would seed 1 customer, 3 jobs, "
                  f"3 service_reports with CYA values "
                  f"{SEED_VALUES}")
        return 0

    tenant = await _resolve_tenant(args.tenant_slug)
    purged = await _purge()
    print(f"purged {purged} prior seed rows")

    if args.clean:
        print("clean mode — no re-seed")
        return 0

    await _seed(tenant["id"])
    print(f"seeded 1 customer + 3 jobs + 3 reports with CYA "
          f"values {SEED_VALUES} on tenant "
          f"{args.tenant_slug!r} ({tenant['id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
