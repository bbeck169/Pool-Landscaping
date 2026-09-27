"""AIHUB-A · Feb-2026 — AI-comms callsite coverage guardrail.

Preventative test — any future ``services/marco/*``,
``services/soshie/*``, or ``services/ai_hub/*`` file that
adds a direct ``send_email`` / ``send_sms`` call MUST route
through ``services.ai_hub.context_stamping.stamp_agent_context``
first.  Without this, an AI-agentic send could bypass the
SAFE-SEND-A authorization gate and reach real customers even
when the employee is not ``authorized_for_public_use``.

The AI-comms surface is currently EMPTY (verified at AIHUB-A
recon — no MARCO / Soshie code path directly calls the
adapters; every AI action lands in the approval queue and
admin fires the send via a router endpoint that stamps
``CommsContext.SYSTEM`` on the admin's behalf).  This test
LOCKS that empty state.

If a future contributor adds a direct AI-comms send, this
test fires with the exact file + line + the required
``stamp_agent_context(...)`` invocation shape to apply.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_BACKEND_ROOT = Path(__file__).resolve().parent.parent


# Directories that host AI-agentic code paths.  Any direct
# adapter call in these dirs is a potential SAFE-SEND-A bypass.
_AI_AGENTIC_DIRS = (
    "services/marco",
    "services/soshie",
    "services/ai_hub",
)

# Regex — direct adapter call.  Mirrors the SAFE-SEND-A
# callsite-coverage rule.
_CALL_RE_EMAIL = re.compile(r"await\s+send_email\s*\(")
_CALL_RE_SMS = re.compile(r"await\s+send_sms\s*\(")
# The gate — any ``stamp_agent_context`` mention in the file
# means the module is at least AWARE of the gate.  We tighten
# to per-callsite proximity below.
_STAMP_RE = re.compile(r"stamp_agent_context\s*\(")


def _iter_agentic_py() -> list[Path]:
    files: list[Path] = []
    for rel_dir in _AI_AGENTIC_DIRS:
        root = _BACKEND_ROOT / rel_dir
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            files.append(path)
    return files


def _find_ai_adapter_bypasses(pattern: re.Pattern):
    """Return ``[(path, lineno, snippet)]`` for every direct
    adapter call in the AI-agentic dirs that lacks a
    ``stamp_agent_context`` mention within the enclosing
    function (30-line window scan above + below)."""
    violations = []
    for path in _iter_agentic_py():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for idx, line in enumerate(lines):
            if not pattern.search(line):
                continue
            # Scan 30 lines above + below for the stamp call.
            start = max(0, idx - 30)
            end = min(len(lines), idx + 30)
            window = "\n".join(lines[start:end])
            if _STAMP_RE.search(window):
                continue
            snippet = line.strip()[:120]
            rel = path.relative_to(_BACKEND_ROOT).as_posix()
            violations.append((rel, idx + 1, snippet))
    return violations


# ═══════════════════════════════════════════════════════════════════
# Assertion — AI dirs have zero un-stamped adapter callsites
# ═══════════════════════════════════════════════════════════════════
def test_ai_agentic_dirs_have_no_unstamped_send_email_callsites():
    violations = _find_ai_adapter_bypasses(_CALL_RE_EMAIL)
    if violations:
        lines = "\n".join(
            f"  - {p}:{ln}  →  {s}" for p, ln, s in violations
        )
        pytest.fail(
            f"{len(violations)} AI-agentic send_email callsite(s) do "
            f"NOT route through stamp_agent_context — SAFE-SEND-A "
            f"authorization gate bypassed.\n\nRoute each call via:\n"
            f"  effective_ctx = stamp_agent_context(\n"
            f"      employee=employee_row,\n"
            f"      requested_context=CommsContext.SYSTEM,\n"
            f"  )\n"
            f"  await send_email(..., context=effective_ctx)\n\n"
            f"Offenders:\n{lines}"
        )


def test_ai_agentic_dirs_have_no_unstamped_send_sms_callsites():
    violations = _find_ai_adapter_bypasses(_CALL_RE_SMS)
    if violations:
        lines = "\n".join(
            f"  - {p}:{ln}  →  {s}" for p, ln, s in violations
        )
        pytest.fail(
            f"{len(violations)} AI-agentic send_sms callsite(s) do "
            f"NOT route through stamp_agent_context — SAFE-SEND-A "
            f"authorization gate bypassed.\n\nRoute each call via:\n"
            f"  effective_ctx = stamp_agent_context(\n"
            f"      employee=employee_row,\n"
            f"      requested_context=CommsContext.SYSTEM,\n"
            f"  )\n"
            f"  await send_sms(..., context=effective_ctx)\n\n"
            f"Offenders:\n{lines}"
        )


def test_ai_agentic_dirs_are_discoverable():
    """Sanity — the AI-agentic dirs actually exist on disk.  If
    someone renames ``services/marco`` to ``services/marco_v2`` the
    coverage test above would pass vacuously with zero files
    scanned; this test catches that."""
    seen = {path.parent.relative_to(_BACKEND_ROOT).as_posix()
             for path in _iter_agentic_py()}
    expected_prefixes = ("services/marco", "services/soshie",
                          "services/ai_hub")
    for prefix in expected_prefixes:
        assert any(
            s.startswith(prefix) for s in seen
        ), f"AI-agentic dir {prefix!r} disappeared from tree — " \
           f"update _AI_AGENTIC_DIRS or restore the module"
