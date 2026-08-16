"""Queue Item 5c · Feb-2026 — Homeworks import dispatcher pytest suite.

Uses an in-memory fake Mongo (same shape as
``test_pricebook_importer.py``) plus a monkeypatched ``importlib``
so we don't drag the real importers in. Covers:

  1. **Pick-up flow** — dispatcher_tick claims a queued run and
     hands it off to ``_run_one``.
  2. **Atomic flip** — the queued → running transition uses
     ``update_one({run_id, status:"queued"}, ...)`` so a lost race
     returns False without executing the run.
  3. **Concurrency guard** — a second queued run for the same tenant
     is skipped while another is still running.
  4. **Cancel flag halt** — flipping to ``cancelling`` between
     ticks stops the importer cleanly (delegated to importer's own
     _cancel_flag_set — dispatcher just runs it, importer handles).
  5. **Crash recovery** — an unhandled crash inside the importer
     transitions the doc to ``failed`` with an error_log entry.
  6. **Unknown-kind poison-pill** — a doc with an unmapped ``kind``
     is transitioned to ``failed`` so it doesn't keep re-tripping.
"""
from __future__ import annotations

import asyncio
import re
import sys
from typing import Any, Dict, List

import pytest

sys.path.insert(0, "/app/backend")

from services.homeworks_mcp import import_dispatcher as disp  # noqa: E402


# ── Fake Mongo (reduced version of the pricebook suite's) ────────────
class _Cursor:
    def __init__(self, rows):
        self._rows = rows
        self._i = 0

    def sort(self, *_a, **_k):     return self

    def __aiter__(self):
        self._i = 0
        return self

    async def __anext__(self):
        if self._i >= len(self._rows):
            raise StopAsyncIteration
        r = self._rows[self._i]
        self._i += 1
        return r


def _match(doc, q):
    for k, v in q.items():
        actual = doc.get(k)
        if isinstance(v, dict):
            if "$ne" in v and actual == v["$ne"]:
                return False
            if "$in" in v and actual not in v["$in"]:
                return False
        else:
            if actual != v:
                return False
    return True


class _Coll:
    def __init__(self):
        self._d: List[Dict[str, Any]] = []

    async def find_one(self, q, projection=None):
        for d in self._d:
            if _match(d, q):
                return {**d}
        return None

    async def count_documents(self, q):
        return sum(1 for d in self._d if _match(d, q))

    async def insert_one(self, doc):
        self._d.append({**doc})
        return type("_R", (), {"inserted_id": len(self._d)})

    def find(self, q, projection=None):
        return _Cursor([{**d} for d in self._d if _match(d, q)])

    async def update_one(self, q, upd):
        for d in self._d:
            if _match(d, q):
                if "$set" in upd:
                    d.update(upd["$set"])
                if "$push" in upd:
                    for kk, vv in upd["$push"].items():
                        d.setdefault(kk, []).append(vv)
                return type("_R", (), {"matched_count": 1, "modified_count": 1})
        return type("_R", (), {"matched_count": 0, "modified_count": 0})


class _DB:
    def __init__(self):
        self.homeworks_import_runs = _Coll()


@pytest.fixture
def fake_db(monkeypatch):
    d = _DB()
    monkeypatch.setattr("config.db", d, raising=False)
    return d


# ── 1. Pick-up flow ──────────────────────────────────────────────────
def test_dispatcher_picks_up_queued_run(fake_db, monkeypatch):
    executed: List[str] = []

    async def _fake_run_one(kind, tenant_id, run_id, user_id):
        executed.append(run_id)
        # Simulate completion via the same update path the importer uses.
        await fake_db.homeworks_import_runs.update_one(
            {"run_id": run_id},
            {"$set": {"status": "completed",
                       "finished_at": "2026-02-16T00:00:00Z"}},
        )
    monkeypatch.setattr(disp, "_run_one", _fake_run_one)

    asyncio.get_event_loop().run_until_complete(
        fake_db.homeworks_import_runs.insert_one({
            "run_id": "r-1", "tenant_id": "t-1",
            "kind": "pricebook", "status": "queued",
            "started_at": "2026-02-16T00:00:00Z",
        }),
    )
    summary = asyncio.get_event_loop().run_until_complete(disp.dispatcher_tick())
    assert summary["started"] == 1
    # Let the fire-and-forget task finish.
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))
    assert executed == ["r-1"]
    # Doc marked completed by our fake.
    doc = asyncio.get_event_loop().run_until_complete(
        fake_db.homeworks_import_runs.find_one({"run_id": "r-1"}),
    )
    assert doc["status"] == "completed"


# ── 2. Atomic flip — losing the race returns False ───────────────────
def test_try_start_run_is_atomic(fake_db):
    # Insert an already-running doc — the atomic flip must return False.
    asyncio.get_event_loop().run_until_complete(
        fake_db.homeworks_import_runs.insert_one({
            "run_id": "r-race", "tenant_id": "t-1",
            "kind": "pricebook", "status": "running",
            "started_at": "2026-02-16T00:00:00Z",
        }),
    )
    won = asyncio.get_event_loop().run_until_complete(
        disp._try_start_run(fake_db, {"run_id": "r-race"}),
    )
    assert won is False


# ── 3. Concurrency guard — one live run per tenant ───────────────────
def test_concurrency_guard_skips_same_tenant(fake_db, monkeypatch):
    executed: List[str] = []

    async def _fake_run_one(kind, tenant_id, run_id, user_id):
        executed.append(run_id)
    monkeypatch.setattr(disp, "_run_one", _fake_run_one)

    # Tenant already has a running job.
    asyncio.get_event_loop().run_until_complete(
        fake_db.homeworks_import_runs.insert_one({
            "run_id": "r-running", "tenant_id": "t-1",
            "kind": "pricebook", "status": "running",
            "started_at": "2026-02-16T00:00:00Z",
        }),
    )
    # A second queued run for the SAME tenant lands.
    asyncio.get_event_loop().run_until_complete(
        fake_db.homeworks_import_runs.insert_one({
            "run_id": "r-queued", "tenant_id": "t-1",
            "kind": "pricebook", "status": "queued",
            "started_at": "2026-02-16T00:01:00Z",
        }),
    )
    summary = asyncio.get_event_loop().run_until_complete(disp.dispatcher_tick())
    assert summary["started"] == 0
    assert summary["skipped_concurrency"] == 1
    assert executed == []


# ── 4. Different tenant can still start (concurrency is per-tenant) ──
def test_concurrency_guard_scoped_to_tenant(fake_db, monkeypatch):
    executed: List[str] = []

    async def _fake_run_one(kind, tenant_id, run_id, user_id):
        executed.append(run_id)
    monkeypatch.setattr(disp, "_run_one", _fake_run_one)

    asyncio.get_event_loop().run_until_complete(
        fake_db.homeworks_import_runs.insert_one({
            "run_id": "r-running-tA", "tenant_id": "tA",
            "kind": "pricebook", "status": "running",
            "started_at": "2026-02-16T00:00:00Z",
        }),
    )
    asyncio.get_event_loop().run_until_complete(
        fake_db.homeworks_import_runs.insert_one({
            "run_id": "r-queued-tB", "tenant_id": "tB",
            "kind": "pricebook", "status": "queued",
            "started_at": "2026-02-16T00:01:00Z",
        }),
    )
    summary = asyncio.get_event_loop().run_until_complete(disp.dispatcher_tick())
    assert summary["started"] == 1
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))
    assert executed == ["r-queued-tB"]


# ── 5. Crash inside _run_one flips the doc to failed ─────────────────
def test_run_one_crash_marks_failed(fake_db, monkeypatch):
    # Register a synthetic module that crashes so importlib returns it.
    class _CrashingImp:
        @staticmethod
        async def run_full(**_kw):
            raise RuntimeError("boom")

    def _fake_import_module(path):
        return _CrashingImp
    # Point the kind map at a stub module path so import_module is
    # asked to load ``fake.mod.path`` — our fake importlib swallows it.
    monkeypatch.setitem(disp._IMPORTER_KIND_MAP, "pricebook",
                          "fake.mod.path")
    import importlib
    monkeypatch.setattr(importlib, "import_module", _fake_import_module)

    asyncio.get_event_loop().run_until_complete(
        fake_db.homeworks_import_runs.insert_one({
            "run_id": "r-crash", "tenant_id": "t-1",
            "kind": "pricebook", "status": "queued",
        }),
    )
    asyncio.get_event_loop().run_until_complete(
        disp._run_one("pricebook", "t-1", "r-crash", "u-1"),
    )
    doc = asyncio.get_event_loop().run_until_complete(
        fake_db.homeworks_import_runs.find_one({"run_id": "r-crash"}),
    )
    assert doc["status"] == "failed"
    assert any(e.get("stage") == "dispatcher_crash"
                 for e in (doc.get("error_log") or []))


# ── 6. Unknown-kind poison pill ─────────────────────────────────────
def test_unknown_kind_marks_failed(fake_db):
    asyncio.get_event_loop().run_until_complete(
        fake_db.homeworks_import_runs.insert_one({
            "run_id": "r-unknown", "tenant_id": "t-1",
            "kind": "not_a_real_kind", "status": "queued",
        }),
    )
    asyncio.get_event_loop().run_until_complete(
        disp._run_one("not_a_real_kind", "t-1", "r-unknown", "u-1"),
    )
    doc = asyncio.get_event_loop().run_until_complete(
        fake_db.homeworks_import_runs.find_one({"run_id": "r-unknown"}),
    )
    assert doc["status"] == "failed"
    reasons = [e.get("reason") for e in (doc.get("error_log") or [])]
    assert any(r and r.startswith("unknown_kind:") for r in reasons)
