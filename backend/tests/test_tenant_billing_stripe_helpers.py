"""Feb-2026 · Business Signup SP1 — tenant-billing Stripe helpers.

Sync tests only (matches project convention). The one async helper
(``create_tenant_billing``) is invoked via ``asyncio.new_event_loop``
so we don't touch Motor's global loop.
"""
from __future__ import annotations

import asyncio


def _run(coro):
    """Run a coroutine on a fresh event loop — matches the project's
    sync-first testing convention while still exercising async helpers."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_create_tenant_billing_sandbox_path(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY_LIVE", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY_TEST", raising=False)
    from services.tenant_billing_stripe import create_tenant_billing
    r = _run(create_tenant_billing(
        tenant_id="t1", business_name="Acme Pools",
        admin_email="a@t.example", payment_method_id="pm_x",
    ))
    assert r["billing_status"] == "pending_stripe_config"
    assert r["stripe_customer_id"] is None
    assert r["stripe_subscription_id"] is None
    assert r["trial_end_utc"] is None
    assert r["sandbox"] is True


def test_resolve_tenant_price_id_defaults_to_starter(monkeypatch):
    from services.tenant_billing_stripe import resolve_tenant_price_id
    monkeypatch.delenv("STRIPE_TENANT_BILLING_PRICE_ID_STARTER", raising=False)
    monkeypatch.delenv("STRIPE_TENANT_BILLING_PRICE_ID_PRO", raising=False)
    assert resolve_tenant_price_id() is None
    monkeypatch.setenv("STRIPE_TENANT_BILLING_PRICE_ID_STARTER", "price_abc")
    assert resolve_tenant_price_id() == "price_abc"
    assert resolve_tenant_price_id("starter") == "price_abc"


def test_resolve_tenant_price_id_pro_plan(monkeypatch):
    from services.tenant_billing_stripe import resolve_tenant_price_id
    monkeypatch.setenv("STRIPE_TENANT_BILLING_PRICE_ID_PRO", "price_pro")
    assert resolve_tenant_price_id("pro") == "price_pro"


def test_resolve_tenant_price_id_falls_through_when_env_blank(monkeypatch):
    from services.tenant_billing_stripe import resolve_tenant_price_id
    monkeypatch.setenv("STRIPE_TENANT_BILLING_PRICE_ID_STARTER", "   ")
    assert resolve_tenant_price_id() is None


def test_create_tenant_billing_env_configured_but_no_price_id(monkeypatch):
    """When Stripe env is present but the price ID is missing, fall
    through to pending_stripe_config with a logged warning."""
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_dummy")
    monkeypatch.delenv("STRIPE_TENANT_BILLING_PRICE_ID_STARTER", raising=False)
    from services.tenant_billing_stripe import create_tenant_billing
    r = _run(create_tenant_billing(
        tenant_id="t2", business_name="Acme", admin_email="b@t.example",
        payment_method_id="pm_y",
    ))
    assert r["billing_status"] == "pending_stripe_config"
    assert r["price_id"] is None


def test_cancel_tenant_subscription_sandbox_returns_canceled():
    from services.tenant_billing_stripe import cancel_tenant_subscription
    r = _run(cancel_tenant_subscription("sub_test_123"))
    assert r["status"] == "canceled"
    assert r["canceled_at"]
