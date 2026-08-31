"""Feb-2026 · Service reminder cron · idempotency contract."""
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


def _seed(fake_db, monkeypatch):
    monkeypatch.setattr(sn, "db", fake_db)
    monkeypatch.setenv("SERVICE_REMINDER_LOCAL_HOUR",
                        str(_now_local().hour))
    monkeypatch.setattr("services.comms_email_adapter.send_email",
                          _EmailCapture())
    monkeypatch.setattr("services.comms_sms_adapter.send_sms",
                          _SMSCapture())

    async def _lease(**_k):
        return {"acquired": True, "lease_id": "test"}
    monkeypatch.setattr(
        "services.comms_hardening.scheduler_lease.try_acquire_lease",
        _lease,
    )


def test_cron_twice_on_same_job_only_sends_once(monkeypatch):
    """A second cron tick sees the ``service_reminder_sent_at``
    stamp and skips the job entirely — no second fire, no second
    audit row."""
    email = _EmailCapture()
    sms = _SMSCapture()
    monkeypatch.setattr("services.comms_email_adapter.send_email", email)
    monkeypatch.setattr("services.comms_sms_adapter.send_sms", sms)

    async def _lease(**_k):
        return {"acquired": True, "lease_id": "test"}
    monkeypatch.setattr(
        "services.comms_hardening.scheduler_lease.try_acquire_lease",
        _lease,
    )

    fake_db = _DB(
        jobs=[{
            "id": "j1", "tenant_id": "t1", "status": "scheduled",
            "customer_id": "c1", "customer_name": "Alice",
            "scheduled_date": (_now_local() + timedelta(hours=25))
                                    .strftime("%Y-%m-%dT%H:%M:%S"),
        }],
        customers=[{"id": "c1", "tenant_id": "t1", "name": "Alice",
                     "email": "alice@x", "phone": "+15550001"}],
        tenants=[{"id": "t1", "name": "T", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)
    monkeypatch.setenv("SERVICE_REMINDER_LOCAL_HOUR",
                        str(_now_local().hour))

    _run(sn.service_reminder_cron_tick())
    assert len(email.calls) == 1
    assert len(sms.calls) == 1
    assert len(fake_db.notifications_sent_log.inserts) == 1

    # ── Second tick — same in-memory state; job already stamped.
    _run(sn.service_reminder_cron_tick())
    assert len(email.calls) == 1, (
        "email fired again after idempotency stamp"
    )
    assert len(sms.calls) == 1
    assert len(fake_db.notifications_sent_log.inserts) == 1


def test_direct_fire_helper_stamps_and_writes_audit(monkeypatch):
    """``fire_reminder_for_job`` is the shared entry point used by
    both the cron AND the short-window reschedule branch. Direct
    call must produce the same stamp + audit as the cron path."""
    email = _EmailCapture()
    sms = _SMSCapture()
    monkeypatch.setattr("services.comms_email_adapter.send_email", email)
    monkeypatch.setattr("services.comms_sms_adapter.send_sms", sms)

    fake_db = _DB(
        jobs=[{
            "id": "j1", "tenant_id": "t1", "status": "scheduled",
            "customer_id": "c1",
            "scheduled_date": (_now_local() + timedelta(hours=25))
                                    .strftime("%Y-%m-%dT%H:%M:%S"),
        }],
        customers=[{"id": "c1", "tenant_id": "t1", "name": "A",
                     "email": "a@x", "phone": "+15551"}],
        tenants=[{"id": "t1", "name": "T", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    result = _run(sn.fire_reminder_for_job(
        dict(fake_db.jobs.rows[0]),
    ))
    assert result["ok"] is True
    assert set(result["channels_sent"]) == {"email", "sms"}
    assert fake_db.jobs.rows[0].get("service_reminder_sent_at")
    assert len(fake_db.notifications_sent_log.inserts) == 1
