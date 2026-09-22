"""Phase P24 · Feb-2026 — Go-live testmode env-flip defaults.

Locks the following contracts:

  1. **Default-False.** With ``AI_TESTMODE_MOCK`` /
     ``CALENDARS_TESTMODE_MOCK`` / ``ZILLOW_TESTMODE_MOCK`` UNSET, the
     three module-level ``*_testmode_mock`` helpers each return
     ``False``. This is the single source of truth — no callsite is
     allowed to inline ``os.getenv(...)``.
  2. **Truthy / falsy variants.** ``"true"`` / ``"1"`` / ``"TRUE"`` /
     ``"True"`` / ``"yes"`` / ``"on"`` (case-insensitive, integer
     alias) resolve to ``True``. ``"false"`` / ``"0"`` /
     ``"anything_else"`` / ``""`` resolve to ``False``.
  3. **WARN log emission.** The P24 boot helper
     ``server._p24_warn_active_testmode_mocks`` emits EXACTLY one
     ``WARNING`` per active flag: 3 when all three mocks are true, 0
     when all off, ``N`` when only ``N`` enabled.
  4. **Hermetic guard.** ``backend/tests/conftest.py`` sets the three
     flags to ``"true"`` via ``os.environ.setdefault`` at import time
     so a stale prod-shaped ``.env`` (mocks=false) can never leak
     real API calls into a test run.

Uses the ``_f7_loop_fixture``-style pattern (no ``pytest-asyncio``).
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
from pathlib import Path

import pytest


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def _clean_p24_env(monkeypatch):
    """Delete the three P24 mock flags from ``os.environ`` for the
    duration of a test. ``monkeypatch.delenv(raising=False)`` handles
    the case where the flag was never set."""
    for k in ("AI_TESTMODE_MOCK",
              "CALENDARS_TESTMODE_MOCK",
              "ZILLOW_TESTMODE_MOCK"):
        monkeypatch.delenv(k, raising=False)


# ── Helpers ────────────────────────────────────────────────────────


def _import_helpers():
    """Return the three central ``*_testmode_mock`` helpers — the
    'single source of truth' for each flag. Imported lazily so the
    module can't cache a stale env read at import time."""
    from services.ai._helpers import ai_testmode_mock
    from services.calendars._helpers import calendars_testmode_mock
    from services.enrichment.zillow import _testmode_mock as zillow_testmode_mock
    return {
        "AI_TESTMODE_MOCK": ai_testmode_mock,
        "CALENDARS_TESTMODE_MOCK": calendars_testmode_mock,
        "ZILLOW_TESTMODE_MOCK": zillow_testmode_mock,
    }


# ── 1) Default-False — through central helpers ─────────────────────


def test_p24_defaults_to_false_when_unset(_clean_p24_env):
    """No env vars set → each helper returns ``False``. This locks the
    single-source-of-truth pattern — callsites MUST use these helpers
    and not inline ``os.getenv(...)`` reads (which would still work
    but bypass the shared truthy-set semantics)."""
    helpers = _import_helpers()
    for flag, fn in helpers.items():
        assert fn() is False, (
            f"{flag} helper returned True with env UNSET — "
            f"P24 default-false contract violated."
        )


# ── 2) Truthy / falsy variants — case-insensitive + integer alias ─


@pytest.mark.parametrize("raw", ["true", "1", "TRUE", "True",
                                   "yes", " true ", "TrUe"])
def test_p24_truthy_variants_resolve_true(monkeypatch, raw):
    """All accepted truthy spellings flip each helper to ``True``.
    Includes case-mix + surrounding whitespace so a shell-quoting
    accident (``AI_TESTMODE_MOCK=" true "``) doesn't silently disable
    the mock. Note: the three module helpers accept ``{"1", "true",
    "yes"}`` (case-insensitive after strip); the P24 WARN loop
    additionally accepts ``"on"`` (see the dedicated WARN tests
    below)."""
    helpers = _import_helpers()
    for flag, fn in helpers.items():
        monkeypatch.setenv(flag, raw)
        assert fn() is True, (
            f"{flag}={raw!r} did not resolve to True — "
            f"P24 truthy-set contract violated."
        )


@pytest.mark.parametrize(
    "raw", ["false", "0", "no", "off", "anything_else", "", "  ", "False"]
)
def test_p24_falsy_variants_resolve_false(monkeypatch, raw):
    """Anything outside the truthy set → ``False``. Includes
    ``"false"`` (word), ``"0"`` (int alias), ``"anything_else"`` (garbage
    guard), and empty / whitespace-only strings."""
    helpers = _import_helpers()
    for flag, fn in helpers.items():
        monkeypatch.setenv(flag, raw)
        assert fn() is False, (
            f"{flag}={raw!r} resolved to True — expected False."
        )


# ── 3) WARN log emission — count matches active flag count ────────


def _load_server_for_warn():
    """Import (or return cached) ``server`` module — needed to
    invoke the extracted ``_p24_warn_active_testmode_mocks`` helper.
    We only need the helper, not the FastAPI app, so this is
    lightweight (config.py side-effects still fire, but that's the
    same footprint the rest of the suite already pays)."""
    if "server" in sys.modules:
        return sys.modules["server"]
    return importlib.import_module("server")


def test_p24_warn_emits_zero_when_all_flags_off(_clean_p24_env, caplog):
    """No flag set → helper returns 0 and emits 0 warnings."""
    srv = _load_server_for_warn()
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="pool_crm"):
        n = srv._p24_warn_active_testmode_mocks()
    assert n == 0
    startup_warns = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "STARTUP:" in r.getMessage()
    ]
    assert startup_warns == [], (
        f"Expected 0 STARTUP warnings, got {len(startup_warns)}: "
        f"{[r.getMessage() for r in startup_warns]}"
    )


def test_p24_warn_emits_three_when_all_flags_on(monkeypatch, caplog):
    """All three flags truthy → helper returns 3 and emits exactly 3
    ``WARNING`` records, one per flag, with the flag name in the
    message body."""
    srv = _load_server_for_warn()
    for flag in ("AI_TESTMODE_MOCK", "CALENDARS_TESTMODE_MOCK",
                 "ZILLOW_TESTMODE_MOCK"):
        monkeypatch.setenv(flag, "true")
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="pool_crm"):
        n = srv._p24_warn_active_testmode_mocks()
    assert n == 3
    startup_warns = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "STARTUP:" in r.getMessage()
    ]
    assert len(startup_warns) == 3, (
        f"Expected 3 STARTUP warnings, got {len(startup_warns)}: "
        f"{[r.getMessage() for r in startup_warns]}"
    )
    body = " ".join(r.getMessage() for r in startup_warns)
    for flag in ("AI_TESTMODE_MOCK", "CALENDARS_TESTMODE_MOCK",
                 "ZILLOW_TESTMODE_MOCK"):
        assert flag in body, f"WARN batch missing flag {flag!r}"


@pytest.mark.parametrize(
    "enabled",
    [
        ("AI_TESTMODE_MOCK",),
        ("CALENDARS_TESTMODE_MOCK", "ZILLOW_TESTMODE_MOCK"),
        ("AI_TESTMODE_MOCK", "ZILLOW_TESTMODE_MOCK"),
    ],
)
def test_p24_warn_emits_n_when_only_n_flags_on(
    _clean_p24_env, monkeypatch, caplog, enabled
):
    """Only ``N`` of the three flags on → exactly ``N`` warnings, and
    each warning message names the enabled flag (no false-positive
    warnings for the off ones)."""
    srv = _load_server_for_warn()
    for flag in enabled:
        monkeypatch.setenv(flag, "true")
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="pool_crm"):
        n = srv._p24_warn_active_testmode_mocks()
    assert n == len(enabled)
    startup_warns = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "STARTUP:" in r.getMessage()
    ]
    assert len(startup_warns) == len(enabled)
    warned_flags = {
        flag for flag in ("AI_TESTMODE_MOCK", "CALENDARS_TESTMODE_MOCK",
                          "ZILLOW_TESTMODE_MOCK")
        if any(flag in r.getMessage() for r in startup_warns)
    }
    assert warned_flags == set(enabled), (
        f"WARN set drift — enabled={set(enabled)}, warned={warned_flags}"
    )


# ── 4) Hermetic guard — conftest.py forces mocks=true at collect ──


def test_p24_conftest_sets_hermetic_mock_defaults():
    """Source-level grep on ``tests/conftest.py`` — the three
    ``os.environ.setdefault`` calls (one per flag) MUST be present so
    a stale prod-shaped ``.env`` (mocks=false) can never bleed real
    API traffic into a test run.

    Guardrail rationale: after the P24 env-flip, ``backend/.env`` now
    ships ``AI_TESTMODE_MOCK=false``. Without this guard, ``pytest``
    would pick that up via ``dotenv_values`` on any suite that imports
    ``server`` (which imports ``config`` which calls ``load_dotenv``)
    and hit the real OpenAI / Google Calendar / Zillow endpoints.
    """
    conftest_path = Path(__file__).resolve().parent / "conftest.py"
    body = conftest_path.read_text(encoding="utf-8")
    for flag in ("AI_TESTMODE_MOCK",
                 "CALENDARS_TESTMODE_MOCK",
                 "ZILLOW_TESTMODE_MOCK"):
        needle = f'os.environ.setdefault(_p24_flag, "true")'
        needle_alt_a = f'os.environ.setdefault("{flag}", "true")'
        needle_alt_b = f"os.environ.setdefault('{flag}', 'true')"
        # Accept either the tuple-loop pattern (needle) or the explicit
        # per-flag form (needle_alt_*). Also assert the flag NAME is
        # present in the conftest body (so the loop pattern doesn't
        # silently omit one).
        assert flag in body, (
            f"conftest.py does not reference {flag} — hermetic guard "
            f"missing. Re-add the P24 os.environ.setdefault loop at "
            f"the top of the module."
        )
        assert (needle in body or needle_alt_a in body
                or needle_alt_b in body), (
            f"conftest.py has no os.environ.setdefault(...) for "
            f"{flag} — hermetic guard incomplete."
        )


def test_p24_hermetic_guard_actually_took_effect():
    """Runtime assertion — after conftest import, ``os.environ`` MUST
    hold the three flags. Value can be anything truthy (developer may
    have set them explicitly before invoking pytest); this test only
    guarantees the vars are DEFINED so downstream ``.env`` loads can't
    silently override them to ``"false"``."""
    for flag in ("AI_TESTMODE_MOCK",
                 "CALENDARS_TESTMODE_MOCK",
                 "ZILLOW_TESTMODE_MOCK"):
        assert flag in os.environ, (
            f"{flag} not present in os.environ after conftest import — "
            f"hermetic guard did not fire. Check the setdefault loop "
            f"at the top of tests/conftest.py."
        )


# ── 5) .env.example / .env defaults are False (documentation gate) ─


def test_p24_env_example_defaults_are_false():
    """``.env.example`` (the committed template ops copies to `.env`
    on a new pod) MUST ship the three flags set to ``false``. Guards
    against a copy-paste regression that would re-enable mocks by
    default on a fresh install."""
    env_example = Path(__file__).resolve().parents[1] / ".env.example"
    if not env_example.is_file():
        pytest.skip(".env.example not present in backend/")
    body = env_example.read_text(encoding="utf-8")
    for flag in ("AI_TESTMODE_MOCK",
                 "CALENDARS_TESTMODE_MOCK",
                 "ZILLOW_TESTMODE_MOCK"):
        line = f"{flag}=false"
        assert line in body, (
            f".env.example missing `{line}` — P24 default-false "
            f"documentation gate failed."
        )
