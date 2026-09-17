"""Feb-2026 · Payment Processor ticket · static-config failover priority."""
from __future__ import annotations

import pytest

from services.payments_byo import failover_router as fr
from services.payments_byo.stripe_provider import StripeByoProvider
from services.payments_byo.lumino_provider import LuminoProvider


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


class _FakeCollection:
    def __init__(self):
        self._rows = []
        self.insert_one_called = 0

    async def insert_one(self, doc):
        self.insert_one_called += 1
        self._rows.append(dict(doc))
        return None


class _FakeTenants:
    def __init__(self, doc):
        self._doc = doc

    async def find_one(self, filter_, projection=None):
        return dict(self._doc)


class _FakeDB:
    def __init__(self, tenant_doc):
        self.tenants = _FakeTenants(tenant_doc)
        self._collections = {}

    def __getitem__(self, name):
        if name not in self._collections:
            self._collections[name] = _FakeCollection()
        return self._collections[name]


@pytest.fixture(autouse=True)
def _reset_secret_cache(monkeypatch):
    """Isolate each test from any real ``services.secrets`` state."""
    async def _no_cfg(*, tenant_id, provider_key, db=None):
        return None
    monkeypatch.setattr(
        "services.payments_byo.failover_router.load_provider_config",
        _no_cfg,
        raising=False,
    )
    # ^ ``load_provider_config`` is imported lazily inside
    # ``_provider_is_configured``. Patch the ``_helpers`` symbol
    # directly so the lazy import picks the fake up.
    from services.payments_byo import _helpers as _h
    monkeypatch.setattr(_h, "load_provider_config", _no_cfg)


@pytest.mark.anyio
async def test_primary_configured_returns_primary(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_ok")
    db = _FakeDB({"settings": {"payment": {
        "primary_provider": "stripe", "backup_provider": "lumino",
    }}})
    p = await fr.get_provider_for_operation(
        tenant_id="t1", operation="create_charge", db=db,
    )
    assert isinstance(p, StripeByoProvider)
    # No audit row when primary is used.
    assert db["payment_failover_audit"].insert_one_called == 0


@pytest.mark.anyio
async def test_primary_unconfigured_returns_backup(monkeypatch):
    """Stripe env unset + Lumino tenant-config present → backup."""
    monkeypatch.delenv("STRIPE_SECRET_KEY_TEST", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY_LIVE", raising=False)
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)

    async def _cfg(*, tenant_id, provider_key, db=None):
        return {"api_key": "test"} if provider_key == LuminoProvider.provider_key else None
    from services.payments_byo import _helpers as _h
    monkeypatch.setattr(_h, "load_provider_config", _cfg)

    db = _FakeDB({"settings": {"payment": {
        "primary_provider": "stripe", "backup_provider": "lumino",
    }}})
    p = await fr.get_provider_for_operation(
        tenant_id="t1", operation="create_charge", db=db,
    )
    assert isinstance(p, LuminoProvider)
    # Static-config failover writes an audit row.
    assert db["payment_failover_audit"].insert_one_called == 1
    row = db["payment_failover_audit"]._rows[-1]
    assert row["resolution"] == "static_config"
    assert row["primary_provider"] == "stripe"
    assert row["backup_provider"] == "lumino"
    assert "unconfigured" in row["error_from_primary"]


@pytest.mark.anyio
async def test_both_unconfigured_raises(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY_TEST", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY_LIVE", raising=False)
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    db = _FakeDB({"settings": {"payment": {
        "primary_provider": "stripe", "backup_provider": "lumino",
    }}})
    with pytest.raises(fr.PaymentProviderUnavailableError):
        await fr.get_provider_for_operation(
            tenant_id="t1", operation="create_charge", db=db,
        )


@pytest.mark.anyio
async def test_missing_settings_falls_back_to_stripe_default(monkeypatch):
    """No ``settings.payment`` at all → default primary is stripe."""
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_ok")
    db = _FakeDB({})
    p = await fr.get_provider_for_operation(
        tenant_id="t1", operation="create_charge", db=db,
    )
    assert isinstance(p, StripeByoProvider)
