"""Phase C1 · Feb-2026 — one-time completed_at backfill.

Fills ``jobs.completed_at`` for every completed job that doesn't
already carry the field. Idempotent — jobs with a truthy
``completed_at`` are skipped. Precedence:

    1. ``auto_invoice_created_at`` if present
    2. Latest ``service_reports.completed_at`` (else
       ``submitted_at``) for the job
    3. ``jobs.updated_at``

Usage
-----
::

    # Dry-run against one tenant
    python -m scripts.backfill_job_completed_at --tenant-id=<uuid> --dry-run

    # Live run against one tenant
    python -m scripts.backfill_job_completed_at --tenant-id=<uuid>

    # Live sweep across every tenant
    python -m scripts.backfill_job_completed_at --all
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any, Dict, List, Optional

# Allow running as ``python backend/scripts/backfill_job_completed_at.py``.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv                                # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient            # noqa: E402

load_dotenv(os.path.join(_ROOT, ".env"))


def _pick_completed_at(
    job: Dict[str, Any],
    latest_report: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Resolve the best available completion timestamp for a job.

    Returns ``None`` when nothing usable exists (caller may skip
    or stamp `updated_at` as a last resort — this helper defers
    that decision to the caller).
    """
    if job.get("auto_invoice_created_at"):
        return job["auto_invoice_created_at"]
    if latest_report:
        return (latest_report.get("completed_at")
                 or latest_report.get("submitted_at"))
    return job.get("updated_at")


async def backfill_tenant(
    db, tenant_id: str, *, dry_run: bool = False,
) -> Dict[str, Any]:
    """Backfill every completed job in a single tenant.

    Returns a summary ``{tenant_id, backfilled_count, skipped_count,
    unresolved_count}`` where ``unresolved_count`` covers jobs where
    no fallback timestamp existed at all.
    """
    q = {"tenant_id": tenant_id, "status": "completed"}
    jobs: List[Dict[str, Any]] = await db.jobs.find(
        q, {"_id": 0, "id": 1, "completed_at": 1,
             "auto_invoice_created_at": 1, "updated_at": 1},
    ).to_list(500_000)

    already: int = 0
    unresolved: int = 0
    to_update: List[Dict[str, Any]] = []

    # Batch-load latest service reports for every job in one query.
    job_ids = [j["id"] for j in jobs if not j.get("completed_at")]
    latest_report_by_job: Dict[str, Dict[str, Any]] = {}
    if job_ids:
        cursor = db.service_reports.find(
            {"tenant_id": tenant_id, "job_id": {"$in": job_ids}},
            {"_id": 0, "job_id": 1, "completed_at": 1,
             "submitted_at": 1},
        ).sort("submitted_at", -1)
        async for r in cursor:
            jid = r.get("job_id") or ""
            latest_report_by_job.setdefault(jid, r)

    for j in jobs:
        if j.get("completed_at"):
            already += 1
            continue
        stamp = _pick_completed_at(
            j, latest_report_by_job.get(j["id"]),
        )
        if not stamp:
            unresolved += 1
            continue
        to_update.append({"id": j["id"], "completed_at": stamp})

    backfilled = 0
    if not dry_run and to_update:
        for entry in to_update:
            r = await db.jobs.update_one(
                {"id": entry["id"], "tenant_id": tenant_id,
                 "$or": [{"completed_at": None},
                         {"completed_at": {"$exists": False}}]},
                {"$set": {"completed_at": entry["completed_at"]}},
            )
            if r.modified_count:
                backfilled += 1

    return {
        "tenant_id":         tenant_id,
        "backfilled_count":  backfilled if not dry_run else len(to_update),
        "skipped_count":     already,
        "unresolved_count":  unresolved,
        "dry_run":           dry_run,
    }


async def _run(args: argparse.Namespace) -> None:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    if args.tenant_id:
        tenants = [args.tenant_id]
    else:
        cursor = db.tenants.find({"active": True}, {"_id": 0, "id": 1})
        tenants = [t["id"] async for t in cursor if t.get("id")]

    print(f"[backfill] running dry_run={args.dry_run} for "
          f"{len(tenants)} tenant(s)")
    grand_total = 0
    for tid in tenants:
        r = await backfill_tenant(db, tid, dry_run=args.dry_run)
        grand_total += r["backfilled_count"]
        print(f"[backfill] tenant={tid} "
              f"backfilled={r['backfilled_count']} "
              f"skipped={r['skipped_count']} "
              f"unresolved={r['unresolved_count']} "
              f"dry_run={r['dry_run']}")
    print(f"[backfill] done · total_backfilled={grand_total}")


def main() -> None:
    parser = argparse.ArgumentParser()
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--tenant-id",
                       help="Target a single tenant by id")
    grp.add_argument("--all", action="store_true",
                       dest="all_tenants",
                       help="Sweep every active tenant")
    parser.add_argument("--dry-run", action="store_true",
                          help="Report only — no writes")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
