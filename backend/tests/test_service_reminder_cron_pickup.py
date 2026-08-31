"""Feb-2026 · Service reminder cron · happy path pickup."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from services.notifications_pipeline import service_notifications as sn
from tests._notif_pipeline_fakes import _DB, _EmailCapture, _SMSCapture


TZ = "America/Phoenix"


def _now_local():
    return datetime.now(ZoneInfo(TZ))


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def wire(monkeypatch):
    """Wire the service_notifications module + comms adapters to
    in-memory fakes. Returns the DB + captured adapter calls."""
    email = _EmailCapture()
    sms = _SMSCapture()
    monkeypatch.setattr(sn, "logger", sn.logger)  # no-op, keeps IDE happy
    # ``fire_hour = 8`` matches the module default so the cron
    # picks up jobs when the tenant's local hour is 08.
    monkeypatch.setenv("SERVICE_REMINDER_LOCAL_HOUR",
                        str(_now_local().hour))
    monkeypatch.setattr(
        "services.comms_email_adapter.send_email", email,
    )
    monkeypatch.setattr(
        "services.comms_sms_adapter.send_sms", sms,
    )
    # Bypass the scheduler_lease — the tests don't need real
    # inter-process protection.
    async def _fake_lease(**_k):
        return {"acquired": True, "lease_id": "test"}
    monkeypatch.setattr(
        "services.comms_hardening.scheduler_lease.try_acquire_lease",
        _fake_lease,
    )
    return {"email": email, "sms": sms}


def _seed_due_job(target_hours: int = 25) -> dict:
    """Return a job dict whose ``scheduled_date`` is
    ``target_hours`` hours from now in the tenant TZ."""
    dt = _now_local() + timedelta(hours=target_hours)
    return {
        "id": "job-1", "tenant_id": "t1", "status": "scheduled",
        "customer_id": "c1", "customer_name": "Alice",
        "service_type": "Pool Cleaning",
        "scheduled_date": dt.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def test_reminder_cron_picks_up_24hr_job_and_fires_both_channels(wire, monkeypatch):
    job = _seed_due_job(target_hours=25)
    fake_db = _DB(
        jobs=[job],
        customers=[{"id": "c1", "tenant_id": "t1", "name": "Alice",
                     "email": "alice@x", "phone": "+15550001"}],
        tenants=[{"id": "t1", "name": "AquaTerra", "timezone": TZ,
                   "phone": "+15559999"}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    result = _run(sn.service_reminder_cron_tick())

    assert result["total_fires"] == 1
    # Both channels invoked.
    assert len(wire["email"].calls) == 1
    assert len(wire["sms"].calls) == 1
    # Body sanity — templates should include the customer name +
    # service_type + tenant phone.
    sms_body = wire["sms"].calls[0]["body"]
    assert "Alice" in sms_body
    assert "Pool Cleaning" in sms_body
    assert "+15559999" in sms_body
    email_kw = wire["email"].calls[0]
    assert "Pool Cleaning" in email_kw["subject"]
    assert "Alice" in email_kw["html"]

    # ── Job now carries the idempotency stamp.
    stored = fake_db.jobs.rows[0]
    assert stored.get("service_reminder_sent_at")

    # ── Audit row written.
    assert len(fake_db.notifications_sent_log.inserts) == 1
    audit = fake_db.notifications_sent_log.inserts[0]
    assert audit["template_key"] == "service_reminder"
    assert set(audit["channels_sent"]) == {"email", "sms"}
    assert audit["actor"] == "system_cron"


def test_reminder_cron_skips_jobs_outside_24hr_window(wire, monkeypatch):
    """A job scheduled 48 hours out doesn't fire; 12 hours out
    doesn't fire either. Only the 24-27hr window is picked up."""
    fake_db = _DB(
        jobs=[
            {"id": "j-far", "tenant_id": "t1", "status": "scheduled",
             "customer_id": "c1",
             "scheduled_date": (_now_local() + timedelta(hours=48))
                                    .strftime("%Y-%m-%dT%H:%M:%S")},
            {"id": "j-near", "tenant_id": "t1", "status": "scheduled",
             "customer_id": "c1",
             "scheduled_date": (_now_local() + timedelta(hours=12))
                                    .strftime("%Y-%m-%dT%H:%M:%S")},
        ],
        customers=[{"id": "c1", "tenant_id": "t1", "name": "A",
                     "email": "a@x", "phone": "+15551"}],
        tenants=[{"id": "t1", "name": "T", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    result = _run(sn.service_reminder_cron_tick())

    assert result["total_fires"] == 0
    assert wire["email"].calls == []
    assert wire["sms"].calls == []


def test_reminder_cron_skips_wrong_status(wire, monkeypatch):
    """Jobs whose status is not in the reminder-eligible set
    (e.g., 'completed', 'cancelled', 'deleted') are ignored."""
    fake_db = _DB(
        jobs=[{
            "id": "j1", "tenant_id": "t1", "status": "completed",
            "customer_id": "c1",
            "scheduled_date": (_now_local() + timedelta(hours=25))
                                    .strftime("%Y-%m-%dT%H:%M:%S"),
        }],
        customers=[{"id": "c1", "tenant_id": "t1", "name": "A",
                     "email": "a@x", "phone": "+15551"}],
        tenants=[{"id": "t1", "name": "T", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    _run(sn.service_reminder_cron_tick())
    assert wire["email"].calls == []
    assert wire["sms"].calls == []


def test_reminder_cron_skips_soft_deleted_job(wire, monkeypatch):
    fake_db = _DB(
        jobs=[{
            "id": "j1", "tenant_id": "t1", "status": "scheduled",
            "customer_id": "c1",
            "deleted_at": "2026-08-01",
            "scheduled_date": (_now_local() + timedelta(hours=25))
                                    .strftime("%Y-%m-%dT%H:%M:%S"),
        }],
        customers=[{"id": "c1", "tenant_id": "t1", "name": "A",
                     "email": "a@x", "phone": "+15551"}],
        tenants=[{"id": "t1", "name": "T", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    _run(sn.service_reminder_cron_tick())
    assert wire["email"].calls == []
