"""Phase P39 · Feb-2026 — Telematics models + exceptions."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# ═════════════════════════════════════════════════════════════════
# Exceptions
# ═════════════════════════════════════════════════════════════════
class TelematicsError(Exception):
    """Base error class for the telematics module."""


class UnknownTelematicsProvider(TelematicsError):
    """Raised when a provider key doesn't map to a registered provider."""


class InvalidTelematicsProviderConfig(TelematicsError):
    """Raised when the saved provider config is missing a required field."""


# ═════════════════════════════════════════════════════════════════
# Provider metadata container
# ═════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class TelematicsProviderMeta:
    """Immutable descriptor for a telematics provider.

    Attributes
    ----------
    provider_key:
        Canonical key used everywhere (``tenant_secrets.provider_key``,
        route paths, config_fields lookup).  Prefixed with
        ``telematics_`` so it never collides with a maps/AI/SMS key.
    short_name:
        Slug used in webhook URLs + logs (``"mojio"``, ``"geotab"``).
    label:
        Human-readable display name for the settings UI.
    description:
        One-liner shown under the label in the settings card.
    config_fields:
        ``{name: {"required": bool, "secret": bool, "label": str}}``
        matching the shape read by
        ``routers.tenant_integrations._to_field_entries``.
    primary_secret_field:
        The field whose last-4 chars appear in the connection summary
        (never the whole value).  See ``services.secrets.put_secret``.
    """

    provider_key: str
    short_name: str
    label: str
    description: str
    config_fields: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    primary_secret_field: Optional[str] = None
