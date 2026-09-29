"""Feb-2026 · Test Hygiene Phase 1 — ``_FakeCollection.distinct()``.

Locks in the semantics of the newly-added distinct method on the
module-scope fake collection in ``test_p2_soft_delete_sweep.py``.

Real Motor / PyMongo semantics we mirror:
  1. Returns unique values across all docs for a top-level key.
  2. Respects the ``filter`` argument (docs that don't match are skipped).
  3. Nested-key access via dot-path (``"a.b"``) traverses each part.
  4. ``None`` values are excluded from the return list.
  5. Empty collection → ``[]``.
  6. Non-existent key → ``[]``.

The fake is a private test helper — this file imports it directly
from the sibling test module rather than duplicating the code.
"""
from __future__ import annotations

import asyncio

from tests.test_p2_soft_delete_sweep import _FakeCollection


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ══════════════════════════════════════════════════════════════════
# 1) Returns unique values across all docs for a top-level key
# ══════════════════════════════════════════════════════════════════
def test_distinct_returns_unique_top_level_values():
    coll = _FakeCollection([
        {"id": "a", "batch_id": "b-1"},
        {"id": "b", "batch_id": "b-2"},
        {"id": "c", "batch_id": "b-1"},  # duplicate
        {"id": "d", "batch_id": "b-3"},
    ])
    result = _run(coll.distinct("batch_id"))
    assert sorted(result) == ["b-1", "b-2", "b-3"]


# ══════════════════════════════════════════════════════════════════
# 2) Respects the filter argument
# ══════════════════════════════════════════════════════════════════
def test_distinct_respects_filter_arg():
    coll = _FakeCollection([
        {"id": "a", "tenant_id": "t-1", "batch_id": "b-1"},
        {"id": "b", "tenant_id": "t-2", "batch_id": "b-2"},
        {"id": "c", "tenant_id": "t-1", "batch_id": "b-3"},
        {"id": "d", "tenant_id": "t-2", "batch_id": "b-4"},
    ])
    result = _run(coll.distinct("batch_id", {"tenant_id": "t-1"}))
    assert sorted(result) == ["b-1", "b-3"]


def test_distinct_supports_dashboard_style_filter_with_ne_none():
    """Regression for the exact call shape used at
    ``routers/dashboard.py:250`` — ``$ne`` operator on the key
    upstream of the distinct."""
    coll = _FakeCollection([
        {"event_type": "dashboard_drilldown_edit", "tenant_id": "t-1",
         "timestamp": "2026-02-14T10:00:00Z", "bulk_batch_id": "bb-1"},
        {"event_type": "dashboard_drilldown_edit", "tenant_id": "t-1",
         "timestamp": "2026-02-14T10:05:00Z", "bulk_batch_id": None},
        {"event_type": "dashboard_drilldown_edit", "tenant_id": "t-1",
         "timestamp": "2026-02-14T10:10:00Z", "bulk_batch_id": "bb-2"},
        {"event_type": "other", "tenant_id": "t-1",
         "timestamp": "2026-02-14T10:15:00Z", "bulk_batch_id": "bb-3"},
    ])
    result = _run(coll.distinct(
        "bulk_batch_id",
        {
            "event_type": "dashboard_drilldown_edit",
            "tenant_id": "t-1",
            "bulk_batch_id": {"$ne": None},
        },
    ))
    assert sorted(result) == ["bb-1", "bb-2"]


# ══════════════════════════════════════════════════════════════════
# 3) Nested-key access
# ══════════════════════════════════════════════════════════════════
def test_distinct_nested_key_via_dot_path():
    coll = _FakeCollection([
        {"id": "a", "meta": {"tag": "x"}},
        {"id": "b", "meta": {"tag": "y"}},
        {"id": "c", "meta": {"tag": "x"}},
        {"id": "d", "meta": {}},           # missing nested key
        {"id": "e"},                        # missing whole path
    ])
    result = _run(coll.distinct("meta.tag"))
    assert sorted(result) == ["x", "y"]


# ══════════════════════════════════════════════════════════════════
# 4) None values excluded
# ══════════════════════════════════════════════════════════════════
def test_distinct_excludes_none_values():
    coll = _FakeCollection([
        {"id": "a", "batch_id": "b-1"},
        {"id": "b", "batch_id": None},
        {"id": "c", "batch_id": "b-2"},
        {"id": "d", "batch_id": None},
    ])
    result = _run(coll.distinct("batch_id"))
    assert sorted(result) == ["b-1", "b-2"]
    assert None not in result


# ══════════════════════════════════════════════════════════════════
# 5) Empty collection → []
# ══════════════════════════════════════════════════════════════════
def test_distinct_empty_collection_returns_empty_list():
    coll = _FakeCollection([])
    result = _run(coll.distinct("anything"))
    assert result == []


# ══════════════════════════════════════════════════════════════════
# 6) Non-existent key → []
# ══════════════════════════════════════════════════════════════════
def test_distinct_non_existent_key_returns_empty_list():
    coll = _FakeCollection([
        {"id": "a", "batch_id": "b-1"},
        {"id": "b", "batch_id": "b-2"},
    ])
    result = _run(coll.distinct("no_such_field"))
    assert result == []


# ══════════════════════════════════════════════════════════════════
# 7) Deterministic sort (best-effort — mixed types fall back to
#     encounter order per the docstring contract).
# ══════════════════════════════════════════════════════════════════
def test_distinct_sorts_homogeneous_values_deterministically():
    coll = _FakeCollection([
        {"n": 3}, {"n": 1}, {"n": 2}, {"n": 1},
    ])
    result = _run(coll.distinct("n"))
    assert result == [1, 2, 3]


def test_distinct_falls_back_to_encounter_order_for_unorderable_values():
    coll = _FakeCollection([
        {"v": "abc"},
        {"v": 42},
        {"v": "def"},
    ])
    result = _run(coll.distinct("v"))
    # Mixed str/int → not orderable → encounter order preserved.
    assert result == ["abc", 42, "def"]
