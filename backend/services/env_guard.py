"""Feb-2026 · Payments env hardening — Stripe live-key placeholder guard.

Motivation
----------
In production, ``STRIPE_SECRET_KEY_LIVE`` MUST come from the pod's process
environment — a real ``sk_live_...`` value ops rotates independently of
the repo. An accidentally committed placeholder in ``.env`` /
``.env.example`` / ``.env.production.example`` could theoretically shadow
the real key IF someone flipped ``load_dotenv(override=True)`` in a
future refactor.

Two-layer defense
-----------------
1. Runtime precedence — ``config.load_dotenv(...)`` is called with an
   explicit ``override=False`` so the process env ALWAYS wins over the
   ``.env`` file. This is the python-dotenv default but writing it
   explicitly protects against a future refactor that flips it.

2. Startup placeholder detection — this module's ``check_stripe_live_key()``
   scans ``STRIPE_SECRET_KEY_LIVE`` for placeholder-shaped prefixes and
   emits a **LOUD** ``logging.error`` line if it looks fake. Ops greps
   for the marker string ``STRIPE_LIVE_KEY_PLACEHOLDER_DETECTED`` in the
   pod logs.

Also — ``.env.bak.*`` and ``.env.local`` are NOT loaded anywhere in the
runtime path (only ``.env`` is, via ``backend/config.py`` line 8). This
module documents that contract; if a future refactor adds a wildcard
dotenv sweep, it MUST honour this exclusion list.
"""
from __future__ import annotations

import logging
import os
import socket
from typing import List, Optional


# Prefixes that indicate a NON-real Stripe live key. Order matters —
# longer prefixes first so a match short-circuits cleanly. All checks
# are case-insensitive.
_PLACEHOLDER_PREFIXES: List[str] = [
    "sk_placeholder",
    "sk_sandbox_",
    "sk_dummy_",
    "sk_test_",          # test-mode key masquerading as live — LOUD warn
    "sk_live_replace_me",
    "sk_live_changeme",
    "sk_live_placeholder",
    "sk_live_xxx",
    "sk_live_todo",
    "changeme",
    "your_stripe_key_here",
    "replace_me",
    "todo",
]


# Dotenv files that MUST NEVER be authoritative for secrets. Consumed
# by future refactors — the current ``backend/config.py`` only loads
# ``.env`` so these are covered by construction, but the exclusion
# contract is documented here so it survives future changes.
DOTENV_EXCLUSION_GLOBS: List[str] = [
    ".env.bak",
    ".env.bak.*",
    ".env.local",
    ".env.local.*",
    ".env.production.example",
    ".env.example",
]


def _looks_like_placeholder(key: str) -> Optional[str]:
    """Return the matched placeholder prefix if ``key`` looks fake.

    Empty / None values return ``None`` — the caller decides whether
    empty is a valid state (test-mode pod without Stripe wired).
    """
    if not key:
        return None
    lower = key.strip().lower()
    for prefix in _PLACEHOLDER_PREFIXES:
        if lower.startswith(prefix):
            return prefix
    return None


def check_stripe_live_key(*, logger: Optional[logging.Logger] = None,
                            env: Optional[dict] = None) -> dict:
    """Scan ``STRIPE_SECRET_KEY_LIVE`` for placeholder-shape values.

    Returns a report dict:

        {
          "present": bool,           # key is non-empty
          "placeholder": Optional[str],   # matched prefix if any
          "hostname": str,           # pod hostname
          "safe": bool,              # True iff present and not a placeholder
        }

    Callers use the return value + the emitted log lines to decide
    whether to boot cleanly. This function does NOT ``sys.exit`` on
    its own — production callers may want to raise, dev callers just
    warn.
    """
    log = logger or logging.getLogger("pool_crm")
    src_env = env if env is not None else os.environ
    hostname = socket.gethostname()

    raw = (src_env.get("STRIPE_SECRET_KEY_LIVE") or "").strip()
    if not raw:
        # Empty is legitimate in preview/test pods — silent.
        return {"present": False, "placeholder": None,
                 "hostname": hostname, "safe": False}

    matched = _looks_like_placeholder(raw)
    if matched:
        # LOUD, GREPPABLE line. Ops greps for the marker.
        log.error(
            "STRIPE_LIVE_KEY_PLACEHOLDER_DETECTED hostname=%s "
            "matched_prefix=%r prefix_of_key=%r  "
            "→ STRIPE_SECRET_KEY_LIVE looks like a placeholder — "
            "the real ``sk_live_...`` value from Stripe MUST be set "
            "in the pod process environment. Payments WILL fail "
            "until this is fixed.",
            hostname, matched, raw[:16] + "…",
        )
        return {"present": True, "placeholder": matched,
                 "hostname": hostname, "safe": False}

    return {"present": True, "placeholder": None,
             "hostname": hostname, "safe": True}
