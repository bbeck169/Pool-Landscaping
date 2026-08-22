"""Feb-2026 · P18 — lead-alert notification fan-out.

Pins the ``services.lead_notifications.send_lead_alert_notifications``
helper contract:

  1. Empty recipient lists → no-op, neither adapter is invoked.
  2. SMS-only recipients → RingCentral adapter fires, Resend does NOT.
  3. Email-only recipients → Resend fires, RingCentral does NOT.
  4. Both configured → both fire, one BackgroundTask per recipient.
  5. Cross-tenant isolation: tenant A's recipients never receive
     tenant B's lead alerts (helper takes the tenant doc as an arg;
     no DB lookup happens inside).
  6. Adapter failure inside the background task is swallowed — the
     lead-create request must remain 200 regardless.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks

from services.lead_notifications import (
    send_lead_alert_notifications,
    _send_lead_alert_sms,
    _send_lead_alert_email,
    build_sms_body,
    build_email_html,
)


def _run(bg: BackgroundTasks) -> None:
    """Execute all queued BackgroundTasks synchronously (matches what
    FastAPI does after the response is sent)."""
    async def _drain():
        for t in list(bg.tasks):
            await t()
    asyncio.get_event_loop().run_until_complete(_drain())


LEAD_A = {
    "id": "lead-a1",
    "name": "Alice", "phone": "+15551110001",
    "email": "alice@example.com",
    "service_address": "123 Alice Rd",
    "service_interest": "Pool",
    "message": "Please quote weekly service.",
}
LEAD_B = {
    "id": "lead-b1", "name": "Bob", "phone": "+15551110002",
    "email": "bob@example.com",
}


# ── 1. Empty recipients — no-op ─────────────────────────────────
def test_empty_recipients_are_a_no_op():
    tenant = {"id": "t-empty",
                "lead_alert_sms_recipients": [],
                "lead_alert_email_recipients": []}
    bg = BackgroundTasks()
    with patch("services.sms.rc_adapter.send", AsyncMock()) as sms_mock, \
         patch("services.email.resend_adapter.send", AsyncMock()) as email_mock:
        counts = send_lead_alert_notifications(
            lead=LEAD_A, tenant=tenant, background_tasks=bg,
        )
        _run(bg)
    assert counts == {"sms_queued": 0, "email_queued": 0}
    sms_mock.assert_not_called()
    email_mock.assert_not_called()


# ── 2. SMS-only recipients → RingCentral fires, Resend does NOT ─
def test_sms_only_recipients_fire_only_ringcentral():
    tenant = {"id": "t-sms",
                "lead_alert_sms_recipients": ["+16028874400"],
                "lead_alert_email_recipients": []}
    bg = BackgroundTasks()
    with patch("services.sms.rc_adapter.send",
                 AsyncMock(return_value={"provider_status": "sent"})) as sms_mock, \
         patch("services.email.resend_adapter.send", AsyncMock()) as email_mock:
        counts = send_lead_alert_notifications(
            lead=LEAD_A, tenant=tenant, background_tasks=bg,
        )
        _run(bg)
    assert counts == {"sms_queued": 1, "email_queued": 0}
    assert sms_mock.call_count == 1
    call_kwargs = sms_mock.call_args.kwargs
    assert call_kwargs["to"] == "+16028874400"
    assert "New lead — Alice" in call_kwargs["body"]
    assert "+15551110001" in call_kwargs["body"]
    email_mock.assert_not_called()


# ── 3. Email-only recipients → Resend fires, RingCentral does NOT ──
def test_email_only_recipients_fire_only_resend():
    tenant = {"id": "t-email",
                "lead_alert_sms_recipients": [],
                "lead_alert_email_recipients": ["brian@plofv.com"]}
    bg = BackgroundTasks()
    with patch("services.sms.rc_adapter.send", AsyncMock()) as sms_mock, \
         patch("services.email.resend_adapter.send",
                 AsyncMock(return_value={"status": "sent"})) as email_mock:
        counts = send_lead_alert_notifications(
            lead=LEAD_A, tenant=tenant, background_tasks=bg,
        )
        _run(bg)
    assert counts == {"sms_queued": 0, "email_queued": 1}
    sms_mock.assert_not_called()
    assert email_mock.call_count == 1
    kwargs = email_mock.call_args.kwargs
    assert kwargs["to"] == "brian@plofv.com"
    assert "New lead — Alice" in kwargs["subject"]
    assert "+15551110001" in kwargs["subject"]
    assert "alice@example.com" in kwargs["html"]
    assert "Please quote weekly service." in kwargs["html"]


# ── 4. Both configured → both fire ──────────────────────────────
def test_both_configured_fires_both_channels():
    tenant = {"id": "t-both",
                "lead_alert_sms_recipients": ["+16028874400", "+15550000001"],
                "lead_alert_email_recipients": ["brian@plofv.com",
                                                    "ops@plofv.com"]}
    bg = BackgroundTasks()
    with patch("services.sms.rc_adapter.send",
                 AsyncMock(return_value={"provider_status": "sent"})) as sms_mock, \
         patch("services.email.resend_adapter.send",
                 AsyncMock(return_value={"status": "sent"})) as email_mock:
        counts = send_lead_alert_notifications(
            lead=LEAD_A, tenant=tenant, background_tasks=bg,
        )
        _run(bg)
    assert counts == {"sms_queued": 2, "email_queued": 2}
    assert sms_mock.call_count == 2
    assert email_mock.call_count == 2


# ── 5. Cross-tenant isolation ──────────────────────────────────
def test_cross_tenant_isolation():
    """Helper takes the tenant doc as an arg + does zero DB lookup —
    so tenant B's lead can never fan out to tenant A's recipients."""
    tenant_a = {"id": "t-a",
                  "lead_alert_sms_recipients": ["+15559990001"],
                  "lead_alert_email_recipients": []}
    tenant_b = {"id": "t-b",
                  "lead_alert_sms_recipients": ["+15559990002"],
                  "lead_alert_email_recipients": []}
    bg = BackgroundTasks()
    with patch("services.sms.rc_adapter.send",
                 AsyncMock(return_value={"provider_status": "sent"})) as sms_mock:
        # Tenant A's lead — must only fire to tenant A's recipient.
        send_lead_alert_notifications(
            lead=LEAD_A, tenant=tenant_a, background_tasks=bg,
        )
        _run(bg)
    to_addrs = [c.kwargs["to"] for c in sms_mock.call_args_list]
    assert to_addrs == ["+15559990001"], (
        f"tenant A lead must only fan out to tenant A recipient, got {to_addrs}"
    )
    # Now tenant B lead — proves the helper does NOT retain cross-run state.
    bg2 = BackgroundTasks()
    with patch("services.sms.rc_adapter.send",
                 AsyncMock(return_value={"provider_status": "sent"})) as sms_mock2:
        send_lead_alert_notifications(
            lead=LEAD_B, tenant=tenant_b, background_tasks=bg2,
        )
        _run(bg2)
    to_addrs2 = [c.kwargs["to"] for c in sms_mock2.call_args_list]
    assert to_addrs2 == ["+15559990002"]


# ── 6. Adapter failure is swallowed ────────────────────────────
def test_adapter_failure_never_propagates():
    """A broken RC / Resend SDK inside the background task must be
    swallowed by the task's own try/except; nothing bubbles out."""
    async def _boom(*_a, **_kw):
        raise RuntimeError("simulated_adapter_outage_p18")
    with patch("services.sms.rc_adapter.send",
                 AsyncMock(side_effect=_boom)), \
         patch("services.email.resend_adapter.send",
                 AsyncMock(side_effect=_boom)):
        # Invoke each background-task callable directly.
        asyncio.get_event_loop().run_until_complete(_send_lead_alert_sms(
            to="+16028874400", body="body", tenant_id="t", lead_id="l",
        ))
        asyncio.get_event_loop().run_until_complete(_send_lead_alert_email(
            to="brian@plofv.com", subject="s", html="<b>h</b>",
            tenant_id="t", lead_id="l",
        ))


# ── 7. SMS body template — skips empty fields + truncates message ──
def test_sms_body_skips_missing_fields_and_truncates_message():
    lead = {
        "id": "lead-x", "name": "Trunc",
        "phone": "", "email": "",
        "service_address": "789 Long Rd",
        "service_interest": None,
        "message": "x" * 120,
    }
    body = build_sms_body(lead=lead, app_url="https://app.plofv.com")
    assert "New lead — Trunc" in body
    # Empty phone + email lines skipped.
    assert "📞" not in body
    assert "✉️" not in body
    # Non-empty address line rendered.
    assert "🏠 789 Long Rd" in body
    # Message truncated at 80 chars + "..." suffix.
    assert '"' + "x" * 80 + "...\"" in body
    # CTA link present.
    assert body.rstrip().endswith("https://app.plofv.com/leads/lead-x")


# ── 8. Email HTML template — full message + CTA ─────────────────
def test_email_html_includes_full_message_and_cta_button():
    long_msg = "please respond " * 30  # 450 chars — must NOT truncate
    lead = {
        "id": "lead-y", "name": "Full",
        "email": "e@x.com", "phone": "+15559999999",
        "message": long_msg,
    }
    html = build_email_html(lead=lead, app_url="https://app.plofv.com")
    # Full untruncated message present.
    assert long_msg.strip() in html
    # CTA button links to /leads/{id}.
    assert "https://app.plofv.com/leads/lead-y" in html
    assert "View lead in admin" in html
