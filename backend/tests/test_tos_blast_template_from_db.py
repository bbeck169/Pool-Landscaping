"""Phase EMAIL-MIGRATE · Batch 4 · Feb-2026 — DB-first render for
:func:`routers.tos_multi._blast_one_customer`.

Locks three contracts:

1. When a ``tos_blast_email`` row exists in
   ``marketing_templates`` the DB-rendered body wins over the
   hardcoded ``_tos_blast_html`` fallback.
2. Tenant-specific rows win over global-default rows for the
   same ``code``.
3. When no row exists at all the hardcoded fallback fires and
   never leaks the plofv-internal literal.
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
    import routers.tos_multi as _mod
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
        {"code": "tos_blast_email"},
    )
    await _db().marketing_deliveries.delete_many({"tenant_id": tid})


async def _seed_row(*, tenant_id_scope, body: str,
                       subject: str = "ignored") -> None:
    from utils import new_id, now_iso
    await _db().marketing_templates.insert_one({
        "id": new_id(), "code": "tos_blast_email",
        "tenant_id": tenant_id_scope,
        "subject": subject, "body": body,
        "category": "legal", "channel": "email",
        "kind": "transactional",
        "is_system": True, "is_default": True, "editable": True,
        "created_at": now_iso(), "updated_at": now_iso(),
    })


class _Capture:
    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    async def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return {"id": "res_test_123", "provider_id": "res_test_123"}


def _doc(tid: str) -> Dict[str, Any]:
    return {
        "id": f"tos-{uuid.uuid4().hex[:8]}", "tenant_id": tid,
        "service_type": "pool", "version": 3,
        "effective_at": "2026-03-01",
    }


def _cust(tid: str) -> Dict[str, Any]:
    return {
        "id": f"c-{uuid.uuid4().hex[:8]}", "tenant_id": tid,
        "first_name": "Terry", "name": "Terry Terms",
        "email": "terry@example.com",
    }


def test_db_body_wins_over_hardcoded_fallback(monkeypatch):
    from routers.tos_multi import _blast_one_customer

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        await _wipe(tid)
        sentinel = f"TOS-{uuid.uuid4().hex[:8]}"
        await _seed_row(
            tenant_id_scope=None,
            body=(
                f"<div>{sentinel} — {{{{RECIPIENT_NAME}}}} @ "
                f"{{{{COMPANY_NAME}}}} — v{{{{TOS_VERSION}}}} "
                f"({{{{SERVICE_LABEL}}}}) effective "
                f"{{{{EFFECTIVE_DATE}}}} — {{{{TOS_URL}}}}</div>"
            ),
        )
        cap = _Capture()
        monkeypatch.setattr(
            "services.email.resend_adapter.send", cap,
        )
        try:
            tenant = {"id": tid, "name": "Acme Pools"}
            await _blast_one_customer(
                document=_doc(tid), tenant=tenant, cust=_cust(tid),
            )
            assert cap.calls, "resend_adapter.send was not invoked"
            html = cap.calls[0]["kwargs"]["html"]
            assert sentinel in html
            assert "Terry" in html
            assert "Acme Pools" in html
            assert "pool" in html
            assert "2026-03-01" in html
            assert "Pool & Landscaping of Vistancia" not in html
        finally:
            await _wipe(tid)

    _run(_go())


def test_tenant_specific_row_wins_over_global_default(monkeypatch):
    from routers.tos_multi import _blast_one_customer

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
            await _blast_one_customer(
                document=_doc(tid), tenant=tenant, cust=_cust(tid),
            )
            html = cap.calls[0]["kwargs"]["html"]
            assert ts in html
            assert gs not in html
        finally:
            await _wipe(tid)

    _run(_go())


def test_hardcoded_fallback_fires_when_row_absent(monkeypatch):
    from routers.tos_multi import _blast_one_customer

    async def _go():
        tid = f"t-{uuid.uuid4().hex[:8]}"
        await _wipe(tid)
        cap = _Capture()
        monkeypatch.setattr(
            "services.email.resend_adapter.send", cap,
        )
        try:
            tenant = {"id": tid, "name": "Acme Landscaping"}
            await _blast_one_customer(
                document=_doc(tid), tenant=tenant, cust=_cust(tid),
            )
            assert cap.calls, "resend_adapter.send was not invoked"
            html = cap.calls[0]["kwargs"]["html"]
            # Fallback path — no plofv literal leaks even here.
            assert "Acme Landscaping" in html
            assert "Pool & Landscaping of Vistancia" not in html
        finally:
            await _wipe(tid)

    _run(_go())
