"""C2 · Feb-2026 — OpenWeather adapter + /weather/openweather/current tests.

Coverage:
    Adapter unit tests (in-process, ``httpx.MockTransport``):
        1. ``current_by_coords`` happy path — snapshot shape + F range sanity.
        2. ``current_by_address`` happy path — geocode → current, echoes resolved.
        3. Wind cardinal boundaries at 0/45/90/135/180/225/270/315/359.9°.
        4. 401 → ``WeatherConfigError``.
        5. 429 → ``WeatherRateLimitError``.
        6. Transport timeout → ``WeatherServiceUnavailable``.
        7. Geocode 0 results → ``WeatherAddressNotFoundError``.
        8. Cache hit within TTL → mock hit count stays at 1.
        9. Cache miss after TTL expiry (freezegun) → hit count increments.
        10. Cache-key normalization — trims + lowercases + collapses whitespace.

    Endpoint tests (in-process ASGI + ``dependency_overrides``):
        11. ``GET /api/weather/openweather/current?address=X`` → 200 (tech).
        12. No params → 422.
        13. Both forms → 422 (mutually exclusive).
        14. Partial coords (only ``lat``) → 422.
        15. Customer role → 403.
        16. Missing ``OPENWEATHER_API_KEY`` env → 500 with WEATHER_CONFIG_ERROR.
        17. Regression guard: our router does NOT register /weather/current.

No real OpenWeather HTTP calls. No real API keys committed.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, List, Tuple

import httpx
import pytest
from freezegun import freeze_time

from services.weather.openweather_adapter import (
    OpenWeatherAdapter,
    WeatherAddressNotFoundError,
    WeatherConfigError,
    WeatherRateLimitError,
    WeatherServiceUnavailable,
    WeatherSnapshot,
    _deg_to_cardinal,
    _normalize_address,
)


# ═════════════════════════════════════════════════════════════════════
# Anyio backend fixture (project convention — asyncio only).
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


# ═════════════════════════════════════════════════════════════════════
# Test fixtures — mock transport factory.
# ═════════════════════════════════════════════════════════════════════
def _current_payload(
    *,
    temp_f: float = 72.5,
    humidity: int = 58,
    wind_speed: float = 6.4,
    wind_deg: float = 180.0,
    main: str = "Clear",
) -> dict:
    return {
        "weather": [{"main": main, "description": main.lower()}],
        "main": {"temp": temp_f, "humidity": humidity},
        "wind": {"speed": wind_speed, "deg": wind_deg},
        "coord": {"lat": 30.2672, "lon": -97.7431},
        "dt": 1700000000,
    }


def _geocode_payload(
    *,
    lat: float = 30.2672,
    lon: float = -97.7431,
    name: str = "Austin",
    state: str = "Texas",
    country: str = "US",
) -> list:
    return [
        {"name": name, "state": state, "country": country,
         "lat": lat, "lon": lon}
    ]


def _make_handler(
    responses: List[Tuple[str, Any, int]],
    call_log: List[str],
) -> Callable[[httpx.Request], httpx.Response]:
    """Build a MockTransport handler.

    Each ``responses`` entry is ``(url_substring, payload, status_code)``.
    The first entry whose substring appears in the request URL is
    returned. Missing routes raise so the test fails loudly.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        call_log.append(str(request.url))
        url = str(request.url)
        for substr, payload, status in responses:
            if substr in url:
                return httpx.Response(status, json=payload)
        raise AssertionError(f"Unhandled request in mock: {url}")
    return handler


def _adapter_with_mock(
    responses: List[Tuple[str, Any, int]],
    *,
    cache_ttl_s: int = 600,
) -> Tuple[OpenWeatherAdapter, List[str]]:
    call_log: List[str] = []
    transport = httpx.MockTransport(_make_handler(responses, call_log))
    client = httpx.AsyncClient(transport=transport)
    adapter = OpenWeatherAdapter(
        api_key="test-key",
        http_client=client,
        cache_ttl_s=cache_ttl_s,
    )
    return adapter, call_log


# ═════════════════════════════════════════════════════════════════════
# 1. current_by_coords — happy path
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_current_by_coords_happy_path():
    adapter, calls = _adapter_with_mock([
        ("/data/2.5/weather", _current_payload(
            temp_f=68.2, humidity=52, wind_speed=5.7, wind_deg=180.0,
            main="Clear",
        ), 200),
    ])
    snap = await adapter.current_by_coords(30.2672, -97.7431)

    assert isinstance(snap, WeatherSnapshot)
    assert snap.temp_f == 68.2
    assert snap.humidity_pct == 52.0
    assert snap.wind_mph == 5.7
    assert snap.wind_direction == "S"   # 180° → S
    assert snap.conditions == "Clear"
    assert snap.source == "openweather"
    assert snap.lat == 30.2672
    assert snap.lon == -97.7431
    assert snap.resolved_address is None
    # Sanity: -50°F to 150°F covers all inhabited Earth.
    assert -50 <= snap.temp_f <= 150
    assert 0 <= snap.humidity_pct <= 100
    assert len(calls) == 1
    assert "units=imperial" in calls[0]
    assert "appid=test-key" in calls[0]


# ═════════════════════════════════════════════════════════════════════
# 2. current_by_address — geocode → current
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_current_by_address_happy_path():
    adapter, calls = _adapter_with_mock([
        # Geocode substring matched first — order matters in _make_handler.
        ("/geo/1.0/direct", _geocode_payload(
            lat=30.2672, lon=-97.7431,
            name="Austin", state="Texas", country="US",
        ), 200),
        ("/data/2.5/weather", _current_payload(main="Rain"), 200),
    ])
    snap = await adapter.current_by_address("123 Main St, Austin TX")

    assert snap.conditions == "Rain"
    assert snap.resolved_address == "Austin, Texas, US"
    assert snap.lat == 30.2672
    assert snap.lon == -97.7431
    # Two upstream calls: geocode + current.
    assert len(calls) == 2
    assert "/geo/1.0/direct" in calls[0]
    assert "/data/2.5/weather" in calls[1]


# ═════════════════════════════════════════════════════════════════════
# 3. Wind cardinal boundaries
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("deg,expected", [
    (0.0,   "N"),
    (22.4,  "N"),
    (22.5,  "NE"),
    (45.0,  "NE"),
    (67.4,  "NE"),
    (67.5,  "E"),
    (90.0,  "E"),
    (135.0, "SE"),
    (180.0, "S"),
    (225.0, "SW"),
    (270.0, "W"),
    (315.0, "NW"),
    (337.4, "NW"),
    (337.5, "N"),
    (359.9, "N"),
    (360.0, "N"),   # defensive: wrap
    (720.5, "N"),   # defensive: multiple wraps
])
def test_deg_to_cardinal_wheel(deg: float, expected: str):
    assert _deg_to_cardinal(deg) == expected


# ═════════════════════════════════════════════════════════════════════
# 4-6. Error taxonomy
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_401_raises_config_error():
    adapter, _ = _adapter_with_mock([
        ("/data/2.5/weather", {"cod": 401, "message": "Invalid API key"}, 401),
    ])
    with pytest.raises(WeatherConfigError) as exc:
        await adapter.current_by_coords(1.0, 2.0)
    assert "OPENWEATHER_API_KEY" in str(exc.value)


@pytest.mark.anyio
async def test_429_raises_rate_limit_error():
    adapter, _ = _adapter_with_mock([
        ("/data/2.5/weather", {"cod": 429}, 429),
    ])
    with pytest.raises(WeatherRateLimitError):
        await adapter.current_by_coords(1.0, 2.0)


@pytest.mark.anyio
async def test_transport_timeout_raises_service_unavailable():
    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout")
    transport = httpx.MockTransport(handler)
    adapter = OpenWeatherAdapter(
        api_key="k", http_client=httpx.AsyncClient(transport=transport),
    )
    with pytest.raises(WeatherServiceUnavailable) as exc:
        await adapter.current_by_coords(1.0, 2.0)
    assert "transport" in str(exc.value).lower()


# ═════════════════════════════════════════════════════════════════════
# 7. Geocode 0 results
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_geocode_zero_results_raises_address_not_found():
    adapter, _ = _adapter_with_mock([
        ("/geo/1.0/direct", [], 200),
    ])
    with pytest.raises(WeatherAddressNotFoundError) as exc:
        await adapter.current_by_address("Nowhere St, Nullville")
    assert "0 results" in str(exc.value)


# ═════════════════════════════════════════════════════════════════════
# 8. Cache hit within TTL
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_cache_hit_within_ttl_avoids_upstream_call():
    adapter, calls = _adapter_with_mock([
        ("/data/2.5/weather", _current_payload(), 200),
    ], cache_ttl_s=600)

    first = await adapter.current_by_coords(30.2672, -97.7431)
    second = await adapter.current_by_coords(30.2672, -97.7431)

    assert first.temp_f == second.temp_f
    assert len(calls) == 1, (
        "Second lookup within TTL must be served from cache; "
        f"got {len(calls)} upstream calls"
    )


# ═════════════════════════════════════════════════════════════════════
# 9. Cache miss after TTL expiry
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_cache_miss_after_ttl_expiry_hits_upstream_again():
    adapter, calls = _adapter_with_mock([
        ("/data/2.5/weather", _current_payload(), 200),
    ], cache_ttl_s=60)

    start = datetime(2026, 2, 15, 12, 0, 0, tzinfo=timezone.utc)
    with freeze_time(start) as clock:
        await adapter.current_by_coords(30.2672, -97.7431)
        assert len(calls) == 1
        # Advance clock past TTL.
        clock.move_to(start + timedelta(seconds=61))
        await adapter.current_by_coords(30.2672, -97.7431)
    assert len(calls) == 2, (
        "Lookup after TTL expiry must hit upstream again; "
        f"got {len(calls)} upstream calls"
    )


# ═════════════════════════════════════════════════════════════════════
# 10. Cache-key normalization
# ═════════════════════════════════════════════════════════════════════
def test_normalize_address_lowercases_strips_and_collapses_whitespace():
    assert _normalize_address("123 Main St") == "123 main st"
    assert _normalize_address("  123 main st  ") == "123 main st"
    assert _normalize_address("123 MAIN ST") == "123 main st"
    assert _normalize_address("123  main\tst") == "123 main st"
    assert _normalize_address("123\n main st ") == "123 main st"


@pytest.mark.anyio
async def test_cache_key_address_normalization_shares_one_slot():
    adapter, calls = _adapter_with_mock([
        ("/geo/1.0/direct", _geocode_payload(), 200),
        ("/data/2.5/weather", _current_payload(), 200),
    ])
    await adapter.current_by_address("123 Main St")
    await adapter.current_by_address("  123 MAIN st  ")
    await adapter.current_by_address("123\tmain\nst")
    # Only the first should hit upstream (geocode + current = 2 calls).
    assert len(calls) == 2, (
        f"Address variants must share a cache slot; got {len(calls)} calls"
    )


# ═════════════════════════════════════════════════════════════════════
# ── Endpoint tests (in-process ASGI) ────────────────────────────────
# ═════════════════════════════════════════════════════════════════════
from httpx import ASGITransport, AsyncClient  # noqa: E402  (post-adapter imports)

from server import app  # noqa: E402
from routers.pool_calculators import require_tech_or_above  # noqa: E402
from routers.weather_openweather import get_openweather_adapter  # noqa: E402


def _fake_tech_user() -> dict:
    return {"id": "test-tech", "email": "mike@aquaterra.com",
            "role": "technician", "name": "Test Tech",
            "tenant_id": "test-tenant"}


class _FixedAdapter:
    """Stand-in adapter injected via ``dependency_overrides``.

    Bypasses HTTP entirely — the C2 endpoint's job is param validation
    + error-code mapping, not upstream fidelity (that's the adapter
    suite above).
    """
    def __init__(self, *, raise_exc: Exception | None = None):
        self._raise = raise_exc

    async def current_by_coords(self, lat, lon, *, _resolved_address=None):
        if self._raise is not None:
            raise self._raise
        return WeatherSnapshot(
            temp_f=70.0, humidity_pct=50.0, wind_mph=5.0,
            wind_direction="N", conditions="Clear",
            fetched_at=datetime.now(timezone.utc),
            lat=lat, lon=lon,
            resolved_address=_resolved_address,
        )

    async def current_by_address(self, address):
        if self._raise is not None:
            raise self._raise
        return WeatherSnapshot(
            temp_f=70.0, humidity_pct=50.0, wind_mph=5.0,
            wind_direction="N", conditions="Clear",
            fetched_at=datetime.now(timezone.utc),
            lat=30.0, lon=-97.0,
            resolved_address=address,
        )


@pytest.fixture
def override_adapter():
    """Yields a setter; auto-cleans on teardown."""
    stack: list = []

    def _set(adapter):
        app.dependency_overrides[get_openweather_adapter] = lambda: adapter
        stack.append(adapter)

    yield _set

    app.dependency_overrides.pop(get_openweather_adapter, None)


@pytest.fixture
def override_tech_user():
    def _set(user_dict):
        app.dependency_overrides[require_tech_or_above] = lambda: user_dict
    yield _set
    app.dependency_overrides.pop(require_tech_or_above, None)


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app),
                       base_url="http://test")


# ═════════════════════════════════════════════════════════════════════
# 11. Address form happy path
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_endpoint_address_form_returns_200_tech(
    override_adapter, override_tech_user,
):
    override_adapter(_FixedAdapter())
    override_tech_user(_fake_tech_user())
    async with await _client() as c:
        r = await c.get("/api/weather/openweather/current",
                        params={"address": "123 Main St, Austin TX"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "openweather"
    assert body["resolved_address"] == "123 Main St, Austin TX"
    assert body["conditions"] == "Clear"


# ═════════════════════════════════════════════════════════════════════
# 12-14. Query-param validation
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_endpoint_no_params_returns_422(
    override_adapter, override_tech_user,
):
    override_adapter(_FixedAdapter())
    override_tech_user(_fake_tech_user())
    async with await _client() as c:
        r = await c.get("/api/weather/openweather/current")
    assert r.status_code == 422, r.text


@pytest.mark.anyio
async def test_endpoint_both_forms_returns_422(
    override_adapter, override_tech_user,
):
    override_adapter(_FixedAdapter())
    override_tech_user(_fake_tech_user())
    async with await _client() as c:
        r = await c.get("/api/weather/openweather/current",
                        params={"address": "X", "lat": 1.0, "lon": 2.0})
    assert r.status_code == 422, r.text


@pytest.mark.anyio
async def test_endpoint_partial_coords_returns_422(
    override_adapter, override_tech_user,
):
    override_adapter(_FixedAdapter())
    override_tech_user(_fake_tech_user())
    async with await _client() as c:
        r = await c.get("/api/weather/openweather/current",
                        params={"lat": 1.0})  # missing lon
    assert r.status_code == 422, r.text


# ═════════════════════════════════════════════════════════════════════
# 15. Customer role is denied (real auth dep, no override)
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_endpoint_customer_role_denied(override_adapter):
    """Verify the *real* ``require_tech_or_above`` blocks non-tech callers.

    Uses the real dep (no user override); overrides only the adapter.
    A caller with ``role="customer"`` must be rejected with 403 before
    the handler runs, so the adapter is never invoked.
    """
    override_adapter(_FixedAdapter())
    # Simulate the customer by overriding get_current_user (which
    # require_tech_or_above depends on).
    from utils import get_current_user

    def _fake_customer():
        return {"id": "cust-1", "email": "customer@aquaterra.com",
                "role": "customer", "name": "Test Customer",
                "tenant_id": "test-tenant"}

    app.dependency_overrides[get_current_user] = _fake_customer
    try:
        async with await _client() as c:
            r = await c.get("/api/weather/openweather/current",
                            params={"address": "X"})
        assert r.status_code == 403, r.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ═════════════════════════════════════════════════════════════════════
# 16. Missing OPENWEATHER_API_KEY → 500 with WEATHER_CONFIG_ERROR
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_endpoint_missing_api_key_returns_500_config_error(
    override_tech_user, monkeypatch,
):
    """When the env var is missing, the endpoint MUST NOT crash — it
    must return HTTP 500 with a machine-readable ``WEATHER_CONFIG_ERROR``
    code so the C4 UI can surface a targeted setup message.
    """
    # Clear any cached singleton and env var.
    import routers.weather_openweather as mod
    monkeypatch.setattr(mod, "_ADAPTER", None)
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    override_tech_user(_fake_tech_user())

    async with await _client() as c:
        r = await c.get("/api/weather/openweather/current",
                        params={"address": "X"})
    assert r.status_code == 500, r.text
    body = r.json()
    # FastAPI wraps our dict in ``{"detail": ...}``.
    detail = body.get("detail") or {}
    assert detail.get("code") == "WEATHER_CONFIG_ERROR", body


# ═════════════════════════════════════════════════════════════════════
# 17. Regression guard: this router does not shadow /weather/current
# ═════════════════════════════════════════════════════════════════════
def test_openweather_router_does_not_shadow_nws_current():
    """The C2 endpoint must live at /weather/openweather/current so
    it never collides with the NWS-backed widget at /weather/current
    (owned by ``routers/weather_v2.py``).
    """
    from routers import weather_openweather

    all_paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/weather/openweather/current" in all_paths, (
        "Expected /api/weather/openweather/current to be registered"
    )

    ow_module_name = weather_openweather.__name__
    ow_routes = []
    for r in app.routes:
        endpoint = getattr(r, "endpoint", None)
        if endpoint is None:
            continue
        mod = getattr(endpoint, "__module__", "")
        if mod == ow_module_name:
            ow_routes.append(r.path)

    # Every route this router owns MUST be under the /openweather/ ns.
    for path in ow_routes:
        assert path != "/api/weather/current", (
            f"Router {ow_module_name} must NOT shadow /weather/current "
            f"(owned by weather_v2.py NWS widget). Found: {path}"
        )
        assert "openweather" in path, (
            f"Router {ow_module_name} route {path!r} must contain "
            "'openweather' to avoid future path collisions."
        )
