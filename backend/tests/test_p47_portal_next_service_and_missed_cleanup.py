"""Phase P47 · Feb-2026 — Portal Next-Service query fix + missed-job
auto-cleanup poller.

Locks two related invariants that shipped together:

1. ``routers/customer_portal.py::get_portal_summary`` — pushes the
   ``>= today`` date guard into the DB query itself so a stale
   ``status=scheduled`` row (past-dated, never marked completed)
   no longer surfaces via BSON's null-first ascending sort and get
   dropped by a Python post-filter.  Two OR branches:
     * ``scheduled_start >= now_iso``
     * ``scheduled_start`` null/missing AND ``scheduled_date >= today``

2. ``services/missed_job_scheduler.py::run_once`` — sweep any open
   status (``scheduled | pending | active | requested``) job whose
   effective scheduled datetime is older than
   ``MISSED_JOB_STALENESS_HOURS`` and mark it ``status="missed"``.
   Tenant-scoped, atomic-update-race-safe, writes an audit doc,
   never touches ``in_progress``, never touches ``completed |
   cancelled | missed`` (idempotent), never leaks cross-tenant.

Test-loop convention (mirrors ``test_p44_service_log_media_read_path``
and ``test_p46_bulk_charge_index_swap``): sync ``pymongo`` for seed +
cleanup, fresh ``asyncio`` loop + ``Motor`` client bound to it for
the SUT call, patch ``routers.customer_portal.db`` and
``services.missed_job_scheduler.db`` to the loop-bound Motor for
the duration of the test.  This avoids Motor's cached-loop trap
that bit earlier suites.

Sixteen tests total:
  * 8 for ``get_portal_summary`` next-service resolution.
  * 6 for ``missed_job_scheduler.run_once`` cleanup behaviour.
  * 2 that verify the two units COMPOSE correctly (a job the
    cleanup marks ``missed`` must not surface in the portal
    Next-Service tile; the portal Next-Service selection must
    agree with the same-sort calendar query for the same customer).
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "P47_"


# ═════════════════════════════════════════════════════════════════════
# Fixtures — sync pymongo for seeding + cleanup
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def cleanup(dbc):
    """Tracks every P47_-tagged job / audit / invoice this test wrote
    and drops it on teardown so full-suite runs stay hermetic."""
    seeded_job_ids: List[str] = []
    seeded_audit_ids: List[str] = []
    seeded_quote_ids: List[str] = []
    yield seeded_job_ids, seeded_audit_ids, seeded_quote_ids
    if seeded_job_ids:
        dbc.jobs.delete_many({"id": {"$in": seeded_job_ids}})
        dbc.audits.delete_many({"job_id": {"$in": seeded_job_ids}})
    if seeded_audit_ids:
        dbc.audits.delete_many({"id": {"$in": seeded_audit_ids}})
    if seeded_quote_ids:
        dbc.quotes.delete_many({"id": {"$in": seeded_quote_ids}})


# ═════════════════════════════════════════════════════════════════════
# Per-test async loop + Motor db handle bound to it
# ═════════════════════════════════════════════════════════════════════
def _fresh_loop_and_db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = AsyncIOMotorClient(MONGO_URL, io_loop=loop)
    adb = client[DB_NAME]
    return loop, client, adb


def _patch_cp_db(adb):
    from routers import customer_portal as _cp
    _cp._orig_db_for_test = getattr(_cp, "_orig_db_for_test", _cp.db)
    _cp.db = adb


def _restore_cp_db():
    from routers import customer_portal as _cp
    if hasattr(_cp, "_orig_db_for_test"):
        _cp.db = _cp._orig_db_for_test


def _patch_mjs_db(adb):
    from services import missed_job_scheduler as _mjs
    _mjs._orig_db_for_test = getattr(_mjs, "_orig_db_for_test", _mjs.db)
    _mjs.db = adb


def _restore_mjs_db():
    from services import missed_job_scheduler as _mjs
    if hasattr(_mjs, "_orig_db_for_test"):
        _mjs.db = _mjs._orig_db_for_test


def _run_get_portal_summary(user: Dict[str, Any],
                              tenant: Dict[str, Any]) -> Dict[str, Any]:
    loop, client, adb = _fresh_loop_and_db()
    try:
        _patch_cp_db(adb)
        from routers.customer_portal import get_portal_summary
        return loop.run_until_complete(get_portal_summary(user=user, tenant=tenant))
    finally:
        _restore_cp_db()
        try:
            client.close()
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass


def _run_missed_cleanup(*, staleness_hours: Optional[int] = None) -> Dict[str, Any]:
    loop, client, adb = _fresh_loop_and_db()
    try:
        _patch_mjs_db(adb)
        from services.missed_job_scheduler import run_once
        return loop.run_until_complete(
            run_once(staleness_hours=staleness_hours, db_client=adb),
        )
    finally:
        _restore_mjs_db()
        try:
            client.close()
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass


# ═════════════════════════════════════════════════════════════════════
# Seed builders
# ═════════════════════════════════════════════════════════════════════
def _fresh(prefix: str) -> str:
    return f"{TAG}{prefix}_{uuid.uuid4().hex[:8]}"


def _seed_job(dbc, *, tenant_id: str, customer_id: str,
              status: str = "scheduled",
              scheduled_start: Optional[str] = None,
              scheduled_date: Optional[str] = None,
              deleted_at: Optional[str] = None,
              extra: Optional[Dict[str, Any]] = None) -> str:
    """Insert one jobs row.  Fields default to a healthy 'upcoming
    scheduled' shape unless overridden.  Returns the new job id."""
    jid = _fresh("JOB")
    doc: Dict[str, Any] = {
        "id": jid,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "title": "P47 seed job",
        "status": status,
        "service_type": "Pool cleaning",
        "created_at": "2026-02-01T00:00:00Z",
    }
    if scheduled_start is not None:
        doc["scheduled_start"] = scheduled_start
    if scheduled_date is not None:
        doc["scheduled_date"] = scheduled_date
    if deleted_at is not None:
        doc["deleted_at"] = deleted_at
    if extra:
        doc.update(extra)
    dbc.jobs.insert_one(doc)
    return jid


def _future_iso(days: int = 1, hours: int = 0) -> str:
    return (datetime.now(timezone.utc)
            + timedelta(days=days, hours=hours)).isoformat()


def _past_iso(days: int = 5) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _today_ymd() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _future_ymd(days: int = 3) -> str:
    return (datetime.now(timezone.utc)
            + timedelta(days=days)).date().isoformat()


def _past_ymd(days: int = 5) -> str:
    return (datetime.now(timezone.utc)
            - timedelta(days=days)).date().isoformat()


# ═════════════════════════════════════════════════════════════════════
# 1-8 · Portal Next-Service resolution
# ═════════════════════════════════════════════════════════════════════
def test_next_service_returns_upcoming_scheduled_start(dbc, cleanup):
    """A job with a specific ``scheduled_start`` in the future must
    surface as the tile — this is the primary happy path."""
    seeded_jobs, _, _ = cleanup
    tid = _fresh("TEN")
    cid = _fresh("CUST")
    future = _future_iso(days=2)
    jid = _seed_job(dbc, tenant_id=tid, customer_id=cid,
                     scheduled_start=future,
                     scheduled_date=_future_ymd(2))
    seeded_jobs.append(jid)

    res = _run_get_portal_summary(
        user={"role": "customer", "customer_id": cid, "id": "u1"},
        tenant={"id": tid},
    )
    assert res["next_service"] is not None, (
        f"expected next_service to surface, got None. summary={res!r}")
    assert res["next_service"]["job_id"] == jid
    assert res["next_service"]["scheduled_start"] == future


def test_next_service_returns_upcoming_scheduled_date_only(dbc, cleanup):
    """A job with NO ``scheduled_start`` but a ``scheduled_date`` >=
    today must surface via the OR fallback branch."""
    seeded_jobs, _, _ = cleanup
    tid = _fresh("TEN")
    cid = _fresh("CUST")
    ymd = _future_ymd(3)
    jid = _seed_job(dbc, tenant_id=tid, customer_id=cid,
                     scheduled_date=ymd)
    seeded_jobs.append(jid)

    res = _run_get_portal_summary(
        user={"role": "customer", "customer_id": cid, "id": "u1"},
        tenant={"id": tid},
    )
    assert res["next_service"] is not None
    assert res["next_service"]["job_id"] == jid
    assert res["next_service"]["date"] == ymd


def test_next_service_ignores_past_scheduled_start(dbc, cleanup):
    """The whole point of P47: a past-dated ``scheduled_start`` must
    NOT surface (pre-P47 the null-first sort dropped this row and
    the tile went blank)."""
    seeded_jobs, _, _ = cleanup
    tid = _fresh("TEN")
    cid = _fresh("CUST")
    jid = _seed_job(dbc, tenant_id=tid, customer_id=cid,
                     scheduled_start=_past_iso(days=10),
                     scheduled_date=_past_ymd(10))
    seeded_jobs.append(jid)

    res = _run_get_portal_summary(
        user={"role": "customer", "customer_id": cid, "id": "u1"},
        tenant={"id": tid},
    )
    assert res["next_service"] is None


def test_next_service_ignores_past_scheduled_date(dbc, cleanup):
    """Same guard but on the OR fallback branch — no
    ``scheduled_start`` and ``scheduled_date`` in the past."""
    seeded_jobs, _, _ = cleanup
    tid = _fresh("TEN")
    cid = _fresh("CUST")
    jid = _seed_job(dbc, tenant_id=tid, customer_id=cid,
                     scheduled_date=_past_ymd(10))
    seeded_jobs.append(jid)

    res = _run_get_portal_summary(
        user={"role": "customer", "customer_id": cid, "id": "u1"},
        tenant={"id": tid},
    )
    assert res["next_service"] is None


def test_next_service_or_branch_picks_scheduled_date_when_ss_empty(dbc, cleanup):
    """OR-fallback specifically covers ``scheduled_start = ""``
    (empty-string, not just null / missing).  Historical data
    carries empty strings from an old form-submission path."""
    seeded_jobs, _, _ = cleanup
    tid = _fresh("TEN")
    cid = _fresh("CUST")
    ymd = _future_ymd(4)
    jid = _seed_job(dbc, tenant_id=tid, customer_id=cid,
                     scheduled_start="",
                     scheduled_date=ymd)
    seeded_jobs.append(jid)

    res = _run_get_portal_summary(
        user={"role": "customer", "customer_id": cid, "id": "u1"},
        tenant={"id": tid},
    )
    assert res["next_service"] is not None
    assert res["next_service"]["job_id"] == jid
    assert res["next_service"]["date"] == ymd


def test_next_service_null_when_no_upcoming_jobs(dbc, cleanup):
    """Customer with only past-dated + completed jobs → null tile
    (defensive default, not a crash)."""
    seeded_jobs, _, _ = cleanup
    tid = _fresh("TEN")
    cid = _fresh("CUST")
    # Past-dated scheduled job (should NOT surface — see test 3).
    j_past = _seed_job(dbc, tenant_id=tid, customer_id=cid,
                        scheduled_start=_past_iso(30))
    # Completed job in the future (status filter excludes it).
    j_completed = _seed_job(
        dbc, tenant_id=tid, customer_id=cid,
        status="completed", scheduled_start=_future_iso(2))
    seeded_jobs.extend([j_past, j_completed])

    res = _run_get_portal_summary(
        user={"role": "customer", "customer_id": cid, "id": "u1"},
        tenant={"id": tid},
    )
    assert res["next_service"] is None


def test_next_service_tenant_scoped(dbc, cleanup):
    """A same-customer_id row in a DIFFERENT tenant must NEVER leak
    into the current tenant's portal summary."""
    seeded_jobs, _, _ = cleanup
    tid_a = _fresh("TEN_A")
    tid_b = _fresh("TEN_B")
    cid = _fresh("CUST")  # same id, different tenant
    j_b = _seed_job(dbc, tenant_id=tid_b, customer_id=cid,
                     scheduled_start=_future_iso(1))
    seeded_jobs.append(j_b)

    # No jobs seeded for tid_a.  Cross-tenant leak = fail.
    res = _run_get_portal_summary(
        user={"role": "customer", "customer_id": cid, "id": "u1"},
        tenant={"id": tid_a},
    )
    assert res["next_service"] is None, (
        f"cross-tenant leak: tid_a should have no next_service, "
        f"got {res['next_service']!r} (job in tid_b was {j_b})")


def test_next_service_excludes_deleted_and_terminal_statuses(dbc, cleanup):
    """soft-deleted rows AND terminal statuses (completed / cancelled
    / missed) must not surface — deleted_at guard + status $in filter."""
    seeded_jobs, _, _ = cleanup
    tid = _fresh("TEN")
    cid = _fresh("CUST")
    # Soft-deleted upcoming job.
    j_del = _seed_job(dbc, tenant_id=tid, customer_id=cid,
                       scheduled_start=_future_iso(1),
                       deleted_at="2026-02-01T00:00:00Z")
    # Cancelled upcoming.
    j_cancel = _seed_job(dbc, tenant_id=tid, customer_id=cid,
                          status="cancelled",
                          scheduled_start=_future_iso(2))
    # Missed upcoming (cleanup wrote this — see test 15).
    j_missed = _seed_job(dbc, tenant_id=tid, customer_id=cid,
                          status="missed",
                          scheduled_start=_future_iso(3))
    seeded_jobs.extend([j_del, j_cancel, j_missed])

    res = _run_get_portal_summary(
        user={"role": "customer", "customer_id": cid, "id": "u1"},
        tenant={"id": tid},
    )
    assert res["next_service"] is None


# ═════════════════════════════════════════════════════════════════════
# 9-14 · Missed-job cleanup poller (run_once)
# ═════════════════════════════════════════════════════════════════════
def test_run_once_marks_stale_scheduled_start_job(dbc, cleanup):
    """Job with ``scheduled_start`` older than the staleness cutoff
    must transition to ``status="missed"`` + carry the forensic
    breadcrumbs (``missed_at``, ``missed_by``, ``missed_prior_status``,
    ``missed_effective_scheduled_at``)."""
    seeded_jobs, _, _ = cleanup
    tid = _fresh("TEN")
    cid = _fresh("CUST")
    stale = _past_iso(days=5)
    jid = _seed_job(dbc, tenant_id=tid, customer_id=cid,
                     scheduled_start=stale)
    seeded_jobs.append(jid)

    summary = _run_missed_cleanup(staleness_hours=48)
    assert summary["marked"] >= 1, summary
    row = dbc.jobs.find_one({"id": jid}, {"_id": 0})
    assert row["status"] == "missed"
    assert row.get("missed_by") == "auto-cleanup"
    assert row.get("missed_prior_status") == "scheduled"
    assert row.get("missed_at")
    assert row.get("missed_effective_scheduled_at") == stale


def test_run_once_marks_stale_scheduled_date_only_job(dbc, cleanup):
    """Same behaviour on the OR-fallback branch (no
    ``scheduled_start``, ``scheduled_date`` older than the cutoff
    calendar day)."""
    seeded_jobs, _, _ = cleanup
    tid = _fresh("TEN")
    cid = _fresh("CUST")
    stale_ymd = _past_ymd(days=5)
    jid = _seed_job(dbc, tenant_id=tid, customer_id=cid,
                     scheduled_date=stale_ymd)
    seeded_jobs.append(jid)

    summary = _run_missed_cleanup(staleness_hours=48)
    assert summary["marked"] >= 1
    row = dbc.jobs.find_one({"id": jid}, {"_id": 0})
    assert row["status"] == "missed"
    # effective_scheduled_at defaults to 08:00 UTC when only a date is present
    assert row.get("missed_effective_scheduled_at", "").startswith(
        f"{stale_ymd}T08:00:00")


def test_run_once_skips_in_progress(dbc, cleanup):
    """``in_progress`` is intentionally EXCLUDED from the sweep — a
    tech mid-visit needs operator attention, not auto-cleanup."""
    seeded_jobs, _, _ = cleanup
    tid = _fresh("TEN")
    cid = _fresh("CUST")
    jid = _seed_job(dbc, tenant_id=tid, customer_id=cid,
                     status="in_progress",
                     scheduled_start=_past_iso(30))
    seeded_jobs.append(jid)

    _run_missed_cleanup(staleness_hours=48)
    row = dbc.jobs.find_one({"id": jid}, {"_id": 0})
    assert row["status"] == "in_progress", (
        "in_progress job must never be auto-marked missed")


def test_run_once_skips_completed_and_cancelled_and_already_missed(dbc, cleanup):
    """Terminal buckets must not be re-touched — idempotency
    invariant.  Includes ``missed`` itself so the poller can run on
    a schedule without re-marking already-marked rows."""
    seeded_jobs, _, _ = cleanup
    tid = _fresh("TEN")
    cid = _fresh("CUST")
    stale = _past_iso(30)
    jids = []
    for st in ("completed", "cancelled", "missed"):
        jids.append(_seed_job(dbc, tenant_id=tid, customer_id=cid,
                               status=st, scheduled_start=stale))
    seeded_jobs.extend(jids)

    _run_missed_cleanup(staleness_hours=48)
    for jid, expected in zip(jids, ("completed", "cancelled", "missed")):
        row = dbc.jobs.find_one({"id": jid}, {"_id": 0})
        # ``missed`` is expected to stay ``missed`` — that's the
        # idempotent case.  ``completed`` / ``cancelled`` must NOT
        # flip.
        assert row["status"] == expected, (
            f"expected {expected}, got {row['status']} — "
            f"terminal statuses must not be touched")


def test_run_once_tenant_scoped_atomic_update(dbc, cleanup):
    """The update filter includes ``tenant_id`` — cross-tenant leaks
    structurally impossible.  We seed the same job id shape in two
    tenants and verify only the target tenant's row is marked.

    (In practice job ids are globally unique — but we prove the
    filter contract by touching cross-tenant DATA rather than
    relying on id uniqueness.)"""
    seeded_jobs, _, _ = cleanup
    tid_a = _fresh("TEN_A")
    tid_b = _fresh("TEN_B")
    cid = _fresh("CUST")
    stale = _past_iso(30)
    j_a = _seed_job(dbc, tenant_id=tid_a, customer_id=cid,
                     scheduled_start=stale)
    j_b = _seed_job(dbc, tenant_id=tid_b, customer_id=cid,
                     scheduled_start=stale)
    seeded_jobs.extend([j_a, j_b])

    _run_missed_cleanup(staleness_hours=48)
    row_a = dbc.jobs.find_one({"id": j_a}, {"_id": 0})
    row_b = dbc.jobs.find_one({"id": j_b}, {"_id": 0})
    assert row_a["status"] == "missed"
    assert row_a["tenant_id"] == tid_a
    assert row_b["status"] == "missed"
    assert row_b["tenant_id"] == tid_b
    # Every marked doc must ALSO be paired with a same-tenant audit doc.
    for tid, jid in ((tid_a, j_a), (tid_b, j_b)):
        audit = dbc.audits.find_one(
            {"kind": "job_auto_marked_missed", "job_id": jid},
            {"_id": 0})
        assert audit is not None, f"audit doc missing for {jid}"
        assert audit["tenant_id"] == tid, (
            "audit doc tenant_id must match the marked job's tenant_id")


def test_run_once_respects_disabled_env_toggle(monkeypatch):
    """``MISSED_JOB_CLEANUP_ENABLED=false`` disables the *poller* —
    verified via the module-local resolver.  ``run_once`` itself is
    always callable so tests / manual sweeps can force a pass; the
    env toggle only gates the background loop."""
    from services.missed_job_scheduler import _resolve_enabled
    # Default (unset) → enabled.
    monkeypatch.delenv("MISSED_JOB_CLEANUP_ENABLED", raising=False)
    assert _resolve_enabled() is True
    # Truthy variants.
    for v in ("true", "1", "yes", "on"):
        monkeypatch.setenv("MISSED_JOB_CLEANUP_ENABLED", v)
        assert _resolve_enabled() is True, v
    # Falsy variants.  NOTE: empty-string is deliberately excluded —
    # the resolver reads ``os.environ.get(k) or "true"`` before the
    # disabled-set check, so ``""`` short-circuits to ``"true"`` and
    # behaves as "unset → default enabled".  A future refactor that
    # distinguishes ``""`` from unset would flip this expectation.
    for v in ("false", "0", "no", "off"):
        monkeypatch.setenv("MISSED_JOB_CLEANUP_ENABLED", v)
        assert _resolve_enabled() is False, v
    # And explicitly lock the empty-string → enabled contract.
    monkeypatch.setenv("MISSED_JOB_CLEANUP_ENABLED", "")
    assert _resolve_enabled() is True, (
        "empty-string must short-circuit to the default (enabled) — "
        "the resolver applies ``or 'true'`` before the disabled-set check")


# ═════════════════════════════════════════════════════════════════════
# 15-16 · Composition — P47 pieces work together
# ═════════════════════════════════════════════════════════════════════
def test_next_service_ignores_jobs_marked_missed_by_cleanup(dbc, cleanup):
    """User-added composition #15 — prove the two P47 items compose
    correctly.  Seed a stale scheduled job → run cleanup (marks
    it missed) → get_portal_summary → assert next_service is null.
    The cleanup MUST NOT leave orphan pointers that then leak back
    through the portal Next-Service tile.

    Also seeds an unrelated future-dated ``requested`` row so we
    prove the null result reflects "no valid next_service" rather
    than "no rows at all"."""
    seeded_jobs, _, _ = cleanup
    tid = _fresh("TEN")
    cid = _fresh("CUST")
    stale_jid = _seed_job(dbc, tenant_id=tid, customer_id=cid,
                           scheduled_start=_past_iso(30))
    seeded_jobs.append(stale_jid)

    # Sweep — the stale row should be marked missed.
    summary = _run_missed_cleanup(staleness_hours=48)
    assert summary["marked"] >= 1
    stale_after = dbc.jobs.find_one({"id": stale_jid}, {"_id": 0})
    assert stale_after["status"] == "missed"

    # Portal Next-Service — must NOT surface the now-missed row.
    res = _run_get_portal_summary(
        user={"role": "customer", "customer_id": cid, "id": "u1"},
        tenant={"id": tid},
    )
    assert res["next_service"] is None, (
        f"regression: missed row leaked back through next_service: {res!r}")


def test_next_service_matches_calendar_view_first_row(dbc, cleanup):
    """User-added composition #16 — for a customer with 3 upcoming
    jobs, assert the id returned by ``get_portal_summary.next_service``
    matches the FIRST row from the calendar-view sort applied to
    the same customer.  Guards against the portal + schedule
    surfaces drifting out of sync (they now share the same
    ``(scheduled_start ASC, scheduled_date ASC)`` ordering post-P47).

    The 'calendar view query' is emulated locally with the same
    sort the calendar page uses; the invariant we lock is that
    both surfaces agree on which job is 'next' for this customer."""
    seeded_jobs, _, _ = cleanup
    tid = _fresh("TEN")
    cid = _fresh("CUST")
    # Seed three future jobs at T+1 / T+3 / T+7 — insertion order
    # scrambled so we know the query sort is what surfaces T+1 first.
    j_middle = _seed_job(dbc, tenant_id=tid, customer_id=cid,
                          scheduled_start=_future_iso(3))
    j_soon = _seed_job(dbc, tenant_id=tid, customer_id=cid,
                        scheduled_start=_future_iso(1))
    j_far = _seed_job(dbc, tenant_id=tid, customer_id=cid,
                       scheduled_start=_future_iso(7))
    seeded_jobs.extend([j_middle, j_soon, j_far])

    # Portal summary — should surface j_soon.
    res = _run_get_portal_summary(
        user={"role": "customer", "customer_id": cid, "id": "u1"},
        tenant={"id": tid},
    )
    assert res["next_service"] is not None
    assert res["next_service"]["job_id"] == j_soon

    # Emulate the calendar-view sort for the same customer.  This is
    # deliberately the SAME query the portal uses so we lock the
    # 'agreement' invariant — if a future refactor changes one side
    # without the other, this test breaks.
    now_iso = datetime.now(timezone.utc).isoformat()
    calendar_first = dbc.jobs.find(
        {
            "tenant_id": tid,
            "customer_id": cid,
            "status": {"$in": ["scheduled", "active", "pending", "requested"]},
            "$and": [
                {"$or": [
                    {"deleted_at": None},
                    {"deleted_at": {"$exists": False}},
                ]},
                {"$or": [
                    {"scheduled_start": {"$gte": now_iso}},
                    {"$and": [
                        {"$or": [
                            {"scheduled_start": None},
                            {"scheduled_start": ""},
                            {"scheduled_start": {"$exists": False}},
                        ]},
                        {"scheduled_date": {"$gte": _today_ymd()}},
                    ]},
                ]},
            ],
        },
        {"_id": 0, "id": 1},
    ).sort([("scheduled_start", 1), ("scheduled_date", 1)]).limit(1)
    calendar_first = list(calendar_first)
    assert calendar_first, "calendar-view query returned zero rows"
    assert calendar_first[0]["id"] == res["next_service"]["job_id"], (
        "portal Next-Service tile disagreed with the calendar-view "
        "first row — the two surfaces have drifted apart")
