"""Phase I1.7.b · Feb-2026 — SMS send-flow smoke via SMS_TESTMODE_MOCK.

Uses the mock env flag so we exercise the real adapter code path
without any outbound HTTP. Also seeds a real tenant secret via
``put_secret`` so ``test_connection`` succeeds on the mock branch.
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

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

_sync = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

from services.messaging._helpers import save_provider_config  # noqa: E402
from services.messaging.sms.registry import (  # noqa: E402
    get_sms_provider,
    list_registered_sms_provider_keys,
    reset_cache_for_tests,
)


TENANT = f"i17b-sms-send-{uuid.uuid4().hex[:8]}"


# One persistent event loop for the whole file so Motor's default
# client (bound at import time) and the per-test Motor client both
# live on the same loop.
_LOOP: asyncio.AbstractEventLoop | None = None
_MOTOR_CLIENT: AsyncIOMotorClient | None = None
_MOTOR_DB = None


def _setup_loop():
    global _LOOP, _MOTOR_CLIENT, _MOTOR_DB
    if _LOOP is None:
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
        _MOTOR_CLIENT = AsyncIOMotorClient(os.environ["MONGO_URL"])
        _MOTOR_DB = _MOTOR_CLIENT[os.environ["DB_NAME"]]
        # Force ``services.secrets.store._default_db`` to use OUR db
        # so the provider's default-db path uses the same loop.
        import services.secrets.store as _store
        _store._default_db = lambda: _MOTOR_DB   # type: ignore
    return _LOOP, _MOTOR_DB


def _drive(coro_factory):
    loop, db = _setup_loop()
    return loop.run_until_complete(coro_factory(db))


@pytest.fixture(autouse=True)
def _clean_and_flag(monkeypatch):
    monkeypatch.setenv("SMS_TESTMODE_MOCK", "true")
    reset_cache_for_tests()
    yield
    _sync.tenant_secrets.delete_many({"tenant_id": TENANT})


@pytest.mark.parametrize("provider_key,cfg", [
    ("twilio", {"account_sid": "ACxxxxxxxxxxxxxxxxxxxxxxxx",
                "auth_token": "totally-secret", "from_number": "+15551234567"}),
    ("textmagic", {"username": "tenant_user", "api_key": "tm_test_key",
                    "from_number": "+15551234567"}),
    ("ringcentral", {"server_url": "https://platform.ringcentral.com",
                       "client_id": "cid", "client_secret": "csecret",
                       "jwt_token": "jwt_body_here", "from_number": "+15551234567"}),
])
def test_sms_send_mock_returns_queued_result(provider_key, cfg):
    schema = get_sms_provider(provider_key).config_fields
    _drive(lambda db: save_provider_config(
        tenant_id=TENANT, provider_key=provider_key,
        config=cfg, schema=schema, db=db,
    ))
    provider = get_sms_provider(provider_key)
    result = _drive(lambda db: provider.send_sms(
        tenant_id=TENANT, to="+15559999999", body="I17b hello world",
    ))
    assert result.status == "queued"
    assert result.provider_key == provider_key
    assert result.id.startswith(("SM_test_", "TM_test_", "rc_test_"))


def test_sms_test_connection_mock_ok():
    reset_cache_for_tests()
    schema = get_sms_provider("twilio").config_fields
    _drive(lambda db: save_provider_config(
        tenant_id=TENANT, provider_key="twilio",
        config={"account_sid": "ACabcdef1234", "auth_token": "x",
                "from_number": "+15551234567"},
        schema=schema, db=db,
    ))
    provider = get_sms_provider("twilio")
    # Route through the shared driver so both the encrypted-secret
    # lookup and Motor client attach to the same event loop.
    async def _probe(db):
        from services.secrets.store import get_secret as _get
        # Warm the cfg via the provider's private path.
        cfg = await _get(TENANT, "twilio", db=db)
        assert cfg is not None
        return await provider.test_connection(tenant_id=TENANT)
    result = _drive(_probe)
    assert result.ok is True
    assert result.provider_key == "twilio"


def test_sms_test_connection_returns_ok_false_when_not_configured():
    async def _probe(db):
        results = []
        for key in list_registered_sms_provider_keys():
            provider = get_sms_provider(key)
            r = await provider.test_connection(tenant_id=f"never-configured-{uuid.uuid4().hex[:8]}")
            results.append(r)
        return results
    for r in _drive(_probe):
        assert r.ok is False
        assert "No " in r.message
