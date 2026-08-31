"""Feb-2026 · Notification Bundle · testing-agent-fix regressions.

Pins the fixes for the CRITICAL / HIGH / minor issues surfaced by
the live testing agent:

1. **Reschedule status gate** — completed / cancelled / could-
   not-service jobs MUST NOT emit customer-facing reschedule
   copy.
2. **Past-date guard** — back-dating a job for data cleanup
   MUST NOT notify the customer NOR stamp
   ``service_reminder_sent_at``.
3. **Retry-friendly reminder stamping** — transient failures
   (``:failed`` / ``:crash`` / ``:unknown`` / ``:missing_key``)
   leave the reminder stamp OFF so the next cron tick retries.
4. **Scheduler-worker override** — a dedicated scheduler process
   can register crons even when ``APP_ENV=production``.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from services.notifications_pipeline import service_notifications as sn
from tests._notif_pipeline_fakes import _DB, _EmailCapture, _SMSCapture


TZ = "America/Phoenix"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _now_local():
    return datetime.now(ZoneInfo(TZ))


def _wire(monkeypatch):
    email = _EmailCapture(); sms = _SMSCapture()
    monkeypatch.setattr("services.comms_email_adapter.send_email", email)
    monkeypatch.setattr("services.comms_sms_adapter.send_sms", sms)
    return email, sms


# ═══════════════════════════════════════════════════════════════════
# 1. Reschedule status gate
# ═══════════════════════════════════════════════════════════════════
def test_reschedule_on_completed_job_is_no_op(monkeypatch):
    email, sms = _wire(monkeypatch)
    fake_db = _DB(
        jobs=[{"id": "j1", "tenant_id": "t1", "customer_id": "c1",
                "status": "completed",
                "scheduled_date": "2026-09-01"}],
        customers=[{"id": "c1", "tenant_id": "t1", "email": "a@x",
                     "phone": "+15551"}],
        tenants=[{"id": "t1", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    result = _run(sn.fire_reschedule_notification(
        job=dict(fake_db.jobs.rows[0]),
        old_scheduled_date="2026-09-01",
        new_scheduled_date="2026-09-05",
        actor_user_id="admin",
    ))
    assert result["ok"] is False
    assert "status_not_notifiable" in (result.get("reason") or "")
    assert "completed" in (result.get("reason") or "")
    assert email.calls == []
    assert sms.calls == []
    # No audit row written either.
    assert fake_db.notifications_sent_log.inserts == []


def test_reschedule_on_cancelled_job_is_no_op(monkeypatch):
    email, sms = _wire(monkeypatch)
    fake_db = _DB(
        jobs=[{"id": "j1", "tenant_id": "t1", "customer_id": "c1",
                "status": "cancelled",
                "scheduled_date": "2026-09-01"}],
        customers=[{"id": "c1", "tenant_id": "t1", "email": "a@x",
                     "phone": "+15551"}],
        tenants=[{"id": "t1", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    result = _run(sn.fire_reschedule_notification(
        job=dict(fake_db.jobs.rows[0]),
        old_scheduled_date="2026-09-01",
        new_scheduled_date="2026-09-05",
        actor_user_id="admin",
    ))
    assert result["ok"] is False
    assert email.calls == []
    assert sms.calls == []


def test_reschedule_on_active_job_still_fires(monkeypatch):
    """Baseline: scheduled / confirmed / pending → fires."""
    for status in ("scheduled", "confirmed", "pending"):
        email, sms = _wire(monkeypatch)
        fake_db = _DB(
            jobs=[{"id": "j1", "tenant_id": "t1", "customer_id": "c1",
                    "status": status, "service_type": "Pool",
                    "scheduled_date": "2027-01-01"}],
            customers=[{"id": "c1", "tenant_id": "t1", "name": "A",
                         "email": "a@x", "phone": "+15551"}],
            tenants=[{"id": "t1", "name": "T", "timezone": TZ}],
        )
        monkeypatch.setattr(sn, "db", fake_db)

        result = _run(sn.fire_reschedule_notification(
            job=dict(fake_db.jobs.rows[0]),
            old_scheduled_date="2027-01-01",
            new_scheduled_date="2027-01-05",
            actor_user_id="admin",
        ))
        assert result["ok"] is True, (
            f"status={status} should still fire"
        )
        assert set(result["channels_sent"]) == {"email", "sms"}


# ═══════════════════════════════════════════════════════════════════
# 2. Past-date guard
# ═══════════════════════════════════════════════════════════════════
def test_reschedule_to_past_date_is_no_op(monkeypatch):
    """Data-cleanup back-date must NOT notify and MUST NOT stamp
    ``service_reminder_sent_at``."""
    email, sms = _wire(monkeypatch)
    fake_db = _DB(
        jobs=[{"id": "j1", "tenant_id": "t1", "customer_id": "c1",
                "status": "scheduled",
                "scheduled_date": "2020-01-01"}],
        customers=[{"id": "c1", "tenant_id": "t1", "email": "a@x",
                     "phone": "+15551"}],
        tenants=[{"id": "t1", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    result = _run(sn.fire_reschedule_notification(
        job=dict(fake_db.jobs.rows[0]),
        old_scheduled_date="2020-01-01",
        new_scheduled_date="2020-02-01",   # both in the past
        actor_user_id="ops",
    ))
    assert result["ok"] is False
    assert result["reason"] == "new_date_in_past"
    assert email.calls == []
    assert sms.calls == []
    # And no rogue reminder stamp.
    assert not fake_db.jobs.rows[0].get("service_reminder_sent_at")


# ═══════════════════════════════════════════════════════════════════
# 3. Retry-friendly reminder stamping
# ═══════════════════════════════════════════════════════════════════
def test_reminder_transient_failure_does_not_stamp(monkeypatch):
    """Both channels fail transiently → stamp stays off so the
    next cron tick retries. Audit row still written with
    ``stamped=False`` metadata."""
    email = _EmailCapture(ret_status="failed")
    sms = _SMSCapture(ret_status="failed")
    monkeypatch.setattr("services.comms_email_adapter.send_email", email)
    monkeypatch.setattr("services.comms_sms_adapter.send_sms", sms)

    fake_db = _DB(
        jobs=[{"id": "j1", "tenant_id": "t1", "status": "scheduled",
                "customer_id": "c1",
                "scheduled_date": (_now_local() + timedelta(hours=25))
                                    .strftime("%Y-%m-%dT%H:%M:%S")}],
        customers=[{"id": "c1", "tenant_id": "t1", "name": "A",
                     "email": "a@x", "phone": "+15551"}],
        tenants=[{"id": "t1", "name": "T", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    result = _run(sn.fire_reminder_for_job(dict(fake_db.jobs.rows[0])))

    assert result["channels_sent"] == []
    # Both channels marked as transient failures.
    assert any("email:failed" in s for s in result["channels_skipped"])
    assert any("sms:failed" in s for s in result["channels_skipped"])
    # Reminder stamp NOT set → cron will retry next tick.
    assert not fake_db.jobs.rows[0].get("service_reminder_sent_at")
    assert result["will_retry"] is True
    # Audit row still exists so ops has traceability of the retry
    # opportunity.
    assert len(fake_db.notifications_sent_log.inserts) == 1
    assert fake_db.notifications_sent_log.inserts[0]["stamped"] is False


def test_reminder_terminal_optout_still_stamps(monkeypatch):
    """Opt-out is a permanent skip — stamp AS BEFORE so the cron
    doesn't re-scan on every tick."""
    email = _EmailCapture(); sms = _SMSCapture()
    monkeypatch.setattr("services.comms_email_adapter.send_email", email)
    monkeypatch.setattr("services.comms_sms_adapter.send_sms", sms)

    fake_db = _DB(
        jobs=[{"id": "j1", "tenant_id": "t1", "status": "scheduled",
                "customer_id": "c1",
                "scheduled_date": (_now_local() + timedelta(hours=25))
                                    .strftime("%Y-%m-%dT%H:%M:%S")}],
        customers=[{"id": "c1", "tenant_id": "t1", "name": "A",
                     "sms_opt_in": False,
                     "channel_opt_in": {"email": False}}],
        tenants=[{"id": "t1", "name": "T", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    result = _run(sn.fire_reminder_for_job(dict(fake_db.jobs.rows[0])))
    assert result["channels_sent"] == []
    # Terminal skips only.
    assert result["will_retry"] is False
    # Stamp WAS set.
    assert fake_db.jobs.rows[0].get("service_reminder_sent_at")


# ═══════════════════════════════════════════════════════════════════
# 4. Scheduler-worker override
# ═══════════════════════════════════════════════════════════════════
def test_scheduler_worker_override_defeats_production_gate(monkeypatch):
    """A process that exports ``SCHEDULER_WORKER=1`` can enable
    the scheduler even when ``APP_ENV=production``. Without this,
    the dedicated scheduler-worker (``scripts/run_scheduler.py``)
    is dead code in prod."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SCHEDULER_WORKER", "1")
    monkeypatch.setenv("ENABLE_SCHEDULER", "true")

    from boot_flags import should_enable_scheduler
    assert should_enable_scheduler() is True


def test_scheduler_worker_flag_defers_to_explicit_disable(monkeypatch):
    """Even with the worker override, an explicit
    ``ENABLE_SCHEDULER=false`` still disables the scheduler —
    matches the belt-and-braces docstring."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SCHEDULER_WORKER", "1")
    monkeypatch.setenv("ENABLE_SCHEDULER", "false")

    from boot_flags import should_enable_scheduler
    assert should_enable_scheduler() is False


def test_web_worker_stays_off_in_production_without_worker_flag(monkeypatch):
    """Web worker in prod (no ``SCHEDULER_WORKER``) MUST NOT enable
    the scheduler even if ``ENABLE_SCHEDULER=true`` — prevents
    duplicate cron work across web workers."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SCHEDULER_WORKER", raising=False)
    monkeypatch.setenv("ENABLE_SCHEDULER", "true")

    from boot_flags import should_enable_scheduler
    assert should_enable_scheduler() is False
