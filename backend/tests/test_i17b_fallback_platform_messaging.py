"""Phase I1.7.b · Feb-2026 — Platform messaging fallback + audit log.

Covers:
  1. ``dispatch_sms`` with no tenant provider configured routes to
     the legacy ``comms_sms_adapter.send_sms`` and appends to
     ``platform_messaging_fallback_log``.
  2. ``dispatch_email`` behaves the same way.
  3. When ``MESSAGING_PLATFORM_FALLBACK_ENABLED=false`` and no
     tenant provider is configured, ``dispatch_*`` returns
     ``{"status": "failed"}`` and does NOT log a fallback entry
     (nothing to audit).
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

from services.messaging import (  # noqa: E402
    FALLBACK_LOG_COLLECTION,
    dispatch_email,
    dispatch_sms,
)
from services.messaging.email.registry import reset_cache_for_tests as _reset_email  # noqa: E402
from services.messaging.sms.registry import reset_cache_for_tests as _reset_sms  # noqa: E402


TENANT = f"i17b-fallback-{uuid.uuid4().hex[:8]}"


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
        # ``dispatch._log_fallback`` also uses config.db by default —
        # replace it with a small wrapper that picks up OUR db.
        import services.messaging.dispatch as _dispatch
        _orig = _dispatch._log_fallback
        async def _wrapper(*, tenant_id, kind, reason, db=None):
            return await _orig(tenant_id=tenant_id, kind=kind,
                                reason=reason, db=db or _MOTOR_DB)
        _dispatch._log_fallback = _wrapper   # type: ignore
    return _LOOP, _MOTOR_DB


@pytest.fixture(autouse=True)
def _wipe():
    _reset_sms()
    _reset_email()
    _sync[FALLBACK_LOG_COLLECTION].delete_many({"tenant_id": TENANT})
    _sync.tenant_secrets.delete_many({"tenant_id": TENANT})
    yield
    _sync[FALLBACK_LOG_COLLECTION].delete_many({"tenant_id": TENANT})
    _sync.tenant_secrets.delete_many({"tenant_id": TENANT})


def _run(coro):
    loop, _db = _setup_loop()
    return loop.run_until_complete(coro)


def test_sms_dispatch_falls_back_and_audits(monkeypatch):
    calls = []

    async def _fake_platform(tenant_id, to, body, mms_url=None):
        calls.append({"tenant_id": tenant_id, "to": to, "body": body})
        return {"status": "sent", "provider_id": "platform_1", "provider_key": "platform_default"}

    import services.comms_sms_adapter as legacy
    monkeypatch.setattr(legacy, "send_sms", _fake_platform, raising=True)
    monkeypatch.setenv("MESSAGING_PLATFORM_FALLBACK_ENABLED", "true")

    result = _run(dispatch_sms(tenant_id=TENANT, to="+15559999999", body="hi"))
    assert result["status"] == "sent"
    assert calls and calls[0]["to"] == "+15559999999"

    entries = list(_sync[FALLBACK_LOG_COLLECTION].find({"tenant_id": TENANT, "kind": "sms"}))
    assert len(entries) == 1
    assert entries[0]["reason"] == "no_tenant_provider"


def test_email_dispatch_falls_back_and_audits(monkeypatch):
    calls = []

    async def _fake_platform(tenant_id, to, subject, html, from_name=None, from_email=None):
        calls.append({"tenant_id": tenant_id, "to": to, "subject": subject})
        return {"status": "sent", "provider_id": "platform_email_1"}

    import services.comms_email_adapter as legacy
    monkeypatch.setattr(legacy, "send_email", _fake_platform, raising=True)
    monkeypatch.setenv("MESSAGING_PLATFORM_FALLBACK_ENABLED", "true")

    result = _run(dispatch_email(
        tenant_id=TENANT, to=["dest@example.com"],
        subject="hi", html_body="<b>hi</b>",
    ))
    assert result["status"] == "sent"
    assert calls and calls[0]["to"] == "dest@example.com"

    entries = list(_sync[FALLBACK_LOG_COLLECTION].find({"tenant_id": TENANT, "kind": "email"}))
    assert len(entries) == 1


def test_sms_dispatch_fails_when_fallback_disabled_and_no_tenant_provider(monkeypatch):
    monkeypatch.setenv("MESSAGING_PLATFORM_FALLBACK_ENABLED", "false")
    result = _run(dispatch_sms(tenant_id=TENANT, to="+15559999999", body="hi"))
    assert result["status"] == "failed"
    assert "fallback disabled" in (result.get("error") or "")
    entries = list(_sync[FALLBACK_LOG_COLLECTION].find({"tenant_id": TENANT}))
    assert entries == []


def test_email_dispatch_fails_when_fallback_disabled_and_no_tenant_provider(monkeypatch):
    monkeypatch.setenv("MESSAGING_PLATFORM_FALLBACK_ENABLED", "false")
    result = _run(dispatch_email(
        tenant_id=TENANT, to=["x@example.com"],
        subject="hi", html_body="<b>hi</b>",
    ))
    assert result["status"] == "failed"
    entries = list(_sync[FALLBACK_LOG_COLLECTION].find({"tenant_id": TENANT}))
    assert entries == []
