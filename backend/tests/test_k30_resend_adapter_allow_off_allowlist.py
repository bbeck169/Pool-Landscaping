"""K30 · Feb-2026 — ``resend_adapter.send(allow_off_allowlist=True)``.

Validates the bypass flag added to the shared Resend adapter so
admin-triggered transactional sends (e.g. the K30
``/portal-reset-link`` endpoint) can leave preview environments
even when the recipient isn't on ``COMMS_TEST_ALLOWLIST_EMAILS``
and isn't flagged ``is_demo_account``.

We monkey-patch:
    * ``services.comms.gate.is_comm_allowed`` — proves the gate is
      NOT consulted when the flag is True.
    * ``services.comms_env_guard.guard_outbound`` — proves the
      env-allowlist gate is NOT consulted when the flag is True.
    * ``resend.Emails.send`` — captures the outgoing params so we
      can assert the payload was assembled correctly.

Also confirms the flag defaults to False (every other call-site
in the codebase gets the pre-K30 behaviour verbatim).
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

# Ensure preview-ish env so the guards would normally block.
os.environ.setdefault("APP_ENV", "preview")
os.environ.setdefault("COMMS_TEST_ALLOWLIST_EMAILS", "brian@plofv.com")
os.environ.setdefault("RESEND_API_KEY", "re_test_dummy")


_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


def _fresh_adapter():
    """Re-import so ``RESEND_API_KEY`` / allow-list env vars are read
    at construction time."""
    from services.email.resend_adapter import ResendEmailAdapter
    return ResendEmailAdapter()


class _CapturedSend:
    def __init__(self):
        self.calls = []

    def __call__(self, params):
        self.calls.append(params)
        return {"id": "test-message-id-0001"}


def test_bypass_flag_skips_both_gates(monkeypatch):
    """With ``allow_off_allowlist=True`` the send must reach the
    (monkey-patched) resend SDK even though the recipient is NOT
    a demo account AND is NOT on the env allow-list."""
    adapter = _fresh_adapter()

    # 1) is_comm_allowed would normally return False → assert it's
    # NEVER called when bypass is on.
    gate_called = {"count": 0}

    async def _fake_gate(**_kw):
        gate_called["count"] += 1
        return False

    monkeypatch.setattr(
        "services.comms.gate.is_comm_allowed", _fake_gate, raising=True,
    )

    # 2) guard_outbound would normally return blocked=True → assert
    # it's NEVER called when bypass is on.
    guard_called = {"count": 0}

    def _fake_guard(*, kind, to):  # noqa: ARG001
        guard_called["count"] += 1
        from services.comms_env_guard import GuardVerdict
        return GuardVerdict(
            blocked=True, reason="test_forced_block",
            to=to, kind=kind,
        )

    monkeypatch.setattr(
        "services.comms_env_guard.guard_outbound", _fake_guard, raising=True,
    )

    # 3) Capture the outgoing resend params.
    captured = _CapturedSend()
    import resend  # noqa: WPS433 — local import so tests own the module
    monkeypatch.setattr(resend.Emails, "send", captured, raising=True)

    result = asyncio.run(adapter.send(
        to="offlist@example.com",
        subject="K30 test",
        html="<p>hi</p>",
        category="transactional",
        allow_off_allowlist=True,
    ))

    assert result["provider_status"] == "sent"
    assert result["provider_response_id"] == "test-message-id-0001"
    assert gate_called["count"] == 0, "is_comm_allowed must be bypassed"
    assert guard_called["count"] == 0, "guard_outbound must be bypassed"
    assert len(captured.calls) == 1
    assert captured.calls[0]["to"] == ["offlist@example.com"]


def test_default_flag_still_enforces_guard(monkeypatch):
    """Regression guard — the default ``allow_off_allowlist=False``
    must preserve the pre-K30 behaviour: env-allowlist gate blocks
    off-list preview sends with a ``dry_run`` verdict."""
    adapter = _fresh_adapter()

    async def _fake_gate(**_kw):
        return True  # let the demo-account check pass

    monkeypatch.setattr(
        "services.comms.gate.is_comm_allowed", _fake_gate, raising=True,
    )

    # Real guard_outbound is fine — with APP_ENV=preview and the
    # recipient not on the allow-list, it should block.
    result = asyncio.run(adapter.send(
        to="notonlist@example.com",
        subject="Default flag",
        html="<p>should be blocked</p>",
        category="transactional",
    ))

    assert result["provider_status"] == "dry_run"
    assert result["dry_run"] is True


def test_default_flag_still_enforces_demo_gate(monkeypatch):
    """Default flag must also consult ``is_comm_allowed`` — an off-
    list demo-negative recipient is suppressed BEFORE the env guard
    even gets a chance to weigh in."""
    adapter = _fresh_adapter()

    async def _fake_gate(**_kw):
        return False  # not a demo account

    monkeypatch.setattr(
        "services.comms.gate.is_comm_allowed", _fake_gate, raising=True,
    )

    result = asyncio.run(adapter.send(
        to="offlist@example.com",
        subject="Default flag demo",
        html="<p>should be suppressed</p>",
        category="transactional",
    ))

    assert result["provider_status"] == "suppressed_not_demo"
