"""MTH-C · Feb-2026 — Callsite coverage lock.

Every production callsite that reaches
:func:`services.ai_hub.context_stamping.stamp_agent_context` MUST
go through the async ``_with_gate`` wrapper (or the ``_or_defer``
extension) so the per-tenant AI rules gate always runs.

The one exception is inside ``context_stamping.py`` itself — the
async wrapper chains to the sync stamper as its final decision.

Any future callsite that legitimately can't migrate can land on
the allowlist below (with a justification comment) and pass this
test.  Empty allowlist today.
"""
from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

# Absolute paths inside backend/ that are ALLOWED to call
# ``stamp_agent_context`` directly.  Add with a justification.
ALLOWLIST = {
    # The sync stamper's own module (chained by _with_gate).
    BACKEND / "services" / "ai_hub" / "context_stamping.py",
    # MTH-C gated-send helper chains to the sync stamper on its
    # fast-path — same rationale as _with_gate.  Callers of
    # ``gated_send.stamp_agent_context_with_gate_or_defer`` get
    # the full gate coverage.
    BACKEND / "services" / "ai_comms" / "gated_send.py",
    # MTH-C escalation notifier — invokes stamp_agent_context ONCE
    # with a synthetic "system_escalation" employee row (returns
    # SYSTEM verbatim).  The call exists to satisfy the AIHUB-A
    # send-adapter guardrail; it doesn't reach a customer, only
    # tenant admins.
    BACKEND / "services" / "ai_hub" / "escalation_detector.py",
}


def _iter_py_files():
    for p in BACKEND.rglob("*.py"):
        if any(part in {"__pycache__", "tests", "migrations",
                          "scripts", ".venv"} for part in p.parts):
            continue
        yield p


_CALL_RE = re.compile(r"\bstamp_agent_context\s*\(")


def test_no_sync_callsites_outside_allowlist():
    violations = []
    for path in _iter_py_files():
        text = path.read_text(errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if not _CALL_RE.search(stripped):
                continue
            # ``stamp_agent_context_with_gate`` and
            # ``stamp_agent_context_with_gate_or_defer`` are the
            # gated forms — allowed everywhere.
            if "stamp_agent_context_with_gate" in stripped:
                continue
            if "stamp_agent_context_with_gate_or_defer" in stripped:
                continue
            # ``def stamp_agent_context...`` in the definition file.
            if "def stamp_agent_context" in stripped:
                continue
            if path in ALLOWLIST:
                continue
            violations.append(f"{path}:{lineno} → {stripped}")
    assert not violations, (
        "MTH-C callsite coverage violated — direct sync "
        "stamp_agent_context() calls outside the allowlist:\n"
        + "\n".join(violations)
    )


def test_allowlist_is_current():
    # The allowlist itself MUST reference existing files so a
    # deletion doesn't accidentally weaken the guard.
    for p in ALLOWLIST:
        assert p.exists(), f"MTH-C callsite allowlist stale: {p}"
