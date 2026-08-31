"""Feb-2026 · Reschedule notification event · fires on scheduled_date change."""
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


def _seed(monkeypatch, *, extra_cust=None, jobs=None):
    email = _EmailCapture(); sms = _SMSCapture()
    monkeypatch.setattr("services.comms_email_adapter.send_email", email)
    monkeypatch.setattr("services.comms_sms_adapter.send_sms", sms)

    cust = {"id": "c1", "tenant_id": "t1", "name": "Alice",
             "email": "alice@x", "phone": "+15550001"}
    if extra_cust:
        cust.update(extra_cust)
    fake_db = _DB(
        jobs=jobs or [{"id": "j1", "tenant_id": "t1",
                        "customer_id": "c1",
                        "service_type": "Pool Cleaning",
                        "scheduled_date": "2026-09-01"}],
        customers=[cust],
        tenants=[{"id": "t1", "name": "AquaTerra", "timezone": TZ,
                   "phone": "+15559999"}],
    )
    monkeypatch.setattr(sn, "db", fake_db)
    return fake_db, email, sms


def test_reschedule_fires_both_channels_and_writes_audit(monkeypatch):
    fake_db, email, sms = _seed(monkeypatch)

    result = _run(sn.fire_reschedule_notification(
        job=dict(fake_db.jobs.rows[0]),
        old_scheduled_date="2026-09-01",
        new_scheduled_date="2026-09-05",
        actor_user_id="admin-1",
    ))

    assert result["ok"] is True
    assert set(result["channels_sent"]) == {"email", "sms"}
    assert len(email.calls) == 1
    assert len(sms.calls) == 1
    # SMS body carries BOTH old and new formatted times.
    body = sms.calls[0]["body"]
    assert "Pool Cleaning" in body
    assert "AquaTerra" in body
    # Audit row with the transition_key.
    audit = fake_db.notifications_sent_log.inserts[0]
    assert audit["template_key"] == "reschedule_service"
    assert audit["actor"] == "user:admin-1"
    assert audit["transition_key"] == "2026-09-01→2026-09-05"
    assert "old_scheduled_at" in audit
    assert "new_scheduled_at" in audit


def test_reschedule_pref_off_skips_channel(monkeypatch):
    fake_db, email, sms = _seed(
        monkeypatch,
        extra_cust={"notification_preferences":
                        {"reschedule_email": False}},
    )
    result = _run(sn.fire_reschedule_notification(
        job=dict(fake_db.jobs.rows[0]),
        old_scheduled_date="2026-09-01",
        new_scheduled_date="2026-09-05",
        actor_user_id=None,
    ))
    assert "sms" in result["channels_sent"]
    assert "email" not in result["channels_sent"]
    assert any("reschedule_email" in s
                for s in result["channels_skipped"])
