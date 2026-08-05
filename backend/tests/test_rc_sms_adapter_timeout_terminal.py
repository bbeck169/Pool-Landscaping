"""Feb-2026 · Prod 502 hardening — RC SMS adapter timeout terminality.

Mocks the ``RingCentralService.send_sms`` coroutine to raise specific
exceptions, then asserts the adapter's retry loop:

  * ``httpx.TimeoutException`` and ``httpx.ConnectError`` are **terminal**
    — the adapter breaks immediately, no retries, no sleep. Prevents the
    ``3 × 15s = 45s`` hang that trips the edge-gateway 502.
  * ``RingCentralError(429, ...)`` still retries per the existing
    contract — this is the regression guardrail.
  * ``RingCentralError(401, "invalid_client")`` is terminal (4xx-non-429).

Zero live RC / network calls. Zero preview .env touches.
"""
from __future__ import annotations
import asyncio
import time
from unittest.mock import patch, AsyncMock

import httpx
import pytest

from services.sms.rc_adapter import RingCentralSMSAdapter
from services.ringcentral.rc_client import RingCentralError


# Phase 46 · Feb 2026 — Bypass Phase 34 `guard_outbound` for this module.
# Every test in this file monkeypatches `RingCentralService.send_sms`
# to raise a mocked exception, so NO live RC traffic is possible.
# Without this override, `APP_ENV=preview` (the .env default) would
# cause `guard_outbound` to short-circuit the send to a `dry_run`
# envelope BEFORE the mocked `send_sms` is ever called, and every
# retry-loop assertion (calls["n"] == 3, provider_status == "failed",
# etc.) would fail.
@pytest.fixture(autouse=True)
def _phase46_bypass_comms_guard(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")


def _run(coro):
    """Run a coroutine on a fresh event loop (each test isolated)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _adapter():
    """Fresh adapter with the enabled path forced ON (env-agnostic)."""
    a = RingCentralSMSAdapter()
    a.enabled = True
    a.rc_client_id = "TEST_CLIENT_ID"
    a.rc_jwt = "TEST_JWT"
    a.rc_server = "https://platform.ringcentral.com"
    a.default_from = "+15555550100"
    return a


def _stub_no_suppress(monkeypatch):
    """Skip the suppression DB check for these unit tests."""
    async def _fake(*_a, **_kw): return False
    monkeypatch.setattr(RingCentralSMSAdapter, "_suppressed", _fake)
    async def _fake_from(*_a, **_kw): return "+15555550100"
    monkeypatch.setattr(RingCentralSMSAdapter, "_resolve_from", _fake_from)


@pytest.mark.parametrize("exc_cls", [
    httpx.TimeoutException,
    httpx.ConnectError,
])
def test_httpx_transport_errors_are_terminal(monkeypatch, exc_cls):
    """The core fix — a single httpx timeout / connect error must return
    fast without retrying. Locks the anti-hang guarantee."""
    _stub_no_suppress(monkeypatch)
    calls = {"n": 0}

    async def _boom(self, to, body, from_number=None):
        calls["n"] += 1
        raise exc_cls("simulated transport failure")
    monkeypatch.setattr("services.sms.rc_adapter.RingCentralService.send_sms", _boom)
    # Force asyncio.sleep to raise if the adapter tries to back off —
    # nothing should trigger a sleep on the terminal path.
    async def _no_sleep(*_a, **_kw):
        raise AssertionError("adapter slept on a terminal httpx error")
    monkeypatch.setattr("services.sms.rc_adapter.asyncio.sleep", _no_sleep)

    a = _adapter()
    t0 = time.perf_counter()
    res = _run(a.send(to="+15005551212", body="hi", tenant_id="t",
                        category="transactional"))
    elapsed = time.perf_counter() - t0

    assert res["provider_status"] == "failed"
    assert exc_cls.__name__ in res["error"]
    assert calls["n"] == 1, f"expected 1 attempt, got {calls['n']}"
    # And it must have returned quickly (< 1s even in the slowest CI).
    assert elapsed < 1.0, f"terminal path took {elapsed:.2f}s"


def test_generic_exception_still_retries(monkeypatch):
    """Regression — a *non-httpx* generic exception preserves the
    original 3-attempt retry contract."""
    _stub_no_suppress(monkeypatch)
    calls = {"n": 0}

    async def _boom(self, to, body, from_number=None):
        calls["n"] += 1
        raise RuntimeError("something transient we don't classify")
    monkeypatch.setattr("services.sms.rc_adapter.RingCentralService.send_sms", _boom)
    # Zero-cost backoff so the test runs fast but the retry loop still
    # advances through all attempts.
    async def _fake_sleep(*_a, **_kw): pass
    monkeypatch.setattr("services.sms.rc_adapter.asyncio.sleep", _fake_sleep)

    a = _adapter()
    res = _run(a.send(to="+15005551212", body="hi", tenant_id="t",
                        category="transactional"))

    assert res["provider_status"] == "failed"
    assert calls["n"] == 3, (
        f"generic exception must still retry 3× · got {calls['n']}")


def test_ringcentral_429_still_retries(monkeypatch):
    """Regression — RC 429 stays in ``_TRANSIENT_STATUS`` and retries."""
    _stub_no_suppress(monkeypatch)
    calls = {"n": 0}

    async def _boom(self, to, body, from_number=None):
        calls["n"] += 1
        raise RingCentralError(429, "rate limit")
    monkeypatch.setattr("services.sms.rc_adapter.RingCentralService.send_sms", _boom)
    async def _fake_sleep(*_a, **_kw): pass
    monkeypatch.setattr("services.sms.rc_adapter.asyncio.sleep", _fake_sleep)

    a = _adapter()
    res = _run(a.send(to="+15005551212", body="hi", tenant_id="t",
                        category="transactional"))
    assert res["provider_status"] == "failed"
    assert res["http_status"] == 429
    assert calls["n"] == 3


def test_ringcentral_401_is_terminal(monkeypatch):
    """RC 401 (``invalid_client`` — the exact prod bug) must be
    terminal — no retry."""
    _stub_no_suppress(monkeypatch)
    calls = {"n": 0}

    async def _boom(self, to, body, from_number=None):
        calls["n"] += 1
        raise RingCentralError(401, "invalid_client")
    monkeypatch.setattr("services.sms.rc_adapter.RingCentralService.send_sms", _boom)
    async def _fake_sleep(*_a, **_kw): pass
    monkeypatch.setattr("services.sms.rc_adapter.asyncio.sleep", _fake_sleep)

    a = _adapter()
    res = _run(a.send(to="+15005551212", body="hi", tenant_id="t",
                        category="transactional"))
    assert res["provider_status"] == "failed"
    assert res["http_status"] == 401
    assert calls["n"] == 1
