"""Feb-2026 · Service reminder cron · notification preferences.

Preferences precedence per channel:
  1. Hard SMS opt-out (``customer.sms_opt_in == False``) → skip SMS
  2. Marketing channel toggle (``channel_opt_in.{email|sms}=False``)
  3. Feature-specific pref
     (``notification_preferences.{reminders_email|reminders_sms}=False``)
  4. Missing address (no phone / no email)
  5. Otherwise fire.

The cron MUST still stamp the job even when both channels are
skipped for legitimate reasons — otherwise every subsequent tick
re-scans the same opted-out row forever.
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


def test_sms_hard_opt_out_only_email_fires(monkeypatch):
    email = _EmailCapture(); sms = _SMSCapture()
    monkeypatch.setattr("services.comms_email_adapter.send_email", email)
    monkeypatch.setattr("services.comms_sms_adapter.send_sms", sms)

    fake_db = _DB(
        jobs=[_seed_job()],
        customers=[{
            "id": "c1", "tenant_id": "t1", "name": "A",
            "email": "a@x", "phone": "+15551",
            "sms_opt_in": False,   # hard opt-out
        }],
        tenants=[{"id": "t1", "name": "T", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    result = _run(sn.fire_reminder_for_job(dict(fake_db.jobs.rows[0])))

    assert result["ok"] is True
    assert result["channels_sent"] == ["email"]
    assert "sms:hard_opt_out" in result["channels_skipped"]
    assert len(email.calls) == 1
    assert len(sms.calls) == 0


def test_reminders_sms_pref_off_only_email_fires(monkeypatch):
    email = _EmailCapture(); sms = _SMSCapture()
    monkeypatch.setattr("services.comms_email_adapter.send_email", email)
    monkeypatch.setattr("services.comms_sms_adapter.send_sms", sms)

    fake_db = _DB(
        jobs=[_seed_job()],
        customers=[{
            "id": "c1", "tenant_id": "t1", "name": "A",
            "email": "a@x", "phone": "+15551",
            "notification_preferences": {"reminders_sms": False},
        }],
        tenants=[{"id": "t1", "name": "T", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    result = _run(sn.fire_reminder_for_job(dict(fake_db.jobs.rows[0])))

    assert result["channels_sent"] == ["email"]
    assert any("reminders_sms" in x
                for x in result["channels_skipped"])


def test_marketing_channel_opt_out_takes_precedence_over_missing_pref(monkeypatch):
    """A customer with ``channel_opt_in.email=False`` must NOT
    receive email even when the feature-specific pref isn't set.
    Belt-and-braces: the marketing preference is authoritative
    across features."""
    email = _EmailCapture(); sms = _SMSCapture()
    monkeypatch.setattr("services.comms_email_adapter.send_email", email)
    monkeypatch.setattr("services.comms_sms_adapter.send_sms", sms)

    fake_db = _DB(
        jobs=[_seed_job()],
        customers=[{
            "id": "c1", "tenant_id": "t1", "name": "A",
            "email": "a@x", "phone": "+15551",
            "channel_opt_in": {"email": False},
        }],
        tenants=[{"id": "t1", "name": "T", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    result = _run(sn.fire_reminder_for_job(dict(fake_db.jobs.rows[0])))
    assert "email" not in result["channels_sent"]
    assert "sms" in result["channels_sent"]
