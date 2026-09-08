"""Phase I1.7.e · Feb-2026 — Messaging test-mode short-circuit.

Mirrors the existing ``ZILLOW_TESTMODE_MOCK`` / ``PAYMENTS_TESTMODE_MOCK``
/ ``CALENDARS_TESTMODE_MOCK`` pattern for messaging so
preview / dev / staging tester passes can verify the full transactional
+ bulk cap-exceeded contracts end-to-end without needing valid
Twilio / RingCentral / SendGrid / Resend API keys.

Enable in preview ``.env`` with::

    MESSAGING_TESTMODE_MOCK=true

When enabled, every last-mile outbound HTTP call in the four
centralized messaging adapters is short-circuited to a deterministic
fixture envelope. Cap accounting, opt-out gates, the comm allowlist
gate, ``guard_outbound`` kill-switch, and the tenant-BYO probe **all
still fire** — only the actual provider HTTP request is skipped.

Deterministic response contract:
  * ``message_id`` = ``"mock-<sha1(tenant|to|body)[:12]>"`` so
    idempotency caches still work.
  * ``provider_status`` = ``"sent"`` — downstream classifiers treat
    it identically to a real send.
  * ``routed_via`` = ``"messaging_testmode_mock"`` so audit trails
    can distinguish mocks from live sends.

To simulate cap-exceeded in tests, monkey-patch the BYO probe
(``try_dispatch_email_tenant_byo`` / ``try_dispatch_sms_tenant_byo``)
to return a cap-exceeded envelope. Test-mode NEVER surfaces
cap-exceeded by itself — a cap hit is a state that lives inside the
tenant's upstream provider, not in preview env config.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, List, Optional


_ENV_FLAG = "MESSAGING_TESTMODE_MOCK"


def is_messaging_testmode() -> bool:
    """Return True when ``MESSAGING_TESTMODE_MOCK`` is set to any
    truthy value. Re-read the env on every call so a supervisor
    reload of ``.env`` picks up the change without a process
    restart."""
    return os.environ.get(_ENV_FLAG, "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _mock_msg_id(tenant_id: Optional[str], to: str, body: str) -> str:
    """Deterministic message id — same (tenant, recipient, body) in,
    same id out — so idempotency caches, delivery ledgers, and log
    grep-audits all work identically to a real send."""
    seed = f"{tenant_id or 'no-tenant'}|{to}|{body}"
    return "mock-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def mock_email_envelope(
    *,
    tenant_id: Optional[str],
    to: str,
    subject: str,
    routed_via: str = "messaging_testmode_mock",
) -> Dict[str, Any]:
    """Return a deterministic mock email envelope compatible with
    BOTH the legacy platform-adapter shape (``status`` / ``provider_id``)
    AND the modern adapter shape (``provider_status`` /
    ``provider_response_id``). ``routed_via`` distinguishes a
    BYO-mock from a platform-mock in the audit trail."""
    mid = _mock_msg_id(tenant_id, to, subject)
    return {
        # Legacy shape.
        "status": "sent",
        "provider_id": mid,
        # Modern shape.
        "provider": "mock",
        "provider_status": "sent",
        "provider_response_id": mid,
        "attempts": 1,
        "error": None,
        "routed_via": routed_via,
        "raw": {"testmode_mock": True, "tenant_id": tenant_id},
    }


def mock_sms_envelope(
    *,
    tenant_id: Optional[str],
    to: str,
    body: str,
    routed_via: str = "messaging_testmode_mock",
    length_stats: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Return a deterministic mock SMS envelope. ``length_stats``
    (from ``sms_length_stats``) is merged in so downstream ledger
    rows still get ``character_count`` / ``segment_count``."""
    mid = _mock_msg_id(tenant_id, to, body)
    env: Dict[str, Any] = {
        "status": "sent",
        "provider_id": mid,
        "provider": "mock",
        "provider_status": "sent",
        "provider_response_id": mid,
        "attempts": 1,
        "error": None,
        "routed_via": routed_via,
        "raw": {"testmode_mock": True, "tenant_id": tenant_id},
    }
    if length_stats:
        env.update(length_stats)
    return env


__all__ = [
    "is_messaging_testmode",
    "mock_email_envelope",
    "mock_sms_envelope",
]
