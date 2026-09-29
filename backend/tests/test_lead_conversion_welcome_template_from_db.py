"""Phase EMAIL-MIGRATE · Batch 2 · Feb-2026 — DB-first render for the
lead-to-customer conversion welcome email.

Locks two contracts:

1. When a ``lead_conversion_welcome_email`` row exists, the DB body
   wins over the hardcoded fallback that
   :func:`services.lead_conversion_notifications._send_welcome_email`
   used pre-migration.
2. BUGFIX invariant — the seeded body renders through
   ``{{COMPANY_NAME}}`` / ``{{COMPANY_PHONE}}``, so a tenant whose
   business-card name is NOT ``Pool & Landscaping of Vistancia``
   sees their own brand + phone in the outbound email.  The
   pre-migration builder hardcoded both.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict, List, Optional

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
    import services.lead_conversion_notifications as _mod
    _orig_cfg = _cfg.db
    _orig_mod = getattr(_mod, "db", None)
    _cfg.db = fresh_db
    if _orig_mod is not None:
        _mod.db = fresh_db
    try:
        yield
    finally:
        _cfg.db = _orig_cfg
        if _orig_mod is not None:
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


async def _wipe_rows(tenant_id: str, cid: str, lead_id: str) -> None:
    await _db().marketing_templates.delete_many(
        {"code": "lead_conversion_welcome_email"},
    )
    await _db().tenants.delete_many({"id": tenant_id})
    await _db().marketing_deliveries.delete_many(
        {"tenant_id": tenant_id, "customer_id": cid},
    )


async def _seed_tenant(tenant_id: str, name: str,
                        phone: str = "+15559990000") -> None:
    from utils import now_iso
    await _db().tenants.insert_one({
        "id": tenant_id, "name": name,
        "settings": {"business_card": {
            "company_name": name, "phone": phone,
        }},
        "created_at": now_iso(), "updated_at": now_iso(),
    })


async def _seed_row(*, tenant_id_scope, subject: str, body: str) -> None:
    from utils import new_id, now_iso
    await _db().marketing_templates.insert_one({
        "id": new_id(),
        "code": "lead_conversion_welcome_email",
        "tenant_id": tenant_id_scope,
        "subject": subject, "body": body,
        "category": "lead", "channel": "email",
        "kind": "transactional",
        "is_system": True, "is_default": True, "editable": True,
        "created_at": now_iso(), "updated_at": now_iso(),
    })


def _customer(cid: str) -> Dict[str, Any]:
    return {
        "id": cid, "name": "Sam Convert",
        "email": "sam@example.com",
        "phone": "+15550000000",
        "notification_preferences": {
            "email": {"enabled": True},
            "email_marketing_enabled": True,
        },
    }


def _capture_deliveries(monkeypatch) -> List[Dict[str, Any]]:
    captured: List[Dict[str, Any]] = []

    async def _fake(**kwargs):
        captured.append(kwargs)
        return "row-id"

    import services.lead_conversion_notifications as _mod
    monkeypatch.setattr(_mod, "_record_delivery", _fake)
    return captured


def test_db_body_wins_and_uses_company_name_not_hardcoded(monkeypatch):
    from services.lead_conversion_notifications import _send_welcome_email

    async def _go():
        tenant_id = f"t-{uuid.uuid4().hex[:8]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        lead_id = f"l-{uuid.uuid4().hex[:8]}"
        await _wipe_rows(tenant_id, cid, lead_id)
        # Non-plofv tenant name — the BUGFIX assertion below verifies
        # the outbound email uses THIS name, not the plofv default.
        await _seed_tenant(tenant_id, "Acme Landscaping",
                             phone="+15551234567")
        sentinel = f"WELCOME-SENTINEL-{uuid.uuid4().hex[:8]}"
        await _seed_row(
            tenant_id_scope=None,
            subject="Welcome to {{COMPANY_NAME}} — your account is ready",
            body=(
                f"<div>{sentinel} Welcome, {{{{CUSTOMER_NAME}}}}! "
                f"You picked {{{{COMPANY_NAME}}}}. Call "
                f"{{{{COMPANY_PHONE}}}}.  "
                f"Portal: {{{{PORTAL_LINK}}}}</div>"
            ),
        )
        captured = _capture_deliveries(monkeypatch)
        try:
            await _send_welcome_email(
                tenant_id=tenant_id, customer=_customer(cid),
                lead_id=lead_id,
            )
            assert captured, "expected at least one delivery"
            body = captured[0]["body"]
            subject = captured[0]["subject"]
            assert sentinel in body
            assert "Acme Landscaping" in body
            assert "+15551234567" in body
            assert subject == (
                "Welcome to Acme Landscaping — your account is ready"
            )
            # BUGFIX invariant.
            assert "Pool & Landscaping of Vistancia" not in body
            assert "Pool & Landscaping of Vistancia" not in subject
            for phone_literal in ("602-887-4400", "(602) 887-4400",
                                    "6028874400"):
                assert phone_literal not in body
        finally:
            await _wipe_rows(tenant_id, cid, lead_id)

    _run(_go())


def test_tenant_specific_row_wins_over_global_default(monkeypatch):
    from services.lead_conversion_notifications import _send_welcome_email

    async def _go():
        tenant_id = f"t-{uuid.uuid4().hex[:8]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        lead_id = f"l-{uuid.uuid4().hex[:8]}"
        await _wipe_rows(tenant_id, cid, lead_id)
        await _seed_tenant(tenant_id, "Acme")
        gs = f"GLOBAL-{uuid.uuid4().hex[:8]}"
        ts = f"TENANT-{uuid.uuid4().hex[:8]}"
        await _seed_row(tenant_id_scope=None, subject="G",
                          body=f"<p>{gs}</p>")
        await _seed_row(tenant_id_scope=tenant_id, subject="T",
                          body=f"<p>{ts}</p>")
        captured = _capture_deliveries(monkeypatch)
        try:
            await _send_welcome_email(
                tenant_id=tenant_id, customer=_customer(cid),
                lead_id=lead_id,
            )
            body = captured[0]["body"]
            assert ts in body
            assert gs not in body
        finally:
            await _wipe_rows(tenant_id, cid, lead_id)

    _run(_go())


def test_hardcoded_fallback_fires_when_row_absent_and_uses_company_name(
    monkeypatch,
):
    """When no DB row exists, the hardcoded fallback body still
    renders — but it now pulls the tenant's business-card
    ``company_name`` (not the hardcoded plofv literal) and the
    business-card phone (not the hardcoded 602 literal)."""
    from services.lead_conversion_notifications import _send_welcome_email

    async def _go():
        tenant_id = f"t-{uuid.uuid4().hex[:8]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        lead_id = f"l-{uuid.uuid4().hex[:8]}"
        await _wipe_rows(tenant_id, cid, lead_id)
        await _seed_tenant(tenant_id, "Bayside Pools",
                             phone="+15559876543")
        captured = _capture_deliveries(monkeypatch)
        try:
            await _send_welcome_email(
                tenant_id=tenant_id, customer=_customer(cid),
                lead_id=lead_id,
            )
            body = captured[0]["body"]
            subject = captured[0]["subject"]
            # Fallback body renders the tenant name, not the plofv default.
            assert "Bayside Pools" in body
            assert "+15559876543" in body
            assert subject == (
                "Welcome to Bayside Pools — your account is ready"
            )
            # BUGFIX invariant even on the fallback path.
            assert "Pool & Landscaping of Vistancia" not in body
            assert "Pool & Landscaping of Vistancia" not in subject
            for phone_literal in ("602-887-4400", "(602) 887-4400",
                                    "6028874400"):
                assert phone_literal not in body
        finally:
            await _wipe_rows(tenant_id, cid, lead_id)

    _run(_go())
