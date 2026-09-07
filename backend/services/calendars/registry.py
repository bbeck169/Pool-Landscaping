"""Phase I1.7.c.3 · Feb-2026 — Calendar provider registry."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from .google_calendar_provider import GoogleCalendarProvider
from .models import UnknownCalendarProvider
from .outlook_calendar_provider import OutlookCalendarProvider
from .tenant_base import CalendarProvider


_CAL_PROVIDER_CLASSES: Dict[str, Type[CalendarProvider]] = {
    GoogleCalendarProvider.provider_key: GoogleCalendarProvider,
    OutlookCalendarProvider.provider_key: OutlookCalendarProvider,
}
_CAL_PROVIDER_CACHE: Dict[str, CalendarProvider] = {}
_SHORT_NAME_TO_KEY: Dict[str, str] = {
    "google":  GoogleCalendarProvider.provider_key,
    "outlook": OutlookCalendarProvider.provider_key,
}


def register_calendar_provider(key: str, cls: Type[CalendarProvider]) -> None:
    _CAL_PROVIDER_CLASSES[key] = cls
    _CAL_PROVIDER_CACHE.pop(key, None)


def get_calendar_provider(key: str) -> CalendarProvider:
    if key in _CAL_PROVIDER_CACHE:
        return _CAL_PROVIDER_CACHE[key]
    cls = _CAL_PROVIDER_CLASSES.get(key)
    if not cls:
        raise UnknownCalendarProvider(f"unknown calendar provider: {key}")
    inst = cls()
    _CAL_PROVIDER_CACHE[key] = inst
    return inst


def get_calendar_provider_by_short_name(short: str) -> CalendarProvider:
    key = _SHORT_NAME_TO_KEY.get(short)
    if not key:
        raise UnknownCalendarProvider(f"unknown calendar provider short-name: {short}")
    return get_calendar_provider(key)


def list_registered_calendar_provider_keys() -> List[str]:
    return list(_CAL_PROVIDER_CLASSES.keys())


def list_short_names() -> List[str]:
    return list(_SHORT_NAME_TO_KEY.keys())


def short_name_for(provider_key: str) -> Optional[str]:
    for short, key in _SHORT_NAME_TO_KEY.items():
        if key == provider_key:
            return short
    return None


def reset_cache_for_tests() -> None:
    _CAL_PROVIDER_CACHE.clear()


def get_provider_field_schemas() -> Dict[str, Dict[str, Dict[str, Any]]]:
    return {k: cls.config_fields for k, cls in _CAL_PROVIDER_CLASSES.items()}
