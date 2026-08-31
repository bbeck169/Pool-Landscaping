"""Feb-2026 · Phase F2 · dry-run coverage.

The scan endpoint must:
  * classify every active job into one of the three dangling-ref
    buckets (or none),
  * NEVER write to the ``jobs`` collection,
  * mint a fresh ``confirm_token`` and persist a scan record with
    a 15-minute expiry,
  * be super_admin-only.

These tests hit ``_scan_dangling_refs`` and the router function
directly with in-memory Motor stubs; no network, no live DB, no
running server.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException

from routers import data_repair as dr


# ── Motor-compatible in-memory stubs ───────────────────────────────
class _Coll:
    def __init__(self, rows=None):
        self.rows: List[Dict[str, Any]] = list(rows or [])
        self.updates: List[Dict[str, Any]] = []
        self.inserts: List[Dict[str, Any]] = []

    async def find_one(self, query, projection=None):  # noqa: ARG002
        for row in self.rows:
            if _matches(row, query):
                return dict(row)
        return None

    async def insert_one(self, doc):
        self.inserts.append(dict(doc))
        # Also visible to subsequent find_one / find calls.
        self.rows.append(dict(doc))
        return type("R", (), {"inserted_id": doc.get("id")})()

    async def update_one(self, filt, update):
        for row in self.rows:
            if _matches(row, filt):
                self.updates.append({"filter": dict(filt), "update": dict(update)})
                if "$set" in update:
                    row.update(update["$set"])
                return type("R", (), {"modified_count": 1})()
        return type("R", (), {"modified_count": 0})()

    def find(self, query=None, projection=None):  # noqa: ARG002
        outer = self
        q = query or {}

        class _Cursor:
            def __init__(self):
                self._rows = [dict(r) for r in outer.rows if _matches(r, q)]

            def __aiter__(self):
                self._it = iter(self._rows)
                return self

            async def __anext__(self):
                try:
                    return next(self._it)
                except StopIteration:
                    raise StopAsyncIteration

            def sort(self, *_a, **_k):
                return self

            async def to_list(self, _n=None):
                return list(self._rows)

        return _Cursor()


def _matches(row, query):
    for k, v in query.items():
        if k == "$or":
            if not any(_matches(row, sub) for sub in v):
                return False
            continue
        if k == "$and":
            if not all(_matches(row, sub) for sub in v):
                return False
            continue
        if isinstance(v, dict):
            if "$exists" in v:
                exists = k in row
                if v["$exists"] != exists:
                    return False
                continue
            if "$in" in v:
                if row.get(k) not in v["$in"]:
                    return False
                continue
            return False
        if row.get(k) != v:
            return False
    return True


class _DB:
    def __init__(self, jobs=None, customers=None, technicians=None,
                 users=None):
        self.jobs = _Coll(jobs)
        self.customers = _Coll(customers)
        self.technicians = _Coll(technicians)
        self.users = _Coll(users)
        self.data_integrity_scans = _Coll()
        self.data_integrity_repairs = _Coll()


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ═══════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════
def test_scan_classifies_all_three_buckets(monkeypatch):
    """Given a mixed job dataset the scan returns the correct
    counts and jobs in each of the three buckets."""
    # Live customers.
    customers = [
        {"id": "c1", "tenant_id": "t1"},
        {"id": "c2", "tenant_id": "t1"},
    ]
    # Live techs — one via technicians, one via users.
    techs = [{"id": "tech-a", "tenant_id": "t1"}]
    users = [{"id": "user-b", "role": "technician"}]
    jobs = [
        # Baseline — everything wired up.
        {"id": "j-ok", "tenant_id": "t1", "customer_id": "c1",
         "technician_id": "tech-a", "status": "scheduled",
         "scheduled_date": "2026-08-01"},
        # Orphan customer — soft-delete.
        {"id": "j-orphan-cust", "tenant_id": "t1",
         "customer_id": "GHOST", "customer_name": "Confirm Case",
         "technician_id": "tech-a", "status": "scheduled",
         "scheduled_date": "2026-08-01"},
        # Orphan tech — null out.
        {"id": "j-orphan-tech", "tenant_id": "t1", "customer_id": "c2",
         "technician_id": "GHOST", "technician_name": "Sara Nguyen",
         "status": "pending", "scheduled_date": "2026-08-02"},
        # Unassigned pending — flag only.
        {"id": "j-unassigned", "tenant_id": "t1", "customer_id": "c1",
         "technician_id": None, "crew_id": None,
         "status": "requested", "scheduled_date": "2026-08-03"},
        # Soft-deleted — should be excluded from scan entirely.
        {"id": "j-deleted", "tenant_id": "t1", "customer_id": "GHOST",
         "deleted_at": "2026-06-01"},
    ]
    fake = _DB(jobs=jobs, customers=customers, technicians=techs, users=users)
    monkeypatch.setattr(dr, "db", fake)

    classes = _run(dr._scan_dangling_refs())

    assert [row["job_id"] for row in classes["orphaned_customer_refs"]] == \
        ["j-orphan-cust"]
    assert classes["orphaned_customer_refs"][0]["would_action"] == "soft_delete"
    assert classes["orphaned_customer_refs"][0]["customer_name_denorm"] == \
        "Confirm Case"

    assert [row["job_id"] for row in classes["orphaned_technician_refs"]] == \
        ["j-orphan-tech"]
    assert classes["orphaned_technician_refs"][0]["would_action"] == \
        "null_technician_id"

    assert [row["job_id"] for row in classes["unassigned_pending_jobs"]] == \
        ["j-unassigned"]
    assert classes["unassigned_pending_jobs"][0]["would_action"] == "flag_only"


def test_scan_is_readonly(monkeypatch):
    """The scan MUST NOT write to ``db.jobs``. Verified by checking
    the fake collection's update/insert queues after a scan."""
    customers = [{"id": "c1", "tenant_id": "t1"}]
    jobs = [{"id": "j1", "tenant_id": "t1", "customer_id": "GHOST",
             "status": "scheduled"}]
    fake = _DB(jobs=jobs, customers=customers)
    monkeypatch.setattr(dr, "db", fake)

    _run(dr._scan_dangling_refs())

    assert fake.jobs.updates == []
    assert fake.jobs.inserts == []


def test_dry_run_endpoint_mints_confirm_token_and_persists(monkeypatch):
    """The router endpoint stores the scan report so apply can
    re-load it and returns the token to the caller."""
    fake = _DB(
        jobs=[{"id": "j1", "tenant_id": "t1", "customer_id": "GHOST",
               "status": "scheduled"}],
        customers=[],
    )
    monkeypatch.setattr(dr, "db", fake)
    # Reset the in-memory cache so this test isn't hit by leftover
    # state from earlier tests in the same process.
    monkeypatch.setattr(dr, "_dry_run_cache",
                        {"expires_at": 0.0, "payload": None})

    user = {"id": "sa-1", "role": "super_admin"}
    payload = _run(dr.data_repair_dry_run(user=user))

    assert payload["confirm_token"]
    assert payload["scan_timestamp"]
    assert payload["summary"]["total_would_change"] == 1
    assert payload["summary"]["total_flagged_no_action"] == 0
    # A scan doc must have been persisted to the fake collection.
    assert len(fake.data_integrity_scans.inserts) == 1
    stored = fake.data_integrity_scans.inserts[0]
    assert stored["confirm_token"] == payload["confirm_token"]
    assert stored["actor_user_id"] == "sa-1"
    assert isinstance(stored["expires_at"], datetime)


def test_non_super_admin_rejected():
    """The router dependency ``require_super_admin`` rejects any
    other role — this test pins that contract directly."""
    from utils import require_super_admin

    for role in ("admin", "manager", "technician", "customer", None):
        user = {"id": "u1", "role": role}
        with pytest.raises(HTTPException) as exc:
            require_super_admin(user=user)
        assert exc.value.status_code == 403
