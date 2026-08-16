"""Queue Item 5b · Feb-2026 — pricebook importer pytest suite.

Mocks the MCP layer via ``gql_query`` monkeypatch — no network. Uses
an in-memory fake Mongo shaped identically to
``test_homeworks_importer.py`` so the two suites stay isomorphic and
easy to diff.

Covered:
  1. **Dry-run counts** — total_item_count reflects the page fixture.
  2. **Name-collision skip** — an existing manually-created item with
     the same name (case-insensitive) causes the incoming item to be
     skipped and an error_log entry to accrue.
  3. **Category fuzzy match** — case+whitespace-insensitive match
     against an existing service_categories row hits it.
  4. **Unknown category → catch-all** — creates the
     ``Homeworks (unmapped)`` row once and reuses it.
  5. **Idempotent double-run** — second pass adds zero new items
     (skip-by-original_id).
  6. **Cascade auto-stop** — 5 consecutive page failures halt the
     run with status=paused_needs_attention.
"""
from __future__ import annotations

import asyncio
import re
import sys
from typing import Any, Dict, List

import pytest

sys.path.insert(0, "/app/backend")

from services.homeworks_mcp import (  # noqa: E402
    pricebook_importer as imp,
    queries,
)


# ── Fake Mongo & Motor plumbing ──────────────────────────────────────
class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def sort(self, *_a, **_k):    return self
    def skip(self, *_a, **_k):    return self
    def limit(self, *_a, **_k):   return self
    def to_list(self, length=None):
        async def _await():
            return list(self._rows[: length or len(self._rows)])
        return _await()

    def __aiter__(self):
        self._i = 0
        return self

    async def __anext__(self):
        if self._i >= len(self._rows):
            raise StopAsyncIteration
        r = self._rows[self._i]
        self._i += 1
        return r


def _match(doc: Dict[str, Any], q: Dict[str, Any]) -> bool:
    """Support the tiny slice of Mongo query grammar the importer uses:
    equality, ``$exists``, ``$ne``, ``$in``, ``$regex``, ``$or``, ``$and``.
    """
    for k, v in q.items():
        if k == "$or":
            if not any(_match(doc, cl) for cl in v):
                return False
            continue
        if k == "$and":
            if not all(_match(doc, cl) for cl in v):
                return False
            continue
        actual = doc.get(k)
        if isinstance(v, dict):
            if "$exists" in v:
                exists = k in doc
                if exists != bool(v["$exists"]):
                    return False
            if "$ne" in v:
                if actual == v["$ne"]:
                    return False
            if "$in" in v:
                if actual not in v["$in"]:
                    return False
            if "$regex" in v:
                if not isinstance(actual, str):
                    return False
                flags = re.IGNORECASE if "i" in (v.get("$options") or "") else 0
                if not re.search(v["$regex"], actual, flags):
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
                if "$set" in upd: d.update(upd["$set"])
                if "$push" in upd:
                    for kk, vv in upd["$push"].items():
                        d.setdefault(kk, []).append(vv)
                return type("_R", (), {"matched_count": 1, "modified_count": 1})
        return type("_R", (), {"matched_count": 0, "modified_count": 0})


class _DB:
    def __init__(self):
        self.items = _Coll()
        self.service_categories = _Coll()
        self.homeworks_import_runs = _Coll()


@pytest.fixture
def fake_db(monkeypatch):
    d = _DB()
    monkeypatch.setattr(
        "services.homeworks_mcp.pricebook_importer.db", d, raising=False,
    )
    return d


# ── Fake gql layer ───────────────────────────────────────────────────
def _fake_item(id_: int, *, name: str = "Widget",
                 category: str = "Chemicals", price: float = 10.0,
                 type_: str = "ITEM") -> Dict[str, Any]:
    return {
        "id": id_, "name": name, "description": "",
        "type": type_, "price": price, "unit": "each",
        "tax1": 0.0, "tax2": 0.0, "isTaxable": True,
        "materialCost": price * 0.4, "equipmentCost": 0.0,
        "subcontractCost": 0.0, "wholesaleCost": price * 0.4,
        "markup": 60.0, "markupType": "PERCENT",
        "category": {"id": 1, "name": category},
    }


def _stub_gql(pages: List[List[Dict[str, Any]]], *,
                fail_first_page_pages: int = 0):
    """Returns a fake ``gql_query`` yielding items page-by-page.

    ``fail_first_page_pages`` — raise MCPError on the first N page
    fetches (used to exercise the cascade stop).
    """
    from services.homeworks_mcp.client import MCPError
    state = {"call": 0, "failed": 0}

    async def _fn(*, tenant_id, query, variables=None, user_id=None):
        state["call"] += 1
        skip = (variables or {}).get("skip", 0)
        take = (variables or {}).get("take", imp.PAGE_SIZE)
        if query == queries.ITEM_COUNT_PAGE_QUERY:
            all_items = [it for pg in pages for it in pg]
            return {"items": all_items[skip:skip + take]}
        if query == queries.ITEM_PAGE_QUERY:
            if state["failed"] < fail_first_page_pages:
                state["failed"] += 1
                raise MCPError(f"fake_page_error_{state['failed']}")
            all_items = [it for pg in pages for it in pg]
            return {"items": all_items[skip:skip + take]}
        return {}

    return _fn


# ── 1. Dry-run counts ────────────────────────────────────────────────
def test_dry_run_reports_total_count(fake_db, monkeypatch):
    rows = [_fake_item(i, name=f"Item {i}") for i in range(1, 8)]
    monkeypatch.setattr(
        "services.homeworks_mcp.pricebook_importer.gql_query",
        _stub_gql([rows]),
    )
    report = asyncio.get_event_loop().run_until_complete(
        imp.dry_run("t1", user_id="u1"),
    )
    assert report.total_item_count == 7
    assert report.existing_in_aquaterra_by_original_id == 0
    assert not report.fatal_error


# ── 2. Name-collision skip ───────────────────────────────────────────
def test_name_collision_skips_and_logs(fake_db, monkeypatch):
    # Existing manually-created item that will collide.
    asyncio.get_event_loop().run_until_complete(
        fake_db.items.insert_one({
            "id": "existing-1", "tenant_id": "t1",
            "name": "widget",  # case-insensitive collision
        }),
    )
    rows = [_fake_item(1, name="Widget")]
    monkeypatch.setattr(
        "services.homeworks_mcp.pricebook_importer.gql_query",
        _stub_gql([rows]),
    )
    run_id = asyncio.get_event_loop().run_until_complete(
        imp.create_run(tenant_id="t1", user_id="u1",
                        dry_run_report=None, status="queued"),
    )
    counters = asyncio.get_event_loop().run_until_complete(
        imp.run_full(tenant_id="t1", user_id="u1", run_id=run_id),
    )
    assert counters.items_scanned == 1
    assert counters.items_imported == 0
    assert counters.items_skipped_by_name_collision == 1
    # error_log carries a reason entry.
    run = asyncio.get_event_loop().run_until_complete(
        fake_db.homeworks_import_runs.find_one({"run_id": run_id}),
    )
    reasons = [e.get("reason") for e in (run.get("error_log") or [])]
    assert "name_collision_with_existing_item" in reasons


# ── 3. Category fuzzy match ──────────────────────────────────────────
def test_category_fuzzy_match_hits_existing(fake_db, monkeypatch):
    asyncio.get_event_loop().run_until_complete(
        fake_db.service_categories.insert_one({
            "id": "sc-chem", "tenant_id": "t1",
            "name": "  Chemicals  ",  # extra whitespace on purpose
        }),
    )
    rows = [_fake_item(1, name="Chlorine", category="chemicals")]
    monkeypatch.setattr(
        "services.homeworks_mcp.pricebook_importer.gql_query",
        _stub_gql([rows]),
    )
    run_id = asyncio.get_event_loop().run_until_complete(
        imp.create_run(tenant_id="t1", user_id="u1",
                        dry_run_report=None, status="queued"),
    )
    asyncio.get_event_loop().run_until_complete(
        imp.run_full(tenant_id="t1", user_id="u1", run_id=run_id),
    )
    landed = asyncio.get_event_loop().run_until_complete(
        fake_db.items.find_one({"homeworks_original_id": "1"}),
    )
    assert landed is not None
    assert landed["service_category_id"] == "sc-chem"


# ── 4. Unknown category → catch-all ──────────────────────────────────
def test_unknown_category_creates_catch_all(fake_db, monkeypatch):
    rows = [
        _fake_item(1, name="A", category="Nonexistent"),
        _fake_item(2, name="B", category="AlsoUnknown"),
    ]
    monkeypatch.setattr(
        "services.homeworks_mcp.pricebook_importer.gql_query",
        _stub_gql([rows]),
    )
    run_id = asyncio.get_event_loop().run_until_complete(
        imp.create_run(tenant_id="t1", user_id="u1",
                        dry_run_report=None, status="queued"),
    )
    asyncio.get_event_loop().run_until_complete(
        imp.run_full(tenant_id="t1", user_id="u1", run_id=run_id),
    )
    catch_all = asyncio.get_event_loop().run_until_complete(
        fake_db.service_categories.find_one({"name": imp.CATCH_ALL_CATEGORY_NAME}),
    )
    assert catch_all is not None
    landed_a = asyncio.get_event_loop().run_until_complete(
        fake_db.items.find_one({"homeworks_original_id": "1"}),
    )
    landed_b = asyncio.get_event_loop().run_until_complete(
        fake_db.items.find_one({"homeworks_original_id": "2"}),
    )
    # Both items point to the same catch-all row.
    assert landed_a["service_category_id"] == catch_all["id"]
    assert landed_b["service_category_id"] == catch_all["id"]


# ── 5. Idempotent double-run ─────────────────────────────────────────
def test_double_run_zero_new_inserts(fake_db, monkeypatch):
    rows = [_fake_item(i, name=f"Item {i}") for i in range(1, 4)]
    monkeypatch.setattr(
        "services.homeworks_mcp.pricebook_importer.gql_query",
        _stub_gql([rows]),
    )
    run_1 = asyncio.get_event_loop().run_until_complete(
        imp.create_run(tenant_id="t1", user_id="u1",
                        dry_run_report=None, status="queued"),
    )
    c1 = asyncio.get_event_loop().run_until_complete(
        imp.run_full(tenant_id="t1", user_id="u1", run_id=run_1),
    )
    assert c1.items_imported == 3

    run_2 = asyncio.get_event_loop().run_until_complete(
        imp.create_run(tenant_id="t1", user_id="u1",
                        dry_run_report=None, status="queued"),
    )
    c2 = asyncio.get_event_loop().run_until_complete(
        imp.run_full(tenant_id="t1", user_id="u1", run_id=run_2),
    )
    assert c2.items_imported == 0
    assert c2.items_skipped_by_original_id == 3


# ── 6. Cascade auto-stop after 5 consecutive page failures ───────────
def test_cascade_stop_after_5_consecutive_page_failures(fake_db, monkeypatch):
    rows = [_fake_item(1)]
    monkeypatch.setattr(
        "services.homeworks_mcp.pricebook_importer.gql_query",
        _stub_gql([rows], fail_first_page_pages=999),
    )
    # Skip the retry backoff so the test is fast.
    _real_sleep = asyncio.sleep
    monkeypatch.setattr(
        "services.homeworks_mcp.pricebook_importer.asyncio.sleep",
        lambda *_a, **_k: _real_sleep(0),
    )
    run_id = asyncio.get_event_loop().run_until_complete(
        imp.create_run(tenant_id="t1", user_id="u1",
                        dry_run_report=None, status="queued"),
    )
    asyncio.get_event_loop().run_until_complete(
        imp.run_full(tenant_id="t1", user_id="u1", run_id=run_id),
    )
    run = asyncio.get_event_loop().run_until_complete(
        fake_db.homeworks_import_runs.find_one({"run_id": run_id}),
    )
    assert run["status"] == "paused_needs_attention"
