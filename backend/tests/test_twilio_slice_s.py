"""Feb 2026 · Slice S — Twilio SMS adapter unit tests.

Coverage:
* Phone E.164 normalization across common human formats.
* Adapter enabled/disabled paths.
* Suppression pre-check runs BEFORE Twilio call; transactional bypass.
* Retry on 429/5xx with success on attempt 3; exhaustion → failed.
* Permanent 400 (bad phone / permanent) → no retry.
* STOP suffix auto-appended on marketing/drip categories; NOT on transactional.
* STOP suffix skipped when body already contains 'stop'.
"""
from __future__ import annotations

import asyncio
import os
import sys
import types

import pytest

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _load_adapter(monkeypatch, **env):
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    sys.modules.pop("services.sms.twilio_adapter", None)
    from services.sms import twilio_adapter as ta
    return ta


class _MockTwilioException(Exception):
    def __init__(self, status, msg="mock", code=None):
        super().__init__(msg)
        self.status = status
        self.code = code


def _install_mock_twilio(monkeypatch, create_impl):
    fake_rest = types.ModuleType("twilio.rest")

    class _Client:
        def __init__(self, *args, **kwargs):
            self.messages = types.SimpleNamespace(create=create_impl)

    fake_rest.Client = _Client
    fake_pkg = types.ModuleType("twilio")
    fake_pkg.rest = fake_rest
    monkeypatch.setitem(sys.modules, "twilio", fake_pkg)
    monkeypatch.setitem(sys.modules, "twilio.rest", fake_rest)


# ── Phone normalisation ────────────────────────────────────────────
def test_normalize_common_formats(monkeypatch):
    ta = _load_adapter(monkeypatch)
    for raw in ("(623) 887-8060", "623.887.8060", "623-887-8060",
                "+16238878060", "16238878060", "6238878060"):
        assert ta.normalize_phone_e164(raw) == "+16238878060", raw


def test_normalize_rejects_short_numbers(monkeypatch):
    ta = _load_adapter(monkeypatch)
    assert ta.normalize_phone_e164("12345") is None
    assert ta.normalize_phone_e164("") is None
    assert ta.normalize_phone_e164(None) is None


# ── Enabled / disabled paths ───────────────────────────────────────
def test_disabled_returns_mocked(monkeypatch):
    ta = _load_adapter(
        monkeypatch,
        TWILIO_ACCOUNT_SID="",
        TWILIO_API_KEY_SID="", TWILIO_API_KEY_SECRET="",
        TWILIO_AUTH_TOKEN="", TWILIO_FROM_NUMBER="",
    )
    adapter = ta.TwilioSMSAdapter()
    assert adapter.enabled is False
    res = _run(adapter.send(to="6238878060", body="hi"))
    assert res["provider"] == "mock"
    assert res["provider_status"] == "mocked"


def test_invalid_phone_fails_fast(monkeypatch):
    ta = _load_adapter(
        monkeypatch,
        TWILIO_ACCOUNT_SID="ACtest", TWILIO_API_KEY_SID="SKtest",
        TWILIO_API_KEY_SECRET="secret", TWILIO_FROM_NUMBER="+16238878060",
    )
    adapter = ta.TwilioSMSAdapter()
    res = _run(adapter.send(to="12345", body="hi"))
    assert res["provider_status"] == "failed"
    assert res["error"] == "invalid_phone"


# ── Suppression ────────────────────────────────────────────────────
def test_suppression_blocks_send(monkeypatch):
    ta = _load_adapter(
        monkeypatch,
        TWILIO_ACCOUNT_SID="ACtest", TWILIO_API_KEY_SID="SKtest",
        TWILIO_API_KEY_SECRET="secret", TWILIO_FROM_NUMBER="+16238878060",
    )
    calls = {"n": 0}

    def _create(**kwargs):
        calls["n"] += 1
        return types.SimpleNamespace(sid="SM1")
    _install_mock_twilio(monkeypatch, _create)

    async def _fake_is_suppressed(*args, **kwargs):
        return True
    import routers.marketing_preferences as prefs
    monkeypatch.setattr(prefs, "is_suppressed", _fake_is_suppressed)

    adapter = ta.TwilioSMSAdapter()
    res = _run(adapter.send(
        to="6238878060", body="marketing blast",
        category="marketing", tenant_id="tenant-1",
    ))
    assert res["provider_status"] == "suppressed"
    assert calls["n"] == 0


def test_transactional_bypasses_suppression(monkeypatch):
    ta = _load_adapter(
        monkeypatch,
        TWILIO_ACCOUNT_SID="ACtest", TWILIO_API_KEY_SID="SKtest",
        TWILIO_API_KEY_SECRET="secret", TWILIO_FROM_NUMBER="+16238878060",
    )
    calls = {"n": 0}

    def _create(**kwargs):
        calls["n"] += 1
        return types.SimpleNamespace(sid="SM_TX")
    _install_mock_twilio(monkeypatch, _create)

    async def _fake_is_suppressed(*args, **kwargs):
        raise AssertionError("suppression must be bypassed for transactional")
    import routers.marketing_preferences as prefs
    monkeypatch.setattr(prefs, "is_suppressed", _fake_is_suppressed)

    adapter = ta.TwilioSMSAdapter()
    res = _run(adapter.send(
        to="6238878060", body="Your appt is confirmed.",
        category="transactional", tenant_id="tenant-1",
    ))
    assert res["provider_status"] == "sent"
    assert res["provider_response_id"] == "SM_TX"
    assert calls["n"] == 1


# ── Retry ──────────────────────────────────────────────────────────
def test_retry_succeeds_on_third_attempt(monkeypatch):
    ta = _load_adapter(
        monkeypatch,
        TWILIO_ACCOUNT_SID="ACtest", TWILIO_API_KEY_SID="SKtest",
        TWILIO_API_KEY_SECRET="secret", TWILIO_FROM_NUMBER="+16238878060",
    )

    async def _noop_sleep(_):
        return None
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)

    attempts = {"n": 0}

    def _create(**kwargs):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise _MockTwilioException(429, "rate limited")
        return types.SimpleNamespace(sid="SM_FINAL")
    _install_mock_twilio(monkeypatch, _create)

    adapter = ta.TwilioSMSAdapter()
    res = _run(adapter.send(
        to="6238878060", body="hi", category="marketing", tenant_id=None,
    ))
    assert res["provider_status"] == "sent"
    assert res["attempts"] == 3
    assert res["provider_response_id"] == "SM_FINAL"


def test_retry_exhaustion(monkeypatch):
    ta = _load_adapter(
        monkeypatch,
        TWILIO_ACCOUNT_SID="ACtest", TWILIO_API_KEY_SID="SKtest",
        TWILIO_API_KEY_SECRET="secret", TWILIO_FROM_NUMBER="+16238878060",
    )

    async def _noop_sleep(_):
        return None
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)

    attempts = {"n": 0}

    def _create(**kwargs):
        attempts["n"] += 1
        raise _MockTwilioException(503, "svc unavail")
    _install_mock_twilio(monkeypatch, _create)

    adapter = ta.TwilioSMSAdapter()
    res = _run(adapter.send(
        to="6238878060", body="hi", category="marketing", tenant_id=None,
    ))
    assert res["provider_status"] == "failed"
    assert res["attempts"] == 3
    assert attempts["n"] == 3


def test_permanent_4xx_no_retry(monkeypatch):
    ta = _load_adapter(
        monkeypatch,
        TWILIO_ACCOUNT_SID="ACtest", TWILIO_API_KEY_SID="SKtest",
        TWILIO_API_KEY_SECRET="secret", TWILIO_FROM_NUMBER="+16238878060",
    )
    attempts = {"n": 0}

    def _create(**kwargs):
        attempts["n"] += 1
        raise _MockTwilioException(400, "not a mobile", code=21610)
    _install_mock_twilio(monkeypatch, _create)

    adapter = ta.TwilioSMSAdapter()
    res = _run(adapter.send(
        to="6238878060", body="hi", category="marketing", tenant_id=None,
    ))
    assert res["provider_status"] == "failed"
    assert attempts["n"] == 1


# ── STOP suffix compliance ─────────────────────────────────────────
def test_stop_suffix_marketing(monkeypatch):
    ta = _load_adapter(
        monkeypatch,
        TWILIO_ACCOUNT_SID="ACtest", TWILIO_API_KEY_SID="SKtest",
        TWILIO_API_KEY_SECRET="secret", TWILIO_FROM_NUMBER="+16238878060",
    )
    seen = {}

    def _create(**kwargs):
        seen.update(kwargs)
        return types.SimpleNamespace(sid="SM_MK")
    _install_mock_twilio(monkeypatch, _create)

    adapter = ta.TwilioSMSAdapter()
    _run(adapter.send(
        to="6238878060", body="Big blowout sale!",
        category="marketing", tenant_id=None,
    ))
    assert "Reply STOP to unsubscribe" in seen["body"]


def test_stop_suffix_skipped_for_transactional(monkeypatch):
    ta = _load_adapter(
        monkeypatch,
        TWILIO_ACCOUNT_SID="ACtest", TWILIO_API_KEY_SID="SKtest",
        TWILIO_API_KEY_SECRET="secret", TWILIO_FROM_NUMBER="+16238878060",
    )
    seen = {}

    def _create(**kwargs):
        seen.update(kwargs)
        return types.SimpleNamespace(sid="SM_TX2")
    _install_mock_twilio(monkeypatch, _create)

    adapter = ta.TwilioSMSAdapter()
    _run(adapter.send(
        to="6238878060", body="Your appointment is confirmed.",
        category="transactional", tenant_id=None,
    ))
    assert "STOP" not in seen["body"]


def test_stop_suffix_not_double_appended(monkeypatch):
    """A template that already includes STOP language must NOT get a
    second suffix — case-insensitive detection."""
    ta = _load_adapter(
        monkeypatch,
        TWILIO_ACCOUNT_SID="ACtest", TWILIO_API_KEY_SID="SKtest",
        TWILIO_API_KEY_SECRET="secret", TWILIO_FROM_NUMBER="+16238878060",
    )
    seen = {}

    def _create(**kwargs):
        seen.update(kwargs)
        return types.SimpleNamespace(sid="SM_DUP")
    _install_mock_twilio(monkeypatch, _create)

    adapter = ta.TwilioSMSAdapter()
    body = "Hi — reply STOP to opt out of alerts."
    _run(adapter.send(
        to="6238878060", body=body,
        category="marketing", tenant_id=None,
    ))
    # STOP appears exactly once (from our original template).
    assert seen["body"].lower().count("stop") == 1


def test_body_capped_at_1600(monkeypatch):
    ta = _load_adapter(
        monkeypatch,
        TWILIO_ACCOUNT_SID="ACtest", TWILIO_API_KEY_SID="SKtest",
        TWILIO_API_KEY_SECRET="secret", TWILIO_FROM_NUMBER="+16238878060",
    )
    seen = {}

    def _create(**kwargs):
        seen.update(kwargs)
        return types.SimpleNamespace(sid="SM_CAP")
    _install_mock_twilio(monkeypatch, _create)

    adapter = ta.TwilioSMSAdapter()
    _run(adapter.send(
        to="6238878060", body="x" * 5000,
        category="transactional", tenant_id=None,
    ))
    assert len(seen["body"]) <= 1600
