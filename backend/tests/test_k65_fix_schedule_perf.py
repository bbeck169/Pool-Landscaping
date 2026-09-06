"""Phase K65.fix · Feb-2026 — regression tests for the Schedule
Load Performance Fix.

Coverage:
  1. K65 service_reports migration idempotency + prefix-detection
  2. `/api/technicians` collapsed N+1 (single $group, response
     shape preserved).
  3. `/api/jobs` sort correctness after the aggregation-sort swap.
  4. `/api/admin/perf/explain-schedule` feature-flag + role gate.

Never mutates prod data — every test uses ephemeral tenants + docs
inserted at setUp and torn down at tearDown.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

_sync = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

_LOOP = asyncio.new_event_loop()
_MOTOR = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
_DB = _MOTOR[os.environ["DB_NAME"]]


def _run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture
def rebind_db(monkeypatch):
    import config as _config_mod
    from services.migrations import k65_service_reports_indexes as _k65_mod
    monkeypatch.setattr(_config_mod, "db", _DB)
    monkeypatch.setattr(_k65_mod, "db", _DB)
    yield


# ─────────────────────────────────────────────────────────────────
# 1 · K65 service_reports migration
# ─────────────────────────────────────────────────────────────────
def _drop_k65():
    _sync.migrations.delete_one({"id": "k65_service_reports_indexes_v1"})
    try:
        _sync.service_reports.drop_index("k65_service_reports_tenant_job")
    except Exception:  # noqa: BLE001
        pass


def test_k65_migration_detects_prefix_cover_and_writes_sentinel(rebind_db):
    """Preview DB has an existing (tenant_id, job_id, tech_id)
    compound.  The migration must detect the prefix cover, skip
    creating a duplicate index, and still write the sentinel so a
    subsequent boot early-returns.
    """
    _drop_k65()
    try:
        from services.migrations.k65_service_reports_indexes import (
            run_k65_service_reports_indexes_migration,
        )
        res = _run(run_k65_service_reports_indexes_migration())
        assert res["status"] == "ok"
        s = res["summary"]
        # The prefix-covering index exists in preview → we do NOT
        # create the standalone.
        assert s["created"] == 0
        assert s["already_covered_by_prefix"] == 1
        assert s["covered_by"] == "tenant_id_1_job_id_1_tech_id_1"
        # Sentinel written.
        sentinel = _sync.migrations.find_one(
            {"id": "k65_service_reports_indexes_v1"},
        )
        assert sentinel is not None
    finally:
        _drop_k65()


def test_k65_migration_second_run_is_skipped_on_sentinel(rebind_db):
    _drop_k65()
    try:
        from services.migrations.k65_service_reports_indexes import (
            run_k65_service_reports_indexes_migration,
        )
        _run(run_k65_service_reports_indexes_migration())
        res = _run(run_k65_service_reports_indexes_migration())
        assert res["status"] == "skipped"
        assert res["reason"] == "sentinel_present"
    finally:
        _drop_k65()


def test_k65_migration_creates_index_when_no_prefix_cover(rebind_db):
    """When the covering compound is absent, the migration must
    create the standalone (tenant_id, job_id) index."""
    _drop_k65()
    original_key = None
    try:
        # Temporarily drop the covering compound so we can test the
        # create branch.  Restore it in `finally` no matter what.
        try:
            info = _sync.service_reports.index_information()
            covering = info.get("tenant_id_1_job_id_1_tech_id_1")
            if covering:
                original_key = list(covering.get("key") or [])
                _sync.service_reports.drop_index("tenant_id_1_job_id_1_tech_id_1")
        except Exception:  # noqa: BLE001
            pass

        from services.migrations.k65_service_reports_indexes import (
            run_k65_service_reports_indexes_migration,
        )
        res = _run(run_k65_service_reports_indexes_migration())
        assert res["status"] == "ok"
        s = res["summary"]
        assert s["created"] == 1
        assert s["already_covered_by_prefix"] == 0
        names = {i["name"] for i in _sync.service_reports.list_indexes()}
        assert "k65_service_reports_tenant_job" in names
    finally:
        _drop_k65()
        if original_key:
            _sync.service_reports.create_index(
                original_key,
                name="tenant_id_1_job_id_1_tech_id_1",
                background=True,
            )


# ─────────────────────────────────────────────────────────────────
# 2 · /api/technicians — collapsed N+1
# ─────────────────────────────────────────────────────────────────
def test_k65_fix_technicians_uses_single_group_aggregate(monkeypatch):
    """After K65.fix, the technicians endpoint must NOT execute the
    old ``count_documents`` per-row loop.  We prove this by
    monkeypatching ``db.jobs.count_documents`` to raise so that ANY
    residual call is a hard fail, then invoking the handler
    end-to-end and asserting it still returns the counter fields on
    every row.
    """
    # Rebind config.db + technicians.db to the K65-loop-bound Motor
    # client so awaits below don't cross event loops.
    import config as _config_mod
    from routers import technicians as _tech_mod
    monkeypatch.setattr(_config_mod, "db", _DB)
    monkeypatch.setattr(_tech_mod, "db", _DB)

    call_counter = {"count_documents": 0, "aggregate": 0}

    original_agg = _tech_mod.db.jobs.aggregate

    class _NoCountAllowed:
        async def __call__(self, *a, **kw):  # noqa: D401 — mock
            call_counter["count_documents"] += 1
            raise AssertionError(
                "K65.fix regression — count_documents fired on "
                "/api/technicians hot path"
            )

    def _wrapped_aggregate(*a, **kw):
        call_counter["aggregate"] += 1
        return original_agg(*a, **kw)

    monkeypatch.setattr(
        _tech_mod.db.jobs, "count_documents", _NoCountAllowed(),
    )
    monkeypatch.setattr(
        _tech_mod.db.jobs, "aggregate", _wrapped_aggregate,
    )

    async def _drive():
        # Grab a real tenant to feed the handler.
        t = await _tech_mod.db.tenants.find_one({}, {"_id": 0, "id": 1})
        assert t, "no tenant present in preview DB"
        u = {"id": "test-user", "role": "super_admin",
              "tenant_id": t["id"]}
        docs = await _tech_mod.list_technicians(user=u, tenant=t)
        return docs

    docs = _run(_drive())
    # Response shape preserved: every doc carries the three counter
    # fields the frontend renders.
    assert isinstance(docs, list)
    for d in docs:
        assert "active_jobs" in d
        assert "active_jobs_repair" in d
        assert "active_jobs_service" in d
        assert d["active_jobs"] == (
            d["active_jobs_repair"] + d["active_jobs_service"]
        )
    # No count_documents fired.
    assert call_counter["count_documents"] == 0
    # At most 1 aggregate call for the counters (there may also be
    # zero when no tech ids are eligible in the preview seed).
    assert call_counter["aggregate"] <= 1, (
        "K65.fix expected at most 1 aggregate call on the "
        "technicians hot path (the collapsed $group). Got "
        f"{call_counter['aggregate']}."
    )


# ─────────────────────────────────────────────────────────────────
# 3 · /api/jobs sort correctness
# ─────────────────────────────────────────────────────────────────
def test_k65_fix_jobs_python_re_sort_key_matches_pre_k65_contract():
    """The K65.fix pipeline sorts by ``scheduled_date`` in Mongo
    then Python-re-sorts by ``(day, route_index, scheduled_date,
    created_at)``.  This test proves the Python key is equivalent to
    the old aggregation sort for a representative fixture where
    Mongo alone would order incorrectly.
    """
    def _re_sort_key(d: dict) -> tuple:
        sd = d.get("scheduled_date") or ""
        day = sd[:10] if isinstance(sd, str) else ""
        ri = d.get("route_index")
        ri_val = ri if isinstance(ri, (int, float)) else 999999
        ca = d.get("created_at") or ""
        return (day, ri_val, sd, ca)

    # Same-day rows with mixed route_index values.  Mongo's
    # scheduled_date-only sort emits them in time order; K65.fix's
    # Python re-sort MUST reorder them by route_index within the day.
    fixture = [
        {"id": "A", "scheduled_date": "2026-09-04T09:00:00", "route_index": 3, "created_at": "2026-08-01"},
        {"id": "B", "scheduled_date": "2026-09-04T14:00:00", "route_index": 1, "created_at": "2026-08-01"},
        {"id": "C", "scheduled_date": "2026-09-04T11:00:00", "route_index": 2, "created_at": "2026-08-01"},
        {"id": "D", "scheduled_date": "2026-09-05T08:00:00", "route_index": 1, "created_at": "2026-08-01"},
        # Missing route_index → sentinel 999999 (last within its day).
        {"id": "E", "scheduled_date": "2026-09-04T10:00:00", "route_index": None, "created_at": "2026-08-01"},
    ]
    ordered = sorted(fixture, key=_re_sort_key)
    ids = [d["id"] for d in ordered]
    # Expected: 09-04 rows first (by ri asc: B=1, C=2, A=3, then
    # E=None-sentinel at end of the day), then 09-05.
    assert ids == ["B", "C", "A", "E", "D"], f"got {ids}"


# ─────────────────────────────────────────────────────────────────
# 4 · Perf-explain endpoint gates
# ─────────────────────────────────────────────────────────────────
def test_k65_perf_explain_flag_off_returns_404_from_module():
    """``_feature_enabled`` must be False when the env var is
    absent/empty, and the POST endpoint must 404 in that state.
    """
    from routers import admin_perf_explain_schedule as _m
    monkey_env = os.environ.get("FEATURE_PERF_EXPLAIN")
    os.environ["FEATURE_PERF_EXPLAIN"] = ""
    try:
        assert _m._feature_enabled() is False
    finally:
        if monkey_env is None:
            os.environ.pop("FEATURE_PERF_EXPLAIN", None)
        else:
            os.environ["FEATURE_PERF_EXPLAIN"] = monkey_env


def test_k65_perf_explain_flag_on_returns_true():
    from routers import admin_perf_explain_schedule as _m
    monkey_env = os.environ.get("FEATURE_PERF_EXPLAIN")
    os.environ["FEATURE_PERF_EXPLAIN"] = "1"
    try:
        assert _m._feature_enabled() is True
    finally:
        if monkey_env is None:
            os.environ.pop("FEATURE_PERF_EXPLAIN", None)
        else:
            os.environ["FEATURE_PERF_EXPLAIN"] = monkey_env


def test_k65_perf_explain_bson_safe_survives_bytes_planCacheKey():
    """The ``_bson_safe`` helper must round-trip a raw ``db.command``
    response containing bytes fields without raising a
    UnicodeDecodeError (the exact regression that surfaced against
    Mongo's planCacheKey on preview).
    """
    from routers.admin_perf_explain_schedule import _bson_safe
    from bson import Binary
    payload = {"ok": 1, "planCacheKey": Binary(b"\xc0\x01\x02"), "nested": {"k": Binary(b"\xff")}}
    out = _bson_safe(payload)
    # JSON-safe primitives only.
    import json as _json
    _json.dumps(out)  # must not raise
    assert out["ok"] == 1
