"""Feb 2026 · Slice N — Resend adapter unit tests.

Coverage:
* Enabled/disabled paths (mocked mode when no API key).
* Suppression pre-check runs BEFORE the Resend call.
* Category=``transactional`` bypasses suppression.
* Retry on 429/5xx with success on attempt 3.
* Retry exhaustion → status=failed, attempts=3.
* Permanent 4xx error → no retry.
* Idempotency-Key header is forwarded to Resend.
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
    sys.modules.pop("services.email.resend_adapter", None)
    from services.email import resend_adapter as ra
    return ra


class _MockResendError(Exception):
    def __init__(self, status_code, message="mock"):
        super().__init__(message)
        self.status_code = status_code


def _install_mock_resend(monkeypatch, send_impl):
    fake = types.ModuleType("resend")
    fake.api_key = None

    class _Emails:
        @staticmethod
        def send(params):
            return send_impl(params)

    fake.Emails = _Emails
    monkeypatch.setitem(sys.modules, "resend", fake)


# ── Baseline paths ─────────────────────────────────────────────────
def test_disabled_returns_mocked_status(monkeypatch):
    ra = _load_adapter(monkeypatch, RESEND_API_KEY="")
    adapter = ra.ResendEmailAdapter()
    assert adapter.enabled is False
    res = _run(adapter.send(to="a@b.com", subject="s", html="h"))
    assert res["provider"] == "mock"
    assert res["provider_status"] == "mocked"
    assert res["attempts"] == 0
    assert res["provider_response_id"] is None


def test_placeholder_key_treated_as_disabled(monkeypatch):
    ra = _load_adapter(monkeypatch, RESEND_API_KEY="re_placeholder_dev")
    adapter = ra.ResendEmailAdapter()
    assert adapter.enabled is False


def test_empty_recipient_fails_fast(monkeypatch):
    ra = _load_adapter(monkeypatch, RESEND_API_KEY="re_test_ok")
    adapter = ra.ResendEmailAdapter()
    res = _run(adapter.send(to="   ", subject="s", html="h"))
    assert res["provider_status"] == "failed"
    assert "empty recipient" in (res["error"] or "")


# ── Suppression ────────────────────────────────────────────────────
def test_suppression_pre_check_blocks_send(monkeypatch):
    ra = _load_adapter(monkeypatch, RESEND_API_KEY="re_test_ok")
    call_count = {"n": 0}

    def _send_impl(_params):
        call_count["n"] += 1
        return {"id": "should-not-happen"}
    _install_mock_resend(monkeypatch, _send_impl)

    async def _fake_is_suppressed(*args, **kwargs):
        return True

    import routers.marketing_preferences as prefs
    monkeypatch.setattr(prefs, "is_suppressed", _fake_is_suppressed)

    adapter = ra.ResendEmailAdapter()
    res = _run(adapter.send(
        to="opted-out@example.com", subject="Hi", html="<p>Hi</p>",
        category="marketing", tenant_id="tenant-1",
    ))
    assert res["provider_status"] == "suppressed"
    assert call_count["n"] == 0


def test_transactional_bypasses_suppression(monkeypatch):
    ra = _load_adapter(monkeypatch, RESEND_API_KEY="re_test_ok")
    call_count = {"n": 0}

    def _send_impl(params):
        call_count["n"] += 1
        return {"id": "abc"}
    _install_mock_resend(monkeypatch, _send_impl)

    async def _fake_is_suppressed(*args, **kwargs):
        raise AssertionError("suppression must be bypassed for transactional")

    import routers.marketing_preferences as prefs
    monkeypatch.setattr(prefs, "is_suppressed", _fake_is_suppressed)

    adapter = ra.ResendEmailAdapter()
    res = _run(adapter.send(
        to="anyone@example.com", subject="Invoice",
        html="<p>Invoice</p>", category="transactional",
        tenant_id="tenant-1",
    ))
    assert res["provider_status"] == "sent"
    assert call_count["n"] == 1


# ── Retry logic ────────────────────────────────────────────────────
def test_retry_succeeds_on_third_attempt(monkeypatch):
    ra = _load_adapter(monkeypatch, RESEND_API_KEY="re_test_ok")

    async def _noop_sleep(_):
        return None
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)
    attempts = {"n": 0}

    def _send_impl(_params):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise _MockResendError(429, "rate limited")
        return {"id": "final-ok"}
    _install_mock_resend(monkeypatch, _send_impl)

    adapter = ra.ResendEmailAdapter()
    res = _run(adapter.send(
        to="ok@example.com", subject="s", html="h",
        category="marketing", tenant_id=None,
    ))
    assert res["provider_status"] == "sent"
    assert res["attempts"] == 3
    assert res["provider_response_id"] == "final-ok"


def test_retry_gives_up_after_three(monkeypatch):
    ra = _load_adapter(monkeypatch, RESEND_API_KEY="re_test_ok")

    async def _noop_sleep(_):
        return None
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)
    attempts = {"n": 0}

    def _send_impl(_params):
        attempts["n"] += 1
        raise _MockResendError(503, "svc unavail")
    _install_mock_resend(monkeypatch, _send_impl)

    adapter = ra.ResendEmailAdapter()
    res = _run(adapter.send(
        to="ok@example.com", subject="s", html="h",
        category="marketing", tenant_id=None,
    ))
    assert res["provider_status"] == "failed"
    assert res["attempts"] == 3
    assert attempts["n"] == 3


def test_permanent_4xx_no_retry(monkeypatch):
    ra = _load_adapter(monkeypatch, RESEND_API_KEY="re_test_ok")
    attempts = {"n": 0}

    def _send_impl(_params):
        attempts["n"] += 1
        raise _MockResendError(400, "domain not verified")
    _install_mock_resend(monkeypatch, _send_impl)

    adapter = ra.ResendEmailAdapter()
    res = _run(adapter.send(
        to="ok@example.com", subject="s", html="h",
        category="marketing", tenant_id=None,
    ))
    assert res["provider_status"] == "failed"
    assert attempts["n"] == 1


# ── Header forwarding ──────────────────────────────────────────────
def test_idempotency_key_forwarded(monkeypatch):
    ra = _load_adapter(
        monkeypatch,
        RESEND_API_KEY="re_test_ok",
        RESEND_FROM_ADDRESS="cs@plofv.com",
        RESEND_FROM_NAME="Pool & Landscaping of Vistancia",
    )
    seen = {}

    def _send_impl(params):
        seen.update(params)
        return {"id": "ok"}
    _install_mock_resend(monkeypatch, _send_impl)

    adapter = ra.ResendEmailAdapter()
    _run(adapter.send(
        to="k@example.com", subject="s", html="h",
        category="transactional", idempotency_key="drip:xyz",
    ))
    assert seen["headers"]["Idempotency-Key"] == "drip:xyz"
    assert seen["from"] == "Pool & Landscaping of Vistancia <cs@plofv.com>"
