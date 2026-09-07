"""Phase I1.7.b · Feb-2026 — Email send-flow smoke via EMAIL_TESTMODE_MOCK."""
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
from services.messaging.email.registry import (  # noqa: E402
    get_email_provider,
    list_registered_email_provider_keys,
    reset_cache_for_tests,
)


TENANT = f"i17b-email-send-{uuid.uuid4().hex[:8]}"


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
        import services.secrets.store as _store
        _store._default_db = lambda: _MOTOR_DB   # type: ignore
    return _LOOP, _MOTOR_DB


def _drive(coro_factory):
    loop, db = _setup_loop()
    return loop.run_until_complete(coro_factory(db))


@pytest.fixture(autouse=True)
def _clean_and_flag(monkeypatch):
    monkeypatch.setenv("EMAIL_TESTMODE_MOCK", "true")
    reset_cache_for_tests()
    yield
    _sync.tenant_secrets.delete_many({"tenant_id": TENANT})


@pytest.mark.parametrize("provider_key,cfg", [
    ("resend",   {"api_key": "re_test_XXXXXXXX", "from_addr": "hello@example.com"}),
    ("sendgrid", {"api_key": "SG.test.YYYYYYYY", "from_addr": "hello@example.com"}),
    ("postmark", {"server_token": "pm-test-token", "from_addr": "hello@example.com"}),
    ("mailgun",  {"api_key": "key-test", "domain": "mg.example.com",
                    "from_addr": "hello@example.com"}),
    ("smtp",     {"host": "smtp.example.com", "port": 587,
                    "username": "u", "password": "p",
                    "from_addr": "hello@example.com"}),
])
def test_email_send_mock_returns_queued_or_sent(provider_key, cfg):
    schema = get_email_provider(provider_key).config_fields
    _drive(lambda db: save_provider_config(
        tenant_id=TENANT, provider_key=provider_key,
        config=cfg, schema=schema, db=db,
    ))
    provider = get_email_provider(provider_key)
    result = _drive(lambda db: provider.send_email(
        tenant_id=TENANT, to=["dest@example.com"],
        subject="I17b probe", html_body="<b>hello</b>",
        text_body="hello",
    ))
    assert result.status in ("queued", "sent")
    assert result.provider_key == provider_key
    assert result.id  # non-empty mock id


def test_email_test_connection_returns_ok_false_when_not_configured():
    async def _probe(db):
        results = []
        for key in list_registered_email_provider_keys():
            provider = get_email_provider(key)
            r = await provider.test_connection(tenant_id=f"never-configured-{uuid.uuid4().hex[:8]}")
            results.append(r)
        return results
    for r in _drive(_probe):
        assert r.ok is False
        assert "No " in r.message
