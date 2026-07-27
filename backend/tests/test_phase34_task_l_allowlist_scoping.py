"""Phase 34 · Task L (allow-list scoping) · Feb-2026.

Pinned invariants after the ``COMMS_TEST_ALLOWLIST_*`` env vars are
populated in preview to unblock ONLY Brian's live comms path:

- ``brian@plofv.com``           → guard NOT blocked
- ``+16028874400``              → guard NOT blocked
- Every OTHER destination       → guard BLOCKED (dry-run)
- Different casing / spacing    → still matched
- E.164 vs national formatting  → still matched (last-10-digits check)
"""
from __future__ import annotations

import importlib


def _reset_env(monkeypatch, **overrides: str) -> None:
    for k in ("APP_ENV", "COMMS_TEST_ALLOWLIST_EMAILS",
              "COMMS_TEST_ALLOWLIST_PHONES"):
        monkeypatch.delenv(k, raising=False)
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)


def _guard(monkeypatch):
    return importlib.reload(
        importlib.import_module("services.comms_env_guard")
    )


def test_only_brian_email_unblocked_in_preview(monkeypatch):
    _reset_env(monkeypatch,
                APP_ENV="preview",
                COMMS_TEST_ALLOWLIST_EMAILS="brian@plofv.com",
                COMMS_TEST_ALLOWLIST_PHONES="+16028874400")
    g = _guard(monkeypatch)

    # Brian: not blocked (allow-listed).
    v = g.guard_outbound(kind="email", to="brian@plofv.com")
    assert v.blocked is False
    assert "allowlist" in v.reason

    # Anyone else: blocked.
    for other in ("customer@example.com", "someone@plofv.com",
                  "brianbeckman@plofv.com", "BRIAN@example.com"):
        v = g.guard_outbound(kind="email", to=other)
        assert v.blocked is True, other
        assert "no_allowlist" in v.reason


def test_only_brian_phone_unblocked_in_preview(monkeypatch):
    _reset_env(monkeypatch,
                APP_ENV="preview",
                COMMS_TEST_ALLOWLIST_EMAILS="brian@plofv.com",
                COMMS_TEST_ALLOWLIST_PHONES="+16028874400")
    g = _guard(monkeypatch)

    # Brian's number, in every plausible format the codebase might pass.
    for fmt in ("+16028874400", "16028874400", "6028874400",
                 "602-887-4400", "(602) 887-4400"):
        v = g.guard_outbound(kind="sms", to=fmt)
        assert v.blocked is False, fmt

    # Other customer numbers: blocked.
    for other in ("+15551234567", "+16025551234", "5551234567"):
        v = g.guard_outbound(kind="sms", to=other)
        assert v.blocked is True, other


def test_case_and_whitespace_tolerance(monkeypatch):
    _reset_env(monkeypatch,
                APP_ENV="preview",
                COMMS_TEST_ALLOWLIST_EMAILS=" Brian@PLOFV.com ,  qa@example.com  ",
                COMMS_TEST_ALLOWLIST_PHONES="  602-887-4400  ")
    g = _guard(monkeypatch)

    assert g.guard_outbound(kind="email", to="brian@plofv.com").blocked is False
    assert g.guard_outbound(kind="email", to="BRIAN@plofv.com").blocked is False
    assert g.guard_outbound(kind="email", to="qa@example.com").blocked is False
    assert g.guard_outbound(kind="email", to="stranger@x.com").blocked is True

    assert g.guard_outbound(kind="sms", to="+16028874400").blocked is False


def test_production_ignores_allowlist(monkeypatch):
    """When APP_ENV=production the guard NEVER blocks — allow-list
    contents are irrelevant."""
    _reset_env(monkeypatch,
                APP_ENV="production",
                COMMS_TEST_ALLOWLIST_EMAILS="",  # empty
                COMMS_TEST_ALLOWLIST_PHONES="")
    g = _guard(monkeypatch)

    for addr in ("stranger@example.com", "someone-else@plofv.com"):
        v = g.guard_outbound(kind="email", to=addr)
        assert v.blocked is False and v.reason == "production_live"
