"""Feb-2026 · Phase 1b — Inactive-customers importer P0 invariants.

Covers the three non-negotiable properties before launching real data:

  1. **Idempotency** — a double-run over the same page produces zero
     new customers on the second pass (all skipped by ``original_id``).
  2. **Cancel flag honoured** — flipping ``status`` to ``cancelling``
     between page fetches makes the driver exit ``status=cancelled``.
  3. **Cascade auto-stop** — 5 consecutive per-customer failures
     ``paused_needs_attention`` the run.

Mocks the MCP layer via ``gql_query`` monkeypatch — no network.
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

sys.path.insert(0, "/app/backend")

from services.homeworks_mcp import (  # noqa: E402
    inactive_customers_importer as imp,
    queries,
)


# ── Fake Mongo & Motor plumbing ──────────────────────────────────────
class _Coll:
    def __init__(self):
        self._d: List[Dict[str, Any]] = []

    async def find_one(self, q, projection=None):
        for d in self._d:
            if all(d.get(k) == v for k, v in q.items()
                    if not isinstance(v, dict)):
                return {**d}
        return None

    async def count_documents(self, q):
        hits = 0
        for d in self._d:
            ok = True
            for k, v in q.items():
                if isinstance(v, dict) and "$in" in v:
                    if d.get(k) not in v["$in"]:
                        ok = False; break
                elif d.get(k) != v:
                    ok = False; break
            if ok: hits += 1
        return hits

    async def insert_one(self, doc):
        self._d.append({**doc})
        return type("_R", (), {"inserted_id": len(self._d)})

    async def insert_many(self, docs):
        for d in docs: self._d.append({**d})
        return type("_R", (), {"inserted_ids": list(range(len(docs)))})

    async def update_one(self, q, upd):
        for d in self._d:
            if all(d.get(k) == v for k, v in q.items()
                    if not isinstance(v, dict)):
                if "$set" in upd: d.update(upd["$set"])
                if "$push" in upd:
                    for k, v in upd["$push"].items():
                        d.setdefault(k, []).append(v)
                return type("_R", (), {"matched_count": 1})
        return type("_R", (), {"matched_count": 0})


class _DB:
    def __init__(self):
        self.customers = _Coll()
        self.jobs = _Coll()
        self.invoices = _Coll()
        self.payments = _Coll()
        self.quotes = _Coll()
        self.homeworks_import_runs = _Coll()
        self.audit_logs = _Coll()


@pytest.fixture
def fake_db(monkeypatch):
    d = _DB()
    monkeypatch.setattr("services.homeworks_mcp.inactive_customers_importer.db",
                         d, raising=False)
    return d


# ── Fake gql layer ───────────────────────────────────────────────────
def _fake_customer(id_: int, name: str = "X") -> Dict[str, Any]:
    return {
        "id": id_, "email": f"c{id_}@x.test", "fullName": name,
        "firstName": name, "lastName": "", "status": "INACTIVE",
        "pic": None, "tags": [], "address": {}, "location": None,
        "description": "",
    }


def _stub_gql(pages):
    calls = {"n": 0, "children": 0}
    async def _fn(*, tenant_id, query, variables=None, user_id=None):
        if query == queries.CUSTOMER_PAGE_QUERY:
            skip = (variables or {}).get("skip", 0)
            take = (variables or {}).get("take", 25)
            all_c = [c for pg in pages for c in pg]
            return {"customers": all_c[skip:skip+take]}
        if query in (
            queries.CUSTOMER_EVENTS_QUERY,
            queries.CUSTOMER_INVOICES_QUERY,
            queries.CUSTOMER_PAYMENTS_QUERY,
            queries.CUSTOMER_ESTIMATES_QUERY,
        ):
            calls["children"] += 1
            key = {queries.CUSTOMER_EVENTS_QUERY: "events",
                    queries.CUSTOMER_INVOICES_QUERY: "invoices",
                    queries.CUSTOMER_PAYMENTS_QUERY: "payments",
                    queries.CUSTOMER_ESTIMATES_QUERY: "estimates"}[query]
            return {key: []}
        return {}
    _fn.calls = calls  # type: ignore[attr-defined]
    return _fn


# ── Tests ────────────────────────────────────────────────────────────
class TestIdempotency:
    def test_double_run_zero_new(self, fake_db, monkeypatch):
        rows = [_fake_customer(1, "Alpha"), _fake_customer(2, "Bravo")]
        gql = _stub_gql([rows])
        monkeypatch.setattr(
            "services.homeworks_mcp.inactive_customers_importer.gql_query",
            gql,
        )
        # Run 1.
        run_id = asyncio.get_event_loop().run_until_complete(
            imp.create_run(tenant_id="t1", user_id="u1",
                            dry_run_report=None, status="queued")
        )
        c1 = asyncio.get_event_loop().run_until_complete(
            imp.run_full(tenant_id="t1", user_id="u1", run_id=run_id)
        )
        assert c1.customers_imported == 2
        assert c1.customers_skipped == 0
        # Run 2 (same data).
        run2 = asyncio.get_event_loop().run_until_complete(
            imp.create_run(tenant_id="t1", user_id="u1",
                            dry_run_report=None, status="queued")
        )
        c2 = asyncio.get_event_loop().run_until_complete(
            imp.run_full(tenant_id="t1", user_id="u1", run_id=run2)
        )
        assert c2.customers_imported == 0
        assert c2.customers_skipped == 2
        # Zero duplicates in the customers collection.
        assert len(fake_db.customers._d) == 2


class TestCancelFlag:
    def test_cancelling_status_stops_driver(self, fake_db, monkeypatch):
        # Big page so the driver has room to notice the cancel.
        rows = [_fake_customer(i, f"C{i}") for i in range(1, 26)]
        monkeypatch.setattr(
            "services.homeworks_mcp.inactive_customers_importer.gql_query",
            _stub_gql([rows]),
        )
        # Pre-flip to `cancelling` — driver should exit clean on first check.
        run_id = asyncio.get_event_loop().run_until_complete(
            imp.create_run(tenant_id="t1", user_id="u1",
                            dry_run_report=None, status="cancelling")
        )
        c = asyncio.get_event_loop().run_until_complete(
            imp.run_full(tenant_id="t1", user_id="u1", run_id=run_id)
        )
        # Nothing imported; final status is `cancelled`.
        assert c.customers_imported == 0
        doc = asyncio.get_event_loop().run_until_complete(
            fake_db.homeworks_import_runs.find_one({"run_id": run_id})
        )
        assert doc["status"] == "cancelled"


class TestCascadeAutoStop:
    def test_five_consecutive_failures_pauses(self, fake_db, monkeypatch):
        rows = [_fake_customer(i, f"C{i}") for i in range(1, 11)]

        # gql_query fake — page returns rows; children RAISE.
        async def _fn(*, tenant_id, query, variables=None, user_id=None):
            if query == queries.CUSTOMER_PAGE_QUERY:
                return {"customers": rows}
            raise imp.MCPError("simulated child failure")
        monkeypatch.setattr(
            "services.homeworks_mcp.inactive_customers_importer.gql_query",
            _fn,
        )
        run_id = asyncio.get_event_loop().run_until_complete(
            imp.create_run(tenant_id="t1", user_id="u1",
                            dry_run_report=None, status="queued")
        )
        asyncio.get_event_loop().run_until_complete(
            imp.run_full(tenant_id="t1", user_id="u1", run_id=run_id)
        )
        doc = asyncio.get_event_loop().run_until_complete(
            fake_db.homeworks_import_runs.find_one({"run_id": run_id})
        )
        assert doc["status"] == "paused_needs_attention"
        # Exactly 5 failures before the auto-stop kicks in.
        assert doc["counters"]["customers_failed"] == 5
        assert len(doc["error_log"]) >= 5
