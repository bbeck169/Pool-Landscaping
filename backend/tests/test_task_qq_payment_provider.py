"""Task QQ · Feb 2026 — payment-provider abstraction tests."""
from __future__ import annotations

import asyncio
import hmac
import hashlib
import json
import os
import pytest


def _sync(coro):
    """Run coroutine on the existing loop so Motor's global loop
    stays alive for later tests. Using ``asyncio.run`` per-test
    closes the loop and breaks any later Motor call."""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Reset payments-related env + factory cache between tests."""
    for k in (
        "PAYMENT_PROVIDER", "LUMINO_API_URL", "LUMINO_API_TOKEN",
        "LUMINO_WEBHOOK_SECRET", "LUMINO_RETURN_URL",
        "PAYMENTS_TEST_ALLOWLIST_CUSTOMERS", "APP_ENV",
    ):
        monkeypatch.delenv(k, raising=False)
    from services.payments import reset_provider_cache
    reset_provider_cache()
    yield
    reset_provider_cache()


def _reload_factory():
    from services.payments import get_payment_provider, reset_provider_cache
    reset_provider_cache()
    return get_payment_provider()


# ══════════════════════════════════════════════════════════════════
# Factory selection.
# ══════════════════════════════════════════════════════════════════
def test_factory_defaults_to_stripe(monkeypatch):
    p = _reload_factory()
    assert p.name == "stripe"


def test_factory_returns_lumino_when_env_set(monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER", "lumino")
    p = _reload_factory()
    assert p.name == "lumino"


def test_factory_unknown_falls_back_to_stripe(monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER", "nonsense")
    p = _reload_factory()
    assert p.name == "stripe"


# ══════════════════════════════════════════════════════════════════
# Lumino not-configured state.
# ══════════════════════════════════════════════════════════════════
def test_lumino_not_configured_raises(monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER", "lumino")
    monkeypatch.setenv("APP_ENV", "production")
    from services.payments import PaymentProviderNotConfigured
    p = _reload_factory()
    import asyncio
    with pytest.raises(PaymentProviderNotConfigured):
        _sync(p.create_customer(email="anyone@aquaterra.com"))


# ══════════════════════════════════════════════════════════════════
# Test-scope safety rail — NO LIVE CUSTOMERS.
# ══════════════════════════════════════════════════════════════════
def test_scope_violation_refuses_non_synthetic_customer(monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER", "lumino")
    monkeypatch.setenv("APP_ENV", "preview")
    from services.payments import PaymentTestScopeViolation
    p = _reload_factory()
    import asyncio
    with pytest.raises(PaymentTestScopeViolation):
        _sync(p.create_customer(email="real-person@gmail.com"))


def test_scope_allows_aquaterra_domain_synthetic(monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER", "lumino")
    monkeypatch.setenv("APP_ENV", "preview")
    from services.payments import PaymentProviderDryRun
    p = _reload_factory()
    import asyncio
    # Synthetic domain → passes scope → dry-run short-circuit fires.
    with pytest.raises(PaymentProviderDryRun) as ex:
        _sync(p.create_customer(email="fixture@aquaterra.com"))
    assert ex.value.payload["status"] == "dry_run"
    assert ex.value.payload["provider"] == "lumino"


def test_scope_allows_plofv_domain(monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER", "lumino")
    monkeypatch.setenv("APP_ENV", "preview")
    from services.payments import PaymentProviderDryRun
    p = _reload_factory()
    import asyncio
    with pytest.raises(PaymentProviderDryRun):
        _sync(p.create_customer(email="brian@plofv.com"))


def test_scope_allowlist_explicit_opt_in(monkeypatch):
    """Explicit allow-list entry bypasses dry-run — actually hits the
    wire (which fails because env not configured). This proves the
    scope rail lets allow-listed refs through."""
    monkeypatch.setenv("PAYMENT_PROVIDER", "lumino")
    monkeypatch.setenv("APP_ENV", "preview")
    monkeypatch.setenv("PAYMENTS_TEST_ALLOWLIST_CUSTOMERS",
                          "explicit-smoke-test@vendor.example")
    from services.payments import PaymentProviderNotConfigured
    p = _reload_factory()
    import asyncio
    # Allow-listed → scope passes AND dry-run passes → we hit the
    # "not configured" bail because no LUMINO_API_TOKEN is set.
    with pytest.raises(PaymentProviderNotConfigured):
        _sync(p.create_customer(email="explicit-smoke-test@vendor.example"))


# ══════════════════════════════════════════════════════════════════
# Dry-run short-circuit.
# ══════════════════════════════════════════════════════════════════
def test_dry_run_short_circuits_payment_session(monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER", "lumino")
    monkeypatch.setenv("APP_ENV", "preview")
    from services.payments import PaymentProviderDryRun
    p = _reload_factory()
    import asyncio
    with pytest.raises(PaymentProviderDryRun) as ex:
        _sync(p.create_payment_session(
            customer_ref="fixture@aquaterra.com",
            amount_cents=1000, currency="usd",
        ))
    payload = ex.value.payload
    assert payload["status"] == "dry_run"
    assert payload["kind"] == "payment_session"
    assert payload["amount_cents"] == 1000


# ══════════════════════════════════════════════════════════════════
# Webhook signature verification.
# ══════════════════════════════════════════════════════════════════
def test_webhook_signature_verify_accepts_valid(monkeypatch):
    secret = "test-secret-abc123"
    monkeypatch.setenv("PAYMENT_PROVIDER", "lumino")
    monkeypatch.setenv("LUMINO_WEBHOOK_SECRET", secret)
    p = _reload_factory()
    body = b'{"id": "evt_1", "type": "payment.succeeded"}'
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert p.verify_webhook(raw_body=body, signature_header=sig) is True
    assert p.verify_webhook(raw_body=body,
                                signature_header=f"sha256={sig}") is True


def test_webhook_signature_rejects_tampered(monkeypatch):
    secret = "test-secret-abc123"
    monkeypatch.setenv("PAYMENT_PROVIDER", "lumino")
    monkeypatch.setenv("LUMINO_WEBHOOK_SECRET", secret)
    p = _reload_factory()
    body = b'{"id": "evt_1"}'
    assert p.verify_webhook(raw_body=body,
                                signature_header="deadbeef") is False


def test_webhook_signature_no_secret_refuses(monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER", "lumino")
    p = _reload_factory()
    assert p.verify_webhook(raw_body=b"{}",
                                signature_header="anything") is False


def test_webhook_parse_event_returns_dict(monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER", "lumino")
    p = _reload_factory()
    evt = p.parse_webhook_event(raw_body=b'{"id":"evt_1","type":"x"}')
    assert evt["id"] == "evt_1"
    assert evt["type"] == "x"


# ══════════════════════════════════════════════════════════════════
# Migration script — dry-run enumeration compiles + runs safely.
# ══════════════════════════════════════════════════════════════════
def test_migration_script_dry_run_default(monkeypatch, capsys):
    """Exercise the enumeration function directly rather than the
    outer ``main`` wrapper. ``main`` calls ``asyncio.run`` which
    closes Motor's global loop for the rest of the pytest process
    — that's fine when the script is invoked from the CLI (fresh
    process) but breaks when pytest chains multiple loops. This
    test still proves the enumeration + stat-shape contract."""
    import sys, importlib, asyncio
    sys.path.insert(0, "/app/backend/scripts")
    mod = importlib.import_module("migrate_stripe_to_lumino")
    from config import db
    async def _go():
        tenant_id = await mod._resolve_default_tenant(db)
        return await mod.migrate(tenant_id=tenant_id, live=False)
    result = asyncio.get_event_loop().run_until_complete(_go())
    assert isinstance(result, dict)
    for key in ("customers", "payment_methods", "subscriptions",
                    "skipped_already_migrated"):
        assert key in result


def test_migration_script_argparse_shape():
    """Verify the safety flags are wired into argparse without
    invoking asyncio.run (Motor's global loop only survives one
    ``asyncio.run`` per pytest process)."""
    import sys, importlib
    sys.path.insert(0, "/app/backend/scripts")
    mod = importlib.import_module("migrate_stripe_to_lumino")
    ns = mod._parse(["--tenant-id", "T1", "--live",
                        "--i-know-this-is-production"])
    assert ns.tenant_id == "T1"
    assert ns.live is True
    assert ns.i_know_this_is_production is True
    # Defaults — dry-run, no production flag.
    ns2 = mod._parse([])
    assert ns2.live is False
    assert ns2.i_know_this_is_production is False
    assert ns2.tenant_id is None
