"""
Feb-2026 · Diag-Timeout Task 1 — Customers search P95 pytest guard.

CI-scale benchmark: seeds 2 000 synthetic customers into the demo
aquaterra tenant, hits ``GET /api/customers?search=lynn&page=1&
page_size=50`` 10 times through the in-process ASGI shim, and
asserts:

  * P50 < 250 ms
  * P95 < 500 ms (target from the pivot spec)
  * max < 1 000 ms (guard against a single 30 s spike hiding in the
    average)

Every seeded row is prefixed with ``TEST-bench-cust-`` so the
session-wide cleanup autouse fixture in ``conftest.py`` deletes it
regardless of whether an assertion tripped mid-run.

The standalone script version ``tests/bench_customers_search.py``
still exists for one-off preview / prod runs against an external
DB; this pytest is the CI-loop replacement so a regression to the
six-field OR shape is caught before it lands.
"""
from __future__ import annotations

import statistics
import time
import uuid
from pathlib import Path
from typing import List

import pytest
from dotenv import dotenv_values

from tests._phase34_http_shim import http

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

_ADMIN = {"email": "super@aquaterra.com", "password": "password123"}
_ADMIN_FALLBACK = {"email": "admin@aquaterra.com", "password": "password123"}

_N_CUSTOMERS = 2000
_LYNN_RATIO = 20  # every 20th row starts with "Lynn"
_ITERS = 10
_P50_BUDGET_MS = 250
_P95_BUDGET_MS = 500
_MAX_BUDGET_MS = 1000

_LAST_NAMES = ("Carson", "Reyes", "Nguyen", "Patel", "Kim", "Baram",
                 "Blake", "Mahoney")
_OTHER_FIRST = ("Alex", "Sam", "Jordan", "Casey", "Riley", "Taylor")


def _login() -> str:
    for creds in (_ADMIN, _ADMIN_FALLBACK):
        r = http.post(f"{API}/auth/login", json=creds, timeout=30)
        if r.status_code == 200:
            return r.json()["access_token"]
    pytest.skip("no admin login available in this env")


def _auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}",
            "X-Tenant-Slug": "aquaterra"}


def _seed_directly(tenant_id: str, marker: str, n: int) -> None:
    """Bulk-insert straight into Mongo. Endpoint-level ``POST
    /customers`` is O(seconds) per row and would take 30+ min for
    2 000 docs; direct insert stays under 5 s and still exercises
    the runtime search path because it applies the haystack the
    same way the real create hook does."""
    import asyncio
    from config import db
    from services.customers_search_haystack import apply_haystack

    docs = []
    for i in range(n):
        first = "Lynn" if (i % _LYNN_RATIO == 0) else _OTHER_FIRST[i % 6]
        last = _LAST_NAMES[i % len(_LAST_NAMES)]
        d = {
            "id": f"{marker}-{i:06d}",
            "tenant_id": tenant_id,
            "name": f"{first} {last} {marker[-4:]}{i}",
            "first_name": first,
            "last_name": last,
            "email": f"{first.lower()}.{last.lower()}.{marker}{i}@example.com",
            "phone": f"+1602{i:07d}",
            "address": f"{i} Bench St, Peoria, AZ",
            "is_active": True,
            "is_muted": False,
            "waitlisted": False,
            "created_at": "2026-02-01T00:00:00+00:00",
        }
        apply_haystack(d)
        docs.append(d)

    async def _do():
        # Idempotency guard — remove any prior run's rows first.
        await db.customers.delete_many({
            "tenant_id": tenant_id,
            "id": {"$regex": f"^{marker}"},
        })
        # Batch of 500 rows per insert_many.
        for chunk_start in range(0, n, 500):
            await db.customers.insert_many(docs[chunk_start: chunk_start + 500])
        # Ensure the compound index is in place; the boot task is
        # async so a fresh test pod might not have raced to
        # completion yet.
        from services.customers_search_haystack import ensure_haystack_indexes
        await ensure_haystack_indexes(db)

    from tests._phase34_asyncio import batch_safe_run
    batch_safe_run(_do())


def _cleanup(tenant_id: str, marker: str) -> None:
    import asyncio
    from config import db
    from tests._phase34_asyncio import batch_safe_run

    async def _do():
        await db.customers.delete_many({
            "tenant_id": tenant_id,
            "id": {"$regex": f"^{marker}"},
        })

    batch_safe_run(_do())


def _resolve_aquaterra_id() -> str:
    """Look up the demo tenant's id (the auth login response payload
    used to carry it but the shape has drifted)."""
    import asyncio
    from config import db
    from tests._phase34_asyncio import batch_safe_run

    async def _do():
        row = await db.tenants.find_one({"slug": "aquaterra"})
        return (row or {}).get("id") or ""

    return batch_safe_run(_do())


@pytest.mark.perf
def test_customer_search_p95_under_500ms():
    tok = _login()
    tenant_id = _resolve_aquaterra_id()
    if not tenant_id:
        pytest.skip("aquaterra tenant not found in this env")

    marker = f"TEST-bench-cust-{uuid.uuid4().hex[:8]}"
    _seed_directly(tenant_id, marker, _N_CUSTOMERS)
    try:
        # Warm-up hit (index cache + hydration paths) — not counted.
        r = http.get(f"{API}/customers", params={
            "search": "lynn", "page": 1, "page_size": 50,
        }, headers=_auth(tok), timeout=30)
        assert r.status_code == 200, r.text
        # Should return at least one Lynn row.
        body = r.json()
        rows = body.get("items") if isinstance(body, dict) else body
        assert rows and len(rows) > 0, "warm-up returned no rows"

        latencies_ms: List[float] = []
        for _ in range(_ITERS):
            t0 = time.perf_counter()
            r = http.get(f"{API}/customers", params={
                "search": "lynn", "page": 1, "page_size": 50,
            }, headers=_auth(tok), timeout=30)
            latencies_ms.append((time.perf_counter() - t0) * 1000)
            assert r.status_code == 200, r.text

        latencies_ms.sort()
        p50 = latencies_ms[len(latencies_ms) // 2]
        p95_idx = max(0, int(round(len(latencies_ms) * 0.95)) - 1)
        p95 = latencies_ms[p95_idx]
        mx = latencies_ms[-1]

        print(f"\n[bench] N={_N_CUSTOMERS} iters={_ITERS} "
              f"p50={p50:.0f}ms p95={p95:.0f}ms max={mx:.0f}ms "
              f"all={[int(x) for x in latencies_ms]}")

        assert p50 < _P50_BUDGET_MS, (
            f"P50 {p50:.0f}ms exceeded {_P50_BUDGET_MS}ms budget"
        )
        assert p95 < _P95_BUDGET_MS, (
            f"P95 {p95:.0f}ms exceeded {_P95_BUDGET_MS}ms budget"
        )
        assert mx < _MAX_BUDGET_MS, (
            f"max {mx:.0f}ms exceeded {_MAX_BUDGET_MS}ms budget"
        )
    finally:
        _cleanup(tenant_id, marker)
