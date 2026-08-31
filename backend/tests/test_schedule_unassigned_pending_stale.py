"""Feb-2026 Enhancement — ``GET /api/schedule/unassigned-pending-stale``.

Counts jobs that are:
  * status='pending'
  * NO technician_id AND NO crew_id
  * created_at older than ``days`` days ago (default 7)
  * NOT soft-deleted

Tenant-scoped via ``get_current_tenant``. Techs are 403.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

import pytest
from fastapi import HTTPException

from routers import schedule as sched


class _FakeJobs:
    def __init__(self, rows):
        self._rows = list(rows)
        self.calls = []

    async def count_documents(self, query):
        self.calls.append(dict(query))
        # Only implement enough of the shape to test.
        cnt = 0
        cutoff = query.get("created_at", {}).get("$lt")
        tid = query.get("tenant_id")
        for r in self._rows:
            if tid and r.get("tenant_id") != tid:
                continue
            if r.get("status") != query.get("status"):
                continue
            if r.get("technician_id") is not None:
                continue
            if r.get("crew_id") is not None:
                continue
            if r.get("deleted_at") is not None:
                continue
            if cutoff and (r.get("created_at") or "") >= cutoff:
                continue
            cnt += 1
        return cnt


class _FakeDb:
    def __init__(self, jobs):
        self.jobs = _FakeJobs(jobs)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _iso_days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


def _admin(role="admin", tenant_id="t-1"):
    return {"id": "u-1", "tenant_id": tenant_id, "role": role}


def _tenant(tid="t-1"):
    return {"id": tid, "slug": "acme"}


def test_count_returns_zero_when_no_stale_jobs(monkeypatch):
    fake = _FakeDb([])
    monkeypatch.setattr(sched, "db", fake)
    result = _run(sched.get_unassigned_pending_stale_count(
        days=7, user=_admin(), tenant=_tenant(),
    ))
    assert result == {"count": 0, "days": 7,
                       "cutoff": result["cutoff"]}


def test_count_includes_pending_unassigned_stale_only(monkeypatch):
    fake = _FakeDb([
        # (1) stale + unassigned + pending → COUNTED
        {"tenant_id": "t-1", "status": "pending",
         "technician_id": None, "crew_id": None,
         "deleted_at": None, "created_at": _iso_days_ago(20)},
        # (2) too fresh (yesterday) → not counted
        {"tenant_id": "t-1", "status": "pending",
         "technician_id": None, "crew_id": None,
         "deleted_at": None, "created_at": _iso_days_ago(1)},
        # (3) has a technician → not counted
        {"tenant_id": "t-1", "status": "pending",
         "technician_id": "tech-a", "crew_id": None,
         "deleted_at": None, "created_at": _iso_days_ago(30)},
        # (4) has a crew → not counted
        {"tenant_id": "t-1", "status": "pending",
         "technician_id": None, "crew_id": "crew-a",
         "deleted_at": None, "created_at": _iso_days_ago(30)},
        # (5) status=scheduled → not counted
        {"tenant_id": "t-1", "status": "scheduled",
         "technician_id": None, "crew_id": None,
         "deleted_at": None, "created_at": _iso_days_ago(30)},
        # (6) soft-deleted → not counted
        {"tenant_id": "t-1", "status": "pending",
         "technician_id": None, "crew_id": None,
         "deleted_at": _iso_days_ago(10), "created_at": _iso_days_ago(30)},
        # (7) other tenant → not counted
        {"tenant_id": "t-other", "status": "pending",
         "technician_id": None, "crew_id": None,
         "deleted_at": None, "created_at": _iso_days_ago(30)},
    ])
    monkeypatch.setattr(sched, "db", fake)
    result = _run(sched.get_unassigned_pending_stale_count(
        days=7, user=_admin(), tenant=_tenant(),
    ))
    assert result["count"] == 1


def test_non_admin_rejected(monkeypatch):
    fake = _FakeDb([])
    monkeypatch.setattr(sched, "db", fake)
    for role in ("technician", "customer", "portal_customer"):
        with pytest.raises(HTTPException) as exc:
            _run(sched.get_unassigned_pending_stale_count(
                days=7, user=_admin(role=role), tenant=_tenant(),
            ))
        assert exc.value.status_code == 403


def test_manager_allowed(monkeypatch):
    fake = _FakeDb([])
    monkeypatch.setattr(sched, "db", fake)
    result = _run(sched.get_unassigned_pending_stale_count(
        days=7, user=_admin(role="manager"), tenant=_tenant(),
    ))
    assert result["count"] == 0


def test_days_out_of_range_400(monkeypatch):
    fake = _FakeDb([])
    monkeypatch.setattr(sched, "db", fake)
    with pytest.raises(HTTPException) as exc:
        _run(sched.get_unassigned_pending_stale_count(
            days=0, user=_admin(), tenant=_tenant(),
        ))
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:
        _run(sched.get_unassigned_pending_stale_count(
            days=999, user=_admin(), tenant=_tenant(),
        ))
    assert exc.value.status_code == 400


def test_tenant_isolation(monkeypatch):
    """A caller in tenant A must never see tenant B's stale jobs."""
    fake = _FakeDb([
        {"tenant_id": "t-a", "status": "pending",
         "technician_id": None, "crew_id": None,
         "deleted_at": None, "created_at": _iso_days_ago(30)},
        {"tenant_id": "t-b", "status": "pending",
         "technician_id": None, "crew_id": None,
         "deleted_at": None, "created_at": _iso_days_ago(30)},
    ])
    monkeypatch.setattr(sched, "db", fake)
    result_a = _run(sched.get_unassigned_pending_stale_count(
        days=7, user=_admin(tenant_id="t-a"), tenant={"id": "t-a"},
    ))
    result_b = _run(sched.get_unassigned_pending_stale_count(
        days=7, user=_admin(tenant_id="t-b"), tenant={"id": "t-b"},
    ))
    assert result_a["count"] == 1
    assert result_b["count"] == 1
