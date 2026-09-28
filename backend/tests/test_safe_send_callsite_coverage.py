"""SAFE-SEND-A / SAFE-SEND-C · Feb-2026 — callsite coverage guardrail.

Two related but independent contracts are enforced here:

1. **SAFE-SEND-A (context kwarg coverage).**  Every direct
   ``await send_email(`` / ``await send_sms(`` in the backend must
   carry an explicit ``context=CommsContext.<X>`` kwarg — proves the
   caller stamped the send provenance so the adapter can decide
   passthrough vs. redirect.  Test files are excluded (they cover
   missing-context on purpose via ``pytest.raises``).

2. **SAFE-SEND-C (adapter-unification ban).**  Legacy vendor SDK
   bypasses of the SAFE-SEND gate are banned outside the adapter
   files themselves.  Concretely:

   - ``resend.Emails.send(`` / ``resend.emails.send(`` — banned
     outside the resend adapter files below.
   - ``platform.post("/restapi/v1.0/account/~/extension/~/sms"`` —
     the raw RingCentral SMS transport HTTP call, banned outside
     the RC adapter files below.
   - ``requests.post`` / ``httpx.post`` targeting
     ``api.resend.com`` or a ``*.ringcentral.com`` host — banned
     outside the adapter files below.

   Callsites needing a legitimate exemption must place an inline
   ``# safe-send: allowlist because <specific-reason>`` sentinel
   comment on the offending line or within the preceding 5 lines.
   The reason must be substantive (matched by the regex — any
   non-empty text after ``because`` is accepted; the burden of
   specificity is on the reviewer, not the test).

Discovery rules for SAFE-SEND-A checks:
- Only ``await send_email(`` / ``await send_sms(`` (direct
  adapter calls). Local ``_send_email`` / ``_send_sms``
  wrappers with a leading underscore are OUT OF SCOPE — those
  wrappers propagate ``context`` through their own signature.
- Test files are excluded.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_BACKEND_ROOT = Path(__file__).resolve().parent.parent


# ─── SAFE-SEND-A · context-kwarg coverage ──────────────────────────
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
    "routers/warranties.py",              # imports send_email from ``emailer``
}


# ─── SAFE-SEND-C · adapter-unification ban ─────────────────────────
# Raw SDK / HTTP callsites that ARE legitimately allowed:
# * The two email adapter files (comms_email_adapter is the
#   SAFE-SEND-A gated high-level wrapper; resend_adapter is the
#   SAFE-SEND-C gated low-level adapter).
# * The two SMS adapter files (comms_sms_adapter is the SAFE-SEND-A
#   gated high-level wrapper; rc_adapter wraps RingCentralService).
# * sdk_intercept.py — patches ``resend.Emails.send`` at boot so
#   every direct SDK caller is force-routed through
#   ``is_comm_allowed_sync``.  It NEEDS to reference the raw symbol.
# * ringcentral_provider.py — the tenant-BYO RingCentral provider;
#   part of the messaging-BYO stack, itself an adapter.
_RAW_SDK_ALLOWED_FILES = {
    "services/email/resend_adapter.py",
    "services/comms_email_adapter.py",
    "services/comms/sdk_intercept.py",
    "services/comms_sms_adapter.py",
    "services/sms/rc_adapter.py",
    "services/messaging/sms/ringcentral_provider.py",
}


_RESEND_SDK_RE = re.compile(r"\bresend\.[Ee]mails\.send\s*\(")
_RC_PLATFORM_POST_SMS_RE = re.compile(
    r"platform\.post\s*\(\s*[\"']/restapi/v1\.0/account/~/extension/~/sms[\"']",
)
_HTTP_POST_HOST_RE = re.compile(
    r"(requests|httpx)\.(post|request|Client|AsyncClient)\s*"
    r"[\s\S]{0,240}?(api\.resend\.com|\.ringcentral\.com)",
)


_SAFE_SEND_ALLOWLIST_SENTINEL_RE = re.compile(
    r"#\s*safe-send:\s*allowlist\s+because\s+\S",
)


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


def _sentinel_present(lines: list[str], idx: int) -> bool:
    """True if the offending line at 0-based ``idx`` (or any of
    the 5 preceding lines) carries a
    ``# safe-send: allowlist because <reason>`` sentinel."""
    lo = max(0, idx - 5)
    window = "\n".join(lines[lo: idx + 1])
    return bool(_SAFE_SEND_ALLOWLIST_SENTINEL_RE.search(window))


def _find_banned_bypass_callsites(pattern: re.Pattern,
                                    excluded: set[str]):
    """Grep every backend .py file for ``pattern`` and return
    ``[(path, lineno, snippet)]`` for every match that is NOT in
    the ``excluded`` allowlist AND does NOT carry an inline
    SAFE-SEND allowlist sentinel."""
    violations = []
    for path in _BACKEND_ROOT.rglob("*.py"):
        rel = path.relative_to(_BACKEND_ROOT).as_posix()
        if rel.startswith(("tests/", "__pycache__/",
                            "migrations/", "scripts/")):
            continue
        if rel in excluded:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for idx, line in enumerate(lines):
            if not pattern.search(line):
                continue
            if _sentinel_present(lines, idx):
                continue
            snippet = line.strip()[:120]
            violations.append((rel, idx + 1, snippet))
    return violations


# ═══════════════════════════════════════════════════════════════════
# SAFE-SEND-A · context-kwarg coverage
# ═══════════════════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════════════
# SAFE-SEND-C · adapter-unification ban
# ═══════════════════════════════════════════════════════════════════
def test_no_raw_resend_sdk_outside_adapters():
    """``resend.Emails.send(`` / ``resend.emails.send(`` bypasses
    the SAFE-SEND-C gate.  Only the two email adapter files (and
    ``sdk_intercept.py``, which patches the SDK entry point) may
    reference the raw SDK symbol.  Anywhere else must either
    migrate to ``await _resend_send(..., context=CommsContext.X)``
    OR add an inline ``# safe-send: allowlist because <reason>``
    sentinel on the callsite or within the preceding 5 lines.
    """
    violations = _find_banned_bypass_callsites(
        _RESEND_SDK_RE, _RAW_SDK_ALLOWED_FILES,
    )
    if violations:
        lines = "\n".join(
            f"  - {p}:{ln}  →  {s}" for p, ln, s in violations
        )
        pytest.fail(
            f"{len(violations)} raw resend.Emails.send callsite(s) "
            f"outside the SAFE-SEND adapters — SAFE-SEND-C bypass:\n"
            f"{lines}\n\n"
            "Migrate to ``await _resend_send(..., "
            "context=CommsContext.<X>)`` or add an inline "
            "``# safe-send: allowlist because <reason>`` sentinel."
        )


def test_no_raw_rc_platform_sms_post_outside_adapters():
    """``platform.post('/restapi/v1.0/account/~/extension/~/sms', ...)``
    is the raw RingCentral SMS-send HTTP transport.  Only the two SMS
    adapter files and the BYO RC provider may reference it.
    """
    violations = _find_banned_bypass_callsites(
        _RC_PLATFORM_POST_SMS_RE, _RAW_SDK_ALLOWED_FILES,
    )
    if violations:
        lines = "\n".join(
            f"  - {p}:{ln}  →  {s}" for p, ln, s in violations
        )
        pytest.fail(
            f"{len(violations)} raw platform.post SMS callsite(s) "
            f"outside the SAFE-SEND adapters — SAFE-SEND-C bypass:\n"
            f"{lines}\n\n"
            "Migrate to ``await _rc_send(..., "
            "context=CommsContext.<X>)`` or add an inline "
            "``# safe-send: allowlist because <reason>`` sentinel."
        )


def test_no_raw_http_post_to_resend_or_rc_hosts_outside_adapters():
    """Direct ``requests.post`` / ``httpx.post`` (or client
    construction) targeting ``api.resend.com`` or a
    ``*.ringcentral.com`` host bypasses every SAFE-SEND gate.
    Same allowlist as the SDK check.
    """
    violations = _find_banned_bypass_callsites(
        _HTTP_POST_HOST_RE, _RAW_SDK_ALLOWED_FILES,
    )
    if violations:
        lines = "\n".join(
            f"  - {p}:{ln}  →  {s}" for p, ln, s in violations
        )
        pytest.fail(
            f"{len(violations)} raw HTTP callsite(s) to a Resend / "
            f"RingCentral host outside the SAFE-SEND adapters:\n"
            f"{lines}\n\n"
            "Migrate to the appropriate SAFE-SEND adapter or add an "
            "inline ``# safe-send: allowlist because <reason>`` "
            "sentinel."
        )
