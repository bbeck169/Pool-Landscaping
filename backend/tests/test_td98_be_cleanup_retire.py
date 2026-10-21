"""TD-98-be-cleanup-retire · Feb-2026 — retire regression guard.

Shipped under commit ``td98-be-cleanup-retire``. The legacy
``GET /customers/{cid}/communication-timeline`` endpoint was retired
in favor of the Phase B super-timeline at
``GET /customers/{cid}/timeline``. This test locks the retire so a
future refactor cannot silently re-introduce the deprecated handler
without an operator-approved un-retire ticket.

Context:
  * Mobile track completed migration under commits ``db6edd59f``
    (adapter) + ``e0bc500ae`` (component) + ``0e86b4a3b`` (doc).
  * Web migration landed under ``td98b-fe`` (reap orphan Wave A +
    migrate ``CustomerDetail.jsx`` to ``CustomerFullTimeline``).
  * Operator-approved regression per TD-98/99 close-out — three
    source classes (``notification_dispatch_log``, ``audit_events``
    with K6/K14 event types, ``delivery_error`` field) have no
    replacement reader on the Phase B super-timeline. Bookmarked
    as **TD-98-be-sources (P2 backend)** in TECH_DEBT.md.

Pattern parity: mirrors the ASGITransport harness established by
``test_td96_lead_recipient_exclusion.py`` and
``test_td98_99_xref_lead_comms_cross_visibility.py``.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from dotenv import dotenv_values
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient


_TEST_DIR = Path(__file__).resolve().parent
_BE = dotenv_values(_TEST_DIR.parent / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(MONGO_URL, io_loop=_LOOP)
_DB = _MC[DB_NAME]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _build_app():
    from routers import communication_timeline as mod
    from routers.tenants import get_current_tenant
    from utils import get_current_user

    user = {"id": "u_test", "role": "admin",
             "tenant_id": "TESTtd98retire_tenant"}
    tenant = {"id": "TESTtd98retire_tenant"}
    app = FastAPI()
    app.include_router(mod.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_tenant] = lambda: tenant
    mod.db = _DB
    return app


# ═══════════════════════════════════════════════════════════════════
# §1 · Retired endpoint returns 410 Gone with migration guidance
# ═══════════════════════════════════════════════════════════════════
def test_retired_endpoint_returns_410_with_migration_guidance():
    async def _go():
        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport,
                                 base_url="http://test") as c:
            r = await c.get("/api/customers/cust-x/communication-timeline")
        return r

    r = _run(_go())
    assert r.status_code == 410, (
        f"Retired endpoint must return 410 Gone, got {r.status_code}"
    )
    detail = r.json().get("detail", "")
    assert "retired" in detail.lower()
    assert "/customers/{cid}/timeline" in detail, (
        "410 response must point consumers at the Phase B super-timeline"
    )
    assert "TD-98-be-cleanup-retire" in detail
    assert "TD-98-be-sources" in detail


# ═══════════════════════════════════════════════════════════════════
# §2 · Preserved helpers still importable (recoverable primitives
# for the eventual TD-98-be-sources ship — operator default is
# preserve-with-comment, see TD-98-be-cleanup-retire operator spec).
# ═══════════════════════════════════════════════════════════════════
def test_preserved_helpers_are_still_importable_for_td98_be_sources():
    from routers.communication_timeline import (
        _dispatch_to_item, _audit_to_item, _strip_admin_fields,
        _load_customer, _customer_addresses, _preview,
    )

    assert callable(_dispatch_to_item), (
        "_dispatch_to_item must remain importable — preserved for "
        "TD-98-be-sources per operator spec. If this import fails, "
        "the retire ship inadvertently deleted a recoverable primitive."
    )
    assert callable(_audit_to_item)
    assert callable(_strip_admin_fields)
    assert callable(_load_customer)
    assert callable(_customer_addresses)
    assert callable(_preview)
