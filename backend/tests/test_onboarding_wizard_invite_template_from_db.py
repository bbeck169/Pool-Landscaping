"""Phase EMAIL-MIGRATE · Batch 1 · Feb-2026 — DB-first render for the
onboarding wizard team-invite email.

Two contracts:

1. When the recipient locale resolves to ``en`` and an
   ``onboarding_wizard_invite_email`` row exists, the DB body wins
   over the notification-template-triplet fallback.
2. When the locale resolves to non-English, the DB row is NOT
   consulted — the i18n path fires (decision (c)).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict

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
    import routers.signup_onboarding_wizard as _mod
    _orig_cfg = _cfg.db
    _orig_mod = getattr(_mod, "db", None)
    _cfg.db = fresh_db
    if _orig_mod is not None:
        _mod.db = fresh_db
    try:
        yield
    finally:
        _cfg.db = _orig_cfg
        if _orig_mod is not None:
            _mod.db = _orig_mod
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


async def _wipe_rows() -> None:
    await _db().marketing_templates.delete_many(
        {"code": "onboarding_wizard_invite_email"},
    )


def _capture_send(monkeypatch) -> Dict[str, Any]:
    captured: Dict[str, Any] = {}

    async def _fake_send(**kwargs):
        captured.update(kwargs)
        return {"provider": "mock", "provider_status": "queued",
                "provider_response_id": None, "attempts": 1, "error": None}

    from services.email import resend_adapter as _resend
    monkeypatch.setattr(_resend, "send", _fake_send, raising=True)
    return captured


def test_db_body_wins_for_english_recipient(monkeypatch):
    async def _go():
        await _wipe_rows()
        from utils import new_id, now_iso
        sentinel = f"WIZINV-SENTINEL-{uuid.uuid4().hex[:8]}"
        await _db().marketing_templates.insert_one({
            "id": new_id(),
            "code": "onboarding_wizard_invite_email",
            "tenant_id": None,
            "subject": "Never",
            "body": (
                f"<div>{sentinel} — {{{{ACTOR_NAME}}}} @ "
                f"{{{{BUSINESS_NAME}}}} invited "
                f"{{{{RECIPIENT_EMAIL}}}} as {{{{ROLE}}}}: "
                f"{{{{ONBOARDING_LINK}}}}</div>"
            ),
            "category": "signup", "channel": "email",
            "kind": "transactional",
            "is_system": True, "is_default": True, "editable": True,
            "created_at": now_iso(), "updated_at": now_iso(),
        })
        captured = _capture_send(monkeypatch)
        try:
            from routers.signup_onboarding_wizard import (
                _send_team_invite_signup_email,
            )
            tenant = {"id": "tenant-en", "name": "Acme Pools",
                      "locale": "en"}
            admin_user = {"id": "u1", "email": "alice@example.com",
                          "name": "Alice", "locale": "en"}
            await _send_team_invite_signup_email(
                tenant=tenant, admin_user=admin_user,
                invited_email="bob@example.com", role="technician",
            )
            html = captured.get("html") or ""
            assert sentinel in html, (
                "DB body did not surface for English recipient"
            )
            assert "Alice" in html
            assert "Acme Pools" in html
            assert "bob@example.com" in html
            assert "technician" in html
            assert "/login?invited=bob@example.com" in html
        finally:
            await _wipe_rows()

    _run(_go())


def test_non_english_recipient_uses_i18n_fallback(monkeypatch):
    async def _go():
        await _wipe_rows()
        from utils import new_id, now_iso
        forbidden = f"FORBIDDEN-{uuid.uuid4().hex[:8]}"
        await _db().marketing_templates.insert_one({
            "id": new_id(),
            "code": "onboarding_wizard_invite_email",
            "tenant_id": None,
            "subject": "Never",
            "body": f"<p>{forbidden}</p>",
            "category": "signup", "channel": "email",
            "kind": "transactional",
            "is_system": True, "is_default": True, "editable": True,
            "created_at": now_iso(), "updated_at": now_iso(),
        })
        captured = _capture_send(monkeypatch)
        try:
            from routers.signup_onboarding_wizard import (
                _send_team_invite_signup_email,
            )
            tenant = {"id": "tenant-es", "name": "Acme Pools",
                      "default_locale": "es"}
            admin_user = {"id": "u1", "email": "andres@example.com",
                          "name": "Andrés", "locale": "es"}
            await _send_team_invite_signup_email(
                tenant=tenant, admin_user=admin_user,
                invited_email="charlie@example.com", role="office",
            )
            html = captured.get("html") or ""
            assert forbidden not in html, (
                "Non-English recipient must not receive the DB body"
            )
            assert "charlie@example.com" in html or "office" in html
        finally:
            await _wipe_rows()

    _run(_go())


def test_i18n_fallback_fires_when_row_absent(monkeypatch):
    async def _go():
        await _wipe_rows()
        captured = _capture_send(monkeypatch)
        try:
            from routers.signup_onboarding_wizard import (
                _send_team_invite_signup_email,
            )
            tenant = {"id": "t", "name": "Acme Pools", "locale": "en"}
            admin_user = {"id": "u", "email": "e@example.com",
                          "name": "Ella", "locale": "en"}
            await _send_team_invite_signup_email(
                tenant=tenant, admin_user=admin_user,
                invited_email="dan@example.com", role="technician",
            )
            html = captured.get("html") or ""
            # Notification-template triplet mentions the invited role.
            assert "technician" in html
            assert "dan@example.com" in html or "Acme Pools" in html
        finally:
            await _wipe_rows()

    _run(_go())
