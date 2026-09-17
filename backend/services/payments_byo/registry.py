"""Phase I1.7.d · Feb-2026 — Payments-BYO provider registry."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from services.secrets import connection_summary

from .authnet_provider import AuthorizeNetProvider
from .lumino_provider import LuminoProvider
from .models import UnknownPaymentsProvider
from .paypal_provider import PayPalProvider
from .square_provider import SquareProvider
from .stripe_provider import StripeByoProvider
from .tenant_base import PaymentsByoProvider


_PROVIDER_CLASSES: Dict[str, Type[PaymentsByoProvider]] = {
    SquareProvider.provider_key: SquareProvider,
    PayPalProvider.provider_key: PayPalProvider,
    AuthorizeNetProvider.provider_key: AuthorizeNetProvider,
    LuminoProvider.provider_key: LuminoProvider,
    StripeByoProvider.provider_key: StripeByoProvider,
}
_PROVIDER_CACHE: Dict[str, PaymentsByoProvider] = {}
_SHORT_NAME_TO_KEY: Dict[str, str] = {
    "square":   SquareProvider.provider_key,
    "paypal":   PayPalProvider.provider_key,
    "authnet":  AuthorizeNetProvider.provider_key,
    "lumino":   LuminoProvider.provider_key,
    "stripe":   StripeByoProvider.provider_key,
}


def register_payments_byo_provider(key: str, cls: Type[PaymentsByoProvider]) -> None:
    _PROVIDER_CLASSES[key] = cls
    _PROVIDER_CACHE.pop(key, None)


def get_payments_byo_provider(key: str) -> PaymentsByoProvider:
    if key in _PROVIDER_CACHE:
        return _PROVIDER_CACHE[key]
    cls = _PROVIDER_CLASSES.get(key)
    if not cls:
        raise UnknownPaymentsProvider(f"unknown payments-byo provider: {key}")
    inst = cls()
    _PROVIDER_CACHE[key] = inst
    return inst


def get_payments_byo_provider_by_short_name(short: str) -> PaymentsByoProvider:
    key = _SHORT_NAME_TO_KEY.get(short)
    if not key:
        raise UnknownPaymentsProvider(f"unknown payments-byo short-name: {short}")
    return get_payments_byo_provider(key)


def list_registered_payments_byo_provider_keys() -> List[str]:
    return list(_PROVIDER_CLASSES.keys())


def list_short_names() -> List[str]:
    return list(_SHORT_NAME_TO_KEY.keys())


def short_name_for(provider_key: str) -> Optional[str]:
    for short, key in _SHORT_NAME_TO_KEY.items():
        if key == provider_key:
            return short
    return None


def reset_cache_for_tests() -> None:
    _PROVIDER_CACHE.clear()


def get_provider_field_schemas() -> Dict[str, Dict[str, Dict[str, Any]]]:
    return {k: cls.config_fields for k, cls in _PROVIDER_CLASSES.items()}


async def get_tenant_payments_byo_provider(
    tenant_id: str, *, db=None,
) -> Optional[PaymentsByoProvider]:
    """Return the tenant's saved BYO payments provider (if any).

    Returns the first connected row across the registered keys —
    tenants can only have one BYO payments provider active at a time
    (enforced by the /integrations UI, not by DB constraint).
    """
    for key in _PROVIDER_CLASSES.keys():
        summary = await connection_summary(tenant_id, key, db=db)
        if summary and summary.connected:
            return get_payments_byo_provider(key)
    return None
