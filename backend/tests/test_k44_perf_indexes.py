"""Phase K44 · Feb-2026 — regression tests for the always-on
production perf-index reconciliation migration.

Guarantees:
  1. Fresh run creates every K44 index (the union of K15 + K21 +
     F3.5 catalogues) and reports ``created`` counts.
  2. Second run is a full-idempotent no-op (all ``already_present``)
     because ``create_index`` name-checks first — unlike K15/K21
     which sentinel-gate the check, K44 must survive without
     sentinels so the fix keeps working even if the sentinel
     collection is dropped.
  3. K44 always writes a run-summary sentinel to ``db.migrations``
     for diagnostic grepping.
  4. Also verifies the ``boot_flags.should_run_startup_indexes()``
     K44 override: setting ``RUN_STARTUP_INDEXES=true`` in a
     production APP_ENV now returns True (previously hard-forced to
     False), so ops has a single-redeploy escape hatch.
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
# K44 · fresh loop + Motor client bound to it, mirroring K33's
# rebind pattern so this file doesn't interfere with the shared
# event loop used elsewhere.
_LOOP = asyncio.new_event_loop()
_K44_MOTOR = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
_K44_DB = _K44_MOTOR[os.environ["DB_NAME"]]


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _drop_all_k44_indexes():
    """Drop every K44 index + its diagnostic sentinel row so tests
    start from a clean slate."""
    from migrations.k44_perf_indexes import _INDEXES
    _sync.migrations.delete_one({"id": "k44_perf_indexes_v1"})
    for coll, name, _ in _INDEXES:
        try:
            _sync[coll].drop_index(name)
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture
def clean_k44():
    _drop_all_k44_indexes()
    yield
    _drop_all_k44_indexes()


@pytest.fixture
def rebind_db(monkeypatch):
    """Rebind ``config.db`` + the migration module's ``db`` handle
    to the K44-loop-bound client."""
    import config as _config_mod
    from migrations import k44_perf_indexes as _k44_mod
    monkeypatch.setattr(_config_mod, "db", _K44_DB)
    monkeypatch.setattr(_k44_mod, "db", _K44_DB)
    yield


# ── Migration behaviour ──────────────────────────────────────────
def test_k44_first_run_creates_indexes_and_writes_sentinel(
    clean_k44, rebind_db,
):
    from migrations.k44_perf_indexes import run as _k44_run, _INDEXES
    res = _run(_k44_run())
    assert res["status"] == "ok"
    s = res["summary"]
    # Every declared index landed as either "created" or
    # "already_present" (some may already be there from earlier
    # migrations like K21 that shipped on preview).
    assert s["created"] + s["already_present"] == len(_INDEXES)
    assert s["errors"] == []
    # Every K44 index now exists on its collection.
    for coll, name, _ in _INDEXES:
        names = {i["name"] for i in _sync[coll].list_indexes()}
        assert name in names, f"{coll}.{name} missing after K44 run"
    # Diagnostic sentinel landed.
    sentinel = _sync.migrations.find_one({"id": "k44_perf_indexes_v1"})
    assert sentinel is not None
    assert "last_run_at" in sentinel


def test_k44_second_run_is_pure_idempotent_no_op(clean_k44, rebind_db):
    from migrations.k44_perf_indexes import run as _k44_run, _INDEXES
    _run(_k44_run())
    res = _run(_k44_run())
    assert res["status"] == "ok"
    s = res["summary"]
    # After the first run every index exists, so the second run
    # must report zero created + everything already_present.
    assert s["created"] == 0
    assert s["already_present"] == len(_INDEXES)
    assert s["errors"] == []


def test_k44_ignores_missing_sentinel_and_still_runs(
    clean_k44, rebind_db,
):
    """Drop the K44 diagnostic sentinel between runs — the second
    run must STILL succeed (proving the migration is NOT gated on
    the sentinel, unlike K15/K21). This is the whole point of K44:
    a corrupted migrations collection cannot re-break prod perf."""
    from migrations.k44_perf_indexes import run as _k44_run, _INDEXES
    _run(_k44_run())
    _sync.migrations.delete_one({"id": "k44_perf_indexes_v1"})
    res = _run(_k44_run())
    assert res["status"] == "ok"
    assert res["summary"]["created"] == 0
    assert res["summary"]["already_present"] == len(_INDEXES)


# ── boot_flags.should_run_startup_indexes() K44 override ─────────
def test_boot_flags_k44_prod_opt_in_override(monkeypatch):
    """Prod redeploys can now flip startup indexing back on with a
    single ``RUN_STARTUP_INDEXES=true`` env change — no code rebuild
    needed."""
    import boot_flags
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("RUN_STARTUP_INDEXES", "true")
    assert boot_flags.should_run_startup_indexes() is True


def test_boot_flags_prod_default_remains_lean(monkeypatch):
    """Unset env in prod continues to skip startup indexes so cold-
    start latency budget is preserved for pods that don't need the
    self-heal."""
    import boot_flags
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("RUN_STARTUP_INDEXES", raising=False)
    assert boot_flags.should_run_startup_indexes() is False


def test_boot_flags_prod_explicit_false_still_wins(monkeypatch):
    """Belt-and-suspenders: explicit false in ANY env means false,
    even if a future refactor accidentally relaxes prod defaults."""
    import boot_flags
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("RUN_STARTUP_INDEXES", "false")
    assert boot_flags.should_run_startup_indexes() is False


def test_boot_flags_preview_default_stays_on(monkeypatch):
    import boot_flags
    monkeypatch.setenv("APP_ENV", "preview")
    monkeypatch.delenv("RUN_STARTUP_INDEXES", raising=False)
    assert boot_flags.should_run_startup_indexes() is True
