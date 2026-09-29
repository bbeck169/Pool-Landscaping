"""Phase EMAIL-MIGRATE · Batch 4 · Feb-2026 — DB-first render for
:func:`routers.team._send_team_invite_email`.
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
    import routers.team as _mod
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


async def _wipe(tid: str) -> None:
    await _db().marketing_templates.delete_many(
        {"code": "team_invite_email"},
    )
    await _db().email_delivery_log.delete_many({"tenant_id": tid})
    await _db().communications_log.delete_many({"tenant_id": tid})
    await _db().marketing_deliveries.delete_many({"tenant_id": tid})


async def _seed_row(*, tenant_id_scope, body: str,
                       subject: str = "ignored") -> None:
    from utils import new_id, now_iso
    await _db().marketing_templates.insert_one({
        "id": new_id(), "code": "team_invite_email",
        "tenant_id": tenant_id_scope,
        "subject": subject, "body": body,
        "category": "team", "channel": "email",
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
                "provider_response_id": "test", "provider": "resend",
                "error": None}


def test_db_body_wins_over_hardcoded_fallback(monkeypatch):
    from routers.team import _send_team_invite_email

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        await _wipe(tid)
        sentinel = f"INV-{uuid.uuid4().hex[:8]}"
        await _seed_row(
            tenant_id_scope=None,
            body=(
                f"<div>{sentinel} — {{{{INVITEE_NAME}}}} joined "
                f"{{{{COMPANY_NAME}}}} — {{{{INVITER_NAME}}}} — "
                f"temp {{{{TEMP_PASSWORD}}}} — url "
                f"{{{{ACCEPT_INVITE_LINK}}}}</div>"
            ),
        )
        cap = _Capture()
        monkeypatch.setattr(
            "services.email.resend_adapter.send", cap,
        )
        try:
            tenant = {
                "id": tid, "name": "Acme Team",
                "settings": {"business_card": {"company_name": "Acme Team"}},
            }
            actor = {"id": "u1", "name": "Admin Amy",
                     "email": "amy@example.com"}
            invitee = {"id": "u2", "email": "bob@example.com",
                       "first_name": "Bob", "role": "technician",
                       "department": "field"}
            status = await _send_team_invite_email(
                tenant=tenant, actor=actor, invitee=invitee,
                temp_password="TempPass!23",
            )
            assert status == "sent"
            call = cap.calls[0]["kwargs"]
            html = call["html"]
            assert sentinel in html
            assert "Bob" in html
            assert "Admin Amy" in html
            assert "Acme Team" in html
            assert "TempPass!23" in html
            assert "Pool & Landscaping of Vistancia" not in html
        finally:
            await _wipe(tid)

    _run(_go())


def test_tenant_specific_row_wins_over_global_default(monkeypatch):
    from routers.team import _send_team_invite_email

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        await _wipe(tid)
        gs = f"GLOBAL-{uuid.uuid4().hex[:8]}"
        ts = f"TENANT-{uuid.uuid4().hex[:8]}"
        await _seed_row(tenant_id_scope=None, body=f"<p>{gs}</p>")
        await _seed_row(tenant_id_scope=tid, body=f"<p>{ts}</p>")
        cap = _Capture()
        monkeypatch.setattr(
            "services.email.resend_adapter.send", cap,
        )
        try:
            tenant = {"id": tid, "name": "Acme"}
            actor = {"id": "a", "name": "Admin"}
            invitee = {"id": "u", "email": "b@x.com", "name": "Bob"}
            await _send_team_invite_email(
                tenant=tenant, actor=actor, invitee=invitee,
                temp_password="x",
            )
            html = cap.calls[0]["kwargs"]["html"]
            assert ts in html
            assert gs not in html
        finally:
            await _wipe(tid)

    _run(_go())


def test_hardcoded_fallback_fires_when_row_absent(monkeypatch):
    from routers.team import _send_team_invite_email

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        await _wipe(tid)
        cap = _Capture()
        monkeypatch.setattr(
            "services.email.resend_adapter.send", cap,
        )
        try:
            tenant = {"id": tid, "name": "Acme Landscaping"}
            actor = {"id": "a", "name": "Admin Anna",
                     "email": "anna@x.com"}
            invitee = {"id": "u", "email": "c@x.com",
                       "first_name": "Carol", "role": "office"}
            status = await _send_team_invite_email(
                tenant=tenant, actor=actor, invitee=invitee,
                temp_password="TempX",
            )
            assert status == "sent"
            html = cap.calls[0]["kwargs"]["html"]
            # Fallback path — no plofv literal leaks even here.
            assert "Acme Landscaping" in html
            assert "Carol" in html
            assert "TempX" in html
            assert "Pool & Landscaping of Vistancia" not in html
        finally:
            await _wipe(tid)

    _run(_go())
