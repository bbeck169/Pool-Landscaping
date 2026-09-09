"""Phase I1.7.c.2 · Feb-2026 — Shared Maps-BYO models.

Mirrors ``services.ai.models`` — everything here is JSON-serialisable
and MUST NOT contain any secret material. The public shape is stable
across Google Maps and Mapbox so callers never switch on
``provider_key``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Operation results ────────────────────────────────────────────
class MapsGeocodeResult(BaseModel):
    """Normalized geocode return-shape from every Maps provider."""

    address: str
    lat: float
    lng: float
    formatted_address: Optional[str] = None
    provider_response_id: Optional[str] = None
    provider_key: str            # "maps_google" | "maps_mapbox" | "maps_platform"
    provider_used: str           # "tenant:google" | "platform:google" | ...
    tenant_id: str
    raw: Dict[str, Any] = Field(default_factory=dict)


class MapsRouteLeg(BaseModel):
    distance_m: int = 0
    duration_s: int = 0
    start_address: Optional[str] = None
    end_address: Optional[str] = None


class MapsRouteResult(BaseModel):
    legs: List[MapsRouteLeg] = Field(default_factory=list)
    total_distance_m: int = 0
    total_duration_s: int = 0
    polyline: Optional[str] = None
    ordered_indices: List[int] = Field(default_factory=list)
    provider_key: str
    provider_used: str
    tenant_id: str
    raw: Dict[str, Any] = Field(default_factory=dict)


class MapsStaticMapURL(BaseModel):
    url: str
    provider_key: str
    provider_used: str
    tenant_id: str


# ── Usage snapshot returned by /maps/usage ───────────────────────
class MapsProviderUsage(BaseModel):
    provider: str                # "google" | "mapbox"
    period_yyyymm: str
    geocode: int = 0
    reverse_geocode: int = 0     # Chunk 3, Feb-2026 — Mapbox reverse-geocode op
    route: int = 0
    static_map: int = 0
    total: int = 0
    monthly_request_cap: Optional[int] = None    # None = unlimited
    connected: bool = False
    pct_used: Optional[float] = None
    status: str = "ok"                          # "ok" | "warn" | "blocked"


class MapsUsageResponse(BaseModel):
    tenant_id: str
    period_yyyymm: str
    providers: List[MapsProviderUsage]


# ── Health ───────────────────────────────────────────────────────
class ConnectionHealth(BaseModel):
    provider_key: str
    tenant_id: str
    ok: bool
    connected_account_id_masked: Optional[str] = None
    message: str = ""
    checked_at: str


# ── Errors ───────────────────────────────────────────────────────
class MapsError(Exception):
    pass


class TenantMapsNotConnected(MapsError):
    """No BYO row + platform fallback disabled."""


class UnknownMapsProvider(MapsError):
    """Provider key not registered."""


class InvalidMapsProviderConfig(MapsError):
    """Missing / blank required config field at save-time."""


class TenantMapsRequestCapExceeded(MapsError):
    """Tenant's monthly request cap has been reached — MUST be
    surfaced as HTTP 429 with NO platform fallback."""

    def __init__(self, provider: str, cap: int, used: int) -> None:
        super().__init__(
            f"tenant Maps request cap reached for provider={provider}: "
            f"used={used}/{cap} requests this month"
        )
        self.provider = provider
        self.cap = cap
        self.used = used


# ── Operation enum-ish ───────────────────────────────────────────
# Chunk 3, Feb-2026 — added ``reverse_geocode`` as its own op with a
# dedicated cap key. Mapbox is the platform reverse-geocode provider
# today; BYO adapters may back it with Google or Mapbox.
OPERATIONS = ("geocode", "reverse_geocode", "route", "static_map")
