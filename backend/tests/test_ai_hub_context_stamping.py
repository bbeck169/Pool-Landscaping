"""AIHUB-A · Feb-2026 — context-stamping tests (SAFE-SEND-A hook).

Locks the fail-safe default: every unauthorized employee (i.e.
every employee at migration time, since ``default=False``) is
forced to ``CommsContext.AGENT`` — even when the caller passes
``CommsContext.SYSTEM``.

Also asserts:

* Authorized employees preserve caller's requested context.
* Authorized employee + ``None`` → SYSTEM (default production).
* Missing employee → AGENT (fail-safe unknown employee).
* Downgrade path logs a WARN with the attempted context.

The final test is an INTEGRATION assertion against
``comms_email_adapter.send_email`` — an AI-driven send stamped
via ``stamp_agent_context`` for an unauthorized employee must
land in the admin's ``business_card.email`` inbox, not the
customer's.
"""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

from services.ai_hub.context_stamping import stamp_agent_context
from services.comms_env_guard import CommsContext


# ═══════════════════════════════════════════════════════════════════
# Fail-safe default — unauthorized forces AGENT
# ═══════════════════════════════════════════════════════════════════
def test_unauthorized_employee_forces_agent_even_when_caller_asks_system():
    emp = {"id": "e-1", "key": "nova",
             "authorized_for_public_use": False}
    ctx = stamp_agent_context(
        employee=emp, requested_context=CommsContext.SYSTEM,
    )
    assert ctx == CommsContext.AGENT


def test_unauthorized_employee_forces_agent_when_caller_passes_none():
    emp = {"id": "e-1", "key": "nova",
             "authorized_for_public_use": False}
    ctx = stamp_agent_context(employee=emp, requested_context=None)
    assert ctx == CommsContext.AGENT


def test_unauthorized_employee_preserves_agent_when_caller_asks_agent():
    """Idempotent — asking for AGENT still gets AGENT."""
    emp = {"id": "e-1", "key": "nova",
             "authorized_for_public_use": False}
    ctx = stamp_agent_context(
        employee=emp, requested_context=CommsContext.AGENT,
    )
    assert ctx == CommsContext.AGENT


# ═══════════════════════════════════════════════════════════════════
# Authorized path — caller intent honoured
# ═══════════════════════════════════════════════════════════════════
def test_authorized_employee_preserves_system():
    emp = {"id": "e-2", "key": "pulse",
             "authorized_for_public_use": True}
    ctx = stamp_agent_context(
        employee=emp, requested_context=CommsContext.SYSTEM,
    )
    assert ctx == CommsContext.SYSTEM


def test_authorized_employee_defaults_to_system_when_none():
    emp = {"id": "e-2", "key": "pulse",
             "authorized_for_public_use": True}
    ctx = stamp_agent_context(employee=emp, requested_context=None)
    assert ctx == CommsContext.SYSTEM


def test_authorized_employee_can_still_stamp_test():
    """An admin-driven test-fire against an authorized employee
    still routes as TEST — the authorization only opens SYSTEM."""
    emp = {"id": "e-3", "key": "pulse",
             "authorized_for_public_use": True}
    ctx = stamp_agent_context(
        employee=emp, requested_context=CommsContext.TEST,
    )
    assert ctx == CommsContext.TEST


# ═══════════════════════════════════════════════════════════════════
# Unknown / missing employee → AGENT
# ═══════════════════════════════════════════════════════════════════
def test_missing_employee_forces_agent():
    ctx = stamp_agent_context(
        employee=None, requested_context=CommsContext.SYSTEM,
    )
    assert ctx == CommsContext.AGENT


def test_empty_dict_employee_forces_agent():
    ctx = stamp_agent_context(
        employee={}, requested_context=CommsContext.SYSTEM,
    )
    assert ctx == CommsContext.AGENT


# ═══════════════════════════════════════════════════════════════════
# Downgrade path logs a WARN
# ═══════════════════════════════════════════════════════════════════
def test_context_downgrade_emits_warning_with_attempted(caplog):
    emp = {"id": "e-4", "key": "attrib",
             "authorized_for_public_use": False}
    with caplog.at_level(logging.WARNING, logger="pool_crm"):
        stamp_agent_context(
            employee=emp, requested_context=CommsContext.SYSTEM,
        )
    assert any(
        "ai_hub.context_downgraded" in r.message
        and "attempted=system" in r.message
        for r in caplog.records
    ), f"expected WARN log, got {[r.message for r in caplog.records]}"


def test_no_warn_when_caller_and_effective_both_agent(caplog):
    emp = {"id": "e-5", "key": "attrib",
             "authorized_for_public_use": False}
    with caplog.at_level(logging.WARNING, logger="pool_crm"):
        stamp_agent_context(
            employee=emp, requested_context=CommsContext.AGENT,
        )
    # Not a downgrade — the caller already asked for AGENT.
    for r in caplog.records:
        assert "ai_hub.context_downgraded" not in r.message, (
            f"unexpected downgrade WARN: {r.message}"
        )


# ═══════════════════════════════════════════════════════════════════
# INTEGRATION — unauthorized AI send lands in admin inbox
# ═══════════════════════════════════════════════════════════════════
def _hermetic_email_env(monkeypatch):
    """Stub every gate downstream of the SAFE-SEND branch (mirror
    of the SAFE-SEND-A admin-redirect test harness)."""
    monkeypatch.setattr(
        "services.comms_email_adapter._is_opted_out",
        AsyncMock(return_value=False),
    )
    fake_qh = MagicMock()
    fake_qh.is_within_send_window = AsyncMock(return_value=True)
    fake_qh.defer_send = AsyncMock(return_value="deferred-id")
    fake_qh_ctx = MagicMock()
    fake_qh_ctx.is_bypassing = MagicMock(return_value=True)
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "services.quiet_hours", fake_qh)
    monkeypatch.setitem(
        _sys.modules, "services.quiet_hours_context", fake_qh_ctx,
    )
    fake_byo = MagicMock()
    fake_byo.try_dispatch_email_tenant_byo = AsyncMock(return_value=None)
    monkeypatch.setitem(
        _sys.modules, "services.messaging.byo_passthrough", fake_byo,
    )
    fake_tm = MagicMock()
    fake_tm.is_messaging_testmode = MagicMock(return_value=False)
    monkeypatch.setitem(
        _sys.modules, "services.messaging.testmode", fake_tm,
    )
    fake_gate = MagicMock()
    fake_gate.is_comm_allowed = AsyncMock(return_value=True)
    monkeypatch.setitem(
        _sys.modules, "services.comms.gate", fake_gate,
    )
    fake_resend = MagicMock()
    fake_resend.Emails = MagicMock()
    fake_resend.Emails.send = MagicMock(return_value={"id": "resend-xyz"})
    monkeypatch.setitem(_sys.modules, "resend", fake_resend)
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    captured: list = []
    def _capture(_channel, **kwargs):
        captured.append({"channel": _channel, **kwargs})
    monkeypatch.setattr(
        "services.comms_email_adapter.record_attempt", _capture,
    )
    return captured, fake_resend


def test_ai_send_for_unauthorized_employee_redirects_to_admin(monkeypatch):
    """Full loop:  stamp_agent_context(unauthorized employee) →
    forces AGENT → adapter redirects to business_card.email."""
    from services import comms_email_adapter

    _, fake_resend = _hermetic_email_env(monkeypatch)
    fake_tenants = MagicMock()
    fake_tenants.find_one = AsyncMock(return_value={
        "settings": {"business_card": {"email": "admin@aihub.test"}},
    })
    monkeypatch.setattr(comms_email_adapter, "db", MagicMock(
        tenants=fake_tenants,
    ))

    employee = {
        "id": "emp-nova", "key": "nova",
        "authorized_for_public_use": False,  # ← the gate
    }
    effective_ctx = stamp_agent_context(
        employee=employee, requested_context=CommsContext.SYSTEM,
    )
    assert effective_ctx == CommsContext.AGENT

    result = asyncio.run(comms_email_adapter.send_email(
        tenant_id="tenant-acme",
        to_email="customer@example.com",
        subject="AI-drafted campaign",
        html="<p>weekly digest</p>",
        context=effective_ctx,
    ))
    assert result["status"] == "sent"
    payload = fake_resend.Emails.send.call_args[0][0]
    # Redirected to admin inbox, subject stamped with [MARCO TEST].
    assert payload["to"] == ["admin@aihub.test"]
    assert payload["subject"].startswith("[MARCO TEST]")


def test_ai_send_for_authorized_employee_reaches_real_customer(monkeypatch):
    """Once admin authorizes the employee, real customer sends
    fire without redirect."""
    from services import comms_email_adapter

    _, fake_resend = _hermetic_email_env(monkeypatch)
    fake_tenants = MagicMock()
    fake_tenants.find_one = AsyncMock(return_value={
        "settings": {"business_card": {"email": "admin@aihub.test"}},
    })
    monkeypatch.setattr(comms_email_adapter, "db", MagicMock(
        tenants=fake_tenants,
    ))

    employee = {
        "id": "emp-pulse", "key": "pulse",
        "authorized_for_public_use": True,
    }
    effective_ctx = stamp_agent_context(
        employee=employee, requested_context=CommsContext.SYSTEM,
    )
    assert effective_ctx == CommsContext.SYSTEM

    result = asyncio.run(comms_email_adapter.send_email(
        tenant_id="tenant-acme",
        to_email="customer@example.com",
        subject="Weekly SMS digest",
        html="<p>digest</p>",
        context=effective_ctx,
    ))
    assert result["status"] == "sent"
    payload = fake_resend.Emails.send.call_args[0][0]
    assert payload["to"] == ["customer@example.com"]
    assert not payload["subject"].startswith("[MARCO TEST]")
