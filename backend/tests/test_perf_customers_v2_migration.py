"""CUS-perf · Feb-2026 — perf_customers_v2 migration wiring.

Locks the following contracts for the Customers-list sort-path
compound indexes shipped in
``services/migrations/perf_customers_indexes_v2.py``:

  1. **Idempotency.** Running ``run(db)`` twice against a live Motor
     DB produces the three expected indexes on the first pass and
     reports ``skipped=True`` on the second. Both runs succeed
     without error.
  2. **Expected index shape.** The migration creates ONE compound
     index per row of the ``_INDEXES`` catalogue with the exact
     name + key spec ruled at Phase 0. ``list_indexes()`` MUST
     include each after a fresh run.
  3. **Version marker.** After a successful run the migration writes
     ``{"key": "perf_customers_v2", "completed_at": <iso>, ...}`` to
     ``db.migration_status`` (NOT ``db.migrations`` — the latter is
     the diagnostic collection used by k44 / dashboard indexes).
  4. **Source-level guardrail.** ``server.py`` MUST invoke
     ``_run_perf_customers_v2_boot`` from inside ``_run_boot_sequence``
     — a refactor that moves the call into a background task would
     silently stop the sentinel from being written on cold starts.
  5. **``_REQUIRED_MIGRATIONS`` sentinel guard.** Per ruling R2, v2
     is NOT in ``_REQUIRED_MIGRATIONS`` — adding it there would
     503 ``/health/ready`` during background index builds on rolling
     deploys against a large ``customers`` collection.

Ruling R5 · Feb-2026 — the primary static test uses the shared
``run_test`` fixture to drive a live Motor DB against the real
migration coroutine (fast, in-CI). A deeper explain-plan check is
gated behind ``-m integration`` (see the marked test at the bottom
of the file) so a preview-DB verification can be triggered on
demand without slowing CI.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests._f7_loop_fixture import run_test


MIGRATION_KEY = "perf_customers_v2"

# (index_name, [(key, direction), ...])
EXPECTED_INDEXES = [
    ("perf_customers_v2_tenant_created",
     [("tenant_id", 1), ("created_at", 1), ("_id", 1)]),
    ("perf_customers_v2_tenant_lastname_firstname",
     [("tenant_id", 1), ("last_name", 1),
      ("first_name", 1), ("_id", 1)]),
    ("perf_customers_v2_tenant_name",
     [("tenant_id", 1), ("name", 1), ("_id", 1)]),
]


# ── 1) Idempotency + expected indexes present ─────────────────────


def test_perf_customers_v2_run_is_idempotent_and_creates_expected_indexes():
    """First run: creates OR reuses existing indexes and stamps the
    sentinel. Second run: sentinel hit, returns ``skipped=True`` with
    zero creates. ``list_indexes()`` includes each expected name on
    both runs (indexes survive between the two)."""
    async def _go(db):
        from services.migrations.perf_customers_indexes_v2 import run

        # Clean slate — remove the sentinel so run() actually executes.
        await db.migration_status.delete_one({"key": MIGRATION_KEY})

        res1 = await run(db)
        assert res1["ok"] is True
        assert res1["skipped"] is False, (
            f"First run reported skipped=True — sentinel state leaked "
            f"from a prior test: {res1}"
        )

        # Every expected index must appear on the ``customers``
        # collection, OR a compatible pre-existing compound sharing
        # the first two keys must be present (the v1-style safety
        # net skips creation in that case).
        names = set()
        async for idx in db.customers.list_indexes():
            names.add(idx.get("name") or "")
        for idx_name, keys in EXPECTED_INDEXES:
            first, second = keys[0][0], keys[1][0]
            has_expected = idx_name in names
            has_compat = False
            async for idx in db.customers.list_indexes():
                ks = list((idx.get("key") or {}).items())
                if (len(ks) >= 2
                        and ks[0][0] == first
                        and ks[1][0] == second):
                    has_compat = True
                    break
            assert has_expected or has_compat, (
                f"customers: neither expected index {idx_name!r} nor "
                f"a compatible ({first}, {second}, ...) index found — "
                f"actual indexes: {sorted(names)}"
            )

        # Second run — sentinel is set, no-op.
        res2 = await run(db)
        assert res2["ok"] is True
        assert res2["skipped"] is True, (
            f"Second run should be sentinel-skipped but was: {res2}"
        )
        assert res2["created"] == 0
        assert res2["reason"] == "already_ran"

    run_test(_go)


# ── 2) Version marker written to migration_status ─────────────────


def test_perf_customers_v2_run_writes_sentinel_to_migration_status():
    """After a successful run, ``migration_status`` MUST contain a
    row with ``key = perf_customers_v2`` and a truthy ``completed_at``
    ISO-8601 timestamp. ``db.migrations`` MUST NOT be touched — that
    collection is the diagnostic-only sentinel used by k44 / dashboard
    index migrations."""
    async def _go(db):
        from services.migrations.perf_customers_indexes_v2 import run

        await db.migration_status.delete_one({"key": MIGRATION_KEY})
        # Belt-and-suspenders: also clear any accidentally-crossed
        # ``db.migrations`` row so a stale entry doesn't mask a
        # regression that writes to the wrong collection.
        await db.migrations.delete_many({"id": MIGRATION_KEY})

        await run(db)

        row = await db.migration_status.find_one(
            {"key": MIGRATION_KEY}, {"_id": 0},
        )
        assert row is not None, (
            "migration_status row missing — perf_customers_v2 "
            "sentinel was not written."
        )
        assert row.get("key") == MIGRATION_KEY
        assert row.get("completed_at"), (
            f"perf_customers_v2 sentinel missing completed_at: {row}"
        )
        # Basic ISO-8601 shape check.
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}",
            row["completed_at"],
        ), f"completed_at not ISO-8601: {row['completed_at']!r}"

        # ``db.migrations`` (diagnostic collection) MUST NOT have
        # received a row keyed by this migration — the sentinel
        # collection is exclusively ``migration_status``.
        wrong_row = await db.migrations.find_one({"id": MIGRATION_KEY})
        assert wrong_row is None, (
            "perf_customers_v2 wrote to db.migrations — should be "
            "db.migration_status only."
        )

    run_test(_go)


# ── 3) Source-level guardrail — wrapper is invoked from _run_boot_sequence ─


def test_perf_customers_v2_call_is_in_run_boot_sequence():
    """Source-level lint — ``server.py`` MUST invoke
    ``_run_perf_customers_v2_boot`` from inside ``_run_boot_sequence``
    (structural bucket, pre-yield). A refactor that accidentally
    moves it into a background task would silently stop the
    ``migration_status`` sentinel from being written on cold starts,
    and the /api/health surface would lose visibility into build
    failures.
    """
    src = Path(__file__).resolve().parents[1] / "server.py"
    body = src.read_text(encoding="utf-8")

    m_boot = re.search(
        r"^async def _run_boot_sequence\(\).*?(?=^async def |\Z)",
        body, flags=re.MULTILINE | re.DOTALL,
    )
    assert m_boot is not None, (
        "_run_boot_sequence not found in server.py — refactor "
        "regression."
    )
    boot_body = m_boot.group(0)
    assert "_run_perf_customers_v2_boot" in boot_body, (
        "_run_perf_customers_v2_boot is NOT invoked inside "
        "_run_boot_sequence — the perf_customers_v2 sentinel will "
        "never be written on cold starts and the /api/health surface "
        "loses visibility into build failures."
    )


# ── 4) Guard — v2 must NOT be in _REQUIRED_MIGRATIONS (ruling R2) ─


def test_perf_customers_v2_is_not_in_required_migrations():
    """Per ruling R2, ``perf_customers_v2`` is best-effort and MUST
    NOT gate ``/health/ready``. Adding it to ``_REQUIRED_MIGRATIONS``
    would 503 the pod during background index builds against a
    10K-50K-doc ``customers`` collection on rolling deploys.

    Guards both call sites — the ready-probe list in
    ``server.py`` and the mirrored list in
    ``routers/admin_health_check.py``.
    """
    for rel in ("server.py", "routers/admin_health_check.py"):
        src = Path(__file__).resolve().parents[1] / rel
        body = src.read_text(encoding="utf-8")
        m = re.search(
            r"_?REQUIRED_MIGRATIONS[^=]*=\s*\[([^\]]*)\]",
            body,
        )
        assert m is not None, (
            f"REQUIRED_MIGRATIONS list not found in {rel} — the "
            f"ready-gate contract has moved; update the guard."
        )
        listing = m.group(1)
        assert MIGRATION_KEY not in listing, (
            f"{rel}: {MIGRATION_KEY!r} appears in "
            f"_REQUIRED_MIGRATIONS — ruling R2 says v2 MUST be "
            f"best-effort and NOT gate /health/ready. Remove it."
        )


# ── 5) Deferred integration test — explain-plan against a live DB ─
#
# Gated behind ``-m integration`` per ruling R5 so CI stays fast
# and preview-DB verification is opt-in. Confirms that the primary
# sort path (``created_desc`` default) picks IXSCAN via the v2
# compound index and produces zero in-memory ``SORT`` stages. Run
# via::
#
#     pytest backend/tests/test_perf_customers_v2_migration.py \
#         -m integration -v
#


@pytest.mark.integration
def test_perf_customers_v2_explain_plan_uses_ixscan_no_inmemory_sort():
    """Verify against a live Motor DB that the Customers-list sort
    path uses IXSCAN on the v2 compound index and produces no
    in-memory ``SORT`` stage.

    Skipped by default; run explicitly with ``-m integration``
    against a preview DB. Requires the migration to have already
    landed on the target DB (either via a prior boot or by running
    the idempotency test above first)."""
    async def _go(db):
        from services.migrations.perf_customers_indexes_v2 import run

        # Ensure the v2 indexes are in place. Idempotent — no-op
        # when the sentinel is already stamped.
        await run(db)

        # Grab any tenant_id that has customer rows so the explain
        # runs against a realistic query, not an empty predicate.
        sample = await db.customers.find_one({}, {"tenant_id": 1})
        tenant_id = (sample or {}).get("tenant_id") or "tenant-probe"

        # The primary Customers-list sort — ``created_desc`` default.
        # Matches the fast-path builder in ``routers/customers.py``
        # (see ``_SORT_MAP["created_desc"]``).
        cur = (db.customers.find({"tenant_id": tenant_id}, {"_id": 0})
                .sort([("created_at", -1), ("_id", -1)])
                .skip(0).limit(25))
        plan = await cur.explain()

        # Walk ONLY the winning plan sub-tree — Mongo's explain
        # output also lists ``rejectedPlans`` + ``allPlansExecution``
        # (candidate plans the query planner considered and
        # rejected), which naturally contain SORT stages from the
        # other IXSCANs that lost the race. Inspecting them would
        # give false-positive "SORT present" failures even when the
        # winning plan is a clean IXSCAN.
        winning = ((plan.get("queryPlanner") or {}).get("winningPlan")
                   or {})
        seen: list[str] = []

        def _walk(obj) -> None:
            if isinstance(obj, dict):
                stage = obj.get("stage")
                if isinstance(stage, str):
                    seen.append(stage)
                for k, v in obj.items():
                    # ``inputStage`` / ``inputStages`` are the only
                    # legitimate stage-continuation keys — the rest
                    # (bounds, transformBy, etc.) hold data, not
                    # further stages.
                    if k in ("inputStage", "inputStages"):
                        _walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    _walk(v)

        _walk(winning)

        assert "IXSCAN" in seen, (
            f"Expected IXSCAN in winning-plan stages; got {seen!r}. "
            f"WinningPlan: {winning!r}"
        )
        # The winning plan MUST use the v2 compound. Sanity-check the
        # index name so a future planner regression that picks a
        # different index (e.g. the haystack idx with an in-memory
        # sort) is caught.
        winning_index = None

        def _find_index(obj):
            nonlocal winning_index
            if isinstance(obj, dict):
                if obj.get("stage") == "IXSCAN":
                    winning_index = obj.get("indexName")
                    return
                for k, v in obj.items():
                    if k in ("inputStage", "inputStages"):
                        _find_index(v)
            elif isinstance(obj, list):
                for v in obj:
                    _find_index(v)

        _find_index(winning)
        assert winning_index == "perf_customers_v2_tenant_created", (
            f"Winning plan uses index {winning_index!r} instead of "
            f"the v2 compound. WinningPlan: {winning!r}"
        )
        # ``SORT`` is Mongo's in-memory sort stage. Its absence in
        # the winning plan means the compound index served the
        # ordering natively via a backward B-tree walk.
        assert "SORT" not in seen, (
            f"In-memory SORT stage present in winning plan; the v2 "
            f"compound is not serving the sort. Stages: {seen!r}. "
            f"WinningPlan: {winning!r}"
        )

    run_test(_go)
