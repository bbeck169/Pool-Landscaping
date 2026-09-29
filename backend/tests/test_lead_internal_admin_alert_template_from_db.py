"""Phase EMAIL-MIGRATE · Batch 2 · Feb-2026 — DB-first render for the
internal lead-created admin alert email.

Locks the contract that
:func:`services.leads_side_effects._fire_internal_notification`
prefers the ``lead_internal_admin_alert_email`` row in
``marketing_templates`` over the hardcoded newline→<br> conversion
of ``_compose_internal``'s plain-text body.
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
        {"code": "lead_internal_admin_alert_email"},
    )
    await _db().marketing_deliveries.delete_many(
        {"trigger_id": f"lead_created_internal_notification:{lead_id}"},
    )


async def _seed_row(*, tenant_id_scope, subject: str, body: str) -> None:
    from utils import new_id, now_iso
    await _db().marketing_templates.insert_one({
        "id": new_id(),
        "code": "lead_internal_admin_alert_email",
        "tenant_id": tenant_id_scope,
        "subject": subject, "body": body,
        "category": "lead", "channel": "email",
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
                "provider_response_id": "test", "error": None}


def _cfg() -> Dict[str, Any]:
    return {
        "enabled": True, "email": "admin@example.com",
        "sms": "", "serviced_states": ["AZ", "NM"],
        "app_host": "https://app.example.com",
    }


def test_db_body_wins_over_hardcoded_fallback(monkeypatch):
    from services.leads_side_effects import _fire_internal_notification

    async def _go():
        tenant_id = f"t-{uuid.uuid4().hex[:8]}"
        lead_id = f"l-{uuid.uuid4().hex[:8]}"
        await _wipe_rows(tenant_id, lead_id)
        sentinel = f"INTERNAL-SENTINEL-{uuid.uuid4().hex[:8]}"
        await _seed_row(
            tenant_id_scope=None,
            subject="ignored",
            body=(
                f"<article>{sentinel} {{{{LEAD_REJECT_HEADER}}}} "
                f"NAME={{{{LEAD_NAME}}}} PH={{{{LEAD_PHONE}}}} "
                f"EM={{{{LEAD_EMAIL}}}} ADDR={{{{PROPERTY_ADDRESS}}}} "
                f"MSG={{{{LEAD_MESSAGE}}}} LINK={{{{LEAD_LINK}}}}</article>"
            ),
        )
        capture = _Capture()
        monkeypatch.setattr(
            "services.email.resend_adapter.send", capture,
        )
        monkeypatch.setattr(
            "services.sms.rc_adapter.send", _Capture(),
        )
        try:
            lead = {
                "id": lead_id, "tenant_id": tenant_id,
                "name": "Emma Prospect", "phone": "+15551110000",
                "email": "emma@example.com",
                "service_address": "9 Palm Rd",
                "message": "Interested in weekly service",
                "source": "webform",
                "created_at": "2026-02-22T12:00:00+00:00",
            }
            await _fire_internal_notification(lead, _cfg(), None)
            assert len(capture.calls) == 1
            call = capture.calls[0]["kwargs"]
            html = call["html"]
            assert sentinel in html, (
                "DB body did not surface for internal admin alert"
            )
            assert "Emma Prospect" in html
            assert "+15551110000" in html
            assert "emma@example.com" in html
            assert "9 Palm Rd" in html
            assert "Interested in weekly service" in html
            assert "https://app.example.com/leads/" in html
            # No reject header when reject_state is None.
            assert "STATUS: REJECTED" not in html
            # Subject stays composed inline — not the DB row's
            # "ignored" literal.
            assert call["subject"].startswith("[New lead]")
            assert "Emma Prospect" in call["subject"]
        finally:
            await _wipe_rows(tenant_id, lead_id)

    _run(_go())


def test_reject_header_surfaces_when_reject_state_present(monkeypatch):
    from services.leads_side_effects import _fire_internal_notification

    async def _go():
        tenant_id = f"t-{uuid.uuid4().hex[:8]}"
        lead_id = f"l-{uuid.uuid4().hex[:8]}"
        await _wipe_rows(tenant_id, lead_id)
        await _seed_row(
            tenant_id_scope=None,
            subject="ignored",
            body=(
                "<div>HEADER=[{{LEAD_REJECT_HEADER}}] "
                "STATE=[{{REJECT_STATE}}]</div>"
            ),
        )
        capture = _Capture()
        monkeypatch.setattr(
            "services.email.resend_adapter.send", capture,
        )
        monkeypatch.setattr(
            "services.sms.rc_adapter.send", _Capture(),
        )
        try:
            lead = {"id": lead_id, "tenant_id": tenant_id,
                    "name": "Frank OOS", "email": "f@x.com",
                    "service_address": "1 Elsewhere Ln, CA"}
            await _fire_internal_notification(lead, _cfg(), "CA")
            call = capture.calls[0]["kwargs"]
            assert "STATUS: REJECTED — out of state (CA)" in call["html"]
            assert call["subject"].startswith("[REJECTED]")
        finally:
            await _wipe_rows(tenant_id, lead_id)

    _run(_go())


def test_tenant_specific_row_wins_over_global_default(monkeypatch):
    from services.leads_side_effects import _fire_internal_notification

    async def _go():
        tenant_id = f"t-{uuid.uuid4().hex[:8]}"
        lead_id = f"l-{uuid.uuid4().hex[:8]}"
        await _wipe_rows(tenant_id, lead_id)
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
        monkeypatch.setattr(
            "services.sms.rc_adapter.send", _Capture(),
        )
        try:
            lead = {"id": lead_id, "tenant_id": tenant_id,
                    "name": "Gina", "email": "g@x.com"}
            await _fire_internal_notification(lead, _cfg(), None)
            html = capture.calls[0]["kwargs"]["html"]
            assert ts in html
            assert gs not in html
        finally:
            await _wipe_rows(tenant_id, lead_id)

    _run(_go())


def test_hardcoded_fallback_fires_when_row_absent(monkeypatch):
    from services.leads_side_effects import _fire_internal_notification

    async def _go():
        tenant_id = f"t-{uuid.uuid4().hex[:8]}"
        lead_id = f"l-{uuid.uuid4().hex[:8]}"
        await _wipe_rows(tenant_id, lead_id)
        capture = _Capture()
        monkeypatch.setattr(
            "services.email.resend_adapter.send", capture,
        )
        monkeypatch.setattr(
            "services.sms.rc_adapter.send", _Capture(),
        )
        try:
            lead = {"id": lead_id, "tenant_id": tenant_id,
                    "name": "Hank", "phone": "+15550000001",
                    "email": "h@x.com"}
            await _fire_internal_notification(lead, _cfg(), None)
            call = capture.calls[0]["kwargs"]
            # Hardcoded fallback = plain newline→<br> conversion.
            assert "Hank" in call["html"]
            assert "+15550000001" in call["html"]
            assert "<br>" in call["html"]
        finally:
            await _wipe_rows(tenant_id, lead_id)

    _run(_go())
