"""Phase K72 · Feb-2026 — Emergency customer-email kill switch.

Coverage
--------
1. Flag OFF (default) → guard_outbound behaves exactly like before
   (production_live in prod, otherwise env-guard rules).
2. Flag ON + audience="customer" → guard_outbound returns
   ``blocked=True`` with reason
   ``customer_email_suppressed_kill_switch``, REGARDLESS of
   ``APP_ENV`` (including production).
3. Flag ON + audience="internal" → guard_outbound bypasses the
   kill switch and follows normal env-guard rules.
4. Flag ON blocks the resend adapter's ``send()`` even when
   ``allow_off_allowlist=True`` for customer audience (belt-and-
   braces guard against admin-triggered customer-facing sends).
5. Flag ON does not affect internal audience through
   ``allow_off_allowlist=True`` (K30 admin reset path unaffected).
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

_LOOP = asyncio.new_event_loop()


def _run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture(autouse=True)
def _reset_kill_switch_env(monkeypatch):
    monkeypatch.delenv("FEATURE_CUSTOMER_EMAIL_KILL_SWITCH", raising=False)


def test_kill_switch_default_off():
    from services.comms_env_guard import is_customer_email_kill_switch_on
    assert is_customer_email_kill_switch_on() is False


@pytest.mark.parametrize("val", ["on", "ON", "true", "True", "1", "yes"])
def test_kill_switch_truthy_variants(monkeypatch, val):
    monkeypatch.setenv("FEATURE_CUSTOMER_EMAIL_KILL_SWITCH", val)
    from services.comms_env_guard import is_customer_email_kill_switch_on
    assert is_customer_email_kill_switch_on() is True


@pytest.mark.parametrize("val", ["off", "false", "0", "no", "", "bogus"])
def test_kill_switch_falsy_variants(monkeypatch, val):
    monkeypatch.setenv("FEATURE_CUSTOMER_EMAIL_KILL_SWITCH", val)
    from services.comms_env_guard import is_customer_email_kill_switch_on
    assert is_customer_email_kill_switch_on() is False


def test_guard_outbound_flag_off_prod_passes(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    from services.comms_env_guard import guard_outbound
    v = guard_outbound(kind="email", to="customer@example.com")
    assert v.blocked is False
    assert v.reason == "production_live"


def test_guard_outbound_flag_on_customer_blocked_in_prod(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FEATURE_CUSTOMER_EMAIL_KILL_SWITCH", "on")
    from services.comms_env_guard import guard_outbound
    v = guard_outbound(kind="email", to="customer@example.com",
                        audience="customer")
    assert v.blocked is True
    assert v.reason == "customer_email_suppressed_kill_switch"


def test_guard_outbound_flag_on_internal_bypasses_switch(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FEATURE_CUSTOMER_EMAIL_KILL_SWITCH", "on")
    from services.comms_env_guard import guard_outbound
    v = guard_outbound(kind="email", to="admin@example.com",
                        audience="internal")
    assert v.blocked is False
    assert v.reason == "production_live"


def test_guard_outbound_flag_on_sms_customer_blocked(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FEATURE_CUSTOMER_EMAIL_KILL_SWITCH", "on")
    from services.comms_env_guard import guard_outbound
    v = guard_outbound(kind="sms", to="+15551234567",
                        audience="customer")
    assert v.blocked is True
    assert v.reason == "customer_email_suppressed_kill_switch"


def test_guard_outbound_flag_on_preview_customer_still_blocked(monkeypatch):
    """Kill switch fires BEFORE the env allow-list check, so preview
    allow-listed addresses are ALSO suppressed when the switch is
    on."""
    monkeypatch.setenv("APP_ENV", "preview")
    monkeypatch.setenv("FEATURE_CUSTOMER_EMAIL_KILL_SWITCH", "on")
    monkeypatch.setenv(
        "COMMS_TEST_ALLOWLIST_EMAILS", "allowlist@example.com",
    )
    from services.comms_env_guard import guard_outbound
    v = guard_outbound(kind="email", to="allowlist@example.com",
                        audience="customer")
    assert v.blocked is True
    assert v.reason == "customer_email_suppressed_kill_switch"


def test_resend_adapter_blocks_customer_send_with_allow_off_allowlist(
    monkeypatch,
):
    """Even the K30 admin-bypass path is short-circuited when
    ``audience="customer"`` and the kill switch is on. K30 admin
    resets pass ``audience="internal"`` so they stay flowing."""
    monkeypatch.setenv("FEATURE_CUSTOMER_EMAIL_KILL_SWITCH", "on")
    from services.email.resend_adapter import send as _send

    result = _run(_send(
        to="michelle@example.com",
        subject="hi",
        html="<p>hi</p>",
        category="transactional",
        allow_off_allowlist=True,
        audience="customer",
        tenant_id="t-test",
    ))
    assert result.get("provider_status") == "dry_run"
    assert result.get("dry_run_reason") \
        == "customer_email_suppressed_kill_switch"


def test_resend_adapter_admin_internal_bypasses_kill_switch(monkeypatch):
    """audience=internal + allow_off_allowlist=True must not be
    blocked by the kill switch (K30 password-reset path)."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FEATURE_CUSTOMER_EMAIL_KILL_SWITCH", "on")
    from services.email.resend_adapter import send as _send
    # In production APP_ENV with resend api key unset, the adapter
    # would try to call Resend and fail — that's fine, the goal is
    # to prove the kill-switch check DID NOT short-circuit. We
    # verify by patching the low-level resend call.
    import services.email.resend_adapter as _mod
    called = {"n": 0}

    async def _fake_httpx_post(*a, **kw):
        called["n"] += 1
        class R:
            status_code = 200
            def json(self):
                return {"id": "resend_fake"}
        return R()

    monkeypatch.setattr(_mod, "_httpx_post",
                          _fake_httpx_post, raising=False)
    # If the module doesn't expose _httpx_post we just check that
    # the return isn't the K72 dry-run shape.
    result = _run(_send(
        to="admin@example.com",
        subject="admin",
        html="<p>x</p>",
        category="transactional",
        allow_off_allowlist=True,
        audience="internal",
        tenant_id="t-test",
    ))
    assert result.get("dry_run_reason") \
        != "customer_email_suppressed_kill_switch"
