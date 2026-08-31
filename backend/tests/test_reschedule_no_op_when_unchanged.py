"""Feb-2026 · Reschedule notification · no-op when unchanged.

Contract: identical old→new date fires nothing. Also — a second
call with the same transition (idempotency guard) is a no-op with
``no_op=True`` in the response.
"""
from __future__ import annotations

import asyncio

from services.notifications_pipeline import service_notifications as sn
from tests._notif_pipeline_fakes import _DB, _EmailCapture, _SMSCapture


TZ = "America/Phoenix"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _wire(monkeypatch):
    email = _EmailCapture(); sms = _SMSCapture()
    monkeypatch.setattr("services.comms_email_adapter.send_email", email)
    monkeypatch.setattr("services.comms_sms_adapter.send_sms", sms)
    return email, sms


def test_same_date_is_no_op(monkeypatch):
    email, sms = _wire(monkeypatch)
    fake_db = _DB(
        jobs=[{"id": "j1", "tenant_id": "t1", "customer_id": "c1",
                "scheduled_date": "2026-09-01"}],
        customers=[{"id": "c1", "tenant_id": "t1", "name": "A",
                     "email": "a@x", "phone": "+15551"}],
        tenants=[{"id": "t1", "name": "T", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    result = _run(sn.fire_reschedule_notification(
        job=dict(fake_db.jobs.rows[0]),
        old_scheduled_date="2026-09-01",
        new_scheduled_date="2026-09-01",  # SAME
        actor_user_id="a1",
    ))
    assert result["ok"] is False
    assert result["reason"] == "no_change"
    assert email.calls == []
    assert sms.calls == []


def test_missing_dates_no_op(monkeypatch):
    email, sms = _wire(monkeypatch)
    fake_db = _DB(
        jobs=[{"id": "j1", "tenant_id": "t1", "customer_id": "c1"}],
        customers=[{"id": "c1", "tenant_id": "t1", "email": "a@x",
                     "phone": "+15551"}],
        tenants=[{"id": "t1", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    result = _run(sn.fire_reschedule_notification(
        job=dict(fake_db.jobs.rows[0]),
        old_scheduled_date=None,
        new_scheduled_date="2026-09-05",
        actor_user_id=None,
    ))
    assert result["ok"] is False
    assert email.calls == []


def test_same_transition_twice_is_idempotent(monkeypatch):
    """Second call with the same old→new pair returns ``no_op=True``
    — protects against double-PATCH from a retried request."""
    email, sms = _wire(monkeypatch)
    fake_db = _DB(
        jobs=[{"id": "j1", "tenant_id": "t1", "customer_id": "c1",
                "service_type": "Pool", "scheduled_date": "2026-09-01"}],
        customers=[{"id": "c1", "tenant_id": "t1", "name": "A",
                     "email": "a@x", "phone": "+15551"}],
        tenants=[{"id": "t1", "name": "T", "timezone": TZ}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    r1 = _run(sn.fire_reschedule_notification(
        job=dict(fake_db.jobs.rows[0]),
        old_scheduled_date="2026-09-01",
        new_scheduled_date="2026-09-05",
        actor_user_id="a",
    ))
    assert set(r1["channels_sent"]) == {"email", "sms"}
    assert len(email.calls) == 1
    assert len(sms.calls) == 1

    r2 = _run(sn.fire_reschedule_notification(
        job=dict(fake_db.jobs.rows[0]),
        old_scheduled_date="2026-09-01",
        new_scheduled_date="2026-09-05",
        actor_user_id="a",
    ))
    assert r2.get("no_op") is True
    # Still only 1 email + 1 SMS in total.
    assert len(email.calls) == 1
    assert len(sms.calls) == 1
