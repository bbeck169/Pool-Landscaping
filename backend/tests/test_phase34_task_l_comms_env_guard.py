"""Phase 34 · Task L · Feb-2026 — Comms env guard regression tests.

Pinned invariants (any regression = live send from preview, which is
what Task L is preventing):

1. In ``APP_ENV != production`` with an empty allow-list, calling
   ``resend_adapter.send()`` with a real-looking address returns
   ``{"provider_status": "dry_run"}`` and MUST NOT trigger the
   underlying ``resend.Emails.send`` SDK call.
2. Same for ``rc_adapter.send()``.
3. Adding the recipient to ``COMMS_TEST_ALLOWLIST_EMAILS`` /
   ``COMMS_TEST_ALLOWLIST_PHONES`` bypasses the guard.
4. ``APP_ENV=production`` unblocks all sends unconditionally.

The project uses plain sync tests + a small ``_run`` helper wrapping
``asyncio.run`` — mirroring ``test_phase7b_rc_sms_adapter.py``.
"""
from __future__ import annotations

import asyncio
import importlib
from typing import Any, Coroutine
from unittest.mock import patch


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.new_event_loop().run_until_complete(coro)


def _reset_env(monkeypatch, **overrides: str) -> None:
    for k in ("APP_ENV", "COMMS_TEST_ALLOWLIST_EMAILS",
              "COMMS_TEST_ALLOWLIST_PHONES", "RESEND_API_KEY",
              "RC_CLIENT_ID", "RC_JWT", "RC_SERVER_URL",
              "RC_SMS_DEFAULT_FROM"):
        monkeypatch.delenv(k, raising=False)
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)


# ══════════════════════════════════════════════════════════════════════
# 1 · Resend adapter — preview blocks
# ══════════════════════════════════════════════════════════════════════
def test_resend_dry_run_in_preview_with_empty_allowlist(monkeypatch):
    _reset_env(monkeypatch, APP_ENV="preview")
    resend_mod = importlib.reload(
        importlib.import_module("services.email.resend_adapter")
    )
    adapter = resend_mod.ResendEmailAdapter()

    # Sentinel: adapter.send should short-circuit BEFORE hitting the
    # SDK. If the guard fails, ``asyncio.to_thread`` would be called.
    with patch.object(resend_mod.asyncio, "to_thread",
                      side_effect=AssertionError(
                          "resend_adapter must NOT hit the SDK in dry-run")):
        resp = _run(adapter.send(
            to="stranger@example.com",
            subject="hello",
            html="<p>hi</p>",
            category="transactional",
        ))

    assert resp["provider_status"] == "dry_run", resp
    assert resp["dry_run"] is True
    assert resp["dry_run_to"] == "stranger@example.com"


def test_resend_allowlist_bypasses_guard(monkeypatch):
    _reset_env(
        monkeypatch,
        APP_ENV="preview",
        COMMS_TEST_ALLOWLIST_EMAILS="qa@example.com,other@example.com",
    )
    resend_mod = importlib.reload(
        importlib.import_module("services.email.resend_adapter")
    )
    adapter = resend_mod.ResendEmailAdapter()

    resp = _run(adapter.send(
        to="qa@example.com",
        subject="hi",
        html="<p>hi</p>",
        category="transactional",
    ))
    # Guard bypassed. No RESEND_API_KEY → adapter falls through to
    # its own ``mocked`` path (never hits the network in tests).
    assert resp["provider_status"] in ("mocked", "sent"), resp
    assert resp.get("dry_run") is not True


# ══════════════════════════════════════════════════════════════════════
# 2 · RingCentral SMS adapter — preview blocks
# ══════════════════════════════════════════════════════════════════════
def test_rc_sms_dry_run_in_preview_with_empty_allowlist(monkeypatch):
    _reset_env(monkeypatch, APP_ENV="preview")
    rc_mod = importlib.reload(
        importlib.import_module("services.sms.rc_adapter")
    )
    adapter = rc_mod.RingCentralSMSAdapter()

    with patch.object(rc_mod, "RingCentralService",
                      side_effect=AssertionError(
                          "rc_adapter must NOT hit RingCentralService in dry-run")):
        resp = _run(adapter.send(
            to="+15551234567",
            body="hello",
            category="transactional",
        ))

    assert resp["provider_status"] == "dry_run", resp
    assert resp["dry_run"] is True


def test_rc_sms_allowlist_bypasses_guard(monkeypatch):
    _reset_env(
        monkeypatch,
        APP_ENV="preview",
        COMMS_TEST_ALLOWLIST_PHONES="602-887-4400,555-123-4567",
    )
    rc_mod = importlib.reload(
        importlib.import_module("services.sms.rc_adapter")
    )
    adapter = rc_mod.RingCentralSMSAdapter()

    resp = _run(adapter.send(
        to="+16028874400",
        body="hi",
        category="transactional",
    ))
    # Guard bypassed. RC is not configured in test env → ``mocked``.
    assert resp["provider_status"] in ("mocked", "sent"), resp
    assert resp.get("dry_run") is not True


# ══════════════════════════════════════════════════════════════════════
# 3 · Env-guard primitives
# ══════════════════════════════════════════════════════════════════════
def test_guard_verdict_never_blocked_in_production(monkeypatch):
    _reset_env(monkeypatch, APP_ENV="production")
    guard_mod = importlib.reload(
        importlib.import_module("services.comms_env_guard")
    )
    e = guard_mod.guard_outbound(kind="email", to="anyone@example.com")
    s = guard_mod.guard_outbound(kind="sms", to="+15551234567")
    assert e.blocked is False and e.reason == "production_live"
    assert s.blocked is False and s.reason == "production_live"


def test_guard_verdict_blocked_in_preview_without_allowlist(monkeypatch):
    _reset_env(monkeypatch, APP_ENV="preview")
    guard_mod = importlib.reload(
        importlib.import_module("services.comms_env_guard")
    )
    e = guard_mod.guard_outbound(kind="email", to="stranger@example.com")
    s = guard_mod.guard_outbound(kind="sms", to="+15551234567")
    assert e.blocked is True
    assert s.blocked is True
    for verdict, provider in ((e, "resend"), (s, "ringcentral")):
        env = verdict.dry_run_response(provider=provider)
        assert env["provider"] == provider
        assert env["provider_status"] == "dry_run"
        assert env["provider_response_id"] is None
        assert env["attempts"] == 0
        assert env["dry_run"] is True
