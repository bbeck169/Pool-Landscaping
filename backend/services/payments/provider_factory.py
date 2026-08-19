"""Task QQ · Feb 2026 · Option-A revert (Feb-2026) — payment-provider
factory.

Historical: this factory once claimed to switch between Stripe and
Lumino. In practice, every customer-facing pay path already calls
``services.payments.stripe_charge`` directly — the factory was only
kept alive to feed two dark modules that ARE Lumino-specific by
design: ``services.lumino_reconciler`` (background reconciler for the
hosted-checkout return flow) and ``routers.lumino_return`` (customer
landing endpoint after a Lumino session). Those two callers still
need a ``LuminoProvider`` instance.

For anything else, the factory now hard-returns Stripe truthfully so
future readers don't inherit the retired "Lumino is the sole
provider" claim. The pay path never invoked this factory anyway.

See ``/app/memory/known_issues.md`` (Option A revert notes) for
Phase 2 context.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from .provider_base import PaymentProvider

log = logging.getLogger("payment_factory")

_PROVIDER: Optional[PaymentProvider] = None


def get_payment_provider() -> PaymentProvider:
    """Return a Lumino provider instance.

    Only ``lumino_reconciler`` and ``lumino_return`` call this — both
    are Lumino-specific by design and need the concrete provider.
    Every customer-facing pay path imports
    ``services.payments.stripe_charge`` directly and never touches
    this factory.
    """
    global _PROVIDER
    if _PROVIDER is not None:
        return _PROVIDER
    # ``PAYMENT_PROVIDER`` env is respected for logs only — the two
    # remaining callers are Lumino by design.
    choice = (os.environ.get("PAYMENT_PROVIDER") or "lumino").strip().lower()
    if choice not in ("lumino", "stripe", ""):
        log.warning("Unknown PAYMENT_PROVIDER=%s — using Lumino", choice)
    from .lumino_provider import LuminoProvider
    _PROVIDER = LuminoProvider()
    log.info("PaymentProvider selected: %s (lumino-specific caller)",
             _PROVIDER.name)
    return _PROVIDER


def reset_provider_cache() -> None:
    """Testing hook — call between tests that mutate env vars."""
    global _PROVIDER
    _PROVIDER = None
