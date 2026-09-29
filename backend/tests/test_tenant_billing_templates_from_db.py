"""Phase EMAIL-MIGRATE · Batch 3 · Feb-2026 — DB-first render for the
tenant-billing trial-reminder + dunning emails.

Locks two contracts:

1. English-locale recipients see the DB body from
   ``tenant_billing_trial_reminder_email`` /
   ``tenant_billing_dunning_email``.
2. Non-English recipients continue to use the on-disk D5
   notification-template triplets (decision (c)).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _orig = _cfg.db
    _cfg.db = fresh_db
    try:
        yield
    finally:
        _cfg.db = _orig
        try:
            fresh.close()
        except Exception:
            pass


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(
        os.environ["MONGO_URL"], io_loop=_LOOP,
    )[os.environ["DB_NAME"]]


async def _wipe(tid: str) -> None:
    await _db().marketing_templates.delete_many({
        "code": {"$in": ["tenant_billing_trial_reminder_email",
                          "tenant_billing_dunning_email"]},
    })
    await _db().tenants.delete_many({"id": tid})
    await _db().users.delete_many({"tenant_id": tid})


async def _seed_tenant(tid: str, *, locale: str = "en",
                          trial_end_utc: str = "") -> None:
    from utils import now_iso
    await _db().tenants.insert_one({
        "id": tid, "name": "Billing Co",
        "default_locale": locale,
        "billing_status": "trialing",
        "trial_end_utc": trial_end_utc,
        "trial_reminder_sent_at": None,
        "created_at": now_iso(), "updated_at": now_iso(),
    })


async def _seed_admin(tid: str, *, locale: str = "en") -> None:
    from utils import new_id, now_iso
    await _db().users.insert_one({
        "id": new_id(), "tenant_id": tid, "role": "admin",
        "email": "ops@billing.co", "name": "Ops Alice",
        "locale": locale,
        "created_at": now_iso(),
    })


async def _seed_row(*, code: str, tenant_id_scope, body: str) -> None:
    from utils import new_id, now_iso
    await _db().marketing_templates.insert_one({
        "id": new_id(), "code": code, "tenant_id": tenant_id_scope,
        "subject": "ignored", "body": body,
        "category": "billing", "channel": "email",
        "kind": "transactional",
        "is_system": True, "is_default": True, "editable": True,
        "created_at": now_iso(), "updated_at": now_iso(),
    })


class _Capture:
    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    async def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return {"provider_status": "sent",
                "provider_response_id": "test"}


# ── Trial reminder ─────────────────────────────────────────────────
def test_trial_reminder_db_body_wins_for_english_recipient(monkeypatch):
    from services.tenant_billing_reminders import (
        run_trial_ending_reminders,
    )

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        # Schedule trial-end 24h out so the reminder cron fires.
        now = datetime.now(timezone.utc)
        end = (now + timedelta(hours=24)).isoformat()
        await _wipe(tid)
        await _seed_tenant(tid, trial_end_utc=end)
        await _seed_admin(tid)
        sentinel = f"TRIAL-{uuid.uuid4().hex[:8]}"
        await _seed_row(
            code="tenant_billing_trial_reminder_email",
            tenant_id_scope=None,
            body=(
                f"<div>{sentinel} Hi {{{{ADMIN_NAME}}}} @ "
                f"{{{{COMPANY_NAME}}}} — cancel at "
                f"{{{{CANCEL_LINK}}}} (ends {{{{TRIAL_END_LOCAL}}}}, "
                f"{{{{PLAN_AMOUNT}}}})</div>"
            ),
        )
        capture = _Capture()
        monkeypatch.setattr(
            "services.email.resend_adapter.send", capture,
        )
        try:
            result = await run_trial_ending_reminders(_db(), now=now)
            assert result["sent"] == 1
            html = capture.calls[0]["kwargs"]["html"]
            assert sentinel in html
            assert "Ops Alice" in html
            assert "Billing Co" in html
            assert "/settings/billing" in html
        finally:
            await _wipe(tid)

    _run(_go())


def test_trial_reminder_non_english_uses_i18n_fallback(monkeypatch):
    from services.tenant_billing_reminders import (
        run_trial_ending_reminders,
    )

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc)
        end = (now + timedelta(hours=24)).isoformat()
        await _wipe(tid)
        # ES locale on the tenant + admin.
        await _seed_tenant(tid, locale="es", trial_end_utc=end)
        await _seed_admin(tid, locale="es")
        forbidden = f"FORBIDDEN-{uuid.uuid4().hex[:8]}"
        await _seed_row(
            code="tenant_billing_trial_reminder_email",
            tenant_id_scope=None,
            body=f"<p>{forbidden}</p>",
        )
        capture = _Capture()
        monkeypatch.setattr(
            "services.email.resend_adapter.send", capture,
        )
        try:
            result = await run_trial_ending_reminders(_db(), now=now)
            assert result["sent"] == 1
            html = capture.calls[0]["kwargs"]["html"]
            assert forbidden not in html, (
                "Non-English recipient must not receive the DB body"
            )
        finally:
            await _wipe(tid)

    _run(_go())


# ── Dunning / payment-failed ────────────────────────────────────────
def test_dunning_db_body_wins_for_english_recipient(monkeypatch):
    from services.tenant_billing_webhooks import (
        handle_tenant_billing_event,
    )

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        await _wipe(tid)
        await _seed_tenant(tid)
        await _seed_admin(tid)
        sentinel = f"DUNNING-{uuid.uuid4().hex[:8]}"
        await _seed_row(
            code="tenant_billing_dunning_email",
            tenant_id_scope=None,
            body=(
                f"<div>{sentinel} {{{{ADMIN_NAME}}}} — "
                f"card at {{{{UPDATE_CARD_LINK}}}}</div>"
            ),
        )
        capture = _Capture()
        monkeypatch.setattr(
            "services.email.resend_adapter.send", capture,
        )
        try:
            event = {
                "type": "invoice.payment_failed",
                "data": {"object": {
                    "metadata": {
                        "crm_billing_kind": "tenant_platform_fee",
                        "crm_tenant_id": tid,
                    },
                }},
            }
            result = await handle_tenant_billing_event(event, _db())
            assert result["handled"] is True
            assert result["action"] == "past_due"
            html = capture.calls[0]["kwargs"]["html"]
            assert sentinel in html
            assert "Ops Alice" in html
            assert "/settings/billing" in html
        finally:
            await _wipe(tid)

    _run(_go())


def test_dunning_non_english_uses_i18n_fallback(monkeypatch):
    from services.tenant_billing_webhooks import (
        handle_tenant_billing_event,
    )

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        await _wipe(tid)
        await _seed_tenant(tid, locale="es")
        await _seed_admin(tid, locale="es")
        forbidden = f"FORBIDDEN-{uuid.uuid4().hex[:8]}"
        await _seed_row(
            code="tenant_billing_dunning_email",
            tenant_id_scope=None,
            body=f"<p>{forbidden}</p>",
        )
        capture = _Capture()
        monkeypatch.setattr(
            "services.email.resend_adapter.send", capture,
        )
        try:
            event = {
                "type": "invoice.payment_failed",
                "data": {"object": {
                    "metadata": {
                        "crm_billing_kind": "tenant_platform_fee",
                        "crm_tenant_id": tid,
                    },
                }},
            }
            await handle_tenant_billing_event(event, _db())
            html = capture.calls[0]["kwargs"]["html"]
            assert forbidden not in html
        finally:
            await _wipe(tid)

    _run(_go())
