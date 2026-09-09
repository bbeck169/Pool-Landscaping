"""Feb-2026 · P1 parallel fix — AI + Maps BYO empty-credential
fallback (companion to
``test_p0_byo_empty_credentials_fallback.py``).

Same shape of fix in three places:
  * ``services.messaging.byo_passthrough`` (already tested)
  * ``services.ai.dispatcher.dispatch_ai_completion``
  * ``services.maps.dispatcher._dispatch_op``

These tests lock in:
  1. AI: empty / whitespace / missing required BYO field →
     falls back to Emergent platform (``_emergent_platform_fallback``)
  2. AI: BYO ``complete()`` raises "401 Unauthorized" → falls back
  3. AI: cap-exceeded (``TenantAIUsageCapExceeded``) still HARD
     BLOCKS — no fallback, no swallow.
  4. Maps: same three shapes for the geocode op.

Cap-exceeded semantics are the intentional-behaviour-lock — this
suite double-checks the parallel fix did NOT weaken them.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# ─── AI dispatcher ────────────────────────────────────────────────

class _FakeAIProvider:
    provider_key = "openai"
    config_fields = {
        "api_key": {"required": True, "secret": True},
        "org_id":  {"required": False, "secret": False},
    }

    def __init__(self, *, complete_side_effect=None,
                  complete_return=None) -> None:
        if complete_side_effect is not None:
            self.complete = AsyncMock(side_effect=complete_side_effect)
        else:
            self.complete = AsyncMock(return_value=complete_return or SimpleNamespace(
                content="hello", tokens_prompt=1, tokens_completion=2,
                tokens_total=3, provider_key="openai",
                provider_used="tenant:openai", model="gpt-4o",
                tenant_id="t", raw={},
            ))


def _fake_emergent_result():
    """Sentinel object returned by the mocked platform fallback."""
    from services.ai.models import AICompletionResult
    return AICompletionResult(
        content="[platform]", provider_key="emergent",
        provider_used="platform:emergent", model="claude-sonnet-4-5",
        tokens_prompt=0, tokens_completion=0, tokens_total=0,
        tenant_id="t-brian-tenant", raw={"platform": True},
    )


@pytest.mark.anyio
@pytest.mark.parametrize("cfg", [
    {"api_key": ""},                 # empty string
    {"api_key": "   "},              # whitespace
    {"org_id": "org_x"},             # missing required
    {"api_key": None},               # None
])
async def test_ai_falls_back_when_required_fields_blank(cfg, monkeypatch):
    from services.ai import dispatcher as disp
    provider = _FakeAIProvider()
    monkeypatch.setattr(disp, "get_tenant_ai_provider",
                        AsyncMock(return_value=provider))
    monkeypatch.setattr(
        "services.ai._helpers.load_provider_config",
        AsyncMock(return_value=cfg),
    )
    fallback = AsyncMock(return_value=_fake_emergent_result())
    monkeypatch.setattr(disp, "_emergent_platform_fallback", fallback)
    # Cap check must NOT be reached — assert-fail if it fires.
    monkeypatch.setattr(disp, "enforce_cap_or_raise",
                        AsyncMock(side_effect=AssertionError(
                            "cap check must not fire when BYO fields blank"
                        )))

    result = await disp.dispatch_ai_completion(
        tenant_id="t-brian-tenant",
        system_prompt="sys", user_text="hello",
    )
    assert result.provider_used == "platform:emergent"
    provider.complete.assert_not_called()
    fallback.assert_awaited_once()


@pytest.mark.anyio
async def test_ai_falls_back_on_credential_shaped_exception(monkeypatch):
    """BYO fields look present but the upstream API returns 401.
    Fall back to platform silently."""
    from services.ai import dispatcher as disp
    provider = _FakeAIProvider(
        complete_side_effect=RuntimeError("OpenAI API 401 Unauthorized"),
    )
    monkeypatch.setattr(disp, "get_tenant_ai_provider",
                        AsyncMock(return_value=provider))
    monkeypatch.setattr(
        "services.ai._helpers.load_provider_config",
        AsyncMock(return_value={"api_key": "sk-looks-real"}),
    )
    monkeypatch.setattr(disp, "enforce_cap_or_raise", AsyncMock())
    fallback = AsyncMock(return_value=_fake_emergent_result())
    monkeypatch.setattr(disp, "_emergent_platform_fallback", fallback)

    result = await disp.dispatch_ai_completion(
        tenant_id="t", system_prompt="s", user_text="u",
    )
    assert result.provider_used == "platform:emergent"
    provider.complete.assert_awaited_once()
    fallback.assert_awaited_once()


@pytest.mark.anyio
async def test_ai_cap_exceeded_stays_hard_block(monkeypatch):
    """Cap-exceeded MUST NOT silently fall back to platform.
    ``enforce_cap_or_raise`` raises ``TenantAIUsageCapExceeded`` and
    the dispatcher must propagate — not swallow."""
    from services.ai import dispatcher as disp
    from services.ai.models import TenantAIUsageCapExceeded

    provider = _FakeAIProvider()
    monkeypatch.setattr(disp, "get_tenant_ai_provider",
                        AsyncMock(return_value=provider))
    monkeypatch.setattr(
        "services.ai._helpers.load_provider_config",
        AsyncMock(return_value={"api_key": "sk-real"}),
    )
    monkeypatch.setattr(disp, "enforce_cap_or_raise",
                        AsyncMock(side_effect=TenantAIUsageCapExceeded(
                            provider="openai", cap=100, used=101,
                        )))
    fallback = AsyncMock(return_value=_fake_emergent_result())
    monkeypatch.setattr(disp, "_emergent_platform_fallback", fallback)

    with pytest.raises(TenantAIUsageCapExceeded):
        await disp.dispatch_ai_completion(
            tenant_id="t", system_prompt="s", user_text="u",
        )
    fallback.assert_not_called()
    provider.complete.assert_not_called()


# ─── Maps dispatcher ──────────────────────────────────────────────

class _FakeMapsProvider:
    provider_key = "google"
    config_fields = {
        "api_key": {"required": True, "secret": True},
    }

    def __init__(self, geocode_side_effect=None) -> None:
        if geocode_side_effect is not None:
            self.geocode = AsyncMock(side_effect=geocode_side_effect)
        else:
            self.geocode = AsyncMock(return_value=SimpleNamespace(
                address="tenant-byo",
                provider_used="tenant:google",
            ))


def _fake_platform_geocode_result():
    from services.maps.models import MapsGeocodeResult
    return MapsGeocodeResult(
        address="platform-fallback", lat=33.5, lng=-112.0,
        formatted_address="[platform] test", provider_response_id=None,
        provider_key="maps_platform",
        provider_used="platform:google",
        tenant_id="t-brian-tenant", raw={"platform": True},
    )


@pytest.mark.anyio
@pytest.mark.parametrize("cfg", [
    {"api_key": ""},
    {"api_key": "   "},
    {},                      # missing
    {"api_key": None},
])
async def test_maps_falls_back_when_required_fields_blank(cfg, monkeypatch):
    from services.maps import dispatcher as disp
    provider = _FakeMapsProvider()
    monkeypatch.setattr(disp, "get_tenant_maps_provider",
                        AsyncMock(return_value=provider))
    monkeypatch.setattr(
        "services.maps._helpers.load_provider_config",
        AsyncMock(return_value=cfg),
    )
    monkeypatch.setattr(disp, "enforce_cap_or_raise",
                        AsyncMock(side_effect=AssertionError(
                            "cap check must not fire when BYO fields blank"
                        )))
    monkeypatch.setattr(disp, "_platform_geocode",
                        AsyncMock(return_value=_fake_platform_geocode_result()))

    result = await disp.dispatch_maps_geocode(
        tenant_id="t-brian-tenant", address="123 Main",
    )
    assert result.provider_used == "platform:google"
    provider.geocode.assert_not_called()


@pytest.mark.anyio
async def test_maps_falls_back_on_credential_shaped_exception(monkeypatch):
    from services.maps import dispatcher as disp
    provider = _FakeMapsProvider(
        geocode_side_effect=RuntimeError(
            "Google Maps API 403 Forbidden: invalid API key"
        ),
    )
    monkeypatch.setattr(disp, "get_tenant_maps_provider",
                        AsyncMock(return_value=provider))
    monkeypatch.setattr(
        "services.maps._helpers.load_provider_config",
        AsyncMock(return_value={"api_key": "AIzaLooksReal"}),
    )
    monkeypatch.setattr(disp, "enforce_cap_or_raise", AsyncMock())
    platform = AsyncMock(return_value=_fake_platform_geocode_result())
    monkeypatch.setattr(disp, "_platform_geocode", platform)

    result = await disp.dispatch_maps_geocode(
        tenant_id="t", address="123 Main",
    )
    assert result.provider_used == "platform:google"
    provider.geocode.assert_awaited_once()
    platform.assert_awaited_once()


@pytest.mark.anyio
async def test_maps_cap_exceeded_stays_hard_block(monkeypatch):
    from services.maps import dispatcher as disp
    from services.maps.models import TenantMapsRequestCapExceeded

    provider = _FakeMapsProvider()
    monkeypatch.setattr(disp, "get_tenant_maps_provider",
                        AsyncMock(return_value=provider))
    monkeypatch.setattr(
        "services.maps._helpers.load_provider_config",
        AsyncMock(return_value={"api_key": "AIzaReal"}),
    )
    monkeypatch.setattr(disp, "enforce_cap_or_raise",
                        AsyncMock(side_effect=TenantMapsRequestCapExceeded(
                            provider="google", cap=100, used=101,
                        )))
    platform = AsyncMock(return_value=_fake_platform_geocode_result())
    monkeypatch.setattr(disp, "_platform_geocode", platform)

    with pytest.raises(TenantMapsRequestCapExceeded):
        await disp.dispatch_maps_geocode(
            tenant_id="t", address="123 Main",
        )
    platform.assert_not_called()
    provider.geocode.assert_not_called()
