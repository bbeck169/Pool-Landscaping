"""Phase P46 · Feb-2026 — bulk_charge_runs index swap + startup hardening.

Locks the two-track fix that replaces the legacy 2-column unique
index ``tenant_idempotency_unique`` with the correct 3-column
``tenant_idempotency_dry_run_unique`` on
``(tenant_id, idempotency_key, dry_run)``.

  * Migration script (``migrations/p46_bulk_charge_index_swap.py``)
    — dry-run by default, marker-idempotent, --force to override.
  * ``ensure_indexes()`` in
    ``routers/invoices_bulk_charge.py`` — self-healing on every
    boot; broad try/except so an index-op flake can't crash the
    pod; loud ERROR logging on both drop + create rungs.

Test loop convention mirrors ``test_p44``: sync pymongo for
seeding + cleanup on a per-test **collection** clone, fresh
async loop + Motor client for the SUT calls.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

# The migration + ensure_indexes both target ``bulk_charge_runs``.
# For test isolation we work against a per-test **scratch
# collection** in the same DB and swap the ``.bulk_charge_runs``
# attribute on the Motor db object.  This keeps real preview
# ``bulk_charge_runs`` data + real indexes untouched.


# ─── Helpers ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def scratch(dbc):
    """Per-test scratch collection name + marker slate reset.

    The migration/ensure_indexes code reads
    ``target.bulk_charge_runs`` — we monkey-patch that attribute to
    point at a fresh collection so real data is never touched.

    The P46 startup wiring stamps
    ``migrations_applied[name="p46_bulk_charge_index_swap"]`` on
    every backend boot, so pre-delete it here before yielding.
    Every test that wants "marker present" state seeds it
    explicitly via ``_run(..., seed_marker=True)``.
    """
    name = f"_p46_test_bcr_{uuid.uuid4().hex[:10]}"
    marker_id = f"_p46_test_marker_{uuid.uuid4().hex[:10]}"
    # Reset marker slate for this test.
    dbc.migrations_applied.delete_many(
        {"name": "p46_bulk_charge_index_swap"},
    )
    yield {"coll_name": name, "marker_id": marker_id}
    try:
        dbc[name].drop()
    except Exception:
        pass
    # Same-name delete on teardown so a stamp left by the test
    # doesn't survive to poison other suites.  The real boot pass
    # will re-stamp on the next backend restart.
    dbc.migrations_applied.delete_many(
        {"name": "p46_bulk_charge_index_swap"},
    )


def _loop_client():
    """Fresh asyncio loop + Motor client bound to it."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = AsyncIOMotorClient(MONGO_URL, io_loop=loop)
    return loop, client


class _DbWrapper:
    """Motor-db proxy where ``.bulk_charge_runs`` returns the
    scratch collection.  Every other attribute passes through
    to the real Motor db so ``migrations_applied.find_one`` etc.
    still work.

    ``bulk_charge_runs`` is **cached** on first access so a
    ``patch.object(wrapped.bulk_charge_runs, "drop_index", ...)``
    in the test survives the second attribute access from inside
    the SUT — without the cache, Motor's ``__getitem__`` returns
    a fresh collection object per call and the patch never takes.
    """
    def __init__(self, real, scratch_name, marker_test_id):
        self._real = real
        self._scratch_name = scratch_name
        self._marker_test_id = marker_test_id
        self._cached_bcr = None

    def __getitem__(self, name):
        return self._real[name]

    def __getattr__(self, name):
        if name == "bulk_charge_runs":
            # Cache on first access — see class docstring for why.
            cached = self.__dict__.get("_cached_bcr")
            if cached is None:
                cached = self._real[self._scratch_name]
                self.__dict__["_cached_bcr"] = cached
            return cached
        return getattr(self._real, name)


def _run(coro_factory, scratch, *, seed_marker=False):
    """Wrap the SUT call in a fresh loop + scratch-collection swap.

    Also monkey-patches ``_stamp_marker`` to tag inserts with the
    per-test marker id so the fixture's cleanup can drop them
    without touching real markers.
    """
    loop, client = _loop_client()
    try:
        adb = client[DB_NAME]
        wrapped = _DbWrapper(adb, scratch["coll_name"], scratch["marker_id"])

        # Patch config.db used inside the migration module so its
        # module-level ``db`` reads/writes go through the wrapper.
        import migrations.p46_bulk_charge_index_swap as p46
        p46._orig_db_for_test = getattr(p46, "_orig_db_for_test", p46.db)
        p46.db = wrapped
        # And the same for the router (ensure_indexes reads ``db``
        # from ``config`` at module scope).
        import routers.invoices_bulk_charge as ibc
        ibc._orig_db_for_test = getattr(ibc, "_orig_db_for_test", ibc.db)
        ibc.db = wrapped

        # Tag marker inserts.
        orig_stamp = p46._stamp_marker

        async def _tagged_stamp(summary, db_client=None):
            await orig_stamp(summary, db_client)
            await (db_client or wrapped)[p46.MARKER_COLLECTION].update_one(
                {"name": p46.MIGRATION_NAME},
                {"$set": {"_p46_test_id": scratch["marker_id"]}},
            )
        p46._stamp_marker = _tagged_stamp

        if seed_marker:
            _sync = MongoClient(MONGO_URL)[DB_NAME]
            _sync.migrations_applied.insert_one({
                "name": p46.MIGRATION_NAME,
                "applied_at": "2026-02-15T00:00:00Z",
                "_p46_test_id": scratch["marker_id"],
            })

        try:
            return loop.run_until_complete(coro_factory(wrapped))
        finally:
            p46._stamp_marker = orig_stamp
    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass
        # Restore module ``db`` handles.
        import migrations.p46_bulk_charge_index_swap as p46r
        if hasattr(p46r, "_orig_db_for_test"):
            p46r.db = p46r._orig_db_for_test
        import routers.invoices_bulk_charge as ibcr
        if hasattr(ibcr, "_orig_db_for_test"):
            ibcr.db = ibcr._orig_db_for_test


def _seed_legacy_index(dbc, scratch):
    """Create the pre-P46 2-column unique index on the scratch
    collection (via sync pymongo so it's ready when the SUT runs)."""
    dbc[scratch["coll_name"]].create_index(
        [("tenant_id", 1), ("idempotency_key", 1)],
        name="tenant_idempotency_unique",
        unique=True,
    )


def _seed_new_index(dbc, scratch):
    """Create the correct 3-column unique index on the scratch coll."""
    dbc[scratch["coll_name"]].create_index(
        [("tenant_id", 1), ("idempotency_key", 1), ("dry_run", 1)],
        name="tenant_idempotency_dry_run_unique",
        unique=True,
    )


def _list_names(dbc, scratch) -> List[str]:
    return [ix.get("name") for ix in dbc[scratch["coll_name"]].list_indexes()]


# ═══════════════════════════════════════════════════════════════════
# Migration script tests (1–6)
# ═══════════════════════════════════════════════════════════════════

def test_migration_drops_legacy_index_when_present(dbc, scratch):
    """Seed the legacy 2-col index, run ``--execute``, assert it's gone."""
    _seed_legacy_index(dbc, scratch)
    assert "tenant_idempotency_unique" in _list_names(dbc, scratch)

    async def _c(wrapped):
        from migrations.p46_bulk_charge_index_swap import run
        return await run(execute=True, db_client=wrapped)

    summary = _run(_c, scratch)
    assert summary["dropped_legacy"] is True
    assert summary["skipped_by_marker"] is False
    names = _list_names(dbc, scratch)
    assert "tenant_idempotency_unique" not in names
    assert "tenant_idempotency_dry_run_unique" in names


def test_migration_creates_new_index_when_absent(dbc, scratch):
    """No indexes seeded — run ``--execute`` — new 3-col present."""
    async def _c(wrapped):
        from migrations.p46_bulk_charge_index_swap import run
        return await run(execute=True, db_client=wrapped)

    summary = _run(_c, scratch)
    assert summary["created_new"] is True
    assert summary["dropped_legacy"] is False
    names = _list_names(dbc, scratch)
    assert "tenant_idempotency_dry_run_unique" in names


def test_migration_idempotent_when_correct_index_already_present(dbc, scratch):
    """Pre-seed the correct 3-col index — the script reports
    ``already_correct=True`` and does no drop/create."""
    _seed_new_index(dbc, scratch)

    async def _c(wrapped):
        from migrations.p46_bulk_charge_index_swap import run
        return await run(execute=True, db_client=wrapped)

    summary = _run(_c, scratch)
    assert summary["already_correct"] is True
    assert summary["dropped_legacy"] is False
    assert summary["created_new"] is False


def test_migration_dry_run_reports_actions_without_mutating(dbc, scratch):
    """Legacy pre-seeded, ``--dry-run`` (default) reports what it
    WOULD do without touching the DB."""
    _seed_legacy_index(dbc, scratch)
    names_before = _list_names(dbc, scratch)

    async def _c(wrapped):
        from migrations.p46_bulk_charge_index_swap import run
        return await run(execute=False, db_client=wrapped)

    summary = _run(_c, scratch)
    assert summary["dry_run"] is True
    assert summary["executed_at"] is None
    # Would-drop + would-create signalled in the same fields as
    # execute (dropped_legacy=True, created_new=True).
    assert summary["dropped_legacy"] is True
    assert summary["created_new"] is True
    # But the DB is UNCHANGED.
    assert _list_names(dbc, scratch) == names_before
    assert "tenant_idempotency_unique" in _list_names(dbc, scratch)


def test_migration_second_execute_short_circuits_by_marker(dbc, scratch):
    """Second execute after a successful stamp returns
    ``skipped_by_marker: True`` and doesn't touch indexes."""
    async def _first(wrapped):
        from migrations.p46_bulk_charge_index_swap import run
        return await run(execute=True, db_client=wrapped)
    _run(_first, scratch)
    names_after_first = _list_names(dbc, scratch)

    async def _second(wrapped):
        from migrations.p46_bulk_charge_index_swap import run
        return await run(execute=True, db_client=wrapped)
    summary = _run(_second, scratch)
    assert summary["skipped_by_marker"] is True
    assert summary["dropped_legacy"] is False
    assert summary["created_new"] is False
    # No index mutation on the second call.
    assert _list_names(dbc, scratch) == names_after_first


def test_migration_force_bypasses_marker(dbc, scratch):
    """After the marker is stamped, ``--force`` re-runs the swap."""
    async def _first(wrapped):
        from migrations.p46_bulk_charge_index_swap import run
        return await run(execute=True, db_client=wrapped)
    _run(_first, scratch)

    async def _forced(wrapped):
        from migrations.p46_bulk_charge_index_swap import run
        return await run(execute=True, force=True, db_client=wrapped)
    summary = _run(_forced, scratch)
    # ``already_correct`` should be True (the swap ran once already
    # so the state is correct on the second, forced pass).
    assert summary["skipped_by_marker"] is False
    assert summary["already_correct"] is True


# ═══════════════════════════════════════════════════════════════════
# ensure_indexes hardening tests (7–10)
# ═══════════════════════════════════════════════════════════════════

def test_ensure_indexes_drops_legacy_then_creates_new(dbc, scratch, caplog):
    """Legacy pre-seeded, ensure_indexes drops + creates + logs
    the P46 verification line."""
    import logging as _logging
    _seed_legacy_index(dbc, scratch)

    async def _c(wrapped):
        from routers.invoices_bulk_charge import ensure_indexes
        await ensure_indexes(db_client=wrapped)
        return True

    caplog.set_level(_logging.INFO)
    _run(_c, scratch)
    names = _list_names(dbc, scratch)
    assert "tenant_idempotency_unique" not in names
    assert "tenant_idempotency_dry_run_unique" in names
    assert "tenant_started_at_desc" in names
    logs = " ".join(r.getMessage() for r in caplog.records)
    assert "[p46] bulk_charge_runs indexes verified" in logs
    assert "legacy dropped=True" in logs


def test_ensure_indexes_survives_drop_failure_logs_error(
    dbc, scratch, caplog,
):
    """Mock ``drop_index`` to raise a non-not-found error.  The
    function must NOT re-raise; it must emit a loud ERROR line."""
    import logging as _logging
    _seed_legacy_index(dbc, scratch)

    from pymongo.errors import OperationFailure

    async def _fake_drop(name):
        raise OperationFailure("simulated write conflict")

    async def _c(wrapped):
        from routers.invoices_bulk_charge import ensure_indexes
        # Patch drop_index on the scratch collection instance.
        coll = wrapped.bulk_charge_runs
        with patch.object(coll, "drop_index", side_effect=_fake_drop):
            await ensure_indexes(db_client=wrapped)
        return True

    caplog.set_level(_logging.ERROR)
    _run(_c, scratch)
    errs = [r.getMessage() for r in caplog.records
            if r.levelname == "ERROR"]
    assert any("failed to drop legacy tenant_idempotency_unique" in e
                for e in errs), f"expected P46 drop-fail ERROR, got {errs}"


def test_ensure_indexes_survives_create_failure_logs_error(
    dbc, scratch, caplog,
):
    """Mock ``create_index`` on the new-index call to raise; assert
    ERROR + no re-raise."""
    import logging as _logging
    from pymongo.errors import OperationFailure

    _create_state: dict = {"orig": None}

    async def _fake_create(*args, **kwargs):
        if kwargs.get("name") == "tenant_idempotency_dry_run_unique":
            raise OperationFailure("simulated create failure")
        return await _create_state["orig"](*args, **kwargs)

    async def _c(wrapped):
        from routers.invoices_bulk_charge import ensure_indexes
        coll = wrapped.bulk_charge_runs
        _create_state["orig"] = coll.create_index
        with patch.object(coll, "create_index", side_effect=_fake_create):
            await ensure_indexes(db_client=wrapped)
        return True

    caplog.set_level(_logging.ERROR)
    _run(_c, scratch)
    errs = [r.getMessage() for r in caplog.records
            if r.levelname == "ERROR"]
    assert any(
        "failed to create tenant_idempotency_dry_run_unique" in e
        for e in errs
    ), f"expected P46 create-fail ERROR, got {errs}"


def test_ensure_indexes_idempotent_on_second_call(dbc, scratch):
    """Two consecutive calls — second is a no-op; state stable."""
    async def _c(wrapped):
        from routers.invoices_bulk_charge import ensure_indexes
        await ensure_indexes(db_client=wrapped)
        await ensure_indexes(db_client=wrapped)
        return True

    _run(_c, scratch)
    names = sorted(_list_names(dbc, scratch))
    assert "tenant_idempotency_dry_run_unique" in names
    assert "tenant_started_at_desc" in names
    # Sanity — only the two managed indexes + ``_id_``.
    assert "tenant_idempotency_unique" not in names


# ═══════════════════════════════════════════════════════════════════
# Contract tests (11–12) — invariant enforcement
# ═══════════════════════════════════════════════════════════════════

def test_new_index_allows_same_key_across_dry_run_boundary(dbc, scratch):
    """The whole point of P46: preview (dry_run=True) + confirm
    (dry_run=False) with the SAME idempotency key must coexist."""
    _seed_new_index(dbc, scratch)
    coll = dbc[scratch["coll_name"]]
    tenant = "t-p46-a"
    key = "same-key"
    coll.insert_one({"tenant_id": tenant, "idempotency_key": key,
                       "dry_run": True, "run_id": "r1"})
    # This second write MUST NOT hit E11000.
    coll.insert_one({"tenant_id": tenant, "idempotency_key": key,
                       "dry_run": False, "run_id": "r2"})
    assert coll.count_documents(
        {"tenant_id": tenant, "idempotency_key": key},
    ) == 2


def test_new_index_still_blocks_same_key_same_dry_run(dbc, scratch):
    """Belt-and-suspenders: within one ``dry_run`` mode, the same
    ``(tenant_id, key)`` still hits E11000.  The unique invariant is
    preserved — only the SCOPING widened."""
    _seed_new_index(dbc, scratch)
    coll = dbc[scratch["coll_name"]]
    tenant = "t-p46-b"
    key = "duplicate-key"
    coll.insert_one({"tenant_id": tenant, "idempotency_key": key,
                       "dry_run": False, "run_id": "r1"})
    with pytest.raises(DuplicateKeyError):
        coll.insert_one({"tenant_id": tenant, "idempotency_key": key,
                           "dry_run": False, "run_id": "r2"})
