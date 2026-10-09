"""Feb-2026 · Pool Service Report — inclusive-count fix.

Locks the backend contract introduced to resolve the "Pool Service
Report undercounting" bug (user-approved option (a)+(ii) — additive,
non-breaking):

  * ``total_completed_all`` — top-level sum of every COMPLETED pool
    job (service + repair + other), independent of ``work_class``.
  * Per-tech ``completed_all`` — same sum scoped to a single
    technician row.
  * ``dropped_count`` — count of pool jobs in the window whose
    status is neither ``completed`` nor in ``SKIPPED_STATUSES``
    (e.g. ``scheduled``, ``in_progress``, ``pending``).  These are
    silently excluded by the legacy aggregator and now surfaced so
    admins can tell "nothing happened" apart from "we quietly
    dropped seven jobs with abnormal statuses".

Legacy fields MUST NOT change semantics:

  * ``total_completed`` continues to count ONLY service visits
    (``pools_serviced``).  A repair never inflates it.
  * ``totals.pools_serviced`` / ``totals.repairs_completed`` /
    ``summary.*`` / per-row ``completed`` are unchanged.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest


# ─── Shared minimal fake Mongo (lifted from the sibling bucketing
#     test to keep this file self-contained — same pattern) ────────
_MISSING = object()


class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def __aiter__(self):
        async def _gen():
            for r in self._rows:
                yield r
        return _gen()

    async def to_list(self, length=None):
        return list(self._rows[: length or len(self._rows)])


class _FakeCollection:
    def __init__(self):
        self.rows = []

    def find(self, query=None, projection=None):
        return _FakeCursor([r for r in self.rows if self._match(r, query or {})])

    def _match(self, row, query):
        if "$and" in query:
            return all(self._match(row, s) for s in query["$and"])
        if "$or" in query:
            return any(self._match(row, s) for s in query["$or"])
        for k, v in query.items():
            if k in ("$and", "$or"):
                continue
            got = row.get(k, _MISSING)
            if isinstance(v, dict):
                if "$in" in v and got not in v["$in"]:
                    return False
                if "$nin" in v and got in v["$nin"]:
                    return False
                if "$exists" in v:
                    if v["$exists"] and got is _MISSING:
                        return False
                    if (not v["$exists"]) and got is not _MISSING:
                        return False
                if "$ne" in v and got == v["$ne"]:
                    return False
                if "$gte" in v:
                    if got is _MISSING or got < v["$gte"]:
                        return False
                if "$lte" in v:
                    if got is _MISSING or got > v["$lte"]:
                        return False
                if "$regex" in v:
                    import re as _re
                    flags = _re.IGNORECASE if v.get("$options") == "i" else 0
                    if got is _MISSING or not isinstance(got, str):
                        return False
                    if not _re.search(v["$regex"], got, flags):
                        return False
            else:
                if got is _MISSING:
                    if v is None:
                        continue
                    return False
                if got != v:
                    return False
        return True


class _FakeDb:
    def __init__(self):
        self.users = _FakeCollection()
        self.technicians = _FakeCollection()
        self.jobs = _FakeCollection()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _seed_users(db_):
    db_.users.rows = [
        {"id": "u-alice", "tenant_id": "tA", "role": "technician",
         "technician_id": "tech-alice", "name": "Alice Adams",
         "active": True},
        {"id": "u-bob", "tenant_id": "tA", "role": "technician",
         "technician_id": "tech-bob", "name": "Bob Brown",
         "active": True},
    ]


# ────────────────────────────────────────────────────────────────────
#  Core assertions
# ────────────────────────────────────────────────────────────────────

def test_total_completed_all_sums_service_repair_and_other():
    """``total_completed_all`` is the sum of every COMPLETED pool
    job regardless of ``work_class`` — service + repair + other.
    Legacy ``total_completed`` keeps the service-only semantic."""
    from routers import jobs as _mod
    db_ = _FakeDb()
    _seed_users(db_)
    db_.jobs.rows = [
        # 2 service completions for Alice
        {"id": "a1", "tenant_id": "tA", "technician_id": "tech-alice",
         "technician_name": "Alice Adams", "service_type": "Pool Cleaning",
         "work_class": "service", "status": "completed",
         "scheduled_date": "2026-02-16"},
        {"id": "a2", "tenant_id": "tA", "technician_id": "tech-alice",
         "technician_name": "Alice Adams", "service_type": "Pool Cleaning",
         "work_class": "service", "status": "completed",
         "scheduled_date": "2026-02-17"},
        # 1 repair completion for Bob
        {"id": "b1", "tenant_id": "tA", "technician_id": "tech-bob",
         "technician_name": "Bob Brown", "service_type": "Pool Pump Repair",
         "work_class": "repair", "status": "completed",
         "scheduled_date": "2026-02-18"},
        # 1 completion with unknown work_class for Bob → "other"
        {"id": "b2", "tenant_id": "tA", "technician_id": "tech-bob",
         "technician_name": "Bob Brown", "service_type": "Pool Inspection",
         "work_class": None, "status": "completed",
         "scheduled_date": "2026-02-19"},
    ]
    with patch.object(_mod, "db", db_):
        rep = _run(_mod.compute_pool_service(
            "tA", date_from="2026-02-16", date_to="2026-02-22"))

    # Legacy semantic preserved — service-only.
    assert rep["total_completed"] == 2, (
        f"legacy total_completed must remain service-only; got "
        f"{rep['total_completed']}"
    )
    # New inclusive count.
    assert rep["total_completed_all"] == 4, (
        f"total_completed_all must be service+repair+other "
        f"(2+1+1=4); got {rep['total_completed_all']}"
    )
    # Breakdown still intact.
    assert rep["totals"]["pools_serviced"] == 2
    assert rep["totals"]["repairs_completed"] == 1
    assert rep["summary"]["other_visits"] == 1


def test_dropped_count_captures_non_terminal_statuses():
    """Pool jobs with a status outside completed/skipped (e.g.
    ``scheduled``, ``in_progress``, ``pending``) feed
    ``dropped_count`` and are excluded from every other bucket."""
    from routers import jobs as _mod
    db_ = _FakeDb()
    _seed_users(db_)
    db_.jobs.rows = [
        # 1 completed service — counted
        {"id": "ok", "tenant_id": "tA", "technician_id": "tech-alice",
         "technician_name": "Alice Adams", "service_type": "Pool Cleaning",
         "work_class": "service", "status": "completed",
         "scheduled_date": "2026-02-16"},
        # 3 non-terminal statuses → dropped
        {"id": "s1", "tenant_id": "tA", "technician_id": "tech-alice",
         "technician_name": "Alice Adams", "service_type": "Pool Cleaning",
         "work_class": "service", "status": "scheduled",
         "scheduled_date": "2026-02-17"},
        {"id": "ip", "tenant_id": "tA", "technician_id": "tech-alice",
         "technician_name": "Alice Adams", "service_type": "Pool Cleaning",
         "work_class": "service", "status": "in_progress",
         "scheduled_date": "2026-02-18"},
        {"id": "pd", "tenant_id": "tA", "technician_id": "tech-bob",
         "technician_name": "Bob Brown", "service_type": "Pool Cleaning",
         "work_class": "service", "status": "pending",
         "scheduled_date": "2026-02-19"},
        # 1 skipped — counted in ``skipped``, NOT ``dropped``
        {"id": "sk", "tenant_id": "tA", "technician_id": "tech-bob",
         "technician_name": "Bob Brown", "service_type": "Pool Cleaning",
         "work_class": "service", "status": "skipped",
         "scheduled_date": "2026-02-20"},
    ]
    with patch.object(_mod, "db", db_):
        rep = _run(_mod.compute_pool_service(
            "tA", date_from="2026-02-16", date_to="2026-02-22"))

    assert rep["dropped_count"] == 3, (
        f"3 non-terminal pool jobs must feed dropped_count; got "
        f"{rep['dropped_count']}"
    )
    # The skipped visit must NOT leak into dropped.
    assert rep["total_skipped"] == 1
    # And the one completed job must still be counted.
    assert rep["total_completed"] == 1
    assert rep["total_completed_all"] == 1


def test_per_tech_completed_all_matches_per_tech_sum():
    """Each ``by_technician`` row exposes ``completed_all`` and it
    equals the row's own ``pools_serviced + repairs_completed +
    other``.  The sum across rows equals ``total_completed_all``."""
    from routers import jobs as _mod
    db_ = _FakeDb()
    _seed_users(db_)
    db_.jobs.rows = [
        {"id": "a1", "tenant_id": "tA", "technician_id": "tech-alice",
         "technician_name": "Alice Adams", "service_type": "Pool Cleaning",
         "work_class": "service", "status": "completed",
         "scheduled_date": "2026-02-16"},
        {"id": "a2", "tenant_id": "tA", "technician_id": "tech-alice",
         "technician_name": "Alice Adams", "service_type": "Pool Pump Repair",
         "work_class": "repair", "status": "completed",
         "scheduled_date": "2026-02-17"},
        {"id": "b1", "tenant_id": "tA", "technician_id": "tech-bob",
         "technician_name": "Bob Brown", "service_type": "Pool Inspection",
         "work_class": None, "status": "completed",
         "scheduled_date": "2026-02-18"},
    ]
    with patch.object(_mod, "db", db_):
        rep = _run(_mod.compute_pool_service(
            "tA", date_from="2026-02-16", date_to="2026-02-22"))

    rows = {r["technician_id"]: r for r in rep["by_technician"]}
    alice = rows["tech-alice"]
    bob = rows["tech-bob"]

    # Alice: 1 service + 1 repair = 2 completed_all
    assert alice["completed_all"] == 2
    assert alice["completed_all"] == (
        alice["pools_serviced"]
        + alice["repairs_completed"]
        + alice["other"]
    )
    # Bob: 1 other = 1 completed_all
    assert bob["completed_all"] == 1
    assert bob["completed_all"] == (
        bob["pools_serviced"]
        + bob["repairs_completed"]
        + bob["other"]
    )
    # Sum of per-tech completed_all equals top-level total.
    assert (alice["completed_all"] + bob["completed_all"]) == \
        rep["total_completed_all"] == 3


def test_zero_jobs_returns_zero_counts_not_missing_fields():
    """Empty window — the new fields are still present and equal 0
    so the frontend never needs defensive null-coalescing on the
    fast path."""
    from routers import jobs as _mod
    db_ = _FakeDb()
    _seed_users(db_)
    db_.jobs.rows = []
    with patch.object(_mod, "db", db_):
        rep = _run(_mod.compute_pool_service(
            "tA", date_from="2026-02-16", date_to="2026-02-22"))
    assert rep["total_completed_all"] == 0
    assert rep["dropped_count"] == 0
    assert rep["by_technician"] == []


def test_legacy_total_completed_unchanged_when_only_repairs():
    """A regression guard — a window with ONLY repair completions
    must keep ``total_completed == 0`` (service-only) even though
    ``total_completed_all`` sees the repairs."""
    from routers import jobs as _mod
    db_ = _FakeDb()
    _seed_users(db_)
    db_.jobs.rows = [
        {"id": "r1", "tenant_id": "tA", "technician_id": "tech-alice",
         "technician_name": "Alice Adams", "service_type": "Pool Pump Repair",
         "work_class": "repair", "status": "completed",
         "scheduled_date": "2026-02-16"},
        {"id": "r2", "tenant_id": "tA", "technician_id": "tech-alice",
         "technician_name": "Alice Adams", "service_type": "Pool Pump Repair",
         "work_class": "repair", "status": "completed",
         "scheduled_date": "2026-02-17"},
    ]
    with patch.object(_mod, "db", db_):
        rep = _run(_mod.compute_pool_service(
            "tA", date_from="2026-02-16", date_to="2026-02-22"))
    assert rep["total_completed"] == 0, (
        "legacy total_completed must stay service-only even when "
        "the window is 100%% repairs"
    )
    assert rep["total_completed_all"] == 2
    assert rep["totals"]["repairs_completed"] == 2
