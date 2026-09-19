"""Feb-2026 · Payments env hardening — regression tests for
``services.env_guard`` and the ``config.py`` dotenv precedence.

Covers:
  * Process env with a real ``sk_live_...`` value → safe.
  * Process env with a placeholder-shape value → detected + LOUD
    log line emitted with the greppable
    ``STRIPE_LIVE_KEY_PLACEHOLDER_DETECTED`` marker.
  * Process env EMPTY → silent (preview/test pods with no Stripe
    wired must not spam boot logs).
  * ``load_dotenv(override=False)`` is honoured — the process env
    value wins over a ``.env`` file with a competing placeholder.
    Verified by monkey-patching ``os.environ`` to simulate the
    pod's process environment BEFORE re-invoking ``load_dotenv``
    against a temp ``.env`` file — the real key must survive.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from services.env_guard import (
    check_stripe_live_key,
    _looks_like_placeholder,
    _PLACEHOLDER_PREFIXES,
    DOTENV_EXCLUSION_GLOBS,
)


# ═════════════════════════════════════════════════════════════════════
# Placeholder detection unit tests
# ═════════════════════════════════════════════════════════════════════
def test_real_live_key_is_safe(caplog):
    env = {"STRIPE_SECRET_KEY_LIVE":
             "sk_live_51NE9ygFKIPLAH4AyCnpBNYDet9XyohWpVuFi8qwTPp4B"}
    with caplog.at_level(logging.ERROR):
        report = check_stripe_live_key(env=env)
    assert report["present"] is True
    assert report["placeholder"] is None
    assert report["safe"] is True
    # No LOUD warning emitted.
    assert not any("STRIPE_LIVE_KEY_PLACEHOLDER_DETECTED" in r.message
                    for r in caplog.records)


def test_empty_key_is_silent(caplog):
    env = {"STRIPE_SECRET_KEY_LIVE": ""}
    with caplog.at_level(logging.ERROR):
        report = check_stripe_live_key(env=env)
    assert report["present"] is False
    assert report["placeholder"] is None
    assert report["safe"] is False
    # No log emitted for empty — preview pods must not spam boot logs.
    assert not any("STRIPE_LIVE_KEY_PLACEHOLDER_DETECTED" in r.message
                    for r in caplog.records)


def test_missing_key_is_silent(caplog):
    env = {}
    with caplog.at_level(logging.ERROR):
        report = check_stripe_live_key(env=env)
    assert report["present"] is False
    assert report["placeholder"] is None
    assert not any("STRIPE_LIVE_KEY_PLACEHOLDER_DETECTED" in r.message
                    for r in caplog.records)


def test_sk_test_masquerading_as_live_is_detected(caplog):
    """``sk_test_...`` in ``STRIPE_SECRET_KEY_LIVE`` is a common
    misconfiguration — someone pasted a test-mode key into the live
    slot. Must fire the warning."""
    env = {"STRIPE_SECRET_KEY_LIVE": "sk_test_51NE9ygFKIPLAH4Ay"}
    with caplog.at_level(logging.ERROR):
        report = check_stripe_live_key(env=env)
    assert report["placeholder"] == "sk_test_"
    assert report["safe"] is False
    warn_lines = [r.message for r in caplog.records
                   if "STRIPE_LIVE_KEY_PLACEHOLDER_DETECTED" in r.message]
    assert len(warn_lines) == 1
    assert "matched_prefix='sk_test_'" in warn_lines[0]


def test_all_documented_placeholder_prefixes_are_detected(caplog):
    """Belt-and-braces — every prefix in ``_PLACEHOLDER_PREFIXES``
    must trigger the warning when it appears at the start of the key."""
    for prefix in _PLACEHOLDER_PREFIXES:
        # Compose a fake key starting with each prefix.
        fake = prefix + "AAAA_padding_to_match_real_key_shape"
        env = {"STRIPE_SECRET_KEY_LIVE": fake}
        report = check_stripe_live_key(env=env)
        assert report["placeholder"] == prefix, (
            f"prefix {prefix!r} not detected — got {report}"
        )
        assert report["safe"] is False


def test_case_insensitive_prefix_match():
    for variant in ("SK_LIVE_REPLACE_ME_XXX", "sk_LIVE_replace_ME",
                     "Sk_Placeholder_"):
        env = {"STRIPE_SECRET_KEY_LIVE": variant}
        report = check_stripe_live_key(env=env)
        assert report["placeholder"] is not None, (
            f"case variant {variant!r} not detected"
        )


def test_looks_like_placeholder_helper():
    """Directly exercise the small predicate — makes intent explicit
    if the callable ever changes."""
    assert _looks_like_placeholder("") is None
    assert _looks_like_placeholder(None) is None  # type: ignore[arg-type]
    assert _looks_like_placeholder("sk_live_51real") is None
    assert _looks_like_placeholder("sk_test_51fake") == "sk_test_"
    assert _looks_like_placeholder("changeme_xxx") == "changeme"


# ═════════════════════════════════════════════════════════════════════
# Dotenv precedence — process env must win
# ═════════════════════════════════════════════════════════════════════
def test_process_env_wins_over_dotenv_file(tmp_path, monkeypatch):
    """Verifies the critical guarantee: the PROCESS environment value
    wins even if a ``.env`` file with a placeholder is loaded on top.

    Simulates the boot sequence:
      1. Pod starts with ``STRIPE_SECRET_KEY_LIVE=sk_live_real…`` in
         process env (Kubernetes secret injection).
      2. ``config.py`` calls ``load_dotenv(path, override=False)`` on
         a checked-in ``.env`` that unfortunately contains
         ``STRIPE_SECRET_KEY_LIVE=sk_placeholder_XXX``.
      3. Post-load ``os.environ["STRIPE_SECRET_KEY_LIVE"]`` MUST still
         hold the real value (process env wins).
    """
    from dotenv import load_dotenv

    # Pod's real process env — Kubernetes-injected secret.
    real_key = "sk_live_51NE9ygFKIPLAH4Ay_realkeyfromkubernetes"
    monkeypatch.setenv("STRIPE_SECRET_KEY_LIVE", real_key)

    # Attacker-shaped .env file — placeholder committed by accident.
    env_file = tmp_path / ".env"
    env_file.write_text(
        "STRIPE_SECRET_KEY_LIVE=sk_placeholder_committed_by_mistake\n"
        "SOME_OTHER_KEY=only_in_dotenv\n"
    )

    # Boot sequence: load .env with override=False (matches config.py).
    load_dotenv(env_file, override=False)

    # Process env must still hold the real key.
    assert os.environ["STRIPE_SECRET_KEY_LIVE"] == real_key
    # But the non-conflicting variable from the file should have
    # populated (proves the .env was actually consulted).
    assert os.environ["SOME_OTHER_KEY"] == "only_in_dotenv"

    # And the placeholder guard flags the SAFE state (no warning).
    report = check_stripe_live_key(env=os.environ)
    assert report["safe"] is True
    assert report["placeholder"] is None


def test_dotenv_override_false_is_the_default_behavior(tmp_path):
    """Regression guard: python-dotenv's ``load_dotenv`` defaults to
    ``override=False`` — if the library ever changes that default, this
    test fails and we get a chance to react."""
    from dotenv import load_dotenv
    real_key = "sk_live_pinned_probe_value"
    os.environ["STRIPE_SECRET_KEY_LIVE"] = real_key
    try:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "STRIPE_SECRET_KEY_LIVE=sk_placeholder_from_dotenv\n"
        )
        # NO explicit override kwarg — must default to False.
        load_dotenv(env_file)
        assert os.environ["STRIPE_SECRET_KEY_LIVE"] == real_key
    finally:
        os.environ.pop("STRIPE_SECRET_KEY_LIVE", None)


# ═════════════════════════════════════════════════════════════════════
# Documented .env.bak.* exclusion contract
# ═════════════════════════════════════════════════════════════════════
def test_documented_exclusion_globs_cover_expected_backups():
    """The exclusion list is a contract that future refactors must
    honour if they add a wildcard dotenv sweep."""
    for glob in (".env.bak", ".env.bak.*", ".env.local",
                  ".env.example", ".env.production.example"):
        assert glob in DOTENV_EXCLUSION_GLOBS, (
            f"exclusion glob {glob!r} missing from contract list"
        )
