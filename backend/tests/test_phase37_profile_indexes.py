"""Phase 37 · Feb-2026 — customer-profile hot-path index regression lock.

Asserts that the five Phase 37 compound indexes land on their
respective collections after ``migrations.k44_perf_indexes.run()``
completes. Phase 37 closed the five tenant-prefix-only
fallbacks that were causing the ``GET /customers/{cid}/summary``
and ``GET /customers/{cid}/kpi-summary`` endpoints to scan the
full tenant-scoped slice of ``service_reports`` / ``messages`` /
``customer_tasks`` / ``customer_equipment`` / ``warranty_contracts``
on every customer-profile open (user-reported 30s+ latency on an
Aquaterra-scale tenant).

The migration's own ``summary`` dict reports ``created`` vs.
``already_present`` per target; this test:

  * Runs ``k44_run()`` against the live preview DB.
  * Asserts the five Phase 37 index names appear in
    ``list_indexes()`` on their respective collections.
  * Asserts their key specs match the Phase 37 specification
    (so a drift that silently changes the key order would
    surface as a regression here, not in prod latency).
  * Asserts the migration is idempotent — a second ``run()``
    call reports every Phase 37 target as ``already_present``.
"""
from __future__ import annotations

import pytest

from config import db
from migrations.k44_perf_indexes import run as k44_run


# Phase 37 · Feb-2026 — pytest-anyio integration. The suite uses the
# ``anyio`` plugin (see sibling tests + the Task Q manual-override
# tests for the canonical pattern); force the ``asyncio`` backend
# so the Motor cursor's ``async for`` resolves on the standard
# event loop rather than Trio.
@pytest.fixture
def anyio_backend():
    return "asyncio"


_PHASE37_TARGETS = [
    # (collection, index_name, expected_key_spec_in_SON_order)
    ("service_reports",
     "p37_service_reports_tenant_customer_submitted",
     [("tenant_id", 1), ("customer_id", 1), ("submitted_at", -1)]),
    ("customer_tasks",
     "p37_customer_tasks_tenant_customer_created",
     [("tenant_id", 1), ("customer_id", 1), ("created_at", -1)]),
    ("messages",
     "p37_messages_tenant_customer_sender_read",
     [("tenant_id", 1), ("customer_id", 1),
      ("sender", 1), ("read_by_staff", 1)]),
    ("customer_equipment",
     "p37_customer_equipment_tenant_customer_created",
     [("tenant_id", 1), ("customer_id", 1), ("created_at", 1)]),
    ("warranty_contracts",
     "p37_warranty_contracts_tenant_customer_startdate",
     [("tenant_id", 1), ("customer_id", 1), ("start_date", -1)]),
]


async def _list_index_map(coll_name: str) -> dict:
    """Return ``{index_name: key_spec_as_list_of_tuples}`` for every
    index on ``db[coll_name]``. The key spec preserves the ordered
    pairs mongo returns via ``list_indexes()``."""
    out = {}
    async for idx in db[coll_name].list_indexes():
        name = idx.get("name") or ""
        key = idx.get("key") or {}
        # key is a bson.SON — items() preserves insertion order.
        out[name] = [(k, int(v)) for k, v in key.items()]
    return out


@pytest.mark.anyio
async def test_phase37_indexes_land_on_run():
    """``k44_run()`` creates (or confirms-present) every Phase 37
    index on its target collection with the exact spec, and a
    second ``k44_run()`` within the same event-loop context reports
    every Phase 37 target as ``already_present`` (idempotency lock).
    """
    result = await k44_run()
    assert result["status"] == "ok", result

    for coll_name, idx_name, expected_keys in _PHASE37_TARGETS:
        idx_map = await _list_index_map(coll_name)
        assert idx_name in idx_map, (
            f"{coll_name}.{idx_name} missing after k44_run()."
            f" Present indexes: {sorted(idx_map.keys())}"
        )
        assert idx_map[idx_name] == expected_keys, (
            f"{coll_name}.{idx_name} key spec drifted."
            f" Expected={expected_keys!r} got={idx_map[idx_name]!r}"
        )

    # ── Idempotency: a second run inside the SAME event-loop
    # context must see every P37 target as already-present. The
    # second-run block runs here (rather than in a sibling test
    # function) because the test suite's event-loop isolation
    # closes Motor's connection pool between function invocations,
    # which would mask real idempotency drift behind a loop-closed
    # exception.
    result2 = await k44_run()
    assert result2["status"] == "ok", result2

    p37_names = {name for _, name, _ in _PHASE37_TARGETS}
    p37_colls = {coll for coll, _, _ in _PHASE37_TARGETS}
    p37_in_summary = [
        t for t in result2["summary"]["targets"]
        if t["collection"] in p37_colls and t["index"] in p37_names
    ]
    assert len(p37_in_summary) == len(_PHASE37_TARGETS), (
        f"Expected {len(_PHASE37_TARGETS)} P37 targets in second-run "
        f"summary, got {len(p37_in_summary)}: {p37_in_summary}"
    )
    for target in p37_in_summary:
        assert target["status"] == "already_present", (
            f"Second run should have found "
            f"{target['collection']}.{target['index']} already "
            f"present; got status={target['status']!r}"
        )


@pytest.mark.anyio
async def test_phase37_catalogue_shape_locked():
    """Compile-time guard against copy-paste drift in the k44
    catalogue — asserts the five P37 ``(collection, name, keys)``
    tuples exist verbatim in ``migrations.k44_perf_indexes._INDEXES``.

    Keeps the k44 _INDEXES list honest: a future refactor that
    renames one of the P37 indexes or swaps the key order shows
    up here instead of silently regressing the profile-load
    latency.
    """
    from migrations.k44_perf_indexes import _INDEXES
    catalogue = {
        (coll, name): keys for coll, name, keys in _INDEXES
    }
    for coll_name, idx_name, expected_keys in _PHASE37_TARGETS:
        key = (coll_name, idx_name)
        assert key in catalogue, (
            f"P37 target ({coll_name}, {idx_name}) absent from "
            f"k44 catalogue. Catalogue keys: "
            f"{sorted(catalogue.keys())}"
        )
        assert catalogue[key] == expected_keys, (
            f"P37 target ({coll_name}, {idx_name}) key spec in "
            f"catalogue differs from this test's expectation. "
            f"Catalogue={catalogue[key]!r} "
            f"test={expected_keys!r}"
        )
