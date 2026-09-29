"""Phase EMAIL-MIGRATE · Batch 3 · Feb-2026 — DB-first passthrough
for the canonical lead-admin notification email.
"""
from __future__ import annotations

import asyncio
import os
import uuid
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
    import services.lead_admin_notifications as _mod
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


async def _wipe(tid: str, lid: str) -> None:
    await _db().marketing_templates.delete_many(
        {"code": "lead_admin_notification_email"},
    )
    await _db().users.delete_many({"tenant_id": tid})
    await _db().lead_admin_email_dispatches.delete_many(
        {"tenant_id": tid, "lead_id": lid},
    )


async def _seed_admin(tid: str, email: str = "admin@t.com") -> None:
    from utils import new_id, now_iso
    await _db().users.insert_one({
        "id": new_id(), "tenant_id": tid, "role": "admin",
        "email": email, "name": "Ada Admin",
        "notification_role_muted": False,
        "created_at": now_iso(),
    })


async def _seed_row(*, tenant_id_scope, body: str) -> None:
    from utils import new_id, now_iso
    await _db().marketing_templates.insert_one({
        "id": new_id(), "code": "lead_admin_notification_email",
        "tenant_id": tenant_id_scope,
        "subject": "ignored", "body": body,
        "category": "lead", "channel": "email",
        "kind": "transactional",
        "is_system": True, "is_default": True, "editable": True,
        "created_at": now_iso(), "updated_at": now_iso(),
    })


class _FakeBGT:
    def __init__(self):
        self.tasks: List[Dict[str, Any]] = []

    def add_task(self, fn, **kwargs):
        self.tasks.append({"fn": fn, "kwargs": kwargs})


def _lead(tid: str) -> Dict[str, Any]:
    return {
        "id": uuid.uuid4().hex, "tenant_id": tid,
        "name": "Zach Prospect", "email": "z@example.com",
        "phone": "+15551239876",
        "service_interest": "Weekly pool cleaning",
        "message": "Need to schedule ASAP",
        "source": "lead_form", "created_at": "2026-02-22T12:00:00+00:00",
    }


def test_default_passthrough_body_matches_hardcoded_output(monkeypatch):
    """Default DB body is exactly ``{{LEAD_ADMIN_INNER_HTML}}`` so
    tenants that haven't customised the row see the same composed
    HTML as before."""
    from services.lead_admin_notifications import (
        dispatch_admin_lead_email,
    )

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        lead = _lead(tid)
        await _wipe(tid, lead["id"])
        await _seed_admin(tid)
        await _seed_row(
            tenant_id_scope=None,
            body="{{LEAD_ADMIN_INNER_HTML}}",   # passthrough default
        )
        bgt = _FakeBGT()
        try:
            tenant = {"id": tid, "name": "Acme Pools"}
            result = await dispatch_admin_lead_email(
                lead=lead, tenant=tenant, background_tasks=bgt,
            )
            assert result["queued"] == 1
            kwargs = bgt.tasks[0]["kwargs"]
            html = kwargs["html"]
            # Passthrough — inner composed HTML surfaces.
            assert "Zach Prospect" in html
            assert "+15551239876" in html or "5551239876" in html
            assert "z@example.com" in html
            assert "Need to schedule ASAP" in html
        finally:
            await _wipe(tid, lead["id"])

    _run(_go())


def test_tenant_edited_row_wraps_inner_html_with_chrome(monkeypatch):
    """A tenant that customises the row body to add chrome sees
    the chrome PLUS the composed inner HTML."""
    from services.lead_admin_notifications import (
        dispatch_admin_lead_email,
    )

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        lead = _lead(tid)
        await _wipe(tid, lead["id"])
        await _seed_admin(tid)
        chrome_top = f"CHROME-TOP-{uuid.uuid4().hex[:6]}"
        chrome_bot = f"CHROME-BOT-{uuid.uuid4().hex[:6]}"
        await _seed_row(
            tenant_id_scope=tid,
            body=(
                f"<div>{chrome_top}</div>"
                "{{LEAD_ADMIN_INNER_HTML}}"
                f"<div>{chrome_bot}</div>"
            ),
        )
        bgt = _FakeBGT()
        try:
            tenant = {"id": tid, "name": "Acme Pools"}
            await dispatch_admin_lead_email(
                lead=lead, tenant=tenant, background_tasks=bgt,
            )
            html = bgt.tasks[0]["kwargs"]["html"]
            assert chrome_top in html
            assert chrome_bot in html
            # Inner HTML still surfaces sandwiched between chrome.
            assert "Zach Prospect" in html
            top_pos = html.index(chrome_top)
            inner_pos = html.index("Zach Prospect")
            bot_pos = html.index(chrome_bot)
            assert top_pos < inner_pos < bot_pos, (
                top_pos, inner_pos, bot_pos,
            )
        finally:
            await _wipe(tid, lead["id"])

    _run(_go())


def test_hardcoded_composed_fallback_fires_when_row_absent(monkeypatch):
    from services.lead_admin_notifications import (
        dispatch_admin_lead_email,
    )

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        lead = _lead(tid)
        await _wipe(tid, lead["id"])
        await _seed_admin(tid)
        bgt = _FakeBGT()
        try:
            tenant = {"id": tid, "name": "Acme Pools"}
            await dispatch_admin_lead_email(
                lead=lead, tenant=tenant, background_tasks=bgt,
            )
            html = bgt.tasks[0]["kwargs"]["html"]
            # No DB row → no chrome, just the composed inner HTML.
            assert "Zach Prospect" in html
            assert "Need to schedule ASAP" in html
        finally:
            await _wipe(tid, lead["id"])

    _run(_go())
