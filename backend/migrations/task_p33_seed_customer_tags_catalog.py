"""Feb-2026 · P33 — Seed the tenant ``customer_tags`` catalog from
existing ``customers.tags`` values.

Every tag string ever attached to a customer (via CRM UI, Homeworks
import, direct DB write, older versions of the customer form before
the auto-persist hook, etc.) is upserted into the tenant-scoped
``customer_tags`` collection as ``auto_created=true`` on any row that
wasn't already there. Existing catalog rows are left untouched.

Idempotent — safe to re-run. Dry-run by default; ``--commit`` writes.

Usage
-----
    $ python -m migrations.task_p33_seed_customer_tags_catalog          # dry-run
    $ python -m migrations.task_p33_seed_customer_tags_catalog --commit # write
"""
from __future__ import annotations

import argparse
import asyncio
from typing import Any, Dict, List

from config import db, logger
from routers.customer_tags import auto_persist_customer_tags


async def main(commit: bool) -> Dict[str, Any]:
    tenants: List[Dict[str, Any]] = await db.tenants.find(
        {}, {"_id": 0, "id": 1, "name": 1},
    ).to_list(500)

    per_tenant: List[Dict[str, Any]] = []
    grand_inserted = 0
    grand_scanned_customers = 0

    for t in tenants:
        tid = t.get("id")
        if not tid:
            continue

        # Collect every distinct tag string this tenant's customers carry.
        distinct = set()
        n_customers = 0
        async for cust in db.customers.find(
            {"tenant_id": tid,
              "tags": {"$exists": True, "$ne": []}},
            {"_id": 0, "tags": 1},
        ):
            n_customers += 1
            for raw in (cust.get("tags") or []):
                if isinstance(raw, str) and raw.strip():
                    distinct.add(raw.strip())
        grand_scanned_customers += n_customers

        # How many are already in the catalog?
        already = 0
        will_insert = 0
        for label in distinct:
            hit = await db.customer_tags.find_one(
                {"tenant_id": tid, "name_lower": label.lower()},
                {"_id": 0, "id": 1},
            )
            if hit:
                already += 1
            else:
                will_insert += 1

        inserted = 0
        if commit and will_insert:
            inserted = await auto_persist_customer_tags(
                tid, "migration_p33", list(distinct),
            )
            logger.info("[p33] tenant=%s scanned=%s distinct=%s "
                            "already=%s inserted=%s",
                            tid, n_customers, len(distinct), already, inserted)

        grand_inserted += (inserted if commit else will_insert)
        per_tenant.append({
            "tenant_id": tid,
            "tenant_name": t.get("name"),
            "customers_scanned": n_customers,
            "distinct_tags": len(distinct),
            "already_in_catalog": already,
            "inserted": inserted if commit else 0,
            "would_insert": will_insert,
        })

    return {
        "committed": bool(commit),
        "grand_total_inserted": grand_inserted,
        "grand_total_customers_scanned": grand_scanned_customers,
        "tenants": per_tenant,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    out = asyncio.run(main(commit=args.commit))
    print("─── task_p33_seed_customer_tags_catalog ───")
    print(f"committed:                     {out['committed']}")
    print(f"grand_total_customers_scanned: {out['grand_total_customers_scanned']}")
    if args.commit:
        print(f"grand_total_inserted:          {out['grand_total_inserted']}")
    else:
        print(f"grand_total_would_insert:      {out['grand_total_inserted']}")
    for row in out["tenants"]:
        summary = (
            f"  tenant={row['tenant_id']:36s} "
            f"scanned={row['customers_scanned']:>4}  "
            f"distinct={row['distinct_tags']:>3}  "
            f"already={row['already_in_catalog']:>3}  "
        )
        if args.commit:
            summary += f"inserted={row['inserted']}"
        else:
            summary += f"would_insert={row['would_insert']}"
        print(summary)
