"""MTH-C · Feb-2026 — Escalation integration tests.

Locks:
  * Inbound customer message triggers ``scan_and_escalate``,
    which persists a row + notifies the target-role admins.
  * SLA breach scanner fires the follow-up notification once
    (idempotent).
  * Notify channel respected (email / sms / both).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.ai_hub.escalation_detector import (
    scan_and_escalate, scan_sla_breaches, COLLECTION,
)
from tests._mth_c_helpers import mth_c_db, seed_rules_doc, run  # noqa: F401


_UTC = timezone.utc


def _rules_with_escalation(rule):
    return {
        "tone_voice": {"style": "friendly", "custom_directive": ""},
        "employee_enable_disable": {},
        "working_hours": {"enabled": False, "timezone": "UTC", "windows": []},
        "auto_action_allowlist": {},
        "escalation_rules": [rule],
    }


def _seed_admin(fake, tenant_id, *, email="admin@t1", phone="+15551110000"):
    fake.users.rows.append({
        "id": "u-admin", "tenant_id": tenant_id, "role": "admin",
        "email": email, "phone_number": phone, "name": "Ops",
    })


def test_inbound_sms_with_refund_keyword_creates_escalation(
    mth_c_db, monkeypatch,
):
    rule = {"keyword": "refund", "is_regex": False,
             "target_role": "admin", "sla_minutes": 5,
             "notify_channel": "email"}
    seed_rules_doc(
        mth_c_db, "t1", _rules_with_escalation(rule), master=True,
    )
    _seed_admin(mth_c_db, "t1")
    sent = []

    async def _fake_send_email(**kw):
        sent.append(kw)

    import services.comms_email_adapter as _cea
    monkeypatch.setattr(_cea, "send_email", _fake_send_email,
                          raising=False)
    row = run(scan_and_escalate(
        tenant_id="t1", source="sms",
        message_body="I want a refund NOW",
        customer_id="c1",
    ))
    assert row is not None
    assert row["notified"] is True
    assert len(sent) == 1
    persisted = mth_c_db[COLLECTION].rows
    assert len(persisted) == 1
    assert persisted[0]["source"] == "sms"


def test_channel_both_sends_email_plus_sms(mth_c_db, monkeypatch):
    rule = {"keyword": "urgent", "is_regex": False,
             "target_role": "admin", "sla_minutes": 5,
             "notify_channel": "both"}
    seed_rules_doc(mth_c_db, "t1", _rules_with_escalation(rule), master=True)
    _seed_admin(mth_c_db, "t1")
    emails, texts = [], []

    async def _fake_send_email(**kw):
        emails.append(kw)

    async def _fake_send_sms(**kw):
        texts.append(kw)

    import services.comms_email_adapter as _cea
    import services.comms_sms_adapter as _csa
    monkeypatch.setattr(_cea, "send_email", _fake_send_email,
                          raising=False)
    monkeypatch.setattr(_csa, "send_sms", _fake_send_sms,
                          raising=False)
    run(scan_and_escalate(
        tenant_id="t1", source="sms",
        message_body="urgent — pool leak overnight",
    ))
    assert len(emails) == 1
    assert len(texts) == 1


def test_no_match_returns_none_without_persisting(mth_c_db):
    rule = {"keyword": "refund", "is_regex": False,
             "target_role": "admin", "sla_minutes": 5,
             "notify_channel": "email"}
    seed_rules_doc(mth_c_db, "t1", _rules_with_escalation(rule), master=True)
    out = run(scan_and_escalate(
        tenant_id="t1", source="sms",
        message_body="hello and thanks",
    ))
    assert out is None
    assert mth_c_db[COLLECTION].rows == []


def test_sla_breach_scanner_fires_once(mth_c_db, monkeypatch):
    _seed_admin(mth_c_db, "t1")
    past_ts = (datetime.now(_UTC) - timedelta(minutes=10)).timestamp()
    mth_c_db[COLLECTION].rows.append({
        "id": "esc-1", "tenant_id": "t1",
        "source": "sms", "customer_id": None, "lead_id": None,
        "message_body": "help",
        "matched_rule": {"keyword": "help", "is_regex": False,
                          "target_role": "admin",
                          "sla_minutes": 1,
                          "notify_channel": "email"},
        "escalated_at": "2026-02-02T09:00:00+00:00",
        "sla_deadline": "2026-02-02T09:01:00+00:00",
        "sla_deadline_ts": past_ts,
        "notified": True, "notified_at": "2026-02-02T09:00:01+00:00",
        "notify_error": None,
        "breach_notified": False, "breach_notified_at": None,
        "resolved": False, "resolved_by": None, "resolved_at": None,
    })
    sent = []

    async def _fake_send_email(**kw):
        sent.append(kw)

    import services.comms_email_adapter as _cea
    monkeypatch.setattr(_cea, "send_email", _fake_send_email,
                          raising=False)
    stats = run(scan_sla_breaches())
    assert stats["breached"] == 1
    assert len(sent) == 1
    # Idempotent — second run does NOT re-notify.
    sent.clear()
    stats2 = run(scan_sla_breaches())
    assert stats2["breached"] == 0
    assert sent == []


def test_scan_and_escalate_missing_scope_returns_none(mth_c_db):
    assert run(scan_and_escalate(
        tenant_id="", source="sms", message_body="x",
    )) is None
    assert run(scan_and_escalate(
        tenant_id="t1", source="sms", message_body="",
    )) is None
