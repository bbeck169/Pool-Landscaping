"""Feb-2026 · P8 — Characterization tests for ``dedupe_ai_employees``.

Pins the CURRENT observable contract of
``migrations.task_jj_dedupe_ai_employees.dedupe_ai_employees`` before
the behavior-preserving refactor. Every assertion targets a behavior
that MUST NOT drift across the refactor.

Observable contract (paraphrased from the code at
``migrations/task_jj_dedupe_ai_employees.py:53``):

* Phase 1 — drops every ``ai_employees`` row with ``tenant_id: None``,
  best-effort repointing any conversation/message/action refs.
* Phase 2 — within each tenant, groups by ``key``; per group with
  count>1, the survivor has the MOST non-null fields
  (``sum(v not in (None, "", [], {}))``); tiebreak = ``updated_at``
  ASCENDING (earliest updated_at wins).  The docstring says "DESC" but
  the code sorts ascending on the tuple — pinned here as-is.
* Phase 3 — inserts a single row into ``migration_log`` **iff** any
  merge/drop happened.  No mutations → no ``migration_log`` write.
* Phase 4 — best-effort ``create_index`` for
  ``phase34_task_jj_tenant_key_uniq`` on ``(tenant_id, key)`` unique
  with the partialFilter ``{tenant_id: string, key: string}``.
* Return value: ``{before, after, null_tenant_dropped,
  in_tenant_dupes_merged, conversation_refs_migrated}``.
* Cross-tenant isolation: dupes in tenant A never affect tenant B.

Non-goals of this suite (documented for the refactor reader):

* NO fuzzy matching in current impl — grouping is exact on
  ``(tenant_id, key)``. Fuzzy-threshold characterization SKIPPED.
* NO ``deleted_at`` / soft-delete concept on ``ai_employees``. All
  rows with matching keys are considered dedupe candidates. Skip
  test SKIPPED with note.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from datetime import datetime, timezone

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._phase34_asyncio import batch_safe_run as _run

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]

_TENANT_A = f"p8-tenant-a-{uuid.uuid4().hex[:6]}"
_TENANT_B = f"p8-tenant-b-{uuid.uuid4().hex[:6]}"


# ── Fixture helpers ───────────────────────────────────────────────
def _mk_employee(*, tenant_id, key, extras=None, updated_at=None):
    """Insert a fresh ai_employees row. Returns the row's ``id``."""
    rid = f"p8-emp-{uuid.uuid4().hex[:8]}"
    body = {
        "id": rid, "tenant_id": tenant_id, "key": key,
        "slug": f"slug-{rid[:4]}", "name": f"Name-{rid[:4]}",
        "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
    }
    if extras:
        body.update(extras)
    _sync.ai_employees.insert_one(body)
    return rid


@pytest.fixture(autouse=True)
def _isolate_test_data():
    """Purge any P8-scoped fixtures + tenant-scoped migration_log
    entries before & after each test. Never touches the production
    aquaterra rows — every fixture id is prefixed ``p8-``.

    Also drops the ``phase34_task_jj_tenant_key_uniq`` compound index
    at test setup so we can seed duplicates. ``dedupe_ai_employees``
    itself re-creates the index in Phase 4, so post-test the index is
    restored automatically.
    """
    def _purge():
        _sync.ai_employees.delete_many({"id": {"$regex": "^p8-"}})
        _sync.ai_employees.delete_many(
            {"tenant_id": {"$in": [_TENANT_A, _TENANT_B]}})
        _sync.ai_employee_conversations.delete_many(
            {"employee_id": {"$regex": "^p8-"}})
        _sync.ai_employee_messages.delete_many(
            {"employee_id": {"$regex": "^p8-"}})
        _sync.ai_employee_actions.delete_many(
            {"employee_id": {"$regex": "^p8-"}})
    _purge()
    # Drop the unique index — Phase 4 of dedupe reinstalls it.
    try:
        _sync.ai_employees.drop_index("phase34_task_jj_tenant_key_uniq")
    except Exception:  # noqa: BLE001 — index may not exist yet
        pass
    yield
    _purge()


def _invoke():
    """Sync entrypoint into the async ``dedupe_ai_employees``."""
    from migrations.task_jj_dedupe_ai_employees import dedupe_ai_employees
    return _run(dedupe_ai_employees())


# ── 1. No-op path: clean state → zero counters, no migration_log ─
def test_no_op_when_no_null_tenant_and_no_dupes():
    """With zero p8-scoped fixtures and no null-tenant rows, the run
    reports zero mutations and does NOT write to migration_log."""
    # The current db may still contain the seed aquaterra rows — those
    # are legitimate and pinned via the aquaterra idempotency test in
    # ``test_phase34_task_jj_kk_ee_digest.py``. Our contract here is:
    # our fixtures don't cause work.
    ml_before = _sync.migration_log.count_documents({})
    r = _invoke()
    # Second run (idempotent baseline) — should be a full no-op for
    # OUR data set.
    r2 = _invoke()
    assert r2["null_tenant_dropped"] == 0
    assert r2["in_tenant_dupes_merged"] == 0
    assert r2["before"] == r2["after"]
    # No new migration_log rows are inserted by the second run because
    # ``merge_log`` was empty.
    ml_after = _sync.migration_log.count_documents({})
    assert ml_after == ml_before + (1 if (
        r["null_tenant_dropped"] > 0 or r["in_tenant_dupes_merged"] > 0
    ) else 0), (
        "migration_log must only be written when work actually happens"
    )


# ── 2. Null-tenant rows are dropped + logged with kind marker ────
def test_null_tenant_rows_are_dropped_and_logged():
    a = _mk_employee(tenant_id=None, key="p8-null-1")
    b = _mk_employee(tenant_id=None, key="p8-null-2")
    r = _invoke()
    # Both fixture rows dropped.
    assert _sync.ai_employees.find_one({"id": a}) is None
    assert _sync.ai_employees.find_one({"id": b}) is None
    assert r["null_tenant_dropped"] >= 2, r
    # Migration log carries entries with the ``null_tenant_legacy`` kind.
    ml = _sync.migration_log.find_one(
        {"task": "task-jj-ai-employees-dedupe",
         "sample.dropped_id": {"$in": [a, b]}},
        sort=[("_id", -1)],
    )
    assert ml is not None
    kinds = {s.get("kind") for s in (ml.get("sample") or [])
              if s.get("dropped_id") in (a, b)}
    assert kinds == {"null_tenant_legacy"}


# ── 3. Within-tenant duplicate: survivor = most-populated row ────
def test_in_tenant_dupe_keeps_most_populated_row():
    key = f"p8-dup-{uuid.uuid4().hex[:6]}"
    winner = _mk_employee(
        tenant_id=_TENANT_A, key=key,
        extras={"description": "richer", "avatar_url": "u", "tone": "friendly"},
        updated_at="2026-01-01T00:00:00+00:00",
    )
    loser = _mk_employee(
        tenant_id=_TENANT_A, key=key,
        extras={"description": None},
        updated_at="2026-01-02T00:00:00+00:00",
    )
    r = _invoke()
    assert _sync.ai_employees.find_one({"id": winner}) is not None, \
        "row with more non-null fields must survive"
    assert _sync.ai_employees.find_one({"id": loser}) is None, \
        "sparser row must be dropped"
    assert r["in_tenant_dupes_merged"] >= 1


# ── 4. Tie on field-count → OLDEST updated_at wins (docstring drift) ──
def test_tiebreak_prefers_oldest_updated_at_on_equal_field_count():
    """The docstring says ``updated_at DESC`` but the code sorts by
    ``(-field_count, updated_at)`` ascending, so the OLDEST
    ``updated_at`` ends up at ``full[0]`` and survives. Pinned as-is.
    Flagged in the P8 report as a pre-existing docstring drift — NOT
    fixed by this refactor.
    """
    key = f"p8-tie-{uuid.uuid4().hex[:6]}"
    older = _mk_employee(
        tenant_id=_TENANT_A, key=key,
        extras={"description": "same fill"},
        updated_at="2026-01-01T00:00:00+00:00",
    )
    newer = _mk_employee(
        tenant_id=_TENANT_A, key=key,
        extras={"description": "same fill"},
        updated_at="2026-06-01T00:00:00+00:00",
    )
    _invoke()
    assert _sync.ai_employees.find_one({"id": older}) is not None, \
        "OLDEST updated_at must survive per current sort key ordering"
    assert _sync.ai_employees.find_one({"id": newer}) is None


# ── 5. Conversation refs are repointed BEFORE the loser is deleted ──
def test_conversation_refs_are_repointed_to_survivor():
    key = f"p8-refs-{uuid.uuid4().hex[:6]}"
    winner = _mk_employee(
        tenant_id=_TENANT_A, key=key,
        extras={"description": "rich", "avatar_url": "u"},
    )
    loser = _mk_employee(tenant_id=_TENANT_A, key=key)
    # Plant a conversation + a message + an action referring to loser.
    _sync.ai_employee_conversations.insert_one({
        "id": f"p8-conv-{uuid.uuid4().hex[:6]}", "employee_id": loser})
    _sync.ai_employee_messages.insert_one({
        "id": f"p8-msg-{uuid.uuid4().hex[:6]}", "employee_id": loser})
    _sync.ai_employee_actions.insert_one({
        "id": f"p8-act-{uuid.uuid4().hex[:6]}", "employee_id": loser})
    r = _invoke()
    assert _sync.ai_employees.find_one({"id": loser}) is None
    for coll in ("ai_employee_conversations", "ai_employee_messages",
                  "ai_employee_actions"):
        assert _sync[coll].count_documents({"employee_id": loser}) == 0
        assert _sync[coll].count_documents({"employee_id": winner}) >= 1
    assert r["conversation_refs_migrated"] >= 3


# ── 6. Cross-tenant isolation: tenant B untouched by A's dupe ────
def test_cross_tenant_isolation():
    key = f"p8-iso-{uuid.uuid4().hex[:6]}"
    a1 = _mk_employee(tenant_id=_TENANT_A, key=key)
    a2 = _mk_employee(tenant_id=_TENANT_A, key=key,
                        extras={"description": "richer"})
    b_only = _mk_employee(tenant_id=_TENANT_B, key=key,
                            extras={"description": "solo"})
    _invoke()
    # Tenant A collapsed to one row for this key.
    assert _sync.ai_employees.count_documents(
        {"tenant_id": _TENANT_A, "key": key}) == 1
    # Tenant B untouched.
    assert _sync.ai_employees.find_one({"id": b_only}) is not None
    assert _sync.ai_employees.count_documents(
        {"tenant_id": _TENANT_B, "key": key}) == 1


# ── 7. Idempotent — second run reports zero work ─────────────────
def test_second_run_is_a_no_op():
    key = f"p8-idem-{uuid.uuid4().hex[:6]}"
    _mk_employee(tenant_id=_TENANT_A, key=key)
    _mk_employee(tenant_id=_TENANT_A, key=key)
    _mk_employee(tenant_id=None, key="p8-idem-null")
    first = _invoke()
    second = _invoke()
    assert first["null_tenant_dropped"] >= 1
    assert first["in_tenant_dupes_merged"] >= 1
    assert second["null_tenant_dropped"] == 0
    assert second["in_tenant_dupes_merged"] == 0
    assert second["before"] == second["after"]
    assert second["conversation_refs_migrated"] == 0


# ── 8. Unique compound index is installed under the pinned name ──
def test_unique_compound_index_is_installed():
    _invoke()
    names = [ix.get("name") for ix in _sync.ai_employees.list_indexes()]
    assert "phase34_task_jj_tenant_key_uniq" in names


# ── 9. Migration log is written only when work happens ───────────
def test_migration_log_written_only_when_work_happens():
    ml_before = _sync.migration_log.count_documents(
        {"task": "task-jj-ai-employees-dedupe"})
    # No-op run (our fixtures purged, aquaterra already deduped).
    _invoke()
    ml_after_noop = _sync.migration_log.count_documents(
        {"task": "task-jj-ai-employees-dedupe"})
    # Zero new rows because ``merge_log`` was empty.
    assert ml_after_noop == ml_before, (
        "no-op run must not write to migration_log"
    )
    # Now plant a null-tenant fixture and re-run — one row should land.
    _mk_employee(tenant_id=None, key="p8-mig-log")
    _invoke()
    ml_after_work = _sync.migration_log.count_documents(
        {"task": "task-jj-ai-employees-dedupe"})
    assert ml_after_work == ml_after_noop + 1
