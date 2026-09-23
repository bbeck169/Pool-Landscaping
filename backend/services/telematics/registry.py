"""Phase P39 · Feb-2026 — Telematics provider registry.

Mirrors ``services.maps.registry`` — key → provider meta, short-name
lookup, field-schema enumeration for the settings UI.

Adding a new provider = drop another ``TelematicsProviderMeta`` into
``_PROVIDERS`` here.  No other file needs to change.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .models import TelematicsProviderMeta, UnknownTelematicsProvider


# ═════════════════════════════════════════════════════════════════
# Canonical keys (imported by tenant_integrations.py + tests)
# ═════════════════════════════════════════════════════════════════
MOJIO_PROVIDER_KEY = "telematics_mojio"
GEOTAB_PROVIDER_KEY = "telematics_geotab"


# ═════════════════════════════════════════════════════════════════
# Provider registry
# ═════════════════════════════════════════════════════════════════
_MOJIO_META = TelematicsProviderMeta(
    provider_key=MOJIO_PROVIDER_KEY,
    short_name="mojio",
    label="Mojio",
    description=(
        "Bring your own Mojio account.  Vehicle location pings arrive "
        "via a signed webhook (HMAC-SHA256 body signature)."
    ),
    config_fields={
        "api_key": {
            "required": True,
            "secret": True,
            "label": "API key",
        },
        "account_id": {
            "required": True,
            "secret": False,
            "label": "Account ID",
        },
        "webhook_secret": {
            "required": True,
            "secret": True,
            "label": "Webhook signing secret",
        },
    },
    primary_secret_field="api_key",
)


_GEOTAB_META = TelematicsProviderMeta(
    provider_key=GEOTAB_PROVIDER_KEY,
    short_name="geotab",
    label="Geotab",
    description=(
        "Bring your own MyGeotab database.  Pings arrive via BOTH a "
        "MyGeotab notification-template webhook (shared secret in "
        "``X-Telematics-Secret``) AND a 60-second JSON-RPC polling "
        "adapter (``DeviceStatusInfo``).  Enable the poller via the "
        "``TELEMATICS_GEOTAB_POLL_ENABLED`` env var."
    ),
    config_fields={
        # MyGeotab uses the ``api_key`` slot to carry either the
        # session id (preferred) or the account password.  The
        # settings UI's helper text should spell this out.
        "api_key": {
            "required": True,
            "secret": True,
            "label": "MyGeotab sessionId or password",
        },
        # MyGeotab database name (e.g. ``"my_pool_co"``).  Maps to the
        # JSON-RPC ``database`` credential field.
        "account_id": {
            "required": True,
            "secret": False,
            "label": "MyGeotab database name",
        },
        "webhook_secret": {
            "required": True,
            "secret": True,
            "label": "Notification-template shared secret",
        },
        # Optional 4th field — MyGeotab supports federated servers.
        # Defaults to the canonical ``my.geotab.com`` when blank.
        "server_url": {
            "required": False,
            "secret": False,
            "label": "MyGeotab server host (default: my.geotab.com)",
        },
    },
    primary_secret_field="api_key",
)


_PROVIDERS: Dict[str, TelematicsProviderMeta] = {
    _MOJIO_META.provider_key: _MOJIO_META,
    _GEOTAB_META.provider_key: _GEOTAB_META,
}

_SHORT_NAME_TO_KEY: Dict[str, str] = {
    _MOJIO_META.short_name: _MOJIO_META.provider_key,
    _GEOTAB_META.short_name: _GEOTAB_META.provider_key,
}


# ═════════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════════
def get_provider(key: str) -> TelematicsProviderMeta:
    meta = _PROVIDERS.get(key)
    if not meta:
        raise UnknownTelematicsProvider(f"unknown telematics provider: {key}")
    return meta


def get_provider_by_short_name(short: str) -> TelematicsProviderMeta:
    key = _SHORT_NAME_TO_KEY.get(short)
    if not key:
        raise UnknownTelematicsProvider(
            f"unknown telematics provider short-name: {short}"
        )
    return get_provider(key)


def list_registered_telematics_provider_keys() -> List[str]:
    return list(_PROVIDERS.keys())


def list_short_names() -> List[str]:
    return list(_SHORT_NAME_TO_KEY.keys())


def short_name_for(provider_key: str) -> Optional[str]:
    meta = _PROVIDERS.get(provider_key)
    return meta.short_name if meta else None


def get_provider_field_schemas() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Return ``{provider_key: config_fields}`` for the settings UI.

    Matches the shape ``services.maps.registry.get_provider_field_schemas``
    returns, so ``routers.tenant_integrations`` can consume both via
    a shared code path.
    """
    return {k: meta.config_fields for k, meta in _PROVIDERS.items()}
