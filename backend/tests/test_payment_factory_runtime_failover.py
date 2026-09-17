"""Feb-2026 · Payment Processor ticket · runtime failover retry path."""
from __future__ import annotations

import logging

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

    async def insert_one(self, doc):
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
        self._c = {}

    def __getitem__(self, name):
        if name not in self._c:
            self._c[name] = _FakeCollection()
        return self._c[name]


@pytest.fixture(autouse=True)
def _stub_env(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_ok")

    async def _cfg(*, tenant_id, provider_key, db=None):
        if provider_key == LuminoProvider.provider_key:
            return {
                "api_key": "test", "account_id": "acct_test",
                "webhook_secret": "whsec",
            }
        return None
    from services.payments_byo import _helpers as _h
    monkeypatch.setattr(_h, "load_provider_config", _cfg)


@pytest.mark.anyio
async def test_transient_error_triggers_backup(caplog):
    """Primary raises retryable → backup invoked + audit + WARNING."""
    db = _FakeDB({"settings": {"payment": {
        "primary_provider": "stripe", "backup_provider": "lumino",
    }}})

    calls = []

    async def _call(provider):
        calls.append(provider.short_name)
        if provider.short_name == "stripe":
            raise fr.ProviderTransientError("simulated 5xx")
        return {"ok": True, "provider": provider.short_name}

    with caplog.at_level(logging.WARNING, logger="payments_byo.failover"):
        result = await fr.with_failover(
            tenant_id="t1",
            operation="create_charge",
            call=_call,
            db=db,
        )
    assert result == {"ok": True, "provider": "lumino"}
    assert calls == ["stripe", "lumino"]

    row = db["payment_failover_audit"]._rows[-1]
    assert row["resolution"] == "backup_used"
    assert row["primary_provider"] == "stripe"
    assert row["backup_provider"] == "lumino"
    assert "ProviderTransientError" in row["error_from_primary"]

    warned = [r.message for r in caplog.records
              if r.levelno == logging.WARNING]
    assert any("failover_to=lumino" in m for m in warned)


@pytest.mark.anyio
async def test_non_retryable_error_bubbles_up_without_backup_call():
    """4xx-equivalent exception must NOT trigger backup retry."""
    db = _FakeDB({"settings": {"payment": {
        "primary_provider": "stripe", "backup_provider": "lumino",
    }}})

    calls = []

    async def _call(provider):
        calls.append(provider.short_name)
        raise ValueError("card_declined")

    with pytest.raises(ValueError):
        await fr.with_failover(
            tenant_id="t1", operation="create_charge",
            call=_call, db=db,
        )
    assert calls == ["stripe"]  # backup NEVER called
    assert db["payment_failover_audit"]._rows == []  # no audit row


@pytest.mark.anyio
async def test_transient_but_no_backup_ready_raises(monkeypatch):
    """Primary transient + backup unconfigured → exhausted audit + raise."""
    # Override cfg so nothing is configured on backup side.
    async def _no_cfg(*, tenant_id, provider_key, db=None):
        return None
    from services.payments_byo import _helpers as _h
    monkeypatch.setattr(_h, "load_provider_config", _no_cfg)

    db = _FakeDB({"settings": {"payment": {
        "primary_provider": "stripe", "backup_provider": "lumino",
    }}})

    async def _call(provider):
        raise fr.ProviderTransientError("boom")

    with pytest.raises(fr.ProviderTransientError):
        await fr.with_failover(
            tenant_id="t1", operation="create_charge",
            call=_call, db=db,
        )
    rows = db["payment_failover_audit"]._rows
    assert rows and rows[-1]["resolution"] == "exhausted"
