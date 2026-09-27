"""SAFE-SEND-A · Feb-2026 — spec-validation scenarios.

The SAFE-SEND-A brief mandates two end-to-end validation cases,
copied verbatim from the dispatch:

1. **Job Completion email with ``context=SYSTEM``** — reaches
   the original customer, subject unchanged.
2. **AI-generated SEO Update email with ``context=AGENT``** —
   redirects to ``business_card.email``, subject prepended with
   ``[MARCO TEST]``.

These are the two "smoke tests" the safety gate must not break —
if either regresses, real customers either miss transactional
mail (case 1) or start receiving AI drafts (case 2).  Both are
P0 for the tenant's outbound reputation.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from services.comms_env_guard import CommsContext


def _hermetic_env(monkeypatch):
    """Stub every gate downstream of the SAFE-SEND branch."""
    monkeypatch.setattr(
        "services.comms_email_adapter._is_opted_out",
        AsyncMock(return_value=False),
    )
    fake_qh = MagicMock()
    fake_qh.is_within_send_window = AsyncMock(return_value=True)
    fake_qh.defer_send = AsyncMock(return_value="deferred-id")
    fake_qh_ctx = MagicMock()
    fake_qh_ctx.is_bypassing = MagicMock(return_value=True)
    monkeypatch.setitem(
        __import__("sys").modules, "services.quiet_hours", fake_qh,
    )
    monkeypatch.setitem(
        __import__("sys").modules, "services.quiet_hours_context",
        fake_qh_ctx,
    )
    fake_byo = MagicMock()
    fake_byo.try_dispatch_email_tenant_byo = AsyncMock(return_value=None)
    monkeypatch.setitem(
        __import__("sys").modules, "services.messaging.byo_passthrough",
        fake_byo,
    )
    fake_tm = MagicMock()
    fake_tm.is_messaging_testmode = MagicMock(return_value=False)
    monkeypatch.setitem(
        __import__("sys").modules, "services.messaging.testmode", fake_tm,
    )
    fake_gate = MagicMock()
    fake_gate.is_comm_allowed = AsyncMock(return_value=True)
    monkeypatch.setitem(
        __import__("sys").modules, "services.comms.gate", fake_gate,
    )
    fake_resend = MagicMock()
    fake_resend.Emails = MagicMock()
    fake_resend.Emails.send = MagicMock(return_value={"id": "resend-xyz"})
    monkeypatch.setitem(
        __import__("sys").modules, "resend", fake_resend,
    )
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    _captured: list[dict] = []
    def _capture(_channel, **kwargs):
        _captured.append({"channel": _channel, **kwargs})
    monkeypatch.setattr(
        "services.comms_email_adapter.record_attempt", _capture,
    )
    return _captured, fake_resend


# ═══════════════════════════════════════════════════════════════════
# Spec case 1 — Job Completion + SYSTEM → customer.
# ═══════════════════════════════════════════════════════════════════
def test_job_completion_system_reaches_customer_subject_unchanged(monkeypatch):
    """Real transactional flow: nightly Job Completion emailer
    stamps ``CommsContext.SYSTEM``.  The customer must actually
    receive the email; the subject must be verbatim from the
    template — no ``[MARCO TEST]`` prefix leaking to prod."""
    from services import comms_email_adapter

    _, fake_resend = _hermetic_env(monkeypatch)
    fake_tenants = MagicMock()
    # business_card exists on the tenant, but SYSTEM must ignore it.
    fake_tenants.find_one = AsyncMock(return_value={
        "settings": {"business_card": {"email": "admin@acmepools.com"}},
    })
    monkeypatch.setattr(comms_email_adapter, "db", MagicMock(
        tenants=fake_tenants,
    ))

    subject_verbatim = "Your Pool Service is Complete · Jan 30 · Acme Pools"
    result = asyncio.run(comms_email_adapter.send_email(
        tenant_id="tenant-acme",
        to_email="jane.customer@example.com",
        subject=subject_verbatim,
        html="<p>Details of your visit ...</p>",
        context=CommsContext.SYSTEM,
    ))

    assert result["status"] == "sent"
    payload = fake_resend.Emails.send.call_args[0][0]
    # (a) Customer received it, not the admin business_card.
    assert payload["to"] == ["jane.customer@example.com"]
    # (b) Subject unchanged — verbatim from the template.
    assert payload["subject"] == subject_verbatim
    assert "MARCO TEST" not in payload["subject"]
    # (c) No safe-send headers on the passthrough path.
    headers = payload.get("headers") or {}
    assert "X-MARCO-Original-To" not in headers
    assert "X-MARCO-Safe-Send-Context" not in headers


# ═══════════════════════════════════════════════════════════════════
# Spec case 2 — SEO Update + AGENT → business_card.email + prefix.
# ═══════════════════════════════════════════════════════════════════
def test_seo_update_agent_redirects_and_prepends_marco_test(monkeypatch):
    """The AI-authored SEO weekly digest stamps ``CommsContext.AGENT``.
    The customer must NEVER receive it — it goes to
    ``business_card.email``.  Subject gets ``[MARCO TEST]`` prepended
    so the admin's inbox rules can route it to a review folder."""
    from services import comms_email_adapter

    _, fake_resend = _hermetic_env(monkeypatch)
    fake_tenants = MagicMock()
    fake_tenants.find_one = AsyncMock(return_value={
        "settings": {"business_card": {"email": "admin@acmepools.com"}},
    })
    monkeypatch.setattr(comms_email_adapter, "db", MagicMock(
        tenants=fake_tenants,
    ))

    original_subject = "SEO Update · Week of Feb 10 · 12 keywords moving"
    result = asyncio.run(comms_email_adapter.send_email(
        tenant_id="tenant-acme",
        to_email="jane.customer@example.com",  # would-be recipient
        subject=original_subject,
        html="<p>Your ranks this week ...</p>",
        context=CommsContext.AGENT,
    ))

    assert result["status"] == "sent"
    payload = fake_resend.Emails.send.call_args[0][0]
    # (a) Redirected to admin business_card, NOT the customer.
    assert payload["to"] == ["admin@acmepools.com"]
    # (b) Subject prepended with the [MARCO TEST] tag.
    assert payload["subject"].startswith("[MARCO TEST] ")
    assert original_subject in payload["subject"]
    # (c) Header trail preserves the intended recipient + context
    #     stamp so the admin's inbox knows this is a redirect.
    headers = payload.get("headers") or {}
    assert headers.get("X-MARCO-Original-To") == "jane.customer@example.com"
    assert headers.get("X-MARCO-Safe-Send-Context") == "agent"
