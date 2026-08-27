"""Feb-2026 · Sequence trigger — ``job_scheduled_reminder_1d``.

Covers the new day-before service reminder:

* ``TRIGGER_REGISTRY`` exposes the type + empty config schema so the
  composer dropdown can render it.
* ``daily_marketing_trigger_sweep`` picks up jobs scheduled EXACTLY
  tomorrow and enrols the customer via
  ``enrol_customer_into_sequence``.
* Jobs in non-forward statuses (``completed`` / ``cancelled``) are
  skipped.
* Both ``work_class == service`` AND ``work_class == repair`` fire.
* Cross-tenant safety — other tenants' jobs never trigger.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from config import db


TID_A = "test-tenant-job-reminder-a"
TID_B = "test-tenant-job-reminder-b"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _seed():
    for coll in ("tenants", "jobs", "customers",
                  "marketing_sequences", "marketing_drip_enrolments"):
        await db[coll].delete_many({"tenant_id": {"$in": [TID_A, TID_B]}})
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)) \
        .date().isoformat()
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)) \
        .date().isoformat()
    day_after = (datetime.now(timezone.utc) + timedelta(days=2)) \
        .date().isoformat()

    for tid in (TID_A, TID_B):
        await db.tenants.insert_one({
            "id": tid, "name": tid, "slug": tid, "active": True,
            "settings": {},
        })

    # Customers in both tenants (kept minimal for reminder tests).
    await db.customers.insert_many([
        {"id": "c-a1", "tenant_id": TID_A, "name": "A One",
          "email": "a1@example.com", "status": "subscribed"},
        {"id": "c-a2", "tenant_id": TID_A, "name": "A Two",
          "email": "a2@example.com", "status": "subscribed"},
        {"id": "c-b1", "tenant_id": TID_B, "name": "B One",
          "email": "b1@example.com", "status": "subscribed"},
    ])
    # Jobs:
    #   ja-service-tomorrow — tomorrow · scheduled · service → fires
    #   ja-repair-tomorrow  — tomorrow · scheduled · repair → fires
    #   ja-completed        — tomorrow · COMPLETED → skipped
    #   ja-yesterday        — yesterday → skipped
    #   ja-day-after        — day after tomorrow → skipped
    #   jb-tomorrow         — tomorrow · tenant B → other-tenant safety
    await db.jobs.insert_many([
        {"id": "ja-service-tomorrow", "tenant_id": TID_A,
          "customer_id": "c-a1", "scheduled_date": tomorrow,
          "status": "scheduled", "work_class": "service"},
        {"id": "ja-repair-tomorrow", "tenant_id": TID_A,
          "customer_id": "c-a2", "scheduled_date": tomorrow,
          "status": "scheduled", "work_class": "repair"},
        {"id": "ja-completed", "tenant_id": TID_A,
          "customer_id": "c-a1", "scheduled_date": tomorrow,
          "status": "completed", "work_class": "service"},
        {"id": "ja-yesterday", "tenant_id": TID_A,
          "customer_id": "c-a1", "scheduled_date": yesterday,
          "status": "scheduled", "work_class": "service"},
        {"id": "ja-day-after", "tenant_id": TID_A,
          "customer_id": "c-a1", "scheduled_date": day_after,
          "status": "scheduled", "work_class": "service"},
        {"id": "jb-tomorrow", "tenant_id": TID_B,
          "customer_id": "c-b1", "scheduled_date": tomorrow,
          "status": "scheduled", "work_class": "service"},
    ])
    # Active reminder sequence on tenant A only. One step so the
    # inserted enrolment is ``status="active"`` (empty ``steps``
    # would mark the enrolment ``completed`` on insert which
    # bypasses the (sequence, customer, active) dedupe on re-runs).
    await db.marketing_sequences.insert_one({
        "id": "seq-a-reminder", "tenant_id": TID_A,
        "name": "Day-before reminder", "active": True,
        "trigger_type": "job_scheduled_reminder_1d",
        "trigger_config": {},
        "steps": [{"order": 0, "channel": "email",
                    "template_id": "tpl-x", "delay_hours": 0,
                    "delay_from": "trigger"}],
    })


async def _teardown():
    for coll in ("tenants", "jobs", "customers",
                  "marketing_sequences", "marketing_drip_enrolments"):
        await db[coll].delete_many({"tenant_id": {"$in": [TID_A, TID_B]}})


@pytest.fixture(scope="module")
def seeded():
    _run(_seed())
    yield
    _run(_teardown())


class TestTriggerRegistryExposesNewType:
    def test_registry_has_reminder_type(self):
        from routers.marketing_sequences import (
            TRIGGER_REGISTRY, _ALLOWED_TRIGGERS,
        )
        types = {t["type"] for t in TRIGGER_REGISTRY}
        assert "job_scheduled_reminder_1d" in types
        assert "job_scheduled_reminder_1d" in _ALLOWED_TRIGGERS


class TestSweepEnrollsExactlyMatchingJobs:
    def test_sweep_enrolls_service_and_repair_scheduled_tomorrow(self, seeded):
        """Both work_class values fire for tomorrow-scheduled jobs;
        every other job (completed / off-date) is skipped."""
        from services.marketing import drip_events as de
        # Ensure no prior enrolments for tenant A in this test.
        _run(db.marketing_drip_enrolments.delete_many({"tenant_id": TID_A}))
        n = _run(de._sweep_job_scheduled_reminder_1d(TID_A))
        # Exactly 2 → one for the service job, one for the repair job.
        assert n == 2
        # Confirm the enrolments landed on the right customers +
        # sequence.
        rows = _run(db.marketing_drip_enrolments.find(
            {"tenant_id": TID_A, "sequence_id": "seq-a-reminder"},
            {"_id": 0, "customer_id": 1, "trigger_source": 1},
        ).to_list(20))
        customer_ids = {r["customer_id"] for r in rows}
        assert customer_ids == {"c-a1", "c-a2"}
        # Trigger source carries the job id for observability.
        assert all(
            (r.get("trigger_source") or "")
            .startswith("job_scheduled_reminder_1d:")
            for r in rows
        )

    def test_sweep_is_idempotent_same_day(self, seeded):
        """A re-run on the same day must not double-enrol — dedupe
        inside ``enrol_customer_into_sequence`` handles this. Second
        call returns 0."""
        from services.marketing import drip_events as de
        _run(db.marketing_drip_enrolments.delete_many({"tenant_id": TID_A}))
        first = _run(de._sweep_job_scheduled_reminder_1d(TID_A))
        second = _run(de._sweep_job_scheduled_reminder_1d(TID_A))
        assert first == 2
        assert second == 0

    def test_cross_tenant_safety(self, seeded):
        """The sweep on tenant A must not touch tenant B jobs / customers."""
        from services.marketing import drip_events as de
        _run(db.marketing_drip_enrolments.delete_many({"tenant_id": TID_A}))
        _run(db.marketing_drip_enrolments.delete_many({"tenant_id": TID_B}))
        _run(de._sweep_job_scheduled_reminder_1d(TID_A))
        # Tenant B enrolments stay at zero.
        n_b = _run(db.marketing_drip_enrolments.count_documents(
            {"tenant_id": TID_B}))
        assert n_b == 0

    def test_sweep_short_circuits_when_no_active_reminder_sequences(self, seeded):
        """A tenant with no reminder sequence returns 0 without a
        crash — matches the sibling sweeps' behavior."""
        from services.marketing import drip_events as de
        n = _run(de._sweep_job_scheduled_reminder_1d(TID_B))
        assert n == 0
