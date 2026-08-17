"""Task 3 · Feb-2026 — importer_base shared-primitives pytest suite.

Locks in the paged-driver contract so future subclasses (customer
importers, once migrated) can rely on it.

Covered:
  1. **RateLimiter** ticks respect the qps gate.
  2. **checkpoint** serialises dataclass counters + optional error_log.
  3. **cancel_flag_set** returns True on cancelling / cancelled /
      paused_needs_attention statuses.
  4. **run_paged_driver** end-to-end happy path.
  5. **run_paged_driver** cancel-during-run exits cleanly.
  6. **run_paged_driver** cascade-stop after N page failures.
"""
from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List

import pytest

sys.path.insert(0, "/app/backend")

from services.homeworks_mcp import importer_base as base  # noqa: E402


# ── Fake Mongo (tiny — only needs the run_doc coll) ──────────────────
class _Coll:
    def __init__(self):
        self._d: List[Dict[str, Any]] = []

    async def find_one(self, q, projection=None):
        for d in self._d:
            if all(d.get(k) == v for k, v in q.items()):
                return {**d}
        return None

    async def insert_one(self, doc):
        self._d.append({**doc})

    async def update_one(self, q, upd):
        for d in self._d:
            if all(d.get(k) == v for k, v in q.items()):
                if "$set" in upd:
                    d.update(upd["$set"])
                if "$push" in upd:
                    for kk, vv in upd["$push"].items():
                        d.setdefault(kk, []).append(vv)
                return


class _DB:
    def __init__(self):
        self.homeworks_import_runs = _Coll()


@dataclass
class _Ctrs:
    scanned: int = 0
    imported: int = 0
    failed: int = 0


class _FakeMCPError(Exception):
    pass


def _mk_config():
    return base.PagedDriverConfig(
        kind="test",
        page_query="PAGE",
        page_key="rows",
        page_size=3,
        rate_limit_qps=100,
        checkpoint_every_s=1,
        cascade_stop_after=3,
        page_retries=2,
        counter_scanned="scanned",
        counter_failed="failed",
    )


# ── 1. RateLimiter ────────────────────────────────────────────────────
def test_rate_limiter_respects_qps():
    rl = base.RateLimiter(qps=20)  # 50ms gap
    start = time.monotonic()
    asyncio.get_event_loop().run_until_complete(rl.wait())
    asyncio.get_event_loop().run_until_complete(rl.wait())
    elapsed = time.monotonic() - start
    # Two waits ⇒ at least one full gap between them (~50ms).
    assert elapsed >= 0.045


# ── 2. checkpoint serialises dataclass + error_log ───────────────────
def test_checkpoint_serialises_counters_and_pushes_error():
    db = _DB()
    asyncio.get_event_loop().run_until_complete(
        db.homeworks_import_runs.insert_one({
            "run_id": "r-1", "status": "queued",
            "counters": {}, "resume_cursor": 0, "error_log": [],
        }),
    )
    ctrs = _Ctrs(scanned=3, imported=2, failed=1)
    asyncio.get_event_loop().run_until_complete(
        base.checkpoint(
            db, "r-1", counters=ctrs, resume_cursor=42,
            status="running",
            error={"reason": "x", "at": "now"},
        ),
    )
    doc = asyncio.get_event_loop().run_until_complete(
        db.homeworks_import_runs.find_one({"run_id": "r-1"}),
    )
    assert doc["counters"] == {"scanned": 3, "imported": 2, "failed": 1}
    assert doc["resume_cursor"] == 42
    assert doc["status"] == "running"
    assert doc["error_log"][0]["reason"] == "x"


# ── 3. cancel_flag_set ───────────────────────────────────────────────
@pytest.mark.parametrize("status,expected", [
    ("running", False),
    ("queued", False),
    ("cancelling", True),
    ("cancelled", True),
    ("paused_needs_attention", True),
])
def test_cancel_flag_set_reads_all_stop_statuses(status, expected):
    db = _DB()
    asyncio.get_event_loop().run_until_complete(
        db.homeworks_import_runs.insert_one({"run_id": "r-1", "status": status}),
    )
    got = asyncio.get_event_loop().run_until_complete(
        base.cancel_flag_set(db, "r-1"),
    )
    assert got is expected


# ── 4. run_paged_driver — end-to-end happy path ──────────────────────
def test_paged_driver_happy_path():
    db = _DB()
    asyncio.get_event_loop().run_until_complete(
        db.homeworks_import_runs.insert_one({
            "run_id": "r-happy", "status": "queued",
            "counters": {}, "resume_cursor": 0, "error_log": [],
        }),
    )
    imported: List[int] = []

    async def _import_one(row, ctrs):
        imported.append(row["id"])
        ctrs.imported += 1
        return None

    all_rows = [{"id": i} for i in range(1, 6)]

    async def _fake_gql(**kw):
        vs = kw.get("variables") or {}
        skip = vs.get("skip", 0)
        take = vs.get("take", 3)
        return {"rows": all_rows[skip:skip + take]}

    result = asyncio.get_event_loop().run_until_complete(
        base.run_paged_driver(
            db=db, gql_query=_fake_gql,
            tenant_id="t1", user_id="u1", run_id="r-happy",
            config=_mk_config(),
            counters=_Ctrs(),
            import_one_fn=_import_one,
            exceptions=(_FakeMCPError,),
        ),
    )
    assert imported == [1, 2, 3, 4, 5]
    assert result.imported == 5
    doc = asyncio.get_event_loop().run_until_complete(
        db.homeworks_import_runs.find_one({"run_id": "r-happy"}),
    )
    assert doc["status"] == "completed"
    assert doc.get("finished_at")


# ── 5. cancel_flag halts mid-run ─────────────────────────────────────
def test_paged_driver_cancel_flag_halts():
    db = _DB()
    asyncio.get_event_loop().run_until_complete(
        db.homeworks_import_runs.insert_one({
            "run_id": "r-cancel", "status": "cancelling",
            "counters": {}, "resume_cursor": 0, "error_log": [],
        }),
    )

    async def _import_one(row, ctrs):
        return None

    async def _fake_gql(**kw):
        return {"rows": [{"id": 1}, {"id": 2}]}

    asyncio.get_event_loop().run_until_complete(
        base.run_paged_driver(
            db=db, gql_query=_fake_gql,
            tenant_id="t1", user_id=None, run_id="r-cancel",
            config=_mk_config(),
            counters=_Ctrs(),
            import_one_fn=_import_one,
            exceptions=(_FakeMCPError,),
        ),
    )
    doc = asyncio.get_event_loop().run_until_complete(
        db.homeworks_import_runs.find_one({"run_id": "r-cancel"}),
    )
    assert doc["status"] == "cancelled"


# ── 6. cascade auto-stop ─────────────────────────────────────────────
def test_paged_driver_cascade_stop(monkeypatch):
    db = _DB()
    asyncio.get_event_loop().run_until_complete(
        db.homeworks_import_runs.insert_one({
            "run_id": "r-cascade", "status": "queued",
            "counters": {}, "resume_cursor": 0, "error_log": [],
        }),
    )
    call_count = {"n": 0}

    async def _fake_gql(**_kw):
        call_count["n"] += 1
        raise _FakeMCPError("always fails")

    async def _import_one(row, ctrs):
        return None

    _real_sleep = asyncio.sleep
    monkeypatch.setattr("services.homeworks_mcp.importer_base.asyncio.sleep",
                         lambda *_a, **_k: _real_sleep(0))

    asyncio.get_event_loop().run_until_complete(
        base.run_paged_driver(
            db=db, gql_query=_fake_gql,
            tenant_id="t1", user_id=None, run_id="r-cascade",
            config=_mk_config(),
            counters=_Ctrs(),
            import_one_fn=_import_one,
            exceptions=(_FakeMCPError,),
        ),
    )
    doc = asyncio.get_event_loop().run_until_complete(
        db.homeworks_import_runs.find_one({"run_id": "r-cascade"}),
    )
    assert doc["status"] == "paused_needs_attention"
