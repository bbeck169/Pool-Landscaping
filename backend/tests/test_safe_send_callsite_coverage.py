"""SAFE-SEND-A · Feb-2026 — callsite coverage guardrail.

Load-bearing test — greps the backend tree for every direct
call to ``comms_email_adapter.send_email`` /
``comms_sms_adapter.send_sms`` and asserts each carries an
explicit ``context=`` kwarg.  Any callsite that forgets
``context=`` fails this test with the offending file + line
number, so future contributors can't silently regress the
mandatory-gate contract.

Discovery rules:
- Only ``await send_email(`` / ``await send_sms(`` (direct
  adapter calls). Local ``_send_email`` / ``_send_sms``
  wrappers with a leading underscore are OUT OF SCOPE for
  this test — those wrappers propagate ``context`` through
  their own signature; the underlying adapter call is what
  gets grep'd.
- Test files are excluded (they cover missing-context on
  purpose via ``pytest.raises``).
- ``services/comms_email_adapter.py`` +
  ``services/comms_sms_adapter.py`` are excluded — the
  ``def send_email(`` / ``def send_sms(`` signatures live
  there.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_BACKEND_ROOT = Path(__file__).resolve().parent.parent


_CALL_RE_EMAIL = re.compile(r"await\s+send_email\s*\(")
_CALL_RE_SMS = re.compile(r"await\s+send_sms\s*\(")
_CONTEXT_KWARG = re.compile(r"\bcontext\s*=")


_EXCLUDED_FILES = {
    "services/comms_email_adapter.py",  # signature site
    "services/comms_sms_adapter.py",     # signature site
    # Design forks — these files call a ``send_email`` / ``send_sms``
    # symbol from a DIFFERENT module (not the SAFE-SEND-gated
    # ``comms_*_adapter``).  The regex-only guardrail can't
    # distinguish between adapter-level and provider-level callsites,
    # so we exclude them here with the specific import-source noted.
    # If either file is ever refactored to route through the
    # SAFE-SEND adapters, delete its entry and add ``context=`` to
    # the callsite.
    "emailer.py",                         # own Resend-direct send_email
    "routers/warranties.py",              # imports send_email from ``emailer``
    "services/lana/reminders.py",         # imports send_sms from ``services.sms_provider`` (dead module → dry-run)
}


def _iter_backend_py() -> list[Path]:
    files: list[Path] = []
    for path in _BACKEND_ROOT.rglob("*.py"):
        # skip tests, migrations, scripts, pycache
        rel = path.relative_to(_BACKEND_ROOT).as_posix()
        if rel.startswith("tests/") or rel.startswith("__pycache__"):
            continue
        if rel.startswith(("migrations/", "scripts/")):
            continue
        if rel in _EXCLUDED_FILES:
            continue
        files.append(path)
    return files


def _find_uncontexted_callsites(pattern: re.Pattern):
    """Return ``[(path, lineno, snippet)]`` for every direct
    adapter call missing a ``context=`` kwarg within a 30-line
    scan window from the call-site (the kwarg is almost always
    on the same or the next few lines)."""
    violations = []
    for path in _iter_backend_py():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for idx, line in enumerate(lines):
            if not pattern.search(line):
                continue
            # Scan the current + next 30 lines for context= kwarg
            # (multi-line calls span several lines).
            window = "\n".join(lines[idx: idx + 30])
            if _CONTEXT_KWARG.search(window):
                continue
            snippet = line.strip()[:120]
            rel = path.relative_to(_BACKEND_ROOT).as_posix()
            violations.append((rel, idx + 1, snippet))
    return violations


def test_every_send_email_callsite_has_context_kwarg():
    """Every ``await send_email(`` in the backend must carry
    an explicit ``context=CommsContext.<X>`` kwarg. Missing →
    fail with the file path + line number so the offending
    site can be fixed.
    """
    violations = _find_uncontexted_callsites(_CALL_RE_EMAIL)
    if violations:
        lines = "\n".join(
            f"  - {p}:{ln}  →  {s}" for p, ln, s in violations
        )
        pytest.fail(
            f"{len(violations)} send_email callsite(s) missing "
            f"explicit context= kwarg — SAFE-SEND-A gate broken:\n"
            f"{lines}"
        )


def test_every_send_sms_callsite_has_context_kwarg():
    """Every ``await send_sms(`` in the backend must carry an
    explicit ``context=CommsContext.<X>`` kwarg.
    """
    violations = _find_uncontexted_callsites(_CALL_RE_SMS)
    if violations:
        lines = "\n".join(
            f"  - {p}:{ln}  →  {s}" for p, ln, s in violations
        )
        pytest.fail(
            f"{len(violations)} send_sms callsite(s) missing "
            f"explicit context= kwarg — SAFE-SEND-A gate broken:\n"
            f"{lines}"
        )
