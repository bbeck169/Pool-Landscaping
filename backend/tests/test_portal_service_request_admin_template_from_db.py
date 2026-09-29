"""Phase EMAIL-MIGRATE · Batch 2 · Feb-2026 — DB-first render for the
portal service-request admin notification email.

Locks the contract that
:func:`routers.customer_portal.create_service_request` prefers the
``portal_service_request_admin_email`` row in ``marketing_templates``
over the hardcoded fallback body.
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
    import routers.customer_portal as _mod
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


async def _wipe_rows(tenant_id: str, cid: str) -> None:
    await _db().marketing_templates.delete_many(
        {"code": "portal_service_request_admin_email"},
    )
    await _db().customers.delete_many({"id": cid})
    await _db().messages.delete_many({"customer_id": cid,
                                        "tenant_id": tenant_id})


class _Capture:
    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    async def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return {"provider_status": "sent",
                "provider_response_id": "test",
                "attempts": 1, "error": None}


class _AsyncNoop:
    def __init__(self, ret=None):
        self._ret = ret

    async def __call__(self, *_a, **_k):
        return self._ret


def _wire(monkeypatch):
    sms = _Capture()
    email = _Capture()
    monkeypatch.setattr("services.sms.rc_adapter.send", sms)
    monkeypatch.setattr("services.email.resend_adapter.send", email)
    monkeypatch.setattr(
        "services.notifications.enqueue_for_tenant_admins",
        _AsyncNoop([]),
    )
    return {"email": email, "sms": sms}


def _seed_customer(tenant_id: str, cid: str) -> None:
    async def _go():
        await _db().customers.insert_one({
            "id": cid, "tenant_id": tenant_id,
            "name": "Zoe Portal", "email": "zoe@portal.example",
            "phone": "+15550009999",
            "service_address": "123 Cactus Way",
        })
    _run(_go())


async def _seed_customer_async(tenant_id: str, cid: str) -> None:
    await _db().customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "Zoe Portal", "email": "zoe@portal.example",
        "phone": "+15550009999",
        "service_address": "123 Cactus Way",
    })


async def _seed_row(*, tenant_id_scope, body: str, subject: str) -> None:
    from utils import new_id, now_iso
    await _db().marketing_templates.insert_one({
        "id": new_id(),
        "code": "portal_service_request_admin_email",
        "tenant_id": tenant_id_scope,
        "subject": subject, "body": body,
        "category": "portal", "channel": "email",
        "kind": "transactional",
        "is_system": True, "is_default": True, "editable": True,
        "created_at": now_iso(), "updated_at": now_iso(),
    })


def test_db_body_wins_over_hardcoded_fallback(monkeypatch):
    from routers.customer_portal import (
        ServiceRequestIn, create_service_request,
    )

    async def _go():
        tenant_id = f"t-{uuid.uuid4().hex[:8]}"
        cid = f"cust-{uuid.uuid4().hex[:12]}"
        await _wipe_rows(tenant_id, cid)
        await _seed_customer_async(tenant_id, cid)
        sentinel = f"PORTAL-SENTINEL-{uuid.uuid4().hex[:8]}"
        await _seed_row(
            tenant_id_scope=None,
            subject="Subj-{{CUSTOMER_NAME}}",
            body=(
                f"<div>{sentinel} for {{{{CUSTOMER_NAME}}}} @ "
                f"{{{{PROPERTY_ADDRESS}}}} — {{{{REQUEST_DETAILS}}}}"
                f" / phone {{{{TENANT_SERVICE_REQUEST_PHONE}}}}</div>"
            ),
        )
        wire = _wire(monkeypatch)
        try:
            user = {"id": "u1", "role": "customer", "customer_id": cid,
                    "name": "SessionZoe"}
            tenant = {"id": tenant_id, "settings": {"notifications": {
                "service_request_email": "admin@t.com",
                "service_request_sms": "+15555550100",
            }}}
            resp = await create_service_request(
                ServiceRequestIn(
                    service_type="Pool Cleaning",
                    request_details="pH is high",
                    address="Home",
                ),
                user=user, tenant=tenant,
            )
            assert resp.get("ok") is True
            email_html = wire["email"].calls[0]["kwargs"].get("html") or ""
            assert sentinel in email_html, (
                "DB body did not surface — the create_service_request "
                "path must prefer marketing_templates over the "
                "hardcoded HTML builder"
            )
            assert "Zoe Portal" in email_html
            assert "pH is high" in email_html
            # PHONE-PURGE invariant — the tenant-configured phone
            # surfaced, no hardcoded 602 literal leaked.
            assert "+15555550100" in email_html
            for phone_literal in ("602-887-4400", "(602) 887-4400",
                                    "6028874400"):
                assert phone_literal not in email_html
            subject = wire["email"].calls[0]["kwargs"].get("subject") or ""
            assert subject.startswith("Subj-")
            assert "{{CUSTOMER_NAME}}" not in subject
        finally:
            await _wipe_rows(tenant_id, cid)

    _run(_go())


def test_tenant_specific_row_wins_over_global_default(monkeypatch):
    from routers.customer_portal import (
        ServiceRequestIn, create_service_request,
    )

    async def _go():
        tenant_id = f"t-{uuid.uuid4().hex[:8]}"
        cid = f"cust-{uuid.uuid4().hex[:12]}"
        await _wipe_rows(tenant_id, cid)
        await _seed_customer_async(tenant_id, cid)
        gs = f"GLOBAL-{uuid.uuid4().hex[:8]}"
        ts = f"TENANT-{uuid.uuid4().hex[:8]}"
        await _seed_row(tenant_id_scope=None,
                          subject="Global", body=f"<p>{gs}</p>")
        await _seed_row(tenant_id_scope=tenant_id,
                          subject="Tenant", body=f"<p>{ts}</p>")
        wire = _wire(monkeypatch)
        try:
            user = {"id": "u1", "role": "customer", "customer_id": cid,
                    "name": "X"}
            await create_service_request(
                ServiceRequestIn(service_type="Pool Cleaning"),
                user=user, tenant={"id": tenant_id},
            )
            email_html = wire["email"].calls[0]["kwargs"].get("html") or ""
            assert ts in email_html
            assert gs not in email_html
        finally:
            await _wipe_rows(tenant_id, cid)

    _run(_go())


def test_hardcoded_fallback_fires_when_row_absent(monkeypatch):
    from routers.customer_portal import (
        ServiceRequestIn, create_service_request,
    )

    async def _go():
        tenant_id = f"t-{uuid.uuid4().hex[:8]}"
        cid = f"cust-{uuid.uuid4().hex[:12]}"
        await _wipe_rows(tenant_id, cid)
        await _seed_customer_async(tenant_id, cid)
        wire = _wire(monkeypatch)
        try:
            user = {"id": "u1", "role": "customer", "customer_id": cid,
                    "name": "Z"}
            await create_service_request(
                ServiceRequestIn(
                    service_type="Pool Cleaning",
                    request_details="hardcoded-fallback-test-details",
                ),
                user=user, tenant={"id": tenant_id},
            )
            email_html = wire["email"].calls[0]["kwargs"].get("html") or ""
            # Hardcoded HTML mentions "New Service Request" heading.
            assert "New Service Request" in email_html
            assert "Zoe Portal" in email_html
            assert "hardcoded-fallback-test-details" in email_html
        finally:
            await _wipe_rows(tenant_id, cid)

    _run(_go())
