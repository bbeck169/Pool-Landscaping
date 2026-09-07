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


# ── I1.7.b.fix — friendly error for kind-alias URL mistakes ──────
import requests
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
_API = "http://localhost:8001/api"


def _tok():
    r = requests.post(f"{_API}/auth/login",
                        json={"email": "super@aquaterra.com",
                                "password": "password123"}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


class TestKindAliasHint:
    def test_put_to_kind_sms_returns_helpful_error(self):
        r = requests.put(
            f"{_API}/tenants/me/integrations/sms",
            headers={"Authorization": f"Bearer {_tok()}"},
            json={"config": {"any": "value"}}, timeout=15,
        )
        assert r.status_code == 400, r.text
        body = r.text
        assert "unknown provider key 'sms'" in body
        for k in ("twilio", "textmagic", "ringcentral"):
            assert k in body
        assert "/api/tenants/me/integrations/schemas" in body

    def test_put_to_kind_email_returns_helpful_error(self):
        r = requests.put(
            f"{_API}/tenants/me/integrations/email",
            headers={"Authorization": f"Bearer {_tok()}"},
            json={"config": {"any": "value"}}, timeout=15,
        )
        assert r.status_code == 400, r.text
        body = r.text
        assert "unknown provider key 'email'" in body
        for k in ("resend", "sendgrid", "postmark", "mailgun", "smtp"):
            assert k in body
        assert "/api/tenants/me/integrations/schemas" in body

    def test_put_to_stripe_returns_oauth_specific_error(self):
        r = requests.put(
            f"{_API}/tenants/me/integrations/stripe",
            headers={"Authorization": f"Bearer {_tok()}"},
            json={"config": {"api_key": "sk_test_dontsaveme"}}, timeout=15,
        )
        assert r.status_code == 400, r.text
        assert "OAuth" in r.text
        assert "/connect-link" in r.text

    def test_put_to_unknown_provider_returns_generic_error(self):
        r = requests.put(
            f"{_API}/tenants/me/integrations/carrier-pigeon",
            headers={"Authorization": f"Bearer {_tok()}"},
            json={"config": {"foo": "bar"}}, timeout=15,
        )
        assert r.status_code == 400, r.text
        assert "unknown provider key 'carrier-pigeon'" in r.text
        assert "/api/tenants/me/integrations/schemas" in r.text
