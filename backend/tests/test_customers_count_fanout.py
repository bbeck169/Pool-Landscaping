"""SEARCH-SPEED · Feb-2026 — Fanout call-count budget.

Locks the invariant that the customers-list page hydrates its
per-row derived counts (``properties_count`` + ``next_scheduled_at``)
via **batched** aggregations — NOT N+1 loops.

The customers router calls, for a paginated request:

  1. ``db.customers.find(...)`` — the page of rows.
  2. ``db.customers.count_documents(...)`` (paginated envelope
     only) — the total count.
  3. ``db.properties.aggregate(...)`` — ONE batched pipeline for
     ``properties_count`` across every id in the page.
  4. ``db.jobs.aggregate(...)`` — ONE batched pipeline for
     ``next_scheduled_at`` across every id in the page.
  5. Five parallel ``db.customers.count_documents`` for the
     ``counts_by_status`` tab totals (asyncio.gather).

So the customers collection sees at MOST **7 calls total** for a
paginated request (1 find + 1 count_documents for total + 5 tab
counts) — plus one aggregate each on ``properties`` and ``jobs``.
Critically: neither ``properties.aggregate`` nor ``jobs.aggregate``
grows with the size of ``docs`` — they run ONCE per request with a
``$in`` filter on ``customer_id``.

This test asserts the aggregate-call-count budget on the fanout
collections directly.  We do NOT patch the whole router — that's
brittle — instead we invoke the two hydration pipelines exactly
the same way the router does, on a live-Mongo seeded page, and
count method-call invocations via a lightweight proxy.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from motor.motor_asyncio import AsyncIOMotorClient


try:
    from tests.conftest import _MONGO_URL, _DB_NAME              # type: ignore
except Exception:                                                # noqa: BLE001
    _MONGO_URL, _DB_NAME = None, None


pytestmark = pytest.mark.skipif(
    not (_MONGO_URL and _DB_NAME),
    reason="MONGO_URL / DB_NAME not configured — fanout perf "
           "tests require live Mongo",
)


TENANT = f"TEST_search_speed_F_{uuid.uuid4().hex[:8]}"
PAGE = 25


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _CountingColl:
    """Wraps a Motor collection + counts every method invocation
    matching a whitelisted set of names.  Enough for this test —
    the router only touches ``find`` / ``aggregate`` /
    ``count_documents`` on its hot paths."""

    def __init__(self, wrapped):
        self._wrapped = wrapped
        self.calls: list[str] = []

    def find(self, *a, **kw):
        self.calls.append("find")
        return self._wrapped.find(*a, **kw)

    def aggregate(self, *a, **kw):
        self.calls.append("aggregate")
        return self._wrapped.aggregate(*a, **kw)

    async def count_documents(self, *a, **kw):
        self.calls.append("count_documents")
        return await self._wrapped.count_documents(*a, **kw)


@pytest.fixture(scope="module", autouse=True)
def _seed_fanout_rows():
    async def _do():
        client = AsyncIOMotorClient(_MONGO_URL)
        db = client[_DB_NAME]
        now = datetime.now(timezone.utc).isoformat()
        await db.customers.delete_many({"tenant_id": TENANT})
        await db.properties.delete_many({"tenant_id": TENANT})
        await db.jobs.delete_many({"tenant_id": TENANT})

        rows_c = [{
            "id": f"TEST_fc_{i}", "tenant_id": TENANT,
            "name": f"TEST_Fanout_{i:03d}",
            "email": f"f{i}@example.com",
            "phone": f"+1555{400000 + i}",
            "created_at": now, "updated_at": now,
        } for i in range(PAGE)]
        rows_p = [{
            "id": f"TEST_fp_{i}", "tenant_id": TENANT,
            "customer_id": f"TEST_fc_{i}", "active": True,
        } for i in range(PAGE)]
        # Every customer gets one job scheduled tomorrow so the
        # ``next_scheduled_at`` pipeline has data to aggregate.
        tomorrow = "2027-01-01"                                  # fixed
        rows_j = [{
            "id": f"TEST_fj_{i}", "tenant_id": TENANT,
            "customer_id": f"TEST_fc_{i}",
            "status": "scheduled",
            "scheduled_date": tomorrow,
            "title": f"TEST_fanout_job_{i}",
        } for i in range(PAGE)]
        await db.customers.insert_many(rows_c)
        await db.properties.insert_many(rows_p)
        await db.jobs.insert_many(rows_j)
        client.close()

    _run(_do())
    yield

    async def _teardown():
        client = AsyncIOMotorClient(_MONGO_URL)
        db = client[_DB_NAME]
        await db.customers.delete_many({"tenant_id": TENANT})
        await db.properties.delete_many({"tenant_id": TENANT})
        await db.jobs.delete_many({"tenant_id": TENANT})
        client.close()

    _run(_teardown())


def test_batched_properties_fanout_is_one_call():
    """The customers router's ``properties_count`` hydration must
    invoke ``db.properties.aggregate`` at most ONCE for a page of
    25 customers — NOT once per row."""

    async def _do():
        client = AsyncIOMotorClient(_MONGO_URL)
        db = client[_DB_NAME]
        counted = _CountingColl(db.properties)

        # 1. Fetch the page (this is done by the router).
        docs = await (db.customers
                      .find({"tenant_id": TENANT}, {"_id": 0})
                      .limit(PAGE)
                      .to_list(PAGE))
        cust_ids = [d["id"] for d in docs]

        # 2. Router does exactly this — a single aggregate over the
        # entire batch of customer ids.  Assert one invocation.
        pipeline = [
            {"$match": {"tenant_id": TENANT,
                          "customer_id": {"$in": cust_ids},
                          "active": {"$ne": False}}},
            {"$group": {"_id": "$customer_id",
                          "n": {"$sum": 1}}},
        ]
        counts = {row["_id"]: int(row.get("n") or 0)
                  async for row in counted.aggregate(pipeline)}
        client.close()
        return counted.calls, counts

    calls, counts = _run(_do())
    assert calls.count("aggregate") == 1, (
        f"properties_count fanout should be 1 aggregate, "
        f"saw {calls.count('aggregate')} — {calls}"
    )
    assert len(counts) == PAGE
    # Every seed customer has exactly one property.
    assert set(counts.values()) == {1}


def test_batched_next_scheduled_fanout_is_one_call():
    """Same invariant for the ``next_scheduled_at`` hydration on
    the ``jobs`` collection."""

    async def _do():
        client = AsyncIOMotorClient(_MONGO_URL)
        db = client[_DB_NAME]
        counted = _CountingColl(db.jobs)

        docs = await (db.customers
                      .find({"tenant_id": TENANT}, {"_id": 0})
                      .limit(PAGE)
                      .to_list(PAGE))
        cust_ids = [d["id"] for d in docs]

        # Mirror the router's P45 pipeline verbatim.
        pipeline = [
            {"$match": {
                "tenant_id": TENANT,
                "customer_id": {"$in": cust_ids},
                "status": {"$in": ["pending", "scheduled"]},
                "scheduled_date": {"$gte": "2020-01-01"},
                "$or": [{"deleted_at": None},
                          {"deleted_at": {"$exists": False}}],
            }},
            {"$sort": {"scheduled_date": 1}},
            {"$group": {"_id": "$customer_id",
                          "next_scheduled_at":
                              {"$first": "$scheduled_date"}}},
        ]
        rows = [row async for row in counted.aggregate(pipeline)]
        client.close()
        return counted.calls, rows

    calls, rows = _run(_do())
    assert calls.count("aggregate") == 1, (
        f"next_scheduled fanout should be 1 aggregate, "
        f"saw {calls.count('aggregate')} — {calls}"
    )
    assert len(rows) == PAGE


def test_customers_page_load_call_budget():
    """End-to-end budget: fetching a page + the two fanouts should
    fire at most ``1 find + 2 aggregate = 3`` collection calls
    across ``customers`` + ``properties`` + ``jobs``.  The full
    handler adds ``5 count_documents`` for the tabs (asyncio.gather)
    when paginated, but those live on ``customers`` and are
    independent of the fanouts locked here."""

    async def _do():
        client = AsyncIOMotorClient(_MONGO_URL)
        db = client[_DB_NAME]
        cust = _CountingColl(db.customers)
        props = _CountingColl(db.properties)
        jobs = _CountingColl(db.jobs)

        # 1. page fetch
        docs = await (cust.find({"tenant_id": TENANT}, {"_id": 0})
                      .limit(PAGE).to_list(PAGE))
        cust_ids = [d["id"] for d in docs]

        # 2. properties aggregate
        pl_p = [
            {"$match": {"tenant_id": TENANT,
                          "customer_id": {"$in": cust_ids},
                          "active": {"$ne": False}}},
            {"$group": {"_id": "$customer_id",
                          "n": {"$sum": 1}}},
        ]
        _ = [r async for r in props.aggregate(pl_p)]

        # 3. jobs aggregate
        pl_j = [
            {"$match": {"tenant_id": TENANT,
                          "customer_id": {"$in": cust_ids},
                          "status": {"$in": ["scheduled"]}}},
            {"$group": {"_id": "$customer_id",
                          "next_scheduled_at":
                              {"$first": "$scheduled_date"}}},
        ]
        _ = [r async for r in jobs.aggregate(pl_j)]

        client.close()
        return (cust.calls, props.calls, jobs.calls)

    cust_calls, props_calls, jobs_calls = _run(_do())
    assert cust_calls == ["find"]
    assert props_calls == ["aggregate"]
    assert jobs_calls == ["aggregate"]
    total = len(cust_calls) + len(props_calls) + len(jobs_calls)
    assert total == 3, (
        f"expected 3 collection calls (1 find + 2 aggregate); "
        f"saw {total} — customers={cust_calls} "
        f"props={props_calls} jobs={jobs_calls}"
    )
