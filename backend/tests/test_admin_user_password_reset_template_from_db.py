"""Phase EMAIL-MIGRATE · Batch 1 · Feb-2026 — DB-first render for the
admin-driven password-reset email.

Locks two contracts:

1. When ``locale == "en"`` and a row exists, the DB body wins over
   the ``_password_reset_html`` hardcoded fallback.
2. When ``locale != "en"``, the i18n fallback fires regardless of
   the row — decision (c) in the EMAIL-MIGRATE brief keeps
   non-English HTML on the current i18n path.

The test exercises the private
:func:`routers.admin_users._send_password_reset_email` by patching
the resend adapter to capture the rendered subject + html.
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
    import routers.admin_users as _mod
    _orig_cfg = _cfg.db
    _orig_mod = _mod.db
    _cfg.db = fresh_db
    _mod.db = fresh_db
    try:
        yield
    finally:
        _cfg.db = _orig_cfg
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
        {"code": "admin_user_password_reset_email"},
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
        sentinel = f"ADMIN-RESET-SENTINEL-{uuid.uuid4().hex[:8]}"
        await _db().marketing_templates.insert_one({
            "id": new_id(),
            "code": "admin_user_password_reset_email",
            "tenant_id": None,
            "subject": "Never (subject stays i18n)",
            "body": (
                f"<div>{sentinel} for {{{{RECIPIENT_NAME}}}} — "
                f"temp {{{{TEMP_PASSWORD}}}} — actor "
                f"{{{{ACTOR_NAME}}}} — login {{{{LOGIN_URL}}}}</div>"
            ),
            "category": "auth", "channel": "email",
            "kind": "transactional",
            "is_system": True, "is_default": True, "editable": True,
            "created_at": now_iso(), "updated_at": now_iso(),
        })
        captured = _capture_send(monkeypatch)
        try:
            from routers.admin_users import _send_password_reset_email
            tenant = {
                "id": "tenant-en", "name": "Acme Pools",
                "locale": "en",
            }
            target = {"id": "u-target", "email": "t@example.com",
                      "first_name": "Alice", "locale": "en"}
            actor = {"id": "u-actor", "name": "Admin Amy",
                     "email": "amy@example.com"}
            await _send_password_reset_email(
                tenant=tenant, actor=actor, target=target,
                temp_password="TempPass!23",
            )
            html = captured.get("html") or ""
            assert sentinel in html, (
                "DB body did not surface for English recipient"
            )
            assert "Alice" in html
            assert "Admin Amy" in html
            assert "TempPass!23" in html
            # Subject stays i18n — decision (c). Non-empty check only.
            assert captured.get("subject")
        finally:
            await _wipe_rows()

    _run(_go())


def test_non_english_recipient_uses_i18n_fallback(monkeypatch):
    """Recipient locale ``es`` → DB row is NOT consulted; body comes
    from the ``t_email_body`` i18n composer."""
    async def _go():
        await _wipe_rows()
        from utils import new_id, now_iso
        forbidden = f"FORBIDDEN-{uuid.uuid4().hex[:8]}"
        await _db().marketing_templates.insert_one({
            "id": new_id(),
            "code": "admin_user_password_reset_email",
            "tenant_id": None,
            "subject": "Never",
            "body": f"<p>{forbidden}</p>",
            "category": "auth", "channel": "email",
            "kind": "transactional",
            "is_system": True, "is_default": True, "editable": True,
            "created_at": now_iso(), "updated_at": now_iso(),
        })
        captured = _capture_send(monkeypatch)
        try:
            from routers.admin_users import _send_password_reset_email
            tenant = {"id": "tenant-es", "name": "Acme Pools",
                      "locale": "es"}
            target = {"id": "u-t", "email": "t@example.com",
                      "first_name": "Andrés", "locale": "es"}
            actor = {"id": "u-a", "name": "Admin",
                     "email": "a@example.com"}
            await _send_password_reset_email(
                tenant=tenant, actor=actor, target=target,
                temp_password="Xyz123",
            )
            html = captured.get("html") or ""
            assert forbidden not in html, (
                "Non-English recipient must not receive the DB body"
            )
            # Temp password + actor still surface via the i18n path.
            assert "Xyz123" in html
            assert "Admin" in html
        finally:
            await _wipe_rows()

    _run(_go())


def test_hardcoded_fallback_fires_when_row_absent(monkeypatch):
    async def _go():
        await _wipe_rows()
        captured = _capture_send(monkeypatch)
        try:
            from routers.admin_users import _send_password_reset_email
            tenant = {"id": "t", "name": "Acme", "locale": "en"}
            target = {"id": "u", "email": "t@e.com",
                      "first_name": "Ella", "locale": "en"}
            actor = {"id": "a", "name": "Admin", "email": "a@e.com"}
            await _send_password_reset_email(
                tenant=tenant, actor=actor, target=target,
                temp_password="Pw!23",
            )
            html = captured.get("html") or ""
            assert "Pw!23" in html
            assert "Ella" in html
            assert "Admin" in html
            # Sign-in CTA copy from ``_password_reset_html``.
            assert "sign in" in html.lower() or "Sign in" in html
        finally:
            await _wipe_rows()

    _run(_go())
