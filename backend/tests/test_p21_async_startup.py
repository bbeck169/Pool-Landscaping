"""Phase P21 · Feb-2026 — Async startup lifespan tests.

Locks the following contracts of the new ``lifespan`` context manager:

  1. Schema migrations run SYNC before yield — the health endpoint
     reports ``init.schema_migrations == "done"`` the instant the
     server begins serving. The chained background task is scheduled
     (present on ``app.state.bg_tasks``).
  2. After the background task completes: ``init.seed.status`` and
     ``init.integrity_scan.status`` both flip to ``done``.
  3. SEED failure → ONE retry after ``P21_SEED_RETRY_DELAY_SECS``
     (monkey-patched to a tiny value) → succeeds on the second
     attempt → final state ``seed.status == "done"`` with
     ``retry_count == 1``.
  4. SEED failure on BOTH attempts → final state ``seed.status ==
     "error"``, ``retry_count == 1``, error string populated, and the
     server still binds + responds ``200`` on ``/api/health``.
  5. INTEGRITY_SCAN starts AFTER _do_seed completes (ordered via
     chained-``await`` — the runner ``_seed_then_scan`` guarantees
     this even under a preemption-free scheduler).

Each test drives the ASGI lifespan protocol against ``server.app``
directly (no ``pytest-asyncio`` dep) — same idiom the existing F7
loop-fixture tests use via ``asyncio.run``. Every test monkey-patches
the two module-level entry points ``_do_seed`` / ``_do_integrity_scan``
on ``server`` so failure modes + timing can be injected without
touching the ~500-line pre-yield boot sequence.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport


# ── Helpers ────────────────────────────────────────────────────────


class _LifespanDriver:
    """Minimal ASGI lifespan-protocol driver — sends ``lifespan.startup``
    + ``lifespan.shutdown`` messages to the app so ``app.state.init``
    is populated end-to-end.  We can't use Starlette's ``TestClient``
    here — it only triggers lifespan on-enter/exit and we need to
    inspect state DURING the yielded phase."""

    def __init__(self, app):
        self.app = app
        self._startup_done = asyncio.Event()
        self._shutdown_done = asyncio.Event()
        self._receive_q: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def _lifespan_loop(self):
        async def _receive():
            return await self._receive_q.get()

        async def _send(msg):
            t = msg.get("type", "")
            if t in ("lifespan.startup.complete",
                     "lifespan.startup.failed"):
                self._startup_done.set()
            elif t in ("lifespan.shutdown.complete",
                       "lifespan.shutdown.failed"):
                self._shutdown_done.set()

        await self.app({"type": "lifespan"}, _receive, _send)

    async def startup(self):
        self._task = asyncio.create_task(self._lifespan_loop())
        await self._receive_q.put({"type": "lifespan.startup"})
        await self._startup_done.wait()

    async def shutdown(self):
        await self._receive_q.put({"type": "lifespan.shutdown"})
        await self._shutdown_done.wait()
        if self._task:
            await self._task


def _load_server():
    """Import the ``server`` module fresh + stub the heavy pre-yield
    boot sequence so tests take milliseconds, not minutes. Returns the
    module handle."""
    if "server" in sys.modules:
        srv = sys.modules["server"]
    else:
        srv = importlib.import_module("server")
    # Reset per-test app.state fields the lifespan (re)populates.
    if hasattr(srv.app.state, "init"):
        delattr(srv.app.state, "init")
    if hasattr(srv.app.state, "bg_tasks"):
        delattr(srv.app.state, "bg_tasks")

    async def _noop_boot():
        return None

    async def _noop_shutdown():
        return None

    srv._run_boot_sequence = _noop_boot
    srv._p21_shutdown_sequence = _noop_shutdown
    # Shrink retry sleep so failure-path tests are fast.
    srv.P21_SEED_RETRY_DELAY_SECS = 0.01
    return srv


def _run(coro):
    """Standardized async runner — matches the ``_f7_loop_fixture``
    pattern used by other backend tests (no ``pytest-asyncio`` dep)."""
    return asyncio.run(coro)


# ── 1) Sync migrations complete before yield · BG tasks scheduled ─


def test_p21_lifespan_stamps_schema_migrations_before_yield():
    srv = _load_server()
    call_gate = asyncio.Event()

    async def _go():
        seed_started = asyncio.Event()

        async def _slow_seed():
            seed_started.set()
            await call_gate.wait()

        async def _slow_scan():
            await call_gate.wait()

        srv._do_seed = _slow_seed
        srv._do_integrity_scan = _slow_scan

        driver = _LifespanDriver(srv.app)
        await driver.startup()

        # State stamped, BG task scheduled.
        assert srv.app.state.init.schema_migrations_done_at is not None
        assert len(srv.app.state.bg_tasks) == 1
        assert not srv.app.state.bg_tasks[0].done()

        # /api/health surfaces the shape.
        async with AsyncClient(
            transport=ASGITransport(app=srv.app), base_url="http://test",
        ) as client:
            r = await client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["init"]["schema_migrations"] == "done"

        # Seed should be RUNNING by now.
        await asyncio.wait_for(seed_started.wait(), timeout=2.0)
        assert srv.app.state.init.tasks["seed"].status.value == "running"

        # Unblock + shutdown.
        call_gate.set()
        await driver.shutdown()

    _run(_go())


# ── 2) After BG tasks complete: both DONE ──────────────────────────


def test_p21_seed_and_integrity_scan_complete_to_done():
    srv = _load_server()

    async def _go():
        seed_called = {"n": 0}
        scan_called = {"n": 0}

        async def _seed_ok():
            seed_called["n"] += 1

        async def _scan_ok():
            scan_called["n"] += 1

        srv._do_seed = _seed_ok
        srv._do_integrity_scan = _scan_ok

        driver = _LifespanDriver(srv.app)
        await driver.startup()
        # Chain runs SEED → SCAN inside a single task.
        await asyncio.gather(
            *srv.app.state.bg_tasks, return_exceptions=True,
        )

        st = srv.app.state.init
        assert st.tasks["seed"].status.value == "done"
        assert st.tasks["integrity_scan"].status.value == "done"
        assert seed_called["n"] == 1
        assert scan_called["n"] == 1

        async with AsyncClient(
            transport=ASGITransport(app=srv.app), base_url="http://test",
        ) as client:
            r = await client.get("/api/health")
        body = r.json()
        assert body["init"]["seed"]["status"] == "done"
        assert body["init"]["seed"]["retry_count"] == 0
        assert body["init"]["integrity_scan"]["status"] == "done"

        await driver.shutdown()

    _run(_go())


# ── 3) Seed raises on first attempt, succeeds on retry ─────────────


def test_p21_seed_retries_once_on_failure():
    srv = _load_server()

    async def _go():
        calls = {"n": 0}

        async def _flaky_seed():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom-first")
            return

        async def _scan_ok():
            return

        srv._do_seed = _flaky_seed
        srv._do_integrity_scan = _scan_ok

        driver = _LifespanDriver(srv.app)
        await driver.startup()
        await asyncio.gather(
            *srv.app.state.bg_tasks, return_exceptions=True,
        )

        st = srv.app.state.init
        assert calls["n"] == 2
        assert st.tasks["seed"].status.value == "done"
        assert st.tasks["seed"].retry_count == 1
        # Chain continued to scan.
        assert st.tasks["integrity_scan"].status.value == "done"

        await driver.shutdown()

    _run(_go())


# ── 4) Seed fails both attempts — final ERROR + server responsive ─


def test_p21_seed_persistent_failure_leaves_error_state_server_up():
    srv = _load_server()

    async def _go():
        calls = {"n": 0}

        async def _always_fails():
            calls["n"] += 1
            raise RuntimeError(f"boom-{calls['n']}")

        async def _scan_ok():
            return

        srv._do_seed = _always_fails
        srv._do_integrity_scan = _scan_ok

        driver = _LifespanDriver(srv.app)
        await driver.startup()
        await asyncio.gather(
            *srv.app.state.bg_tasks, return_exceptions=True,
        )

        st = srv.app.state.init
        assert calls["n"] == 2   # first + one retry
        seed_rec = st.tasks["seed"]
        assert seed_rec.status.value == "error"
        assert seed_rec.retry_count == 1
        assert seed_rec.error and "boom" in seed_rec.error
        # Chain still ran the scan (seed failure doesn't block scan).
        assert st.tasks["integrity_scan"].status.value == "done"

        # Server still returns 200 on /api/health — SEED error does
        # NOT downgrade the top-level status.
        async with AsyncClient(
            transport=ASGITransport(app=srv.app), base_url="http://test",
        ) as client:
            r = await client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["init"]["seed"]["status"] == "error"
        assert body["init"]["seed"]["retry_count"] == 1

        await driver.shutdown()

    _run(_go())


# ── 5) INTEGRITY_SCAN starts AFTER _do_seed completes ──────────────


def test_p21_integrity_scan_starts_after_seed_completes():
    srv = _load_server()

    async def _go():
        order: list[str] = []

        async def _seed_slow():
            order.append("seed:start")
            # Real await so the loop can schedule other tasks.
            await asyncio.sleep(0.05)
            order.append("seed:end")

        async def _scan_after():
            order.append("scan:start")
            assert "seed:end" in order, (
                f"P21 chain violated — scan started before seed "
                f"finished: {order}"
            )
            order.append("scan:end")

        srv._do_seed = _seed_slow
        srv._do_integrity_scan = _scan_after

        driver = _LifespanDriver(srv.app)
        await driver.startup()
        await asyncio.gather(
            *srv.app.state.bg_tasks, return_exceptions=True,
        )

        assert order == [
            "seed:start", "seed:end", "scan:start", "scan:end",
        ], f"P21 chain order mismatch: {order}"

        await driver.shutdown()

    _run(_go())


# ── 6) Guardrail — no @app.on_event("startup"/"shutdown") decorators ─


def test_p21_source_lint_no_on_event_decorators():
    """Source-level guardrail: no ``@app.on_event("startup")`` or
    ``@app.on_event("shutdown")`` decorators remain in ``server.py``.
    Comment/docstring mentions are allowed (they document the pre-P21
    shape); an actual decorator would be a regression."""
    src = Path(__file__).resolve().parents[1] / "server.py"
    body = src.read_text(encoding="utf-8")
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("@app.on_event("):
            raise AssertionError(
                f"P21 regression: found @app.on_event decorator: {line!r}"
            )
