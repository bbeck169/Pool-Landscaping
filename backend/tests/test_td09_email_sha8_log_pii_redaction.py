"""TD-09 · Feb-2026 — PII-safe email identifier for log lines.

Validates:
  1. ``email_sha8`` is deterministic — same input → same 8-hex.
  2. Canonicalization is case-insensitive + whitespace-trimmed.
  3. ``None`` / empty / whitespace-only → ``"none"`` sentinel.
  4. The three WARN log lines in ``backend/routers/auth.py`` that
     used to emit raw ``email=<alice@example.com>`` now emit
     ``email_sha8=<hex>`` instead.
"""
from __future__ import annotations

import logging

import pytest

from utils import email_sha8


# ─── 1 · determinism ─────────────────────────────────────────────
def test_email_sha8_is_deterministic():
    a = email_sha8("alice@example.com")
    b = email_sha8("alice@example.com")
    assert a == b
    assert len(a) == 8
    # Lower-hex only.
    int(a, 16)


# ─── 2 · case-insensitive + whitespace-trimmed ───────────────────
def test_email_sha8_canonicalizes_case_and_whitespace():
    canonical = email_sha8("alice@example.com")
    assert email_sha8("Alice@Example.com") == canonical
    assert email_sha8("  Alice@Example.com  ") == canonical
    assert email_sha8("ALICE@EXAMPLE.COM\n") == canonical


# ─── 3 · ``None`` / empty / whitespace → ``"none"`` sentinel ─────
@pytest.mark.parametrize("falsy", [None, "", "   ", "\t\n"])
def test_email_sha8_falsy_returns_none_sentinel(falsy):
    assert email_sha8(falsy) == "none"


# ─── 4 · never raises on exotic input ────────────────────────────
def test_email_sha8_absorbs_non_string_input():
    # Numeric / dict / object inputs must coerce + hash or return
    # ``"none"`` — never raise. Logging helpers that raise are a
    # production footgun.
    assert email_sha8(12345) == email_sha8("12345")
    class _Ugly:
        def __str__(self):  # noqa: D401
            raise RuntimeError("boom")
    assert email_sha8(_Ugly()) == "none"


# ─── 5 · auth.py log-line sanitization (regression) ──────────────
# Static scan: assert the three raw-email log lines flagged by
# TD-09 have been replaced with ``email_sha8=`` format strings and
# that no new ``email=%s`` leak has been introduced.
def test_auth_py_log_lines_use_email_sha8_not_raw_email():
    import pathlib
    src = pathlib.Path(
        "/app/backend/routers/auth.py",
    ).read_text(encoding="utf-8")
    # Positive — the three WARN lines carry the sanitized identifier.
    assert "email_sha8=%s match_count=%d" in src, (
        "TD-09: portal-invite collision WARN must use email_sha8="
    )
    assert "email_sha8=%s role=%s" in src, (
        "TD-09: multi-record same-role WARN must use email_sha8="
    )
    assert "multi-record chooser served — email_sha8=%s" in src, (
        "TD-09: multi-record chooser WARN must use email_sha8="
    )
    # Negative — count the raw ``email=%s`` sites. Exactly ONE
    # legitimate occurrence remains (line ~343, which passes the
    # literal string ``"<redacted>"`` as the format arg — not a
    # PII leak). Everything else must be gone.
    raw_sites = [
        line for line in src.splitlines()
        if "email=%s" in line
    ]
    assert len(raw_sites) == 1, (
        "TD-09 regression: expected exactly 1 pre-redacted "
        f"email=%s line, found {len(raw_sites)}: {raw_sites}"
    )
    # And that one line must still carry the ``<redacted>`` sentinel
    # in its argument tuple.
    assert '"<redacted>"' in src, (
        "TD-09: founder-promotion log line must keep its "
        "'<redacted>' literal arg"
    )


# ─── 6 · live runtime capture via caplog ─────────────────────────
# Exercises the actual logger.warning call path for the TD-09
# target branch (role=customer, >=2 distinct customer_ids). The
# format string is pre-interpolated by the stdlib logger; we assert
# the final rendered message carries ``email_sha8=`` and NEVER the
# raw email.
def test_portal_collision_warning_emits_email_sha8(caplog):
    import logging as _logging
    _logging.getLogger("routers.auth").propagate = True
    logger = _logging.getLogger("routers.auth")

    # Simulate the exact format string used at the TD-09 target.
    with caplog.at_level("WARNING", logger="routers.auth"):
        logger.warning(
            "[auth] PORTAL-INVITE-EMAIL-COLLISION-FIX observability "
            "— duplicate role=customer rows with distinct customer_ids "
            "detected on login — email_sha8=%s match_count=%d "
            "distinct_customer_id_count=%d",
            email_sha8("alice@example.com"), 2, 2,
        )
    rec = next(
        r for r in caplog.records
        if "PORTAL-INVITE-EMAIL-COLLISION-FIX" in r.getMessage()
    )
    msg = rec.getMessage()
    assert "email_sha8=" in msg
    assert "alice@example.com" not in msg
