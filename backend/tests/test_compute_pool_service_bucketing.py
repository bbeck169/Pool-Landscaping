"""Feb 2026 · ``compute_pool_service`` — effective-ID bucketing.

The pool-service tally must bucket by canonical tech identity so:
  * Two jobs with the SAME ``technician_id`` land in ONE row even if
    their stored ``technician_name`` differs (stale + fresh spelling
    of the same person's name — the classic "Ethan Smith duplicate"
    bug).
  * Jobs with only a ``technician_name`` (no id) get a best-effort
    ID rescue via case-insensitive ``db.users.name`` lookup —
    unique match → bucket by resolved id; ambiguous/no match →
    "Unassigned" bucket.
  * Soft-deleted jobs are excluded (``not_deleted_filter``).
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest


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
                    if v is None: continue
                    return False
                if got != v:
                    return False
        return True


_MISSING = object()


class _FakeDb:
    def __init__(self):
        self.users = _FakeCollection()
        self.technicians = _FakeCollection()
        self.jobs = _FakeCollection()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _seed(db_):
    """Seed a canonical tech + one that appears ambiguously as a
    name (two users with the same string ``Ambiguous Al`` on the
    same tenant)."""
    db_.users.rows = [
        {"id": "u-eth", "tenant_id": "tA", "role": "technician",
          "technician_id": "tech-eth", "name": "Ethan Smith",
          "active": True},
        # Two same-name users → ambiguity trigger.
        {"id": "u-am1", "tenant_id": "tA", "role": "technician",
          "technician_id": "tech-am1", "name": "Ambiguous Al"},
        {"id": "u-am2", "tenant_id": "tA", "role": "technician",
          "technician_id": "tech-am2", "name": "Ambiguous Al"},
    ]


def test_compute_pool_service_buckets_by_tech_id_not_name():
    """Two jobs with the SAME ``technician_id`` but DIFFERENT stored
    ``technician_name`` strings must land in ONE bucket."""
    from routers import jobs as _mod
    db_ = _FakeDb()
    _seed(db_)
    db_.jobs.rows = [
        {"id": "j1", "tenant_id": "tA", "technician_id": "tech-eth",
          "technician_name": "Ethan Smith",         # canonical
          "status": "completed", "scheduled_date": "2026-01-06"},
        {"id": "j2", "tenant_id": "tA", "technician_id": "tech-eth",
          "technician_name": "Ethan  Smith",        # stale — extra space
          "status": "completed", "scheduled_date": "2026-01-07"},
        {"id": "j3", "tenant_id": "tA", "technician_id": "tech-eth",
          "technician_name": "E. Smith",            # stale — nickname
          "status": "skipped", "scheduled_date": "2026-01-08"},
    ]
    with patch.object(_mod, "db", db_):
        rep = _run(_mod.compute_pool_service(
            "tA", date_from="2026-01-06", date_to="2026-01-12"))
    # ONE row for Ethan (id-based bucketing).
    tech_rows = [r for r in rep["rows"]
                   if r.get("technician_id") == "tech-eth"]
    assert len(tech_rows) == 1
    row = tech_rows[0]
    assert row["completed"] == 2
    assert row["skipped"] == 1
    # Resolver's canonical name wins over any stale spelling.
    assert row["technician_name"] == "Ethan Smith"
    assert row["technician_active"] is True


def test_compute_pool_service_no_tech_id_but_name_resolves_uniquely():
    """A job with only ``technician_name`` (no id) gets a
    best-effort rescue via case-insensitive users.name lookup —
    unique match → bucket by resolved technician_id."""
    from routers import jobs as _mod
    db_ = _FakeDb()
    _seed(db_)
    db_.jobs.rows = [
        {"id": "jn1", "tenant_id": "tA",
          "technician_name": "ETHAN SMITH",   # case-differs; unique match
          "status": "completed", "scheduled_date": "2026-01-06"},
    ]
    with patch.object(_mod, "db", db_):
        rep = _run(_mod.compute_pool_service(
            "tA", date_from="2026-01-06", date_to="2026-01-12"))
    eth_rows = [r for r in rep["rows"]
                  if r.get("technician_id") == "tech-eth"]
    assert len(eth_rows) == 1
    assert eth_rows[0]["completed"] == 1


def test_compute_pool_service_ambiguous_name_lands_in_unassigned():
    """Same name resolves to TWO users → fall back to Unassigned
    bucket (per spec — never invent an ID)."""
    from routers import jobs as _mod
    db_ = _FakeDb()
    _seed(db_)
    db_.jobs.rows = [
        {"id": "ja", "tenant_id": "tA",
          "technician_name": "Ambiguous Al",  # 2 users match
          "status": "completed", "scheduled_date": "2026-01-06"},
    ]
    with patch.object(_mod, "db", db_):
        rep = _run(_mod.compute_pool_service(
            "tA", date_from="2026-01-06", date_to="2026-01-12"))
    unassigned = [r for r in rep["rows"] if r["technician_id"] is None]
    assert len(unassigned) == 1
    assert unassigned[0]["technician_name"] == "Unassigned"
    assert unassigned[0]["completed"] == 1


def test_compute_pool_service_excludes_soft_deleted():
    from routers import jobs as _mod
    db_ = _FakeDb()
    _seed(db_)
    db_.jobs.rows = [
        {"id": "jk", "tenant_id": "tA", "technician_id": "tech-eth",
          "technician_name": "Ethan Smith",
          "status": "completed", "scheduled_date": "2026-01-06",
          "deleted_at": "2026-01-10"},   # soft-deleted
    ]
    with patch.object(_mod, "db", db_):
        rep = _run(_mod.compute_pool_service(
            "tA", date_from="2026-01-06", date_to="2026-01-12"))
    eth_rows = [r for r in rep["rows"]
                  if r.get("technician_id") == "tech-eth"]
    assert eth_rows == []
    assert rep["total_completed"] == 0
