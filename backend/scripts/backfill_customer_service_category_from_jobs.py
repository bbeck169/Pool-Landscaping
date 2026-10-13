"""P2 #6 · Feb-2026 — One-shot backfill: customer.service_category from job history.

Heuristic:
    For each customer row where ``service_category`` is unset (null OR
    missing) AND there is at least one historical job with a
    ``service_type`` string containing "pool" or "land" (case-insensitive):

        * matches /pool/i only              →  ``pool``
        * matches /land/i only              →  ``landscaping``
        * matches BOTH on different jobs    →  ``both``

Customers with no job history, or whose jobs all have a service_type
not matching either pattern, remain unset — the admin fills them in
via the P2 #6 CustomerDetail dropdown later.

CONTRACT:

* **First-write-wins**: this script NEVER overwrites an existing
  non-null ``service_category``.  Idempotent on repeat runs.
* **Dry-run by default**: operator must pass ``--commit`` to actually
  write.  Without the flag the script tallies the planned bucket
  counts and exits.  Prints the summary table in both modes.
* **One batch audit row per invocation** (approved alternative to
  spamming 100+ per-row rows):

        event="customer.service_category_backfill_run"
        payload={
            total_scanned, total_updated,
            pool_count, landscaping_count, both_count,
            dry_run, actor="backfill_script",
            source_script="backfill_customer_service_category_from_jobs.py",
            run_at: ISO-UTC,
            tenant_scope: <tid> or "<all>",
        }

* Tenant scope: ``--tenant-id <tid>`` runs against a single tenant.
  Omitted → runs against every tenant in the DB.

Usage:
    python3 backend/scripts/backfill_customer_service_category_from_jobs.py             # dry-run against ALL tenants
    python3 backend/scripts/backfill_customer_service_category_from_jobs.py --tenant-id t-abc
    python3 backend/scripts/backfill_customer_service_category_from_jobs.py --commit    # ACTUALLY write
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient


def _env() -> Dict[str, str]:
    env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    return {k: (v.strip().strip('"').strip("'") if isinstance(v, str) else v)
            for k, v in env.items()}


def _bucket_for(st_values: Iterable[str]) -> Optional[str]:
    """Collapse a customer's service_type values into a bucket."""
    pool = False
    land = False
    for s in st_values:
        if not isinstance(s, str):
            continue
        low = s.lower()
        if "pool" in low:
            pool = True
        if "land" in low:
            land = True
    if pool and land:
        return "both"
    if pool:
        return "pool"
    if land:
        return "landscaping"
    return None


async def _plan(db, tenant_scope: Optional[str]) -> Dict[str, Any]:
    """Return the planned update map keyed by customer id, plus
    per-bucket counts.  Does NOT write."""
    cust_filter: Dict[str, Any] = {
        "$or": [
            {"service_category": None},
            {"service_category": {"$exists": False}},
        ],
    }
    if tenant_scope:
        cust_filter["tenant_id"] = tenant_scope

    # customer_id → (tenant_id, current_category_or_None)
    unset: Dict[str, str] = {}
    async for row in db.customers.find(
        cust_filter, {"_id": 0, "id": 1, "tenant_id": 1},
    ):
        unset[row["id"]] = row["tenant_id"]
    total_scanned = len(unset)

    # Pull job service_type per (tenant_id, customer_id) pair in the
    # unset set.  Index-friendly single $in filter per tenant.
    by_tenant: Dict[str, list] = {}
    for cid, tid in unset.items():
        by_tenant.setdefault(tid, []).append(cid)

    plan: Dict[str, str] = {}  # customer_id → bucket
    for tid, cids in by_tenant.items():
        cust_jobs: Dict[str, list] = {c: [] for c in cids}
        async for job in db.jobs.find(
            {"tenant_id": tid, "customer_id": {"$in": cids}},
            {"_id": 0, "customer_id": 1, "service_type": 1},
        ):
            cust_jobs.setdefault(job["customer_id"], []).append(
                job.get("service_type") or "",
            )
        for cid, sts in cust_jobs.items():
            b = _bucket_for(sts)
            if b:
                plan[cid] = b

    counts = {"pool": 0, "landscaping": 0, "both": 0}
    for b in plan.values():
        counts[b] += 1
    return {
        "total_scanned": total_scanned,
        "plan": plan,
        "counts": counts,
    }


async def _commit(db, plan: Dict[str, str]) -> int:
    """Apply the plan.  Returns actual update count (modified_count)."""
    updated = 0
    for cid, bucket in plan.items():
        res = await db.customers.update_one(
            {"id": cid,
             # Guard rail: last-chance check that nothing else wrote
             # a service_category between plan + commit.  First-write-
             # wins contract.
             "$or": [
                 {"service_category": None},
                 {"service_category": {"$exists": False}},
             ]},
            {"$set": {"service_category": bucket}},
        )
        updated += res.modified_count
    return updated


async def _audit(db, *, tenant_scope, total_scanned, total_updated,
                   counts, dry_run) -> None:
    await db.audit_logs.insert_one({
        "event": "customer.service_category_backfill_run",
        "entity_kind": "customer",
        "actor_user_id": None,
        "actor": "backfill_script",
        "source_script": "backfill_customer_service_category_from_jobs.py",
        "tenant_id": tenant_scope or "<all>",
        "tenant_scope": tenant_scope or "<all>",
        "total_scanned": int(total_scanned),
        "total_updated": int(total_updated),
        "pool_count": int(counts.get("pool", 0)),
        "landscaping_count": int(counts.get("landscaping", 0)),
        "both_count": int(counts.get("both", 0)),
        "dry_run": bool(dry_run),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


def _print_summary(*, dry_run, total_scanned, total_updated, counts,
                     tenant_scope):
    bar = "─" * 56
    print(bar)
    print(f"  P2 #6 · customer.service_category backfill")
    print(f"  tenant_scope      : {tenant_scope or '<all>'}")
    print(f"  mode              : {'DRY-RUN' if dry_run else 'COMMIT'}")
    print(bar)
    print(f"  total_scanned     : {total_scanned}")
    print(f"  pool bucket       : {counts.get('pool', 0)}")
    print(f"  landscaping       : {counts.get('landscaping', 0)}")
    print(f"  both bucket       : {counts.get('both', 0)}")
    print(f"  planned updates   : {sum(counts.values())}")
    if not dry_run:
        print(f"  actual modified   : {total_updated}")
    print(bar)


async def run(*, dry_run: bool, tenant_scope: Optional[str],
                _db_override=None) -> Dict[str, Any]:
    """Public entry point.  Test-callable with ``_db_override``."""
    if _db_override is not None:
        db = _db_override
    else:
        env = _env()
        cli = AsyncIOMotorClient(env["MONGO_URL"])
        db = cli[env["DB_NAME"]]

    plan_result = await _plan(db, tenant_scope)
    total_updated = 0
    if not dry_run and plan_result["plan"]:
        total_updated = await _commit(db, plan_result["plan"])
    await _audit(
        db,
        tenant_scope=tenant_scope,
        total_scanned=plan_result["total_scanned"],
        total_updated=total_updated,
        counts=plan_result["counts"],
        dry_run=dry_run,
    )
    _print_summary(
        dry_run=dry_run,
        total_scanned=plan_result["total_scanned"],
        total_updated=total_updated,
        counts=plan_result["counts"],
        tenant_scope=tenant_scope,
    )
    return {
        "total_scanned": plan_result["total_scanned"],
        "total_updated": total_updated,
        "counts": plan_result["counts"],
        "dry_run": dry_run,
    }


def _cli():
    p = argparse.ArgumentParser(
        description=(
            "P2 #6 · One-shot backfill: customer.service_category "
            "from job service_type history. Dry-run by default."
        ),
    )
    p.add_argument("--tenant-id", default=None,
                    help="scope to a single tenant_id (omit for all tenants)")
    p.add_argument("--commit", action="store_true",
                    help="actually write (default is dry-run)")
    args = p.parse_args()
    return asyncio.run(run(dry_run=not args.commit,
                               tenant_scope=args.tenant_id))


if __name__ == "__main__":
    _cli()
