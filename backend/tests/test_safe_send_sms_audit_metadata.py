"""SAFE-SEND-A.1 · Feb-2026 — SMS audit-metadata parity.

Mirror of ``test_safe_send_audit_metadata.py`` for the SMS
channel.  Asserts that ``comms_sms_adapter.send_sms`` stamps
EVERY audit row with:

* ``intended_recipient_redacted`` — phone the caller passed
* ``recipient_redacted``          — phone the SMS actually went to
* ``context``                     — the ``CommsContext`` enum value
* ``redirected``                  — bool, True iff redirect fired

Covers every terminal branch:

* SYSTEM passthrough (mocked send)
* AGENT / TEST redirect (real business_card.phone)
* RingCentral failure (vendor error)
* ``RedirectTargetMissing`` skip (no admin phone available)
* Empty recipient
* Opt-out gate

Plus a phone-redaction sanity test — ``+15551234567`` must
become ``+1555***4567`` (leading country + area preserved,
trailing 4 preserved, middle starred).  Cross-check that
email redaction from A did not regress.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from services.comms_env_guard import CommsContext
from services.comms_send_log import _build_audit_row, _redact


# ═══════════════════════════════════════════════════════════════════
# _redact — phone-aware branch (added in A.1)
# ═══════════════════════════════════════════════════════════════════
def test_redact_e164_us_phone_keeps_country_area_and_tail():
    """``+15551234567`` (12 chars) → ``+1555`` + 3 stars + ``4567``."""
    assert _redact("+15551234567") == "+1555***4567"


def test_redact_e164_intl_phone_preserves_shape():
    """``+919876543210`` (13 chars) → ``+9198`` + 4 stars + ``3210``."""
    assert _redact("+919876543210") == "+9198****3210"


def test_redact_e164_keeps_prefix_and_never_leaks_middle():
    """Middle digits must be starred — no leaked substring
    from the middle of the number."""
    r = _redact("+14155551234")
    assert r is not None
    # No consecutive digit run > 4 from the middle (the tail is
    # allowed to be a 4-digit run, area code is separated by '+').
    assert "555" not in r.replace("+1415", "").replace("1234", "")


def test_redact_short_phone_falls_back_to_generic():
    """Non-E.164 (no '+') → generic tail-preserve, unchanged
    from pre-A.1 behaviour."""
    # ``5551234567`` (10 chars, no '+') → generic branch:
    # first 2 + stars + last 4 = ``55`` + ``****`` + ``4567``.
    assert _redact("5551234567") == "55****4567"


def test_redact_email_unchanged_by_a1_regression():
    """Pre-A.1 email redaction is BYTE-IDENTICAL.  Guard against
    accidental behaviour drift from the phone branch.

    Note: ``keep=2`` on the local-part means 1-char locals like
    ``a@b.co`` come back unstarred — that's the pre-A.1 shape
    and is preserved verbatim.
    """
    assert _redact("customer@example.com") == "cu******@example.com"
    assert _redact("ab@c.co") == "ab@c.co"  # local <= keep → no stars, pre-A.1 shape
    assert _redact("abc@d.co") == "ab*@d.co"  # keep 2 + 1 star
    assert _redact("") == ""
    assert _redact(None) is None


# ═══════════════════════════════════════════════════════════════════
# _build_audit_row — SMS row shape parity
# ═══════════════════════════════════════════════════════════════════
def _row(**overrides):
    base = dict(
        channel="sms",
        ok=True,
        now="2026-02-15T00:00:00+00:00",
        tenant_id="tenant-abc",
        recipient=None,
        template=None,
        provider="ringcentral",
        provider_status="sent",
        provider_response_id="rc-1",
        was_mock=False,
        error=None,
        exc_type=None,
        exc_trace=None,
        routed_via="platform_ringcentral",
        diagnostic=False,
        context=None,
        intended_recipient=None,
        redirected=False,
    )
    base.update(overrides)
    return _build_audit_row(**base)


def test_sms_audit_row_system_passthrough():
    row = _row(
        recipient="+15551234567",
        intended_recipient="+15551234567",
        context="system",
        redirected=False,
    )
    assert row["channel"] == "sms"
    assert row["context"] == "system"
    assert row["redirected"] is False
    # Both fields point at the same redacted number.
    assert row["intended_recipient_redacted"] == "+1555***4567"
    assert row["recipient_redacted"] == "+1555***4567"
    assert row["intended_recipient_redacted"] == row["recipient_redacted"]


def test_sms_audit_row_agent_redirect():
    row = _row(
        recipient="+16025557777",              # admin business_card
        intended_recipient="+15551234567",     # customer
        context="agent",
        redirected=True,
    )
    assert row["redirected"] is True
    assert row["context"] == "agent"
    assert row["intended_recipient_redacted"] == "+1555***4567"
    assert row["recipient_redacted"] == "+1602***7777"
    assert row["intended_recipient_redacted"] != row["recipient_redacted"]


def test_sms_audit_row_test_redirect():
    row = _row(
        recipient="+16025557777",
        intended_recipient="+15551234567",
        context="test",
        redirected=True,
    )
    assert row["context"] == "test"
    assert row["redirected"] is True


# ═══════════════════════════════════════════════════════════════════
# send_sms — integration through the full adapter.
# ═══════════════════════════════════════════════════════════════════
def _hermetic_sms_env(monkeypatch, *, sms_mock_mode: str = "1"):
    """Stub every gate downstream of the SAFE-SEND branch so this
    suite exercises only the audit + redirect + response envelope."""
    from services import comms_sms_adapter

    monkeypatch.setattr(
        "services.comms_sms_adapter._is_opted_out",
        AsyncMock(return_value=False),
    )
    # quiet-hours + testmode + BYO all pass-through / no-op.
    fake_qh = MagicMock()
    fake_qh.is_within_send_window = AsyncMock(return_value=True)
    fake_qh.defer_send = AsyncMock(return_value="deferred-id")
    fake_qh_ctx = MagicMock()
    fake_qh_ctx.is_bypassing = MagicMock(return_value=True)
    monkeypatch.setitem(
        __import__("sys").modules, "services.quiet_hours", fake_qh,
    )
    monkeypatch.setitem(
        __import__("sys").modules, "services.quiet_hours_context",
        fake_qh_ctx,
    )
    fake_byo = MagicMock()
    fake_byo.try_dispatch_sms_tenant_byo = AsyncMock(return_value=None)
    monkeypatch.setitem(
        __import__("sys").modules, "services.messaging.byo_passthrough",
        fake_byo,
    )
    fake_tm = MagicMock()
    fake_tm.is_messaging_testmode = MagicMock(return_value=False)
    monkeypatch.setitem(
        __import__("sys").modules, "services.messaging.testmode", fake_tm,
    )
    monkeypatch.setenv("SMS_MOCK_MODE", sms_mock_mode)

    _captured: list[dict] = []
    def _capture(_channel, **kwargs):
        _captured.append({"channel": _channel, **kwargs})
    monkeypatch.setattr(comms_sms_adapter, "record_attempt", _capture)
    return _captured, comms_sms_adapter


def test_send_sms_system_passthrough_audits_customer(monkeypatch):
    """SYSTEM SMS goes to the real customer, audit stamps
    ``context='system'``, ``redirected=False``, intended == actual."""
    captured, mod = _hermetic_sms_env(monkeypatch, sms_mock_mode="1")
    # tenants — never consulted for SYSTEM (redirect gate skips).
    fake_tenants = MagicMock()
    fake_tenants.find_one = AsyncMock(return_value=None)
    monkeypatch.setattr(mod, "db", MagicMock(tenants=fake_tenants))

    result = asyncio.run(mod.send_sms(
        tenant_id="tenant-acme",
        to_phone="+15551234567",
        body="Your pool tech arrives at 10:15am.",
        context=CommsContext.SYSTEM,
    ))
    assert result["status"] == "mocked"
    assert captured, "record_attempt should have fired for the mock"
    row = captured[-1]
    assert row["channel"] == "sms"
    assert row["context"] == "system"
    assert row["redirected"] is False
    assert row["intended_recipient"] == "+15551234567"
    assert row["recipient"] == "+15551234567"
    assert row["provider_status"] == "mocked"
    assert row["was_mock"] is True


def test_send_sms_agent_redirects_to_business_card_phone(monkeypatch):
    """AGENT redirects the send to ``business_card.phone`` and
    the audit stamps ``redirected=True`` with intended != actual."""
    captured, mod = _hermetic_sms_env(monkeypatch, sms_mock_mode="1")
    fake_tenants = MagicMock()
    fake_tenants.find_one = AsyncMock(return_value={
        "settings": {"business_card": {"phone": "+16025557777"}},
    })
    monkeypatch.setattr(mod, "db", MagicMock(tenants=fake_tenants))

    result = asyncio.run(mod.send_sms(
        tenant_id="tenant-acme",
        to_phone="+15551234567",              # customer would-be recipient
        body="AI-drafted reminder",
        context=CommsContext.AGENT,
    ))
    assert result["status"] == "mocked"
    row = captured[-1]
    assert row["context"] == "agent"
    assert row["redirected"] is True
    assert row["intended_recipient"] == "+15551234567"
    assert row["recipient"] == "+16025557777"
    # provider_status carries through — the mock path fires.
    assert row["provider_status"] == "mocked"


def test_send_sms_test_redirects_and_audits(monkeypatch):
    """TEST context has the same shape as AGENT."""
    captured, mod = _hermetic_sms_env(monkeypatch, sms_mock_mode="1")
    fake_tenants = MagicMock()
    fake_tenants.find_one = AsyncMock(return_value={
        "settings": {"business_card": {"phone": "+16025557777"}},
    })
    monkeypatch.setattr(mod, "db", MagicMock(tenants=fake_tenants))

    result = asyncio.run(mod.send_sms(
        tenant_id="tenant-acme",
        to_phone="+15551234567",
        body="Test message",
        context=CommsContext.TEST,
    ))
    assert result["status"] == "mocked"
    row = captured[-1]
    assert row["context"] == "test"
    assert row["redirected"] is True
    assert row["intended_recipient"] == "+15551234567"
    assert row["recipient"] == "+16025557777"


def test_send_sms_vendor_failure_preserves_all_safe_send_fields(monkeypatch):
    """RC HTTP failure → ``status=failed`` row still carries all
    4 SAFE-SEND fields.  Ops read this row to answer 'where did
    the failed send TRY to go?'."""
    captured, mod = _hermetic_sms_env(monkeypatch, sms_mock_mode="0")
    fake_tenants = MagicMock()
    fake_tenants.find_one = AsyncMock(return_value=None)
    monkeypatch.setattr(mod, "db", MagicMock(tenants=fake_tenants))
    # Fake ringcentral_client — outbound enabled, but SDK raises.
    fake_rc = MagicMock()
    fake_rc.is_outbound_enabled = AsyncMock(return_value=True)
    def _blowup():
        raise RuntimeError("RC send blew up")
    fake_platform = MagicMock()
    fake_platform.post = MagicMock(side_effect=RuntimeError("RC send blew up"))
    fake_rc.get_rc_platform = MagicMock(return_value=fake_platform)
    monkeypatch.setitem(
        __import__("sys").modules, "services.ringcentral_client", fake_rc,
    )

    result = asyncio.run(mod.send_sms(
        tenant_id="tenant-acme",
        to_phone="+15551234567",
        body="System notification",
        context=CommsContext.SYSTEM,
    ))
    assert result["status"] == "failed"
    row = captured[-1]
    assert row["ok"] is False
    assert row["provider_status"] == "failed"
    assert row["context"] == "system"
    assert row["intended_recipient"] == "+15551234567"
    assert row["recipient"] == "+15551234567"
    assert row["redirected"] is False


def test_send_sms_agent_missing_redirect_target_audits_skip(monkeypatch):
    """AGENT + no business_card.phone + no admin user → adapter
    returns ``skipped_no_redirect_target`` AND still writes an
    audit row with ``redirected=True``, ``recipient=None`` (no
    actual send), suppression marker on ``provider_status``."""
    captured, mod = _hermetic_sms_env(monkeypatch, sms_mock_mode="1")
    fake_users = MagicMock()
    fake_users.find_one = AsyncMock(return_value=None)
    fake_tenants = MagicMock()
    fake_tenants.find_one = AsyncMock(return_value={"settings": {}})
    monkeypatch.setattr(mod, "db", MagicMock(
        tenants=fake_tenants, users=fake_users,
    ))

    result = asyncio.run(mod.send_sms(
        tenant_id="tenant-acme",
        to_phone="+15551234567",
        body="AI-drafted note",
        context=CommsContext.AGENT,
    ))
    assert result["status"] == "skipped_no_redirect_target"
    assert result["safe_send_context"] == "agent"
    assert result["original_to"] == "+15551234567"
    assert captured, "audit row should still be written on skip"
    row = captured[-1]
    assert row["ok"] is False
    # Suppression marker — same string as the response envelope
    # so ops can filter both surfaces by the same key.
    assert row["provider_status"] == "skipped_no_redirect_target"
    assert row["context"] == "agent"
    assert row["redirected"] is True
    assert row["intended_recipient"] == "+15551234567"
    # recipient is None — the send never went anywhere.
    assert row["recipient"] is None


def test_send_sms_empty_recipient_audits_failure(monkeypatch):
    """Empty phone after redirect resolution → ``failed`` row
    with intended preserved."""
    captured, mod = _hermetic_sms_env(monkeypatch, sms_mock_mode="1")
    fake_tenants = MagicMock()
    fake_tenants.find_one = AsyncMock(return_value=None)
    monkeypatch.setattr(mod, "db", MagicMock(tenants=fake_tenants))

    result = asyncio.run(mod.send_sms(
        tenant_id="tenant-acme",
        to_phone="",  # ← empty
        body="body",
        context=CommsContext.SYSTEM,
    ))
    assert result["status"] == "failed"
    assert result["error"] == "empty recipient phone"
    row = captured[-1]
    assert row["ok"] is False
    assert row["provider_status"] == "failed_empty_recipient"
    assert row["context"] == "system"
    assert row["intended_recipient"] == ""
    assert row["redirected"] is False


def test_send_sms_opt_out_audits_skip(monkeypatch):
    """Recipient opted out of SMS → ``skipped_opted_out`` row
    with all SAFE-SEND fields preserved."""
    captured, mod = _hermetic_sms_env(monkeypatch, sms_mock_mode="1")
    monkeypatch.setattr(
        "services.comms_sms_adapter._is_opted_out",
        AsyncMock(return_value=True),
    )
    fake_tenants = MagicMock()
    fake_tenants.find_one = AsyncMock(return_value=None)
    monkeypatch.setattr(mod, "db", MagicMock(tenants=fake_tenants))

    result = asyncio.run(mod.send_sms(
        tenant_id="tenant-acme",
        to_phone="+15551234567",
        body="body",
        context=CommsContext.SYSTEM,
    ))
    assert result["status"] == "skipped_opted_out"
    row = captured[-1]
    assert row["provider_status"] == "skipped_opted_out"
    assert row["context"] == "system"
    assert row["intended_recipient"] == "+15551234567"
    assert row["recipient"] == "+15551234567"
    assert row["redirected"] is False
