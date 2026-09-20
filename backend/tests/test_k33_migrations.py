"""Phase K33 · Feb-2026 — regression tests for the boot-wired
K15 and K21 index migrations.

Guarantees for each migration:
  1. First run creates every missing index + writes the sentinel row.
  2. Second run early-returns ``status=skipped`` on the sentinel.
  3. ``force=True`` bypasses the sentinel guard (matches the pattern
     used by every other migration in the ``services.migrations``
     directory).
  4. Every index name from the K15/K21 standalone scripts is
     represented in the migration's ``_INDEXES`` catalogue (byte-
     for-byte parity so a future refactor can't silently drift).

The tests drop the sentinel + created indexes on setup + teardown
so they're safe to run repeatedly against the same preview DB.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)



load_dotenv(Path(__file__).resolve().parents[1] / ".env")

_sync = _shared_db()
# K33 · fresh loop + Motor client bound to it.  Rebind
# ``config.db`` inside a fixture so other test files aren't left
# holding a K33-loop-bound client. Mirrors the K14 / K31 pattern.
_LOOP = asyncio.new_event_loop()
_K33_MOTOR = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
_K33_DB = _K33_MOTOR[os.environ["DB_NAME"]]


def _run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture
def clean_sentinels_and_indexes():
    """Drop K15/K21 sentinels + indexes before AND after each test
    that uses this fixture, so the suite starts from a clean
    slate."""
    _drop_k15(); _drop_k21()
    yield
    _drop_k15(); _drop_k21()


@pytest.fixture
def rebind_db(monkeypatch):
    """Rebind ``config.db`` + both migration modules' ``db``
    handles to the K33-loop-bound client for the test's duration."""
    import config as _config_mod
    from services.migrations import k15_jobs_indexes as _k15_mod
    from services.migrations import k21_perf_indexes as _k21_mod
    monkeypatch.setattr(_config_mod, "db", _K33_DB)
    monkeypatch.setattr(_k15_mod, "db", _K33_DB)
    monkeypatch.setattr(_k21_mod, "db", _K33_DB)
    yield


# ── K15 migration ────────────────────────────────────────────────
def _drop_k15():
    _sync.migrations.delete_one({"id": "k15_jobs_indexes_v1"})
    for name in ("k15_jobs_tech_schedule_status", "k15_jobs_crew_schedule"):
        try:
            _sync.jobs.drop_index(name)
        except Exception:  # noqa: BLE001
            pass


def _drop_k21():
    _sync.migrations.delete_one({"id": "k21_perf_indexes_v1"})
    from services.migrations.k21_perf_indexes import _INDEXES
    for coll, name, _ in _INDEXES:
        try:
            _sync[coll].drop_index(name)
        except Exception:  # noqa: BLE001
            pass


def test_k33_k15_first_run_creates_indexes_and_writes_sentinel(
    clean_sentinels_and_indexes, rebind_db,
):
    from services.migrations.k15_jobs_indexes import (
        run_k15_jobs_indexes_migration,
    )
    res = _run(run_k15_jobs_indexes_migration())
    assert res["status"] == "ok"
    assert res["summary"]["created"] == 2
    assert res["summary"]["already_present"] == 0
    names = {i["name"] for i in _sync.jobs.list_indexes()}
    assert "k15_jobs_tech_schedule_status" in names
    assert "k15_jobs_crew_schedule" in names
    sentinel = _sync.migrations.find_one({"id": "k15_jobs_indexes_v1"})
    assert sentinel is not None
    assert sentinel["summary"]["created"] == 2


def test_k33_k15_second_run_is_skipped_on_sentinel(
    clean_sentinels_and_indexes, rebind_db,
):
    from services.migrations.k15_jobs_indexes import (
        run_k15_jobs_indexes_migration,
    )
    _run(run_k15_jobs_indexes_migration())
    res = _run(run_k15_jobs_indexes_migration())
    assert res["status"] == "skipped"
    assert res["reason"] == "sentinel_present"


def test_k33_k15_force_bypasses_sentinel(
    clean_sentinels_and_indexes, rebind_db,
):
    from services.migrations.k15_jobs_indexes import (
        run_k15_jobs_indexes_migration,
    )
    _run(run_k15_jobs_indexes_migration())
    res = _run(run_k15_jobs_indexes_migration(force=True))
    assert res["status"] == "ok"
    assert res["summary"]["already_present"] == 2
    assert res["summary"]["created"] == 0


# ── K21 migration ────────────────────────────────────────────────
def test_k33_k21_first_run_creates_indexes_and_writes_sentinel(
    clean_sentinels_and_indexes, rebind_db,
):
    from services.migrations.k21_perf_indexes import (
        run_k21_perf_indexes_migration, _INDEXES,
    )
    res = _run(run_k21_perf_indexes_migration())
    assert res["status"] == "ok"
    assert res["summary"]["created"] == len(_INDEXES)
    # Every declared index landed on its collection.
    for coll, name, _ in _INDEXES:
        names = {i["name"] for i in _sync[coll].list_indexes()}
        assert name in names, f"{coll}.{name} missing after apply"
    sentinel = _sync.migrations.find_one({"id": "k21_perf_indexes_v1"})
    assert sentinel is not None
    assert sentinel["summary"]["created"] == len(_INDEXES)


def test_k33_k21_second_run_is_skipped_on_sentinel(
    clean_sentinels_and_indexes, rebind_db,
):
    from services.migrations.k21_perf_indexes import (
        run_k21_perf_indexes_migration,
    )
    _run(run_k21_perf_indexes_migration())
    res = _run(run_k21_perf_indexes_migration())
    assert res["status"] == "skipped"
    assert res["reason"] == "sentinel_present"


def test_k33_k21_force_bypasses_sentinel(
    clean_sentinels_and_indexes, rebind_db,
):
    from services.migrations.k21_perf_indexes import (
        run_k21_perf_indexes_migration, _INDEXES,
    )
    _run(run_k21_perf_indexes_migration())
    res = _run(run_k21_perf_indexes_migration(force=True))
    assert res["status"] == "ok"
    assert res["summary"]["already_present"] == len(_INDEXES)
    assert res["summary"]["created"] == 0


# ── Parity with the standalone scripts ───────────────────────────
def test_k33_k15_migration_matches_standalone_script():
    """The migration and the standalone script must declare the
    same set of indexes with byte-for-byte identical key specs.
    Guards against a refactor that silently drifts one of the two
    paths."""
    from services.migrations.k15_jobs_indexes import (
        _INDEXES as _mig,
    )
    from scripts.k15_seed_jobs_indexes import _K15_INDEXES as _script
    assert {(n, tuple(k)) for n, k in _mig} == \
           {(n, tuple(k)) for n, k in _script}


def test_k33_k21_migration_matches_standalone_script():
    from services.migrations.k21_perf_indexes import (
        _INDEXES as _mig,
    )
    from scripts.k21_seed_perf_indexes import _K21_INDEXES as _script
    assert {(c, n, tuple(k)) for c, n, k in _mig} == \
           {(c, n, tuple(k)) for c, n, k in _script}
