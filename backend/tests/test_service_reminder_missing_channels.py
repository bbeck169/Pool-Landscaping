"""Feb-2026 · Service reminder cron · missing-channel graceful skips.

A customer with no phone still gets email; a customer with no
email still gets SMS. Missing-both silently skips (still stamps
the job so the cron doesn't re-scan every tick).
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


def _seed_job():
    return {
        "id": "j1", "tenant_id": "t1", "status": "scheduled",
        "customer_id": "c1",
        "scheduled_date": (_now_local() + timedelta(hours=25))
                             .strftime("%Y-%m-%dT%H:%M:%S"),
    }


def test_customer_missing_phone_still_gets_email(monkeypatch):
    email = _EmailCapture(); sms = _SMSCapture()
    monkeypatch.setattr("services.comms_email_adapter.send_email", email)
    monkeypatch.setattr("services.comms_sms_adapter.send_sms", sms)

    fake_db = _DB(
        jobs=[_seed_job()],
        customers=[{"id": "c1", "tenant_id": "t1", "name": "A",
                     "email": "a@x"}],  # no phone
        tenants=[{"id": "t1", "name": "T", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    result = _run(sn.fire_reminder_for_job(dict(fake_db.jobs.rows[0])))
    assert result["channels_sent"] == ["email"]
    assert "sms:no_address" in result["channels_skipped"]


def test_customer_missing_email_still_gets_sms(monkeypatch):
    email = _EmailCapture(); sms = _SMSCapture()
    monkeypatch.setattr("services.comms_email_adapter.send_email", email)
    monkeypatch.setattr("services.comms_sms_adapter.send_sms", sms)

    fake_db = _DB(
        jobs=[_seed_job()],
        customers=[{"id": "c1", "tenant_id": "t1", "name": "A",
                     "phone": "+15551"}],  # no email
        tenants=[{"id": "t1", "name": "T", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    result = _run(sn.fire_reminder_for_job(dict(fake_db.jobs.rows[0])))
    assert result["channels_sent"] == ["sms"]
    assert "email:no_address" in result["channels_skipped"]


def test_customer_missing_both_still_stamps_job(monkeypatch):
    """A customer with neither email nor phone → zero sends, but
    the job MUST still be stamped so the cron doesn't loop on it."""
    email = _EmailCapture(); sms = _SMSCapture()
    monkeypatch.setattr("services.comms_email_adapter.send_email", email)
    monkeypatch.setattr("services.comms_sms_adapter.send_sms", sms)

    fake_db = _DB(
        jobs=[_seed_job()],
        customers=[{"id": "c1", "tenant_id": "t1", "name": "A"}],
        tenants=[{"id": "t1", "name": "T", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    _run(sn.fire_reminder_for_job(dict(fake_db.jobs.rows[0])))
    assert email.calls == []
    assert sms.calls == []
    # Stamp still present.
    assert fake_db.jobs.rows[0].get("service_reminder_sent_at")
