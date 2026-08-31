"""Feb-2026 · Reschedule short-window dedup.

Contract: when a PATCH moves a job INTO a <24hr window, the
reschedule notification fires AS NORMAL and also stamps
``service_reminder_sent_at`` so the 24-hr cron doesn't double-send
a separate reminder. Rationale: the reschedule notification
already communicates the new timing to the customer.

When the new date is >=24hr out, the reminder stamp is NOT touched
— the cron can still fire at the normal window.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
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


def test_reschedule_into_short_window_stamps_reminder(monkeypatch):
    _wire(monkeypatch)
    # NEW date is 6 hours from now → short window.
    new_iso = (_now_local() + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%S")

    fake_db = _DB(
        jobs=[{"id": "j1", "tenant_id": "t1", "customer_id": "c1",
                "service_type": "Pool",
                "scheduled_date": "2026-12-31T09:00:00"}],
        customers=[{"id": "c1", "tenant_id": "t1", "name": "A",
                     "email": "a@x", "phone": "+15551"}],
        tenants=[{"id": "t1", "name": "T", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    result = _run(sn.fire_reschedule_notification(
        job=dict(fake_db.jobs.rows[0]),
        old_scheduled_date="2026-12-31T09:00:00",
        new_scheduled_date=new_iso,
        actor_user_id="a",
    ))
    assert result["ok"] is True
    # Job now carries the reminder stamp — cron will not double-fire.
    stored = fake_db.jobs.rows[0]
    assert stored.get("service_reminder_sent_at"), (
        "short-window reschedule did NOT stamp the reminder — "
        "cron will double-send"
    )


def test_reschedule_into_long_window_does_not_stamp_reminder(monkeypatch):
    _wire(monkeypatch)
    # NEW date is 96 hours (4 days) from now → cron should still
    # fire at ~72hr from now.
    new_iso = (_now_local() + timedelta(hours=96)).strftime("%Y-%m-%dT%H:%M:%S")

    fake_db = _DB(
        jobs=[{"id": "j1", "tenant_id": "t1", "customer_id": "c1",
                "service_type": "Pool",
                "scheduled_date": "2026-12-31T09:00:00"}],
        customers=[{"id": "c1", "tenant_id": "t1", "name": "A",
                     "email": "a@x", "phone": "+15551"}],
        tenants=[{"id": "t1", "name": "T", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    _run(sn.fire_reschedule_notification(
        job=dict(fake_db.jobs.rows[0]),
        old_scheduled_date="2026-12-31T09:00:00",
        new_scheduled_date=new_iso,
        actor_user_id="a",
    ))
    stored = fake_db.jobs.rows[0]
    # Reminder stamp NOT set — cron will fire at the normal 24hr
    # window.
    assert not stored.get("service_reminder_sent_at")


def test_reschedule_short_window_when_already_stamped_leaves_stamp(monkeypatch):
    """If the job already has ``service_reminder_sent_at`` set
    (e.g., cron already fired), the reschedule short-window branch
    does NOT overwrite it. The reschedule notification itself still
    fires."""
    email, _sms = _wire(monkeypatch)
    original_stamp = "2026-07-15T08:00:00Z"
    new_iso = (_now_local() + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%S")

    fake_db = _DB(
        jobs=[{"id": "j1", "tenant_id": "t1", "customer_id": "c1",
                "service_type": "Pool",
                "scheduled_date": "2026-12-31T09:00:00",
                "service_reminder_sent_at": original_stamp}],
        customers=[{"id": "c1", "tenant_id": "t1", "name": "A",
                     "email": "a@x", "phone": "+15551"}],
        tenants=[{"id": "t1", "name": "T", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    _run(sn.fire_reschedule_notification(
        job=dict(fake_db.jobs.rows[0]),
        old_scheduled_date="2026-12-31T09:00:00",
        new_scheduled_date=new_iso,
        actor_user_id="a",
    ))
    assert fake_db.jobs.rows[0]["service_reminder_sent_at"] == original_stamp
    # But the reschedule notification DID still fire.
    assert len(email.calls) == 1
