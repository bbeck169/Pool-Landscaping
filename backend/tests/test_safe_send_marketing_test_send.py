"""SAFE-SEND-C · Feb-2026 — marketing test-send endpoint gate coverage.

Locks the ``/api/marketing/templates/{tid}/test-send`` endpoint
against two regressions:

1. **Context propagation** — the router MUST pass
   ``context=CommsContext.TEST`` into the low-level adapter so the
   adapter's redirect preflight fires.  A router regression that
   silently omitted ``context=`` would send the test blast to the
   caller-supplied recipient in production; the assertion below
   catches that.

2. **Envelope surface** — the response returned to the FE MUST
   expose the six SAFE-SEND fields the SAFE-SEND-B "Safe Send"
   badge renders from: ``redirected``, ``safe_send_context``,
   ``intended_recipient_redacted``, ``actual_recipient_redacted``,
   ``provider_status``, ``was_mock``.  A drop of any of those
   silently hides the redirect state from the admin.

Both channels (email + SMS) are exercised.  The adapter itself is
stubbed via ``monkeypatch.setattr`` so the test stays hermetic and
does not require Resend / RingCentral creds.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════
def _fake_template(channel: str) -> dict:
    return {
        "id": "tpl-abc",
        "tenant_id": "t1",
        "name": "Test",
        "channel": channel,
        "category": "general",
        "subject": "Hello {{CUSTOMER_FIRST_NAME}}" if channel == "email" else None,
        "body": "Hi there!",
        "active": True,
        "system": False,
    }


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _reset_rate_limit(user_id: str) -> None:
    from routers import marketing_templates as mt
    mt._test_send_hits.pop(user_id, None)


# ═══════════════════════════════════════════════════════════════════
# Email — context + envelope surface
# ═══════════════════════════════════════════════════════════════════
def test_test_send_email_forwards_test_context(monkeypatch):
    """The router passes ``CommsContext.TEST`` into the resend
    adapter — proving AGENT-safe test flows can never leak to a
    real customer."""
    from routers import marketing_templates as mt
    from services.comms_env_guard import CommsContext

    _reset_rate_limit("u1")

    # Adapter stub — captures the context kwarg + returns an
    # enriched envelope shaped like a real redirected send.
    captured: dict = {}

    async def _fake_resend_send(**kwargs):
        captured.update(kwargs)
        return {
            "provider": "resend",
            "provider_status": "sent",
            "provider_response_id": "resend-abc",
            "attempts": 1,
            "error": None,
            "redirected": True,
            "safe_send_context": "test",
            "intended_recipient_redacted": "cu***@example.com",
            "actual_recipient_redacted": "ad***@acme.com",
        }

    monkeypatch.setattr(mt, "_resend_send", _fake_resend_send)

    # Template lookup stub — no DB roundtrip.
    fake_db = MagicMock()
    fake_db.marketing_templates.find_one = AsyncMock(
        return_value=_fake_template("email"),
    )
    monkeypatch.setattr(mt, "db", fake_db)

    body = mt.TemplateTestSendBody(
        to="customer@example.com",
        sample_context={
            "customer": {"first_name": "Jane", "email": "customer@example.com"},
        },
    )

    result = _run(mt.test_send_template(
        tid="tpl-abc",
        body=body,
        user={"id": "u1", "role": "admin"},
        tenant={"id": "t1", "name": "Acme"},
    ))

    # 1. Context propagation.
    assert captured.get("context") == CommsContext.TEST, (
        f"router omitted context=TEST — got {captured.get('context')!r}"
    )

    # 2. Envelope surface — all six SAFE-SEND fields present.
    for key in (
        "redirected", "safe_send_context",
        "intended_recipient_redacted", "actual_recipient_redacted",
        "provider_status", "was_mock",
    ):
        assert key in result, f"safe-send field missing from envelope: {key}"

    # 3. Field values threaded through from the adapter's envelope.
    assert result["redirected"] is True
    assert result["safe_send_context"] == "test"
    assert result["intended_recipient_redacted"] == "cu***@example.com"
    assert result["actual_recipient_redacted"] == "ad***@acme.com"
    assert result["provider_status"] == "sent"
    assert result["was_mock"] is False
    assert result["ok"] is True


def test_test_send_email_surface_mocked_envelope(monkeypatch):
    """When the adapter returns ``provider=mock`` (no Resend key),
    the router still returns the six SAFE-SEND fields with
    ``was_mock=True`` so the FE can render the correct badge state."""
    from routers import marketing_templates as mt

    _reset_rate_limit("u1")

    async def _fake_resend_send(**kwargs):
        return {
            "provider": "mock",
            "provider_status": "mocked",
            "provider_response_id": None,
            "attempts": 0,
            "error": None,
            "redirected": True,
            "safe_send_context": "test",
            "intended_recipient_redacted": "cu***@example.com",
            "actual_recipient_redacted": "ad***@acme.com",
        }

    monkeypatch.setattr(mt, "_resend_send", _fake_resend_send)
    fake_db = MagicMock()
    fake_db.marketing_templates.find_one = AsyncMock(
        return_value=_fake_template("email"),
    )
    monkeypatch.setattr(mt, "db", fake_db)

    body = mt.TemplateTestSendBody(to="customer@example.com")
    result = _run(mt.test_send_template(
        tid="tpl-abc", body=body,
        user={"id": "u1", "role": "admin"},
        tenant={"id": "t1", "name": "Acme"},
    ))
    assert result["provider"] == "mock"
    assert result["was_mock"] is True
    assert result["provider_status"] == "mocked"
    assert result["ok"] is True


# ═══════════════════════════════════════════════════════════════════
# SMS — context + envelope surface
# ═══════════════════════════════════════════════════════════════════
def test_test_send_sms_forwards_test_context(monkeypatch):
    """The router passes ``CommsContext.TEST`` into the RC adapter
    for SMS test-sends as well."""
    from routers import marketing_templates as mt
    import services.sms.rc_adapter as rc_adapter_mod
    from services.comms_env_guard import CommsContext

    _reset_rate_limit("u1")

    captured: dict = {}

    async def _fake_rc_send(**kwargs):
        captured.update(kwargs)
        return {
            "provider": "ringcentral",
            "provider_status": "sent",
            "provider_response_id": "rc-123",
            "attempts": 1,
            "error": None,
            "redirected": True,
            "safe_send_context": "test",
            "intended_recipient_redacted": "+1***5555",
            "actual_recipient_redacted": "+1***9999",
        }

    monkeypatch.setattr(rc_adapter_mod, "send", _fake_rc_send)
    fake_db = MagicMock()
    fake_db.marketing_templates.find_one = AsyncMock(
        return_value=_fake_template("sms"),
    )
    monkeypatch.setattr(mt, "db", fake_db)

    body = mt.TemplateTestSendBody(to="+16025551234")
    result = _run(mt.test_send_template(
        tid="tpl-abc", body=body,
        user={"id": "u1", "role": "admin"},
        tenant={"id": "t1", "name": "Acme"},
    ))

    # Context propagation.
    assert captured.get("context") == CommsContext.TEST

    # Envelope surface — all six SAFE-SEND fields present.
    for key in (
        "redirected", "safe_send_context",
        "intended_recipient_redacted", "actual_recipient_redacted",
        "provider_status", "was_mock",
    ):
        assert key in result, f"safe-send field missing from SMS envelope: {key}"

    assert result["channel"] == "sms"
    assert result["redirected"] is True
    assert result["safe_send_context"] == "test"
    assert result["provider_status"] == "sent"
    assert result["was_mock"] is False
    assert result["ok"] is True


# ═══════════════════════════════════════════════════════════════════
# Non-privileged roles are still 403 — SAFE-SEND-C didn't loosen auth
# ═══════════════════════════════════════════════════════════════════
def test_test_send_rejects_non_admin_roles(monkeypatch):
    """Role guard preserved — only admin / super_admin / manager may
    call test-send.  Regression coverage: a refactor of the endpoint
    body must not accidentally lower the auth bar."""
    from fastapi import HTTPException
    from routers import marketing_templates as mt

    _reset_rate_limit("customer_id")

    body = mt.TemplateTestSendBody(to="customer@example.com")
    with pytest.raises(HTTPException) as ei:
        _run(mt.test_send_template(
            tid="tpl-abc", body=body,
            user={"id": "customer_id", "role": "customer"},
            tenant={"id": "t1", "name": "Acme"},
        ))
    assert ei.value.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# Adapter-level unit — CommsContext.TEST triggers redirect envelope
# ═══════════════════════════════════════════════════════════════════
def test_resend_adapter_test_context_returns_enriched_envelope(monkeypatch):
    """Direct unit on ``services.email.resend_adapter.send`` — with
    ``context=CommsContext.TEST`` and a resolvable tenant admin,
    the adapter should redirect + return the SAFE-SEND envelope
    fields.  Locks the SAFE-SEND-C adapter unification contract.
    """
    import services.email.resend_adapter as adapter_mod
    from services.comms_env_guard import CommsContext

    # 0. Neutralise env-guard leakage from sibling tests — force
    #    APP_ENV=production so guard_outbound doesn't dry-run the
    #    send BEFORE the mocked path returns its enriched envelope.
    monkeypatch.setenv("APP_ENV", "production")
    # 1. Force the adapter into disabled/mock mode so no HTTP fires.
    monkeypatch.setenv("RESEND_API_KEY", "")
    # Rebuild the singleton against the empty key so ``enabled=False``.
    adapter_mod._default = adapter_mod.ResendEmailAdapter()
    # 2. Stub the tenant lookup so redirect target resolves cleanly.
    fake_db = MagicMock()
    fake_db.tenants.find_one = AsyncMock(return_value={
        "settings": {"business_card": {"email": "admin@acme.com"}},
    })
    monkeypatch.setattr("config.db", fake_db, raising=False)
    # 3. Neutralise every downstream gate so we only exercise the
    #    SAFE-SEND branch + mocked return.
    monkeypatch.setattr(
        adapter_mod.ResendEmailAdapter, "_suppressed",
        AsyncMock(return_value=False),
    )
    fake_gate = MagicMock()
    fake_gate.is_comm_allowed = AsyncMock(return_value=True)
    monkeypatch.setitem(
        __import__("sys").modules, "services.comms.gate", fake_gate,
    )
    fake_byo = MagicMock()
    fake_byo.try_dispatch_email_tenant_byo = AsyncMock(return_value=None)
    monkeypatch.setitem(
        __import__("sys").modules, "services.messaging.byo_passthrough",
        fake_byo,
    )
    fake_tm = MagicMock()
    fake_tm.is_messaging_testmode = MagicMock(return_value=False)
    fake_tm.mock_email_envelope = MagicMock(return_value={})
    monkeypatch.setitem(
        __import__("sys").modules, "services.messaging.testmode", fake_tm,
    )

    result = _run(adapter_mod.send(
        to="customer@example.com",
        subject="Test",
        html="<p>hi</p>",
        category="transactional",
        tenant_id="t1",
        context=CommsContext.TEST,
    ))

    # Because RESEND_API_KEY is empty, the adapter returns the
    # ``mocked`` envelope — but the envelope MUST carry SAFE-SEND
    # fields showing the redirect DID happen.
    assert result["provider_status"] == "mocked"
    assert result["redirected"] is True
    assert result["safe_send_context"] == "test"
    assert result["intended_recipient_redacted"], (
        "intended_recipient_redacted must not be empty"
    )
    assert result["actual_recipient_redacted"], (
        "actual_recipient_redacted must not be empty"
    )


def test_rc_adapter_test_context_returns_enriched_envelope(monkeypatch):
    """Same contract as the resend unit above, but for RC SMS."""
    import services.sms.rc_adapter as adapter_mod
    from services.comms_env_guard import CommsContext

    # 0. Neutralise env-guard leakage from sibling tests — force
    #    APP_ENV=production so guard_outbound doesn't dry-run the
    #    send BEFORE the mocked path returns its enriched envelope.
    monkeypatch.setenv("APP_ENV", "production")
    # Force adapter into disabled/mock mode by clearing RC env.
    monkeypatch.delenv("RC_CLIENT_ID", raising=False)
    monkeypatch.delenv("RC_JWT", raising=False)
    monkeypatch.delenv("RC_SERVER_URL", raising=False)
    adapter_mod._default = adapter_mod.RingCentralSMSAdapter()
    # Tenant lookup returns a business_card with an admin phone.
    fake_db = MagicMock()
    fake_db.tenants.find_one = AsyncMock(return_value={
        "settings": {"business_card": {"phone": "+16029999999"}},
    })
    fake_db.sms_idempotency.find_one = AsyncMock(return_value=None)
    fake_db.sms_idempotency.create_index = AsyncMock(return_value=None)
    fake_db.sms_idempotency.update_one = AsyncMock(return_value=None)
    monkeypatch.setattr("config.db", fake_db, raising=False)
    # Neutralise downstream gates.
    monkeypatch.setattr(
        adapter_mod.RingCentralSMSAdapter, "_suppressed",
        AsyncMock(return_value=False),
    )
    fake_consent = MagicMock()
    fake_consent.has_sms_consent = AsyncMock(return_value=True)
    monkeypatch.setitem(
        __import__("sys").modules, "services.comms.consent_gate",
        fake_consent,
    )
    fake_gate = MagicMock()
    fake_gate.is_comm_allowed = AsyncMock(return_value=True)
    monkeypatch.setitem(
        __import__("sys").modules, "services.comms.gate", fake_gate,
    )
    fake_byo = MagicMock()
    fake_byo.try_dispatch_sms_tenant_byo = AsyncMock(return_value=None)
    monkeypatch.setitem(
        __import__("sys").modules, "services.messaging.byo_passthrough",
        fake_byo,
    )
    fake_tm = MagicMock()
    fake_tm.is_messaging_testmode = MagicMock(return_value=False)
    fake_tm.mock_sms_envelope = MagicMock(return_value={})
    monkeypatch.setitem(
        __import__("sys").modules, "services.messaging.testmode", fake_tm,
    )

    result = _run(adapter_mod.send(
        to="+16025551234",
        body="Test SMS",
        category="transactional",
        tenant_id="t1",
        context=CommsContext.TEST,
    ))
    assert result["provider_status"] == "mocked"
    assert result["redirected"] is True
    assert result["safe_send_context"] == "test"
    assert result["intended_recipient_redacted"]
    assert result["actual_recipient_redacted"]
