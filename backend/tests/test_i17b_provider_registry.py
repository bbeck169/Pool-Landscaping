"""Phase I1.7.b · Feb-2026 — Registry unified contract test."""
from __future__ import annotations

import pytest

from services.messaging.email.registry import (
    get_email_provider,
    list_registered_email_provider_keys,
    reset_cache_for_tests as _reset_email,
)
from services.messaging.models import UnknownMessagingProvider
from services.messaging.sms.registry import (
    get_sms_provider,
    list_registered_sms_provider_keys,
    reset_cache_for_tests as _reset_sms,
)


@pytest.fixture(autouse=True)
def _reset_caches():
    _reset_sms()
    _reset_email()
    yield
    _reset_sms()
    _reset_email()


class TestUnifiedRegistry:
    def test_sms_and_email_key_spaces_are_disjoint(self):
        sms_keys = set(list_registered_sms_provider_keys())
        email_keys = set(list_registered_email_provider_keys())
        assert not (sms_keys & email_keys), \
            f"provider keys must be disjoint: sms={sms_keys}, email={email_keys}"

    def test_dispatch_by_key(self):
        assert get_sms_provider("twilio").provider_key == "twilio"
        assert get_email_provider("resend").provider_key == "resend"

    def test_unknown_key_raises_shared_error(self):
        with pytest.raises(UnknownMessagingProvider):
            get_sms_provider("zzz")
        with pytest.raises(UnknownMessagingProvider):
            get_email_provider("zzz")

    def test_registry_singletons_are_stable_after_reset(self):
        a = get_sms_provider("textmagic")
        _reset_sms()
        b = get_sms_provider("textmagic")
        # After reset, a fresh singleton is returned — but same class.
        assert a is not b
        assert type(a) is type(b)
