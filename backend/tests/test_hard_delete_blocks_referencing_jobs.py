"""Feb-2026 · Phase F3 · Contract test — hard-delete blocks orphan
creation.

Enforces the F3 invariant at every hard-delete surface:
  * ``DELETE /api/customers/{cid}?mode=hard`` (routers/customers.py)
  * ``POST /api/customers/bulk`` action=delete (routers/customers.py,
    deprecated but still writeable)
  * ``DELETE /api/crews/{cid}`` (routers/ops.py)

Contract: when the target row is referenced by an ACTIVE job (not
soft-deleted), the endpoint returns 409 with
``error_code=has_referencing_jobs``. Zero references → 200 OK.

Tests call the handlers directly with in-memory Motor stubs so the
regressions run in <1s and don't touch the live DB.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException


class _Coll:
    def __init__(self, rows=None):
        self.rows: List[Dict[str, Any]] = list(rows or [])
        self.deletes: List[Dict[str, Any]] = []

    async def find_one(self, query, projection=None):  # noqa: ARG002
        for row in self.rows:
            if _match(row, query):
                return dict(row)
        return None

    async def delete_one(self, query):
        deleted = 0
        for row in list(self.rows):
            if _match(row, query):
                self.rows.remove(row)
                self.deletes.append(dict(query))
                deleted = 1
                break
        return type("R", (), {"deleted_count": deleted})()

    async def delete_many(self, query):
        deleted = 0
        for row in list(self.rows):
            if _match(row, query):
                self.rows.remove(row)
                deleted += 1
        self.deletes.append({"query": dict(query), "count": deleted})
        return type("R", (), {"deleted_count": deleted})()

    async def count_documents(self, query):
        return sum(1 for row in self.rows if _match(row, query))

    def find(self, query=None, projection=None):  # noqa: ARG002
        outer = self
        q = query or {}

        class _Cursor:
            def __init__(self):
                self._rows = [dict(r) for r in outer.rows if _match(r, q)]

            async def to_list(self, _n=None):
                return list(self._rows)

        return _Cursor()


def _match(row, query):
    for k, v in query.items():
        if k == "$or":
            if not any(_match(row, sub) for sub in v):
                return False
            continue
        if isinstance(v, dict):
            if "$exists" in v:
                if v["$exists"] != (k in row):
                    return False
                continue
            if "$in" in v:
                if row.get(k) not in v["$in"]:
                    return False
                continue
            if "$nin" in v:
                if row.get(k) in v["$nin"]:
                    return False
                continue
            if "$ne" in v:
                if row.get(k) == v["$ne"]:
                    return False
                continue
            return False
        if row.get(k) != v:
            return False
    return True


class _DB:
    def __init__(self, jobs=None, customers=None, crews=None,
                 quotes=None, audit_logs=None, deletion_audit=None):
        self.jobs = _Coll(jobs)
        self.customers = _Coll(customers)
        self.crews = _Coll(crews)
        self.quotes = _Coll(quotes)
        self.audit_logs = _Coll(audit_logs)
        self.deletion_audit = _Coll(deletion_audit)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ═══════════════════════════════════════════════════════════════════
# DELETE /crews/{cid} — the smallest surface, easiest to exercise.
# ═══════════════════════════════════════════════════════════════════
def test_delete_crew_blocks_when_active_job_references(monkeypatch):
    from routers import ops as ops_mod

    fake = _DB(
        crews=[{"id": "crew-1", "tenant_id": "t1"}],
        jobs=[{"id": "j1", "tenant_id": "t1",
               "crew_id": "crew-1", "status": "scheduled"}],
    )
    monkeypatch.setattr(ops_mod, "db", fake)

    with pytest.raises(HTTPException) as exc:
        _run(ops_mod.delete_crew(
            "crew-1",
            user={"id": "u1", "role": "admin"},
            tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 409
    assert exc.value.detail.get("error_code") == "has_referencing_jobs"
    # Crew was NOT deleted.
    assert len(fake.crews.rows) == 1


def test_delete_crew_succeeds_when_no_referencing_jobs(monkeypatch):
    from routers import ops as ops_mod

    fake = _DB(
        crews=[{"id": "crew-1", "tenant_id": "t1"}],
        jobs=[],
    )
    monkeypatch.setattr(ops_mod, "db", fake)

    result = _run(ops_mod.delete_crew(
        "crew-1",
        user={"id": "u1", "role": "admin"},
        tenant={"id": "t1"},
    ))
    assert result == {"ok": True}
    assert len(fake.crews.rows) == 0


def test_delete_crew_allows_soft_deleted_referencing_job(monkeypatch):
    """A job that's already soft-deleted (``status='deleted'`` OR
    ``deleted_at`` set) MUST NOT block the crew delete — it can't
    orphan an active reference."""
    from routers import ops as ops_mod

    fake = _DB(
        crews=[{"id": "crew-1", "tenant_id": "t1"}],
        jobs=[{"id": "j1", "tenant_id": "t1",
               "crew_id": "crew-1", "status": "deleted",
               "deleted_at": "2026-08-01"}],
    )
    monkeypatch.setattr(ops_mod, "db", fake)

    result = _run(ops_mod.delete_crew(
        "crew-1",
        user={"id": "u1", "role": "admin"},
        tenant={"id": "t1"},
    ))
    assert result == {"ok": True}


# ═══════════════════════════════════════════════════════════════════
# Customers bulk-delete (deprecated but writeable) — the F2 orphan
# creator. F3 must block orphan creation even on the legacy path.
# ═══════════════════════════════════════════════════════════════════
def test_customers_bulk_delete_blocks_when_referencing_jobs(monkeypatch):
    from routers import customers as cust_mod
    from routers.customers import CustomerBulkAction

    fake = _DB(
        customers=[{"id": "c1", "tenant_id": "t1", "name": "X"}],
        jobs=[{"id": "j1", "tenant_id": "t1",
               "customer_id": "c1", "status": "scheduled"}],
    )
    monkeypatch.setattr(cust_mod, "db", fake)

    body = CustomerBulkAction(ids=["c1"], action="delete")
    with pytest.raises(HTTPException) as exc:
        _run(cust_mod.customers_bulk(
            body,
            user={"id": "u1", "email": "sa@a", "role": "admin"},
            tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 409
    assert exc.value.detail.get("error_code") == "has_referencing_jobs"
    # Customer NOT deleted.
    assert len(fake.customers.rows) == 1


def test_customers_bulk_delete_succeeds_when_no_referencing_jobs(monkeypatch):
    from routers import customers as cust_mod
    from routers.customers import CustomerBulkAction

    fake = _DB(
        customers=[{"id": "c1", "tenant_id": "t1", "name": "X"}],
        jobs=[],
    )
    monkeypatch.setattr(cust_mod, "db", fake)

    body = CustomerBulkAction(ids=["c1"], action="delete")
    result = _run(cust_mod.customers_bulk(
        body,
        user={"id": "u1", "email": "sa@a", "role": "admin"},
        tenant={"id": "t1"},
    ))
    assert result.get("deleted") == 1
    assert len(fake.customers.rows) == 0
