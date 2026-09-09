"""Feb-2026 · P0 comms hotfix — BYOP empty-credentials fallback.

User reported both Resend AND RingCentral broke after setting up
BYOP. Root cause: ``services.messaging.byo_passthrough`` treated a
``connected=True`` tenant_secrets row as authoritative even when
the row's required credential fields (``api_key``, ``jwt``, etc.)
were empty strings. The BYO provider raised an auth exception, the
passthrough returned a ``_envelope_failed(...)``, and the adapter
never fell back to the platform Resend / RingCentral key.

Fix: :func:`_byo_required_fields_present` runs before every BYO
dispatch and returns ``False`` when any ``required=True`` field
on the provider schema is missing / blank / whitespace — causing
the passthrough to return ``None`` and letting the caller take
the platform path.

These tests lock the fix in:

1. empty-string ``api_key`` in the saved config →
   ``try_dispatch_email_tenant_byo`` returns ``None`` (no BYO call)
2. whitespace-only ``api_key`` → same
3. missing ``from_addr`` (also required) → same
4. all fields present → BYO path runs as usual (regression check)
5. same shape for SMS via RingCentral
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.messaging.byo_passthrough import (
    try_dispatch_email_tenant_byo,
    try_dispatch_sms_tenant_byo,
    _looks_like_credential_failure,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _FakeEmailProvider:
    provider_key = "resend"
    config_fields = {
        "api_key":   {"required": True, "secret": True},
        "from_addr": {"required": True, "secret": False},
        "from_name": {"required": False, "secret": False},
    }

    def __init__(self) -> None:
        self.send_email = AsyncMock(
            side_effect=AssertionError(
                "send_email must not be called when required fields are empty"
            )
        )


class _FakeSmsProvider:
    provider_key = "ringcentral"
    config_fields = {
        "client_id":     {"required": True, "secret": False},
        "client_secret": {"required": True, "secret": True},
        "jwt":           {"required": True, "secret": True},
    }

    def __init__(self) -> None:
        self.send_sms = AsyncMock(
            side_effect=AssertionError(
                "send_sms must not be called when required fields are empty"
            )
        )


@pytest.mark.anyio
@pytest.mark.parametrize("cfg", [
    {"api_key": "", "from_addr": "cs@plofv.com"},         # empty string
    {"api_key": "   ", "from_addr": "cs@plofv.com"},       # whitespace
    {"from_addr": "cs@plofv.com"},                            # missing key
    {"api_key": "re_valid_looking", "from_addr": ""},      # empty from
    {"api_key": None, "from_addr": "cs@plofv.com"},        # None
])
async def test_byo_email_falls_back_when_required_fields_blank(cfg, monkeypatch):
    """Every one of these shapes must trip the guard."""
    provider = _FakeEmailProvider()

    async def _fake_load(**_kw):
        return cfg
    monkeypatch.setattr(
        "services.messaging._helpers.load_provider_config",
        _fake_load,
    )
    monkeypatch.setattr(
        "services.messaging.byo_passthrough.get_tenant_email_provider",
        AsyncMock(return_value=provider),
    )

    envelope = await try_dispatch_email_tenant_byo(
        tenant_id="t-brian-tenant",
        to="brian@example.com",
        subject="probe", text="probe",
    )
    assert envelope is None, (
        f"Expected fall-through to platform, got envelope={envelope}"
    )
    provider.send_email.assert_not_called()


@pytest.mark.anyio
async def test_byo_email_runs_when_all_required_fields_present(monkeypatch):
    """Regression check — a fully-configured BYO row must still route."""
    provider = _FakeEmailProvider()
    provider.send_email = AsyncMock(return_value=SimpleNamespace(
        status="sent", id="msg-123", raw={"id": "msg-123"}, error=None,
    ))

    async def _fake_load(**_kw):
        return {"api_key": "re_LKQ_valid", "from_addr": "cs@plofv.com"}
    monkeypatch.setattr(
        "services.messaging._helpers.load_provider_config",
        _fake_load,
    )
    monkeypatch.setattr(
        "services.messaging.byo_passthrough.get_tenant_email_provider",
        AsyncMock(return_value=provider),
    )

    envelope = await try_dispatch_email_tenant_byo(
        tenant_id="t-good-tenant", to="ok@example.com",
        subject="probe", text="probe",
    )
    assert envelope is not None
    assert envelope["provider"] == "resend"
    assert envelope["provider_status"] == "sent"
    provider.send_email.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("cfg", [
    {"client_id": "", "client_secret": "s", "jwt": "j"},
    {"client_id": "c", "client_secret": " ", "jwt": "j"},
    {"client_id": "c", "client_secret": "s"},                  # no jwt
    {"client_id": None, "client_secret": "s", "jwt": "j"},
])
async def test_byo_sms_falls_back_when_required_fields_blank(cfg, monkeypatch):
    provider = _FakeSmsProvider()

    async def _fake_load(**_kw):
        return cfg
    monkeypatch.setattr(
        "services.messaging._helpers.load_provider_config",
        _fake_load,
    )
    monkeypatch.setattr(
        "services.messaging.byo_passthrough.get_tenant_sms_provider",
        AsyncMock(return_value=provider),
    )

    envelope = await try_dispatch_sms_tenant_byo(
        tenant_id="t-brian-tenant", to="+15555550100", body="probe",
    )
    assert envelope is None, (
        f"Expected fall-through to platform, got envelope={envelope}"
    )
    provider.send_sms.assert_not_called()


@pytest.mark.anyio
async def test_byo_email_falls_back_on_credential_shaped_exception(monkeypatch):
    """If the provider raises an auth-shaped error even with
    non-empty fields, we still fall back to platform. Handles the
    case where the key format passed the ``required`` check but
    the upstream API rejected it as unauthorized."""
    provider = _FakeEmailProvider()
    provider.send_email = AsyncMock(side_effect=RuntimeError(
        "Resend API returned 401 Unauthorized"
    ))

    async def _fake_load(**_kw):
        return {"api_key": "re_LKQ_looks_real", "from_addr": "cs@plofv.com"}
    monkeypatch.setattr(
        "services.messaging._helpers.load_provider_config",
        _fake_load,
    )
    monkeypatch.setattr(
        "services.messaging.byo_passthrough.get_tenant_email_provider",
        AsyncMock(return_value=provider),
    )

    envelope = await try_dispatch_email_tenant_byo(
        tenant_id="t-brian-tenant", to="brian@example.com",
        subject="probe", text="probe",
    )
    assert envelope is None
    provider.send_email.assert_awaited_once()


def test_looks_like_credential_failure_positive_matches():
    for text in [
        "401 Unauthorized",
        "HTTP 403 forbidden",
        "invalid API key",
        "TenantMessagingNotConnected: Tenant t has no Resend config",
        "authentication failed",
        "missing required fields: api_key",
    ]:
        assert _looks_like_credential_failure(text), (
            f"Should match: {text!r}"
        )


def test_looks_like_credential_failure_negative_matches():
    for text in [
        "monthly cap exceeded",
        "429 too many requests",
        "connection reset",
        "recipient bounced",
        "",
        None,
    ]:
        assert not _looks_like_credential_failure(text), (
            f"Should NOT match: {text!r}"
        )
