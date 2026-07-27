"""Task QQ · Feb 2026 — payment-provider factory.

Reads ``PAYMENT_PROVIDER`` env var ONCE at module load and caches
the provider instance. Callers should import ``get_payment_provider``
rather than instantiating providers directly.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from .provider_base import PaymentProvider

log = logging.getLogger("payment_factory")

_PROVIDER: Optional[PaymentProvider] = None


def get_payment_provider() -> PaymentProvider:
    global _PROVIDER
    if _PROVIDER is not None:
        return _PROVIDER
    choice = (os.environ.get("PAYMENT_PROVIDER") or "stripe").strip().lower()
    if choice == "lumino":
        from .lumino_provider import LuminoProvider
        _PROVIDER = LuminoProvider()
    else:
        from .stripe_provider import StripeProvider
        _PROVIDER = StripeProvider()
        if choice not in ("stripe", ""):
            log.warning("Unknown PAYMENT_PROVIDER=%s — defaulting to stripe",
                          choice)
    log.info("PaymentProvider selected: %s", _PROVIDER.name)
    return _PROVIDER


def reset_provider_cache() -> None:
    """Testing hook — call between tests that mutate env vars."""
    global _PROVIDER
    _PROVIDER = None
