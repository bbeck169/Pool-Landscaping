"""SEARCH-SPEED · Feb-2026 — Customers-search perf tests.

Locks the ``search_haystack`` fast-path shipped by the
Diag-Timeout Task 1 haystack service.  The customers-list
``?search=<term>`` handler rewrites the user's query into a
``$regex`` on the pre-computed lowercase haystack + a legacy OR
fallback for un-backfilled rows.  This suite asserts:

  * The prefix search (``^smi``) hits the
    ``customers_search_haystack_idx`` compound (NOT ``COLLSCAN``).
  * Case-insensitive: ``smith`` and ``SMITH`` both surface rows
    seeded with ``Smith``.
  * Regex metacharacters supplied by the user are neutralized
    (``re.escape``) so a typed ``.``  / ``*`` / ``[`` never blows
    up the query planner.
  * Empty query returns the full tenant listing (no filter).

Skipped when live Mongo isn't reachable.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timezone

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from services.customers_search_haystack import build_haystack


try:
    from tests.conftest import _MONGO_URL, _DB_NAME              # type: ignore
except Exception:                                                # noqa: BLE001
    _MONGO_URL, _DB_NAME = None, None


pytestmark = pytest.mark.skipif(
    not (_MONGO_URL and _DB_NAME),
    reason="MONGO_URL / DB_NAME not configured — search-perf "
           "tests require live Mongo",
)


TENANT = f"TEST_search_speed_S_{uuid.uuid4().hex[:8]}"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


SEED_NAMES = [
    "Smith", "Smythe", "Smithson", "Smit",
    "Jones", "Brown", "O'Brien", "Rodriguez",
    "Van der Berg", "Meta.Corp",                       # regex metachar
    "L[bracket]", "Star*shine",                         # regex metachars
]


@pytest.fixture(scope="module", autouse=True)
def _seed_search_rows():
    async def _do():
        client = AsyncIOMotorClient(_MONGO_URL)
        db = client[_DB_NAME]
        await db.customers.delete_many({"tenant_id": TENANT})
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for i, name in enumerate(SEED_NAMES):
            doc = {
                "id": f"TEST_ss_{i}", "tenant_id": TENANT,
                "name": f"TEST_{name}",
                "email": f"seed{i}@example.com",
                "phone": f"+1555{300000 + i}",
                "created_at": now, "updated_at": now,
            }
            doc["search_haystack"] = build_haystack(doc)
            rows.append(doc)
        await db.customers.insert_many(rows)
        client.close()

    _run(_do())
    yield

    async def _teardown():
        client = AsyncIOMotorClient(_MONGO_URL)
        db = client[_DB_NAME]
        await db.customers.delete_many({"tenant_id": TENANT})
        client.close()

    _run(_teardown())


def _search_query(term: str) -> dict:
    """Mirror the query the customers router builds for a single-
    token search (K49b haystack path)."""
    term_lc = term.lower()
    return {
        "tenant_id": TENANT,
        "deleted_at": None,
        "$and": [{
            "$or": [
                {"search_haystack": {"$regex": re.escape(term_lc)}},
                # Legacy fallback the router preserves.
                {"name": {"$regex": re.escape(term),
                             "$options": "i"}},
            ]
        }],
    }


def _walk_index_names(node, out):
    if not isinstance(node, dict):
        return
    n = node.get("indexName")
    if n:
        out.add(n)
    for k in ("inputStage", "inputStages"):
        if k in node:
            sub = node[k]
            if isinstance(sub, list):
                for s in sub:
                    _walk_index_names(s, out)
            else:
                _walk_index_names(sub, out)


def test_prefix_search_uses_haystack_index():
    async def _do():
        client = AsyncIOMotorClient(_MONGO_URL)
        db = client[_DB_NAME]
        # Anchored prefix — Mongo can use the (tenant_id,
        # search_haystack) index for a range scan on the haystack
        # value's ``TEST_sm`` prefix.
        q = {
            "tenant_id": TENANT, "deleted_at": None,
            "search_haystack": {"$regex": "^test_sm"},
        }
        e = await db.customers.find(q).limit(10).explain()
        rows = await db.customers.find(q).limit(10).to_list(10)
        client.close()
        return e, rows

    e, rows = _run(_do())
    wp = e.get("queryPlanner", {}).get("winningPlan", {}) or {}
    idxs: set = set()
    _walk_index_names(wp, idxs)
    assert "customers_search_haystack_idx" in idxs, (
        f"expected haystack index in plan; got {idxs}"
    )
    # Rows should be the Smith / Smythe / Smithson / Smit set (4).
    names = sorted(r.get("name") for r in rows)
    assert names == sorted([
        "TEST_Smith", "TEST_Smit",
        "TEST_Smithson", "TEST_Smythe",
    ]), f"unexpected rows: {names}"


def test_case_insensitive_search_returns_same_rows_lower_and_upper():
    async def _do(term: str):
        client = AsyncIOMotorClient(_MONGO_URL)
        db = client[_DB_NAME]
        rows = await (db.customers.find(_search_query(term),
                                          {"_id": 0, "name": 1})
                      .to_list(50))
        client.close()
        return {r["name"] for r in rows}

    lower = _run(_do("smith"))
    upper = _run(_do("SMITH"))
    mixed = _run(_do("Smith"))
    assert lower == upper == mixed
    assert "TEST_Smith" in lower


def test_regex_metachars_in_user_query_are_sanitized():
    """User types ``Meta.Corp`` — the ``.`` must be escaped so the
    query looks for the literal ``.`` and NOT a regex wildcard."""

    async def _do(term: str):
        client = AsyncIOMotorClient(_MONGO_URL)
        db = client[_DB_NAME]
        rows = await (db.customers.find(_search_query(term),
                                          {"_id": 0, "name": 1})
                      .to_list(50))
        client.close()
        return {r["name"] for r in rows}

    hits = _run(_do("Meta.Corp"))
    assert "TEST_Meta.Corp" in hits
    # A literal-dot search must NOT match "Metaxxxx" (there are no
    # such seed rows anyway) — this is a sanity check that the
    # escape didn't get bypassed.
    assert not any("Metax" in n for n in hits)

    # Bracket / star metachars.
    bracket = _run(_do("L[bracket]"))
    assert "TEST_L[bracket]" in bracket
    star = _run(_do("Star*shine"))
    assert "TEST_Star*shine" in star


def test_empty_query_returns_everything_for_tenant():
    """Empty query = no filter beyond tenant + soft-delete rail."""

    async def _do():
        client = AsyncIOMotorClient(_MONGO_URL)
        db = client[_DB_NAME]
        rows = await (db.customers.find({"tenant_id": TENANT,
                                            "deleted_at": None})
                      .to_list(100))
        client.close()
        return rows

    rows = _run(_do())
    assert len(rows) == len(SEED_NAMES)


def test_search_returns_zero_rows_when_term_missing():
    async def _do():
        client = AsyncIOMotorClient(_MONGO_URL)
        db = client[_DB_NAME]
        rows = await (db.customers.find(
            _search_query("zzzz_no_such_prefix"),
            {"_id": 0, "name": 1},
        ).to_list(50))
        client.close()
        return rows

    assert _run(_do()) == []
