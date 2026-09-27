"""SAFE-SEND-A · Feb-2026 — audit-metadata preservation.

Asserts that ``comms_send_log._build_audit_row`` stamps EVERY row
with:

* ``intended_recipient_redacted`` — the address the caller passed
* ``recipient_redacted``          — the address the send actually
                                    went to (post-redirect)
* ``context``                     — the ``CommsContext`` value
* ``redirected``                  — bool, True iff intended != actual

Two flavours:

1. ``redirected=True``  — AGENT / TEST fired the safe-send redirect.
   The intended + actual fields differ.
2. ``redirected=False`` — SYSTEM passthrough.  intended == actual.

Both are load-bearing for the ops audit trail promised in the
SAFE-SEND-A spec.  Failing either means the audit row can't answer
"where did this send actually go, and where did the caller try to
send it?".
"""
from __future__ import annotations

from services.comms_send_log import _build_audit_row, _redact


def _row(**overrides):
    """Tiny factory — supplies the defaults every test case needs."""
    base = dict(
        channel="email",
        ok=True,
        now="2026-02-15T00:00:00+00:00",
        tenant_id="tenant-abc",
        recipient=None,
        template="job_completion",
        provider="resend",
        provider_status="sent",
        provider_response_id="prov-1",
        was_mock=False,
        error=None,
        exc_type=None,
        exc_trace=None,
        routed_via="platform_resend",
        diagnostic=False,
        context=None,
        intended_recipient=None,
        redirected=False,
    )
    base.update(overrides)
    return _build_audit_row(**base)


# ═══════════════════════════════════════════════════════════════════
# Passthrough case — SYSTEM never redirects.
# ═══════════════════════════════════════════════════════════════════
def test_audit_row_system_passthrough_marks_redirected_false():
    row = _row(
        recipient="customer@example.com",
        intended_recipient="customer@example.com",
        context="system",
        redirected=False,
    )
    assert row["redirected"] is False
    assert row["context"] == "system"
    # Redacted forms match — intended and actual are the same email.
    assert row["intended_recipient_redacted"] == _redact("customer@example.com")
    assert row["recipient_redacted"] == _redact("customer@example.com")
    assert row["intended_recipient_redacted"] == row["recipient_redacted"]


# ═══════════════════════════════════════════════════════════════════
# Redirect case — AGENT / TEST → admin.
# ═══════════════════════════════════════════════════════════════════
def test_audit_row_agent_redirect_marks_redirected_true_and_preserves_intended():
    row = _row(
        recipient="admin@acmepools.com",            # post-redirect
        intended_recipient="customer@example.com",  # what caller passed
        context="agent",
        redirected=True,
    )
    assert row["redirected"] is True
    assert row["context"] == "agent"
    # Redacted forms MUST differ — this is the audit line ops read.
    assert row["intended_recipient_redacted"] == _redact("customer@example.com")
    assert row["recipient_redacted"] == _redact("admin@acmepools.com")
    assert row["intended_recipient_redacted"] != row["recipient_redacted"]


def test_audit_row_test_redirect_marks_redirected_true_and_preserves_intended():
    row = _row(
        recipient="admin@acmepools.com",
        intended_recipient="customer@example.com",
        context="test",
        redirected=True,
    )
    assert row["redirected"] is True
    assert row["context"] == "test"
    assert row["intended_recipient_redacted"] == _redact("customer@example.com")
    assert row["recipient_redacted"] == _redact("admin@acmepools.com")


# ═══════════════════════════════════════════════════════════════════
# Every row carries the SAFE-SEND fields — even when caller forgets.
# ═══════════════════════════════════════════════════════════════════
def test_audit_row_fields_are_always_present():
    """No context / no intended_recipient — the fields still appear
    on the row as ``None`` / ``False``.  This is the contract with
    the diagnostic UI: it can always read ``row["context"]`` and
    ``row["redirected"]`` without ``KeyError``.
    """
    row = _row(recipient="user@example.com")
    assert "context" in row
    assert "intended_recipient_redacted" in row
    assert "redirected" in row
    assert row["context"] is None
    assert row["intended_recipient_redacted"] is None
    assert row["redirected"] is False


def test_audit_row_preserves_intended_on_failure_paths():
    """Failure paths (``ok=False``) still preserve SAFE-SEND fields.
    Ops need to see WHERE the failing send would have gone, not
    just the wall clock + error.
    """
    row = _row(
        ok=False,
        recipient="admin@acmepools.com",
        intended_recipient="customer@example.com",
        context="agent",
        redirected=True,
        provider_status="failed",
        error="resend timeout",
    )
    assert row["ok"] is False
    assert row["error"] == "resend timeout"
    assert row["redirected"] is True
    assert row["context"] == "agent"
    assert row["intended_recipient_redacted"] == _redact("customer@example.com")
    assert row["recipient_redacted"] == _redact("admin@acmepools.com")
