"""K9 Enhancement A · Feb-2026 — Silent-skip audit rows.

Pins the contract that when
``services.portal_chat_sms_bridge.notify_admin_of_customer_message``
short-circuits because either ``tenant.admin_sms_notify_to`` or
``tenant.rc_sms_from_number`` is unset, we now write a
``db.sms_thread_notifications`` row with ``skip_reason`` set so ops can
quantify how often portal messages are dropped silently.

Scope: NARROW.  Stubs the module-level ``db`` to avoid depending on the
live Mongo instance (keeps this suite fast and free of cross-file
event-loop collisions the way the K9 live-DB suite has).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeCollection:
    def __init__(self):
        self.docs: List[Dict[str, Any]] = []

    async def insert_one(self, doc):
        self.docs.append(doc)
        return {"inserted_id": doc.get("id")}

    async def find_one(self, *a, **kw):
        return None


class _FakeDB:
    def __init__(self):
        self.sms_thread_notifications = _FakeCollection()
        # ``portal_chat_notify_state`` is touched by the parent send
        # path but not by the two skip branches — stub it defensively.
        self.portal_chat_notify_state = _FakeCollection()
        self.audit_events = _FakeCollection()


def _seed(monkeypatch):
    from services import portal_chat_sms_bridge as bridge
    fake = _FakeDB()
    monkeypatch.setattr(bridge, "db", fake)
    return bridge, fake


def _chat_and_message(*, tenant_id: str = "t-k9-1",
                     thread_id: str = "chat-abc",
                     message_id: str = "msg-xyz"):
    return (
        {"id": thread_id, "tenant_id": tenant_id, "customer_id": "c-1"},
        {"id": message_id, "chat_id": thread_id, "sender_role": "customer",
         "body": "Hi, when will you come?", "sender_name": "Jane Doe"},
    )


# ═════════════════════════════════════════════════════════════════════
# 1. admin_sms_notify_to unset → audit row + status=skipped_no_admin_phone
# ═════════════════════════════════════════════════════════════════════
def test_skip_no_admin_phone_writes_audit_row(monkeypatch):
    bridge, fake = _seed(monkeypatch)
    chat, msg = _chat_and_message()
    tenant = {"id": "t-k9-1", "admin_sms_notify_to": None,
              "rc_sms_from_number": "+16025550111"}

    result = _run(bridge.notify_admin_of_customer_message(
        tenant=tenant, chat=chat, message=msg, customer_name="Jane Doe",
    ))
    assert result["status"] == "skipped_no_admin_phone"

    rows = fake.sms_thread_notifications.docs
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["tenant_id"] == "t-k9-1"
    assert row["thread_id"] == "chat-abc"
    assert row["message_id"] == "msg-xyz"
    # Enhancement A · Feb-2026 — distinguishing marker.
    assert row["skip_reason"] == "no_admin_phone"
    # Shape parity with the normal-send row (see K9 spec §5).
    assert row["throttled"] is False
    assert row["sent_provider_id"] is None
    # We didn't have an admin_phone to record; from_number IS
    # preserved for eventual inbound-fallback correlation.
    assert row["admin_phone"] == ""
    assert row["from_number"] == "+16025550111"


# ═════════════════════════════════════════════════════════════════════
# 2. rc_sms_from_number unset → audit row + status=skipped_no_from_number
# ═════════════════════════════════════════════════════════════════════
def test_skip_no_from_number_writes_audit_row(monkeypatch):
    bridge, fake = _seed(monkeypatch)
    chat, msg = _chat_and_message()
    tenant = {"id": "t-k9-1", "admin_sms_notify_to": "+16028874400",
              "rc_sms_from_number": None}

    result = _run(bridge.notify_admin_of_customer_message(
        tenant=tenant, chat=chat, message=msg, customer_name="Jane Doe",
    ))
    assert result["status"] == "skipped_no_from_number"

    rows = fake.sms_thread_notifications.docs
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["skip_reason"] == "no_from_number"
    assert row["throttled"] is False
    assert row["sent_provider_id"] is None
    # Admin phone IS known in this branch — preserved for later
    # inbound-fallback correlation.
    assert row["admin_phone"] == "+16028874400"
    assert row["from_number"] is None


# ═════════════════════════════════════════════════════════════════════
# 3. Both unset → the admin-phone branch fires FIRST (fail-fast).
# ═════════════════════════════════════════════════════════════════════
def test_skip_both_unset_reports_admin_phone_first(monkeypatch):
    bridge, fake = _seed(monkeypatch)
    chat, msg = _chat_and_message()
    tenant = {"id": "t-k9-1", "admin_sms_notify_to": None,
              "rc_sms_from_number": None}

    result = _run(bridge.notify_admin_of_customer_message(
        tenant=tenant, chat=chat, message=msg, customer_name="Jane Doe",
    ))
    assert result["status"] == "skipped_no_admin_phone"
    rows = fake.sms_thread_notifications.docs
    assert len(rows) == 1
    assert rows[0]["skip_reason"] == "no_admin_phone"


# ═════════════════════════════════════════════════════════════════════
# 4. skip_reason MUST BE ABSENT on non-skip paths (regression guard).
#    We can't easily exercise the send path w/o a full mongo stub, but
#    we CAN prove ``_record_notification`` omits the field when the
#    caller doesn't pass ``skip_reason``.  That's the invariant that
#    keeps existing K9 tests (which count rows without skip_reason)
#    green.
# ═════════════════════════════════════════════════════════════════════
def test_record_notification_omits_skip_reason_on_normal_path(monkeypatch):
    bridge, fake = _seed(monkeypatch)
    _run(bridge._record_notification(
        tenant_id="t-k9-1", thread_id="chat-abc",
        admin_phone="+16028874400", from_number="+16025550111",
        throttled=False, message_id="msg-xyz",
        sms_body="[Portal] Jane Doe: hi",
        sent_provider_id="rc-abc123",
    ))
    row = fake.sms_thread_notifications.docs[0]
    assert "skip_reason" not in row


# ═════════════════════════════════════════════════════════════════════
# 5. Audit-insert failure must NOT bubble — the function still returns
#    the ``skipped_*`` status so the router response stays predictable.
# ═════════════════════════════════════════════════════════════════════
def test_skip_audit_insert_failure_is_swallowed(monkeypatch):
    bridge, fake = _seed(monkeypatch)

    async def _boom(*a, **kw):
        raise RuntimeError("mongo down")

    fake.sms_thread_notifications.insert_one = _boom  # type: ignore
    chat, msg = _chat_and_message()
    tenant = {"id": "t-k9-1", "admin_sms_notify_to": None,
              "rc_sms_from_number": None}

    # No exception should propagate.
    result = _run(bridge.notify_admin_of_customer_message(
        tenant=tenant, chat=chat, message=msg, customer_name="Jane Doe",
    ))
    assert result["status"] == "skipped_no_admin_phone"
