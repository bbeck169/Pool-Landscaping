"""Feb-2026 · Service Notifications Pipeline · identity guard.

F1 defense-in-depth. Every send path re-verifies that
``job.customer_id == cust.id`` before rendering the template.
When the invariant fails (bad seed, tenant leak, corrupted ref),
the pipeline logs ERROR + skips the send — but MUST NOT crash the
cron or the PATCH endpoint.
"""
from __future__ import annotations

import asyncio
import logging

from services.notifications_pipeline import service_notifications as sn
from tests._notif_pipeline_fakes import _DB, _EmailCapture, _SMSCapture


TZ = "America/Phoenix"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_reminder_skips_send_on_identity_drift(monkeypatch, caplog):
    """The customers-collection returns a row whose ``id`` differs
    from the job's ``customer_id`` — should NEVER happen in normal
    operation, but the guard exists to catch a corrupted query
    path. Pipeline logs ERROR and returns cleanly."""
    email = _EmailCapture(); sms = _SMSCapture()
    monkeypatch.setattr("services.comms_email_adapter.send_email", email)
    monkeypatch.setattr("services.comms_sms_adapter.send_sms", sms)

    fake_db = _DB(
        jobs=[{"id": "j1", "tenant_id": "t1",
                "customer_id": "c1",
                "scheduled_date": "2026-12-31T09:00:00"}],
        # Seed a row keyed by different id — we override find_one
        # below to force the drift.
        customers=[],
        tenants=[{"id": "t1", "timezone": TZ}],
    )

    async def _drifted_find_one(query, projection=None):  # noqa: ARG001
        # Simulates a corrupted lookup that returns the WRONG customer.
        return {
            "id": "c2-STRANGER",
            "tenant_id": "t1", "name": "Wrong Person",
            "email": "wrong@x", "phone": "+19999999",
        }
    fake_db.customers.find_one = _drifted_find_one  # type: ignore[assignment]
    monkeypatch.setattr(sn, "db", fake_db)

    with caplog.at_level(
        logging.ERROR,
        logger="services.notifications_pipeline.service_notifications",
    ):
        result = _run(sn.fire_reminder_for_job(dict(fake_db.jobs.rows[0])))

    # Identity guard fires: no send, no crash.
    assert result["ok"] is False
    assert result["reason"] == "unresolved_identity"
    assert email.calls == []
    assert sms.calls == []
    # ERROR log emitted with the specific identity fields.
    error_msgs = [r.getMessage() for r in caplog.records
                    if r.levelno == logging.ERROR]
    assert error_msgs, "expected an ERROR log on identity drift"
    joined = "\n".join(error_msgs)
    assert "identity_drift" in joined
    assert "c1" in joined
    assert "c2-STRANGER" in joined


def test_reschedule_skips_send_on_identity_drift(monkeypatch, caplog):
    email = _EmailCapture(); sms = _SMSCapture()
    monkeypatch.setattr("services.comms_email_adapter.send_email", email)
    monkeypatch.setattr("services.comms_sms_adapter.send_sms", sms)

    fake_db = _DB(
        jobs=[{"id": "j1", "tenant_id": "t1",
                "customer_id": "c1",
                "scheduled_date": "2026-09-01"}],
        customers=[],
        tenants=[{"id": "t1", "timezone": TZ}],
    )

    async def _drift(query, projection=None):  # noqa: ARG001
        return {"id": "STRANGER", "tenant_id": "t1"}
    fake_db.customers.find_one = _drift  # type: ignore[assignment]
    monkeypatch.setattr(sn, "db", fake_db)

    with caplog.at_level(
        logging.ERROR,
        logger="services.notifications_pipeline.service_notifications",
    ):
        result = _run(sn.fire_reschedule_notification(
            job=dict(fake_db.jobs.rows[0]),
            old_scheduled_date="2026-09-01",
            new_scheduled_date="2026-09-05",
            actor_user_id="a",
        ))

    assert result["ok"] is False
    assert result["reason"] == "unresolved_identity"
    assert email.calls == []
    assert sms.calls == []
