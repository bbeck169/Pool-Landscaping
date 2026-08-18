"""Feb-2026 · Task C · ``services.review_scraper._fire_async`` safety.

Regression guard for the recurring "There is no current event loop in
thread 'asyncio_N'" cron crash. The safe pattern spins up a fresh
event loop for the fire so any ``asyncio.*`` calls inside the driven
coroutine see a running loop.

Isolated from the running app's Motor loop by using pure ``asyncio``
primitives (no db access). Runs in <0.1s.
"""
from __future__ import annotations

import asyncio
import threading

from services.review_scraper import _fire_async


def test_fire_async_returns_value_without_runtime_error():
    """Baseline — a trivial coroutine returns its value without
    raising ``RuntimeError``. This is exactly what would have happened
    to Google/Facebook/Yelp cron fires if the prior anti-pattern were
    still in place."""
    async def _co():
        return 42
    assert _fire_async(_co) == 42


def test_fire_async_survives_asyncio_current_loop_lookup_inside_coro():
    """The reason the prior pattern crashed: the coroutine (or motor
    inside it) called ``asyncio.get_event_loop()`` on a worker thread
    with no loop. The safe pattern MUST make that call succeed."""
    async def _co():
        # Both spellings must resolve to a live, running loop.
        loop_a = asyncio.get_event_loop()
        loop_b = asyncio.get_running_loop()
        assert loop_a is loop_b
        assert loop_a.is_running()
        return "ok"
    assert _fire_async(_co) == "ok"


def test_fire_async_propagates_coroutine_exceptions():
    """Errors inside the coroutine must surface to the caller — that
    matches the AsyncIOScheduler contract where a failing job is
    logged/skipped by the scheduler wrapper, not silently dropped."""
    class _Boom(RuntimeError):
        pass
    async def _co():
        raise _Boom("intended")
    try:
        _fire_async(_co)
    except _Boom as e:
        assert str(e) == "intended"
    else:
        raise AssertionError("_Boom was not propagated")


def test_fire_async_from_worker_thread():
    """Simulate APScheduler's ``ThreadPoolExecutor`` case — the exact
    scenario that used to raise ``No current event loop in thread
    'asyncio_N'``. Firing from a plain daemon thread must succeed."""
    result: dict = {}

    def _worker():
        async def _co():
            # This is the call the old code did that blew up.
            return asyncio.get_event_loop().is_running()
        try:
            result["value"] = _fire_async(_co)
        except Exception as e:  # pragma: no cover — regression trap
            result["error"] = repr(e)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=5)
    assert "error" not in result, result.get("error")
    assert result.get("value") is True


def test_fire_async_repeated_fires_do_not_leak_closed_loops():
    """Two back-to-back fires must both succeed (i.e. the helper
    doesn't leave a closed loop bound to the thread that the second
    call would trip over)."""
    async def _co(n):
        return n * 2
    assert _fire_async(lambda: _co(3)) == 6
    assert _fire_async(lambda: _co(4)) == 8
