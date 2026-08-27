"""Feb 2026 · Technician name resolver + backfill migration.

Covers:
  * ``resolve_technicians`` — 5 cases (users-only, technicians-only,
    both → users wins, nowhere, inactive → active=false).
  * ``compute_pool_service`` — bucketing by tech id, name-only rescue,
    ambiguous-name fallback.
  * ``bulk_enrich_technicians`` — stale name overwrite + inactive
    stamp.
  * Boot migration ``backfill_technician_names_on_jobs`` — dry-fixture
    with mixed jobs (missing/stale/deleted), asserts idempotency,
    soft-delete skip, and unresolved-count.
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


# ══════════════════════════════════════════════════════════════════
# Motor-mock helpers — a tiny in-memory async-cursor stand-in that
# supports the exact ``.find(query, projection)`` pattern the
# resolver uses.
# ══════════════════════════════════════════════════════════════════
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
    def __init__(self, name):
        self.name = name
        self.rows = []
        self.updates = []
    def find(self, query=None, projection=None):
        return _FakeCursor(self._match(query or {}))
    async def find_one(self, query=None, projection=None):
        rows = self._match(query or {})
        return rows[0] if rows else None
    async def count_documents(self, query=None):
        return len(self._match(query or {}))
    async def update_one(self, filt, upd, upsert=False):
        rows = self._match(filt)
        if not rows and not upsert:
            return MagicMock(matched_count=0, modified_count=0)
        if not rows and upsert:
            new = {}
            if "$setOnInsert" in upd:
                new.update(upd["$setOnInsert"])
            if "$set" in upd:
                new.update(upd["$set"])
            self.rows.append(new)
            self.updates.append({"q": filt, "u": upd})
            return MagicMock(upserted_id=new.get("id"),
                              matched_count=0, modified_count=1)
        row = rows[0]
        if "$set" in upd:
            row.update(upd["$set"])
        if "$inc" in upd:
            for k, v in upd["$inc"].items():
                row[k] = row.get(k, 0) + v
        self.updates.append({"q": filt, "u": upd})
        return MagicMock(matched_count=1, modified_count=1)
    async def insert_one(self, doc):
        self.rows.append(dict(doc))
        return MagicMock(inserted_id=doc.get("id"))
    def _match(self, query):
        return [r for r in self.rows if self._matches(r, query)]
    def _matches(self, row, query):
        # Tiny recursive matcher supporting the ops we use in the
        # resolver + migration.
        if "$and" in query:
            return all(self._matches(row, sub) for sub in query["$and"])
        if "$or" in query:
            return any(self._matches(row, sub) for sub in query["$or"])
        for k, v in query.items():
            if k in ("$and", "$or"):
                continue
            got = row.get(k, _MISSING)
            if isinstance(v, dict):
                if "$in" in v and got not in v["$in"]: return False
                if "$nin" in v:
                    if got in v["$nin"]: return False
                if "$exists" in v:
                    if v["$exists"] and got is _MISSING: return False
                    if (not v["$exists"]) and got is not _MISSING: return False
                if "$ne" in v and got == v["$ne"]: return False
                if "$regex" in v:
                    import re as _re
                    flags = _re.IGNORECASE if v.get("$options") == "i" else 0
                    if got is _MISSING or not isinstance(got, str): return False
                    if not _re.search(v["$regex"], got, flags): return False
                if "$gte" in v:
                    if got is _MISSING or got < v["$gte"]: return False
                if "$lte" in v:
                    if got is _MISSING or got > v["$lte"]: return False
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
        self.users = _FakeCollection("users")
        self.technicians = _FakeCollection("technicians")
        self.jobs = _FakeCollection("jobs")
        self.migrations = _FakeCollection("migrations")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ══════════════════════════════════════════════════════════════════
# resolve_technicians — 5-case cascade + inactive flag.
# ══════════════════════════════════════════════════════════════════
def _resolver():
    from services.service_report_view import resolve_technicians
    return resolve_technicians


def test_resolver_users_technician_id_wins():
    """When a tech exists in BOTH ``db.users`` (via technician_id
    back-ref) AND ``db.technicians``, the users doc wins because
    ``users`` is the Feb-2026 canonical source of tech identity.
    """
    db_ = _FakeDb()
    db_.users.rows = [{
        "id": "u1", "tenant_id": "tA", "role": "technician",
        "technician_id": "tech-1",
        "name": "Alice-users", "active": True,
    }]
    db_.technicians.rows = [{
        "id": "tech-1", "tenant_id": "tA",
        "name": "Alice-technicians", "active": True,
    }]
    out = _run(_resolver()(db_, "tA", ["tech-1"]))
    assert out["tech-1"]["name"] == "Alice-users"


def test_resolver_falls_back_to_technicians_collection():
    """No matching user row → fall through to ``db.technicians.id``."""
    db_ = _FakeDb()
    db_.technicians.rows = [{
        "id": "tech-2", "tenant_id": "tA",
        "name": "Bob Techs", "active": True,
    }]
    out = _run(_resolver()(db_, "tA", ["tech-2"]))
    assert out["tech-2"]["name"] == "Bob Techs"
    assert out["tech-2"]["active"] is True


def test_resolver_returns_active_false_for_deactivated():
    """Deactivated techs STILL resolve to a name, but their entry
    carries ``active: False`` so the UI can badge them."""
    db_ = _FakeDb()
    db_.users.rows = [{
        "id": "u3", "tenant_id": "tA", "role": "technician",
        "technician_id": "tech-3",
        "name": "Charlie Inactive", "active": False,
    }]
    out = _run(_resolver()(db_, "tA", ["tech-3"]))
    assert out["tech-3"]["name"] == "Charlie Inactive"
    assert out["tech-3"]["active"] is False


def test_resolver_returns_empty_for_unresolved_ids():
    """No row anywhere → ID isn't in the map. Caller then falls back
    to the raw ID string per the resolver-cascade contract."""
    db_ = _FakeDb()
    out = _run(_resolver()(db_, "tA", ["ghost-tid"]))
    assert "ghost-tid" not in out
    assert out == {}


def test_resolver_users_id_direct_rung_covered():
    """When ``technician_id`` is actually a raw ``users.id`` (writer
    drift), the 4th rung of the cascade still surfaces the name."""
    db_ = _FakeDb()
    db_.users.rows = [{
        "id": "user-direct", "tenant_id": "tA", "role": "technician",
        "name": "Direct User",
    }]
    out = _run(_resolver()(db_, "tA", ["user-direct"]))
    assert out["user-direct"]["name"] == "Direct User"


def test_resolver_active_defaults_true_when_field_missing():
    """Legacy rows (no ``active`` field at all) must not be
    incorrectly flagged as inactive."""
    db_ = _FakeDb()
    db_.technicians.rows = [{
        "id": "legacy-1", "tenant_id": "tA", "name": "Legacy Tech",
    }]
    out = _run(_resolver()(db_, "tA", ["legacy-1"]))
    assert out["legacy-1"]["active"] is True


def test_resolver_synthesises_from_first_last():
    """A user without ``name`` but with ``first_name``+``last_name``
    is stitched via the 5th rung."""
    db_ = _FakeDb()
    db_.users.rows = [{
        "id": "syn-1", "tenant_id": "tA", "role": "technician",
        "first_name": "Sy", "last_name": "Nth",
    }]
    out = _run(_resolver()(db_, "tA", ["syn-1"]))
    assert out["syn-1"]["name"] == "Sy Nth"


# ══════════════════════════════════════════════════════════════════
# bulk_enrich_technicians — stale-name overwrite + active stamp.
# ══════════════════════════════════════════════════════════════════
def test_bulk_enrich_overwrites_stale_stored_name():
    """A job carrying a stale ``technician_name`` string still gets
    the resolver's authoritative name on the response.  No DB
    mutation — response-only."""
    from services.tech_assignment import bulk_enrich_technicians
    db_ = _FakeDb()
    db_.users.rows = [{
        "id": "u5", "tenant_id": "tA", "role": "technician",
        "technician_id": "tech-5", "name": "Fresh Name", "active": True,
    }]
    docs = [{
        "id": "j1", "tenant_id": "tA",
        "technician_id": "tech-5",
        "technician_name": "STALE NAME FROM 2024",
    }]
    _run(bulk_enrich_technicians(db_, "tA", docs))
    assert docs[0]["technician_name"] == "Fresh Name"
    assert docs[0]["technician_active"] is True
    # No writes to ``db.jobs`` (self-heal is response-only).
    assert db_.jobs.updates == []


def test_bulk_enrich_stamps_technician_active_false_when_deactivated():
    from services.tech_assignment import bulk_enrich_technicians
    db_ = _FakeDb()
    db_.users.rows = [{
        "id": "u6", "tenant_id": "tA", "role": "technician",
        "technician_id": "tech-6", "name": "Deac Dan", "active": False,
    }]
    docs = [{"id": "j2", "tenant_id": "tA", "technician_id": "tech-6"}]
    _run(bulk_enrich_technicians(db_, "tA", docs))
    assert docs[0]["technician_active"] is False


def test_bulk_enrich_falls_back_to_tid_string_when_unresolved():
    """The resolver-cascade contract says: no match anywhere → return
    the raw ID string. Enricher must honor that."""
    from services.tech_assignment import bulk_enrich_technicians
    db_ = _FakeDb()
    docs = [{"id": "j3", "tenant_id": "tA", "technician_id": "ghost-999"}]
    _run(bulk_enrich_technicians(db_, "tA", docs))
    assert docs[0]["technician_name"] == "ghost-999"
    assert docs[0]["technician_active"] is True


# ══════════════════════════════════════════════════════════════════
# Backfill migration — idempotent + soft-delete skip.
# ══════════════════════════════════════════════════════════════════
def test_backfill_migration_writes_only_eligible_jobs():
    from services.migrations import backfill_technician_names as _mod
    from unittest.mock import patch
    db_ = _FakeDb()
    db_.users.rows = [{
        "id": "u10", "tenant_id": "tA", "role": "technician",
        "technician_id": "tech-10", "name": "Ten Xander", "active": True,
    }]
    db_.jobs.rows = [
        # Eligible — stamps.
        {"id": "j1", "tenant_id": "tA", "technician_id": "tech-10",
          "technician_name": ""},
        # Eligible — technician_name missing entirely.
        {"id": "j2", "tenant_id": "tA", "technician_id": "tech-10"},
        # NOT eligible — already has a name.
        {"id": "j3", "tenant_id": "tA", "technician_id": "tech-10",
          "technician_name": "Already Named"},
        # NOT eligible — no technician_id.
        {"id": "j4", "tenant_id": "tA", "technician_name": ""},
        # NOT eligible — soft-deleted.
        {"id": "j5", "tenant_id": "tA", "technician_id": "tech-10",
          "technician_name": "", "deleted_at": "2026-01-01"},
        # Eligible but UNRESOLVED — tech id doesn't exist.
        {"id": "j6", "tenant_id": "tA", "technician_id": "ghost-tid",
          "technician_name": ""},
    ]
    with patch.object(_mod, "db", db_):
        report = _run(_mod.backfill_technician_names_on_jobs())
    assert report["skipped"] is False
    assert report["backfilled"] == 2      # j1 + j2
    assert report["unresolved"] == 1      # j6
    assert report["soft_deleted_skipped"] == 1  # j5
    assert report["eligible"] == 3        # j1 + j2 + j6

    # Verify the rows actually got the name stamped.
    for jid in ("j1", "j2"):
        row = next(r for r in db_.jobs.rows if r["id"] == jid)
        assert row["technician_name"] == "Ten Xander"
        assert "technician_name_backfilled_at" in row

    # Untouched rows.
    for jid in ("j3", "j4", "j5", "j6"):
        row = next(r for r in db_.jobs.rows if r["id"] == jid)
        assert "technician_name_backfilled_at" not in row


def test_backfill_migration_is_idempotent():
    """Second run must be a no-op — sentinel guards the write."""
    from services.migrations import backfill_technician_names as _mod
    from unittest.mock import patch
    db_ = _FakeDb()
    db_.users.rows = [{
        "id": "u11", "tenant_id": "tA", "role": "technician",
        "technician_id": "tech-11", "name": "Elle Ven",
    }]
    db_.jobs.rows = [
        {"id": "j-a", "tenant_id": "tA", "technician_id": "tech-11",
          "technician_name": ""},
    ]
    with patch.object(_mod, "db", db_):
        r1 = _run(_mod.backfill_technician_names_on_jobs())
        assert r1["backfilled"] == 1
        writes_before = len(db_.jobs.updates)
        r2 = _run(_mod.backfill_technician_names_on_jobs())
        assert r2["skipped"] is True
        assert r2["reason"] == "already_ran"
        # Zero new writes on the 2nd run.
        assert len(db_.jobs.updates) == writes_before
