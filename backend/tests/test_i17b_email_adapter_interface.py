"""Phase I1.7.b · Feb-2026 — Email adapter interface + registry contract."""
from __future__ import annotations

import inspect

import pytest

from services.messaging.email.base import EmailProvider
from services.messaging.email.mailgun_provider import MailgunEmailProvider
from services.messaging.email.postmark_provider import PostmarkEmailProvider
from services.messaging.email.registry import (
    get_email_provider,
    list_registered_email_provider_keys,
    reset_cache_for_tests,
)
from services.messaging.email.resend_provider import ResendEmailProvider
from services.messaging.email.sendgrid_provider import SendGridEmailProvider
from services.messaging.email.smtp_provider import SmtpEmailProvider
from services.messaging.models import UnknownMessagingProvider


@pytest.fixture(autouse=True)
def _reset():
    reset_cache_for_tests()
    yield
    reset_cache_for_tests()


class TestEmailAdapterInterface:
    def test_abc_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            EmailProvider()

    @pytest.mark.parametrize("cls", [
        ResendEmailProvider, SendGridEmailProvider,
        PostmarkEmailProvider, MailgunEmailProvider, SmtpEmailProvider,
    ])
    def test_concrete_providers_declare_metadata(self, cls):
        assert isinstance(cls.provider_key, str) and cls.provider_key
        assert isinstance(cls.config_fields, dict) and cls.config_fields

    @pytest.mark.parametrize("cls", [
        ResendEmailProvider, SendGridEmailProvider,
        PostmarkEmailProvider, MailgunEmailProvider, SmtpEmailProvider,
    ])
    def test_concrete_providers_implement_async_methods(self, cls):
        for name in ("send_email", "get_status", "verify_webhook", "test_connection"):
            fn = getattr(cls, name)
            assert inspect.iscoroutinefunction(fn), f"{cls.__name__}.{name} must be async"


class TestEmailRegistry:
    def test_all_expected_providers_registered(self):
        keys = set(list_registered_email_provider_keys())
        assert {"resend", "sendgrid", "postmark", "mailgun", "smtp"}.issubset(keys)

    def test_get_email_provider_returns_singleton(self):
        a = get_email_provider("resend")
        b = get_email_provider("resend")
        assert a is b

    def test_unknown_provider_key_raises(self):
        with pytest.raises(UnknownMessagingProvider):
            get_email_provider("nope")
