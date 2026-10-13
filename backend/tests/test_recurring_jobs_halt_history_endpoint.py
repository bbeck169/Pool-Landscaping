"""P0 · Feb-2026 — Halt-history diagnostic endpoint tests.

Pins ``GET /api/admin/diagnostics/recurring-jobs-halt-history``:
  1. Admin gate wired.
  2. ``days`` param capped at 90.
  3. Projection shape matches contract.
  4. Returns both per-tenant (``batch_failure_halt``) and global
     (``global_batch_halt``) rows.

Isolated FastAPI with a monkeypatched ``db.audit_logs`` so the test
doesn't depend on live Mongo state.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from dotenv import dotenv_values
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


_TEST_DIR = Path(__file__).resolve().parent
_BE = dotenv_values(_TEST_DIR.parent / ".env")
for _k in ("MONGO_URL", "DB_NAME"):
    if _k not in os.environ and _BE.get(_k):
        os.environ[_k] = _BE[_k]


def _run(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        import config as _cfg
        try:
            _cfg.db.client._io_loop = loop  # noqa: SLF001
        except Exception:
            pass
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _AuditFindCursor:
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = list(docs)

    def sort(self, *a, **kw):
        return self

    def limit(self, *a, **kw):
        return self

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()


class _AuditCollectionStub:
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = docs
        self.last_filter: Dict[str, Any] = {}
        self.last_projection: Dict[str, Any] = {}

    def find(self, filt, projection=None):
        self.last_filter = filt
        self.last_projection = projection or {}
        # Simulate server-side filtering of the ``action`` key +
        # ``created_at`` floor so tests can assert the endpoint
        # applied the right projection.
        filtered = [
            d for d in self._docs
            if d.get("action") in filt.get("action", {}).get("$in", [])
            and d.get("created_at", "") >= filt.get("created_at", {}).get("$gte", "")
        ]
        return _AuditFindCursor(filtered)


def _make_app_with_fake_admin():
    from routers import admin_recurring_jobs_audit as m
    from utils import require_admin
    app = FastAPI()
    app.include_router(m.router, prefix="/api")

    def _fake_admin():
        return {"id": "test-admin", "role": "admin",
                "tenant_id": "test-tenant"}

    app.dependency_overrides[require_admin] = _fake_admin
    return app


def _fixture_rows() -> List[Dict[str, Any]]:
    """Two per-tenant halt rows + one global halt row + one
    unrelated audit row (must be filtered out)."""
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "id": "a-1",
            "action": "recurring_job.cron.batch_failure_halt",
            "tenant_id": "tenant-A",
            "created_at": now,
            "payload": {
                "run_id": "run-x",
                "trigger_rule": "all_fail",
                "tenant_id": "tenant-A",
                "templates_attempted": 5,
                "templates_failed": 5,
                "templates_succeeded": 0,
                "halted_weekday_counts": {"2": 3, "3": 2},
                "halted_weekday_failed_counts": {"2": 3, "3": 2},
                "failure_signatures_by_weekday": {
                    "2": {"RuntimeError": 3},
                    "3": {"KeyError": 2},
                },
            },
        },
        {
            "id": "a-2",
            "action": "recurring_job.cron.batch_failure_halt",
            "tenant_id": "tenant-B",
            "created_at": now,
            "payload": {
                "run_id": "run-y",
                "trigger_rule": "half_fail_large_batch",
                "tenant_id": "tenant-B",
                "templates_attempted": 10,
                "templates_failed": 5,
                "templates_succeeded": 5,
                "halted_weekday_counts": {"4": 10},
            },
        },
        {
            "id": "a-3",
            "action": "recurring_job.cron.global_batch_halt",
            "tenant_id": None,
            "created_at": now,
            "payload": {
                "run_id": "run-z",
                "trigger_rule": "halted_tenants_threshold",
                "templates_attempted": 25,
                "templates_failed": 25,
                "halted_tenants": ["t-A", "t-B", "t-C", "t-D", "t-E"],
                "tenants_halted_count": 5,
            },
        },
        # Unrelated row — must be filtered out by the endpoint.
        {
            "id": "a-9",
            "action": "unrelated.something_else",
            "tenant_id": None,
            "created_at": now,
            "payload": {},
        },
    ]


def _call_endpoint(docs: List[Dict[str, Any]], *, days: int = 14):
    from config import db as real_db
    app = _make_app_with_fake_admin()
    stub = _AuditCollectionStub(docs)
    orig = real_db.audit_logs
    try:
        real_db.audit_logs = stub

        async def _go():
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                return await client.get(
                    "/api/admin/diagnostics/recurring-jobs-halt-history",
                    params={"days": days},
                )

        resp = _run(_go())
    finally:
        real_db.audit_logs = orig
    return resp, stub


# ─── §1 · Projection shape + both actions returned ───────────────

def test_halt_history_returns_both_per_tenant_and_global_rows():
    resp, _ = _call_endpoint(_fixture_rows())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 3  # unrelated row filtered out
    actions = {r["action"] for r in body["rows"]}
    assert actions == {
        "recurring_job.cron.batch_failure_halt",
        "recurring_job.cron.global_batch_halt",
    }
    # Projection shape — each row carries all contract keys.
    required = {
        "id", "action", "tenant_id", "created_at", "run_id",
        "trigger_rule", "templates_attempted", "templates_failed",
        "templates_succeeded", "halted_weekday_counts",
        "failure_signatures_by_weekday",
    }
    for r in body["rows"]:
        missing = required - set(r.keys())
        assert not missing, f"row missing contract keys: {missing}"


# ─── §2 · days cap ───────────────────────────────────────────────

def test_halt_history_caps_days_at_90():
    resp, _ = _call_endpoint(_fixture_rows(), days=365)
    assert resp.status_code == 200
    body = resp.json()
    assert body["window"]["days_requested"] == 365
    assert body["window"]["days_applied"] == 90
    assert body["window"]["cap"] == 90


# ─── §3 · days floor ─────────────────────────────────────────────

def test_halt_history_rejects_days_below_one():
    """FastAPI's ``Query(ge=1)`` returns 422 for ``days=0``."""
    _, _ = _call_endpoint([], days=1)  # warm-up / sanity
    from routers import admin_recurring_jobs_audit as m
    from utils import require_admin
    from config import db as real_db
    app = FastAPI()
    app.include_router(m.router, prefix="/api")

    def _fake_admin():
        return {"id": "test-admin", "role": "admin"}

    app.dependency_overrides[require_admin] = _fake_admin

    async def _go():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.get(
                "/api/admin/diagnostics/recurring-jobs-halt-history",
                params={"days": 0},
            )

    r = _run(_go())
    assert r.status_code == 422


# ─── §4 · admin gate ─────────────────────────────────────────────

def test_halt_history_requires_admin():
    from routers import admin_recurring_jobs_audit as m
    app = FastAPI()
    app.include_router(m.router, prefix="/api")

    async def _go():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.get(
                "/api/admin/diagnostics/recurring-jobs-halt-history",
            )

    r = _run(_go())
    assert r.status_code in (401, 403), r.text


# ─── §5 · action filter applied ───────────────────────────────────

def test_halt_history_filters_by_halt_action_only():
    """Only ``recurring_job.cron.{batch,global}_failure_halt`` /
    ``global_batch_halt`` rows come back — never unrelated audit rows."""
    resp, stub = _call_endpoint(_fixture_rows())
    assert resp.status_code == 200
    assert set(stub.last_filter.get("action", {}).get("$in", [])) == {
        "recurring_job.cron.batch_failure_halt",
        "recurring_job.cron.global_batch_halt",
    }
    body = resp.json()
    for r in body["rows"]:
        assert r["action"] in {
            "recurring_job.cron.batch_failure_halt",
            "recurring_job.cron.global_batch_halt",
        }
