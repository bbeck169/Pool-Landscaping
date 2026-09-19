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

Feb-2026 P2 tech-debt · migrated off the module-global
``_LOOP + AsyncIOMotorClient`` + ``monkeypatch(_default_db)``
pattern (which hung on collection due to Motor loop rebinding
racing with ``services.secrets.store._default_db``). Uses the
canonical ``run_test(coro_factory)`` helper from
``tests._f7_loop_fixture`` — the same pattern already in use by
``test_reorder_day_route.py``, ``test_recurring_job_end_date.py``,
etc. ``config.db`` is the only global handle in the messaging
dispatch path (both ``services.messaging.dispatch._log_fallback``
and ``services.secrets.store._default_db`` resolve it lazily), so
the standard ``_REBOUND_MODULES`` list already covers everything —
no fixture extension required.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv
from pymongo import MongoClient

from tests._f7_loop_fixture import run_test

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


@pytest.fixture(autouse=True)
def _wipe():
    _reset_sms()
    _reset_email()
    _sync[FALLBACK_LOG_COLLECTION].delete_many({"tenant_id": TENANT})
    _sync.tenant_secrets.delete_many({"tenant_id": TENANT})
    yield
    _sync[FALLBACK_LOG_COLLECTION].delete_many({"tenant_id": TENANT})
    _sync.tenant_secrets.delete_many({"tenant_id": TENANT})


def test_sms_dispatch_falls_back_and_audits(monkeypatch):
    calls = []

    async def _fake_platform(tenant_id, to, body, mms_url=None):
        calls.append({"tenant_id": tenant_id, "to": to, "body": body})
        return {"status": "sent", "provider_id": "platform_1", "provider_key": "platform_default"}

    import services.comms_sms_adapter as legacy
    monkeypatch.setattr(legacy, "send_sms", _fake_platform, raising=True)
    monkeypatch.setenv("MESSAGING_PLATFORM_FALLBACK_ENABLED", "true")

    result = run_test(lambda db: dispatch_sms(
        tenant_id=TENANT, to="+15559999999", body="hi", db=db,
    ))
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

    result = run_test(lambda db: dispatch_email(
        tenant_id=TENANT, to=["dest@example.com"],
        subject="hi", html_body="<b>hi</b>", db=db,
    ))
    assert result["status"] == "sent"
    assert calls and calls[0]["to"] == "dest@example.com"

    entries = list(_sync[FALLBACK_LOG_COLLECTION].find({"tenant_id": TENANT, "kind": "email"}))
    assert len(entries) == 1


def test_sms_dispatch_fails_when_fallback_disabled_and_no_tenant_provider(monkeypatch):
    monkeypatch.setenv("MESSAGING_PLATFORM_FALLBACK_ENABLED", "false")
    result = run_test(lambda db: dispatch_sms(
        tenant_id=TENANT, to="+15559999999", body="hi", db=db,
    ))
    assert result["status"] == "failed"
    assert "fallback disabled" in (result.get("error") or "")
    entries = list(_sync[FALLBACK_LOG_COLLECTION].find({"tenant_id": TENANT}))
    assert entries == []


def test_email_dispatch_fails_when_fallback_disabled_and_no_tenant_provider(monkeypatch):
    monkeypatch.setenv("MESSAGING_PLATFORM_FALLBACK_ENABLED", "false")
    result = run_test(lambda db: dispatch_email(
        tenant_id=TENANT, to=["x@example.com"],
        subject="hi", html_body="<b>hi</b>", db=db,
    ))
    assert result["status"] == "failed"
    entries = list(_sync[FALLBACK_LOG_COLLECTION].find({"tenant_id": TENANT}))
    assert entries == []
