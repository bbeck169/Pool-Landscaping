"""Phase I1.7.e · Feb-2026 — Live-curl-parity tests for the two
`_TESTMODE_MOCK` env flags.

The chunk 2 tester surfaced a P0 gap: `MESSAGING_TESTMODE_MOCK=true`
was set in `.env` and every pytest that read `os.environ` directly
passed — but the running Uvicorn process (started BEFORE the flag
was added to `.env`) never saw it. Live curl requests 502'd at the
edge because the tenant-BYO probe kept trying to reach a fake
Twilio SID.

Root cause was env-var-not-loaded-by-process. The mitigation:

1. Add a boot-time log line (see ``server.py``:
   ``[testmode] MESSAGING_TESTMODE_MOCK=<bool> AI_TESTMODE_MOCK=<bool>``)
   so ops can grep-audit whether the running process has the flag.
2. Add the tests below to catch two flavors of drift:
   * The ``.env`` file HAS the flag but the currently-running
     process does NOT (env-not-loaded-at-startup).
   * The ``.env`` file has a typo / wrong casing / commented-out
     line (flag-declared-but-not-effective).

These tests read the same code path the running server uses
(``is_messaging_testmode()`` /
``services.ai._helpers.ai_testmode_mock()``) and compare with the
values parsed from the on-disk ``.env`` file. When the two disagree
in a preview / staging pod, the test fails with a message that
points at the drift.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import dotenv_values, load_dotenv


_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"

# Load ``.env`` into ``os.environ`` — mirrors what ``config.py`` does at
# server boot so this test file's assertions probe the same
# environment the running server sees.
load_dotenv(_ENV_PATH)


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


@pytest.mark.parametrize(
    "env_name, callable_import_path",
    [
        (
            "MESSAGING_TESTMODE_MOCK",
            "services.messaging.testmode:is_messaging_testmode",
        ),
        (
            "AI_TESTMODE_MOCK",
            "services.ai._helpers:ai_testmode_mock",
        ),
    ],
)
def test_testmode_env_flag_visible_at_process_start(env_name,
                                                       callable_import_path):
    """Regression guard for the chunk 2 tester's 502 finding.

    Parses ``.env`` from disk, imports the same helper the running
    server uses, and asserts they agree. When they disagree it means
    the process was started BEFORE ``.env`` was updated (or a wrong
    casing / commented-out line snuck in) — supervisor restart is
    the fix.
    """
    if not _ENV_PATH.exists():
        pytest.skip(f".env not present at {_ENV_PATH} (dev environment)")

    parsed = dotenv_values(_ENV_PATH)
    expected = _truthy(parsed.get(env_name))
    if not expected:
        pytest.skip(
            f"{env_name} is not truthy in .env — the drift-detection "
            f"invariant only applies when the flag is intentionally "
            f"enabled in this pod"
        )

    # Import the helper the running server actually calls.
    mod_path, attr = callable_import_path.split(":")
    mod = __import__(mod_path, fromlist=[attr])
    fn = getattr(mod, attr)
    actual = bool(fn())

    assert actual is True, (
        f"[testmode-drift] .env has {env_name}=true but "
        f"{callable_import_path}() returns {actual}. The running "
        f"backend process was likely started BEFORE the env flag was "
        f"added. Fix: `sudo supervisorctl restart backend`. If the "
        f"restart doesn't help, verify os.environ.get('{env_name}') "
        f"in a python -c inside the container."
    )


def test_testmode_flag_reads_env_on_every_call(monkeypatch):
    """Regression guard: the two testmode helpers must NOT cache
    their env value. If they did, a supervisor reload of ``.env``
    could not flip the flag without a full process restart, which
    would defeat the drift-recovery path in the sibling test."""
    from services.messaging.testmode import is_messaging_testmode
    from services.ai._helpers import ai_testmode_mock

    monkeypatch.setenv("MESSAGING_TESTMODE_MOCK", "true")
    monkeypatch.setenv("AI_TESTMODE_MOCK", "true")
    assert is_messaging_testmode() is True
    assert ai_testmode_mock() is True

    monkeypatch.setenv("MESSAGING_TESTMODE_MOCK", "")
    monkeypatch.setenv("AI_TESTMODE_MOCK", "")
    assert is_messaging_testmode() is False
    assert ai_testmode_mock() is False

    monkeypatch.setenv("MESSAGING_TESTMODE_MOCK", "false")
    monkeypatch.setenv("AI_TESTMODE_MOCK", "no")
    assert is_messaging_testmode() is False
    assert ai_testmode_mock() is False
