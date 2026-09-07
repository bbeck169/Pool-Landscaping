"""Phase I1.7.c.2 · Feb-2026 — Maps provider abstract base class.

Every operation returns a normalised Pydantic model so callers never
switch on the concrete provider. Adapters read tenant secrets via
``services.secrets`` — plaintext never crosses the encryption
boundary.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    ConnectionHealth,
    MapsGeocodeResult,
    MapsRouteResult,
    MapsStaticMapURL,
)


class MapsProvider(ABC):
    """Tenant-scoped Maps provider contract."""

    provider_key: str = "abstract_maps"
    #: Short name used in ``tenant_maps_usage.provider`` + the
    #: ``/usage`` response — e.g. ``"google"``, ``"mapbox"``.
    short_name: str = "abstract"

    config_fields: Dict[str, Dict[str, Any]] = {}
    primary_secret_field: Optional[str] = None

    @abstractmethod
    async def geocode(
        self, *, tenant_id: str, address: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> MapsGeocodeResult:
        raise NotImplementedError

    @abstractmethod
    async def route(
        self, *, tenant_id: str,
        origin: Tuple[float, float],
        destinations: List[Tuple[float, float]],
        options: Optional[Dict[str, Any]] = None,
    ) -> MapsRouteResult:
        raise NotImplementedError

    @abstractmethod
    async def static_map_url(
        self, *, tenant_id: str,
        center: Optional[Tuple[float, float]] = None,
        path: Optional[List[Tuple[float, float]]] = None,
        size: Tuple[int, int] = (600, 400),
        markers: Optional[List[Tuple[float, float]]] = None,
    ) -> MapsStaticMapURL:
        raise NotImplementedError

    @abstractmethod
    async def test_connection(
        self, *, tenant_id: str,
    ) -> ConnectionHealth:
        raise NotImplementedError
