"""P1 PERF-HOTFIX · Feb-2026 — Customer-profile mount index safety-net
migration tests.

Pins the three contracts of
``services/migrations/perf_customer_profile_mount.py``:

  1. 8 target shapes are declared (jobs×2, quotes×2, properties,
     service_reports, messages, customers) with the exact key
     specs matched to the audit-identified queries.
  2. ``_prefix_covers`` correctly accepts an index whose keys
     START WITH the target key list in order with matching
     directions, and rejects direction-mismatch and length-short.
  3. ``run_perf_customer_profile_mount_migration`` is idempotent
     and sentinel-guarded — a second run under the same sentinel
     short-circuits to ``status=skipped`` without touching Mongo.
     Targets already covered by a prefix-matching index skip the
     ``create_index`` call entirely (prod safety).
"""
from __future__ import annotations

import asyncio
from typing import Dict, List, Tuple
from unittest.mock import AsyncMock, MagicMock


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ─── Target catalogue + prefix helper ────────────────────────────

def test_targets_catalogue_matches_audit_shapes():
    """The 8 target entries must exactly match the index shapes
    identified in the PERF-HOTFIX audit as the critical mount
    compounds."""
    from services.migrations import perf_customer_profile_mount as m
    collections = [t[0] for t in m._TARGETS]
    assert collections.count("jobs") == 2
    assert collections.count("quotes") == 2
    assert collections.count("properties") == 1
    assert collections.count("service_reports") == 1
    assert collections.count("messages") == 1
    assert collections.count("customers") == 1
    assert len(m._TARGETS) == 8

    # Spot-check the exact spec of each hot-path query.
    specs = {(c, n): k for c, n, k in m._TARGETS}
    assert specs[("jobs", "pcpm_jobs_tenant_customer_sched_desc")] == [
        ("tenant_id", 1), ("customer_id", 1), ("scheduled_date", -1),
    ]
    assert specs[(
        "quotes",
        "pcpm_quotes_tenant_customer_doctype_created_desc",
    )] == [
        ("tenant_id", 1), ("customer_id", 1),
        ("doc_type", 1), ("created_at", -1),
    ]
    assert specs[(
        "service_reports",
        "pcpm_service_reports_tenant_customer_submitted_desc",
    )] == [
        ("tenant_id", 1), ("customer_id", 1), ("submitted_at", -1),
    ]
    assert specs[(
        "messages", "pcpm_messages_tenant_customer_sender_read",
    )] == [
        ("tenant_id", 1), ("customer_id", 1),
        ("sender", 1), ("read_by_staff", 1),
    ]


def test_prefix_covers_accepts_exact_and_longer_prefix_match():
    from services.migrations.perf_customer_profile_mount import (
        _prefix_covers,
    )
    target = [("tenant_id", 1), ("customer_id", 1),
              ("scheduled_date", -1)]
    # Exact match.
    assert _prefix_covers(target, target) is True
    # Longer compound with target as a prefix.
    existing = target + [("status", 1)]
    assert _prefix_covers(existing, target) is True


def test_prefix_covers_rejects_direction_mismatch_and_short_prefix():
    from services.migrations.perf_customer_profile_mount import (
        _prefix_covers,
    )
    target = [("tenant_id", 1), ("customer_id", 1),
              ("scheduled_date", -1)]
    # Direction mismatch on the sort field — rejected.
    bad_dir = [("tenant_id", 1), ("customer_id", 1),
               ("scheduled_date", 1)]
    assert _prefix_covers(bad_dir, target) is False
    # Index shorter than the target — rejected.
    short = [("tenant_id", 1), ("customer_id", 1)]
    assert _prefix_covers(short, target) is False
    # Field-order mismatch — rejected.
    swapped = [("customer_id", 1), ("tenant_id", 1),
               ("scheduled_date", -1)]
    assert _prefix_covers(swapped, target) is False


# ─── run_perf_customer_profile_mount_migration ───────────────────

class _FakeIndexCollection:
    """Stubs just ``index_information`` + ``create_index`` for one
    collection. Records every create_index call."""
    def __init__(self, existing_indexes: Dict[str, List[Tuple[str, int]]]):
        self._existing = {
            n: [{"key": [list(t) for t in keys]}, keys]
            for n, keys in existing_indexes.items()
        }
        self._raw = existing_indexes
        self.create_index_calls: List[Tuple[list, str]] = []

    async def index_information(self):
        return {
            n: {"key": list(keys)}
            for n, keys in self._raw.items()
        }

    async def create_index(self, keys, name, background=True):
        self.create_index_calls.append((list(keys), name))
        return name


class _FakeDB:
    """Container matching the shape used by the migration module."""
    def __init__(self, collections: Dict[str, _FakeIndexCollection],
                 sentinel_present: bool = False):
        self._colls = collections
        self.migrations = MagicMock()
        self.migrations.find_one = AsyncMock(
            return_value=(
                {"id": "pcpm_customer_profile_mount_v1"}
                if sentinel_present else None
            ),
        )
        self.migrations.update_one = AsyncMock()

    def __getitem__(self, name):
        return self._colls[name]


def _all_eight_target_collections(stub=None):
    """Build an empty-index fake-db covering the 8 target collections."""
    from services.migrations import perf_customer_profile_mount as m
    coll_names = {t[0] for t in m._TARGETS}
    stub = stub or {}
    return {
        c: _FakeIndexCollection(stub.get(c, {}))
        for c in coll_names
    }


def test_run_short_circuits_on_sentinel():
    """Second-boot ``run_...()`` returns ``status=skipped`` without
    touching ``create_index``."""
    import importlib
    from services.migrations import perf_customer_profile_mount as m
    from services.migrations import perf_customer_profile_mount
    orig_db = perf_customer_profile_mount.db
    fake_db = _FakeDB(_all_eight_target_collections(), sentinel_present=True)
    perf_customer_profile_mount.db = fake_db
    try:
        res = _run(m.run_perf_customer_profile_mount_migration())
        assert res["status"] == "skipped"
        assert res["reason"] == "sentinel_present"
        # No index creation attempted on any collection.
        for coll in fake_db._colls.values():
            assert coll.create_index_calls == []
    finally:
        perf_customer_profile_mount.db = orig_db


def test_run_creates_all_when_no_indexes_exist():
    """Fresh collections with zero prior indexes → 8 create_index
    calls, one per target, using the declared fallback name."""
    from services.migrations import perf_customer_profile_mount as m
    orig_db = m.db
    fake_db = _FakeDB(_all_eight_target_collections())
    m.db = fake_db
    try:
        res = _run(m.run_perf_customer_profile_mount_migration())
        assert res["status"] == "ok"
        s = res["summary"]
        assert s["created"] == 8
        assert s["already_present"] == 0
        assert s["already_covered_by_prefix"] == 0
        assert s["errors"] == []
        # Sentinel written exactly once at the end.
        fake_db.migrations.update_one.assert_called_once()
    finally:
        m.db = orig_db


def test_run_skips_when_existing_index_covers_prefix():
    """Preview case — every target shape is covered by an existing
    compound (different name). Expected: zero creates, 8 counted
    under ``already_covered_by_prefix``."""
    from services.migrations import perf_customer_profile_mount as m
    orig_db = m.db
    # Build a per-collection stub where each target shape is covered
    # by an existing index with a distinct (production-like) name.
    # Note: jobs + quotes have 2 target shapes each, so each
    # legacy-stub name must be unique PER SHAPE (not per collection).
    stub: Dict[str, Dict[str, List[Tuple[str, int]]]] = {}
    for i, (coll, _idx_name, keys) in enumerate(m._TARGETS):
        stub.setdefault(coll, {})[f"legacy_{coll}_ix_{i}"] = list(keys)
    fake_db = _FakeDB(_all_eight_target_collections(stub))
    m.db = fake_db
    try:
        res = _run(m.run_perf_customer_profile_mount_migration())
        assert res["status"] == "ok"
        s = res["summary"]
        assert s["created"] == 0
        assert s["already_covered_by_prefix"] == 8
        for coll in fake_db._colls.values():
            assert coll.create_index_calls == [], (
                "no create_index may fire when the shape is "
                "already covered by a prefix of an existing index"
            )
    finally:
        m.db = orig_db


def test_run_counts_already_present_by_exact_name_match():
    """Target name is already present on the collection — the
    migration counts it under ``already_present`` (NOT
    ``already_covered_by_prefix``) and skips create_index."""
    from services.migrations import perf_customer_profile_mount as m
    orig_db = m.db
    stub = {}
    for coll, idx_name, keys in m._TARGETS:
        stub.setdefault(coll, {})[idx_name] = list(keys)
    fake_db = _FakeDB(_all_eight_target_collections(stub))
    m.db = fake_db
    try:
        res = _run(m.run_perf_customer_profile_mount_migration())
        s = res["summary"]
        assert s["already_present"] == 8
        assert s["created"] == 0
        assert s["already_covered_by_prefix"] == 0
    finally:
        m.db = orig_db
