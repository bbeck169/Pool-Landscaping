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
    # Phase LZ4 · Feb 2026 — Stripe SDK retired. Lumino is now the
    # only concrete provider; ``PAYMENT_PROVIDER`` is honoured only
    # to preserve backward compatibility with any script / test that
    # still reads it, but every value maps to Lumino.
    choice = (os.environ.get("PAYMENT_PROVIDER") or "lumino").strip().lower()
    if choice not in ("lumino", "stripe", ""):
        log.warning("Unknown PAYMENT_PROVIDER=%s — using Lumino", choice)
    if choice == "stripe":
        log.warning(
            "PAYMENT_PROVIDER=stripe is retired (Phase LZ4); Lumino "
            "is now the sole provider — using LuminoProvider anyway."
        )
    from .lumino_provider import LuminoProvider
    _PROVIDER = LuminoProvider()
    log.info("PaymentProvider selected: %s", _PROVIDER.name)
    return _PROVIDER


def reset_provider_cache() -> None:
    """Testing hook — call between tests that mutate env vars."""
    global _PROVIDER
    _PROVIDER = None
