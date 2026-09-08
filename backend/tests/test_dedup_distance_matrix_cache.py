"""Feb-2026 · Task 5 · unit tests for the ``distance_matrix_cache``
dedup helper.

Covers the pure ``dedup`` coroutine with a stubbed Motor collection so
we can prove:

* Dry-run reports duplicates without deleting.
* Apply mode keeps the newest row per ``key`` and removes the rest.
* Clean collections are a no-op (idempotent).
* Ties on ``updated_at`` fall through to ``_id`` for a deterministic
  tie-breaker so the script is safe on collections without the
  ``updated_at`` field.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable, List

import pytest

from scripts.dedup_distance_matrix_cache import dedup


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _AsyncGen:
    def __init__(self, rows): self.rows = list(rows)
    def __aiter__(self): return self._it()
    async def _it(self):
        for r in self.rows: yield r


class _Cursor:
    def __init__(self, rows): self._rows = list(rows)
    async def to_list(self, length=None): return list(self._rows)


class _FakeColl:
    def __init__(self, rows: Iterable[Dict[str, Any]]):
        self.rows: List[Dict[str, Any]] = [dict(r) for r in rows]
        self.deleted_ids: List[Any] = []

    async def estimated_document_count(self):
        return len(self.rows)

    def aggregate(self, pipeline):
        # Only supports the specific $group + $match shape used by dedup().
        groups: Dict[Any, Dict[str, Any]] = {}
        for r in self.rows:
            k = r.get("key")
            g = groups.setdefault(k, {"_id": k, "count": 0, "ids": []})
            g["count"] += 1
            g["ids"].append(r.get("_id"))
        out = [g for g in groups.values() if g["count"] > 1]
        return _AsyncGen(out)

    def find(self, filt=None, projection=None):
        key = (filt or {}).get("key")
        return _Cursor([r for r in self.rows if r.get("key") == key])

    async def delete_many(self, filt):
        ids = set((filt or {}).get("_id", {}).get("$in", []) or [])
        before = len(self.rows)
        self.rows = [r for r in self.rows if r.get("_id") not in ids]
        self.deleted_ids.extend(ids)
        class _Res: deleted_count = before - len(self.rows)
        return _Res


def _rows_with_dupes():
    # 2 duplicates of key=A (keep newest updated_at), 1 solo key=B.
    return [
        {"_id": 1, "key": "A", "updated_at": "2026-02-01T00:00:00Z",
          "distance_meters": 100, "duration_seconds": 10},
        {"_id": 2, "key": "A", "updated_at": "2026-02-05T00:00:00Z",
          "distance_meters": 110, "duration_seconds": 11},
        {"_id": 3, "key": "A", "updated_at": "2026-02-03T00:00:00Z",
          "distance_meters": 105, "duration_seconds": 10},
        {"_id": 9, "key": "B", "updated_at": "2026-02-01T00:00:00Z",
          "distance_meters": 200, "duration_seconds": 20},
    ]


# ═════════════════════════════════════════════════════════════════════
# 1. DRY-RUN reports duplicates but doesn't mutate the collection.
# ═════════════════════════════════════════════════════════════════════
def test_dry_run_reports_but_does_not_delete():
    coll = _FakeColl(_rows_with_dupes())
    summary = _run(dedup(coll, apply=False))
    assert summary["duplicate_keys"] == 1
    assert summary["rows_removed"] == 0
    assert summary["applied"] is False
    # Collection is untouched.
    assert len(coll.rows) == 4
    assert coll.deleted_ids == []


# ═════════════════════════════════════════════════════════════════════
# 2. APPLY keeps newest, deletes the older duplicates of that key.
# ═════════════════════════════════════════════════════════════════════
def test_apply_keeps_newest_deletes_older_dupes():
    coll = _FakeColl(_rows_with_dupes())
    summary = _run(dedup(coll, apply=True))
    assert summary["duplicate_keys"] == 1
    assert summary["rows_removed"] == 2
    assert summary["applied"] is True
    # _id=2 is the newest for key=A (updated_at 2026-02-05).
    survivors = {r["_id"] for r in coll.rows}
    assert 2 in survivors
    assert 9 in survivors  # solo row untouched
    assert 1 not in survivors and 3 not in survivors
    # Sanity: kept row's data is preserved.
    kept = next(r for r in coll.rows if r["_id"] == 2)
    assert kept["distance_meters"] == 110


# ═════════════════════════════════════════════════════════════════════
# 3. Clean collection → no-op summary + no deletes attempted.
# ═════════════════════════════════════════════════════════════════════
def test_no_duplicates_is_noop():
    coll = _FakeColl([
        {"_id": 1, "key": "A", "updated_at": "2026-02-01T00:00:00Z"},
        {"_id": 2, "key": "B", "updated_at": "2026-02-02T00:00:00Z"},
    ])
    summary = _run(dedup(coll, apply=True))
    assert summary["duplicate_keys"] == 0
    assert summary["rows_removed"] == 0
    assert coll.deleted_ids == []
    assert len(coll.rows) == 2


# ═════════════════════════════════════════════════════════════════════
# 4. Tie on missing/equal ``updated_at`` falls through to ``_id`` so
#    the tie-breaker is deterministic on legacy rows.
# ═════════════════════════════════════════════════════════════════════
def test_ties_break_by_id_when_updated_at_missing():
    coll = _FakeColl([
        # No ``updated_at`` at all → tie-broken by _id (bigger wins).
        {"_id": 100, "key": "K"},
        {"_id": 200, "key": "K"},
        {"_id": 150, "key": "K"},
    ])
    summary = _run(dedup(coll, apply=True))
    assert summary["rows_removed"] == 2
    survivors = {r["_id"] for r in coll.rows}
    assert survivors == {200}
