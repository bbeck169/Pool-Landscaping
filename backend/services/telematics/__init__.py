"""Phase P39 · Feb-2026 — Telematics BYO service module.

Wires Mojio (webhook) + Geotab (webhook + polling adapter) into the
existing tenant-integrations registry.  Every provider is API-key +
webhook-shared-secret; there's no OAuth flow.

Public surface:
  * :class:`TelematicsProviderMeta` — Pydantic-ish container matching
    the shape ``services.maps`` uses for a provider.
  * :func:`get_provider` — key → provider meta.
  * :func:`list_registered_telematics_provider_keys` — enumeration.
  * :func:`get_provider_field_schemas` — key → config_fields dict
    (schema returned by the settings UI).
  * :func:`short_name_for` — key → short slug ("mojio"/"geotab") used
    in URLs + logs.
"""
from __future__ import annotations

from .models import (
    InvalidTelematicsProviderConfig,
    UnknownTelematicsProvider,
    TelematicsProviderMeta,
)
from .registry import (
    MOJIO_PROVIDER_KEY,
    GEOTAB_PROVIDER_KEY,
    get_provider,
    get_provider_by_short_name,
    list_registered_telematics_provider_keys,
    list_short_names,
    short_name_for,
    get_provider_field_schemas,
)

__all__ = [
    "InvalidTelematicsProviderConfig",
    "UnknownTelematicsProvider",
    "TelematicsProviderMeta",
    "MOJIO_PROVIDER_KEY",
    "GEOTAB_PROVIDER_KEY",
    "get_provider",
    "get_provider_by_short_name",
    "list_registered_telematics_provider_keys",
    "list_short_names",
    "short_name_for",
    "get_provider_field_schemas",
]
