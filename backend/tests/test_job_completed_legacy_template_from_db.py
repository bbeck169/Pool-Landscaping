"""Phase EMAIL-MIGRATE · Batch 4 · Feb-2026 — DB-first render for
:func:`emailer.send_completion_email`.

Locks two contracts:

1. English recipients receive the DB-rendered body when a
   ``job_completed_legacy_email`` row exists.
2. Non-English recipients keep the D6 i18n path unchanged
   (decision (c)).

The door-hanger path (``door_hanger_job_completed``) is
independent — asserting its non-collision is out of scope here
(covered by the DOOR-HANGER phase tests).
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
    import emailer as _mod
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


async def _wipe(tid: str, cid: str, jid: str) -> None:
    await _db().marketing_templates.delete_many(
        {"code": "job_completed_legacy_email"},
    )
    await _db().customers.delete_many({"id": cid})
    await _db().tenants.delete_many({"id": tid})
    await _db().jobs.delete_many({"id": jid})


async def _seed(tid: str, cid: str, jid: str, *, locale: str = "en") -> None:
    from utils import now_iso
    await _db().tenants.insert_one({
        "id": tid, "name": "Acme Pools",
        "default_locale": locale,
        "settings": {"business_card": {"company_name": "Acme Pools"}},
        "created_at": now_iso(),
    })
    await _db().customers.insert_one({
        "id": cid, "tenant_id": tid,
        "name": "Sam Complete", "email": "sam@example.com",
        "locale": locale, "created_at": now_iso(),
    })
    await _db().jobs.insert_one({
        "id": jid, "tenant_id": tid, "customer_id": cid,
        "service_type": "Weekly Pool Service",
        "scheduled_date": "2026-02-22", "status": "completed",
        "service_address": "9 Palm Rd",
        "created_at": now_iso(),
    })


async def _seed_row(*, tenant_id_scope, body: str) -> None:
    from utils import new_id, now_iso
    await _db().marketing_templates.insert_one({
        "id": new_id(), "code": "job_completed_legacy_email",
        "tenant_id": tenant_id_scope,
        "subject": "ignored", "body": body,
        "category": "job", "channel": "email",
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


def _wire(monkeypatch) -> _Capture:
    cap = _Capture()
    monkeypatch.setattr("emailer._resend_send", cap)
    return cap


def test_db_body_wins_for_english_recipient(monkeypatch):
    from emailer import send_completion_email

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        jid = f"j-{uuid.uuid4().hex[:8]}"
        await _wipe(tid, cid, jid)
        await _seed(tid, cid, jid, locale="en")
        sentinel = f"JOB-{uuid.uuid4().hex[:8]}"
        await _seed_row(
            tenant_id_scope=None,
            body=(
                f"<div>{sentinel} — {{{{CUSTOMER_NAME}}}} @ "
                f"{{{{COMPANY_NAME}}}} — {{{{SERVICE_TYPE}}}} at "
                f"{{{{PROPERTY_ADDRESS}}}} — {{{{VIEW_REQUEST_LINK}}}}</div>"
            ),
        )
        cap = _wire(monkeypatch)
        try:
            job = {"id": jid, "customer_id": cid, "tenant_id": tid,
                   "service_type": "Weekly Pool Service",
                   "scheduled_date": "2026-02-22",
                   "service_address": "9 Palm Rd"}
            ok = await send_completion_email(job)
            assert ok is True
            html = cap.calls[0]["kwargs"]["html"]
            assert sentinel in html
            assert "Sam Complete" in html
            assert "Acme Pools" in html
            assert "Weekly Pool Service" in html
            assert "9 Palm Rd" in html
            assert "Pool & Landscaping of Vistancia" not in html
        finally:
            await _wipe(tid, cid, jid)

    _run(_go())


def test_non_english_recipient_uses_i18n_fallback(monkeypatch):
    from emailer import send_completion_email

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        jid = f"j-{uuid.uuid4().hex[:8]}"
        await _wipe(tid, cid, jid)
        await _seed(tid, cid, jid, locale="es")
        forbidden = f"FORBIDDEN-{uuid.uuid4().hex[:8]}"
        await _seed_row(tenant_id_scope=None,
                          body=f"<p>{forbidden}</p>")
        cap = _wire(monkeypatch)
        try:
            job = {"id": jid, "customer_id": cid, "tenant_id": tid,
                   "service_type": "Weekly Pool Service",
                   "scheduled_date": "2026-02-22",
                   "service_address": "9 Palm Rd"}
            await send_completion_email(job)
            html = cap.calls[0]["kwargs"]["html"]
            assert forbidden not in html
            # i18n fallback surfaces the tenant company_name via the
            # hardcoded header (never the plofv literal).
            assert "Acme Pools" in html
            assert "Pool & Landscaping of Vistancia" not in html
        finally:
            await _wipe(tid, cid, jid)

    _run(_go())


def test_hardcoded_fallback_fires_when_row_absent(monkeypatch):
    from emailer import send_completion_email

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        jid = f"j-{uuid.uuid4().hex[:8]}"
        await _wipe(tid, cid, jid)
        await _seed(tid, cid, jid, locale="en")
        cap = _wire(monkeypatch)
        try:
            job = {"id": jid, "customer_id": cid, "tenant_id": tid,
                   "service_type": "Weekly Pool Service",
                   "scheduled_date": "2026-02-22"}
            ok = await send_completion_email(job)
            assert ok is True
            html = cap.calls[0]["kwargs"]["html"]
            # Hardcoded fallback header shows the tenant name via
            # the ``company_name`` kwarg — no plofv literal.
            assert "Acme Pools" in html
            assert "Pool & Landscaping of Vistancia" not in html
        finally:
            await _wipe(tid, cid, jid)

    _run(_go())
