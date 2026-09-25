#!/usr/bin/env python3
"""Feb-2026 · Support script — dedupe overlapping customers + properties.

Wraps the shared ``services.customer_merge.executor.merge_customers``
helper so audit trails, tenant scoping, and cascade rules apply.
Runs in dry-run mode by default; ``--apply`` flips the write.

Preview vs. production posture:
  * On preview (aquaterra tenant), James Conrad has ONE customer
    with the correct Adobe Dam address; the Bajada Road property
    belongs to a DIFFERENT customer (Michael Raushenberger).  No
    duplicates to fix.
  * The user reports the duplicates exist on production only.  Run
    this script from a shell that can reach the production Mongo,
    against the production tenant_id.

──────────────────────────────────────────────────────────────────────
Pre-flight (run these on the PRODUCTION Mongo shell FIRST)
──────────────────────────────────────────────────────────────────────
Replace ``<TENANT_ID>`` with the production tenant:

  db.customers.find(
      {tenant_id: "<TENANT_ID>", name: /james.*conrad/i},
      {id: 1, name: 1, address: 1, primary_property_id: 1,
       created_at: 1, merged_into: 1}
  ).pretty()

  db.properties.find(
      {tenant_id: "<TENANT_ID>",
       $or: [
         {"address.line1": /bajada/i},
         {"address.line1": /adobe.*dam/i}
       ]},
      {id: 1, label: 1, address: 1, customer_id: 1,
       is_primary: 1, sort_order: 1, deleted_at: 1}
  ).pretty()

Take the JAMES CONRAD customer id you want to KEEP (target) and the
DUPLICATE customer id(s) you want to merge IN (sources). Same for
the property row that should survive (target) and the ones to soft-
delete (extras).
──────────────────────────────────────────────────────────────────────

Usage:

  # Dry-run (default) — merges customers + rewires props to target:
  python scripts/support/dedupe_customers_properties.py \\
      --tenant-id <TENANT_ID> \\
      --target-customer-id <target_cust_id> \\
      --customer-ids <dup_cust_id_1>,<dup_cust_id_2>

  # Apply (writes):
  python scripts/support/dedupe_customers_properties.py \\
      --tenant-id <TENANT_ID> \\
      --target-customer-id <target_cust_id> \\
      --customer-ids <dup_cust_id_1>,<dup_cust_id_2> \\
      --apply

  # Also soft-delete duplicate property rows AFTER the merge:
  python scripts/support/dedupe_customers_properties.py \\
      --tenant-id <TENANT_ID> \\
      --target-customer-id <target_cust_id> \\
      --customer-ids <dup_cust_id_1> \\
      --target-property-id <keeper_property_id> \\
      --property-ids <dup_property_id_1>,<dup_property_id_2> \\
      --apply

Notes:
  * ``--customer-ids`` may be empty when you only need to dedupe
    property rows on a single customer.
  * Property soft-delete stamps ``deleted_at`` + ``deleted_by`` on
    the row (never a hard delete) so the ``data_repair`` scanner
    can pick up misfired rows for later inspection.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

# ── path bootstrap so this script can be run from /app root ──
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_BACKEND = os.path.join(_ROOT, "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="dedupe_customers_properties",
        description=(
            "Dry-run first parameterized dedupe helper. Wraps "
            "customer_merge + issues soft-delete on stale property "
            "rows. Uses the shared audit-firing helpers — no raw "
            "Mongo writes."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--tenant-id", required=True,
        help="Production tenant_id (required, all reads/writes "
              "scope to this).",
    )
    p.add_argument(
        "--target-customer-id",
        help="Customer id to KEEP as the primary. Required when "
              "--customer-ids is non-empty.",
    )
    p.add_argument(
        "--customer-ids", default="",
        help="Comma-separated customer ids to MERGE IN (secondaries). "
              "Empty means \"skip customer merge, only touch "
              "properties\".",
    )
    p.add_argument(
        "--target-property-id",
        help="Property id to KEEP as canonical. Only required "
              "alongside --property-ids.",
    )
    p.add_argument(
        "--property-ids", default="",
        help="Comma-separated property ids to SOFT-DELETE after "
              "the merge (their content is preserved via "
              "``deleted_at`` / ``deleted_by`` — no hard delete).",
    )
    p.add_argument(
        "--initiated-by", default="support-script",
        help="Audit ``initiated_by`` string. Defaults to "
              "\"support-script\".",
    )
    p.add_argument(
        "--dry-run", dest="dry_run", action="store_true",
        default=True, help="Preview mode (default).",
    )
    p.add_argument(
        "--apply", dest="dry_run", action="store_false",
        help="Actually write. Overrides --dry-run.",
    )
    return p.parse_args()


def _split_csv(raw: str) -> List[str]:
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


async def _run(args: argparse.Namespace) -> int:
    # Lazy import so ``--help`` doesn't need Motor / dotenv.
    from config import db
    from services.customer_merge.executor import merge_customers

    tenant_id: str = args.tenant_id
    target_cust: str = args.target_customer_id or ""
    dup_cust_ids: List[str] = _split_csv(args.customer_ids)
    target_prop: str = args.target_property_id or ""
    dup_prop_ids: List[str] = _split_csv(args.property_ids)

    print("═══════════════════════════════════════════════════════")
    print("  dedupe_customers_properties · plan")
    print("═══════════════════════════════════════════════════════")
    print(f"  tenant_id            : {tenant_id}")
    print(f"  target_customer_id   : {target_cust or '(none)'}")
    print(f"  duplicate customers  : {dup_cust_ids or '(none)'}")
    print(f"  target_property_id   : {target_prop or '(none)'}")
    print(f"  duplicate properties : {dup_prop_ids or '(none)'}")
    print(f"  MODE                 : "
          f"{'DRY-RUN' if args.dry_run else 'APPLY (writes)'}")
    print("═══════════════════════════════════════════════════════")

    # ── Sanity check the inputs before touching the DB.
    if dup_cust_ids and not target_cust:
        print("ERR: --target-customer-id is required when "
              "--customer-ids is set.")
        return 2
    if dup_prop_ids and not target_prop:
        print("ERR: --target-property-id is required when "
              "--property-ids is set.")
        return 2

    # ── Print the pre-existing rows we plan to touch, for
    #    operator inspection.
    if target_cust or dup_cust_ids:
        cust_ids = [target_cust] + dup_cust_ids
        print("\n──  Customer preview  ─────────────────────────")
        async for c in db.customers.find(
            {"tenant_id": tenant_id, "id": {"$in": cust_ids}},
            {"_id": 0, "id": 1, "name": 1, "address": 1,
              "primary_property_id": 1, "merged_into": 1,
              "created_at": 1},
        ):
            print(f"  {c}")
    if target_prop or dup_prop_ids:
        prop_ids = [target_prop] + dup_prop_ids
        print("\n──  Property preview  ─────────────────────────")
        async for p in db.properties.find(
            {"tenant_id": tenant_id, "id": {"$in": prop_ids}},
            {"_id": 0, "id": 1, "customer_id": 1, "label": 1,
              "address": 1, "sort_order": 1, "is_primary": 1,
              "deleted_at": 1},
        ):
            print(f"  {p}")

    # ── 1) Merge duplicate customers into the target.
    merge_result: Dict[str, Any] = {}
    if dup_cust_ids:
        print("\n──  Step 1 · customer merge  ──────────────────")
        merge_result = await merge_customers(
            tenant_id=tenant_id,
            primary_id=target_cust,
            secondary_ids=dup_cust_ids,
            strategy="newest_wins",
            initiated_by=args.initiated_by,
            dry_run=args.dry_run,
        )
        print("  result:")
        for k, v in merge_result.items():
            print(f"    {k}: {v}")

    # ── 2) Soft-delete the duplicate property rows on the target
    #    customer.  merge_customers already rewired ``customer_id``
    #    for us (Commit 2), so ``dup_prop_ids`` are now owned by
    #    ``target_cust``. Guard: never soft-delete the ``target_prop``.
    if dup_prop_ids:
        if target_prop in dup_prop_ids:
            print("ERR: --target-property-id is listed in "
                  "--property-ids; that would soft-delete the row "
                  "you're trying to keep.")
            return 2
        print("\n──  Step 2 · property soft-delete  ────────────")
        for pid in dup_prop_ids:
            row = await db.properties.find_one(
                {"tenant_id": tenant_id, "id": pid},
                {"_id": 0, "id": 1, "customer_id": 1,
                  "deleted_at": 1, "address": 1},
            )
            if not row:
                print(f"  skip {pid} — not found in tenant")
                continue
            if row.get("deleted_at"):
                print(f"  skip {pid} — already deleted_at="
                      f"{row['deleted_at']}")
                continue
            if args.dry_run:
                print(f"  DRY  soft-delete {pid} "
                      f"(currently owner={row.get('customer_id')})")
                continue
            await db.properties.update_one(
                {"id": pid, "tenant_id": tenant_id},
                {"$set": {
                    "deleted_at": datetime.now(timezone.utc)
                                                 .isoformat(),
                    "deleted_by": args.initiated_by,
                }},
            )
            print(f"  APPLY soft-delete {pid} ✓")

    # ── Post-run state print.
    print("\n──  Post-run state  ────────────────────────────")
    if target_cust:
        cust = await db.customers.find_one(
            {"tenant_id": tenant_id, "id": target_cust},
            {"_id": 0, "id": 1, "name": 1, "merged_into": 1},
        )
        print(f"  target customer: {cust}")
    if target_prop:
        prop = await db.properties.find_one(
            {"tenant_id": tenant_id, "id": target_prop},
            {"_id": 0, "id": 1, "customer_id": 1, "address": 1,
              "deleted_at": 1},
        )
        print(f"  target property: {prop}")

    print("\n═══════════════════════════════════════════════════════")
    print(f"  DONE — mode={'DRY-RUN' if args.dry_run else 'APPLY'}")
    print("═══════════════════════════════════════════════════════")
    return 0


def main() -> int:
    args = _parse_args()
    return asyncio.new_event_loop().run_until_complete(_run(args))


if __name__ == "__main__":
    sys.exit(main())
