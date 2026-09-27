"""SAFE-SEND-A · Feb-2026 — admin-redirect behaviour.

Directly exercises the three primitives that ``send_email`` /
``send_sms`` rely on:

* ``should_redirect_to_admin(context)`` — AGENT + TEST → True,
  SYSTEM → False.
* ``get_redirect_targets(tenant_settings, ...)`` — reads
  ``business_card.email`` / ``business_card.phone`` verbatim,
  falls back to the first admin user in ``users``, and raises
  ``RedirectTargetMissing`` when neither is available.

Also runs an end-to-end pass through
``comms_email_adapter.send_email`` with:

* ``CommsContext.SYSTEM`` → real recipient, subject unchanged.
* ``CommsContext.AGENT``  → business_card.email, subject prefixed
                            with ``[MARCO TEST]``.
* ``CommsContext.AGENT`` + missing business_card + missing admin
  user → returns ``status=skipped_no_redirect_target`` (never
  falls through to the customer).

Uses ``unittest.mock`` to stub the Motor / Resend call so the
test stays fast + hermetic.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.comms_env_guard import (
    CommsContext, RedirectTargetMissing,
    get_redirect_targets, should_redirect_to_admin,
)


# ═══════════════════════════════════════════════════════════════════
# Unit — ``should_redirect_to_admin``.
# ═══════════════════════════════════════════════════════════════════
def test_should_redirect_agent():
    assert should_redirect_to_admin(CommsContext.AGENT) is True


def test_should_redirect_test():
    assert should_redirect_to_admin(CommsContext.TEST) is True


def test_should_redirect_system_passthrough():
    assert should_redirect_to_admin(CommsContext.SYSTEM) is False


# ═══════════════════════════════════════════════════════════════════
# Unit — ``get_redirect_targets``.
# ═══════════════════════════════════════════════════════════════════
def test_get_redirect_targets_from_business_card_email():
    settings = {"business_card": {"email": "admin@acme.com",
                                   "phone": "+16025551234"}}
    targets = asyncio.run(get_redirect_targets(
        tenant_settings=settings, tenant_id="t1", channel="email", db=None,
    ))
    assert targets.email == "admin@acme.com"
    assert targets.phone == "+16025551234"


def test_get_redirect_targets_from_business_card_phone():
    settings = {"business_card": {"email": "admin@acme.com",
                                   "phone": "+16025551234"}}
    targets = asyncio.run(get_redirect_targets(
        tenant_settings=settings, tenant_id="t1", channel="sms", db=None,
    ))
    assert targets.phone == "+16025551234"


def test_get_redirect_targets_falls_back_to_admin_user():
    """No business_card — fall back to first admin user."""
    fake_db = MagicMock()
    fake_db.users.find_one = AsyncMock(return_value={
        "email": "adminfallback@acme.com",
    })
    targets = asyncio.run(get_redirect_targets(
        tenant_settings={}, tenant_id="t1", channel="email", db=fake_db,
    ))
    assert targets.email == "adminfallback@acme.com"


def test_get_redirect_targets_raises_missing_when_no_source():
    fake_db = MagicMock()
    fake_db.users.find_one = AsyncMock(return_value=None)
    with pytest.raises(RedirectTargetMissing):
        asyncio.run(get_redirect_targets(
            tenant_settings={}, tenant_id="t1", channel="email", db=fake_db,
        ))


def test_get_redirect_targets_rejects_unknown_channel():
    with pytest.raises(ValueError):
        asyncio.run(get_redirect_targets(
            tenant_settings={"business_card": {"email": "a@b.com"}},
            tenant_id="t1", channel="pigeon", db=None,
        ))


# ═══════════════════════════════════════════════════════════════════
# Integration — ``send_email`` end-to-end with adapters stubbed.
# ═══════════════════════════════════════════════════════════════════
# The email adapter has ~7 downstream gates (opt-out, quiet-hours,
# BYO, testmode, resend-gate, resend SDK, audit).  We monkey-patch
# each so the test stays hermetic and only the SAFE-SEND branch
# actually runs.
def _hermetic_email_env(monkeypatch):
    """Patch every downstream gate to a no-op so we only exercise
    the SAFE-SEND redirect + subject-prepend logic."""
    # Opt-out check → always false.
    monkeypatch.setattr(
        "services.comms_email_adapter._is_opted_out",
        AsyncMock(return_value=False),
    )
    # Quiet hours → import path lookup returns modules with no-op
    # guards.
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
    # BYO passthrough → None (no tenant provider configured).
    fake_byo = MagicMock()
    fake_byo.try_dispatch_email_tenant_byo = AsyncMock(return_value=None)
    monkeypatch.setitem(
        __import__("sys").modules, "services.messaging.byo_passthrough",
        fake_byo,
    )
    # Testmode → not testmode.
    fake_tm = MagicMock()
    fake_tm.is_messaging_testmode = MagicMock(return_value=False)
    fake_tm.mock_email_envelope = MagicMock(return_value={"status": "mocked"})
    monkeypatch.setitem(
        __import__("sys").modules, "services.messaging.testmode", fake_tm,
    )
    # Comms whitelist gate → allow every send in test.
    fake_gate = MagicMock()
    fake_gate.is_comm_allowed = AsyncMock(return_value=True)
    monkeypatch.setitem(
        __import__("sys").modules, "services.comms.gate", fake_gate,
    )
    # Resend SDK → deterministic id, no HTTP.
    fake_resend = MagicMock()
    fake_resend.Emails = MagicMock()
    fake_resend.Emails.send = MagicMock(return_value={"id": "resend-xyz"})
    monkeypatch.setitem(
        __import__("sys").modules, "resend", fake_resend,
    )
    # Provider key must be present so the missing-key gate doesn't
    # short-circuit.
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    # record_attempt → capture calls, don't actually persist.
    _captured: list[dict] = []
    def _capture(_channel, **kwargs):
        _captured.append({"channel": _channel, **kwargs})
    monkeypatch.setattr(
        "services.comms_email_adapter.record_attempt", _capture,
    )
    return _captured, fake_resend


def test_send_email_system_passes_through(monkeypatch):
    """SYSTEM sends the email to the real recipient, no
    ``[MARCO TEST]`` subject prefix, no redirect header."""
    from services import comms_email_adapter

    captured, fake_resend = _hermetic_email_env(monkeypatch)
    # tenants collection lookup — no business_card, but SYSTEM
    # doesn't redirect so it never hits the redirect resolver.
    fake_tenants = MagicMock()
    fake_tenants.find_one = AsyncMock(return_value=None)
    monkeypatch.setattr(comms_email_adapter, "db", MagicMock(
        tenants=fake_tenants,
    ))

    result = asyncio.run(comms_email_adapter.send_email(
        tenant_id="t1",
        to_email="customer@example.com",
        subject="Your pool service is complete",
        html="<p>done</p>",
        context=CommsContext.SYSTEM,
    ))

    assert result["status"] == "sent"
    # Real recipient, subject unchanged.
    payload = fake_resend.Emails.send.call_args[0][0]
    assert payload["to"] == ["customer@example.com"]
    assert payload["subject"] == "Your pool service is complete"
    assert "MARCO TEST" not in payload["subject"]
    # Audit row: not redirected, intended == actual, context=system.
    assert captured, "record_attempt was never invoked"
    row = captured[-1]
    assert row["context"] == "system"
    assert row["intended_recipient"] == "customer@example.com"
    assert row["redirected"] is False


def test_send_email_agent_redirects_to_business_card(monkeypatch):
    """AGENT redirects to ``business_card.email`` and prepends
    ``[MARCO TEST]`` to the subject."""
    from services import comms_email_adapter

    captured, fake_resend = _hermetic_email_env(monkeypatch)
    # tenants.find_one → returns a business_card
    fake_tenants = MagicMock()
    fake_tenants.find_one = AsyncMock(return_value={
        "settings": {"business_card": {"email": "admin@acmepools.com"}},
    })
    monkeypatch.setattr(comms_email_adapter, "db", MagicMock(
        tenants=fake_tenants,
    ))

    result = asyncio.run(comms_email_adapter.send_email(
        tenant_id="t1",
        to_email="customer@example.com",
        subject="AI-drafted: SEO Update",
        html="<p>Weekly SEO snapshot</p>",
        context=CommsContext.AGENT,
    ))

    assert result["status"] == "sent"
    payload = fake_resend.Emails.send.call_args[0][0]
    assert payload["to"] == ["admin@acmepools.com"]
    assert payload["subject"].startswith("[MARCO TEST]")
    # X-MARCO-Original-To header preserves the intended recipient.
    assert payload.get("headers", {}).get("X-MARCO-Original-To") == \
        "customer@example.com"
    assert payload.get("headers", {}).get("X-MARCO-Safe-Send-Context") == \
        "agent"
    # Audit row: redirected, intended != actual, context=agent.
    row = captured[-1]
    assert row["context"] == "agent"
    assert row["intended_recipient"] == "customer@example.com"
    assert row["redirected"] is True


def test_send_email_agent_skips_when_no_redirect_target(monkeypatch):
    """AGENT + missing business_card + missing admin user →
    returns ``status=skipped_no_redirect_target``.  NEVER falls
    through to customer."""
    from services import comms_email_adapter

    captured, fake_resend = _hermetic_email_env(monkeypatch)
    fake_users = MagicMock()
    fake_users.find_one = AsyncMock(return_value=None)
    fake_tenants = MagicMock()
    fake_tenants.find_one = AsyncMock(return_value={"settings": {}})
    monkeypatch.setattr(comms_email_adapter, "db", MagicMock(
        tenants=fake_tenants, users=fake_users,
    ))

    result = asyncio.run(comms_email_adapter.send_email(
        tenant_id="t1",
        to_email="customer@example.com",
        subject="AI-drafted note",
        html="<p>hi</p>",
        context=CommsContext.AGENT,
    ))

    assert result["status"] == "skipped_no_redirect_target"
    assert result["safe_send_context"] == "agent"
    assert result["original_to"] == "customer@example.com"
    # Never called Resend.
    assert not fake_resend.Emails.send.called
