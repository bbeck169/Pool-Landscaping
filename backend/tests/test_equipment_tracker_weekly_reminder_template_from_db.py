"""Phase EMAIL-MIGRATE · Batch 3 · Feb-2026 — DB-first render for the
equipment tracker weekly reminder email.

The customer-reminder cron
(:func:`services.equipment_trackers_cron._dispatch_customer_reminders`)
now prefers the ``equipment_tracker_weekly_reminder_email`` row in
``marketing_templates`` (tenant-specific > global default) over the
module-level ``_REMINDER_EMAIL_TEMPLATE`` constant.
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
    import services.equipment_trackers_cron as _mod
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


async def _wipe(tid: str, cid: str) -> None:
    await _db().marketing_templates.delete_many(
        {"code": "equipment_tracker_weekly_reminder_email"},
    )
    await _db().customers.delete_many({"tenant_id": tid})
    await _db().outbound_emails.delete_many({"tenant_id": tid})


async def _seed_customer(tid: str, cid: str) -> None:
    from utils import new_id, now_iso
    await _db().customers.insert_one({
        "id": cid, "tenant_id": tid,
        "name": "Rina Reminder", "first_name": "Rina",
        "email": "rina@example.com", "phone": "+15550001111",
        "created_at": now_iso(),
    })


async def _seed_row(*, tenant_id_scope, body: str) -> None:
    from utils import new_id, now_iso
    await _db().marketing_templates.insert_one({
        "id": new_id(),
        "code": "equipment_tracker_weekly_reminder_email",
        "tenant_id": tenant_id_scope,
        "subject": "Your {{EQUIPMENT_TYPE}} cleaning is due",
        "body": body,
        "category": "equipment", "channel": "email",
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


def _tracker(cid: str) -> Dict[str, Any]:
    return {
        "id": f"trk-{uuid.uuid4().hex[:8]}",
        "customer_id": cid,
        "tracker_type": "salt_cell",
        "last_cleaned_at": "2025-11-01",
        "due_at": "2026-02-25",
        "interval_months": 3,
    }


def test_db_body_wins_over_constant_fallback(monkeypatch):
    from services.equipment_trackers_cron import (
        _dispatch_customer_reminders,
    )

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        await _wipe(tid, cid)
        await _seed_customer(tid, cid)
        sentinel = f"EQ-SENTINEL-{uuid.uuid4().hex[:8]}"
        await _seed_row(
            tenant_id_scope=None,
            body=(
                f"<div>{sentinel} for {{{{CUSTOMER_FIRST_NAME}}}} — "
                f"{{{{EQUIPMENT_TYPE}}}} due "
                f"{{{{EQUIPMENT_DUE_DATE}}}}</div>"
            ),
        )
        email_cap = _Capture()
        monkeypatch.setattr(
            "services.email.resend_adapter.send", email_cap,
        )
        try:
            tenant = {"id": tid, "name": "Acme Pools",
                      "settings": {"business_card": {
                          "company_name": "Acme Pools",
                      }}}
            tracker = _tracker(cid)
            result = await _dispatch_customer_reminders(
                tenant, coming_due=[tracker], past_due=[],
            )
            assert result["emails_sent"] == 1
            html = email_cap.calls[0]["kwargs"]["html"]
            assert sentinel in html
            assert "Rina" in html
            assert "Salt Cell" in html
        finally:
            await _wipe(tid, cid)

    _run(_go())


def test_tenant_specific_row_wins_over_global_default(monkeypatch):
    from services.equipment_trackers_cron import (
        _dispatch_customer_reminders,
    )

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        await _wipe(tid, cid)
        await _seed_customer(tid, cid)
        gs = f"GLOBAL-{uuid.uuid4().hex[:8]}"
        ts = f"TENANT-{uuid.uuid4().hex[:8]}"
        await _seed_row(tenant_id_scope=None, body=f"<p>{gs}</p>")
        await _seed_row(tenant_id_scope=tid, body=f"<p>{ts}</p>")
        email_cap = _Capture()
        monkeypatch.setattr(
            "services.email.resend_adapter.send", email_cap,
        )
        try:
            tenant = {"id": tid, "name": "Acme"}
            await _dispatch_customer_reminders(
                tenant, coming_due=[_tracker(cid)], past_due=[],
            )
            html = email_cap.calls[0]["kwargs"]["html"]
            assert ts in html
            assert gs not in html
        finally:
            await _wipe(tid, cid)

    _run(_go())


def test_constant_fallback_fires_when_row_absent(monkeypatch):
    from services.equipment_trackers_cron import (
        _dispatch_customer_reminders,
    )

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        await _wipe(tid, cid)
        await _seed_customer(tid, cid)
        email_cap = _Capture()
        monkeypatch.setattr(
            "services.email.resend_adapter.send", email_cap,
        )
        try:
            tenant = {"id": tid, "name": "Acme"}
            await _dispatch_customer_reminders(
                tenant, coming_due=[_tracker(cid)], past_due=[],
            )
            html = email_cap.calls[0]["kwargs"]["html"]
            # Constant template's copy surfaces.
            assert "Hi Rina" in html
            assert "Salt Cell" in html
            assert "next cleaning" in html
        finally:
            await _wipe(tid, cid)

    _run(_go())
