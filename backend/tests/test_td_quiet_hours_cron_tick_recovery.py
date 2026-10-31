"""Feb-2026 · TD-quiet-hours-cron-tick-recovery · Phase 1 pytest.

Covers the 6 pytest cases locked in the operator dispatch:

  1. Dry-run on fixture with 3 stuck rows + 2 fresh rows →
     reports 3 stuck; writes nothing.
  2. Apply mode → 3 rows released; 2 fresh untouched; counts
     match dry-run.
  3. Second apply = all-zero (idempotent).
  4. Cross-tenant isolation: tenant A stuck rows not touched when
     running ``--tenant-id B``.
  5. Tenant-level fail-closed: if a row errors mid-apply for
     tenant A, tenant B still processes cleanly.
  6. Grace window honored: row stuck at ``now - 2min`` with
     ``--grace-minutes 5`` → not touched; same row with
     ``--grace-minutes 1`` → touched.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests._phase34_asyncio import batch_safe_run as _run


@pytest.fixture(scope="module")
def db():
    from config import db as _db  # noqa: PLC0415
    return _db


@pytest.fixture
def tid_a() -> str:
    return f"t-rsp-a-{uuid.uuid4().hex[:10]}"


@pytest.fixture
def tid_b() -> str:
    return f"t-rsp-b-{uuid.uuid4().hex[:10]}"


# ─── seed helpers ───────────────────────────────────────────────
def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _plant_row(
    db, *, tenant_id: str, scheduled_for: datetime,
    status: str = "pending", channel: str = "sms",
) -> str:
    rid = f"rsp-{uuid.uuid4().hex[:12]}"

    async def _go():
        await db.outbound_deferred.insert_one({
            "id": rid, "tenant_id": tenant_id,
            "channel": channel,
            "payload": {"to_phone": "+15555550123", "body": "x"}
                if channel == "sms"
                else {"to_email": "x@example.com",
                        "subject": "x", "html": "<p>x</p>"},
            "scheduled_for": _iso(scheduled_for),
            "created_at": _iso(datetime.now(timezone.utc)),
            "created_by": None,
            "released_at": None,
            "status": status,
        })
    _run(_go())
    return rid


def _cleanup(db, tenant_ids: list[str]) -> None:
    async def _go():
        for tid in tenant_ids:
            await db.outbound_deferred.delete_many({"tenant_id": tid})
            await db.migration_runs.delete_many({"tenant_id": tid})
    _run(_go())


def _db_row(db, rid: str):
    async def _go():
        return await db.outbound_deferred.find_one(
            {"id": rid}, {"_id": 0, "status": 1, "released_at": 1},
        )
    return _run(_go())


# ─── mock dispatch ──────────────────────────────────────────────
async def _ok_dispatch(_row: dict) -> dict:
    """Returns the shipped success shape without hitting any
    adapter.  Mirrors what ``_dispatch_row`` returns on a happy
    Resend / RingCentral send."""
    return {"status": "sent", "provider_id": "mock-prov-id"}


# ─── tests ──────────────────────────────────────────────────────

def test_01_dry_run_reports_stuck_without_mutating(db, tid_a):
    """1. Dry-run on fixture with 3 stuck + 2 fresh rows → reports
    3 stuck; writes nothing."""
    from migrations.recover_outbound_deferred_stuck_pending_v1 import (
        recover_stuck_pending,
    )

    now = datetime.now(timezone.utc)
    stuck = [
        _plant_row(db, tenant_id=tid_a,
                     scheduled_for=now - timedelta(minutes=30)),
        _plant_row(db, tenant_id=tid_a,
                     scheduled_for=now - timedelta(minutes=30)),
        _plant_row(db, tenant_id=tid_a,
                     scheduled_for=now - timedelta(minutes=30)),
    ]
    fresh = [
        _plant_row(db, tenant_id=tid_a,
                     scheduled_for=now + timedelta(hours=1)),
        _plant_row(db, tenant_id=tid_a,
                     scheduled_for=now + timedelta(hours=1)),
    ]
    try:
        result = _run(recover_stuck_pending(
            db, tenant_id=tid_a, dry_run=True,
            dispatch=_ok_dispatch, now=now,
        ))
        assert result["totals"]["stuck_pending_count"] == 3
        assert result["totals"]["released_count"] == 0
        # No row mutated.
        for rid in stuck + fresh:
            row = _db_row(db, rid)
            assert row["status"] == "pending", (
                f"dry-run must not mutate row {rid}"
            )
            assert row["released_at"] is None
        # No migration_runs doc written on dry-run.

        async def _audit_count():
            return await db.migration_runs.count_documents(
                {"tenant_id": tid_a,
                 "name":
                     "recover_outbound_deferred_stuck_pending_v1"},
            )
        assert _run(_audit_count()) == 0
    finally:
        _cleanup(db, [tid_a])


def test_02_apply_releases_stuck_leaves_fresh_untouched(db, tid_a):
    """2. Apply mode → 3 rows released; 2 fresh untouched; counts
    match dry-run."""
    from migrations.recover_outbound_deferred_stuck_pending_v1 import (
        recover_stuck_pending,
    )

    now = datetime.now(timezone.utc)
    stuck = [
        _plant_row(db, tenant_id=tid_a,
                     scheduled_for=now - timedelta(minutes=30)),
        _plant_row(db, tenant_id=tid_a,
                     scheduled_for=now - timedelta(minutes=30)),
        _plant_row(db, tenant_id=tid_a,
                     scheduled_for=now - timedelta(minutes=30)),
    ]
    fresh = [
        _plant_row(db, tenant_id=tid_a,
                     scheduled_for=now + timedelta(hours=1)),
        _plant_row(db, tenant_id=tid_a,
                     scheduled_for=now + timedelta(hours=1)),
    ]
    try:
        result = _run(recover_stuck_pending(
            db, tenant_id=tid_a, dry_run=False,
            dispatch=_ok_dispatch, now=now,
        ))
        totals = result["totals"]
        assert totals["stuck_pending_count"] == 3
        assert totals["released_count"] == 3
        assert totals["failed_count"] == 0
        for rid in stuck:
            row = _db_row(db, rid)
            assert row["status"] == "sent"
            assert row["released_at"] is not None
        for rid in fresh:
            row = _db_row(db, rid)
            assert row["status"] == "pending"
            assert row["released_at"] is None
    finally:
        _cleanup(db, [tid_a])


def test_03_second_apply_is_noop_idempotent(db, tid_a):
    """3. Second apply run = all-zero (idempotent)."""
    from migrations.recover_outbound_deferred_stuck_pending_v1 import (
        recover_stuck_pending,
    )

    now = datetime.now(timezone.utc)
    _plant_row(db, tenant_id=tid_a,
                 scheduled_for=now - timedelta(minutes=30))
    _plant_row(db, tenant_id=tid_a,
                 scheduled_for=now - timedelta(minutes=30))
    try:
        first = _run(recover_stuck_pending(
            db, tenant_id=tid_a, dry_run=False,
            dispatch=_ok_dispatch, now=now,
        ))
        assert first["totals"]["released_count"] == 2

        second = _run(recover_stuck_pending(
            db, tenant_id=tid_a, dry_run=False,
            dispatch=_ok_dispatch, now=now,
        ))
        t = second["totals"]
        assert t["stuck_pending_count"] == 0
        assert t["released_count"] == 0
        assert t["failed_count"] == 0
    finally:
        _cleanup(db, [tid_a])


def test_04_cross_tenant_isolation(db, tid_a, tid_b):
    """4. Cross-tenant isolation: tenant A rows not touched when
    running ``--tenant-id B``."""
    from migrations.recover_outbound_deferred_stuck_pending_v1 import (
        recover_stuck_pending,
    )

    now = datetime.now(timezone.utc)
    rid_a = _plant_row(db, tenant_id=tid_a,
                             scheduled_for=now - timedelta(minutes=30))
    rid_b = _plant_row(db, tenant_id=tid_b,
                             scheduled_for=now - timedelta(minutes=30))
    try:
        result = _run(recover_stuck_pending(
            db, tenant_id=tid_b, dry_run=False,
            dispatch=_ok_dispatch, now=now,
        ))
        assert result["totals"]["released_count"] == 1
        # Tenant A untouched.
        assert _db_row(db, rid_a)["status"] == "pending"
        # Tenant B released.
        assert _db_row(db, rid_b)["status"] == "sent"
    finally:
        _cleanup(db, [tid_a, tid_b])


def test_05_fail_closed_per_tenant_other_tenants_continue(
    db, tid_a, tid_b,
):
    """5. If a row errors mid-apply for tenant A, tenant B still
    processes cleanly."""
    from migrations.recover_outbound_deferred_stuck_pending_v1 import (
        recover_stuck_pending,
    )

    now = datetime.now(timezone.utc)
    rid_a_bad = _plant_row(
        db, tenant_id=tid_a,
        scheduled_for=now - timedelta(minutes=30),
    )
    rid_b_ok = _plant_row(
        db, tenant_id=tid_b,
        scheduled_for=now - timedelta(minutes=30),
    )

    async def _bad_dispatch(row):
        if row["tenant_id"] == tid_a:
            raise RuntimeError("simulated adapter crash")
        return {"status": "sent", "provider_id": "mock"}

    try:
        result = _run(recover_stuck_pending(
            db, all_tenants=False,
            # Multi-tenant run via a tiny ad-hoc orchestration:
            # we invoke twice with explicit tenant_ids to exercise
            # the fail-closed-per-tenant guarantee without
            # fingerprinting ``_list_tenants`` on the live DB.
            tenant_id=tid_a, dry_run=False,
            dispatch=_bad_dispatch, now=now,
        ))
        assert result["totals"]["tenants_with_errors"] == 1
        assert result["totals"]["failed_count"] == 1
        assert result["per_tenant"][tid_a]["error"] is not None
        # Tenant A row marked failed (not left in releasing).
        row_a = _db_row(db, rid_a_bad)
        assert row_a["status"] == "failed"

        # Tenant B run proceeds cleanly.
        result_b = _run(recover_stuck_pending(
            db, tenant_id=tid_b, dry_run=False,
            dispatch=_bad_dispatch, now=now,
        ))
        assert result_b["totals"]["released_count"] == 1
        assert result_b["totals"]["failed_count"] == 0
        assert _db_row(db, rid_b_ok)["status"] == "sent"
    finally:
        _cleanup(db, [tid_a, tid_b])


def test_06_grace_window_honored(db, tid_a):
    """6. Row stuck at ``now - 2min`` with ``--grace-minutes 5`` →
    not touched; same scenario with ``--grace-minutes 1`` →
    touched."""
    from migrations.recover_outbound_deferred_stuck_pending_v1 import (
        recover_stuck_pending,
    )

    now = datetime.now(timezone.utc)
    rid = _plant_row(db, tenant_id=tid_a,
                           scheduled_for=now - timedelta(minutes=2))
    try:
        result_5 = _run(recover_stuck_pending(
            db, tenant_id=tid_a, dry_run=False,
            grace_minutes=5,
            dispatch=_ok_dispatch, now=now,
        ))
        assert result_5["totals"]["stuck_pending_count"] == 0
        assert result_5["totals"]["released_count"] == 0
        assert _db_row(db, rid)["status"] == "pending"

        result_1 = _run(recover_stuck_pending(
            db, tenant_id=tid_a, dry_run=False,
            grace_minutes=1,
            dispatch=_ok_dispatch, now=now,
        ))
        assert result_1["totals"]["stuck_pending_count"] == 1
        assert result_1["totals"]["released_count"] == 1
        assert _db_row(db, rid)["status"] == "sent"
    finally:
        _cleanup(db, [tid_a])


# ─── bonus · bookmark surfacing + audit row shape ───────────────

def test_07_orphaned_releasing_count_surfaced_in_totals(db, tid_a):
    """Bookmark for TD-quiet-hours-releasing-orphan-recovery:
    ``releasing`` rows with stale ``scheduled_for`` are counted and
    surfaced in totals but NEVER mutated by this script."""
    from migrations.recover_outbound_deferred_stuck_pending_v1 import (
        recover_stuck_pending,
    )

    now = datetime.now(timezone.utc)
    rid_pending = _plant_row(
        db, tenant_id=tid_a,
        scheduled_for=now - timedelta(minutes=30),
    )
    rid_releasing = _plant_row(
        db, tenant_id=tid_a,
        scheduled_for=now - timedelta(minutes=30),
        status="releasing",
    )
    try:
        result = _run(recover_stuck_pending(
            db, tenant_id=tid_a, dry_run=False,
            dispatch=_ok_dispatch, now=now,
        ))
        t = result["totals"]
        assert t["stuck_pending_count"] == 1
        assert t["orphaned_releasing_count"] == 1
        assert t["released_count"] == 1
        # Pending row released; releasing row LEFT ALONE.
        assert _db_row(db, rid_pending)["status"] == "sent"
        assert _db_row(db, rid_releasing)["status"] == "releasing"
    finally:
        _cleanup(db, [tid_a])


def test_08_apply_writes_migration_runs_audit_doc(db, tid_a):
    """Audit convention mirrors ``merge_income_categories_
    duplicates_v1`` — one ``migration_runs`` doc per tenant per
    apply invocation."""
    from migrations.recover_outbound_deferred_stuck_pending_v1 import (
        recover_stuck_pending,
    )

    now = datetime.now(timezone.utc)
    _plant_row(db, tenant_id=tid_a,
                 scheduled_for=now - timedelta(minutes=30))
    try:
        _run(recover_stuck_pending(
            db, tenant_id=tid_a, dry_run=False,
            dispatch=_ok_dispatch, now=now,
        ))

        async def _get_audit():
            return await db.migration_runs.find_one(
                {"tenant_id": tid_a,
                 "name":
                     "recover_outbound_deferred_stuck_pending_v1"},
                {"_id": 0},
            )
        doc = _run(_get_audit())
        assert doc is not None
        assert doc["status"] == "ok"
        assert doc["grace_minutes"] == 5
        assert doc["summary"]["released_count"] == 1
        assert doc["summary"]["stuck_pending_count"] == 1
        # ``per_row`` purposely excluded from the audit summary so
        # the doc stays small on large recoveries.
        assert "per_row" not in doc["summary"]
    finally:
        _cleanup(db, [tid_a])
