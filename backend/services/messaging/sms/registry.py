"""Phase I1.7.b · Feb-2026 — SMS provider registry."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Type

from services.secrets import connection_summary

from ..models import UnknownMessagingProvider
from .base import SmsProvider
from .ringcentral_provider import RingCentralSmsProvider
from .textmagic_provider import TextMagicSmsProvider
from .twilio_provider import TwilioSmsProvider


_SMS_PROVIDER_CLASSES: Dict[str, Type[SmsProvider]] = {
    TwilioSmsProvider.provider_key: TwilioSmsProvider,
    TextMagicSmsProvider.provider_key: TextMagicSmsProvider,
    RingCentralSmsProvider.provider_key: RingCentralSmsProvider,
}
_SMS_PROVIDER_CACHE: Dict[str, SmsProvider] = {}


def register_sms_provider(key: str, cls: Type[SmsProvider]) -> None:
    _SMS_PROVIDER_CLASSES[key] = cls
    _SMS_PROVIDER_CACHE.pop(key, None)


def get_sms_provider(key: str) -> SmsProvider:
    if key in _SMS_PROVIDER_CACHE:
        return _SMS_PROVIDER_CACHE[key]
    cls = _SMS_PROVIDER_CLASSES.get(key)
    if not cls:
        raise UnknownMessagingProvider(f"unknown sms provider: {key}")
    inst = cls()
    _SMS_PROVIDER_CACHE[key] = inst
    return inst


def list_registered_sms_provider_keys() -> List[str]:
    return list(_SMS_PROVIDER_CLASSES.keys())


async def get_tenant_sms_provider(
    tenant_id: str, *, db=None,
) -> Optional[SmsProvider]:
    """Return the tenant's saved SMS provider adapter (if any).

    Looks through ``tenant_secrets`` for the FIRST row whose
    ``provider_key`` is a registered SMS provider. Returns ``None``
    if the tenant hasn't configured any SMS provider — callers
    should fall back to the platform default (see
    ``services.messaging.dispatch.dispatch_sms``).
    """
    for key in _SMS_PROVIDER_CLASSES.keys():
        summary = await connection_summary(tenant_id, key, db=db)
        if summary and summary.connected:
            return get_sms_provider(key)
    return None


def reset_cache_for_tests() -> None:
    _SMS_PROVIDER_CACHE.clear()


def get_provider_field_schemas() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Expose each SMS provider's config-field schema for the settings UI."""
    return {k: cls.config_fields for k, cls in _SMS_PROVIDER_CLASSES.items()}
