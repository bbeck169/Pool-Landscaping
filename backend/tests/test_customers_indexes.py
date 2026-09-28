"""SEARCH-SPEED · Feb-2026 — Customers perf-indexes bootstrap tests.

Locks the contract for
``services.customers_perf_indexes.ensure_customers_perf_indexes``:

  * All five compound indexes are registered by name.
  * Each carries the expected key spec (order + direction).
  * The bootstrap is idempotent — a second call reports 0 created,
    5 already-present, 0 errors.
  * Batch-fallback path: if a single index name conflicts with an
    existing definition, other indexes still land.

Uses a lightweight recording DB stub so the test can run without
touching real Mongo — same approach as
``test_tenant_ai_rules_schema.py``.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

from services.customers_perf_indexes import (
    INDEX_NAMES,
    ensure_customers_perf_indexes,
)


EXPECTED_NAMES = {
    "customers_tenant_deleted_created_desc_bg",
    "customers_tenant_deleted_updated_desc_bg",
    "customers_tenant_deleted_name_bg",
    "customers_tenant_deleted_email_bg",
    "customers_tenant_deleted_phone_bg",
}


class _RecordingColl:
    def __init__(self, preloaded=None):
        self.calls_batch = []
        self.calls_single = []
        self._preloaded = list(preloaded or [])

    async def create_indexes(self, models):
        self.calls_batch.append(list(models))
        for m in models:
            self._preloaded.append({"name": m.document["name"],
                                     "key": m.document["key"]})

    async def create_index(self, keys, name=None, **kw):
        self.calls_single.append({"name": name, "keys": list(keys)})
        self._preloaded.append({"name": name, "key": dict(keys)})

    async def list_indexes(self):
        for doc in list(self._preloaded):
            yield doc


class _RecordingDB:
    def __init__(self, preloaded=None):
        self.customers = _RecordingColl(preloaded)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_all_five_indexes_registered_by_name():
    """The service ships exactly five named compound indexes on
    the ``customers`` collection."""
    assert set(INDEX_NAMES) == EXPECTED_NAMES


def test_bootstrap_creates_all_five_indexes():
    db = _RecordingDB(preloaded=[{"name": "_id_", "key": [("_id", 1)]}])
    summary = _run(ensure_customers_perf_indexes(db))
    assert set(summary["created"]) == EXPECTED_NAMES
    assert summary["already"] == []
    assert summary["errors"] == []
    # One batched create_indexes call, five models.
    assert len(db.customers.calls_batch) == 1
    assert len(db.customers.calls_batch[0]) == 5


def test_bootstrap_is_idempotent_when_all_present():
    preloaded = [{"name": "_id_", "key": [("_id", 1)]}] + [
        {"name": n, "key": []} for n in EXPECTED_NAMES
    ]
    db = _RecordingDB(preloaded=preloaded)
    summary = _run(ensure_customers_perf_indexes(db))
    assert set(summary["already"]) == EXPECTED_NAMES
    assert summary["created"] == []
    assert summary["errors"] == []
    # No create_indexes call at all — every index was already
    # registered when we checked ``list_indexes()``.
    assert db.customers.calls_batch == []
    assert db.customers.calls_single == []


def test_bootstrap_partial_present_creates_rest():
    """Half the indexes exist — the other half get created."""
    preloaded = [{"name": "_id_", "key": [("_id", 1)]},
                  {"name": "customers_tenant_deleted_name_bg",
                    "key": []},
                  {"name": "customers_tenant_deleted_email_bg",
                    "key": []}]
    db = _RecordingDB(preloaded=preloaded)
    summary = _run(ensure_customers_perf_indexes(db))
    assert set(summary["already"]) == {
        "customers_tenant_deleted_name_bg",
        "customers_tenant_deleted_email_bg",
    }
    assert set(summary["created"]) == {
        "customers_tenant_deleted_created_desc_bg",
        "customers_tenant_deleted_updated_desc_bg",
        "customers_tenant_deleted_phone_bg",
    }
    # The batched call should have carried the three not-yet-present.
    batch = db.customers.calls_batch[0]
    names = {m.document["name"] for m in batch}
    assert names == set(summary["created"])


def test_batch_failure_falls_back_to_per_index_create():
    """If the batched call raises, the service falls back to per-
    index ``create_index`` so a single bad index doesn't block the
    rest."""

    class _BrittleColl(_RecordingColl):
        async def create_indexes(self, models):
            self.calls_batch.append(list(models))
            raise RuntimeError("batch create failed")

    class _BrittleDB:
        def __init__(self):
            self.customers = _BrittleColl(
                preloaded=[{"name": "_id_", "key": [("_id", 1)]}],
            )

    db = _BrittleDB()
    summary = _run(ensure_customers_perf_indexes(db))
    # All five bounced through the per-index fallback and landed.
    assert set(summary["created"]) == EXPECTED_NAMES
    assert len(db.customers.calls_single) == 5


def test_index_key_specs_are_soft_delete_aware():
    """Every one of the five compounds MUST carry ``deleted_at`` in
    position 2 (right after ``tenant_id``).  That's the whole point
    of SEARCH-SPEED — the earlier ``perf_customers_v2_*`` indexes
    lacked ``deleted_at`` in the prefix, causing the query planner
    to fall back to in-memory ``SORT`` on the customers-list path."""
    from services.customers_perf_indexes import _INDEXES
    for name, keys in _INDEXES:
        assert keys[0][0] == "tenant_id", (
            f"{name} must lead with tenant_id"
        )
        assert keys[1][0] == "deleted_at", (
            f"{name} must carry deleted_at at position 2"
        )
