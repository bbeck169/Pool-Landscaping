"""Phase EMAIL-MIGRATE · Batch 4 · Feb-2026 — DB-first render for
:func:`emailer.send_invoice_reminder_email` (dunning path).
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


async def _wipe(tid: str, cid: str) -> None:
    await _db().marketing_templates.delete_many(
        {"code": "invoice_reminder_email"},
    )
    await _db().tenants.delete_many({"id": tid})
    await _db().customers.delete_many({"id": cid})


async def _seed(tid: str, cid: str, *, locale: str = "en") -> None:
    from utils import now_iso
    await _db().tenants.insert_one({
        "id": tid, "name": "Acme Pools",
        "default_locale": locale,
        "settings": {"business_card": {"company_name": "Acme Pools"}},
        "created_at": now_iso(),
    })
    await _db().customers.insert_one({
        "id": cid, "tenant_id": tid, "name": "Inv Ivy",
        "email": "inv@example.com", "locale": locale,
        "created_at": now_iso(),
    })


async def _seed_row(*, tenant_id_scope, body: str) -> None:
    from utils import new_id, now_iso
    await _db().marketing_templates.insert_one({
        "id": new_id(), "code": "invoice_reminder_email",
        "tenant_id": tenant_id_scope,
        "subject": "ignored", "body": body,
        "category": "finance", "channel": "email",
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


def _inv(tid: str, cid: str) -> Dict[str, Any]:
    return {
        "id": f"inv-{uuid.uuid4().hex[:8]}",
        "tenant_id": tid, "customer_id": cid,
        "doc_type": "invoice", "invoice_number": "INV-99",
        "total": 850.00, "amount_paid": 0.00,
        "due_date": "2026-02-14",
    }


def test_db_body_wins_for_english_recipient(monkeypatch):
    from emailer import send_invoice_reminder_email

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        await _wipe(tid, cid)
        await _seed(tid, cid, locale="en")
        sentinel = f"INV-{uuid.uuid4().hex[:8]}"
        await _seed_row(
            tenant_id_scope=None,
            body=(
                f"<div>{sentinel} {{{{CUSTOMER_NAME}}}} — "
                f"INV#{{{{INVOICE_NUMBER}}}} — "
                f"BAL={{{{INVOICE_TOTAL}}}} — DUE {{{{INVOICE_DUE_DATE}}}}"
                f" — pay {{{{PAY_LINK}}}}</div>"
            ),
        )
        cap = _wire(monkeypatch)
        try:
            ok = await send_invoice_reminder_email(_inv(tid, cid))
            assert ok is True
            html = cap.calls[0]["kwargs"]["html"]
            assert sentinel in html
            assert "Inv Ivy" in html
            assert "INV-99" in html
            assert "850.00" in html
            assert "2026-02-14" in html
            assert "Pool & Landscaping of Vistancia" not in html
        finally:
            await _wipe(tid, cid)

    _run(_go())


def test_non_english_recipient_uses_i18n_fallback(monkeypatch):
    from emailer import send_invoice_reminder_email

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        await _wipe(tid, cid)
        await _seed(tid, cid, locale="es")
        forbidden = f"FORBIDDEN-{uuid.uuid4().hex[:8]}"
        await _seed_row(tenant_id_scope=None,
                          body=f"<p>{forbidden}</p>")
        cap = _wire(monkeypatch)
        try:
            await send_invoice_reminder_email(_inv(tid, cid))
            html = cap.calls[0]["kwargs"]["html"]
            assert forbidden not in html
            assert "Pool & Landscaping of Vistancia" not in html
            assert "Pool &amp; Landscaping of Vistancia" not in html
        finally:
            await _wipe(tid, cid)

    _run(_go())


def test_hardcoded_fallback_fires_when_row_absent(monkeypatch):
    from emailer import send_invoice_reminder_email

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        await _wipe(tid, cid)
        await _seed(tid, cid, locale="en")
        cap = _wire(monkeypatch)
        try:
            ok = await send_invoice_reminder_email(_inv(tid, cid))
            assert ok is True
            html = cap.calls[0]["kwargs"]["html"]
            # Fallback body uses the tenant's company_name — no
            # plofv literal leaks in the "Thanks — the <co> team" line.
            assert "Pool & Landscaping of Vistancia" not in html
            assert "Pool &amp; Landscaping of Vistancia" not in html
            assert "Acme Pools" in html
        finally:
            await _wipe(tid, cid)

    _run(_go())
