"""Phase I1.7.c.2 · Feb-2026 — Maps provider registry."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from services.secrets import connection_summary

from .google_maps_provider import GoogleMapsProvider
from .mapbox_provider import MapboxProvider
from .models import UnknownMapsProvider
from .tenant_base import MapsProvider


_MAPS_PROVIDER_CLASSES: Dict[str, Type[MapsProvider]] = {
    GoogleMapsProvider.provider_key: GoogleMapsProvider,
    MapboxProvider.provider_key: MapboxProvider,
}
_MAPS_PROVIDER_CACHE: Dict[str, MapsProvider] = {}
_SHORT_NAME_TO_KEY: Dict[str, str] = {
    "google": GoogleMapsProvider.provider_key,
    "mapbox": MapboxProvider.provider_key,
}


def register_maps_provider(key: str, cls: Type[MapsProvider]) -> None:
    _MAPS_PROVIDER_CLASSES[key] = cls
    _MAPS_PROVIDER_CACHE.pop(key, None)


def get_maps_provider(key: str) -> MapsProvider:
    if key in _MAPS_PROVIDER_CACHE:
        return _MAPS_PROVIDER_CACHE[key]
    cls = _MAPS_PROVIDER_CLASSES.get(key)
    if not cls:
        raise UnknownMapsProvider(f"unknown maps provider: {key}")
    inst = cls()
    _MAPS_PROVIDER_CACHE[key] = inst
    return inst


def get_maps_provider_by_short_name(short: str) -> MapsProvider:
    key = _SHORT_NAME_TO_KEY.get(short)
    if not key:
        raise UnknownMapsProvider(f"unknown maps provider short-name: {short}")
    return get_maps_provider(key)


def list_registered_maps_provider_keys() -> List[str]:
    return list(_MAPS_PROVIDER_CLASSES.keys())


def list_short_names() -> List[str]:
    return list(_SHORT_NAME_TO_KEY.keys())


def short_name_for(provider_key: str) -> Optional[str]:
    for short, key in _SHORT_NAME_TO_KEY.items():
        if key == provider_key:
            return short
    return None


async def get_tenant_maps_provider(
    tenant_id: str, *, db=None,
) -> Optional[MapsProvider]:
    """Return the tenant's saved Maps provider (if any). First
    connected wins — Google before Mapbox by registration order."""
    for key in _MAPS_PROVIDER_CLASSES.keys():
        summary = await connection_summary(tenant_id, key, db=db)
        if summary and summary.connected:
            return get_maps_provider(key)
    return None


def reset_cache_for_tests() -> None:
    _MAPS_PROVIDER_CACHE.clear()


def get_provider_field_schemas() -> Dict[str, Dict[str, Dict[str, Any]]]:
    return {k: cls.config_fields for k, cls in _MAPS_PROVIDER_CLASSES.items()}
