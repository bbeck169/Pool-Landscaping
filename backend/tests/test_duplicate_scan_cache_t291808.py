"""Ticket 291808 · duplicate scans must not stall the server.

Covers the single-flight / TTL / invalidate behaviour of
``services.customers.duplicate_cache`` and that the CPU-bound
duplicate detection runs off the event loop.  No server / DB needed.
"""
import asyncio
import random
import string
import time

from services.customers import duplicate_cache as dc
from services.customers.duplicate_detection import detect_duplicates


def _reset():
    dc._results.clear()
    dc._inflight.clear()
    dc._generation.clear()


def test_concurrent_callers_share_one_scan():
    _reset()
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return ["groups"]

    async def main():
        return await asyncio.gather(*[
            dc.cached_scan("k", "t1", compute) for _ in range(6)
        ])

    out = asyncio.run(main())
    assert calls == 1
    assert all(o == ["groups"] for o in out)


def test_result_is_cached_until_ttl_expires(monkeypatch):
    _reset()
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        return calls

    async def main():
        a = await dc.cached_scan("k", "t1", compute)
        b = await dc.cached_scan("k", "t1", compute)
        monkeypatch.setattr(dc, "_TTL_SECONDS", 0.0)
        c = await dc.cached_scan("k", "t1", compute)
        return a, b, c

    a, b, c = asyncio.run(main())
    assert (a, b) == (1, 1)
    assert c == 2


def test_tenants_and_kinds_are_isolated():
    _reset()

    async def main():
        async def mk(v):
            return v
        a = await dc.cached_scan("k", "t1", lambda: mk("a"))
        b = await dc.cached_scan("k", "t2", lambda: mk("b"))
        c = await dc.cached_scan("other", "t1", lambda: mk("c"))
        return a, b, c

    assert asyncio.run(main()) == ("a", "b", "c")


def test_invalidate_drops_cache_and_does_not_cache_inflight_stale():
    _reset()
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return calls

    async def main():
        first = await dc.cached_scan("k", "t1", compute)
        dc.invalidate_tenant("t1")
        second = await dc.cached_scan("k", "t1", compute)
        # merge lands while a scan is running: that scan's result is
        # handed to its waiters but must not be cached.
        dc.invalidate_tenant("t1")
        pending = asyncio.ensure_future(dc.cached_scan("k", "t1", compute))
        await asyncio.sleep(0.01)
        dc.invalidate_tenant("t1")
        stale = await pending
        fresh = await dc.cached_scan("k", "t1", compute)
        return first, second, stale, fresh

    first, second, stale, fresh = asyncio.run(main())
    assert (first, second) == (1, 2)
    assert stale == 3   # waiter still receives the in-flight result
    assert fresh == 4   # ...but it was not cached, so this recomputes


def test_cancelled_waiter_does_not_kill_the_shared_scan():
    _reset()
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.1)
        return "done"

    async def main():
        t1 = asyncio.ensure_future(dc.cached_scan("k", "t1", compute))
        t2 = asyncio.ensure_future(dc.cached_scan("k", "t1", compute))
        await asyncio.sleep(0.02)
        t1.cancel()  # e.g. the client timed out and disconnected
        return await t2

    assert asyncio.run(main()) == "done"
    assert calls == 1


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __aiter__(self):
        async def gen():
            for r in self._rows:
                yield r
        return gen()


class _FakeCustomers:
    def __init__(self, rows):
        self._rows = rows

    def find(self, *_a, **_k):
        return _FakeCursor(self._rows)


class _FakeDb:
    def __init__(self, rows):
        self.customers = _FakeCustomers(rows)


def _rows(n, seed=7):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        name = "".join(rnd.choice(string.ascii_lowercase) for _ in range(12))
        out.append({"id": f"c{i}", "name": name, "email": f"{name}@x.test",
                    "phone": f"555{i:07d}", "is_active": True})
    return out


def test_fuzzy_duplicates_still_found():
    rows = _rows(20)
    rows.append({"id": "a", "name": "Kevin Aronson", "email": "k1@x.test",
                 "phone": "6025550001", "is_active": True})
    rows.append({"id": "b", "name": "Kevin Aronsen", "email": "k2@x.test",
                 "phone": "6025550002", "is_active": True})
    groups = asyncio.run(detect_duplicates(db=_FakeDb(rows), tenant_id="t"))
    assert len(groups) == 1
    assert {c.id for c in groups[0].customers} == {"a", "b"}
    assert "name_fuzzy" in groups[0].match_reasons


def test_detection_does_not_block_the_event_loop():
    rows = _rows(600)

    async def main():
        worst = 0.0
        done = False

        async def ticker():
            nonlocal worst
            last = time.monotonic()
            while not done:
                await asyncio.sleep(0.01)
                now = time.monotonic()
                worst = max(worst, now - last - 0.01)
                last = now

        t = asyncio.ensure_future(ticker())
        t0 = time.monotonic()
        await detect_duplicates(db=_FakeDb(rows), tenant_id="t")
        took = time.monotonic() - t0
        done = True
        await t
        return worst, took

    worst, took = asyncio.run(main())
    # Run inline, the scan would hold the loop for its whole duration
    # (``took``).  Off-loop, the loop is only delayed by GIL slices.
    assert worst < max(0.25, took / 4), (worst, took)
