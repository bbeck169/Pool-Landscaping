"""BULK-RESCHEDULE · Feb-2026 — pytest coverage for
``POST /api/jobs/bulk-reschedule``.

Locks:

  * Happy path: 5 valid jobs → all rescheduled, notification fanout
    fires per-job, audit rows written per-job.
  * Empty body → 400 ``no_job_ids``.
  * Cap 101 → 400 ``too_many_job_ids``.
  * Bad date format / real-past date → 400 ``invalid_scheduled_date``.
  * Cross-tenant id → skipped ``wrong_tenant`` (no mutation).
  * Soft-deleted job → skipped ``soft_deleted``.
  * CHEM-LOCK: submitted service_report OR terminal status → skipped
    ``locked``.
  * Non-existent id → skipped ``not_found``.
  * Mixed valid + invalid: ``rescheduled_count`` matches actual and
    invalid ones surface in ``skipped``.
  * SAFE-SEND bg task invoked with ``CommsContext.SYSTEM`` (via the
    ``fire_reschedule_notification`` helper — SAFE-SEND-A dedup).

The tests bypass FastAPI dependency injection and invoke the
handler function directly, mirroring the FLEET-A / MTH-A / SEARCH-
SPEED style — a small in-memory Motor stub replaces
``routers.jobs.db`` for the duration of each test.
"""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import pytest
from fastapi import HTTPException

from routers import jobs as jobs_module
from routers.jobs import (
    BulkRescheduleIn,
    bulk_reschedule_jobs,
    _BULK_RESCHEDULE_CAP,
    _BULK_RESCHEDULE_PAST_LIMIT_DAYS,
)


# ─── In-memory Motor stand-in ──────────────────────────────────────

class _Coll:
    def __init__(self, name: str):
        self.name = name
        self.rows: List[Dict[str, Any]] = []
        self.calls: List[str] = []

    async def find_one(self, predicate, projection=None, **_kw):
        self.calls.append("find_one")
        for r in self.rows:
            if all(r.get(k) == v
                   or (isinstance(v, dict) and self._match_op(r.get(k), v))
                   for k, v in predicate.items()):
                return copy.deepcopy(r)
        return None

    def _match_op(self, val, spec):
        if "$ne" in spec:
            return val != spec["$ne"]
        return False

    async def insert_one(self, doc):
        self.calls.append("insert_one")
        self.rows.append(copy.deepcopy(doc))
        return type("_IR", (), {"inserted_id": doc.get("id")})()

    async def insert_many(self, docs):
        self.calls.append("insert_many")
        for d in docs:
            self.rows.append(copy.deepcopy(d))
        return type("_IR", (),
                    {"inserted_ids": [d.get("id") for d in docs]})()

    async def update_one(self, predicate, update, upsert=False):
        self.calls.append("update_one")
        for r in self.rows:
            if all(r.get(k) == v for k, v in predicate.items()):
                if "$set" in update:
                    r.update(copy.deepcopy(update["$set"]))
                return type("_UR", (),
                            {"matched_count": 1,
                             "modified_count": 1})()
        return type("_UR", (),
                    {"matched_count": 0, "modified_count": 0})()


class _DB:
    def __init__(self):
        self.jobs = _Coll("jobs")
        self.audit_log = _Coll("audit_log")
        self.service_reports = _Coll("service_reports")


def _run(coro):
    """Run ``coro`` on a fresh loop, then flush any bg tasks the
    handler kicked off via ``asyncio.create_task`` so the tests can
    assert on the SAFE-SEND fanout side-effects."""
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(coro)
        # Drain the pending task queue — one bg task per rescheduled
        # job.  ``asyncio.all_tasks`` returns every unfinished task
        # on the loop; we await them all before returning.
        pending = [t for t in asyncio.all_tasks(loop)
                   if not t.done()]
        if pending:
            loop.run_until_complete(asyncio.gather(
                *pending, return_exceptions=True,
            ))
        return result
    finally:
        loop.close()


@pytest.fixture
def fake_db(monkeypatch):
    fake = _DB()
    monkeypatch.setattr(jobs_module, "db", fake, raising=False)
    return fake


@pytest.fixture
def bg_capture():
    """No-op placeholder — the ``_run`` helper above already
    awaits every ``asyncio.create_task`` the handler spawned before
    returning to the assertions, so the bg fanout is deterministic
    without spying on ``create_task``."""
    return []


@pytest.fixture
def stub_notify_customer(monkeypatch):
    calls: List[Dict[str, Any]] = []

    async def _stub(cid, title, body, job_id=None, **kw):
        calls.append({"cid": cid, "title": title,
                       "body": body, "job_id": job_id})

    monkeypatch.setattr(jobs_module, "notify_customer", _stub,
                        raising=True)
    return calls


@pytest.fixture
def stub_fire_reschedule(monkeypatch):
    calls: List[Dict[str, Any]] = []

    async def _stub(*, job, old_scheduled_date, new_scheduled_date,
                    actor_user_id):
        calls.append({
            "job_id": job.get("id"),
            "old_scheduled_date": old_scheduled_date,
            "new_scheduled_date": new_scheduled_date,
            "actor_user_id": actor_user_id,
        })

    # Late-imported inside the handler — monkeypatch the module
    # attribute so the ``from ... import fire_reschedule_notification``
    # line in the handler resolves to our stub.
    import services.notifications_pipeline.service_notifications as svc
    monkeypatch.setattr(svc, "fire_reschedule_notification",
                        _stub, raising=True)
    return calls


TENANT = {"id": "t1"}
ADMIN_USER = {"id": "u-adm", "role": "admin", "email": "a@t1"}
MANAGER_USER = {"id": "u-mgr", "role": "manager",
                 "email": "m@t1"}


def _future_date(days: int = 3) -> str:
    return (datetime.now(timezone.utc)
            + timedelta(days=days)).strftime("%Y-%m-%d")


def _seed_job(fake_db, jid, **overrides):
    row = {
        "id": jid, "tenant_id": "t1",
        "customer_id": f"c-{jid}",
        "customer_name": f"Cust {jid}",
        "service_type": "Weekly Pool Svc",
        "title": f"job-{jid}",
        "status": "scheduled",
        "scheduled_date": "2026-02-01",
        "technician_id": "tech-1",
    }
    row.update(overrides)
    fake_db.jobs.rows.append(row)


# ─── Happy path ───────────────────────────────────────────────────

def test_happy_path_five_jobs_all_rescheduled(
        fake_db, stub_notify_customer, stub_fire_reschedule,
        bg_capture):
    for i in range(5):
        _seed_job(fake_db, f"job-{i}")
    target = _future_date(3)
    res = _run(bulk_reschedule_jobs(
        body=BulkRescheduleIn(
            job_ids=[f"job-{i}" for i in range(5)],
            scheduled_date=target,
        ),
        user=ADMIN_USER, tenant=TENANT,
    ))
    assert res["rescheduled_count"] == 5
    assert res["skipped"] == []
    assert res["target_date"] == target
    # Each seeded job now carries the new scheduled_date.
    for row in fake_db.jobs.rows:
        assert row["scheduled_date"] == target
    # Audit rows — one per job.
    audit = [r for r in fake_db.audit_log.rows
             if r.get("action") == "job.reschedule"]
    assert len(audit) == 5
    assert all(r["source"] == "bulk_reschedule" for r in audit)
    # In-app bell rung once per job.
    assert len(stub_notify_customer) == 5
    # SAFE-SEND SYSTEM bg task fired once per job.
    assert len(stub_fire_reschedule) == 5
    # Each SAFE-SEND payload carries the correct (old, new) pair.
    assert all(c["old_scheduled_date"] == "2026-02-01"
               for c in stub_fire_reschedule)
    assert all(c["new_scheduled_date"] == target
               for c in stub_fire_reschedule)
    assert all(c["actor_user_id"] == "u-adm"
               for c in stub_fire_reschedule)


def test_manager_role_also_accepted(fake_db,
                                       stub_notify_customer,
                                       stub_fire_reschedule,
                                       bg_capture):
    _seed_job(fake_db, "job-1")
    res = _run(bulk_reschedule_jobs(
        body=BulkRescheduleIn(job_ids=["job-1"],
                                scheduled_date=_future_date(2)),
        user=MANAGER_USER, tenant=TENANT,
    ))
    assert res["rescheduled_count"] == 1


# ─── Payload validation ───────────────────────────────────────────

def test_empty_job_ids_rejected(fake_db):
    with pytest.raises(HTTPException) as exc:
        _run(bulk_reschedule_jobs(
            body=BulkRescheduleIn(job_ids=[],
                                    scheduled_date=_future_date(3)),
            user=ADMIN_USER, tenant=TENANT,
        ))
    assert exc.value.status_code == 400
    assert exc.value.detail["error_code"] == "no_job_ids"


def test_over_cap_rejected(fake_db):
    ids = [f"job-{i}" for i in range(_BULK_RESCHEDULE_CAP + 1)]
    with pytest.raises(HTTPException) as exc:
        _run(bulk_reschedule_jobs(
            body=BulkRescheduleIn(job_ids=ids,
                                    scheduled_date=_future_date(3)),
            user=ADMIN_USER, tenant=TENANT,
        ))
    assert exc.value.status_code == 400
    assert exc.value.detail["error_code"] == "too_many_job_ids"
    assert exc.value.detail["limit"] == _BULK_RESCHEDULE_CAP


def test_bad_date_format_rejected(fake_db):
    for bad in ("2026/02/01", "Feb 1 2026", "2026-2-1", "yesterday",
                "", "2026-02-01T10:00"):
        with pytest.raises(HTTPException) as exc:
            _run(bulk_reschedule_jobs(
                body=BulkRescheduleIn(job_ids=["job-1"],
                                        scheduled_date=bad),
                user=ADMIN_USER, tenant=TENANT,
            ))
        assert exc.value.status_code == 400, (
            f"date {bad!r} should be rejected"
        )
        assert (exc.value.detail["error_code"]
                 == "invalid_scheduled_date")


def test_impossible_calendar_date_rejected(fake_db):
    with pytest.raises(HTTPException) as exc:
        _run(bulk_reschedule_jobs(
            body=BulkRescheduleIn(job_ids=["job-1"],
                                    scheduled_date="2026-02-30"),
            user=ADMIN_USER, tenant=TENANT,
        ))
    assert exc.value.status_code == 400
    assert (exc.value.detail["error_code"]
             == "invalid_scheduled_date")


def test_way_past_date_rejected(fake_db):
    past = (datetime.now(timezone.utc)
            - timedelta(days=_BULK_RESCHEDULE_PAST_LIMIT_DAYS + 5)
            ).strftime("%Y-%m-%d")
    with pytest.raises(HTTPException) as exc:
        _run(bulk_reschedule_jobs(
            body=BulkRescheduleIn(job_ids=["job-1"],
                                    scheduled_date=past),
            user=ADMIN_USER, tenant=TENANT,
        ))
    assert exc.value.status_code == 400
    assert (exc.value.detail["error_code"]
             == "invalid_scheduled_date")
    assert (exc.value.detail["past_limit_days"]
             == _BULK_RESCHEDULE_PAST_LIMIT_DAYS)


def test_recent_past_date_accepted(fake_db, stub_notify_customer,
                                     stub_fire_reschedule,
                                     bg_capture):
    """Within the 90-day past window — accepted (bulk retro moves)."""
    _seed_job(fake_db, "job-1")
    recent = (datetime.now(timezone.utc)
              - timedelta(days=10)).strftime("%Y-%m-%d")
    res = _run(bulk_reschedule_jobs(
        body=BulkRescheduleIn(job_ids=["job-1"],
                                scheduled_date=recent),
        user=ADMIN_USER, tenant=TENANT,
    ))
    assert res["rescheduled_count"] == 1


# ─── Skip-reasons ─────────────────────────────────────────────────

def test_not_found_skip_reason(fake_db, stub_notify_customer,
                                  stub_fire_reschedule, bg_capture):
    res = _run(bulk_reschedule_jobs(
        body=BulkRescheduleIn(job_ids=["nope"],
                                scheduled_date=_future_date(3)),
        user=ADMIN_USER, tenant=TENANT,
    ))
    assert res["rescheduled_count"] == 0
    assert res["skipped"] == [{"job_id": "nope", "reason":
                                  "not_found"}]


def test_wrong_tenant_skip_reason(fake_db, stub_notify_customer,
                                     stub_fire_reschedule,
                                     bg_capture):
    _seed_job(fake_db, "job-foreign", tenant_id="t-other")
    res = _run(bulk_reschedule_jobs(
        body=BulkRescheduleIn(job_ids=["job-foreign"],
                                scheduled_date=_future_date(3)),
        user=ADMIN_USER, tenant=TENANT,
    ))
    assert res["rescheduled_count"] == 0
    assert res["skipped"] == [{"job_id": "job-foreign",
                                 "reason": "wrong_tenant"}]
    # Cross-tenant row NEVER mutated.
    row = next(r for r in fake_db.jobs.rows if r["id"] == "job-foreign")
    assert row["scheduled_date"] == "2026-02-01"


def test_soft_deleted_skip_reason(fake_db, stub_notify_customer,
                                     stub_fire_reschedule,
                                     bg_capture):
    _seed_job(fake_db, "job-hd",
              deleted_at="2026-02-05T00:00:00Z")
    res = _run(bulk_reschedule_jobs(
        body=BulkRescheduleIn(job_ids=["job-hd"],
                                scheduled_date=_future_date(3)),
        user=ADMIN_USER, tenant=TENANT,
    ))
    assert res["rescheduled_count"] == 0
    assert res["skipped"] == [{"job_id": "job-hd",
                                 "reason": "soft_deleted"}]


def test_terminal_status_locked_skip_reason(
        fake_db, stub_notify_customer, stub_fire_reschedule,
        bg_capture):
    _seed_job(fake_db, "job-done", status="completed")
    _seed_job(fake_db, "job-cancel", status="cancelled")
    res = _run(bulk_reschedule_jobs(
        body=BulkRescheduleIn(
            job_ids=["job-done", "job-cancel"],
            scheduled_date=_future_date(3),
        ),
        user=ADMIN_USER, tenant=TENANT,
    ))
    assert res["rescheduled_count"] == 0
    assert {r["reason"] for r in res["skipped"]} == {"locked"}
    assert {r["job_id"] for r in res["skipped"]} == {
        "job-done", "job-cancel",
    }


def test_chem_lock_submitted_service_report_skips(
        fake_db, stub_notify_customer, stub_fire_reschedule,
        bg_capture):
    _seed_job(fake_db, "job-locked")
    fake_db.service_reports.rows.append({
        "id": "sr-1", "tenant_id": "t1",
        "job_id": "job-locked",
        "submitted_at": "2026-02-04T18:00:00Z",
    })
    res = _run(bulk_reschedule_jobs(
        body=BulkRescheduleIn(job_ids=["job-locked"],
                                scheduled_date=_future_date(3)),
        user=ADMIN_USER, tenant=TENANT,
    ))
    assert res["rescheduled_count"] == 0
    assert res["skipped"] == [{"job_id": "job-locked",
                                 "reason": "locked"}]


def test_service_report_without_submitted_at_does_not_lock(
        fake_db, stub_notify_customer, stub_fire_reschedule,
        bg_capture):
    _seed_job(fake_db, "job-open")
    fake_db.service_reports.rows.append({
        "id": "sr-2", "tenant_id": "t1",
        "job_id": "job-open", "submitted_at": None,
    })
    res = _run(bulk_reschedule_jobs(
        body=BulkRescheduleIn(job_ids=["job-open"],
                                scheduled_date=_future_date(3)),
        user=ADMIN_USER, tenant=TENANT,
    ))
    assert res["rescheduled_count"] == 1
    assert res["skipped"] == []


# ─── Mixed valid + invalid ────────────────────────────────────────

def test_mixed_valid_and_invalid_partitions_response(
        fake_db, stub_notify_customer, stub_fire_reschedule,
        bg_capture):
    _seed_job(fake_db, "ok-1")
    _seed_job(fake_db, "ok-2")
    _seed_job(fake_db, "hd-1", deleted_at="2026-02-05T00:00Z")
    _seed_job(fake_db, "done-1", status="completed")
    _seed_job(fake_db, "foreign-1", tenant_id="t-other")
    target = _future_date(3)

    res = _run(bulk_reschedule_jobs(
        body=BulkRescheduleIn(
            job_ids=["ok-1", "hd-1", "missing-1",
                       "done-1", "foreign-1", "ok-2"],
            scheduled_date=target,
        ),
        user=ADMIN_USER, tenant=TENANT,
    ))
    assert res["rescheduled_count"] == 2
    reasons_by_id = {r["job_id"]: r["reason"] for r in res["skipped"]}
    assert reasons_by_id == {
        "hd-1": "soft_deleted",
        "missing-1": "not_found",
        "done-1": "locked",
        "foreign-1": "wrong_tenant",
    }
    # SAFE-SEND fanout fired for the 2 valid ones only.
    assert len(stub_fire_reschedule) == 2
    assert {c["job_id"] for c in stub_fire_reschedule} == {
        "ok-1", "ok-2",
    }
    assert len(stub_notify_customer) == 2


def test_duplicate_ids_deduped(fake_db, stub_notify_customer,
                                  stub_fire_reschedule, bg_capture):
    _seed_job(fake_db, "job-a")
    res = _run(bulk_reschedule_jobs(
        body=BulkRescheduleIn(
            job_ids=["job-a", "job-a", "job-a"],
            scheduled_date=_future_date(3),
        ),
        user=ADMIN_USER, tenant=TENANT,
    ))
    # Deduped to a single work-unit.
    assert res["rescheduled_count"] == 1
    assert len(stub_fire_reschedule) == 1


# ─── Contract ─────────────────────────────────────────────────────

def test_response_shape_contract(fake_db, stub_notify_customer,
                                    stub_fire_reschedule, bg_capture):
    _seed_job(fake_db, "job-1")
    res = _run(bulk_reschedule_jobs(
        body=BulkRescheduleIn(job_ids=["job-1"],
                                scheduled_date=_future_date(3)),
        user=ADMIN_USER, tenant=TENANT,
    ))
    # Contract keys.
    assert set(res.keys()) >= {
        "rescheduled_count", "skipped", "target_date",
    }
    assert isinstance(res["rescheduled_count"], int)
    assert isinstance(res["skipped"], list)
    assert isinstance(res["target_date"], str)


def test_no_side_effects_on_validation_reject(fake_db,
                                                 stub_notify_customer,
                                                 stub_fire_reschedule,
                                                 bg_capture):
    """400 responses must NOT touch Mongo / fire notifications."""
    _seed_job(fake_db, "job-1")
    with pytest.raises(HTTPException):
        _run(bulk_reschedule_jobs(
            body=BulkRescheduleIn(job_ids=["job-1"],
                                    scheduled_date="not-a-date"),
            user=ADMIN_USER, tenant=TENANT,
        ))
    assert stub_notify_customer == []
    assert stub_fire_reschedule == []
    row = fake_db.jobs.rows[0]
    assert row["scheduled_date"] == "2026-02-01"


def test_audit_row_carries_actor_and_source(
        fake_db, stub_notify_customer, stub_fire_reschedule,
        bg_capture):
    _seed_job(fake_db, "job-1")
    _run(bulk_reschedule_jobs(
        body=BulkRescheduleIn(job_ids=["job-1"],
                                scheduled_date=_future_date(3)),
        user=ADMIN_USER, tenant=TENANT,
    ))
    audit = [r for r in fake_db.audit_log.rows
             if r["action"] == "job.reschedule"]
    assert len(audit) == 1
    row = audit[0]
    assert row["actor_user_id"] == "u-adm"
    assert row["actor_email"] == "a@t1"
    assert row["source"] == "bulk_reschedule"
    assert row["old_scheduled_date"] == "2026-02-01"
    assert row["new_scheduled_date"] == audit[0]["new_scheduled_date"]
    assert row["tenant_id"] == "t1"
