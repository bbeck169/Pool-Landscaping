"""Phase K63 · Feb-2026 — dispatcher rich-recipient + idempotency.

Extends the P18 test suite by pinning the new K63 behaviours in
``services/lead_notifications.py``:

  1. Rich list (``lead_notification_recipients``) wins over the
     legacy flat lists when both are present.
  2. Per-recipient opt-in toggles gate the channel independently
     (email-only / sms-only / both / none).
  3. Idempotency: a second call for the same (lead, target, channel)
     triple is a no-op — recipients are NOT spammed by a widget
     double-submit.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks

from services.lead_notifications import send_lead_alert_notifications


def _run(bg: BackgroundTasks) -> None:
    async def _drain():
        for t in list(bg.tasks):
            await t()
    asyncio.get_event_loop().run_until_complete(_drain())


def _send_sync(**kwargs):
    return asyncio.get_event_loop().run_until_complete(
        send_lead_alert_notifications(**kwargs),
    )


LEAD = {
    "id": "k63-lead-1", "name": "K63", "phone": "+15551110099",
    "email": "k63@example.com", "service_interest": "Pool",
}


def _clean_dispatches(tid: str, lead_id: str) -> None:
    """Ensure the idempotency table is empty before a scenario."""
    from config import db
    asyncio.get_event_loop().run_until_complete(
        db.lead_notification_dispatches.delete_many(
            {"tenant_id": tid, "lead_id": lead_id},
        ),
    )


def test_rich_recipient_list_gates_channels_by_opt_in():
    """Only recipients with the corresponding opt-in flag receive
    that channel's dispatch. Rich list fully replaces the legacy
    flat lists — legacy addresses are NOT fanned out to when the
    rich list is set (even if the toggle is off)."""
    tid = "k63-tenant-rich"
    _clean_dispatches(tid, LEAD["id"])
    tenant = {
        "id": tid,
        "lead_alert_sms_recipients": ["+15550009999"],  # legacy — ignored
        "lead_alert_email_recipients": ["legacy@x.com"],  # legacy — ignored
        "lead_notification_recipients": [
            {"id": "r1", "name": "Both", "email": "both@x.com",
              "phone": "+15550001111",
              "sms_opt_in": True, "email_opt_in": True},
            {"id": "r2", "name": "SMS", "email": "sms@x.com",
              "phone": "+15550002222",
              "sms_opt_in": True, "email_opt_in": False},
            {"id": "r3", "name": "Email", "email": "em@x.com",
              "phone": "+15550003333",
              "sms_opt_in": False, "email_opt_in": True},
            {"id": "r4", "name": "None", "email": "none@x.com",
              "phone": "+15550004444",
              "sms_opt_in": False, "email_opt_in": False},
        ],
    }
    bg = BackgroundTasks()
    with patch("services.sms.rc_adapter.send",
                 AsyncMock(return_value={"provider_status": "sent"})) as sms_mock, \
             patch("services.email.resend_adapter.send",
                     AsyncMock(return_value={"status": "sent"})) as email_mock:
        counts = _send_sync(
            lead=LEAD, tenant=tenant, background_tasks=bg,
        )
        _run(bg)

    assert counts == {"sms_queued": 2, "email_queued": 2}
    sms_to = sorted(c.kwargs["to"] for c in sms_mock.call_args_list)
    assert sms_to == ["+15550001111", "+15550002222"]
    # Legacy address is NOT included.
    assert "+15550009999" not in sms_to
    email_to = sorted(c.kwargs["to"] for c in email_mock.call_args_list)
    assert email_to == ["both@x.com", "em@x.com"]
    assert "legacy@x.com" not in email_to


def test_idempotent_second_dispatch_is_a_noop():
    """Second call for the same (lead, target, channel) triple
    must not fire the adapter again — handles widget double-submits
    without spamming the on-call rotation."""
    tid = "k63-tenant-idem"
    lead_id = "k63-lead-idem"
    _clean_dispatches(tid, lead_id)
    tenant = {
        "id": tid,
        "lead_notification_recipients": [
            {"id": "r1", "name": "Ops", "email": "ops@x.com",
              "phone": "+15551234567",
              "sms_opt_in": True, "email_opt_in": True},
        ],
    }
    lead = {**LEAD, "id": lead_id}

    with patch("services.sms.rc_adapter.send",
                 AsyncMock(return_value={"provider_status": "sent"})) as sms_mock, \
             patch("services.email.resend_adapter.send",
                     AsyncMock(return_value={"status": "sent"})) as email_mock:
        # First submit — both channels fire.
        bg1 = BackgroundTasks()
        counts_1 = _send_sync(lead=lead, tenant=tenant, background_tasks=bg1)
        _run(bg1)
        # Second submit for the SAME lead — must fire nothing.
        bg2 = BackgroundTasks()
        counts_2 = _send_sync(lead=lead, tenant=tenant, background_tasks=bg2)
        _run(bg2)

    # First run — 1 SMS + 1 email queued and fired.
    assert counts_1["sms_queued"] == 1
    assert counts_1["email_queued"] == 1
    # Total adapter invocations after both runs — still 1 each.
    assert sms_mock.call_count == 1, (
        f"SMS adapter fired {sms_mock.call_count} times; expected 1 (idempotent)."
    )
    assert email_mock.call_count == 1, (
        f"Email adapter fired {email_mock.call_count} times; expected 1 (idempotent)."
    )
    _clean_dispatches(tid, lead_id)
