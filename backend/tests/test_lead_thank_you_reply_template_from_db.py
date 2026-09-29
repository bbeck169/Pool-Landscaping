"""Phase EMAIL-MIGRATE · Batch 2 · Feb-2026 — DB-first render for the
lead thank-you (out-of-state) auto-reply email.

Locks the contract that
:func:`services.leads_side_effects._fire_customer_reject_reply`
prefers the ``lead_thank_you_reply_email`` row in
``marketing_templates`` over the hardcoded fallback body.
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
    import services.leads_side_effects as _mod
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


async def _wipe_rows(tenant_id: str, lead_id: str) -> None:
    await _db().marketing_templates.delete_many(
        {"code": "lead_thank_you_reply_email"},
    )
    await _db().tenants.delete_many({"id": tenant_id})
    await _db().marketing_deliveries.delete_many(
        {"trigger_id": f"lead_out_of_state_auto_reply:{lead_id}"},
    )


class _Capture:
    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    async def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return {"provider_status": "sent",
                "provider_response_id": "test", "error": None}


async def _seed_tenant(tenant_id: str, name: str) -> None:
    from utils import new_id, now_iso
    await _db().tenants.insert_one({
        "id": tenant_id, "name": name,
        "settings": {"business_card": {"company_name": name}},
        "created_at": now_iso(), "updated_at": now_iso(),
    })


async def _seed_row(*, tenant_id_scope, subject: str, body: str) -> None:
    from utils import new_id, now_iso
    await _db().marketing_templates.insert_one({
        "id": new_id(),
        "code": "lead_thank_you_reply_email",
        "tenant_id": tenant_id_scope,
        "subject": subject, "body": body,
        "category": "lead", "channel": "email",
        "kind": "transactional",
        "is_system": True, "is_default": True, "editable": True,
        "created_at": now_iso(), "updated_at": now_iso(),
    })


def test_db_body_wins_over_hardcoded_fallback(monkeypatch):
    from services.leads_side_effects import _fire_customer_reject_reply

    async def _go():
        tenant_id = f"t-{uuid.uuid4().hex[:8]}"
        lead_id = f"l-{uuid.uuid4().hex[:8]}"
        await _wipe_rows(tenant_id, lead_id)
        await _seed_tenant(tenant_id, "Acme Landscaping")
        sentinel = f"THANK-YOU-SENTINEL-{uuid.uuid4().hex[:8]}"
        await _seed_row(
            tenant_id_scope=None,
            subject="Custom Thanks",
            body=(
                f"<p>{sentinel} Hi {{{{RECIPIENT_NAME}}}} — "
                f"{{{{COMPANY_NAME}}}} does not serve "
                f"{{{{REJECT_STATE}}}}</p>"
            ),
        )
        capture = _Capture()
        monkeypatch.setattr(
            "services.email.resend_adapter.send", capture,
        )
        try:
            lead = {
                "id": lead_id, "tenant_id": tenant_id,
                "email": "reject@example.com",
                "first_name": "Bob", "name": "Bob Reject",
            }
            await _fire_customer_reject_reply(lead, "CA")
            assert len(capture.calls) == 1
            call = capture.calls[0]["kwargs"]
            assert sentinel in call["html"]
            assert "Bob" in call["html"]
            assert "CA" in call["html"]
            assert "Acme Landscaping" in call["html"]
            assert call["subject"] == "Custom Thanks"
            # BUGFIX invariant — the seeded body must NOT reintroduce
            # the plofv tenant name.
            assert "Pool & Landscaping of Vistancia" not in call["html"]
        finally:
            await _wipe_rows(tenant_id, lead_id)

    _run(_go())


def test_tenant_specific_row_wins_over_global_default(monkeypatch):
    from services.leads_side_effects import _fire_customer_reject_reply

    async def _go():
        tenant_id = f"t-{uuid.uuid4().hex[:8]}"
        lead_id = f"l-{uuid.uuid4().hex[:8]}"
        await _wipe_rows(tenant_id, lead_id)
        await _seed_tenant(tenant_id, "Acme")
        gs = f"GLOBAL-{uuid.uuid4().hex[:8]}"
        ts = f"TENANT-{uuid.uuid4().hex[:8]}"
        await _seed_row(tenant_id_scope=None, subject="G",
                          body=f"<p>{gs}</p>")
        await _seed_row(tenant_id_scope=tenant_id, subject="T",
                          body=f"<p>{ts}</p>")
        capture = _Capture()
        monkeypatch.setattr(
            "services.email.resend_adapter.send", capture,
        )
        try:
            lead = {"id": lead_id, "tenant_id": tenant_id,
                    "email": "reject@example.com", "name": "Cara"}
            await _fire_customer_reject_reply(lead, "WY")
            call = capture.calls[0]["kwargs"]
            assert ts in call["html"]
            assert gs not in call["html"]
            assert call["subject"] == "T"
        finally:
            await _wipe_rows(tenant_id, lead_id)

    _run(_go())


def test_hardcoded_fallback_fires_when_row_absent(monkeypatch):
    from services.leads_side_effects import _fire_customer_reject_reply

    async def _go():
        tenant_id = f"t-{uuid.uuid4().hex[:8]}"
        lead_id = f"l-{uuid.uuid4().hex[:8]}"
        await _wipe_rows(tenant_id, lead_id)
        await _seed_tenant(tenant_id, "Acme")
        capture = _Capture()
        monkeypatch.setattr(
            "services.email.resend_adapter.send", capture,
        )
        try:
            lead = {
                "id": lead_id, "tenant_id": tenant_id,
                "email": "reject@example.com",
                "first_name": "Dana", "name": "Dana Reject",
            }
            await _fire_customer_reject_reply(lead, "OR")
            assert len(capture.calls) == 1
            html = capture.calls[0]["kwargs"]["html"]
            # Hardcoded fallback still fires.
            assert "Dana" in html
            assert "OR" in html
            assert capture.calls[0]["kwargs"]["subject"] == \
                "Thanks for reaching out"
        finally:
            await _wipe_rows(tenant_id, lead_id)

    _run(_go())
