"""Phase 7B · Feb 2026 — RC SMS adapter unit tests.

Direct successor to the retired ``test_twilio_slice_s.py``. Every
behavior the Twilio adapter guaranteed (phone normalisation, mocked
mode, suppression pre-check, transactional bypass, retry with backoff,
permanent-4xx no-retry, STOP suffix compliance, body hard-cap) is
re-asserted against the new ``services.sms.rc_adapter``.

The underlying RingCentral HTTPX client is mocked — no real RC
traffic is generated in this suite.
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict, List, Optional

import pytest


# ═══════════════════════════ Phase 46 · Feb 2026 — comms-guard bypass ══
# The Phase 34 `guard_outbound` (services/comms_env_guard.py) short-
# circuits any non-production SMS to a `dry_run` envelope before the
# adapter's mocked httpx layer runs, which breaks every assertion that
# keys off `provider_status == "sent"`. Every test here already fully
# mocks the RingCentral HTTP transport (`_install_rc_mock` +
# `_FakeClient`), so NO live traffic is possible. Force `APP_ENV=
# production` for the duration of THIS test module only — monkeypatch
# auto-restores after each test. The dry-run gate remains enforced
# globally in runtime code; this fixture only tells the guard "pretend
# we're prod" so the mocked transport can exercise the send path.
@pytest.fixture(autouse=True)
def _phase46_bypass_comms_guard(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")


# ═══════════════════════════ Fake httpx layer ═════════════════════════
class _FakeResponse:
    def __init__(self, status: int, body: Any = None,
                 headers: Optional[Dict] = None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}
        self.content = b"1" if body else b""
        self.text = str(body)[:400]

    def json(self):
        return self._body


class _FakeClient:
    def __init__(self, token_resp: _FakeResponse,
                 sms_responses: List[_FakeResponse]):
        self._token = token_resp
        self._sms = list(sms_responses)
        self.calls: List[Dict[str, Any]] = []
        self.sms_attempts = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, headers=None, json=None,
                      params=None, data=None):
        self.calls.append({"method": method, "url": url, "json": json})
        if "oauth/token" in str(url):
            return self._token
        if "/sms" in str(url):
            self.sms_attempts += 1
            return self._sms.pop(0) if self._sms else _FakeResponse(500, {})
        return _FakeResponse(200, {})

    async def post(self, url, headers=None, json=None, data=None):
        return await self.request("POST", url, headers=headers, json=json,
                                     data=data)

    async def get(self, url, headers=None, params=None):
        return await self.request("GET", url, headers=headers, params=params)


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _load_adapter(monkeypatch, **env):
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    sys.modules.pop("services.sms.rc_adapter", None)
    from services.sms import rc_adapter as ta
    return ta


def _install_rc_mock(monkeypatch, sms_responses: List[_FakeResponse]):
    token = _FakeResponse(200, {"access_token": "t", "expires_in": 3600})
    client = _FakeClient(token, sms_responses)
    # Reset the token cache so each test opens a fresh token flow.
    from services.ringcentral import rc_client as _c
    _c._TOKEN_CACHE.clear()
    monkeypatch.setattr("services.ringcentral.rc_client.httpx.AsyncClient",
                          lambda *a, **kw: client)
    return client


def _rc_enabled_env():
    """Env values required for the RC adapter to consider itself
    enabled (i.e. NOT in mock mode)."""
    return dict(
        RC_CLIENT_ID="fake_client",
        RC_CLIENT_SECRET="fake_secret",
        RC_JWT="eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig",
        RC_SERVER_URL="https://platform.ringcentral.com",
        RC_MODE="sandbox",
        RC_SMS_DEFAULT_FROM="+16028874400",
    )


# ═══════════════════════════ Phone normalisation ═════════════════════
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


# ═══════════════════════════ Enabled / disabled paths ════════════════
def test_disabled_returns_mocked(monkeypatch):
    ta = _load_adapter(
        monkeypatch,
        RC_CLIENT_ID="", RC_CLIENT_SECRET="", RC_JWT="", RC_SERVER_URL="",
    )
    adapter = ta.RingCentralSMSAdapter()
    assert adapter.enabled is False
    res = _run(adapter.send(to="6238878060", body="hi"))
    assert res["provider"] == "mock"
    assert res["provider_status"] == "mocked"


def test_invalid_phone_fails_fast(monkeypatch):
    ta = _load_adapter(monkeypatch, **_rc_enabled_env())
    adapter = ta.RingCentralSMSAdapter()
    res = _run(adapter.send(to="12345", body="hi"))
    assert res["provider_status"] == "failed"
    assert res["error"] == "invalid_phone"
    # Provider is always "ringcentral" for real dispatch attempts even
    # when the number pre-check fails (matches Twilio-era behavior).
    assert res["provider"] == "ringcentral"


# ═══════════════════════════ Suppression ═════════════════════════════
def test_suppression_blocks_send(monkeypatch):
    ta = _load_adapter(monkeypatch, **_rc_enabled_env())
    _install_rc_mock(monkeypatch, [_FakeResponse(200, {"id": 1,
                                                           "messageStatus": "Queued"})])

    async def _fake_is_suppressed(*args, **kwargs):
        return True
    import routers.marketing_preferences as prefs
    monkeypatch.setattr(prefs, "is_suppressed", _fake_is_suppressed)

    adapter = ta.RingCentralSMSAdapter()
    res = _run(adapter.send(
        to="6238878060", body="marketing blast",
        category="marketing", tenant_id="tenant-1",
    ))
    assert res["provider_status"] == "suppressed"
    assert res["provider"] == "ringcentral"


def test_transactional_bypasses_suppression(monkeypatch):
    ta = _load_adapter(monkeypatch, **_rc_enabled_env())
    _install_rc_mock(monkeypatch, [_FakeResponse(200,
                                                     {"id": 42, "messageStatus": "Queued"})])

    async def _fake_is_suppressed(*args, **kwargs):
        raise AssertionError("suppression must be bypassed for transactional")
    import routers.marketing_preferences as prefs
    monkeypatch.setattr(prefs, "is_suppressed", _fake_is_suppressed)

    adapter = ta.RingCentralSMSAdapter()
    res = _run(adapter.send(
        to="6238878060", body="Your appt is confirmed.",
        category="transactional", tenant_id="tenant-1",
    ))
    assert res["provider_status"] == "sent"
    assert res["provider_response_id"] == "42"
    assert res["provider"] == "ringcentral"


# ═══════════════════════════ Retry ═══════════════════════════════════
def test_retry_succeeds_on_third_attempt(monkeypatch):
    ta = _load_adapter(monkeypatch, **_rc_enabled_env())

    async def _noop_sleep(_):
        return None
    # Patch sleep on BOTH the adapter module and the rc_client module.
    monkeypatch.setattr("services.sms.rc_adapter.asyncio.sleep", _noop_sleep)
    monkeypatch.setattr("services.ringcentral.rc_client.asyncio.sleep", _noop_sleep)

    client = _install_rc_mock(monkeypatch, [
        _FakeResponse(429, {"message": "rate"}, headers={"Retry-After": "1"}),
        _FakeResponse(429, {"message": "rate"}, headers={"Retry-After": "1"}),
        _FakeResponse(200, {"id": 999, "messageStatus": "Queued"}),
    ])

    adapter = ta.RingCentralSMSAdapter()
    res = _run(adapter.send(
        to="6238878060", body="hi", category="marketing", tenant_id=None,
    ))
    # The RC client internally retries 429 up to 3 times per call, so the
    # first `svc.send_sms` may internally succeed after client-level
    # retries (returning 200 to the adapter). Adapter-level retry
    # counter therefore may be 1 while total SMS HTTP attempts = 3.
    assert res["provider_status"] == "sent"
    assert res["provider_response_id"] == "999"
    assert client.sms_attempts == 3


def test_retry_exhaustion(monkeypatch):
    ta = _load_adapter(monkeypatch, **_rc_enabled_env())

    async def _noop_sleep(_):
        return None
    monkeypatch.setattr("services.sms.rc_adapter.asyncio.sleep", _noop_sleep)
    monkeypatch.setattr("services.ringcentral.rc_client.asyncio.sleep", _noop_sleep)

    # RC client tries up to 3 times per adapter-attempt; adapter also
    # retries up to 3. Load 9 5xx responses so both layers exhaust.
    _install_rc_mock(monkeypatch, [_FakeResponse(503, {"m": "svc"}) for _ in range(12)])
    adapter = ta.RingCentralSMSAdapter()
    res = _run(adapter.send(
        to="6238878060", body="hi", category="marketing", tenant_id=None,
    ))
    assert res["provider_status"] == "failed"
    assert res["attempts"] == 3


def test_permanent_4xx_no_retry(monkeypatch):
    ta = _load_adapter(monkeypatch, **_rc_enabled_env())

    async def _noop_sleep(_):
        return None
    monkeypatch.setattr("services.sms.rc_adapter.asyncio.sleep", _noop_sleep)
    monkeypatch.setattr("services.ringcentral.rc_client.asyncio.sleep", _noop_sleep)

    client = _install_rc_mock(monkeypatch, [
        _FakeResponse(400, {"errorCode": "InvalidParameter",
                             "message": "bad phone"}),
    ])
    adapter = ta.RingCentralSMSAdapter()
    res = _run(adapter.send(
        to="6238878060", body="hi", category="marketing", tenant_id=None,
    ))
    assert res["provider_status"] == "failed"
    # RC client 400 is terminal; adapter must not retry.
    assert client.sms_attempts == 1


# ═══════════════════════════ STOP suffix compliance ══════════════════
def _capture_last_sms_body(client: _FakeClient) -> str:
    for c in reversed(client.calls):
        if c.get("json") and c["json"].get("text") is not None:
            return c["json"]["text"]
    return ""


def test_stop_suffix_marketing(monkeypatch):
    ta = _load_adapter(monkeypatch, **_rc_enabled_env())
    client = _install_rc_mock(monkeypatch, [_FakeResponse(200, {"id": 1,
                                                                     "messageStatus": "Queued"})])
    adapter = ta.RingCentralSMSAdapter()
    _run(adapter.send(
        to="6238878060", body="Big blowout sale!",
        category="marketing", tenant_id=None,
    ))
    assert "Reply STOP to unsubscribe" in _capture_last_sms_body(client)


def test_stop_suffix_skipped_for_transactional(monkeypatch):
    ta = _load_adapter(monkeypatch, **_rc_enabled_env())
    client = _install_rc_mock(monkeypatch, [_FakeResponse(200, {"id": 2,
                                                                     "messageStatus": "Queued"})])
    adapter = ta.RingCentralSMSAdapter()
    _run(adapter.send(
        to="6238878060", body="Your appointment is confirmed.",
        category="transactional", tenant_id=None,
    ))
    assert "STOP" not in _capture_last_sms_body(client)


def test_stop_suffix_not_double_appended(monkeypatch):
    """A template that already includes STOP language must NOT get a
    second suffix — case-insensitive detection."""
    ta = _load_adapter(monkeypatch, **_rc_enabled_env())
    client = _install_rc_mock(monkeypatch, [_FakeResponse(200, {"id": 3,
                                                                     "messageStatus": "Queued"})])
    adapter = ta.RingCentralSMSAdapter()
    _run(adapter.send(
        to="6238878060", body="Hi — reply STOP to opt out of alerts.",
        category="marketing", tenant_id=None,
    ))
    body = _capture_last_sms_body(client)
    assert body.lower().count("stop") == 1


def test_body_capped_at_1600(monkeypatch):
    ta = _load_adapter(monkeypatch, **_rc_enabled_env())
    client = _install_rc_mock(monkeypatch, [_FakeResponse(200, {"id": 4,
                                                                     "messageStatus": "Queued"})])
    adapter = ta.RingCentralSMSAdapter()
    _run(adapter.send(
        to="6238878060", body="x" * 5000,
        category="transactional", tenant_id=None,
    ))
    body = _capture_last_sms_body(client)
    assert len(body) <= 1600


# ═══════════════════════════ Response envelope shape ═════════════════
def test_response_shape_matches_twilio_contract(monkeypatch):
    """Downstream consumers key off {provider, provider_status,
    provider_response_id, attempts, error}. Every field must be
    present on both success and mock paths so ``marketing_deliveries``
    inserts don't NPE."""
    ta = _load_adapter(monkeypatch, RC_CLIENT_ID="", RC_JWT="",
                          RC_SERVER_URL="")
    res = _run(ta.RingCentralSMSAdapter().send(
        to="6238878060", body="hi", category="marketing", tenant_id=None,
    ))
    for k in ("provider", "provider_status", "provider_response_id",
              "attempts", "error"):
        assert k in res
