"""Feb-2026 · Payment Processor ticket · protocol conformance."""
from __future__ import annotations

import inspect

import pytest

from services.payments_byo.stripe_provider import StripeByoProvider
from services.payments_byo.lumino_provider import LuminoProvider
from services.payments_byo.tenant_base import PaymentsByoProvider


PROTOCOL_METHODS = (
    "create_charge",
    "refund_charge",
    "verify_webhook",
    "test_connection",
)


@pytest.mark.parametrize("cls", [StripeByoProvider, LuminoProvider])
def test_provider_class_extends_payments_byo_abc(cls):
    """Each concrete provider must subclass the shared ABC."""
    assert issubclass(cls, PaymentsByoProvider)


@pytest.mark.parametrize("cls", [StripeByoProvider, LuminoProvider])
def test_provider_class_defines_metadata(cls):
    assert cls.provider_key and cls.provider_key != "abstract_payments_byo"
    assert cls.short_name and cls.short_name != "abstract"


@pytest.mark.parametrize("cls", [StripeByoProvider, LuminoProvider])
def test_provider_implements_full_protocol(cls):
    for method_name in PROTOCOL_METHODS:
        fn = getattr(cls, method_name, None)
        assert fn is not None, f"{cls.__name__} missing {method_name}"
        assert inspect.iscoroutinefunction(fn), (
            f"{cls.__name__}.{method_name} must be async"
        )


def test_stripe_provider_short_name_is_stripe():
    """Ticket requires ``stripe`` as the short-name so the UI + audit
    tables render the human label consistently."""
    assert StripeByoProvider.short_name == "stripe"


def test_stripe_provider_env_probe_reads_env(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY_LIVE", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY_TEST", raising=False)
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    monkeypatch.delenv("STRIPE_MODE", raising=False)
    assert StripeByoProvider.is_configured() is False

    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_xyz")
    assert StripeByoProvider.is_configured() is True
