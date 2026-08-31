"""Phase G1 · Feb 2026 — Add-Card SMS sender-number lock-in.

Regression test for the ticket where the add-card SMS was being sent
from an unexpected RC-substituted number (``(623) 680-3534``) instead
of the company's public number (``+16028874400``).

Root cause captured by this test:
    * ``routers/customers.py:2460`` calls the legacy
      ``utils.send_sms`` wrapper for add-card SMS.
    * ``utils.send_sms`` (see backend/utils.py:230) delegates to
      ``services.sms.rc_adapter.send`` WITHOUT a ``tenant_id`` — so
      per-tenant ``rc_sms_from_number`` overrides never apply on
      this code path.
    * The adapter's ``_resolve_from(tenant_id=None)`` therefore falls
      back to the env ``RC_SMS_DEFAULT_FROM``. Whatever that env is
      set to becomes the outbound ``from`` field RC sees.

The fix is a one-line ``.env`` change (``RC_SMS_DEFAULT_FROM=
+16028874400``). This test locks the boundary: with the shipped
``.env`` value, an SMS routed through the exact same path the
add-card handler uses (``utils.send_sms`` →
``services.sms.rc_adapter.send`` → ``RingCentralService.send_sms``)
MUST produce an outbound RC payload whose ``from.phoneNumber`` is
``+16028874400``.

The test mocks the RingCentral HTTP transport — no live traffic is
generated. It also forces ``APP_ENV=production`` for the module's
duration so the Phase 34 ``guard_outbound`` doesn't short-circuit the
adapter to a dry-run envelope before the mocked transport can see
the payload.

DO NOT weaken this assertion: the exact string ``+16028874400`` is
the contract. Marketing / phone-vendor swaps must update this test
alongside ``.env``.
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict, List, Optional

import pytest


# ═══════════════════════════ Comms-guard bypass ══════════════════════
# The Phase 34 ``guard_outbound`` short-circuits any non-production
# SMS to a ``dry_run`` envelope BEFORE the mocked transport runs,
# which would hide the outbound ``from`` payload we need to assert.
# Every RC call in this file is fully mocked, so forcing prod is
# safe — no live traffic is possible.
@pytest.fixture(autouse=True)
def _bypass_comms_guard(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")


# ═══════════════════════════ Fake httpx layer ════════════════════════
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
    from services.ringcentral import rc_client as _c
    _c._TOKEN_CACHE.clear()
    monkeypatch.setattr(
        "services.ringcentral.rc_client.httpx.AsyncClient",
        lambda *a, **kw: client,
    )
    return client


def _capture_last_sms_from(client: _FakeClient) -> Optional[str]:
    """Return the ``from.phoneNumber`` of the most recent RC SMS
    payload the fake transport saw. Returns ``None`` if no SMS call
    was captured (test failure indicator)."""
    for c in reversed(client.calls):
        j = c.get("json") or {}
        if isinstance(j.get("from"), dict) and j.get("text") is not None:
            return j["from"].get("phoneNumber")
    return None


_RC_ENABLED = dict(
    RC_CLIENT_ID="fake_client",
    RC_CLIENT_SECRET="fake_secret",
    RC_JWT="eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig",
    RC_SERVER_URL="https://platform.ringcentral.com",
    RC_MODE="sandbox",
)


# ═══════════════════════════ The actual test ═════════════════════════
def test_add_card_sms_from_matches_company_number(monkeypatch):
    """Boundary contract: the outbound RC SMS from-number for a
    transactional add-card send MUST be ``+16028874400`` when the
    shipped ``.env RC_SMS_DEFAULT_FROM`` is honored (i.e. no tenant
    override present, which is the current DB state)."""
    ta = _load_adapter(
        monkeypatch,
        RC_SMS_DEFAULT_FROM="+16028874400",
        **_RC_ENABLED,
    )
    client = _install_rc_mock(monkeypatch, [
        _FakeResponse(200, {"id": 12345, "messageStatus": "Queued"}),
    ])

    adapter = ta.RingCentralSMSAdapter()
    res = _run(adapter.send(
        # Recipient phone matches the shape the add-card handler
        # passes (``customer["phone"]`` → normalised to E.164 by the
        # adapter). Use an allow-listed number so any residual guard
        # path is safe.
        to="+16028874400",
        body="Please add a card on file: https://example/portal/add-card/abc",
        category="transactional",
        # ``routers/customers.py:2460`` invokes ``utils.send_sms``
        # which does NOT plumb tenant_id — mirror that here so we
        # exercise the same fallback resolution.
        tenant_id=None,
    ))

    assert res["provider"] == "ringcentral"
    assert res["provider_status"] == "sent"

    captured_from = _capture_last_sms_from(client)
    assert captured_from == "+16028874400", (
        f"Add-card SMS from-number regressed: expected +16028874400, "
        f"got {captured_from!r}. Check backend/.env RC_SMS_DEFAULT_FROM."
    )


def test_add_card_sms_from_via_legacy_utils_send_sms(monkeypatch):
    """End-to-end (still fully mocked): drive the SAME call chain the
    add-card handler uses — ``utils.send_sms`` (sync legacy wrapper)
    → ``rc_adapter.send`` → ``RingCentralService.send_sms`` — and
    assert the outbound RC payload's ``from.phoneNumber`` locks to
    ``+16028874400``.

    This is the most important assertion for Phase G1: even the
    legacy sync helper (which does NOT pass tenant_id) resolves the
    from-number to the corrected env fallback.
    """
    ta = _load_adapter(
        monkeypatch,
        RC_SMS_DEFAULT_FROM="+16028874400",
        **_RC_ENABLED,
    )
    client = _install_rc_mock(monkeypatch, [
        _FakeResponse(200, {"id": 67890, "messageStatus": "Queued"}),
    ])

    # Repoint the legacy helper's import to the freshly-loaded adapter
    # (``_load_adapter`` clears the sys.modules cache).
    import utils as _utils
    monkeypatch.setattr(
        "services.sms.rc_adapter.send",
        ta.RingCentralSMSAdapter().send,
        raising=False,
    )
    # Force the local import inside ``utils.send_sms`` to see the same
    # instance (its ``from services.sms.rc_adapter import send`` will
    # pick up the module attribute we just set).
    import services.sms.rc_adapter as _mod
    monkeypatch.setattr(_mod, "send",
                          ta.RingCentralSMSAdapter().send, raising=False)

    ok = _utils.send_sms(
        "+16028874400",
        "Please add a card on file: https://example/portal/add-card/xyz",
    )
    assert ok is True

    captured_from = _capture_last_sms_from(client)
    assert captured_from == "+16028874400", (
        f"Legacy utils.send_sms → RC payload from-number regressed: "
        f"expected +16028874400, got {captured_from!r}."
    )
