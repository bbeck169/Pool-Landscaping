"""TD-offline-bundle-perf · Phase 2 Lane A · Feb-2026 — regression.

Guards the ``asyncio.gather`` refactor of the 9 post-jobs queries
inside ``routers.mobile_sync.mobile_offline_bundle``.

Phase 0 recon:
  memory/td_offline_bundle_perf_recon.md
Shipped Phase 2 Lane A commit:
  see TECH_DEBT.md entry

What this suite locks:

1. **Response shape byte-identity** — every top-level key the pre-
   refactor handler returned MUST still be in the dict, in the same
   insertion order, with the same types.
2. **Query-dependency audit** — ``db.jobs`` MUST stay sequential
   (its result feeds ``customer_ids`` + ``job_ids``).  The 9 helpers
   MUST be invoked under a single ``asyncio.gather``.
3. **Error propagation** — any helper raising MUST propagate out of
   the handler (``return_exceptions=False`` default).  Mobile
   clients continue to receive proper HTTP errors; no silently-
   degraded bundles.
4. **Latency floor** — concurrent execution MUST be strictly faster
   than the equivalent serial run.  Uses an in-process mock Mongo
   layer with a controlled per-query delay so the signal is
   deterministic and does not depend on real MongoDB.

Deliberate testing scope:
  * Unit-level — exercises the handler directly through a stubbed
    ``db`` so we don't need a running server + seeded tenant for
    byte-shape and timing locks.
  * Co-exists with ``tests/test_phase_o4_offline_bundle.py`` which
    hits the live server for integration coverage.
"""
from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from routers import mobile_sync as ms


# ─── Stubs ──────────────────────────────────────────────────────────────


class _FakeCursor:
    """Minimal ``find().sort().limit()`` + ``async for`` emulator."""
    def __init__(self, rows: List[Dict[str, Any]], delay: float = 0.0):
        self._rows = list(rows)
        self._delay = delay

    def sort(self, *a, **kw) -> "_FakeCursor":    # noqa: ARG002
        return self

    def limit(self, n: int) -> "_FakeCursor":
        self._rows = self._rows[:n]
        return self

    def __aiter__(self):
        async def _gen():
            # One delay per cursor materialisation — mirrors a real
            # Mongo round-trip (cursor open + batch fetch).  Keeps
            # the latency assertions deterministic.
            if self._delay:
                await asyncio.sleep(self._delay)
            for r in self._rows:
                yield r
        return _gen()


class _FakeCollection:
    def __init__(self, rows: List[Dict[str, Any]], delay: float = 0.0):
        self._rows = rows
        self._delay = delay

    def find(self, *a, **kw) -> _FakeCursor:    # noqa: ARG002
        return _FakeCursor(self._rows, self._delay)


class _FakeDB:
    """Just enough of ``config.db`` to satisfy the handler."""
    def __init__(self, delay: float = 0.0):
        self.jobs = _FakeCollection(
            [{"id": "job-1", "customer_id": "cust-1",
               "scheduled_date": "2026-02-10"}],
            delay,
        )
        self.customers = _FakeCollection(
            [{"id": "cust-1", "name": "Dan K.", "phone": "555",
               "address_line_1": "1 Main", "updated_at": "2026-02-01T00:00:00Z"}],
            delay,
        )
        self.service_reports = _FakeCollection([], delay)
        self.chemistry_test_types = _FakeCollection(
            [{"id": "ct-1", "updated_at": "2026-01-01T00:00:00Z"}], delay)
        self.chemicals_catalog = _FakeCollection(
            [{"id": "ch-1", "updated_at": "2026-01-01T00:00:00Z"}], delay)
        self.quotes = _FakeCollection(
            [{"id": "q-1", "doc_type": "quote",
               "updated_at": "2026-02-01T00:00:00Z"}], delay)
        self.income_categories = _FakeCollection(
            [{"id": "ic-1", "updated_at": "2026-01-01T00:00:00Z"}], delay)
        self.service_categories = _FakeCollection(
            [{"id": "sc-1", "updated_at": "2026-01-01T00:00:00Z"}], delay)
        self.pricebook_items = _FakeCollection(
            [{"id": "pb-1", "updated_at": "2026-02-01T00:00:00Z"}], delay)


_USER = {"id": "user-1", "technician_id": "tech-1"}
_TENANT = {"id": "tenant-1"}


# ─── Shape + byte-identity locks ────────────────────────────────────────


_EXPECTED_KEYS_IN_ORDER = [
    "jobs",
    "customers",
    "service_reports_in_progress",
    "chemistry_types",
    "chemicals_catalog",
    "invoices",
    "quotes",
    "income_categories",
    "service_categories",
    "pricebook_items",
    "versions",
    "caps",
    "offline_bundle_expires_at",
    "generated_at",
    "job_count",
    "cap_reached",
]


def test_response_keys_byte_identical() -> None:
    fake = _FakeDB(delay=0.0)
    with patch.object(ms, "db", fake):
        out = asyncio.run(ms.mobile_offline_bundle(
            tech_id="me", user=_USER, tenant=_TENANT))
    assert list(out.keys()) == _EXPECTED_KEYS_IN_ORDER, (
        "Lane A MUST preserve the dict insertion order byte-for-byte; "
        "the mobile client reads some keys positionally."
    )
    # Spot-check value types to catch accidental conversions.
    assert isinstance(out["jobs"], list)
    assert isinstance(out["customers"], list)
    assert isinstance(out["versions"], dict)
    assert isinstance(out["caps"], dict)
    assert isinstance(out["job_count"], int)
    assert isinstance(out["cap_reached"], bool)


def test_customers_mapping_preserved() -> None:
    """The handler's customer transform (``address_line_1 OR address``)
    must survive the refactor into ``_collect_bundle_customers``.
    """
    fake = _FakeDB(delay=0.0)
    # Replace customers to assert the mapping logic.
    fake.customers = _FakeCollection(
        [{"id": "cust-1", "name": "Dan K.", "phone": "555",
           "address_line_1": None, "address": "99 Fallback Ave",
           "updated_at": "2026-02-01T00:00:00Z"}],
        0.0,
    )
    # Also need the job to carry this customer id.
    fake.jobs = _FakeCollection(
        [{"id": "job-1", "customer_id": "cust-1",
           "scheduled_date": "2026-02-10"}],
        0.0,
    )
    with patch.object(ms, "db", fake):
        out = asyncio.run(ms.mobile_offline_bundle(
            tech_id="me", user=_USER, tenant=_TENANT))
    assert out["customers"] == [{
        "id": "cust-1", "name": "Dan K.", "phone": "555",
        "address": "99 Fallback Ave",
        "updated_at": "2026-02-01T00:00:00Z",
    }]


# ─── Gather pattern + dependency audit ──────────────────────────────────


def test_handler_source_uses_asyncio_gather() -> None:
    """Lock the refactor itself — the handler body MUST call
    ``asyncio.gather`` on the 9 collector helpers.  Guards against
    a silent regression back to the sequential ``async for`` shape.
    """
    src = inspect.getsource(ms.mobile_offline_bundle)
    assert "asyncio.gather(" in src
    assert "_collect_bundle_customers" in src
    assert "_collect_bundle_reports" in src
    assert "_collect_bundle_full_table" in src
    assert "_collect_bundle_sorted_capped" in src


def test_jobs_query_stays_sequential_before_gather() -> None:
    """Query-dependency audit — ``db.jobs.find`` MUST appear BEFORE
    the ``asyncio.gather`` call because its result produces
    ``customer_ids`` + ``job_ids`` consumed by the collectors.
    """
    src = inspect.getsource(ms.mobile_offline_bundle)
    jobs_find_pos = src.find("db.jobs.find(")
    gather_pos = src.find("asyncio.gather(")
    assert jobs_find_pos != -1, "db.jobs.find must still execute"
    assert gather_pos != -1, "asyncio.gather must be invoked"
    assert jobs_find_pos < gather_pos, (
        "Dependency audit failed — db.jobs query MUST execute BEFORE "
        "asyncio.gather; its result feeds customer_ids + job_ids."
    )


def test_gather_called_once_with_nine_awaitables() -> None:
    """Runtime proof that ``gather`` is invoked exactly once with
    nine coroutines (one per post-jobs collector).  Catches a
    future accidental split-gather or dropped collector.
    """
    captured: Dict[str, int] = {"calls": 0, "last_count": 0}
    real_gather = asyncio.gather

    def _counting_gather(*aws, **kw):    # noqa: ANN001, ANN002
        captured["calls"] += 1
        captured["last_count"] = len(aws)
        return real_gather(*aws, **kw)

    fake = _FakeDB(delay=0.0)
    with patch.object(ms, "db", fake), \
         patch.object(ms.asyncio, "gather", _counting_gather):
        asyncio.run(ms.mobile_offline_bundle(
            tech_id="me", user=_USER, tenant=_TENANT))
    assert captured["calls"] == 1
    assert captured["last_count"] == 9, (
        "Lane A ships 9 concurrent post-jobs queries; count mismatch "
        "indicates a dropped or added collector."
    )


# ─── Error propagation ──────────────────────────────────────────────────


def test_gather_propagates_first_exception() -> None:
    """If ANY helper raises, the exception MUST bubble out of the
    handler (matches ``return_exceptions=False`` default + pre-
    refactor behaviour where any ``async for`` raise bubbled up).
    """
    async def _boom(*a, **kw) -> List[Dict[str, Any]]:    # noqa: ARG001
        raise RuntimeError("simulated mongo failure")

    fake = _FakeDB(delay=0.0)
    with patch.object(ms, "db", fake), \
         patch.object(ms, "_collect_bundle_reports", _boom):
        with pytest.raises(RuntimeError, match="simulated mongo failure"):
            asyncio.run(ms.mobile_offline_bundle(
                tech_id="me", user=_USER, tenant=_TENANT))


# ─── Latency: concurrent < serial ───────────────────────────────────────


_PER_QUERY_DELAY_SEC = 0.08  # 80 ms per fake Mongo round-trip


def test_concurrent_execution_is_faster_than_serial_floor() -> None:
    """Deterministic latency proof — with a per-query delay of 80 ms
    applied to every stubbed collection, 10 serial queries would
    take ≥ 800 ms, whereas the Lane A gather should finish inside
    ~2× the per-query delay (one for jobs, one for the gather batch).
    Threshold is intentionally lax (<= 500 ms) so slow CI boxes
    don't flake while still catching a regression that would push
    latency back toward the serial floor.
    """
    fake = _FakeDB(delay=_PER_QUERY_DELAY_SEC)
    t0 = time.monotonic()
    with patch.object(ms, "db", fake):
        asyncio.run(ms.mobile_offline_bundle(
            tech_id="me", user=_USER, tenant=_TENANT))
    elapsed = time.monotonic() - t0
    # Serial floor would be ~0.8 s (10 × 0.08 s).  Concurrent should
    # land around 2 × 0.08 s = 0.16 s + overhead.
    assert elapsed < 0.50, (
        f"Lane A regression — concurrent run took {elapsed:.3f}s; "
        f"serial floor is {_PER_QUERY_DELAY_SEC * 10:.3f}s. "
        f"Expected ~2× {_PER_QUERY_DELAY_SEC}s + overhead."
    )


def test_concurrent_ratio_vs_serial_baseline() -> None:
    """Secondary measurement — compare the gathered-handler latency
    against a synthetic serial baseline run over the same fakes.
    Logs the ratio so a reviewer can eyeball the before/after
    without a live DB.  Serial baseline uses the same collectors
    called ``await``-wise one after another.
    """
    fake = _FakeDB(delay=_PER_QUERY_DELAY_SEC)
    # Concurrent (actual Lane A).
    t0 = time.monotonic()
    with patch.object(ms, "db", fake):
        asyncio.run(ms.mobile_offline_bundle(
            tech_id="me", user=_USER, tenant=_TENANT))
    concurrent = time.monotonic() - t0

    # Serial baseline — invoke the collectors directly, back to back.
    async def _serial() -> None:
        with patch.object(ms, "db", fake):
            await ms._collect_bundle_customers(["cust-1"], "tenant-1")
            await ms._collect_bundle_reports(["job-1"], "tenant-1")
            await ms._collect_bundle_full_table(fake.chemistry_test_types,
                                                 "tenant-1")
            await ms._collect_bundle_full_table(fake.chemicals_catalog,
                                                 "tenant-1")
            await ms._collect_bundle_sorted_capped(
                fake.quotes, {"tenant_id": "tenant-1"},
                ms.BUNDLE_MAX_INVOICES)
            await ms._collect_bundle_sorted_capped(
                fake.quotes, {"tenant_id": "tenant-1"},
                ms.BUNDLE_MAX_QUOTES)
            await ms._collect_bundle_full_table(fake.income_categories,
                                                 "tenant-1")
            await ms._collect_bundle_full_table(fake.service_categories,
                                                 "tenant-1")
            await ms._collect_bundle_sorted_capped(
                fake.pricebook_items, {"tenant_id": "tenant-1"},
                ms.BUNDLE_MAX_PRICEBOOK_ITEMS)

    t0 = time.monotonic()
    asyncio.run(_serial())
    serial = time.monotonic() - t0

    speedup = serial / concurrent if concurrent else float("inf")
    # Primary assertion — concurrent MUST be faster.
    assert concurrent < serial
    # Secondary — observable speedup; must be at least 2x on 9 parallel
    # helpers.  Mobile prod expectation per recon doc: ~2.8 s → ~500 ms
    # (≈ 5.6×); this fake-DB floor is a weaker signal but still catches
    # a regression that silently serialised the gather.
    assert speedup >= 2.0, (
        f"Lane A speedup regression — concurrent={concurrent:.3f}s, "
        f"serial={serial:.3f}s, ratio={speedup:.2f}× (want ≥ 2×)."
    )
