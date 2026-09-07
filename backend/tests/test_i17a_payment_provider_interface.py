"""Phase I1.7.a · Feb-2026 — TenantPaymentProvider interface lock.

Guards against accidental drift in the ABC (missing methods,
regressed signatures). Sub-phases I1.7.d providers will
inherit the ABC and this suite will run against them too.
"""
from __future__ import annotations

import inspect

import pytest

from services.payments.tenant_base import (
    ChargeResult,
    ConnectionHealth,
    PaymentIntent,
    RefundResult,
    TenantNotConnected,
    TenantPaymentError,
    TenantPaymentProvider,
    UnknownProvider,
    WebhookEvent,
)
from services.payments.tenant_registry import (
    get_provider,
    list_registered_provider_keys,
    register_provider,
    reset_cache_for_tests,
)


class TestABC:
    def test_abstract_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            TenantPaymentProvider()  # type: ignore[abstract]

    def test_all_expected_methods_are_abstract(self):
        expected = {
            "create_charge", "refund_charge", "get_charge",
            "create_payment_intent", "verify_webhook", "test_connection",
        }
        abstract = set(TenantPaymentProvider.__abstractmethods__)
        assert abstract == expected

    def test_stripe_provider_implements_every_abstract(self):
        from services.payments.tenant_stripe import StripeConnectProvider
        # A concrete provider should be instantiable.
        p = StripeConnectProvider()
        assert isinstance(p, TenantPaymentProvider)
        for name in TenantPaymentProvider.__abstractmethods__:
            m = getattr(p, name)
            assert callable(m), name
            # Every impl is async — required by the ABC contract.
            assert inspect.iscoroutinefunction(m), f"{name} must be async"


class TestReturnTypes:
    def test_all_return_types_are_pydantic_models(self):
        from pydantic import BaseModel
        for cls in (ChargeResult, RefundResult, PaymentIntent,
                     WebhookEvent, ConnectionHealth):
            assert issubclass(cls, BaseModel), cls

    def test_charge_result_serialization_roundtrip(self):
        c = ChargeResult(
            id="ch_test", status="succeeded", amount_cents=1500,
            currency="usd", provider_key="stripe", tenant_id="t1",
            raw={"foo": "bar"},
        )
        j = c.model_dump()
        assert j["id"] == "ch_test"
        assert j["status"] == "succeeded"
        assert j["raw"] == {"foo": "bar"}
        assert ChargeResult.model_validate(j) == c


class TestRegistry:
    def test_stripe_is_registered_by_default(self):
        assert "stripe" in list_registered_provider_keys()
        p = get_provider("stripe")
        assert p.provider_key == "stripe"

    def test_get_provider_returns_singleton(self):
        a = get_provider("stripe")
        b = get_provider("stripe")
        assert a is b

    def test_unknown_provider_raises(self):
        with pytest.raises(UnknownProvider):
            get_provider("nonexistent_provider_key")

    def test_register_and_reset_cache(self):
        class _Fake(TenantPaymentProvider):
            provider_key = "fake_for_test"

            async def create_charge(self, **kw): return ChargeResult(
                id="", status="", amount_cents=0, currency="",
                provider_key="fake_for_test", tenant_id=kw.get("tenant_id", ""))
            async def refund_charge(self, **kw): return RefundResult(
                id="", charge_id="", status="", amount_cents=0,
                provider_key="fake_for_test", tenant_id=kw.get("tenant_id", ""))
            async def get_charge(self, **kw): return ChargeResult(
                id="", status="", amount_cents=0, currency="",
                provider_key="fake_for_test", tenant_id=kw.get("tenant_id", ""))
            async def create_payment_intent(self, **kw): return PaymentIntent(
                id="", client_secret="", status="", amount_cents=0,
                currency="", provider_key="fake_for_test",
                tenant_id=kw.get("tenant_id", ""))
            async def verify_webhook(self, **kw): return WebhookEvent(
                id="", event_type="", provider_key="fake_for_test")
            async def test_connection(self, **kw): return ConnectionHealth(
                provider_key="fake_for_test", tenant_id=kw.get("tenant_id", ""),
                ok=True, checked_at="")

        register_provider("fake_for_test", _Fake)
        assert "fake_for_test" in list_registered_provider_keys()
        p = get_provider("fake_for_test")
        assert p.provider_key == "fake_for_test"
        reset_cache_for_tests()
        p2 = get_provider("fake_for_test")
        # Same class → same singleton after re-instantiation.
        assert type(p) is type(p2)


class TestErrors:
    def test_error_hierarchy(self):
        assert issubclass(TenantNotConnected, TenantPaymentError)
        assert issubclass(UnknownProvider, TenantPaymentError)
