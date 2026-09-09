"""Phase I1.7.e · Chunk 3 · Feb-2026 — ``MAPS_BYO_ENABLED`` reader.

Feature flag that gates the BYO Maps chokepoint rollout. When
``false`` (production default), migrated Maps callsites bypass the
dispatcher and hit the platform vendor path directly — byte-for-byte
identical to pre-Chunk-3 behavior. When ``true`` (preview default),
callsites route through :func:`services.maps.dispatcher.dispatch_maps_*`
so per-tenant BYO keys and monthly caps fire on every real call.

Rollout plan:
    * Preview `.env` → ``MAPS_BYO_ENABLED=true`` (default at ship).
    * Production `.env` → ``MAPS_BYO_ENABLED=false`` (default at ship).
    * Flip prod to ``true`` after preview soak + first-tenant BYO
      opt-in.

Every migrated shim reads this flag on each call so the flip is
zero-downtime (no server restart required).
"""
from __future__ import annotations

import os


def maps_byo_enabled() -> bool:
    """Return True when ``MAPS_BYO_ENABLED`` is set to any truthy
    value. Default False (behavior identical to pre-Chunk-3)."""
    return (
        os.environ.get("MAPS_BYO_ENABLED", "").strip().lower()
        in ("1", "true", "yes")
    )


__all__ = ["maps_byo_enabled"]
