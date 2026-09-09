"""
Feb-2026 · Diag-Timeout Task 1 — Customers search benchmark harness.

Seeds N synthetic customers into a scratch tenant, hits the search
endpoint through the actual FastAPI stack, records P50 / P95 / max
across ``iters`` iterations, and cleans up.

Usage (from /app/backend):

    python -m tests.bench_customers_search \
        --n 2000 --search lynn --iters 8 [--keep]

Kept intentionally separate from the pytest suite so it can run
against the live preview DB without polluting the assert-style
regression tests. The pytest guard at
``tests/test_perf_customers_search_p95.py`` runs a scaled-down
version (400 rows) with a strict P95 assertion for CI.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import string
import time
from typing import List

import httpx

from config import db


SCRATCH_TENANT = "bench-cust-search-tenant"


def _rand_id(i: int) -> str:
    return f"bench-cust-{i:06d}"


def _seed_doc(i: int, has_lynn: bool) -> dict:
    first = "Lynn" if has_lynn else ["Alex", "Sam", "Jordan", "Casey",
                                       "Riley", "Taylor"][i % 6]
    last = ["Carson", "Reyes", "Nguyen", "Patel", "Kim", "Baram",
             "Blake", "Mahoney"][i % 8]
    return {
        "id": _rand_id(i),
        "tenant_id": SCRATCH_TENANT,
        "name": f"{first} {last} {i}",
        "first_name": first,
        "last_name": last,
        "email": f"{first.lower()}.{last.lower()}.{i}@example.com",
        "phone": f"+1602{i:07d}",
        "address": f"{i} Bench St, Peoria, AZ",
        "is_active": True,
        "is_muted": False,
        "waitlisted": False,
    }


async def seed(n: int) -> None:
    await db.customers.delete_many({"tenant_id": SCRATCH_TENANT})
    # Salt 5% of the rows with the "Lynn" first-name so the search
    # query actually returns matches — mirrors the prod ratio.
    docs = [_seed_doc(i, has_lynn=(i % 20 == 0)) for i in range(n)]
    # Insert in batches of 500 to keep memory + wire chunks sane.
    for chunk_start in range(0, n, 500):
        await db.customers.insert_many(docs[chunk_start: chunk_start + 500])


async def cleanup() -> None:
    await db.customers.delete_many({"tenant_id": SCRATCH_TENANT})


async def bench(*, search: str, iters: int,
                  base_url: str, tenant_slug: str,
                  auth_bearer: str) -> List[float]:
    latencies: List[float] = []
    async with httpx.AsyncClient(base_url=base_url,
                                    timeout=45.0) as client:
        for _ in range(iters):
            t0 = time.perf_counter()
            r = await client.get(
                "/api/customers",
                params={"search": search, "page": 1, "page_size": 50},
                headers={
                    "Authorization": f"Bearer {auth_bearer}",
                    "X-Tenant-Slug": tenant_slug,
                },
            )
            r.raise_for_status()
            latencies.append(time.perf_counter() - t0)
    return latencies


def summarize(latencies: List[float]) -> str:
    n = len(latencies)
    latencies_sorted = sorted(latencies)
    p50 = latencies_sorted[n // 2]
    p95_idx = max(0, int(round(n * 0.95)) - 1)
    p95 = latencies_sorted[p95_idx]
    mx = latencies_sorted[-1]
    return (f"n={n}  p50={p50*1000:.0f}ms  p95={p95*1000:.0f}ms  "
            f"max={mx*1000:.0f}ms")


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=2000)
    p.add_argument("--search", default="lynn")
    p.add_argument("--iters", type=int, default=8)
    p.add_argument("--keep", action="store_true")
    p.add_argument("--base-url", default="http://localhost:8001")
    p.add_argument("--tenant-slug", default=SCRATCH_TENANT)
    p.add_argument("--bearer", required=True,
                    help="admin JWT scoped to the scratch tenant")
    args = p.parse_args()

    print(f"Seeding {args.n} customers into {SCRATCH_TENANT} …")
    await seed(args.n)
    try:
        print(f"Benchmarking GET /api/customers?search={args.search} …")
        lat = await bench(
            search=args.search, iters=args.iters,
            base_url=args.base_url, tenant_slug=args.tenant_slug,
            auth_bearer=args.bearer,
        )
        print(summarize(lat))
    finally:
        if not args.keep:
            print("Cleaning up …")
            await cleanup()


if __name__ == "__main__":
    asyncio.run(main())
