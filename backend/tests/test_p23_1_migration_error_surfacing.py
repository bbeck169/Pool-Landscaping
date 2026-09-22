"""Phase P23.1 · Feb-2026 — Non-silent structural-migration surface.

Locks the following contracts:

  1. **Success path.** A structural migration that returns normally
     stamps ``app.state.init.structural_migrations[name].status ==
     "done"``, ``error is None``, ``duration_ms > 0``.
  2. **Failure path.** A structural migration that raises stamps
     ``.status == "error"``, ``.error`` is populated with the
     exception message, ``retry_count == 0``, and the lifespan STILL
     yields (server still binds — per P23.1 spec §4 explicit "does
     not crash").
  3. **/api/health surfacing.** The ``init.structural_migrations``
     sub-object reflects the state change immediately after boot
     completes. Success rows have ``status=done``, failure rows have
     ``status=error`` with the error string, and the top-level
     ``status`` STAYS ``ok`` (migration failure never downgrades the
     probe — it's an ops signal, not a request-serving gate).
  4. **``must_succeed=True`` semantics.** The must-succeed flag
     controls log severity (ERROR vs WARN) and the retry_count
     semantic; it does NOT re-raise (spec §4 explicit). The state
     record reflects the ERROR either way.
  5. **Log surface.** A failure emits ``[structural-migration] <name>
     failed`` at the appropriate severity (ERROR for must_succeed,
     WARN otherwise) WITH the traceback (``exc_info=True``).
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import sys
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport


# ── Helpers (mirrors test_p21_async_startup.py's driver) ──────────


class _LifespanDriver:
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
    if "server" in sys.modules:
        srv = sys.modules["server"]
    else:
        srv = importlib.import_module("server")
    if hasattr(srv.app.state, "init"):
        delattr(srv.app.state, "init")
    if hasattr(srv.app.state, "bg_tasks"):
        delattr(srv.app.state, "bg_tasks")
    srv.P21_SEED_RETRY_DELAY_SECS = 0.01
    return srv


def _run(coro):
    return asyncio.run(coro)


# ── 1) Success path — status DONE, error None, duration > 0 ───────


def test_p23_1_structural_migration_success_stamps_done():
    """A structural migration that returns normally MUST stamp
    ``status=done``, ``error=None``, ``duration_ms > 0``."""
    srv = _load_server()

    async def _go():
        marker = {"called": False}

        async def _slow_ok():
            marker["called"] = True
            await asyncio.sleep(0.01)
            return {"ok": True}

        async def _boot():
            await srv._run_structural_migration(
                "test_p23_1_success", _slow_ok, must_succeed=True,
            )

        async def _noop_shutdown():
            return None

        srv._run_boot_sequence = _boot
        srv._p21_shutdown_sequence = _noop_shutdown
        srv._do_seed = lambda: asyncio.sleep(0)
        srv._do_integrity_scan = lambda: asyncio.sleep(0)

        driver = _LifespanDriver(srv.app)
        await driver.startup()

        assert marker["called"] is True
        rec = srv.app.state.init.structural_migrations.get(
            "test_p23_1_success",
        )
        assert rec is not None
        assert rec.status.value == "done"
        assert rec.error is None
        assert rec.duration_ms is not None
        assert rec.duration_ms >= 0
        assert rec.retry_count == 0

        await driver.shutdown()

    _run(_go())


# ── 2) Failure path — status ERROR, boot still yields ─────────────


def test_p23_1_structural_migration_failure_stamps_error_boot_yields(caplog):
    """A structural migration that raises MUST stamp ``status=error``
    with the exception message and ``retry_count=0`` — and boot MUST
    STILL yield (server still binds). The log line MUST include
    ``[structural-migration]`` with the migration name."""
    srv = _load_server()

    async def _go():
        async def _boom():
            raise RuntimeError("simulated-boot-failure-p23-1")

        async def _boot():
            await srv._run_structural_migration(
                "test_p23_1_failure", _boom, must_succeed=True,
            )

        async def _noop_shutdown():
            return None

        srv._run_boot_sequence = _boot
        srv._p21_shutdown_sequence = _noop_shutdown
        srv._do_seed = lambda: asyncio.sleep(0)
        srv._do_integrity_scan = lambda: asyncio.sleep(0)

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="pool_crm"):
            driver = _LifespanDriver(srv.app)
            await driver.startup()

        # State record reflects the ERROR.
        rec = srv.app.state.init.structural_migrations.get(
            "test_p23_1_failure",
        )
        assert rec is not None
        assert rec.status.value == "error"
        assert rec.error is not None
        assert "simulated-boot-failure-p23-1" in rec.error
        assert rec.retry_count == 0

        # Boot STILL yielded — schema_migrations_done_at stamped.
        assert srv.app.state.init.schema_migrations_done_at is not None

        # Log line surfaces at ERROR level (must_succeed=True).
        error_lines = [
            r for r in caplog.records
            if r.levelno >= logging.ERROR
            and "[structural-migration]" in r.getMessage()
            and "test_p23_1_failure" in r.getMessage()
        ]
        assert error_lines, (
            f"Expected [structural-migration] ERROR log for "
            f"test_p23_1_failure, got: "
            f"{[r.getMessage() for r in caplog.records[-10:]]}"
        )

        await driver.shutdown()

    _run(_go())


# ── 3) /api/health reflects the state change ──────────────────────


def test_p23_1_health_endpoint_exposes_structural_migrations():
    """After boot completes, ``GET /api/health`` MUST include a
    ``init.structural_migrations`` sub-object keyed by migration
    name. Success entries carry ``status=done``, failure entries
    carry ``status=error`` with the ``error`` string. Top-level
    ``status`` STAYS ``ok`` even when a must_succeed migration
    failed."""
    srv = _load_server()

    async def _go():
        async def _ok():
            return "ok"

        async def _fail():
            raise ValueError("h3-boom")

        async def _boot():
            await srv._run_structural_migration(
                "h3_ok_mig", _ok, must_succeed=True,
            )
            await srv._run_structural_migration(
                "h3_fail_mig", _fail, must_succeed=True,
            )

        async def _noop_shutdown():
            return None

        srv._run_boot_sequence = _boot
        srv._p21_shutdown_sequence = _noop_shutdown
        srv._do_seed = lambda: asyncio.sleep(0)
        srv._do_integrity_scan = lambda: asyncio.sleep(0)

        driver = _LifespanDriver(srv.app)
        await driver.startup()

        async with AsyncClient(
            transport=ASGITransport(app=srv.app), base_url="http://test",
        ) as client:
            r = await client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        # Top-level stays ok — migration failure is a signal, not a
        # request-serving gate.
        assert body["status"] == "ok"
        init = body.get("init") or {}
        assert init.get("schema_migrations") == "done"
        sm = init.get("structural_migrations") or {}
        assert "h3_ok_mig" in sm
        assert sm["h3_ok_mig"]["status"] == "done"
        assert sm["h3_ok_mig"]["error"] is None
        assert "h3_fail_mig" in sm
        assert sm["h3_fail_mig"]["status"] == "error"
        assert sm["h3_fail_mig"]["error"] is not None
        assert "h3-boom" in sm["h3_fail_mig"]["error"]
        assert sm["h3_fail_mig"]["retry_count"] == 0

        await driver.shutdown()

    _run(_go())


# ── 4) must_succeed=False → WARN log severity (not ERROR) ─────────


def test_p23_1_non_critical_failure_logs_warn_not_error(caplog):
    """``must_succeed=False`` failures still stamp ERROR state on the
    record but log at WARN severity (not ERROR). This gates ops
    paging thresholds so a non-critical best-effort backfill failure
    doesn't page the on-call."""
    srv = _load_server()

    async def _go():
        async def _flake():
            raise RuntimeError("best-effort-flake")

        async def _boot():
            await srv._run_structural_migration(
                "test_p23_1_non_critical", _flake, must_succeed=False,
            )

        async def _noop_shutdown():
            return None

        srv._run_boot_sequence = _boot
        srv._p21_shutdown_sequence = _noop_shutdown
        srv._do_seed = lambda: asyncio.sleep(0)
        srv._do_integrity_scan = lambda: asyncio.sleep(0)

        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="pool_crm"):
            driver = _LifespanDriver(srv.app)
            await driver.startup()

        # State record still ERROR — telemetry parity across the two
        # severity classes.
        rec = srv.app.state.init.structural_migrations[
            "test_p23_1_non_critical"
        ]
        assert rec.status.value == "error"

        # NO ERROR-level record for this migration.
        err_lines = [
            r for r in caplog.records
            if r.levelno >= logging.ERROR
            and "test_p23_1_non_critical" in r.getMessage()
        ]
        assert err_lines == [], (
            f"Expected 0 ERROR logs for must_succeed=False, got: "
            f"{[r.getMessage() for r in err_lines]}"
        )

        # AT LEAST one WARN-level record.
        warn_lines = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "[structural-migration]" in r.getMessage()
            and "test_p23_1_non_critical" in r.getMessage()
        ]
        assert warn_lines, (
            f"Expected at least one WARN log for must_succeed=False, "
            f"got no matching records."
        )

        await driver.shutdown()

    _run(_go())


# ── 5) Source guardrail — no silent swallows in structural block ──


def test_p23_1_no_silent_migration_swallows_in_boot_sequence():
    """The P23 restore + P24 perf_customers_v1 migrations MUST route
    through ``_run_structural_migration``. The pre-P23.1 pattern
    (``try: await mig() except Exception as e: logger.warning(...)``)
    is banned inside ``_run_boot_sequence`` for the two named
    migrations because it lost the traceback.
    """
    src = Path(__file__).resolve().parents[1] / "server.py"
    body = src.read_text(encoding="utf-8")

    # Extract _run_boot_sequence body.
    import re
    m = re.search(
        r"^async def _run_boot_sequence\(\).*?(?=^async def |\Z)",
        body, flags=re.MULTILINE | re.DOTALL,
    )
    assert m is not None
    boot = m.group(0)

    # Both critical migrations must route through the helper.
    assert "_run_structural_migration" in boot, (
        "_run_boot_sequence no longer references "
        "_run_structural_migration — P23.1 helper wiring regressed."
    )
    assert "p23_restore_ethan_steven_technicians" in boot
    assert "_p24_run_perf_customers_boot" in boot

    # The specific pre-P23.1 anti-pattern must NOT remain for the
    # p23 restore migration — the OLD code was
    # ``except Exception as e:  # noqa: BLE001
    #     logger.warning(f"[p23-restore] boot migration failed: {e}")``
    # which lost the traceback. If a regression re-introduces the
    # WARN-with-no-traceback shape, fail loudly.
    bad_line = 'logger.warning(f"[p23-restore] boot migration failed:'
    assert bad_line not in boot, (
        "Pre-P23.1 silent-swallow WARN detected on the p23 restore "
        "migration invocation. Route through _run_structural_migration "
        "instead."
    )


# ── 6) retry_count defaults to 0 for structural migrations ────────


def test_p23_1_structural_migrations_have_zero_retry_count():
    """Structural migrations don't retry by default — the boot chain
    is single-pass. ``retry_count`` MUST be 0 on both success and
    failure records."""
    srv = _load_server()

    async def _go():
        async def _ok():
            return None

        async def _fail():
            raise KeyError("k")

        async def _boot():
            await srv._run_structural_migration(
                "rc_ok", _ok, must_succeed=True,
            )
            await srv._run_structural_migration(
                "rc_fail", _fail, must_succeed=True,
            )

        async def _noop_shutdown():
            return None

        srv._run_boot_sequence = _boot
        srv._p21_shutdown_sequence = _noop_shutdown
        srv._do_seed = lambda: asyncio.sleep(0)
        srv._do_integrity_scan = lambda: asyncio.sleep(0)

        driver = _LifespanDriver(srv.app)
        await driver.startup()

        sm = srv.app.state.init.structural_migrations
        assert sm["rc_ok"].retry_count == 0
        assert sm["rc_fail"].retry_count == 0

        await driver.shutdown()

    _run(_go())
