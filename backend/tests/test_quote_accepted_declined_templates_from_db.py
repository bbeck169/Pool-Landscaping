"""Phase EMAIL-MIGRATE · Batch 3 · Feb-2026 — DB-first render for the
quote accepted/declined owner notification emails."""
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
    _orig = _cfg.db
    _cfg.db = fresh_db
    try:
        yield
    finally:
        _cfg.db = _orig
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


async def _wipe():
    await _db().marketing_templates.delete_many({
        "code": {"$in": ["quote_accepted_owner_email",
                          "quote_declined_owner_email"]},
    })


async def _seed_row(*, code, tenant_id_scope, body, subject="ignored"):
    from utils import new_id, now_iso
    await _db().marketing_templates.insert_one({
        "id": new_id(), "code": code, "tenant_id": tenant_id_scope,
        "subject": subject, "body": body,
        "category": "quote", "channel": "email",
        "kind": "transactional",
        "is_system": True, "is_default": True, "editable": True,
        "created_at": now_iso(), "updated_at": now_iso(),
    })


def _doc(**overrides):
    d = {"id": uuid.uuid4().hex, "customer_name": "Alice Buyer",
         "total": 1234.5, "doc_type": "quote"}
    d.update(overrides)
    return d


def test_accepted_db_body_wins_over_hardcoded_fallback():
    async def _go():
        await _wipe()
        sentinel = f"ACCEPTED-{uuid.uuid4().hex[:8]}"
        await _seed_row(
            code="quote_accepted_owner_email",
            tenant_id_scope=None,
            body=(
                f"<div>{sentinel} {{{{QUOTE_HEADLINE}}}} — "
                f"TOTAL={{{{QUOTE_TOTAL}}}} LABEL={{{{QUOTE_LABEL}}}} "
                f"SHORT={{{{QUOTE_SHORT_ID}}}} "
                f"LINK={{{{QUOTE_ADMIN_LINK}}}} "
                f"CUST={{{{CUSTOMER_NAME}}}}</div>"
            ),
        )
        try:
            from services.quote_notifications import render_email
            doc = _doc()
            subject, html, text = await render_email(
                event="quote_accepted", doc_type="quote",
                doc=doc, frontend_origin="https://x",
                tenant_id="t1",
            )
            assert sentinel in html
            assert "Alice Buyer accepted quote #" in html
            assert "$1,234.50" in html
            assert "https://x" in html
            # Subject stays composed inline per decision (c).
            assert subject.startswith("[Quote #")
            assert "Accepted by Alice Buyer" in subject
        finally:
            await _wipe()

    _run(_go())


def test_declined_db_body_wins_over_hardcoded_fallback():
    async def _go():
        await _wipe()
        sentinel = f"DECLINED-{uuid.uuid4().hex[:8]}"
        await _seed_row(
            code="quote_declined_owner_email",
            tenant_id_scope=None,
            body=(
                f"<div>{sentinel} {{{{QUOTE_HEADLINE}}}} — "
                f"CUST={{{{CUSTOMER_NAME}}}}</div>"
            ),
        )
        try:
            from services.quote_notifications import render_email
            doc = _doc(decline_reason="too expensive")
            subject, html, text = await render_email(
                event="quote_declined", doc_type="quote",
                doc=doc, frontend_origin="https://x",
                tenant_id="t1",
            )
            assert sentinel in html
            assert "declined quote #" in html
            assert "Reason: too expensive" in html
            assert subject.startswith("[Quote #")
            assert "Declined by Alice Buyer" in subject
        finally:
            await _wipe()

    _run(_go())


def test_tenant_specific_row_wins_over_global_default():
    async def _go():
        await _wipe()
        tid = f"tenant-{uuid.uuid4().hex[:8]}"
        gs = f"GLOBAL-{uuid.uuid4().hex[:8]}"
        ts = f"TENANT-{uuid.uuid4().hex[:8]}"
        await _seed_row(code="quote_accepted_owner_email",
                          tenant_id_scope=None, body=f"<p>{gs}</p>")
        await _seed_row(code="quote_accepted_owner_email",
                          tenant_id_scope=tid, body=f"<p>{ts}</p>")
        try:
            from services.quote_notifications import render_email
            _, html, _ = await render_email(
                event="quote_accepted", doc_type="quote",
                doc=_doc(), frontend_origin="https://x",
                tenant_id=tid,
            )
            assert ts in html
            assert gs not in html
        finally:
            await _wipe()

    _run(_go())


def test_hardcoded_fallback_fires_when_row_absent():
    async def _go():
        await _wipe()
        from services.quote_notifications import render_email
        subject, html, text = await render_email(
            event="quote_accepted", doc_type="quote",
            doc=_doc(), frontend_origin="https://x",
            tenant_id="tenant-z",
        )
        # Hardcoded body renders the headline + link.
        assert "Alice Buyer accepted quote #" in html
        assert "$1,234.50" in html
        assert "https://x" in html
        # Text plaintext body always emitted from the inline builder.
        assert "Total: $1,234.50" in text

    _run(_go())
