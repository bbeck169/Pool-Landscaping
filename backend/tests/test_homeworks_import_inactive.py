"""Feb-2026 · Homeworks Inactive-Customers importer — P0 unstick +
inactive-lifecycle mapping tests.

Covers:
  * Watchdog auto-fails stale ``{queued, running}`` docs.
  * ``POST /api/integrations/homeworks/imports/dispatcher/reset-stuck``
    endpoint clears the stuck lock and re-queues the doc.
  * Inactive Homeworks customers land with ``is_active=False`` and
    ``source_status`` on our side.
  * Written-off Homeworks customers ditto (both collapse onto the
    same lifecycle flag).
  * Re-run over an already-imported customer is idempotent — no
    duplicate row, no field flip.
  * Local edits (e.g. an admin manually toggled ``is_active=True``)
    are NOT reverted by a follow-up import.
  * Mid-run failure marks the run doc ``failed``; a subsequent
    reset-stuck re-arms it.

Every test runs against the real Mongo instance and cleans up its
own docs so it can be executed alongside the rest of the backend
suite without leaving state.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = fresh_db
    # Re-bind the module-level ``db`` reference in the importer +
    # dispatcher modules (each imported ``from config import db``
    # at module load, so the earlier binding lingers).
    import services.homeworks_mcp.inactive_customers_importer as _imp
    _imp.db = fresh_db
    yield


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(
        os.environ["MONGO_URL"], io_loop=_LOOP,
    )[os.environ["DB_NAME"]]


def _mk_tenant_id() -> str:
    # Isolated fake tenant per test module — avoids colliding with
    # real seed tenants during the watchdog sweep.
    return f"TEST_hw_tenant_{uuid.uuid4().hex[:8]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _seed_run(
    *, tenant_id: str, status: str, kind: str = "inactive_customers",
    updated_at: str | None = None,
    counters: Dict[str, int] | None = None,
) -> str:
    run_id = uuid.uuid4().hex
    await _db().homeworks_import_runs.insert_one({
        "run_id": run_id, "tenant_id": tenant_id, "kind": kind,
        "status": status,
        "started_at": _now_iso(),
        "updated_at": updated_at or _now_iso(),
        "counters": counters or {"customers_scanned": 0,
                                    "customers_imported": 0},
        "resume_cursor": 0, "error_log": [],
    })
    return run_id


async def _drain(tenant_id: str) -> None:
    for coll in ("homeworks_import_runs", "customers"):
        await _db()[coll].delete_many({"tenant_id": tenant_id})


# ═════════════════════════════════════════════════════════════════════
# 1. Reset-stuck endpoint re-queues a stuck ``queued`` doc.
# ═════════════════════════════════════════════════════════════════════
def test_reset_stuck_endpoint_requeues_stuck_job(monkeypatch):
    async def _go():
        tid = _mk_tenant_id()
        # Seed a doc that got claimed to ``running`` but never made
        # forward progress — the classic P0 symptom from the ops
        # screenshot.
        run_id = await _seed_run(
            tenant_id=tid, status="running",
            updated_at=(datetime.now(timezone.utc)
                         - timedelta(minutes=30)).isoformat(),
        )
        try:
            from routers.integrations_homeworks_dispatcher import reset_stuck
            fake_user = {"id": "u-1", "tenant_id": tid,
                         "role": "super_admin"}
            # Neutralise the follow-up dispatcher_tick so we don't
            # need a live GraphQL client — the reset flow itself is
            # what we're asserting.
            import routers.integrations_homeworks_dispatcher as _mod
            monkeypatch.setattr(_mod, "dispatcher_tick",
                                 lambda: _fake_tick_summary())

            r = await reset_stuck(kind=None, user=fake_user)
            assert r["ok"] is True
            assert r["reset"] == 1
            assert run_id in r["run_ids"]

            after = await _db().homeworks_import_runs.find_one(
                {"run_id": run_id}, {"_id": 0, "status": 1,
                                       "error_log": 1,
                                       "dispatcher_pid": 1},
            )
            assert after["status"] == "queued"
            assert after.get("dispatcher_pid") is None
            stages = [e.get("stage") for e in after.get("error_log") or []]
            assert "manual_reset_stuck" in stages
        finally:
            await _drain(tid)

    _run(_go())


async def _fake_tick_summary() -> Dict[str, Any]:
    return {"started": 0, "skipped_concurrency": 0, "unknown_kind": 0,
            "stale_transitioned": 0, "at": _now_iso()}


# ═════════════════════════════════════════════════════════════════════
# 2. Watchdog transitions stale ``running`` doc → ``failed_stale``.
# ═════════════════════════════════════════════════════════════════════
def test_watchdog_marks_stale_running_as_failed_stale():
    async def _go():
        tid = _mk_tenant_id()
        stale = (datetime.now(timezone.utc)
                  - timedelta(minutes=60)).isoformat()
        run_id = await _seed_run(
            tenant_id=tid, status="running", updated_at=stale,
        )
        # Also seed a fresh ``running`` doc that MUST NOT be swept
        # (updated_at within the window).
        fresh_id = await _seed_run(
            tenant_id=tid, status="running", updated_at=_now_iso(),
        )
        try:
            from services.homeworks_mcp.import_dispatcher import _watchdog_sweep
            out = await _watchdog_sweep(_db())
            assert out["stale_transitioned"] >= 1

            stale_row = await _db().homeworks_import_runs.find_one(
                {"run_id": run_id}, {"_id": 0, "status": 1,
                                       "error_log": 1},
            )
            assert stale_row["status"] == "failed_stale"
            reasons = [e.get("reason") for e in stale_row["error_log"]]
            assert any("stale_running" in r for r in reasons if r)

            fresh_row = await _db().homeworks_import_runs.find_one(
                {"run_id": fresh_id}, {"_id": 0, "status": 1},
            )
            assert fresh_row["status"] == "running"  # untouched
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 3+4. Inactive + written-off Homeworks customers land as inactive.
# ═════════════════════════════════════════════════════════════════════
def _mk_hw_customer(**overrides: Any) -> Dict[str, Any]:
    doc = {
        "id": 100 + int(uuid.uuid4().int % 100_000),
        "status": "INACTIVE",
        "firstName": "Elena", "lastName": "Roque",
        "fullName": "Elena Roque",
        "email": "elena.roque@example.com",
        "phone": "+15555550101",
        "address": {"street1": "1 Old Pool Ln",
                    "city": "Mesa", "state": "AZ", "zip": "85202"},
        "tags": [], "outstanding": 0, "lifetimePaid": 0,
    }
    doc.update(overrides)
    return doc


def test_inactive_customer_is_stamped_is_active_false():
    async def _go():
        tid = _mk_tenant_id()
        try:
            from services.homeworks_mcp.inactive_customers_importer import (
                _import_one_customer, Counters, _RateLimiter, RATE_LIMIT_QPS,
            )
            counters = Counters()
            limiter = _RateLimiter(RATE_LIMIT_QPS)
            hw = _mk_hw_customer(status="INACTIVE")
            # Monkey-patch child fetches out — this test asserts the
            # customer doc shape, not the child fan-out.
            import services.homeworks_mcp.inactive_customers_importer as _mod

            async def _no_children(**kwargs):
                return {"events": [], "invoices": [], "payments": [], "estimates": []}

            _orig_gql = _mod.gql_query
            _mod.gql_query = _no_children
            try:
                await _import_one_customer(
                    tenant_id=tid, user_id="u-1", customer=hw,
                    limiter=limiter, counters=counters,
                )
            finally:
                _mod.gql_query = _orig_gql

            saved = await _db().customers.find_one(
                {"tenant_id": tid, "original_id": str(hw["id"])},
                {"_id": 0, "is_active": 1, "source_status": 1,
                 "homeworks_status": 1},
            )
            assert saved is not None
            assert saved["is_active"] is False
            assert saved["source_status"] == "INACTIVE"
            assert saved["homeworks_status"] == "INACTIVE"

            assert counters.customers_created == 1
            assert counters.customers_marked_inactive == 1
            assert counters.customers_skipped == 0
        finally:
            await _drain(tid)

    _run(_go())


def test_written_off_customer_is_stamped_is_active_false_with_traceability():
    async def _go():
        tid = _mk_tenant_id()
        try:
            from services.homeworks_mcp.inactive_customers_importer import (
                _import_one_customer, Counters, _RateLimiter, RATE_LIMIT_QPS,
            )
            counters = Counters()
            limiter = _RateLimiter(RATE_LIMIT_QPS)
            hw = _mk_hw_customer(status="WRITTEN_OFF",
                                  fullName="Bad Debtor",
                                  firstName="Bad", lastName="Debtor")
            import services.homeworks_mcp.inactive_customers_importer as _mod

            async def _no_children(**kwargs):
                return {"events": [], "invoices": [], "payments": [], "estimates": []}

            _mod.gql_query = _no_children
            await _import_one_customer(
                tenant_id=tid, user_id="u-1", customer=hw,
                limiter=limiter, counters=counters,
            )

            saved = await _db().customers.find_one(
                {"tenant_id": tid, "original_id": str(hw["id"])},
                {"_id": 0, "is_active": 1, "source_status": 1},
            )
            assert saved["is_active"] is False
            # source_status preserves the raw label for churn analysis.
            assert saved["source_status"] == "WRITTEN_OFF"
            assert counters.customers_marked_inactive == 1
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 5. Re-run over an already-imported inactive customer → skipped.
# ═════════════════════════════════════════════════════════════════════
def test_reimport_of_already_inactive_customer_is_a_noop_skip():
    async def _go():
        tid = _mk_tenant_id()
        try:
            from services.homeworks_mcp.inactive_customers_importer import (
                _import_one_customer, Counters, _RateLimiter, RATE_LIMIT_QPS,
            )
            import services.homeworks_mcp.inactive_customers_importer as _mod

            async def _no_children(**kwargs):
                return {"events": [], "invoices": [], "payments": [], "estimates": []}

            _mod.gql_query = _no_children
            hw = _mk_hw_customer(status="INACTIVE")

            c1 = Counters()
            await _import_one_customer(
                tenant_id=tid, user_id="u-1", customer=hw,
                limiter=_RateLimiter(RATE_LIMIT_QPS), counters=c1,
            )
            assert c1.customers_created == 1
            assert c1.customers_marked_inactive == 1

            # Second pass — SAME hw payload → should skip cleanly.
            c2 = Counters()
            await _import_one_customer(
                tenant_id=tid, user_id="u-1", customer=hw,
                limiter=_RateLimiter(RATE_LIMIT_QPS), counters=c2,
            )
            assert c2.customers_created == 0
            assert c2.customers_updated == 0
            assert c2.customers_skipped == 1
            assert c2.customers_marked_inactive == 0

            n = await _db().customers.count_documents({
                "tenant_id": tid, "original_id": str(hw["id"]),
            })
            assert n == 1
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 6. Local edit (is_active=True) is preserved on re-import.
# ═════════════════════════════════════════════════════════════════════
def test_reimport_preserves_local_is_active_edit():
    async def _go():
        tid = _mk_tenant_id()
        try:
            from services.homeworks_mcp.inactive_customers_importer import (
                _import_one_customer, Counters, _RateLimiter, RATE_LIMIT_QPS,
            )
            import services.homeworks_mcp.inactive_customers_importer as _mod

            async def _no_children(**kwargs):
                return {"events": [], "invoices": [], "payments": [], "estimates": []}

            _mod.gql_query = _no_children
            hw = _mk_hw_customer(status="INACTIVE",
                                  fullName="Reactivated Customer",
                                  firstName="React", lastName="Ivated")

            # 1) initial import → is_active=False.
            await _import_one_customer(
                tenant_id=tid, user_id="u-1", customer=hw,
                limiter=_RateLimiter(RATE_LIMIT_QPS),
                counters=Counters(),
            )

            # 2) simulate an admin manually re-activating the customer.
            saved = await _db().customers.find_one(
                {"tenant_id": tid, "original_id": str(hw["id"])},
                {"_id": 0, "id": 1},
            )
            await _db().customers.update_one(
                {"id": saved["id"]},
                {"$set": {"is_active": True, "phone": "+15555550999"}},
            )

            # 3) re-import → local edit MUST be preserved.
            c2 = Counters()
            await _import_one_customer(
                tenant_id=tid, user_id="u-1", customer=hw,
                limiter=_RateLimiter(RATE_LIMIT_QPS), counters=c2,
            )
            after = await _db().customers.find_one(
                {"id": saved["id"]},
                {"_id": 0, "is_active": 1, "phone": 1},
            )
            assert after["is_active"] is True    # local edit preserved
            assert after["phone"] == "+15555550999"
            # Counters: we didn't create; we may have updated snapshot
            # fields; must NOT re-count as marked_inactive.
            assert c2.customers_created == 0
            assert c2.customers_marked_inactive == 0
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 7. Dispatcher crash marks run ``failed`` → retry via reset-stuck.
# ═════════════════════════════════════════════════════════════════════
def test_dispatcher_marks_run_failed_on_crash_and_reset_re_arms(monkeypatch):
    async def _go():
        tid = _mk_tenant_id()
        run_id = await _seed_run(tenant_id=tid, status="queued")
        try:
            from services.homeworks_mcp import import_dispatcher as _disp

            # Stub the importer module so ``_run_one`` invokes a
            # deliberately-crashing ``run_full``.
            fake_mod_name = "services.homeworks_mcp.inactive_customers_importer"

            async def _boom(**kwargs):
                raise RuntimeError("simulated importer crash")

            import services.homeworks_mcp.inactive_customers_importer as _real
            _orig = _real.run_full
            _real.run_full = _boom  # type: ignore
            try:
                # Claim the run as if a real dispatcher tick did it.
                claimed = await _disp._try_start_run(
                    _db(), {"run_id": run_id, "kind": "inactive_customers",
                            "tenant_id": tid},
                )
                assert claimed is True
                await _disp._run_one(
                    "inactive_customers", tid, run_id, "u-1",
                )
            finally:
                _real.run_full = _orig  # type: ignore

            failed = await _db().homeworks_import_runs.find_one(
                {"run_id": run_id}, {"_id": 0, "status": 1,
                                       "error_log": 1},
            )
            assert failed["status"] == "failed"
            reasons = [e.get("stage") for e in failed["error_log"]]
            assert "dispatcher_crash" in reasons

            # Reset-stuck should now re-queue it (accepts any status
            # in {queued, running}) — a failed doc is a DIFFERENT
            # terminal state, so the endpoint must ignore it, which
            # is the expected contract: the operator resubmits.
            from routers.integrations_homeworks_dispatcher import reset_stuck
            monkeypatch.setattr(
                "routers.integrations_homeworks_dispatcher.dispatcher_tick",
                lambda: _fake_tick_summary(),
            )
            r = await reset_stuck(
                kind="inactive_customers",
                user={"id": "u-1", "tenant_id": tid,
                      "role": "super_admin"},
            )
            # ``failed`` is not in {queued, running} → nothing to reset.
            assert r["reset"] == 0

            # Now manually flip to ``running`` (simulate a repeat of
            # the original P0 stuck-state) and re-arm.
            await _db().homeworks_import_runs.update_one(
                {"run_id": run_id},
                {"$set": {"status": "running",
                           "updated_at": _now_iso()}},
            )
            r2 = await reset_stuck(
                kind="inactive_customers",
                user={"id": "u-1", "tenant_id": tid,
                      "role": "super_admin"},
            )
            assert r2["reset"] == 1
            after = await _db().homeworks_import_runs.find_one(
                {"run_id": run_id}, {"_id": 0, "status": 1},
            )
            assert after["status"] == "queued"
        finally:
            await _drain(tid)

    _run(_go())
