"""Phase 7A · Feb 2026 — RingCentral SMS wiring (additive, no cutover).

Unit-level coverage of ``RingCentralService.send_sms`` and the
``/api/dev/rc-sms-test`` dev endpoint. HTTPX is mocked so this suite
never contacts real RingCentral — the real send was proven once via
the ``/api/dev/rc-sms-test`` deliverable log.

Covers:
  · Happy path — response envelope + message_id + status
  · 429 with Retry-After honored (retried, eventually succeeds)
  · 403 scope-missing surfaces via ``scope_missing`` attribute
  · From-number resolution priority (override > env > SmsSender feature)
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

import pytest


# ═══════════════════════════ Phase 46 · Feb 2026 — comms-guard bypass ══
# The Phase 34 `guard_outbound` (services/comms_env_guard.py) short-
# circuits any non-production SMS to a `dry_run` envelope BEFORE the
# `_FakeClient` httpx mock is consulted, breaking every send-path
# assertion. All tests fully mock `httpx.AsyncClient` so NO live
# traffic is possible. Force `APP_ENV=production` for the duration of
# THIS test module only — monkeypatch auto-restores after each test.
@pytest.fixture(autouse=True)
def _phase46_bypass_comms_guard(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")


# ═══════════════════════════ Fake httpx layer ═════════════════════════
class _FakeResponse:
    def __init__(self, status: int, body: Any = None, headers: Optional[Dict] = None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}
        self.content = b"1" if body else b""
        self.text = str(body)[:400]

    def json(self):
        return self._body


class _FakeClient:
    """Records calls and returns queued responses."""
    def __init__(self, script: List[_FakeResponse]):
        self._script = list(script)
        self.calls: List[Dict[str, Any]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, headers=None, json=None, params=None, data=None):
        self.calls.append({"method": method, "url": url, "json": json,
                           "params": params, "headers": headers})
        return self._script.pop(0) if self._script else _FakeResponse(200, {})

    async def post(self, url, headers=None, json=None, data=None):
        return await self.request("POST", url, headers=headers, json=json, data=data)

    async def get(self, url, headers=None, params=None):
        return await self.request("GET", url, headers=headers, params=params)


@pytest.fixture
def rc_env(monkeypatch):
    monkeypatch.setenv("RC_SERVER_URL", "https://platform.ringcentral.com")
    monkeypatch.setenv("RC_CLIENT_ID", "fake_client")
    monkeypatch.setenv("RC_CLIENT_SECRET", "fake_secret")
    monkeypatch.setenv("RC_JWT",
                        "eyJhbGciOiJIUzI1NiJ9."
                        "eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig")
    monkeypatch.setenv("RC_MODE", "sandbox")
    monkeypatch.setenv("ALLOW_TEST_HOOKS", "1")
    from services.ringcentral import rc_client as _c
    _c._TOKEN_CACHE.clear()
    yield
    _c._TOKEN_CACHE.clear()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ═══════════════════════════ send_sms happy path ══════════════════════
def test_send_sms_happy_path(monkeypatch, rc_env):
    from services.ringcentral.rc_client import RingCentralService

    token_resp = _FakeResponse(200, {"access_token": "t123", "expires_in": 3600})
    sms_resp = _FakeResponse(200, {
        "id": 999888777,
        "messageStatus": "Queued",
        "to": [{"phoneNumber": "+15551110000"}],
        "from": {"phoneNumber": "+16028301080"},
        "type": "SMS",
    })
    # Script feeds the client _fetch_access_token first, then _request.
    client = _FakeClient([token_resp, sms_resp])
    monkeypatch.setattr("services.ringcentral.rc_client.httpx.AsyncClient",
                          lambda *a, **kw: client)
    monkeypatch.setenv("RC_SMS_DEFAULT_FROM", "+16028301080")

    svc = RingCentralService("test-tenant")
    res = _run(svc.send_sms("+15551110000", "hello world"))

    assert res["provider"] == "ringcentral"
    assert res["message_id"] == 999888777
    assert res["status"] == "Queued"
    assert res["from_number"] == "+16028301080"
    assert res["to_number"] == "+15551110000"
    # Verify RC saw the expected shape.
    sms_call = client.calls[-1]
    assert sms_call["method"] == "POST"
    assert sms_call["url"].endswith(
        "/restapi/v1.0/account/~/extension/~/sms"
    )
    assert sms_call["json"]["from"]["phoneNumber"] == "+16028301080"
    assert sms_call["json"]["to"] == [{"phoneNumber": "+15551110000"}]
    assert sms_call["json"]["text"] == "hello world"


# ═══════════════════════════ 429 retry with Retry-After ═══════════════
def test_send_sms_retries_on_429(monkeypatch, rc_env):
    from services.ringcentral.rc_client import RingCentralService

    async def _fast_sleep(*a, **k):
        return None
    monkeypatch.setattr("services.ringcentral.rc_client.asyncio.sleep",
                          _fast_sleep)

    token = _FakeResponse(200, {"access_token": "t", "expires_in": 3600})
    throttled = _FakeResponse(429, {"message": "rate"}, headers={"Retry-After": "1"})
    success = _FakeResponse(200, {"id": 111, "messageStatus": "Queued"})

    client = _FakeClient([token, throttled, success])
    monkeypatch.setattr("services.ringcentral.rc_client.httpx.AsyncClient",
                          lambda *a, **kw: client)
    monkeypatch.setenv("RC_SMS_DEFAULT_FROM", "+16028301080")

    svc = RingCentralService("t-429")
    res = _run(svc.send_sms("+15551110000", "hi"))
    assert res["message_id"] == 111
    # We should have retried once — total request calls = 1 token + 2 sms attempts.
    sms_calls = [c for c in client.calls
                    if str(c["url"]).endswith("/sms")]
    assert len(sms_calls) == 2, f"expected 2 sms attempts, got {len(sms_calls)}"


# ═══════════════════════════ 403 → scope_missing ══════════════════════
def test_send_sms_403_scope_missing(monkeypatch, rc_env):
    from services.ringcentral.rc_client import RingCentralService, RingCentralError

    token = _FakeResponse(200, {"access_token": "t", "expires_in": 3600})
    forbidden = _FakeResponse(403, {
        "errorCode": "InsufficientPermissions",
        "message": "In order to call this API endpoint, "
                   "user needs to have SMS scope",
    })
    client = _FakeClient([token, forbidden])
    monkeypatch.setattr("services.ringcentral.rc_client.httpx.AsyncClient",
                          lambda *a, **kw: client)
    monkeypatch.setenv("RC_SMS_DEFAULT_FROM", "+16028301080")

    svc = RingCentralService("t-403")
    with pytest.raises(RingCentralError) as ei:
        _run(svc.send_sms("+15551110000", "hi"))
    assert ei.value.status == 403
    assert getattr(ei.value, "scope_missing", False) is True


def test_send_sms_403_non_scope_does_not_flag(monkeypatch, rc_env):
    from services.ringcentral.rc_client import RingCentralService, RingCentralError

    token = _FakeResponse(200, {"access_token": "t", "expires_in": 3600})
    forbidden = _FakeResponse(403, {"errorCode": "SomethingElse",
                                       "message": "no permission"})
    client = _FakeClient([token, forbidden])
    monkeypatch.setattr("services.ringcentral.rc_client.httpx.AsyncClient",
                          lambda *a, **kw: client)
    monkeypatch.setenv("RC_SMS_DEFAULT_FROM", "+16028301080")

    svc = RingCentralService("t-403-other")
    with pytest.raises(RingCentralError) as ei:
        _run(svc.send_sms("+15551110000", "hi"))
    assert getattr(ei.value, "scope_missing", False) is False


# ═══════════════════════════ From-number resolution ═══════════════════
def test_resolve_from_prefers_override(monkeypatch, rc_env):
    from services.ringcentral.rc_client import RingCentralService

    token = _FakeResponse(200, {"access_token": "t", "expires_in": 3600})
    sms = _FakeResponse(200, {"id": 1, "messageStatus": "Queued"})
    client = _FakeClient([token, sms])
    monkeypatch.setattr("services.ringcentral.rc_client.httpx.AsyncClient",
                          lambda *a, **kw: client)
    monkeypatch.setenv("RC_SMS_DEFAULT_FROM", "+15550000000")

    svc = RingCentralService("t-override")
    res = _run(svc.send_sms("+15551110000", "hi",
                              from_number="+16028301080"))
    assert res["from_number"] == "+16028301080"


def test_resolve_from_falls_back_to_phone_number_endpoint(monkeypatch, rc_env):
    from services.ringcentral.rc_client import RingCentralService

    token = _FakeResponse(200, {"access_token": "t", "expires_in": 3600})
    phone_numbers = _FakeResponse(200, {"records": [
        {"phoneNumber": "+15559990000", "features": ["FaxReceiver"]},
        {"phoneNumber": "+16028301080", "features": ["SmsSender", "MmsSender"]},
    ]})
    sms = _FakeResponse(200, {"id": 42, "messageStatus": "Queued"})
    client = _FakeClient([token, phone_numbers, sms])
    monkeypatch.setattr("services.ringcentral.rc_client.httpx.AsyncClient",
                          lambda *a, **kw: client)
    # Unset env so resolver walks the phone-number list.
    monkeypatch.delenv("RC_SMS_DEFAULT_FROM", raising=False)

    svc = RingCentralService("t-lookup")
    res = _run(svc.send_sms("+15551110000", "hi"))
    assert res["from_number"] == "+16028301080"


def test_resolve_from_raises_when_no_sms_capable_line(monkeypatch, rc_env):
    from services.ringcentral.rc_client import RingCentralService, RingCentralError

    token = _FakeResponse(200, {"access_token": "t", "expires_in": 3600})
    phone_numbers = _FakeResponse(200, {"records": [
        {"phoneNumber": "+15559990000", "features": ["FaxReceiver"]},
    ]})
    client = _FakeClient([token, phone_numbers])
    monkeypatch.setattr("services.ringcentral.rc_client.httpx.AsyncClient",
                          lambda *a, **kw: client)
    monkeypatch.delenv("RC_SMS_DEFAULT_FROM", raising=False)

    svc = RingCentralService("t-no-sms")
    with pytest.raises(RingCentralError) as ei:
        _run(svc.send_sms("+15551110000", "hi"))
    assert ei.value.status == 400
    assert "SmsSender" in str(ei.value.body)


# ═══════════════════════════ Envelope guards ══════════════════════════
def test_send_sms_missing_to_raises(rc_env):
    from services.ringcentral.rc_client import RingCentralService, RingCentralError
    with pytest.raises(RingCentralError) as ei:
        _run(RingCentralService().send_sms("", "hi"))
    assert ei.value.status == 400


def test_send_sms_missing_body_raises(rc_env):
    from services.ringcentral.rc_client import RingCentralService, RingCentralError
    with pytest.raises(RingCentralError) as ei:
        _run(RingCentralService().send_sms("+15551110000", ""))
    assert ei.value.status == 400
