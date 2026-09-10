"""Feb-2026 follow-up P1 · Resend webhook ledger-honesty split.

Locks in:
  * ``email.delivery_delayed`` is recognized by the webhook mapper
    and stamps ``provider_status="delivery_delayed"`` +
    ``delivery_delayed_at`` WITHOUT touching the terminal-status
    fields (the send may still deliver or bounce).
  * ``email.delivered`` sets BOTH ``terminal_delivered=True`` AND
    ``provider_terminal_status="delivered"`` — decoupling the
    frozen acceptance status from the terminal outcome.
  * ``email.bounced`` / ``email.complained`` set the terminal
    fields to the negative state.
  * ``email.opened`` / ``email.clicked`` leave the terminal-
    status fields untouched (engagement, not terminal).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Coll:
    def __init__(self, rows=None):
        self.rows: List[Dict[str, Any]] = list(rows or [])
        self.updates: List[Dict[str, Any]] = []
        self.inserts: List[Dict[str, Any]] = []

    async def find_one(self, filt=None, projection=None, *a, **kw):
        for r in self.rows:
            if all(r.get(k) == v for k, v in (filt or {}).items()):
                return dict(r)
        return None

    async def insert_one(self, doc):
        self.inserts.append(doc)
        self.rows.append(doc)
        return SimpleNamespace(inserted_id=doc.get("id"))

    async def update_one(self, filt, upd, *a, **kw):
        for r in self.rows:
            if all(r.get(k) == v for k, v in (filt or {}).items()):
                r.update(upd.get("$set") or {})
                self.updates.append({"filter": filt, "set": upd.get("$set")})
                return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)


class _DB:
    def __init__(self):
        self.marketing_deliveries = _Coll()
        self.marketing_suppressions = _Coll()
        self.resend_webhook_events = _Coll()


@pytest.fixture()
def fake_db(monkeypatch):
    fake = _DB()
    from routers import resend_webhooks as rw
    monkeypatch.setattr(rw, "db", fake)
    # Live env has a signing secret; unit-test path monkeypatches
    # the receiver to accept unsigned payloads so the tests can
    # exercise the mapping logic directly.
    monkeypatch.setattr(rw, "_verify_svix_signature",
                          lambda *a, **kw: True)
    import os as _os
    monkeypatch.setattr(_os, "environ", {**_os.environ,
                                              "RESEND_WEBHOOK_SECRET": "s"})
    return fake


def _seed_row(fake_db, email_id="resend_msg_1", tid="t-1", cid="c-1"):
    fake_db.marketing_deliveries.rows.append({
        "id": "d1", "tenant_id": tid, "customer_id": cid,
        "channel": "email", "recipient": "a@x",
        "delivered": True, "accepted_by_provider": True,
        "terminal_delivered": None,
        "provider_status": "sent",
        "provider_terminal_status": None,
        "provider_response_id": email_id,
    })


class _FakeReq:
    def __init__(self, payload):
        self._payload = payload

    async def body(self):
        import json
        return json.dumps(self._payload).encode()

    @property
    def headers(self):
        return {}


def _call(payload, fake_db):
    from routers.resend_webhooks import resend_webhook
    return _run(resend_webhook(_FakeReq(payload)))


# ═════════════════════════════════════════════════════════════════════
# 1. ``email.delivered`` flips both terminal fields.
# ═════════════════════════════════════════════════════════════════════
def test_email_delivered_flips_terminal_fields(fake_db):
    _seed_row(fake_db)
    _call({"type": "email.delivered",
             "data": {"email_id": "resend_msg_1", "to": ["a@x"]}}, fake_db)
    row = fake_db.marketing_deliveries.rows[0]
    assert row["terminal_delivered"] is True
    assert row["provider_terminal_status"] == "delivered"
    assert row["provider_status"] == "delivered"
    assert row["delivered_at"]


# ═════════════════════════════════════════════════════════════════════
# 2. ``email.bounced`` flips terminal to False.
# ═════════════════════════════════════════════════════════════════════
def test_email_bounced_flips_terminal_to_false(fake_db):
    _seed_row(fake_db)
    _call({"type": "email.bounced",
             "data": {"email_id": "resend_msg_1", "to": ["a@x"]}}, fake_db)
    row = fake_db.marketing_deliveries.rows[0]
    assert row["terminal_delivered"] is False
    assert row["provider_terminal_status"] == "bounced"
    assert row["provider_status"] == "bounced"
    assert row["bounced_at"]


def test_email_complained_flips_terminal_to_false(fake_db):
    _seed_row(fake_db)
    _call({"type": "email.complained",
             "data": {"email_id": "resend_msg_1", "to": ["a@x"]}}, fake_db)
    row = fake_db.marketing_deliveries.rows[0]
    assert row["terminal_delivered"] is False
    assert row["provider_terminal_status"] == "complained"


# ═════════════════════════════════════════════════════════════════════
# 3. ``email.delivery_delayed`` is recognized + retryable.
# ═════════════════════════════════════════════════════════════════════
def test_email_delivery_delayed_is_retryable_not_terminal(fake_db):
    _seed_row(fake_db)
    _call({"type": "email.delivery_delayed",
             "data": {"email_id": "resend_msg_1", "to": ["a@x"]}}, fake_db)
    row = fake_db.marketing_deliveries.rows[0]
    # Live cursor moves to ``delivery_delayed``.
    assert row["provider_status"] == "delivery_delayed"
    assert row.get("delivery_delayed_at")
    # Terminal fields UNTOUCHED — this state can transition to
    # ``delivered`` or ``bounced`` when Resend retries.
    assert row["terminal_delivered"] is None
    assert row["provider_terminal_status"] is None


# ═════════════════════════════════════════════════════════════════════
# 4. Engagement events (opened / clicked) do NOT touch terminal-status.
# ═════════════════════════════════════════════════════════════════════
def test_engagement_events_leave_terminal_fields_untouched(fake_db):
    _seed_row(fake_db)
    # Simulate a terminal delivery first.
    _call({"type": "email.delivered",
             "data": {"email_id": "resend_msg_1", "to": ["a@x"]}}, fake_db)
    _call({"type": "email.opened",
             "data": {"email_id": "resend_msg_1", "to": ["a@x"]}}, fake_db)
    _call({"type": "email.clicked",
             "data": {"email_id": "resend_msg_1", "to": ["a@x"]}}, fake_db)
    row = fake_db.marketing_deliveries.rows[0]
    # Terminal fields still reflect the initial ``delivered`` event —
    # engagement never overrides them.
    assert row["terminal_delivered"] is True
    assert row["provider_terminal_status"] == "delivered"
    # Live cursor reflects the most-recent event.
    assert row["provider_status"] == "clicked"


# ═════════════════════════════════════════════════════════════════════
# 5. Unknown email_id — no update, but no crash.
# ═════════════════════════════════════════════════════════════════════
def test_unknown_email_id_is_a_noop(fake_db):
    _seed_row(fake_db, email_id="resend_msg_1")
    _call({"type": "email.delivered",
             "data": {"email_id": "some-other-id", "to": ["a@x"]}}, fake_db)
    row = fake_db.marketing_deliveries.rows[0]
    assert row["terminal_delivered"] is None
    assert row["provider_terminal_status"] is None
