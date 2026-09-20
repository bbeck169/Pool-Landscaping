"""Phase C1 · Feb-2026 — public Stripe key health probe.

``GET /api/health/payments`` — no auth required.  Diagnostic used
after rotating the Stripe key so operators can confirm the live
key loads and the SDK reaches the Stripe API. Never leaks the key
value.

Response shape
--------------
::

    {
      "status": "ok" | "degraded" | "unconfigured",
      "checks": {
        "key_present":          bool,
        "key_shape_valid":      bool,
        "stripe_api_reachable": bool
      },
      "checked_at": "ISO8601"
    }

*   ``unconfigured``  — env var missing or matches a placeholder
    pattern (``sk_placeholder``, ``sk_test_placeholder``,
    ``REPLACE_ME_*``). No network call attempted.
*   ``degraded``      — key looked valid but the live Stripe API
    call failed (auth error, network, rate limit).
*   ``ok``            — key loaded AND ``stripe.Balance.retrieve()``
    returned a payload.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter

logger = logging.getLogger("pool_crm")
router = APIRouter(tags=["health"])

# Placeholder / obvious-test tokens that must NEVER be treated as a
# functional live key. ``sk_test_placeholder`` is the seed we ship in
# the .env.example.  Anything starting with ``REPLACE_ME`` is a
# templating artifact.
_PLACEHOLDER_PATTERNS = (
    re.compile(r"^sk_placeholder", re.IGNORECASE),
    re.compile(r"^sk_test_placeholder", re.IGNORECASE),
    re.compile(r"^REPLACE_ME", re.IGNORECASE),
    re.compile(r"^your[-_]?stripe[-_]?", re.IGNORECASE),
)

# ``stripe.Balance.retrieve()`` call is factored out so tests can
# monkeypatch it without touching the SDK.  Return value ignored —
# any non-exception result is treated as reachable.
_stripe_probe_fn: Optional[Callable[[str], Any]] = None


def set_stripe_probe(fn: Optional[Callable[[str], Any]]) -> None:
    """Test hook — swap in a stub ``fn(key) -> Any`` for the live
    Stripe SDK call.  Pass ``None`` to restore the default probe."""
    global _stripe_probe_fn
    _stripe_probe_fn = fn


def _default_probe(key: str) -> Any:
    """Live SDK probe. Wrapped in a helper so we can catch every
    exception at the caller and translate to ``degraded``.

    Uses the raw ``stripe`` package (v14.x is loaded at boot by
    ``services/payments/stripe_charge.py``). We assign the key
    locally on the SDK singleton for the duration of the call —
    this is what the existing charge/setup-intent code does.
    """
    import stripe as _stripe  # imported lazily so tests can stub
    prev = getattr(_stripe, "api_key", None)
    try:
        _stripe.api_key = key
        # Free Stripe API call — no charges triggered.
        _stripe.Balance.retrieve()
    finally:
        _stripe.api_key = prev
    return True


def _key_present(raw: Optional[str]) -> bool:
    return bool(raw and raw.strip())


def _key_shape_valid(raw: Optional[str]) -> bool:
    if not _key_present(raw):
        return False
    v = raw.strip()
    for pat in _PLACEHOLDER_PATTERNS:
        if pat.match(v):
            return False
    # Stripe live secret keys start with ``sk_live_``; test keys
    # ``sk_test_``. Anything else is highly suspicious; but we
    # accept ``sk_test_`` as valid-shape so the probe can verify
    # test-mode keys too.
    if not (v.startswith("sk_live_") or v.startswith("sk_test_")):
        return False
    # Real Stripe keys are 100+ chars; placeholders are short.
    return len(v) >= 32


@router.get("/health/payments")
async def health_payments() -> Dict[str, Any]:
    """Public Stripe key health probe (see module docstring)."""
    raw_live = os.environ.get("STRIPE_SECRET_KEY_LIVE")
    raw_test = os.environ.get("STRIPE_SECRET_KEY_TEST")
    raw_generic = os.environ.get("STRIPE_SECRET_KEY")
    # Preference: LIVE > generic > TEST. If both LIVE + generic are
    # missing/placeholder, fall through to TEST so at least the
    # sandbox probe still runs.
    key = None
    for candidate in (raw_live, raw_generic, raw_test):
        if _key_shape_valid(candidate):
            key = candidate
            break

    key_present = any(_key_present(x)
                       for x in (raw_live, raw_test, raw_generic))
    key_shape_valid = bool(key)

    stripe_api_reachable = False
    if key_shape_valid:
        probe = _stripe_probe_fn or _default_probe
        try:
            # SDK call may block briefly on the network.  Off-load
            # so we don't wedge the event loop.
            await asyncio.to_thread(probe, key)
            stripe_api_reachable = True
        except Exception as exc:                                # noqa: BLE001
            logger.warning("[health/payments] probe failed: %s",
                             exc.__class__.__name__)

    if not key_present:
        status = "unconfigured"
    elif not key_shape_valid:
        status = "unconfigured"
    elif not stripe_api_reachable:
        status = "degraded"
    else:
        status = "ok"

    return {
        "status": status,
        "checks": {
            "key_present":           key_present,
            "key_shape_valid":       key_shape_valid,
            "stripe_api_reachable":  stripe_api_reachable,
        },
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
