"""Feb-2026 · Profitability backfill migration · pytest suite.

Locks 10 contracts for
``services.migrations.chemical_usage_backfill_v1``:

  1. Fresh DB — 0 submitted reports → migration runs, sentinel
     completes, zero backfilled / failed / skipped.
  2. All in-ledger — 3 submitted reports each with matching ledger
     rows → 0 backfilled (detection query returns empty).
  3. Missing ledger — 3 submitted reports with chemistry, 0 ledger
     rows → migration backfills all 3 with ``backfilled_by``
     marker; ``rows_backfilled == 3``.
  4. Partial gap — 3 reports, 1 has ledger already, 2 missing →
     migration backfills only the 2 missing; the 1 pre-existing
     is left untouched.
  5. Empty-chemistry safeguard — 2 submitted reports with
     ``chemicals_added=[]`` and no water-body chemistry →
     migration skips both; ``rows_skipped_empty_chemistry == 2``.
  6. Fault path — monkeypatch ``snapshot_chemical_usage`` to raise
     on 1 specific report; migration continues; that report ends
     up in ``rows_failed``; other reports still backfill.
  7. Idempotency — run migration twice; second is no-op via
     sentinel-gate short-circuit.
  8. Rollback smoke — apply the documented rollback commands;
     assert ledger rows with the migration's marker are removed +
     sentinel is deleted; assert the migration can then re-run
     to backfill again.
  9. Tenant isolation — 2 tenants each with missing reports;
     migration backfills both without cross-contamination; ledger
     rows carry the correct ``tenant_id`` from the source report.
 10. Source-lint — migration file imports + calls
     ``snapshot_chemical_usage`` and does NOT re-implement
     chemistry math (zero direct ``chemical_usage_events.insert``
     writes; ledger inserts flow ONLY through the snapshot).

Loop / DB hygiene
─────────────────
Uses the same rebind pattern as
``test_task_m_reopen_resubmit_idempotency.py``: a module-scoped
``bind_db`` fixture rebinds ``config.db`` +
``routers.chemical_products.db`` to a Motor client bound to the
test's own event loop.  Restores originals on teardown so sibling
test files aren't polluted.  NO ``asyncio.set_event_loop`` at
module level (learned from the P0 fix's cross-loop regression) —
every op goes through ``_run(coro)`` which uses ``_LOOP``
explicitly.

Cleanup
───────
Seeded jobs / reports / events all carry the tag prefix
``TEST-chembackfill-`` (ids) or ``TEST_ChemBackfill_`` (job
titles).  Module autouse cleanup runs on setup + teardown.
"""
from __future__ import annotations

import asyncio
import os
import re
import uuid
from pathlib import Path

import pytest


MIGRATION_KEY = "chemical_usage_backfill_v1"
MIGRATION_PATH = Path(__file__).resolve().parents[1] / "services" / \
    "migrations" / "chemical_usage_backfill_v1.py"


_JOB_TITLE_PREFIX = "TEST_ChemBackfill_"
_ID_PREFIX = "TEST-chembackfill-"
_CATALOG_SLUG = f"{_ID_PREFIX}chlor-gran"

_LOOP = asyncio.new_event_loop()
# NB: intentionally NOT calling asyncio.set_event_loop(_LOOP) —
# see P0 test file for the rationale (mutating the process's
# current-loop pointer poisons sibling test files that rely on
# asyncio.get_event_loop() at Motor client bind time).


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _fresh_client():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    client = AsyncIOMotorClient(
        os.environ["MONGO_URL"], io_loop=_LOOP,
    )
    return client, client[os.environ["DB_NAME"]]


# ═══════════════════════════════════════════════════════════════════════
# Fixture · rebind config.db + chemical_products.db for hermetic tests.
# ═══════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module", autouse=True)
def bind_db():
    """Rebind ``routers.chemical_products.db`` so the snapshot
    function invoked BY the migration under test uses a Motor
    client bound to _LOOP.

    Intentionally does NOT rebind ``config.db`` — the migration
    receives ``db`` as a parameter (production boot passes the
    already-bound config.db directly; tests pass a _LOOP-scoped
    fresh client via ``_run_migration``).  Touching config.db here
    would put a _LOOP-bound handle into Motor's global state that
    sibling test files (chem_gate, etc.) would see after our
    teardown-restore, causing cross-loop failures in the snapshot
    path that the P0 fix now legitimately surfaces as 500s.
    """
    client, db = _fresh_client()

    from routers import chemical_products as _chem_mod

    _orig = {"chem": getattr(_chem_mod, "db", None)}
    _chem_mod.db = db

    # Pre-cleanup any residue from prior runs / cross-file pollution.
    _run(_cleanup(db))

    yield db

    # Post-cleanup + restore originals.
    _run(_cleanup(db))
    _chem_mod.db = _orig["chem"]
    # Purge ``routers.chemical_products`` from ``sys.modules`` so a
    # sibling test file's later rebind of ``config.db`` propagates
    # into ``chemical_products.db`` on the next lazy import inside
    # ``submit_service_report``.  Without this, our early ``import
    # routers.chemical_products`` (above) locks the module's ``db``
    # attribute to ``config.db``-at-module-load-time (bound to the
    # pytest-bootstrap loop); restoring ``_orig["chem"]`` on
    # teardown just puts that stale-loop reference back.  The gate
    # test (``test_chemistry_required_readings_gate.py``) which
    # runs after us rebinds ``config.db`` to its own loop-bound
    # client but does NOT rebind ``chemical_products.db``, so its
    # ``submit_service_report`` calls ``snapshot_chemical_usage``
    # which does I/O on our stale ``chemical_products.db`` →
    # ``got Future ... attached to a different loop``.  Popping the
    # module from ``sys.modules`` forces the next
    # ``from routers.chemical_products import snapshot_chemical_usage``
    # (lazy import inside the submit handler) to re-execute the
    # module and read the CURRENT ``config.db``.
    import sys as _sys
    _sys.modules.pop("routers.chemical_products", None)
    # Intentionally NOT calling ``client.close()`` — closing the
    # Motor client here releases the connection pool tied to
    # _LOOP, but leaves a residual bound-loop reference in
    # Motor's global state that surfaces as a cross-loop error
    # in sibling test files.  Letting the client GC naturally
    # avoids poking the residual state.


async def _cleanup(db) -> None:
    seeded_job_ids = [j["id"] async for j in db.jobs.find(
        {"title": {"$regex": f"^{_JOB_TITLE_PREFIX}"}},
        {"_id": 0, "id": 1},
    )]
    await db.jobs.delete_many(
        {"title": {"$regex": f"^{_JOB_TITLE_PREFIX}"}})
    await db.service_reports.delete_many(
        {"job_id": {"$in": seeded_job_ids}} if seeded_job_ids
        else {"id": {"$regex": f"^{_ID_PREFIX}"}})
    await db.chemical_usage_events.delete_many(
        {"job_id": {"$in": seeded_job_ids}} if seeded_job_ids
        else {"service_report_id": {"$regex": f"^{_ID_PREFIX}"}})
    await db.chemical_costs.delete_many(
        {"chemical_slug": _CATALOG_SLUG})
    await db.migration_status.delete_one({"key": MIGRATION_KEY})


async def _seed_catalog(db, tenant_id: str, cost_cents: int = 300) -> None:
    await db.chemical_costs.update_one(
        {"tenant_id": tenant_id, "chemical_slug": _CATALOG_SLUG},
        {"$set": {
            "id": _CATALOG_SLUG,
            "tenant_id": tenant_id,
            "chemical_slug": _CATALOG_SLUG,
            "name": "TEST Chlorine Granular",
            "cost_per_unit_cents": cost_cents,
            "unit_kind": "lb",
        }},
        upsert=True,
    )


async def _seed_report(
    db, tenant_id: str, *, submitted: bool = True,
    with_chemistry: bool = True, with_water_bodies: bool = False,
    customer_id: str = "cust-fake-1",
) -> dict:
    from datetime import datetime, timezone
    job_id = f"{_ID_PREFIX}job-{uuid.uuid4().hex[:8]}"
    sr_id = f"{_ID_PREFIX}sr-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()
    scheduled = "2099-11-01T14:00:00+00:00"
    await db.jobs.insert_one({
        "id": job_id,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "title": f"{_JOB_TITLE_PREFIX}{uuid.uuid4().hex[:6]}",
        "service_type": "pool",
        "job_type": "pool",
        "status": "completed",
        "scheduled_date": scheduled,
        "scheduled_start": scheduled,
        "created_at": now, "updated_at": now,
    })
    chemicals: list = []
    water_bodies: list = []
    if with_chemistry:
        if with_water_bodies:
            water_bodies = [{
                "id": f"{_ID_PREFIX}wb-{uuid.uuid4().hex[:6]}",
                "type": "pool",
                "label": "Main pool",
                "chemicals_used": [
                    {"product_slug": _CATALOG_SLUG,
                     "name": "TEST Chlorine Granular",
                     "quantity_used": 3, "unit": "lb"},
                ],
            }]
        else:
            chemicals = [
                {"product_slug": _CATALOG_SLUG,
                 "name": "TEST Chlorine Granular",
                 "quantity_used": 2, "unit": "lb"},
            ]
    doc = {
        "id": sr_id,
        "tenant_id": tenant_id,
        "job_id": job_id,
        "tech_id": "tech-fake-1",
        "template_kind": "pool",
        "created_at": now, "updated_at": now,
        "submitted_at": now if submitted else None,
        "chemicals_added": chemicals,
        "water_bodies": water_bodies,
        "checklist_items": [], "photos": [], "notes": "",
    }
    await db.service_reports.insert_one(doc)
    return {"job_id": job_id, "service_report_id": sr_id}


async def _pick_tenant_id(db, slug: str = "aquaterra") -> str:
    row = await db.tenants.find_one({"slug": slug}, {"_id": 0, "id": 1})
    assert row, f"tenant slug={slug!r} not found — required seed"
    return row["id"]


async def _pick_second_tenant_id(db, primary_id: str) -> str:
    row = await db.tenants.find_one(
        {"id": {"$ne": primary_id}}, {"_id": 0, "id": 1},
    )
    assert row, "expected at least 2 tenants for isolation test"
    return row["id"]


def _import_run():
    """Fresh import of the migration's ``run`` symbol each call so
    monkeypatch on the snapshot function is picked up (the migration
    imports ``snapshot_chemical_usage`` lazily inside ``run`` so
    the patched attribute is what gets resolved)."""
    from services.migrations.chemical_usage_backfill_v1 import run
    return run


# Scoping filter — every test uses this to isolate its seeded rows
# from co-existing data in the shared aquaterra tenant DB.  The
# production boot call at ``server.py::_run_chemical_usage_backfill_v1_boot``
# does NOT pass ``service_report_filter`` so the prod scan is
# global as designed.
_TEST_SCOPE = {"id": {"$regex": f"^{_ID_PREFIX}"}}


def _run_migration(db):
    """Run the migration with the test-scope filter."""
    return _run(_import_run()(db, service_report_filter=_TEST_SCOPE))


@pytest.fixture(autouse=True)
def _per_test_cleanup(bind_db):
    """Wipe every test-prefix row + the sentinel BEFORE each test.

    Without this, seeded rows accumulate across tests (all sharing
    the same ``_ID_PREFIX``) and idempotency / rollback assertions
    that count exact rows would drift.  Runs BEFORE the test body
    so each test starts with a clean slate under our prefix.  The
    module-scope ``bind_db`` fixture handles final teardown.
    """
    _run(_cleanup(bind_db))
    yield


# ═══════════════════════════════════════════════════════════════════════
# 1) Fresh DB — no submitted reports → migration succeeds, all zeros
# ═══════════════════════════════════════════════════════════════════════
def test_fresh_db_no_submitted_reports(bind_db):
    db = bind_db
    tenant_id = _run(_pick_tenant_id(db))
    _run(_seed_catalog(db, tenant_id))
    # No reports seeded — the migration should complete cleanly.

    res = _run_migration(db)
    assert res["ok"] is True
    assert res["skipped"] is False
    assert res["rows_backfilled"] == 0
    assert res["rows_failed"] == 0
    assert res["rows_skipped_empty_chemistry"] == 0

    async def _sentinel():
        return await db.migration_status.find_one({"key": MIGRATION_KEY})
    sen = _run(_sentinel())
    assert sen is not None
    assert sen.get("completed_at")
    assert sen.get("must_succeed") is False


# ═══════════════════════════════════════════════════════════════════════
# 2) All in-ledger — reports already have ledger rows → 0 backfilled
# ═══════════════════════════════════════════════════════════════════════
def test_all_in_ledger_no_op(bind_db):
    db = bind_db
    tenant_id = _run(_pick_tenant_id(db))
    _run(_seed_catalog(db, tenant_id))
    _run(db.migration_status.delete_one({"key": MIGRATION_KEY}))

    # Seed 3 reports with pre-existing ledger rows.
    async def _seed_all():
        ids = []
        for _ in range(3):
            r = await _seed_report(db, tenant_id)
            # Seed a matching ledger row so detection skips.
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            await db.chemical_usage_events.insert_one({
                "id": f"{_ID_PREFIX}evt-{uuid.uuid4().hex[:8]}",
                "tenant_id": tenant_id,
                "job_id": r["job_id"],
                "service_report_id": r["service_report_id"],
                "customer_id": None,
                "product_slug": _CATALOG_SLUG,
                "name": "TEST Chlorine Granular",
                "quantity_used": 2, "unit": "lb",
                "unit_cost_at_time_cents": 300,
                "total_cost_cents": 600,
                "occurred_at": now, "created_at": now,
                # NB: no backfilled_by — pre-existing ledger row.
            })
            ids.append(r)
        return ids
    seeded = _run(_seed_all())

    res = _run_migration(db)
    assert res["ok"] is True
    assert res["rows_backfilled"] == 0, res
    assert res["rows_failed"] == 0, res

    # Confirm pre-existing ledger rows are untouched (no backfilled_by).
    async def _fetch_events():
        return [e async for e in db.chemical_usage_events.find(
            {"service_report_id": {"$in": [r["service_report_id"]
                                              for r in seeded]}},
            {"_id": 0},
        )]
    events = _run(_fetch_events())
    assert len(events) == 3
    for e in events:
        assert "backfilled_by" not in e, (
            f"pre-existing ledger row should NOT carry the migration"
            f" marker: {e}"
        )


# ═══════════════════════════════════════════════════════════════════════
# 3) Missing ledger — snapshot fires for all → all backfilled + stamped
# ═══════════════════════════════════════════════════════════════════════
def test_missing_ledger_all_backfilled(bind_db):
    db = bind_db
    tenant_id = _run(_pick_tenant_id(db))
    _run(_seed_catalog(db, tenant_id))
    _run(db.migration_status.delete_one({"key": MIGRATION_KEY}))

    async def _seed_all():
        return [(await _seed_report(db, tenant_id)) for _ in range(3)]
    seeded = _run(_seed_all())
    sr_ids = [s["service_report_id"] for s in seeded]

    res = _run_migration(db)
    assert res["ok"] is True
    assert res["rows_backfilled"] == 3, res
    assert res["rows_failed"] == 0, res
    assert res["rows_skipped_empty_chemistry"] == 0, res

    # Every seeded report now has ledger rows stamped with the marker.
    async def _fetch_events():
        return [e async for e in db.chemical_usage_events.find(
            {"service_report_id": {"$in": sr_ids}},
            {"_id": 0},
        )]
    events = _run(_fetch_events())
    assert len(events) == 3, (
        f"expected 3 ledger rows (one per report), got {len(events)}"
    )
    for e in events:
        assert e.get("backfilled_by") == MIGRATION_KEY, (
            f"backfilled row should be stamped with the migration key: {e}"
        )
        assert e.get("tenant_id") == tenant_id
        assert e.get("quantity_used") == 2
        assert e.get("unit_cost_at_time_cents") == 300
        assert e.get("total_cost_cents") == 600


# ═══════════════════════════════════════════════════════════════════════
# 4) Partial gap — pre-existing rows untouched; only missing backfilled
# ═══════════════════════════════════════════════════════════════════════
def test_partial_gap_only_missing_backfilled(bind_db):
    db = bind_db
    tenant_id = _run(_pick_tenant_id(db))
    _run(_seed_catalog(db, tenant_id))
    _run(db.migration_status.delete_one({"key": MIGRATION_KEY}))

    async def _seed_mixed():
        # Report A — already has ledger (should be untouched).
        r_a = await _seed_report(db, tenant_id)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        await db.chemical_usage_events.insert_one({
            "id": f"{_ID_PREFIX}evt-preexisting-A",
            "tenant_id": tenant_id,
            "job_id": r_a["job_id"],
            "service_report_id": r_a["service_report_id"],
            "customer_id": None,
            "product_slug": _CATALOG_SLUG,
            "name": "TEST Chlorine Granular",
            "quantity_used": 99, "unit": "lb",
            "unit_cost_at_time_cents": 300,
            "total_cost_cents": 99 * 300,
            "occurred_at": now, "created_at": now,
        })
        # Reports B, C — missing ledger (should be backfilled).
        r_b = await _seed_report(db, tenant_id)
        r_c = await _seed_report(db, tenant_id)
        return r_a, r_b, r_c
    r_a, r_b, r_c = _run(_seed_mixed())

    res = _run_migration(db)
    assert res["ok"] is True
    assert res["rows_backfilled"] == 2, res
    assert res["rows_failed"] == 0, res

    # Report A's pre-existing row is untouched (still has quantity=99,
    # no backfilled_by marker).
    async def _fetch(sr_id):
        return [e async for e in db.chemical_usage_events.find(
            {"service_report_id": sr_id}, {"_id": 0},
        )]
    events_a = _run(_fetch(r_a["service_report_id"]))
    assert len(events_a) == 1
    assert events_a[0]["quantity_used"] == 99
    assert "backfilled_by" not in events_a[0]

    # Reports B & C have new ledger rows stamped with the marker.
    for r in (r_b, r_c):
        events = _run(_fetch(r["service_report_id"]))
        assert len(events) == 1, (
            f"expected 1 ledger row for {r['service_report_id']}, got"
            f" {len(events)}"
        )
        assert events[0].get("backfilled_by") == MIGRATION_KEY


# ═══════════════════════════════════════════════════════════════════════
# 5) Empty-chemistry safeguard — no chemistry payload → skip, don't fake
# ═══════════════════════════════════════════════════════════════════════
def test_empty_chemistry_reports_skipped(bind_db):
    db = bind_db
    tenant_id = _run(_pick_tenant_id(db))
    _run(_seed_catalog(db, tenant_id))
    _run(db.migration_status.delete_one({"key": MIGRATION_KEY}))

    async def _seed_all():
        # 2 reports with NO chemistry (submit with only readings).
        return [(await _seed_report(db, tenant_id, with_chemistry=False))
                  for _ in range(2)]
    seeded = _run(_seed_all())
    sr_ids = [s["service_report_id"] for s in seeded]

    res = _run_migration(db)
    assert res["ok"] is True
    assert res["rows_backfilled"] == 0, res
    assert res["rows_failed"] == 0, res
    assert res["rows_skipped_empty_chemistry"] == 2, res

    async def _fetch_events():
        return [e async for e in db.chemical_usage_events.find(
            {"service_report_id": {"$in": sr_ids}},
            {"_id": 0},
        )]
    events = _run(_fetch_events())
    assert events == [], (
        f"empty-chemistry reports must NOT get fabricated ledger rows,"
        f" got {len(events)}: {events}"
    )


# ═══════════════════════════════════════════════════════════════════════
# 6) Fault path — snapshot raises on 1 report → migration continues
# ═══════════════════════════════════════════════════════════════════════
def test_fault_path_snapshot_raises_migration_continues(
        bind_db, monkeypatch):
    db = bind_db
    tenant_id = _run(_pick_tenant_id(db))
    _run(_seed_catalog(db, tenant_id))
    _run(db.migration_status.delete_one({"key": MIGRATION_KEY}))

    async def _seed_all():
        return [(await _seed_report(db, tenant_id)) for _ in range(3)]
    seeded = _run(_seed_all())
    fail_target = seeded[1]["service_report_id"]

    # Monkeypatch snapshot_chemical_usage on the source module —
    # the migration imports it lazily inside run() so the patched
    # attribute is what gets resolved.
    from routers import chemical_products as _chem_mod
    _original = _chem_mod.snapshot_chemical_usage

    async def _selective_boom(**kwargs):
        if kwargs.get("service_report_id") == fail_target:
            raise RuntimeError(
                "FAULT INJECT · migration snapshot failure for target"
            )
        return await _original(**kwargs)
    monkeypatch.setattr(
        _chem_mod, "snapshot_chemical_usage",
        _selective_boom, raising=True,
    )

    res = _run_migration(db)
    assert res["ok"] is True, res
    # Two reports backfilled, one failed.
    assert res["rows_backfilled"] == 2, res
    assert res["rows_failed"] == 1, res

    # Failed report has NO ledger row.
    async def _fetch_target():
        return [e async for e in db.chemical_usage_events.find(
            {"service_report_id": fail_target}, {"_id": 0},
        )]
    events = _run(_fetch_target())
    assert events == [], (
        f"failed-target should have no ledger rows, got {events}"
    )

    # Sentinel completed anyway (must_succeed=False posture); failures
    # array carries the target for ops triage.
    async def _sentinel():
        return await db.migration_status.find_one({"key": MIGRATION_KEY})
    sen = _run(_sentinel())
    assert sen.get("completed_at")
    assert sen.get("rows_failed") == 1
    assert any(f.get("service_report_id") == fail_target
                 for f in (sen.get("failures") or []))


# ═══════════════════════════════════════════════════════════════════════
# 7) Idempotency — second run is no-op via sentinel-gate short-circuit
# ═══════════════════════════════════════════════════════════════════════
def test_idempotent_second_run_short_circuits(bind_db):
    db = bind_db
    tenant_id = _run(_pick_tenant_id(db))
    _run(_seed_catalog(db, tenant_id))
    _run(db.migration_status.delete_one({"key": MIGRATION_KEY}))

    async def _seed_all():
        return [(await _seed_report(db, tenant_id)) for _ in range(2)]
    _run(_seed_all())

    res1 = _run_migration(db)
    assert res1["ok"] is True
    assert res1["skipped"] is False
    assert res1["rows_backfilled"] == 2

    # Second run — sentinel short-circuit.
    res2 = _run_migration(db)
    assert res2 == {
        "ok": True, "skipped": True, "reason": "already_ran",
    }

    # Double-check: no additional ledger rows written on run 2.
    async def _count():
        return await db.chemical_usage_events.count_documents(
            {"backfilled_by": MIGRATION_KEY,
              "tenant_id": tenant_id,
              "service_report_id": {"$regex": f"^{_ID_PREFIX}"}},
        )
    assert _run(_count()) == 2


# ═══════════════════════════════════════════════════════════════════════
# 8) Rollback smoke — documented commands unwind the migration cleanly
# ═══════════════════════════════════════════════════════════════════════
def test_rollback_smoke_restores_state(bind_db):
    db = bind_db
    tenant_id = _run(_pick_tenant_id(db))
    _run(_seed_catalog(db, tenant_id))
    _run(db.migration_status.delete_one({"key": MIGRATION_KEY}))

    async def _seed_all():
        return [(await _seed_report(db, tenant_id)) for _ in range(2)]
    _run(_seed_all())

    res1 = _run_migration(db)
    assert res1["rows_backfilled"] == 2

    # Confirm marker present pre-rollback.
    async def _count_marker():
        return await db.chemical_usage_events.count_documents(
            {"backfilled_by": MIGRATION_KEY,
              "service_report_id": {"$regex": f"^{_ID_PREFIX}"}},
        )
    assert _run(_count_marker()) == 2

    # Apply the documented rollback verbatim.
    async def _rollback():
        await db.chemical_usage_events.delete_many(
            {"backfilled_by": MIGRATION_KEY,
              "service_report_id": {"$regex": f"^{_ID_PREFIX}"}},
        )
        await db.migration_status.delete_one({"key": MIGRATION_KEY})
    _run(_rollback())

    # Marker rows gone; sentinel gone.
    assert _run(_count_marker()) == 0
    async def _sentinel():
        return await db.migration_status.find_one({"key": MIGRATION_KEY})
    assert _run(_sentinel()) is None

    # Re-running the migration after rollback backfills again cleanly.
    res2 = _run_migration(db)
    assert res2["ok"] is True
    assert res2["skipped"] is False
    assert res2["rows_backfilled"] == 2, res2
    assert _run(_count_marker()) == 2


# ═══════════════════════════════════════════════════════════════════════
# 9) Tenant isolation — two tenants each with gaps, no cross-contamination
# ═══════════════════════════════════════════════════════════════════════
def test_tenant_isolation(bind_db):
    db = bind_db
    tenant_a = _run(_pick_tenant_id(db))
    tenant_b = _run(_pick_second_tenant_id(db, tenant_a))
    _run(_seed_catalog(db, tenant_a))
    _run(_seed_catalog(db, tenant_b))
    _run(db.migration_status.delete_one({"key": MIGRATION_KEY}))

    async def _seed_all():
        ra = await _seed_report(db, tenant_a)
        rb = await _seed_report(db, tenant_b)
        return ra, rb
    ra, rb = _run(_seed_all())

    res = _run_migration(db)
    assert res["ok"] is True
    assert res["rows_backfilled"] == 2, res

    async def _fetch(sr_id):
        return [e async for e in db.chemical_usage_events.find(
            {"service_report_id": sr_id}, {"_id": 0},
        )]

    events_a = _run(_fetch(ra["service_report_id"]))
    assert len(events_a) == 1
    assert events_a[0]["tenant_id"] == tenant_a, (
        f"tenant A ledger row has wrong tenant_id: {events_a[0]}"
    )

    events_b = _run(_fetch(rb["service_report_id"]))
    assert len(events_b) == 1
    assert events_b[0]["tenant_id"] == tenant_b, (
        f"tenant B ledger row has wrong tenant_id: {events_b[0]}"
    )


# ═══════════════════════════════════════════════════════════════════════
# 10) Source-lint — migration reuses snapshot_chemical_usage, no direct
#                   ledger inserts
# ═══════════════════════════════════════════════════════════════════════
def test_source_lint_reuses_snapshot_no_direct_inserts():
    """The migration MUST call ``snapshot_chemical_usage`` (single
    source of truth) and MUST NOT re-implement chemistry math via
    direct ``chemical_usage_events.insert_*`` writes.  Guards
    against future drift where a maintainer bypasses the snapshot
    (and loses cost-catalog resolution, per-body context, etc.)."""
    src = MIGRATION_PATH.read_text(encoding="utf-8")

    # Positive — snapshot import + call present.
    assert "from routers.chemical_products import snapshot_chemical_usage" in src, (
        "migration must import snapshot_chemical_usage from the router"
    )
    assert re.search(r"\bawait\s+snapshot_chemical_usage\s*\(", src), (
        "migration must call snapshot_chemical_usage with await"
    )

    # Negative — no direct chemical_usage_events insert.  The
    # only allowed writes are:
    #   * db.chemical_usage_events.update_many(...) — provenance stamp
    #   * db.chemical_usage_events.count_documents(...) — detection query
    # A direct insert_one / insert_many would bypass the cost model.
    stripped = re.sub(r"#.*$", "", src, flags=re.MULTILINE)
    assert not re.search(
        r"db\.chemical_usage_events\.insert_(one|many)\s*\(", stripped,
    ), (
        "migration must NOT insert directly into chemical_usage_events"
        " — flow through snapshot_chemical_usage instead"
    )

    # Positive — provenance stamp path present.
    assert 'backfilled_by' in src
    assert 'MIGRATION_KEY' in src
