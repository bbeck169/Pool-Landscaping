"""Feb-2026 · P37a — Geocode backfill for customers / jobs / properties.

For every row lacking ``latitude`` + ``longitude``, invoke the P37a
geocode-and-persist helpers. Uses the same 30-day cache as the
customer helper so re-runs are idempotent + cheap.

Failure mode is safe: if ``GOOGLE_MAPS_API_KEY`` is not set OR the
Google API returns ZERO_RESULTS OR the address is empty, the row
simply saves without lat/lng and does not participate in P37 GPS
auto-start. No user-visible error.

Usage
-----
    $ python -m migrations.task_p37_geocode_backfill          # dry-run
    $ python -m migrations.task_p37_geocode_backfill --commit # write
    $ python -m migrations.task_p37_geocode_backfill --commit --tenant <id>
    $ python -m migrations.task_p37_geocode_backfill --commit --limit 25
"""
from __future__ import annotations

import argparse
import asyncio
from typing import Any, Dict, List, Optional

from config import db, logger
from services.google_maps.geocoding import (
    geocode_and_persist_customer,
    geocode_and_persist_job,
    geocode_and_persist_property,
)


async def _scan(coll_name: str, latitude_field: str,
                 lng_field: str, tenant_filter: Optional[str]) -> List[Dict[str, Any]]:
    q: dict = {"$or": [
        {latitude_field: {"$exists": False}},
        {latitude_field: None},
        {lng_field: {"$exists": False}},
        {lng_field: None},
    ]}
    if tenant_filter:
        q["tenant_id"] = tenant_filter
    return await db[coll_name].find(
        q, {"_id": 0, "id": 1, "tenant_id": 1, "name": 1},
    ).to_list(10_000)


async def main(commit: bool, tenant: Optional[str],
                 limit: Optional[int]) -> Dict[str, Any]:
    # ── Customers ────────────────────────────────────────────────
    cust_rows = await _scan("customers", "latitude", "longitude", tenant)
    # ── Jobs ─────────────────────────────────────────────────────
    job_rows = await _scan("jobs", "latitude", "longitude", tenant)
    # ── Properties ───────────────────────────────────────────────
    prop_rows = await _scan("properties", "latitude", "longitude", tenant)

    result = {
        "committed": bool(commit),
        "tenant_filter": tenant,
        "limit": limit,
        "customers": {"scanned": len(cust_rows), "geocoded": 0, "skipped": 0},
        "jobs":      {"scanned": len(job_rows),  "geocoded": 0, "skipped": 0},
        "properties":{"scanned": len(prop_rows), "geocoded": 0, "skipped": 0},
    }
    if not commit:
        return result

    n = 0
    for row in cust_rows:
        if limit and n >= limit:
            break
        try:
            ok = await geocode_and_persist_customer(row["id"], row["tenant_id"])
            result["customers"]["geocoded" if ok else "skipped"] += 1
            n += 1
        except Exception as e:
            logger.warning("[p37] customer=%s geocode error: %s", row["id"], e)
            result["customers"]["skipped"] += 1

    n = 0
    for row in job_rows:
        if limit and n >= limit:
            break
        try:
            ok = await geocode_and_persist_job(row["id"], row["tenant_id"])
            result["jobs"]["geocoded" if ok else "skipped"] += 1
            n += 1
        except Exception as e:
            logger.warning("[p37] job=%s geocode error: %s", row["id"], e)
            result["jobs"]["skipped"] += 1

    n = 0
    for row in prop_rows:
        if limit and n >= limit:
            break
        try:
            ok = await geocode_and_persist_property(row["id"], row["tenant_id"])
            result["properties"]["geocoded" if ok else "skipped"] += 1
            n += 1
        except Exception as e:
            logger.warning("[p37] property=%s geocode error: %s", row["id"], e)
            result["properties"]["skipped"] += 1

    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--tenant", type=str, default=None)
    ap.add_argument("--limit",  type=int, default=None,
                       help="Per-collection safety cap (default: no cap).")
    args = ap.parse_args()
    out = asyncio.run(main(commit=args.commit, tenant=args.tenant, limit=args.limit))
    print("─── task_p37_geocode_backfill ───")
    print(f"committed:       {out['committed']}")
    for coll in ("customers", "jobs", "properties"):
        s = out[coll]
        print(f"  {coll:<11} scanned={s['scanned']:>4}  "
                f"geocoded={s['geocoded']:>4}  skipped={s['skipped']:>4}")
