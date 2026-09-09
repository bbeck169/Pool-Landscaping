"""Phase I1.7.e · Chunk 3 · Feb-2026 — Maps test-mode helpers.

Sibling of :mod:`services.ai.testmode` and
:mod:`services.messaging.testmode`. Two responsibilities:

1. Provide :func:`is_maps_testmode` alias (re-exports
   :func:`services.maps._helpers.maps_testmode_mock`) so callsites
   can use the same spelling as AI / messaging.
2. Provide deterministic mock envelope factories for every
   dispatcher op (:func:`mock_geocode_result`,
   :func:`mock_route_result`, :func:`mock_reverse_geocode_result`,
   :func:`mock_static_map_url`) so callers can short-circuit BEFORE
   the platform HTTP fetch fires. Same input → same output hash,
   indefinitely — required for pytest snapshot comparisons.
3. **Boot guardrail** — refuses to boot the process when
   ``MAPS_TESTMODE_MOCK=true`` AND ``APP_ENV=production``. Import
   fails fast with ``RuntimeError`` so a misconfigured prod pod
   cannot start silently spilling mock data to real customers.

Enable in preview ``.env`` with::

    MAPS_TESTMODE_MOCK=true
"""
from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, List, Optional, Tuple

from ._helpers import maps_testmode_mock as _maps_testmode_mock
from ._helpers import now_iso
from .models import (
    MapsGeocodeResult,
    MapsRouteLeg,
    MapsRouteResult,
    MapsStaticMapURL,
)


def is_maps_testmode() -> bool:
    """Return True when ``MAPS_TESTMODE_MOCK`` is set to any truthy
    value. Alias for :func:`services.maps._helpers.maps_testmode_mock`
    so both spellings work at callsites."""
    return _maps_testmode_mock()


# ── Boot guardrail ───────────────────────────────────────────────
def _assert_boot_safe() -> None:
    """Raise ``RuntimeError`` when ``MAPS_TESTMODE_MOCK=true`` is set
    in ``APP_ENV=production``. Silent import-time fail-fast so a
    misconfigured prod pod cannot start with mock Maps data enabled."""
    app_env = (os.environ.get("APP_ENV") or "").strip().lower()
    if app_env != "production":
        return
    if not is_maps_testmode():
        return
    raise RuntimeError(
        "Refusing to boot: MAPS_TESTMODE_MOCK=true is forbidden when "
        "APP_ENV=production. Unset MAPS_TESTMODE_MOCK or set it to "
        "'false' in the production .env, then restart."
    )


def _run_boot_guardrail_at_import() -> None:
    """Skip when the process is running under pytest — tests use
    ``monkeypatch.setenv`` to flip ``MAPS_TESTMODE_MOCK`` and would
    otherwise trip the guardrail at collection time (imports happen
    before the fixture teardown restores the env)."""
    if "PYTEST_CURRENT_TEST" in os.environ:
        return
    if "PYTEST_VERSION" in os.environ:  # newer pytest exports this
        return
    # Detect pytest by argv[0] too — belt & suspenders for early
    # imports before pytest exports its env vars.
    import sys as _sys
    argv0 = (_sys.argv[0] if _sys.argv else "") or ""
    if "pytest" in argv0.lower() or argv0.endswith("py.test"):
        return
    _assert_boot_safe()


_run_boot_guardrail_at_import()


# ── Deterministic mock envelope factories ────────────────────────
def _hash_seed(*parts: Any) -> str:
    seed = "||".join(str(p) for p in parts)
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def mock_geocode_result(
    *,
    tenant_id: str,
    address: str,
    provider_key: str = "maps_platform",
    provider_used: str = "platform:testmode_mock",
) -> MapsGeocodeResult:
    """Deterministic forward-geocode mock. Same ``address`` → same
    lat/lng, indefinitely (hash-derived so tests can pin them)."""
    h = _hash_seed(address)
    # Coerce two 6-hex nibbles into pseudo lat/lng inside continental US.
    lat = 25.0 + (int(h[:6], 16) % 2_500_000) / 100_000.0
    lng = -125.0 + (int(h[6:], 16) % 5_800_000) / 100_000.0
    return MapsGeocodeResult(
        address=address,
        lat=round(lat, 6),
        lng=round(lng, 6),
        formatted_address=f"[testmode-mock:{h}] {address}",
        provider_response_id=f"place_testmode_{h}",
        provider_key=provider_key,
        provider_used=provider_used,
        tenant_id=tenant_id,
        raw={"testmode_mock": True, "hash": h, "at": now_iso()},
    )


def mock_reverse_geocode_result(
    *,
    tenant_id: str,
    lat: float,
    lng: float,
    provider_key: str = "maps_platform",
    provider_used: str = "platform:testmode_mock",
) -> MapsGeocodeResult:
    """Deterministic reverse-geocode mock. Uses the same
    :class:`MapsGeocodeResult` envelope so callers switch on the
    op-name at the dispatcher layer, not on the result shape."""
    h = _hash_seed(round(float(lat), 5), round(float(lng), 5))
    return MapsGeocodeResult(
        address=f"[testmode-mock:{h}] reverse lookup",
        lat=round(float(lat), 6),
        lng=round(float(lng), 6),
        formatted_address=f"[testmode-mock:{h}] {round(lat, 4)},{round(lng, 4)}",
        provider_response_id=f"place_testmode_reverse_{h}",
        provider_key=provider_key,
        provider_used=provider_used,
        tenant_id=tenant_id,
        raw={"testmode_mock": True, "reverse": True, "hash": h,
              "at": now_iso()},
    )


def mock_route_result(
    *,
    tenant_id: str,
    origin: Tuple[float, float],
    destinations: List[Tuple[float, float]],
    provider_key: str = "maps_platform",
    provider_used: str = "platform:testmode_mock",
) -> MapsRouteResult:
    """Deterministic route mock. Assigns 1000 m and 60 s per leg —
    zero-distance runs give ``total_distance_m=0`` so callers can
    still assert on empty destinations."""
    h = _hash_seed(origin, tuple(destinations))
    legs = [MapsRouteLeg(distance_m=1000, duration_s=60) for _ in destinations]
    return MapsRouteResult(
        legs=legs,
        total_distance_m=1000 * len(destinations),
        total_duration_s=60 * len(destinations),
        polyline=f"testmode_polyline_{h}",
        ordered_indices=list(range(len(destinations))),
        provider_key=provider_key,
        provider_used=provider_used,
        tenant_id=tenant_id,
        raw={"testmode_mock": True, "hash": h, "at": now_iso()},
    )


def mock_static_map_url(
    *,
    tenant_id: str,
    center: Optional[Tuple[float, float]] = None,
    path: Optional[List[Tuple[float, float]]] = None,
    size: Tuple[int, int] = (600, 400),
    markers: Optional[List[Tuple[float, float]]] = None,
    provider_key: str = "maps_platform",
    provider_used: str = "platform:testmode_mock",
) -> MapsStaticMapURL:
    """Deterministic static-map URL mock."""
    h = _hash_seed(center, tuple(path or ()), size, tuple(markers or ()))
    return MapsStaticMapURL(
        url=f"https://testmode-mock.local/maps/{h}?size={size[0]}x{size[1]}",
        provider_key=provider_key,
        provider_used=provider_used,
        tenant_id=tenant_id,
    )


__all__ = [
    "is_maps_testmode",
    "mock_geocode_result",
    "mock_reverse_geocode_result",
    "mock_route_result",
    "mock_static_map_url",
]
