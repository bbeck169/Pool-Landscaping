"""Feb-2026 P0 · Stripe Checkout preflight diagnostic endpoint tests."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

from tests.conftest import demo_pw


API = "http://127.0.0.1:8001/api"
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")


def _warm_backend() -> None:
    import time
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            r = requests.get(f"{API}/config/public", timeout=5)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)


_warm_backend()


def _login(email: str) -> str:
    for _ in range(4):
        try:
            r = requests.post(
                f"{API}/auth/login",
                json={"email": email, "password": demo_pw(email)},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()["access_token"]
        except (requests.exceptions.ReadTimeout,
                 requests.exceptions.ConnectionError):
            pass
    raise AssertionError(f"login failed for {email}")


_REQUIRED_FIELDS = {
    "ok", "app_env", "stripe_mode", "stripe_account_id",
    "app_public_url", "stripe_secret_key_live_set",
    "stripe_webhook_secret_live_set", "checkout_session_created",
    "checkout_url_preview", "error_class", "error_message", "hint",
}


def test_checkout_preflight_returns_ok_true_when_stripe_configured():
    """On this preview pod ``STRIPE_SECRET_KEY_LIVE`` +
    ``APP_PUBLIC_URL`` are set, so the preflight MUST return
    ``ok: true`` with a real ``checkout.stripe.com`` URL preview and
    a fully-populated payload. If this ever regresses the preview
    Stripe config is broken independently of the endpoint."""
    tok = _login("super@aquaterra.com")
    r = requests.get(
        f"{API}/settings/integrations/health/checkout-preflight",
        headers={"Authorization": f"Bearer {tok}"}, timeout=60,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    missing = _REQUIRED_FIELDS - set(body.keys())
    assert not missing, f"missing fields: {missing}"
    assert body["ok"] is True, body
    assert body["checkout_session_created"] is True
    assert body["checkout_url_preview"].startswith(
        "https://checkout.stripe.com/")
    assert body["error_class"] is None
    assert body["error_message"] is None
    # Config side of the payload should mirror what /config/public reports.
    # TD-stripe-test-fixture-refresh · Feb-2026 — preview pod reports
    # ``APP_ENV=development``; widen the allowed-set so this guard does
    # not false-positive on preview while still asserting the field
    # carries a recognised value.
    assert body["app_env"] in (
        "production", "preview", "staging", "test", "development")
    assert body["stripe_mode"] in ("live", "test")


def test_checkout_preflight_reports_unconfigured_when_key_missing():
    """Patch the endpoint's Stripe helpers to raise
    ``_UnconfiguredStripeError`` — payload MUST come back with
    ``ok: false``, ``error_class="_UnconfiguredStripeError"``, and
    the ``hint`` that points ops at the right env var."""
    from unittest.mock import patch

    from routers.google import integration_health_checkout_preflight
    from services.payments import stripe_charge

    async def _boom(**kwargs):
        raise stripe_charge._UnconfiguredStripeError(
            "No Stripe secret key configured.")

    admin = {"id": "u-1", "role": "super_admin",
              "email": "super@aquaterra.com"}
    tenant = {"id": "t-preflight"}

    async def _drive():
        with patch(
            "services.payments.stripe_charge.create_invoice_checkout_session",
            _boom,
        ):
            return await integration_health_checkout_preflight(
                admin=admin, tenant=tenant,
            )

    body = asyncio.get_event_loop().run_until_complete(_drive())
    assert body["ok"] is False
    assert body["error_class"] == "_UnconfiguredStripeError"
    assert "Stripe secret key" in (body["error_message"] or "")
    assert "STRIPE_SECRET_KEY" in (body["hint"] or "")
    assert body["checkout_session_created"] is False


def test_checkout_preflight_role_gate_denies_technician():
    """Technician account MUST get 403 — endpoint is guarded by
    ``require_admin_or_manager``. This is the same guard we use on
    ``/settings/integrations/health/comms``."""
    tok = _login("mike@aquaterra.com")  # seeded tech account
    r = requests.get(
        f"{API}/settings/integrations/health/checkout-preflight",
        headers={"Authorization": f"Bearer {tok}"}, timeout=30,
    )
    assert r.status_code == 403, r.text


def test_checkout_preflight_reports_app_public_url_missing_hint():
    """When ``create_invoice_checkout_session`` raises the
    ``APP_PUBLIC_URL not configured`` ValueError, the preflight
    payload's ``hint`` MUST call out that specific env var by name
    so ops fixes the right thing."""
    from unittest.mock import patch

    from routers.google import integration_health_checkout_preflight

    async def _no_url(**kwargs):
        raise ValueError("APP_PUBLIC_URL not configured")

    admin = {"id": "u-1", "role": "super_admin"}
    tenant = {"id": "t-preflight"}

    async def _drive():
        with patch(
            "services.payments.stripe_charge.create_invoice_checkout_session",
            _no_url,
        ):
            return await integration_health_checkout_preflight(
                admin=admin, tenant=tenant,
            )

    body = asyncio.get_event_loop().run_until_complete(_drive())
    assert body["ok"] is False
    assert body["error_class"] == "ValueError"
    assert "APP_PUBLIC_URL" in (body["error_message"] or "")
    assert "APP_PUBLIC_URL" in (body["hint"] or "")
