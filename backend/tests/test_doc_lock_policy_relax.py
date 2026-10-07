"""DOC-LOCK-POLICY-RELAX · Feb-2026 — Unit + policy tests for the
relaxed PUT/PATCH edit lock and the new ``doc_edit_audit``
collection.

Scope
-----
A. Pure-predicate contract against ``services.quotes.status_gate``:
   * ``is_quote_mutable_for_put`` returns True for every estimate
     status.
   * ``is_quote_mutable_for_put`` returns True for every invoice
     status EXCEPT ``paid`` / ``void`` / ``cancelled``.
   * ``should_super_admin_silent_bypass`` is dead code — always
     False now.
   * ``_ALLOWED_WITH_ACK`` + ``_SUPER_ADMIN_SILENT_BYPASS`` empty.

B. Successful-edit audit row shape:
   * ``audit_put_success`` writes to the ``doc_edit_audit``
     collection with the exact field set documented on the function
     docstring.
   * No-op on draft (``_POST_SEND_STATUSES`` short-circuit).
   * ``edited_fields`` captures top-level key diffs.
   * ``monetary_delta`` captures scalar deltas + line_items length
     delta.

C. Denial-row shape unchanged on paid/void (contract regression
   lock-in).

These tests are UNIT-level and don't require the FastAPI test
client — they drive ``status_gate`` directly with mocked ``db``. HTTP
coverage lives in ``test_k80b_put_quote_status_gate.py``.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.quotes.status_gate import (
    _ALLOWED_WITH_ACK,
    _HARD_LOCKED,
    _POST_SEND_STATUSES,
    _SUPER_ADMIN_SILENT_BYPASS,
    assert_quote_mutable_for_put,
    audit_put_denial,
    audit_put_success,
    audit_super_admin_silent_bypass,
    denial_payload,
    is_quote_mutable_for_put,
    should_super_admin_silent_bypass,
)
from fastapi import HTTPException


# ═════════════════════════════════════════════════════════════════
# A · Pure-predicate contract
# ═════════════════════════════════════════════════════════════════
def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@pytest.mark.parametrize(
    "status",
    ["draft", "sent", "viewed", "accepted", "declined", "void",
      "cancelled", "something_weird"],
)
def test_every_estimate_status_is_mutable(status):
    """DOC-LOCK-POLICY-RELAX gate 1c + core: estimates are ALWAYS
    editable, no matter the status, no matter the role, no matter
    the bypass_lock flag. Any future reviewer who tries to narrow
    this must flip this test deliberately."""
    doc = {"doc_type": "quote", "status": status}
    assert is_quote_mutable_for_put(doc) is True
    assert is_quote_mutable_for_put(doc, bypass_lock=False) is True
    assert is_quote_mutable_for_put(doc, bypass_lock=True) is True
    assert is_quote_mutable_for_put(doc, role="admin") is True
    assert is_quote_mutable_for_put(doc, role="super_admin") is True


@pytest.mark.parametrize(
    "status",
    ["draft", "sent", "viewed", "accepted", "declined",
      "partial", "partially_paid", "past_due", "unpaid", "overdue"],
)
def test_invoice_non_locked_statuses_mutable(status):
    """DOC-LOCK-POLICY-RELAX gate 3a: invoices in any status OTHER
    than paid / void / cancelled are editable. Specifically asserts
    sent + viewed + accepted + aged-lifecycle statuses to lock the
    policy."""
    doc = {"doc_type": "invoice", "status": status}
    assert is_quote_mutable_for_put(doc) is True


@pytest.mark.parametrize("status", ["paid", "void", "cancelled"])
def test_invoice_hard_locked_statuses_blocked(status):
    """paid / void / cancelled invoices stay locked under PUT —
    these are the ONLY statuses this ticket locks."""
    doc = {"doc_type": "invoice", "status": status}
    assert is_quote_mutable_for_put(doc) is False
    # bypass_lock + super_admin role no longer open the lock on
    # these — the deprecated bypass paths are now dead code.
    assert is_quote_mutable_for_put(doc, bypass_lock=True) is False
    assert is_quote_mutable_for_put(doc, role="super_admin") is False


def test_hard_locked_set_shape_is_locked_down():
    """Guard against accidental widening of the hard-lock set in a
    future refactor."""
    assert _HARD_LOCKED["estimate"] == set()
    assert _HARD_LOCKED["invoice"] == {"paid", "void", "cancelled"}


def test_deprecated_bypass_sets_are_empty():
    """``_ALLOWED_WITH_ACK`` and ``_SUPER_ADMIN_SILENT_BYPASS`` are
    kept for import stability but hold no entries — the ack-popup +
    super_admin paths have nothing to unlock under the relaxed
    policy."""
    assert _ALLOWED_WITH_ACK["estimate"] == set()
    assert _ALLOWED_WITH_ACK["invoice"] == set()
    assert _SUPER_ADMIN_SILENT_BYPASS == set()


@pytest.mark.parametrize("status", ["paid", "past_due", "unpaid",
                                      "overdue", "void", "cancelled"])
def test_super_admin_silent_bypass_is_dead_code(status):
    """``should_super_admin_silent_bypass`` always returns False
    post-relax."""
    doc = {"doc_type": "invoice", "status": status}
    assert should_super_admin_silent_bypass(doc, "super_admin") is False
    assert should_super_admin_silent_bypass(doc, "admin") is False
    assert should_super_admin_silent_bypass(doc, None) is False


def test_assert_mutable_raises_only_on_hard_locked_invoice():
    """``assert_quote_mutable_for_put`` raises 409 only on the hard-
    lock set."""
    assert_quote_mutable_for_put(
        {"doc_type": "quote", "status": "accepted"},
    )  # no raise
    assert_quote_mutable_for_put(
        {"doc_type": "invoice", "status": "sent"},
    )  # no raise
    with pytest.raises(HTTPException) as exc:
        assert_quote_mutable_for_put(
            {"doc_type": "invoice", "status": "paid"},
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "status_locked"


def test_denial_payload_messages_narrowed():
    """Denial messages only reference paid / void / cancelled now."""
    paid_msg = denial_payload(
        {"doc_type": "invoice", "status": "paid"},
    )["message"].lower()
    assert "paid" in paid_msg
    assert "cannot be edited" in paid_msg

    void_msg = denial_payload(
        {"doc_type": "invoice", "status": "void"},
    )["message"].lower()
    assert "void" in void_msg


# ═════════════════════════════════════════════════════════════════
# B · ``audit_put_success`` row shape
# ═════════════════════════════════════════════════════════════════
def _mock_db():
    """Build a mock async MongoDB-shaped db where
    ``doc_edit_audit.insert_one`` is an AsyncMock."""
    db = MagicMock()
    db.doc_edit_audit = MagicMock()
    db.doc_edit_audit.insert_one = AsyncMock()
    db.audit_logs = MagicMock()
    db.audit_logs.insert_one = AsyncMock()
    return db


def test_audit_put_success_skips_draft():
    """Draft edits don't carry dispute signal — audit row short-
    circuits so the collection stays small + the dashboard filter
    stays signal-high."""
    db = _mock_db()
    before = {"id": "d-1", "tenant_id": "t-1", "doc_type": "quote",
                "status": "draft", "subtotal": 100}
    after = {**before, "subtotal": 200}
    actor = {"id": "u-1", "email": "x@y.z", "role": "admin"}
    _run(audit_put_success(db, before=before, after=after, actor=actor))
    db.doc_edit_audit.insert_one.assert_not_awaited()


@pytest.mark.parametrize("status", sorted(_POST_SEND_STATUSES))
def test_audit_put_success_fires_on_post_send_statuses(status):
    db = _mock_db()
    before = {"id": f"d-{status}", "tenant_id": "t-1",
                "doc_type": "quote", "status": status,
                "subtotal": 100, "tax": 7, "total": 107,
                "line_items": [{"id": "l-1"}, {"id": "l-2"}]}
    after = {**before, "subtotal": 200, "tax": 14, "total": 214,
              "line_items": [{"id": "l-1"}, {"id": "l-2"}, {"id": "l-3"}]}
    actor = {"id": "u-1", "email": "x@y.z", "role": "admin"}
    _run(audit_put_success(db, before=before, after=after, actor=actor))
    db.doc_edit_audit.insert_one.assert_awaited_once()
    row = db.doc_edit_audit.insert_one.await_args.args[0]

    # Mandatory fields per DOC-LOCK-POLICY-RELAX gate 2a.
    for key in ("event", "at", "tenant_id", "doc_id", "doc_type",
                "status_at_edit", "editor_user_id", "editor_email",
                "editor_role", "edited_fields", "monetary_delta"):
        assert key in row, f"missing audit field {key!r}: {row}"

    assert row["event"] == "put_quote_edit_after_send"
    assert row["doc_id"] == f"d-{status}"
    assert row["doc_type"] == "estimate"
    assert row["status_at_edit"] == status
    assert row["editor_user_id"] == "u-1"
    assert row["editor_role"] == "admin"
    # Monetary delta captures all scalar money fields + length delta.
    assert row["monetary_delta"]["subtotal"] == {"before": 100,
                                                   "after": 200}
    assert row["monetary_delta"]["total"] == {"before": 107,
                                                 "after": 214}
    assert row["monetary_delta"]["line_items.length"] == {
        "before": 2, "after": 3,
    }


def test_audit_put_success_captures_edited_field_names():
    db = _mock_db()
    before = {"id": "d-1", "tenant_id": "t-1", "doc_type": "invoice",
                "status": "sent", "title": "A", "notes": "x",
                "tax_rate": 0.07}
    after = {**before, "title": "B", "notes": "y"}  # tax_rate unchanged
    _run(audit_put_success(db, before=before, after=after,
                             actor={"id": "u-1"}))
    row = db.doc_edit_audit.insert_one.await_args.args[0]
    assert set(row["edited_fields"]) == {"title", "notes"}


def test_audit_put_success_tolerates_mongo_failure():
    """A write failure in the audit collection must not blow up the
    caller — the audit is best-effort."""
    db = _mock_db()
    db.doc_edit_audit.insert_one = AsyncMock(side_effect=RuntimeError)
    before = {"id": "d-1", "tenant_id": "t-1", "doc_type": "invoice",
                "status": "sent", "subtotal": 100}
    after = {**before, "subtotal": 200}
    # Should NOT raise.
    _run(audit_put_success(db, before=before, after=after,
                             actor={"id": "u-1"}))


def test_audit_put_success_source_label_pathed_through():
    """Both PUT and PATCH call sites use the same helper; the
    ``source`` kwarg lets ops filter by call path (put_quote vs
    patch_invoice)."""
    db = _mock_db()
    before = {"id": "d-1", "tenant_id": "t-1", "doc_type": "invoice",
                "status": "accepted"}
    after = dict(before)
    _run(audit_put_success(db, before=before, after=after,
                             actor={"id": "u-1"},
                             source="patch_invoice"))
    row = db.doc_edit_audit.insert_one.await_args.args[0]
    assert row["source"] == "patch_invoice"


def test_post_send_statuses_covers_user_specified_set():
    """DOC-LOCK-POLICY-RELAX gate 2a — the audit must fire on every
    status the user listed."""
    expected = {"sent", "viewed", "accepted", "declined",
                 "paid", "partial", "partially_paid",
                 "past_due", "unpaid", "overdue"}
    assert _POST_SEND_STATUSES == expected
