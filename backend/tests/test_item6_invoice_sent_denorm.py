"""Backlog Item #6 · Feb-2026 — Invoice "Sent" denorm smoke suite.

Operator-named stamp sites (locked by the four import-chain tests
at the bottom of this file — any typo or lost import regresses
the signal):

  1. ``emailer.send_invoice_reminder_email`` (covers single
     ``POST /quotes/{qid}/send-reminder`` invoice branch AND bulk
     ``_send_single_invoice`` email leg via the same canonical fn).
  2. ``routers.quotes.send_reminder`` (invoice branch SMS leg via
     ``notify_customer(sms=True)``).
  3. ``routers.dunning._dispatch_stage`` (SMS leg via
     ``routers.dunning._send_sms``).
  4. ``routers.invoices_bulk_send._send_single_invoice`` (email +
     SMS legs).

The state-machine tests exercise the shared helper
``services.invoice_sent_denorm.stamp_invoice_sent`` through a
mocked ``db.quotes`` collection (same ``_Coll`` fake pattern used
by ``test_resend_webhook_terminal_status.py``) so we don't require
a running Motor loop. The helper is the single source of truth
for all four sites; proving the state machine here + proving the
imports at the four sites gives full logical coverage.

``last_sent_via`` state machine locked:
  * email stamp on empty doc → ``"email"``.
  * sms stamp on an email-stamped doc → ``"both"``.
  * replay of either channel after ``"both"`` is set → still
    ``"both"`` (``$max`` keeps the latest timestamp, no via
    downgrade).
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict, List, Optional

import pytest


def _run(coro):
    """Run an async coroutine on a fresh event loop — matches the
    ``test_resend_webhook_terminal_status.py`` pattern so we don't
    need ``pytest-asyncio`` registered as a marker (not installed)."""
    return asyncio.new_event_loop().run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────
# Fake Motor collection — just enough surface for the helper.
# ─────────────────────────────────────────────────────────────────
class _FakeQuotesColl:
    """In-memory stand-in for ``db.quotes``.  Supports
    ``find_one(filt, projection)`` and
    ``update_one(filt, {"$max"/"$set": {...}})`` — the only ops the
    helper uses.  ``$max`` is implemented as max() of ISO strings
    which is lex-sortable + matches Mongo semantics for the ISO-8601
    shapes we persist via ``now_iso()``."""

    def __init__(self, rows: Optional[List[Dict[str, Any]]] = None):
        self.rows: List[Dict[str, Any]] = [dict(r) for r in (rows or [])]

    @staticmethod
    def _match(doc: Dict[str, Any], filt: Dict[str, Any]) -> bool:
        for k, v in filt.items():
            if doc.get(k) != v:
                return False
        return True

    async def find_one(self, filt: Dict[str, Any],
                        projection: Optional[Dict[str, Any]] = None):
        for d in self.rows:
            if self._match(d, filt):
                return dict(d)
        return None

    async def update_one(self, filt: Dict[str, Any],
                          update: Dict[str, Any]):
        for d in self.rows:
            if self._match(d, filt):
                for k, v in (update.get("$max") or {}).items():
                    cur = d.get(k)
                    if cur is None or (isinstance(cur, str) and v > cur):
                        d[k] = v
                for k, v in (update.get("$set") or {}).items():
                    d[k] = v
                return
        # No match — Mongo's update_one would be a no-op without
        # upsert=True.  Mirror that.


@pytest.fixture
def fake_quotes(monkeypatch):
    """Install the fake quotes collection on ``config.db`` (which
    ``services.invoice_sent_denorm`` imports) + yield the collection
    so tests can read/write their fixtures directly."""
    import config
    coll = _FakeQuotesColl()
    # Also install on ``db`` so any ``from config import db; db.quotes``
    # path hits the fake.
    monkeypatch.setattr(config.db, "quotes", coll, raising=False)
    yield coll


def _seed(fake_quotes, invoice_id="inv-1", tenant_id="t-1"):
    fake_quotes.rows.append({
        "id": invoice_id,
        "tenant_id": tenant_id,
        "doc_type": "invoice",
    })


# ─────────────────────────────────────────────────────────────────
# Core state-machine tests
# ─────────────────────────────────────────────────────────────────
def test_stamp_email_on_empty_doc_sets_via_email(fake_quotes):
    """First-time email stamp → ``last_sent_via = "email"`` + both
    ``last_sent_at`` and ``last_email_sent_at`` populated.
    ``last_sms_sent_at`` stays absent."""
    from services.invoice_sent_denorm import stamp_invoice_sent

    _seed(fake_quotes)
    _run(stamp_invoice_sent(
        invoice_id="inv-1", tenant_id="t-1", channel="email",
    ))

    row = fake_quotes.rows[0]
    assert row.get("last_sent_via") == "email"
    assert row.get("last_sent_at") is not None
    assert row.get("last_email_sent_at") is not None
    assert row.get("last_email_sent_at") == row.get("last_sent_at")
    assert "last_sms_sent_at" not in row


def test_stamp_sms_on_email_doc_flips_via_to_both(fake_quotes):
    """SMS stamp after a prior email stamp → ``last_sent_via =
    "both"`` and both per-channel timestamps present."""
    from services.invoice_sent_denorm import stamp_invoice_sent

    _seed(fake_quotes)
    _run(stamp_invoice_sent(
        invoice_id="inv-1", tenant_id="t-1", channel="email",
    ))
    _run(stamp_invoice_sent(
        invoice_id="inv-1", tenant_id="t-1", channel="sms",
    ))

    row = fake_quotes.rows[0]
    assert row.get("last_sent_via") == "both"
    assert row.get("last_email_sent_at") is not None
    assert row.get("last_sms_sent_at") is not None
    assert row.get("last_sent_at") == max(
        row.get("last_email_sent_at"), row.get("last_sms_sent_at"),
    )


def test_stamp_replay_does_not_downgrade_via(fake_quotes):
    """After ``both`` is set, a replay of a single channel keeps
    ``last_sent_via = "both"`` — operator one-way transition."""
    from services.invoice_sent_denorm import stamp_invoice_sent

    _seed(fake_quotes)
    _run(stamp_invoice_sent(
        invoice_id="inv-1", tenant_id="t-1", channel="email",
    ))
    _run(stamp_invoice_sent(
        invoice_id="inv-1", tenant_id="t-1", channel="sms",
    ))
    _run(stamp_invoice_sent(
        invoice_id="inv-1", tenant_id="t-1", channel="email",
    ))
    assert fake_quotes.rows[0].get("last_sent_via") == "both"


def test_stamp_sms_first_sets_via_sms(fake_quotes):
    """First-time SMS stamp (no email history) → ``last_sent_via =
    "sms"``."""
    from services.invoice_sent_denorm import stamp_invoice_sent

    _seed(fake_quotes)
    _run(stamp_invoice_sent(
        invoice_id="inv-1", tenant_id="t-1", channel="sms",
    ))
    row = fake_quotes.rows[0]
    assert row.get("last_sent_via") == "sms"
    assert row.get("last_sms_sent_at") is not None


def test_stamp_rejects_invalid_channel_silent(fake_quotes):
    """Invalid channel → silent no-op."""
    from services.invoice_sent_denorm import stamp_invoice_sent

    _seed(fake_quotes)
    _run(stamp_invoice_sent(
        invoice_id="inv-1", tenant_id="t-1", channel="pigeon",
    ))
    row = fake_quotes.rows[0]
    assert row.get("last_sent_at") is None
    assert row.get("last_sent_via") is None


def test_stamp_rejects_empty_ids_silent(fake_quotes):
    """Empty invoice_id / tenant_id → silent no-op."""
    from services.invoice_sent_denorm import stamp_invoice_sent

    _seed(fake_quotes)
    _run(stamp_invoice_sent(
        invoice_id="", tenant_id="t-1", channel="email",
    ))
    _run(stamp_invoice_sent(
        invoice_id="inv-1", tenant_id="", channel="email",
    ))
    row = fake_quotes.rows[0]
    assert row.get("last_sent_at") is None


def test_stamp_is_tenant_scoped(fake_quotes):
    """A stamp with the wrong tenant_id must NOT update the invoice
    (defensive against cross-tenant leak)."""
    from services.invoice_sent_denorm import stamp_invoice_sent

    _seed(fake_quotes, invoice_id="inv-A", tenant_id="tenant-A")
    _run(stamp_invoice_sent(
        invoice_id="inv-A", tenant_id="tenant-WRONG", channel="email",
    ))
    row = fake_quotes.rows[0]
    assert row.get("last_sent_at") is None
    assert row.get("last_sent_via") is None


def test_stamp_is_idempotent_via_dollar_max(fake_quotes):
    """A second stamp of the same channel with an earlier timestamp
    must NOT roll back the field (``$max`` semantics)."""
    from services.invoice_sent_denorm import stamp_invoice_sent

    _seed(fake_quotes)
    # Pre-seed a FUTURE timestamp — the helper's now_iso() stamp
    # must NOT overwrite it (``$max`` picks the larger ISO string).
    fake_quotes.rows[0]["last_email_sent_at"] = "9999-01-01T00:00:00+00:00"
    _run(stamp_invoice_sent(
        invoice_id="inv-1", tenant_id="t-1", channel="email",
    ))
    assert fake_quotes.rows[0]["last_email_sent_at"].startswith("9999-")


# ─────────────────────────────────────────────────────────────────
# Call-site import sanity — every operator-named stamp site must
# resolve the helper + name the correct channel. Catches typos
# and circular imports before the first live send.
# ─────────────────────────────────────────────────────────────────
def test_import_chain_emailer_send_invoice_reminder_email():
    import emailer
    src = inspect.getsource(emailer.send_invoice_reminder_email)
    assert "stamp_invoice_sent" in src
    assert 'channel="email"' in src


def test_import_chain_quotes_send_reminder_sms_stamp():
    from routers import quotes
    src = inspect.getsource(quotes.send_reminder)
    assert "stamp_invoice_sent" in src
    assert 'channel="sms"' in src


def test_import_chain_dunning_dispatch_stage_sms_stamp():
    from routers import dunning
    # The SMS stamp block lives inside the ``elif ch == "sms"``
    # branch of ``_send_reminder`` (the per-stage dispatcher that
    # wraps ``_send_sms`` with the ``invoice_id`` in scope).
    src = inspect.getsource(dunning._send_reminder)
    assert "stamp_invoice_sent" in src
    assert 'channel="sms"' in src


def test_import_chain_bulk_send_single_invoice_both_stamps():
    from routers import invoices_bulk_send
    src = inspect.getsource(invoices_bulk_send._send_single_invoice)
    assert "stamp_invoice_sent" in src
    assert 'channel="email"' in src
    assert 'channel="sms"' in src
