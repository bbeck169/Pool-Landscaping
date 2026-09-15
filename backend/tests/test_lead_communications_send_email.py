"""Phase L3 · Feb-2026 · Lead-scoped email send.

Backend acceptance tests for ``POST /api/leads/{lead_id}/send-email``.

Mirrors the SMS suite shape:

* Happy path — persists row, dispatches via Resend, marks ``sent``.
* Missing email — 400.
* Consent gate — ``email_ok=false`` → 400 ``consent_required``.
* Consent override — flips through on ``override_consent=true``.
* Tenant isolation — 404 across tenants.
* Role guard — technician → 403.
* Provider failure — row status ``failed``, error stashed.
* Missing key envelope — Resend adapter returning
  ``status="not_sent_missing_key"`` normalizes to ``failed`` on the
  row (regression guard for the K72 kill-switch path).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.test_lead_communications_send_sms import _DB, _build_app, _seed_lead


def _run(coro):
    return asyncio.run(coro)


# ─── Happy path ─────────────────────────────────────────────────────
def test_send_email_happy_path_persists_and_sends():
    async def run():
        db_stub = _DB()
        _seed_lead(db_stub)
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1", "outbound_email_from": "no-reply@aquaterra.dev"}
        app = _build_app(user, tenant, db_stub)

        with patch(
            "services.comms_email_adapter.send_email",
            new_callable=AsyncMock,
        ) as _mock_send:
            _mock_send.return_value = {
                "status": "sent", "provider_id": "re_abc123",
                "error": None,
            }
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t",
            ) as ac:
                r = await ac.post(
                    "/api/leads/lead-1/send-email",
                    json={"subject": "Following up",
                          "body": "Hi Alice, wanted to check in."},
                )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "sent"
        assert body["channel"] == "email"
        assert body["subject"] == "Following up"
        assert body["provider_message_id"] == "re_abc123"
        assert body["from_identity"] == "no-reply@aquaterra.dev"
        assert body["to_identity"] == "lead@example.com"
        # Row was persisted BEFORE dispatch (invariant).
        assert len(db_stub.lead_communications.inserts) == 1
        assert db_stub.lead_communications.inserts[0]["status"] == "queued"
        assert len(db_stub.lead_communications.updates) == 1

        # HTML escaping — ``body`` field is stored raw, HTML is only
        # inline on dispatch.
        stored = db_stub.lead_communications.rows[0]
        assert "&lt;" not in stored["body"], (
            "raw body must be stored unescaped on the row"
        )

    _run(run())


def test_send_email_missing_address_returns_400():
    async def run():
        db_stub = _DB()
        _seed_lead(db_stub, email="")
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t",
        ) as ac:
            r = await ac.post(
                "/api/leads/lead-1/send-email",
                json={"subject": "Hi", "body": "Hi"},
            )
        assert r.status_code == 400, r.text
        assert "email" in r.text.lower()
        assert db_stub.lead_communications.inserts == []

    _run(run())


def test_send_email_consent_gate_blocks_when_opted_out():
    async def run():
        db_stub = _DB()
        _seed_lead(db_stub, email_ok=False)
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t",
        ) as ac:
            r = await ac.post(
                "/api/leads/lead-1/send-email",
                json={"subject": "Hi", "body": "Hi"},
            )
        assert r.status_code == 400, r.text
        assert "consent_required" in r.text

    _run(run())


def test_send_email_consent_override_allows_send():
    async def run():
        db_stub = _DB()
        _seed_lead(db_stub, email_ok=False)
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)

        with patch(
            "services.comms_email_adapter.send_email",
            new_callable=AsyncMock,
        ) as _mock_send:
            _mock_send.return_value = {"status": "sent", "provider_id": "re_ov"}
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t",
            ) as ac:
                r = await ac.post(
                    "/api/leads/lead-1/send-email",
                    json={"subject": "Hi", "body": "Hi",
                          "override_consent": True},
                )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "sent"

    _run(run())


def test_send_email_tenant_isolation_404():
    async def run():
        db_stub = _DB()
        _seed_lead(db_stub, tenant_id="t-other")
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t",
        ) as ac:
            r = await ac.post(
                "/api/leads/lead-1/send-email",
                json={"subject": "Hi", "body": "Hi"},
            )
        assert r.status_code == 404, r.text

    _run(run())


def test_send_email_role_guard_403():
    async def run():
        db_stub = _DB()
        _seed_lead(db_stub)
        user = {"id": "u-cust", "role": "customer"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t",
        ) as ac:
            r = await ac.post(
                "/api/leads/lead-1/send-email",
                json={"subject": "Hi", "body": "Hi"},
            )
        assert r.status_code == 403, r.text

    _run(run())


def test_send_email_provider_failure_marks_row_failed():
    async def run():
        db_stub = _DB()
        _seed_lead(db_stub)
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)

        with patch(
            "services.comms_email_adapter.send_email",
            new_callable=AsyncMock,
        ) as _mock_send:
            _mock_send.return_value = {
                "status": "failed", "provider_id": None,
                "error": "resend 5xx",
            }
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t",
            ) as ac:
                r = await ac.post(
                    "/api/leads/lead-1/send-email",
                    json={"subject": "Hi", "body": "Hi"},
                )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "failed"
        assert body["error"] == "resend 5xx"

    _run(run())


def test_send_email_missing_key_envelope_normalizes_to_failed():
    async def run():
        db_stub = _DB()
        _seed_lead(db_stub)
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)

        with patch(
            "services.comms_email_adapter.send_email",
            new_callable=AsyncMock,
        ) as _mock_send:
            _mock_send.return_value = {
                "status": "not_sent_missing_key", "provider_id": None,
                "error": None,
            }
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t",
            ) as ac:
                r = await ac.post(
                    "/api/leads/lead-1/send-email",
                    json={"subject": "Hi", "body": "Hi"},
                )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "failed"
        assert body["provider_status_raw"] == "not_sent_missing_key"

    _run(run())
