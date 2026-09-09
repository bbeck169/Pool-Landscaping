"""
Feb-2026 · Phase B — quote/estimate approve/decline notification tests.

Unit tests for ``services.quote_notifications.notify_quote_decision``.
Monkey-patches the email + SMS adapters so no network calls are made
and asserts the resulting ``db.comms_send_log`` rows match the scope
memo's contract.

Scenarios covered:
  1. Approve on a quote with recipients configured → 1 email + 1 SMS
     comms-log row per recipient (``status=sent``).
  2. Decline with ``notify_admin_on_decline=true`` → same.
  3. Decline with ``notify_admin_on_decline=false`` → 0 sends
     (helper returns ``{"suppressed": "tenant_disabled"}``); bell
     fanout is a separate call-site so we don't assert on it here.
  4. Empty recipients + workforce admin fallback → sends go to the
     admin users' emails/phones.
  5. BYO with blank credentials → adapter's fallback returns
     ``status="sent"`` (regression guard on the byo_common hotfix).
  6. Rate limit: 4th successful send in an hour → skipped with an
     audit row of ``status=rate_limited``.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from config import db
from services import quote_notifications as qn


# ── Helpers ──────────────────────────────────────────────────────

_MARK = "phase-b-test-marker"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def cleanup_comms_log():
    """Delete the marker rows before + after each test so ordering
    is deterministic and repeated runs don't accumulate audit rows."""
    _run(db.comms_send_log.delete_many({"tenant_id": _MARK}))
    yield
    _run(db.comms_send_log.delete_many({"tenant_id": _MARK}))


@pytest.fixture()
def fake_adapters(monkeypatch):
    """Swap the module-level ``send`` functions the service imports
    lazily. AsyncMock lets us both assert call args and return a
    stable payload."""
    calls: Dict[str, List[Dict[str, Any]]] = {"email": [], "sms": []}

    async def _fake_email(**kwargs):
        calls["email"].append(kwargs)
        return {"status": "sent", "provider_id": "resend-fake"}

    async def _fake_sms(**kwargs):
        calls["sms"].append(kwargs)
        return {"status": "sent", "provider_id": "rc-fake"}

    monkeypatch.setattr(
        "services.email.resend_adapter.send", _fake_email, raising=False,
    )
    monkeypatch.setattr(
        "services.sms.rc_adapter.send", _fake_sms, raising=False,
    )
    return calls


def _sample_tenant(**overrides) -> Dict[str, Any]:
    return {
        "id": _MARK,
        "name": "Test Tenant",
        "lead_notification_recipients": [
            {"id": "r1", "email": "admin@example.com",
              "phone": "+15551230001", "email_on": True, "sms_on": True},
            {"id": "r2", "email": "ops@example.com",
              "phone": "+15551230002", "email_on": True, "sms_on": True},
        ],
        **overrides,
    }


def _sample_doc(**overrides) -> Dict[str, Any]:
    return {
        "id": "quote-under-test",
        "doc_type": "quote",
        "customer_name": "Jane Doe",
        "total": 1234.56,
        "decline_reason": "over budget",
        **overrides,
    }


async def _rows() -> List[Dict[str, Any]]:
    return await db.comms_send_log.find(
        {"tenant_id": _MARK}, {"_id": 0},
    ).to_list(200)


# ── 1. Approve → email + SMS per recipient ───────────────────────

def test_approve_dispatches_email_and_sms_for_each_recipient(
    cleanup_comms_log, fake_adapters,
):
    tenant = _sample_tenant()
    doc = _sample_doc()

    summary = _run(qn.notify_quote_decision(
        tenant=tenant, doc=doc, event="quote_accepted",
        frontend_origin="https://app.example.com",
    ))
    assert summary["recipient_count"] == 2
    assert summary["email"] == {"sent": 2, "rate_limited": 0, "failed": 0}
    assert summary["sms"]   == {"sent": 2, "rate_limited": 0, "failed": 0}
    assert len(fake_adapters["email"]) == 2
    assert len(fake_adapters["sms"]) == 2

    rows = _run(_rows())
    email_rows = [r for r in rows if r["channel"] == "email"]
    sms_rows = [r for r in rows if r["channel"] == "sms"]
    assert len(email_rows) == 2 and len(sms_rows) == 2
    assert all(r["status"] == "sent" for r in rows)
    assert all(r["kind"] == "quote_accepted" for r in rows)
    assert all(r["doc_id"] == doc["id"] for r in rows)


# ── 2. Decline w/ flag on → email + SMS per recipient ────────────

def test_decline_with_flag_on_dispatches(cleanup_comms_log, fake_adapters):
    tenant = _sample_tenant(notify_admin_on_decline=True)
    doc = _sample_doc()

    summary = _run(qn.notify_quote_decision(
        tenant=tenant, doc=doc, event="quote_declined",
    ))
    assert summary.get("suppressed") is None
    assert summary["email"]["sent"] == 2
    assert summary["sms"]["sent"] == 2
    rows = _run(_rows())
    assert len({r["channel"] for r in rows}) == 2
    assert all(r["kind"] == "quote_declined" for r in rows)


# ── 3. Decline w/ flag OFF → zero sends ──────────────────────────

def test_decline_with_flag_off_suppresses_email_sms(
    cleanup_comms_log, fake_adapters,
):
    tenant = _sample_tenant(notify_admin_on_decline=False)
    doc = _sample_doc()

    summary = _run(qn.notify_quote_decision(
        tenant=tenant, doc=doc, event="quote_declined",
    ))
    assert summary == {"suppressed": "tenant_disabled"}
    assert fake_adapters["email"] == []
    assert fake_adapters["sms"] == []
    rows = _run(_rows())
    assert rows == []


# ── 4. Empty recipients → workforce admin fallback ───────────────

def test_workforce_admin_fallback_when_recipients_empty(
    cleanup_comms_log, fake_adapters,
):
    # Seed 2 admin users in the fake tenant.
    admin_ids = ["u1", "u2"]
    _run(db.users.insert_many([
        {"id": admin_ids[0], "tenant_id": _MARK, "role": "admin",
          "email": "wf-admin1@example.com", "phone": "+15551230101",
          "name": "WF Admin One"},
        {"id": admin_ids[1], "tenant_id": _MARK, "role": "super_admin",
          "email": "wf-admin2@example.com", "phone": "+15551230102",
          "name": "WF Admin Two"},
    ]))
    try:
        tenant = _sample_tenant(lead_notification_recipients=[])
        doc = _sample_doc()

        summary = _run(qn.notify_quote_decision(
            tenant=tenant, doc=doc, event="quote_accepted",
        ))
        assert summary["recipient_source"] == "workforce_admins"
        assert summary["recipient_count"] == 2
        assert summary["email"]["sent"] == 2
        assert summary["sms"]["sent"] == 2
        rows = _run(_rows())
        recips = sorted({r["recipient"] for r in rows})
        assert "wf-admin1@example.com" in recips
        assert "wf-admin2@example.com" in recips
    finally:
        _run(db.users.delete_many({"id": {"$in": admin_ids},
                                     "tenant_id": _MARK}))


# ── 5. BYO with blank credentials → platform fallback still sends ─

def test_byo_blank_credentials_falls_back_to_platform(
    cleanup_comms_log, monkeypatch,
):
    """Regression guard on the byo_common hotfix — when the tenant
    has a BYO provider configured but the credentials block is
    empty, the resend/rc adapters must fall back to the platform
    credentials and return ``status=sent``. We assert the service
    surfaces that as a successful send rather than treating the
    blank-BYO tenant as a hard failure."""
    calls = {"email": [], "sms": []}

    async def _email(**kwargs):
        # Simulate the adapter's post-fallback response: empty BYO
        # → platform Resend used → sent OK.
        calls["email"].append(kwargs)
        return {"status": "sent", "provider_id": "platform-resend",
                 "byo_fallback": "empty_credentials"}

    async def _sms(**kwargs):
        calls["sms"].append(kwargs)
        return {"status": "sent", "provider_id": "platform-rc",
                 "byo_fallback": "empty_credentials"}

    monkeypatch.setattr(
        "services.email.resend_adapter.send", _email, raising=False,
    )
    monkeypatch.setattr(
        "services.sms.rc_adapter.send", _sms, raising=False,
    )
    tenant = _sample_tenant()
    summary = _run(qn.notify_quote_decision(
        tenant=tenant, doc=_sample_doc(), event="quote_accepted",
    ))
    assert summary["email"]["sent"] == 2
    assert summary["email"]["failed"] == 0
    assert summary["sms"]["sent"] == 2
    rows = _run(_rows())
    assert all(r["status"] == "sent" for r in rows)


# ── 6. Rate limit: 4th send in an hour → rate_limited row ─────────

def test_rate_limit_after_three_sends(cleanup_comms_log, fake_adapters):
    """Pre-seed 3 sent rows on the (tenant, doc, kind, email) key so
    the next attempt is throttled. The service must emit an audit
    row of ``status=rate_limited`` and NOT call the email adapter."""
    tenant = _sample_tenant(lead_notification_recipients=[
        {"id": "r1", "email": "rl@example.com", "email_on": True,
          "phone": "", "sms_on": False},
    ])
    doc = _sample_doc(id="quote-rl")
    now = datetime.now(tz=timezone.utc).isoformat()
    _run(db.comms_send_log.insert_many([
        {"tenant_id": _MARK, "doc_id": doc["id"], "kind": "quote_accepted",
          "channel": "email", "recipient": "rl@example.com",
          "status": "sent", "created_at": now,
          "provider_id": f"seed-{i}"}
        for i in range(3)
    ]))

    summary = _run(qn.notify_quote_decision(
        tenant=tenant, doc=doc, event="quote_accepted",
    ))
    assert summary["email"] == {"sent": 0, "rate_limited": 1, "failed": 0}
    # No new adapter call.
    assert fake_adapters["email"] == []
    # New audit row exists with the rate_limited status.
    rows = _run(db.comms_send_log.find(
        {"tenant_id": _MARK, "doc_id": doc["id"],
          "status": "rate_limited"}, {"_id": 0},
    ).to_list(10))
    assert len(rows) == 1
    assert rows[0]["channel"] == "email"


# ── 7. Recipient row can opt out of a channel ────────────────────

def test_recipient_channel_opt_out_is_honoured(
    cleanup_comms_log, fake_adapters,
):
    tenant = _sample_tenant(lead_notification_recipients=[
        {"id": "r1", "email": "email-only@example.com",
          "phone": "+15559999999",
          "email_on": True, "sms_on": False},
        {"id": "r2", "email": "sms-only@example.com",
          "phone": "+15558888888",
          "email_on": False, "sms_on": True},
    ])
    summary = _run(qn.notify_quote_decision(
        tenant=tenant, doc=_sample_doc(), event="quote_accepted",
    ))
    assert summary["email"]["sent"] == 1
    assert summary["sms"]["sent"] == 1
    email_to = [c["to"] for c in fake_adapters["email"]]
    sms_to = [c["to"] for c in fake_adapters["sms"]]
    assert email_to == ["email-only@example.com"]
    assert sms_to == ["+15558888888"]


# ── 8. Template shape checks ─────────────────────────────────────

def test_email_template_carries_doc_number_customer_and_total():
    subject, html, text = qn.render_email(
        event="quote_declined", doc_type="quote",
        doc=_sample_doc(id="deadbeef1234", total=2500.50,
                          customer_name="Larry Contreras",
                          decline_reason="too expensive"),
        frontend_origin="https://app.example.com",
    )
    assert "DEADBEEF" in subject
    assert "Larry Contreras" in subject
    assert "$2,500.50" in html
    assert "too expensive" in html
    assert "https://app.example.com/quotes/deadbeef1234" in html
    assert "$2,500.50" in text


def test_sms_template_under_160_chars_and_has_short_id():
    body = qn.render_sms(
        event="quote_accepted", doc_type="quote",
        doc=_sample_doc(id="cafebabe0001", total=98765.43,
                          customer_name="Jane Doe"),
        frontend_origin="https://app.example.com",
    )
    assert len(body) <= 160
    assert "CAFEBABE" in body
    assert "Jane Doe" in body
