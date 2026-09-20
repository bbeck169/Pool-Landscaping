"""Phase I1.7.a · Feb-2026 — Platform-Stripe fallback audit lock.

Verifies:
  1. When ``STRIPE_PLATFORM_FALLBACK_ENABLED=true`` (default) and the
     tenant has no connection, ``_resolve_auth`` returns the platform
     secret key AND writes a fallback-log entry.
  2. When fallback is disabled and no connection exists,
     ``TenantNotConnected`` is raised.
  3. When the tenant IS connected, the tenant's own access token is
     used (no fallback log entry).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

_sync = _shared_db()
from services.payments.tenant_base import TenantNotConnected  # noqa: E402
from services.payments.tenant_stripe import (  # noqa: E402
    FALLBACK_LOG_COLLECTION,
    StripeConnectProvider,
    _fallback_enabled,
    _platform_secret_key,
)
from services.secrets import put_secret, remove_secret  # noqa: E402
from services.secrets.models import ConnectionType  # noqa: E402


TENANT_A = f"i17a-fallback-tenant-{uuid.uuid4().hex[:8]}"


def _drive(coro_factory):
    async def _wrap():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        try:
            return await coro_factory(db)
        finally:
            client.close()
    return asyncio.run(_wrap())


@pytest.fixture(autouse=True)
def _clean():
    yield
    _sync.tenant_secrets.delete_many({"tenant_id": TENANT_A})
    _sync[FALLBACK_LOG_COLLECTION].delete_many({"tenant_id": TENANT_A})


class TestFallback:
    def test_fallback_env_default_is_true(self):
        assert _fallback_enabled() is True

    def test_platform_secret_key_is_configured(self):
        assert _platform_secret_key(), "STRIPE_SECRET_KEY_TEST must be set in .env"

    def test_no_connection_falls_back_and_logs(self):
        _sync.tenant_secrets.delete_many({"tenant_id": TENANT_A})
        provider = StripeConnectProvider()
        # Call the private ``_resolve_auth`` directly — that's the
        # decision point where fallback logs.
        api_key = _drive(lambda db: provider._resolve_auth(TENANT_A, "test_op", db=db))
        assert api_key == _platform_secret_key()
        rows = list(_sync[FALLBACK_LOG_COLLECTION].find({"tenant_id": TENANT_A}))
        assert len(rows) == 1
        assert rows[0]["op"] == "test_op"

    def test_fallback_disabled_raises_not_connected(self, monkeypatch):
        monkeypatch.setenv("STRIPE_PLATFORM_FALLBACK_ENABLED", "false")
        _sync.tenant_secrets.delete_many({"tenant_id": TENANT_A})
        provider = StripeConnectProvider()
        with pytest.raises(TenantNotConnected):
            _drive(lambda db: provider._resolve_auth(TENANT_A, "test_op", db=db))
        # No fallback log written.
        rows = list(_sync[FALLBACK_LOG_COLLECTION].find({"tenant_id": TENANT_A}))
        assert rows == []

    def test_connected_tenant_uses_own_token(self):
        _drive(lambda db: put_secret(
            TENANT_A, "stripe", "sk_test_tenant_owned_token_xxxxxxx",
            connection_type=ConnectionType.OAUTH_STRIPE_CONNECT,
            connected_account_id="acct_tenant_owned", db=db,
        ))
        provider = StripeConnectProvider()
        api_key = _drive(lambda db: provider._resolve_auth(TENANT_A, "any_op", db=db))
        assert api_key == "sk_test_tenant_owned_token_xxxxxxx"
        # Fallback log MUST NOT fire on the connected path.
        rows = list(_sync[FALLBACK_LOG_COLLECTION].find({"tenant_id": TENANT_A}))
        assert rows == []
        # Cleanup
        _drive(lambda db: remove_secret(TENANT_A, "stripe", db=db))
