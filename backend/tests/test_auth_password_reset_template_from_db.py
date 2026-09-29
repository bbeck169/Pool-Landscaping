"""Phase EMAIL-MIGRATE · Batch 1 · Feb-2026 — DB-first render for the
self-serve password-reset email.

Locks the contract that
:func:`routers.auth._resolve_password_reset_email_html` prefers the
``auth_password_reset_email`` row in ``marketing_templates`` over
the hardcoded fallback body in
:func:`routers.auth._password_reset_email_html`.
"""
from __future__ import annotations

import asyncio
import os
import uuid

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
    _orig_db = _cfg.db
    _cfg.db = fresh_db
    try:
        yield
    finally:
        _cfg.db = _orig_db
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
        {"code": "auth_password_reset_email"},
    )


def test_db_template_wins_over_hardcoded_fallback():
    async def _go():
        await _wipe_rows()
        from utils import new_id, now_iso
        sentinel = f"AUTH-RESET-SENTINEL-{uuid.uuid4().hex[:8]}"
        await _db().marketing_templates.insert_one({
            "id": new_id(),
            "code": "auth_password_reset_email",
            "tenant_id": None,
            "subject": "Subj-{{COMPANY_NAME}}",
            "body": (
                f"<div>{sentinel} — hi {{{{RECIPIENT_NAME}}}}, "
                f"reset at {{{{RESET_LINK}}}} in {{{{EXPIRY_LABEL}}}}</div>"
            ),
            "category": "auth", "channel": "email",
            "kind": "transactional",
            "is_system": True, "is_default": True, "editable": True,
            "created_at": now_iso(), "updated_at": now_iso(),
        })
        try:
            from routers.auth import _resolve_password_reset_email_html
            subject, html = await _resolve_password_reset_email_html(
                tenant={"id": "some-tenant", "name": "Acme Pools"},
                first_name="Alice",
                reset_link="https://x/reset?t=abc",
                expiry_minutes=43200,   # 30 days
            )
            assert sentinel in html, (
                "DB template body did not surface — the resolver must "
                "prefer marketing_templates over the hardcoded fallback"
            )
            assert "Alice" in html
            assert "https://x/reset?t=abc" in html
            assert "30 days" in html    # {{EXPIRY_LABEL}} resolved
            assert subject.startswith("Subj-")
            assert "{{COMPANY_NAME}}" not in subject
        finally:
            await _wipe_rows()

    _run(_go())


def test_tenant_specific_row_wins_over_global_default():
    async def _go():
        await _wipe_rows()
        from utils import new_id, now_iso
        global_sentinel = f"GLOBAL-{uuid.uuid4().hex[:8]}"
        tenant_sentinel = f"TENANT-{uuid.uuid4().hex[:8]}"
        tid = f"tenant-{uuid.uuid4().hex[:8]}"
        await _db().marketing_templates.insert_many([
            {"id": new_id(),
             "code": "auth_password_reset_email",
             "tenant_id": None,
             "subject": "Global",
             "body": f"<p>{global_sentinel}</p>",
             "category": "auth", "channel": "email",
             "kind": "transactional",
             "is_system": True, "is_default": True, "editable": True,
             "created_at": now_iso(), "updated_at": now_iso()},
            {"id": new_id(),
             "code": "auth_password_reset_email",
             "tenant_id": tid,
             "subject": "Tenant",
             "body": f"<p>{tenant_sentinel}</p>",
             "category": "auth", "channel": "email",
             "kind": "transactional",
             "is_system": False, "editable": True,
             "created_at": now_iso(), "updated_at": now_iso()},
        ])
        try:
            from routers.auth import _resolve_password_reset_email_html
            subject, html = await _resolve_password_reset_email_html(
                tenant={"id": tid},
                first_name="Bob",
                reset_link="https://x/r",
                expiry_minutes=60,
            )
            assert tenant_sentinel in html
            assert global_sentinel not in html
            assert subject == "Tenant"
        finally:
            await _wipe_rows()

    _run(_go())


def test_hardcoded_fallback_fires_when_row_absent():
    async def _go():
        await _wipe_rows()
        from routers.auth import _resolve_password_reset_email_html
        subject, html = await _resolve_password_reset_email_html(
            tenant={"id": "tenant-x"},
            first_name="Carol",
            reset_link="https://x/r",
            expiry_minutes=120,
        )
        # No DB row → hardcoded fallback body renders.
        assert isinstance(html, str) and len(html) > 200
        assert "Reset your password" in html
        assert "Hi Carol" in html
        assert "https://x/r" in html
        assert "2 hours" in html    # 120 minutes formatted
        assert subject == "Reset your password"

    _run(_go())


def test_inactive_row_falls_back_to_hardcoded():
    """A row with ``is_active=False`` must be treated as absent."""
    async def _go():
        await _wipe_rows()
        from utils import new_id, now_iso
        await _db().marketing_templates.insert_one({
            "id": new_id(),
            "code": "auth_password_reset_email",
            "tenant_id": None,
            "subject": "Never",
            "body": "<p>INACTIVE_SENTINEL_MUST_NOT_APPEAR</p>",
            "category": "auth", "channel": "email",
            "kind": "transactional",
            "is_active": False,
            "created_at": now_iso(), "updated_at": now_iso(),
        })
        try:
            from routers.auth import _resolve_password_reset_email_html
            subject, html = await _resolve_password_reset_email_html(
                tenant={"id": "t"},
                first_name="Dana",
                reset_link="https://x/r",
                expiry_minutes=30,
            )
            assert "INACTIVE_SENTINEL_MUST_NOT_APPEAR" not in html
            assert "Reset your password" in html
            assert subject == "Reset your password"
        finally:
            await _wipe_rows()

    _run(_go())
