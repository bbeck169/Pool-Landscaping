"""Phase I1.7.a · Feb-2026 — Tenant payment provider registry.

Single-entry registry for the Stripe Connect provider. Sub-phases
I1.7.d will grow this dict with Square / PayPal / Authorize.net /
Lumino entries.

Public API::

    from services.payments.tenant_registry import (
        get_provider, get_tenant_provider, register_provider,
    )

    stripe_provider = get_provider("stripe")
    # or, look up the tenant's configured payment provider:
    provider = await get_tenant_provider(tenant_id)
    result = await provider.create_charge(tenant_id=tenant_id, ...)

Providers are instantiated lazily so importing this module doesn't
touch the network. Each provider is a singleton per process
(they are stateless — the tenant id is passed on every method
call).
"""
from __future__ import annotations

from typing import Dict, Optional, Type

from .tenant_base import TenantPaymentProvider, UnknownProvider
from .tenant_stripe import PROVIDER_KEY as STRIPE_KEY
from .tenant_stripe import StripeConnectProvider


# ── Registry ─────────────────────────────────────────────────────
_PROVIDER_CLASSES: Dict[str, Type[TenantPaymentProvider]] = {
    STRIPE_KEY: StripeConnectProvider,
}


_PROVIDER_CACHE: Dict[str, TenantPaymentProvider] = {}


def register_provider(key: str, cls: Type[TenantPaymentProvider]) -> None:
    """Register a concrete provider class. I1.7.d will call this for
    Square, PayPal, Authorize.net, Lumino."""
    _PROVIDER_CLASSES[key] = cls
    _PROVIDER_CACHE.pop(key, None)


def get_provider(key: str) -> TenantPaymentProvider:
    """Return a process-wide singleton instance of the named provider.

    Raises ``UnknownProvider`` for unregistered keys.
    """
    if key in _PROVIDER_CACHE:
        return _PROVIDER_CACHE[key]
    cls = _PROVIDER_CLASSES.get(key)
    if not cls:
        raise UnknownProvider(f"unknown provider key: {key}")
    instance = cls()
    _PROVIDER_CACHE[key] = instance
    return instance


async def get_tenant_provider(
    tenant_id: str, *, default: str = STRIPE_KEY, db=None,
) -> TenantPaymentProvider:
    """Look up the tenant's configured payment provider.

    Reads ``tenant.payment_provider`` from the tenants collection
    (falls back to ``default`` when unset — Stripe today).
    """
    if db is None:
        from config import db as _db
        db = _db
    tenant = await db.tenants.find_one({"id": tenant_id}, {"payment_provider": 1})
    key = (tenant or {}).get("payment_provider") or default
    return get_provider(key)


def list_registered_provider_keys() -> list[str]:
    return list(_PROVIDER_CLASSES.keys())


def reset_cache_for_tests() -> None:
    """Clear the singleton cache — needed when a test swaps in a
    fake Stripe SDK client via monkeypatching."""
    _PROVIDER_CACHE.clear()
