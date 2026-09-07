"""Phase I1.7.b · Feb-2026 — SMS adapter interface + registry contract.

Pure unit tests — no HTTP, no DB. Validates that:
  1. The ABC ``SmsProvider`` raises on instantiation of a stub that
     skips a method.
  2. Every registered concrete provider satisfies the contract
     (has ``provider_key`` + ``config_fields`` + async methods).
  3. Registry lookups + unknown-key error paths.
"""
from __future__ import annotations

import inspect

import pytest

from services.messaging.sms.base import SmsProvider
from services.messaging.sms.registry import (
    get_sms_provider,
    list_registered_sms_provider_keys,
    reset_cache_for_tests,
)
from services.messaging.sms.ringcentral_provider import RingCentralSmsProvider
from services.messaging.sms.textmagic_provider import TextMagicSmsProvider
from services.messaging.sms.twilio_provider import TwilioSmsProvider
from services.messaging.models import UnknownMessagingProvider


@pytest.fixture(autouse=True)
def _reset():
    reset_cache_for_tests()
    yield
    reset_cache_for_tests()


class TestSmsAdapterInterface:
    def test_abc_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            SmsProvider()   # abstract methods missing

    @pytest.mark.parametrize("cls", [
        TwilioSmsProvider, TextMagicSmsProvider, RingCentralSmsProvider,
    ])
    def test_concrete_providers_declare_metadata(self, cls):
        assert isinstance(cls.provider_key, str) and cls.provider_key
        assert isinstance(cls.config_fields, dict) and cls.config_fields
        for name, meta in cls.config_fields.items():
            assert "required" in meta
            assert "secret" in meta
            assert "label" in meta

    @pytest.mark.parametrize("cls", [
        TwilioSmsProvider, TextMagicSmsProvider, RingCentralSmsProvider,
    ])
    def test_concrete_providers_implement_async_methods(self, cls):
        for name in ("send_sms", "get_status", "verify_webhook", "test_connection"):
            fn = getattr(cls, name)
            assert inspect.iscoroutinefunction(fn), f"{cls.__name__}.{name} must be async"


class TestSmsRegistry:
    def test_all_expected_providers_registered(self):
        keys = set(list_registered_sms_provider_keys())
        assert {"twilio", "textmagic", "ringcentral"}.issubset(keys)

    def test_get_sms_provider_returns_singleton(self):
        a = get_sms_provider("twilio")
        b = get_sms_provider("twilio")
        assert a is b

    def test_unknown_provider_key_raises(self):
        with pytest.raises(UnknownMessagingProvider):
            get_sms_provider("nope")
