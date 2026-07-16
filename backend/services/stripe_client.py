"""Stripe SDK bootstrap.

Reads `STRIPE_SECRET_KEY` from the environment on first import. Never
hardcodes a key. Never logs the key value. Callers should import
`stripe_client.get_stripe()` and use the returned module handle.

Phase 52 · added purely to accept the key + expose a healthcheck so the
frontend can render a "Stripe: configured" banner. No live API calls
are made here. The actual Stripe surface (checkout / elements /
subscriptions) will be wired up in a follow-up phase once the product
decision is made.
"""
from __future__ import annotations

import os
from typing import Optional

import stripe  # SDK is already in requirements.txt

_INITIALIZED = False


def _mode_from_key(key: Optional[str]) -> str:
    if not key:
        return "none"
    if key.startswith("sk_live_"):
        return "live"
    if key.startswith("sk_test_"):
        return "test"
    return "unknown"


def get_stripe():
    """Lazy-init Stripe SDK with the current env key and return the
    module handle. Never echoes the key."""
    global _INITIALIZED
    key = os.getenv("STRIPE_SECRET_KEY") or ""
    stripe.api_key = key or None
    if not _INITIALIZED and key:
        # One-time boot log — never includes the key value or last 4.
        try:
            from config import logger
            logger.info("stripe key configured: true")
            logger.info(f"stripe mode: {_mode_from_key(key)}")
        except Exception:
            pass
        _INITIALIZED = True
    return stripe


def is_configured() -> bool:
    return bool(os.getenv("STRIPE_SECRET_KEY"))


def mode() -> str:
    return _mode_from_key(os.getenv("STRIPE_SECRET_KEY"))
