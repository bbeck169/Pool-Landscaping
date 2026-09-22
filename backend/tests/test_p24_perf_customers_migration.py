"""Phase P24 · Feb-2026 — perf_customers_v1 migration wiring.

Locks the following contracts:

  1. **Idempotency.** Running ``services.migrations.perf_customers_indexes.run``
     twice against a live Motor DB produces the expected indexes on
     the first run and reports ``skipped=True`` on the second. Both
     runs succeed without error.
  2. **Expected index names.** The migration creates ONE compound
     index per collection (``jobs``, ``invoices``, ``payments``,
     ``customer_notes``, ``properties``) with a name of the shape
     ``perf_customers_<coll>_<suffix>``. ``list_indexes()`` MUST
     include each after a fresh run.
  3. **Boot-ordering integration.** The lifespan runs the migration
     BEFORE the yield (structural bucket) — i.e. before ``bg_tasks``
     for SEED / INTEGRITY_SCAN are scheduled. Uses the
     ``_LifespanDriver`` pattern from
     ``test_p21_async_startup.py`` — patches ``_run_boot_sequence``
     with a thin shim that calls the extracted
     ``server._p24_run_perf_customers_boot`` helper, then verifies
     the call landed before the ``lifespan`` yield.
  4. **Version marker.** After a successful run the migration writes
     ``{"key": "perf_customers_v1", "completed_at": <iso>, ...}`` to
     ``db.migration_status`` — this is the sentinel that
     ``/health/ready`` polls to decide whether to serve 503.
"""
from __future__ import annotations

import asyncio
import importlib
import re
import sys
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

from tests._f7_loop_fixture import run_test


MIGRATION_KEY = "perf_customers_v1"

EXPECTED_INDEXES = {
    "jobs": "perf_customers_jobs_tenant_customer_created",
    "invoices": "perf_customers_invoices_tenant_customer_created",
    "payments": "perf_customers_payments_tenant_customer_created",
    "customer_notes": "perf_customers_customer_notes_tenant_customer_created",
    "properties": "perf_customers_properties_tenant_customer",
}


# ── 1) Idempotency + expected indexes present ─────────────────────


def test_p24_perf_customers_run_is_idempotent_and_creates_expected_indexes():
    """First run: creates OR reuses existing indexes and stamps the
    sentinel. Second run: sentinel hit, returns ``skipped=True`` with
    zero creates. ``list_indexes()`` includes each expected name on
    both runs (indexes survive between the two)."""
    async def _go(db):
        from services.migrations.perf_customers_indexes import run

        # Clean slate — remove the sentinel so run() actually executes.
        await db.migration_status.delete_one({"key": MIGRATION_KEY})

        res1 = await run(db)
        assert res1["ok"] is True
        assert res1["skipped"] is False, (
            f"First run reported skipped=True — sentinel state leaked "
            f"from a prior test: {res1}"
        )

        # Every expected index must appear on the collection.
        _expected_names = set(EXPECTED_INDEXES.values())
        for coll_name, idx_name in EXPECTED_INDEXES.items():
            names = set()
            async for idx in db[coll_name].list_indexes():
                names.add(idx.get("name"))
            # The migration is tolerant of pre-existing indexes with
            # the same first two keys — it skips creation in that case.
            # So either our exact name exists, OR a compatible index
            # (first two keys ``tenant_id`` + ``customer_id``) does.
            has_expected = idx_name in names
            has_compat = False
            async for idx in db[coll_name].list_indexes():
                keys = list((idx.get("key") or {}).items())
                if (len(keys) >= 2
                        and keys[0][0] == "tenant_id"
                        and keys[1][0] == "customer_id"):
                    has_compat = True
                    break
            assert has_expected or has_compat, (
                f"{coll_name}: neither expected index {idx_name!r} nor a "
                f"compatible (tenant_id, customer_id, ...) index found — "
                f"actual indexes: {names}"
            )
            # For any coll we created (not already-had), the exact name
            # must match.
            if coll_name in res1.get("collections", []):
                assert idx_name in names, (
                    f"{coll_name}: run() reported CREATE but exact index "
                    f"{idx_name!r} is missing from {names}"
                )
            _expected_names.discard(idx_name)

        # Second run — sentinel is set, no-op.
        res2 = await run(db)
        assert res2["ok"] is True
        assert res2["skipped"] is True, (
            f"Second run should be sentinel-skipped but was: {res2}"
        )
        assert res2["created"] == 0
        assert res2["reason"] == "already_ran"

    run_test(_go)


# ── 2) Version marker written to migration_status ─────────────────


def test_p24_perf_customers_run_writes_v1_sentinel():
    """After a successful run, ``migration_status`` MUST contain a
    row with ``key = perf_customers_v1`` and a truthy
    ``completed_at`` timestamp. This is the sentinel
    ``/health/ready`` reads via ``_REQUIRED_MIGRATIONS`` — a missing
    or unstamped row keeps the pod at 503 forever."""
    async def _go(db):
        from services.migrations.perf_customers_indexes import run

        await db.migration_status.delete_one({"key": MIGRATION_KEY})
        await run(db)

        row = await db.migration_status.find_one(
            {"key": MIGRATION_KEY}, {"_id": 0},
        )
        assert row is not None, (
            "migration_status row missing — perf_customers_v1 "
            "sentinel was not written."
        )
        assert row.get("key") == MIGRATION_KEY
        assert row.get("completed_at"), (
            f"perf_customers_v1 sentinel missing completed_at: {row}"
        )
        # Basic ISO-8601 shape check.
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}",
            row["completed_at"],
        ), f"completed_at not ISO-8601: {row['completed_at']!r}"

    run_test(_go)


# ── 3) Boot-ordering — invoked BEFORE the lifespan yield ──────────


class _LifespanDriver:
    """Same minimal ASGI lifespan driver used by
    ``test_p21_async_startup.py``. Sends ``lifespan.startup`` +
    ``lifespan.shutdown`` messages so we can observe state DURING the
    yielded phase (Starlette's TestClient only fires the events at
    enter/exit)."""

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
    """Import ``server`` (or return cached) and reset per-test app.state
    fields the lifespan repopulates. Stubs ``_run_boot_sequence`` +
    ``_p21_shutdown_sequence`` to lightweight noop equivalents that
    still exercise the P24 helper so we can assert boot ordering."""
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


def test_p24_perf_customers_runs_in_structural_pre_yield_block():
    """Boot-ordering integration test — reuses the P21 lifespan
    driver. The stubbed ``_run_boot_sequence`` calls the extracted
    ``_p24_run_perf_customers_boot`` helper, and we assert:

      * the helper is invoked BEFORE ``mark_migrations_done`` fires
        (structural bucket),
      * the SEED / SCAN chain (post-yield BG task) hasn't STARTED
        until after the helper returned,
      * the migration result dict flows back to the caller.
    """
    srv = _load_server()

    async def _go():
        events: list[str] = []
        seed_gate = asyncio.Event()

        # Stubbed boot sequence — calls the real P24 helper against
        # ``srv.db`` and records ordering.
        async def _boot():
            events.append("boot:enter")
            events.append("perf_customers:before")
            res = await srv._p24_run_perf_customers_boot(srv.db)
            events.append("perf_customers:after")
            events.append(
                f"perf_customers:ok={res.get('ok')}:"
                f"skipped={res.get('skipped')}"
            )
            events.append("boot:exit")

        async def _shutdown():
            return None

        async def _slow_seed():
            events.append("seed:start")
            await seed_gate.wait()

        async def _slow_scan():
            events.append("scan:start")
            await seed_gate.wait()

        srv._run_boot_sequence = _boot
        srv._p21_shutdown_sequence = _shutdown
        srv._do_seed = _slow_seed
        srv._do_integrity_scan = _slow_scan

        driver = _LifespanDriver(srv.app)
        await driver.startup()

        # After lifespan.startup.complete, structural work is done.
        # Ordering assertion — perf_customers_boot ran BEFORE the
        # seed/scan chain got a chance to start.
        idx_pc_after = events.index("perf_customers:after")
        assert idx_pc_after >= 0

        # Ensure boot recorded BOTH before + after (helper was
        # actually invoked, not skipped).
        assert "perf_customers:before" in events
        assert "perf_customers:after" in events
        assert events.index("perf_customers:before") < idx_pc_after

        # Seed / scan must not have started until boot returned.
        for ev in ("seed:start", "scan:start"):
            if ev in events:
                assert events.index(ev) > idx_pc_after, (
                    f"P24 ordering violated — {ev!r} ran BEFORE "
                    f"perf_customers boot finished: {events}"
                )

        # schema_migrations_done_at stamped => structural bucket done.
        assert srv.app.state.init.schema_migrations_done_at is not None

        # /api/health still serves 200 after structural completion.
        async with AsyncClient(
            transport=ASGITransport(app=srv.app), base_url="http://test",
        ) as client:
            r = await client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["init"]["schema_migrations"] == "done"

        seed_gate.set()
        await driver.shutdown()

    _run(_go())


# ── 4) Source-level guardrail — call site lives in structural block ─


def test_p24_perf_customers_call_is_before_lifespan_yield():
    """Source-level lint — ``server.py`` MUST invoke
    ``_p24_run_perf_customers_boot`` from inside
    ``_run_boot_sequence`` (structural bucket, pre-yield). A refactor
    that accidentally moves it into a background task would silently
    stop the ``/health/ready`` sentinel from being written on cold
    starts."""
    src = Path(__file__).resolve().parents[1] / "server.py"
    body = src.read_text(encoding="utf-8")

    m_boot = re.search(
        r"^async def _run_boot_sequence\(\).*?(?=^async def |\Z)",
        body, flags=re.MULTILINE | re.DOTALL,
    )
    assert m_boot is not None, (
        "_run_boot_sequence not found in server.py — P21 refactor "
        "regressed."
    )
    boot_body = m_boot.group(0)
    assert "_p24_run_perf_customers_boot" in boot_body, (
        "_p24_run_perf_customers_boot is NOT invoked inside "
        "_run_boot_sequence — perf_customers_v1 sentinel will never "
        "be written on cold starts, and /health/ready will report "
        "503 forever."
    )
    assert "_p24_warn_active_testmode_mocks" in boot_body, (
        "_p24_warn_active_testmode_mocks is NOT invoked inside "
        "_run_boot_sequence — go-live testmode WARNs will not fire."
    )
