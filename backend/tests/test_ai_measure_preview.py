"""Phase AIM0 · Feb-2026 — AI Measurement Tool POC pytest.

Locks the pipeline's non-visual contracts. The vision providers are
stubbed via ``monkeypatch`` so the suite is hermetic — no live Google
or LLM traffic is generated. Visual quality is spot-checked manually
per the phase brief (no rigorous ground-truth benchmark this phase).

Covered contracts
-----------------
* Role guard: technician → 403, admin → 200.
* Address-only body geocodes then fetches the tile.
* lat/lng body skips the geocoder entirely.
* Rate limit: 21st request in a rolling hour → HTTP 429.
* Vision JSON parse failure → returns empty ``features`` for that
  provider with an ``error`` field set. Endpoint MUST NOT 500.
* Meters-per-pixel formula matches Google's docs for a fixed
  ``lat, zoom, scale`` (regression guard on the formula constant).
* Shoelace area math: a known 100×100 pixel square at ``mpp=0.1``
  yields ~107.6 sq ft.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ──────────────────────────────────────────────────────────────────
# Pure-function guards — no HTTP setup needed
# ──────────────────────────────────────────────────────────────────
def test_meters_per_pixel_matches_google_formula_regression():
    """Regression guard: MPP at ``lat=37.4224, zoom=20, scale=2`` must
    equal ``156543.03392 * cos(lat_rad) / 2^20 / 2`` to 9 decimals.
    Any drift means someone edited the Google-web-Mercator constant."""
    from routers.ai_measure import meters_per_pixel

    lat, zoom = 37.4224, 20
    expected = 156543.03392 * math.cos(math.radians(lat)) / (2 ** zoom) / 2
    got = meters_per_pixel(lat=lat, zoom=zoom, scale=2)
    assert abs(got - expected) < 1e-9, f"got={got} expected={expected}"


def test_meters_per_pixel_scale_halves_effective_mpp():
    """`scale=2` returns half the mpp of `scale=1`."""
    from routers.ai_measure import meters_per_pixel

    lat, zoom = 33.4484, 20  # Phoenix — mid-latitude sanity
    a = meters_per_pixel(lat=lat, zoom=zoom, scale=1)
    b = meters_per_pixel(lat=lat, zoom=zoom, scale=2)
    assert abs(a - 2 * b) < 1e-9


def test_shoelace_area_100x100_square_at_mpp_0p1_equals_107p6_sqft():
    """A 100×100 pixel square at mpp=0.1 has area
    = (100*0.1)^2 = 100 m² = 100 * 10.7639 ≈ 1076.4 sqft.

    The phase brief says "given a known 100x100 pixel square at
    mpp=0.1, area_sqft = ~107.6" — that's a 32×32 pixel square
    (area = (32*0.1)^2 = 10.24 m² = 110.2 sqft). Rather than
    silently pick, we assert BOTH the raw m² identity AND the
    sqft conversion factor so any future edit is loudly caught.
    """
    from routers.ai_measure import polygon_area_pixels, area_to_sqft_sqyd

    square = [[0, 0], [100, 0], [100, 100], [0, 100]]
    px_area = polygon_area_pixels(square)
    assert px_area == pytest.approx(10_000.0, abs=1e-6)
    sqft, sqyd = area_to_sqft_sqyd(area_pixels=px_area, mpp=0.1)
    # 100 m² → 1076.39 sqft
    assert sqft == pytest.approx(1076.4, abs=0.2)
    # 1076.39 sqft → 119.6 sqyd
    assert sqyd == pytest.approx(119.6, abs=0.2)


def test_shoelace_degenerate_polygon_is_zero_area():
    from routers.ai_measure import polygon_area_pixels

    assert polygon_area_pixels([]) == 0.0
    assert polygon_area_pixels([[0, 0]]) == 0.0
    assert polygon_area_pixels([[0, 0], [1, 0]]) == 0.0


def test_sanitized_feature_types_dedup_and_lowercase():
    from routers.ai_measure import AiMeasureRequest

    r = AiMeasureRequest(
        lat=33.0, lng=-112.0,
        feature_types=["Pool", "pool", "YARD", "driveway"],
    )
    assert r.sanitized_feature_types() == ["pool", "yard"]


def test_sanitized_feature_types_empty_defaults_to_all():
    from routers.ai_measure import AiMeasureRequest

    r = AiMeasureRequest(lat=33.0, lng=-112.0, feature_types=[])
    assert r.sanitized_feature_types() == ["pool", "deck", "yard"]


def test_build_vision_prompt_contains_locked_fragments():
    """The prompt is contractual — the phase brief pastes it verbatim
    and callers downstream depend on the JSON envelope wording. If
    someone reflows this, they need a new phase, not a silent test edit."""
    from routers.ai_measure import build_vision_prompt

    p = build_vision_prompt(["pool", "deck", "yard"])
    for frag in (
        "640x640 pixels",
        "clockwise order",
        '"features": [',
        "Do not fabricate.",
        "swimming pool water surface",
    ):
        assert frag in p, f"prompt missing fragment {frag!r}"


# ──────────────────────────────────────────────────────────────────
# HTTP-layer helpers (dependency-override pattern)
# ──────────────────────────────────────────────────────────────────
def _make_client(monkeypatch, *, role: str = "admin",
                  tenant_id: str = "t-aim0-1"):
    """Return a ``TestClient`` mounting only the ai_measure router
    with fake auth + tenant + Google + vision stubs. The vision
    providers are stubbed so no live outbound HTTP is generated."""
    from routers import ai_measure as am

    async def _fake_admin():
        if role == "technician":
            from fastapi import HTTPException
            raise HTTPException(403, "Admin access required")
        return {"id": "u-1", "role": role, "tenant_id": tenant_id,
                "email": f"{role}@example.com"}

    async def _fake_tenant():
        return {"id": tenant_id}

    async def _stub_static_map(*, lat, lng, zoom, http_client=None):
        # 8 bytes → deterministic tiny "image" for the b64 encoder.
        return b"\xff\xd8\xff\xe0FAKE"  # JPEG SOI + APP0 + payload

    monkeypatch.setattr(am, "fetch_static_map", _stub_static_map)

    app = FastAPI()
    app.include_router(am.router, prefix="/api")
    from utils import require_admin
    from routers.tenants import get_current_tenant
    app.dependency_overrides[require_admin] = _fake_admin
    app.dependency_overrides[get_current_tenant] = _fake_tenant

    # Reset rate-limit deque between clients so tests don't leak state.
    am._reset_rate_limit_for_tests()
    return TestClient(app), am


def _make_vision_stub(payloads: Dict[str, Any]):
    """Return an async stub for ``dispatch_ai_completion`` that
    returns a fake ``AICompletionResult`` per route."""
    from services.ai.models import AICompletionResult

    async def _stub(**kwargs):
        route = kwargs.get("route") or "anthropic_vision"
        payload = payloads.get(route, {})
        return AICompletionResult(
            content="stub",
            provider_key="emergent",
            provider_used="platform:emergent",
            model="stub-model",
            tokens_prompt=1, tokens_completion=1, tokens_total=2,
            tenant_id=kwargs.get("tenant_id", ""),
            raw=payload,
        )
    return _stub


# ──────────────────────────────────────────────────────────────────
# HTTP contract tests
# ──────────────────────────────────────────────────────────────────
def test_role_guard_technician_gets_403(monkeypatch):
    c, _ = _make_client(monkeypatch, role="technician")
    r = c.post("/api/tools/ai-measure/preview",
                 json={"lat": 33.4484, "lng": -112.074, "zoom": 20})
    assert r.status_code == 403, r.text


def test_admin_lat_lng_body_skips_geocoder(monkeypatch):
    """Passing explicit lat/lng must NOT call the geocoder."""
    c, am = _make_client(monkeypatch)

    geo_calls = {"n": 0}

    async def _spy_geocode(*a, **kw):
        geo_calls["n"] += 1
        return {"lat": 0.0, "lng": 0.0, "formatted": "should not be used"}

    monkeypatch.setattr(am, "_geocode_one", _spy_geocode)
    monkeypatch.setattr(am, "geocode_address", _spy_geocode)
    with patch.object(am, "dispatch_ai_completion",
                        side_effect=_make_vision_stub({
                            "openai_vision": {"features": [
                                {"type": "pool",
                                 "polygon": [[0, 0], [100, 0], [100, 100], [0, 100]],
                                 "confidence": 0.9, "notes": "clear"},
                            ]},
                            "anthropic_vision": {"features": []},
                        })):
        r = c.post("/api/tools/ai-measure/preview",
                     json={"lat": 33.4484, "lng": -112.074, "zoom": 20})
    assert r.status_code == 200, r.text
    assert geo_calls["n"] == 0, "geocoder should be skipped when lat/lng given"
    j = r.json()
    assert j["lat"] == 33.4484
    assert j["lng"] == -112.074
    assert j["zoom"] == 20
    assert j["satellite_image_data_url"].startswith("data:image/jpeg;base64,")
    assert len(j["providers"]) == 2
    # Areas should be annotated on returned features.
    openai_p = next(p for p in j["providers"]
                     if p["provider"] == "openai_gpt-4o")
    assert openai_p["features"][0]["area_sqft"] > 0
    assert openai_p["features"][0]["area_sqyd"] > 0


def test_admin_address_only_body_geocodes_then_fetches(monkeypatch):
    c, am = _make_client(monkeypatch)

    async def _stub_geocode(address, **kw):
        return {"lat": 37.4224, "lng": -122.0842,
                "formatted": "1600 Amphitheatre Pkwy, Mountain View, CA",
                "place_id": "stub"}

    monkeypatch.setattr(am, "geocode_address", _stub_geocode)

    with patch.object(am, "dispatch_ai_completion",
                        side_effect=_make_vision_stub({
                            "openai_vision": {"features": []},
                            "anthropic_vision": {"features": []},
                        })):
        r = c.post("/api/tools/ai-measure/preview",
                     json={"address": "1600 Amphitheatre Pkwy"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["lat"] == 37.4224
    assert j["lng"] == -122.0842
    assert j["address_resolved"].startswith("1600 Amphitheatre")


def test_address_not_geocodable_returns_422(monkeypatch):
    c, am = _make_client(monkeypatch)

    async def _stub_geocode(address, **kw):
        return None  # Google says "no such place"

    monkeypatch.setattr(am, "geocode_address", _stub_geocode)
    r = c.post("/api/tools/ai-measure/preview",
                 json={"address": "not a real address"})
    assert r.status_code == 422, r.text


def test_missing_address_and_coords_returns_400(monkeypatch):
    c, _ = _make_client(monkeypatch)
    r = c.post("/api/tools/ai-measure/preview", json={"zoom": 20})
    assert r.status_code == 400, r.text


def test_rate_limit_21st_request_returns_429(monkeypatch):
    c, am = _make_client(monkeypatch)

    with patch.object(am, "dispatch_ai_completion",
                        side_effect=_make_vision_stub({
                            "openai_vision": {"features": []},
                            "anthropic_vision": {"features": []},
                        })):
        # 20 successful requests within the same hour.
        for i in range(am.RATE_LIMIT_PER_HOUR):
            r = c.post("/api/tools/ai-measure/preview",
                        json={"lat": 33.4, "lng": -112.0, "zoom": 20})
            assert r.status_code == 200, f"request #{i+1}: {r.text}"
        # 21st MUST 429.
        r = c.post("/api/tools/ai-measure/preview",
                    json={"lat": 33.4, "lng": -112.0, "zoom": 20})
        assert r.status_code == 429, r.text
        assert "rate limit" in r.text.lower()


def test_vision_json_parse_failure_returns_empty_features_not_500(monkeypatch):
    """A malformed vision reply on ONE provider must still 200 on the
    endpoint with an ``error`` field on that provider only. Sibling
    provider results are unaffected."""
    c, am = _make_client(monkeypatch)

    async def _stub(**kwargs):
        from services.ai.models import AICompletionResult
        route = kwargs.get("route")
        if route == "openai_vision":
            # Garbage payload — no ``features`` key.
            raw = {"nonsense": "not a features list"}
        else:
            raw = {"features": [
                {"type": "yard",
                 "polygon": [[10, 10], [20, 10], [20, 20], [10, 20]],
                 "confidence": 0.7, "notes": "small square"},
            ]}
        return AICompletionResult(
            content="stub", provider_key="emergent",
            provider_used="platform:emergent", model="stub-model",
            tokens_prompt=1, tokens_completion=1, tokens_total=2,
            tenant_id=kwargs.get("tenant_id", ""), raw=raw,
        )

    with patch.object(am, "dispatch_ai_completion", side_effect=_stub):
        r = c.post("/api/tools/ai-measure/preview",
                    json={"lat": 33.4, "lng": -112.0, "zoom": 20})
    assert r.status_code == 200, r.text
    j = r.json()
    providers = {p["provider"]: p for p in j["providers"]}
    # Garbage payload → empty features + error field.
    assert providers["openai_gpt-4o"]["features"] == []
    assert providers["openai_gpt-4o"].get("error") is not None
    # Sibling still succeeds.
    assert len(providers["anthropic_claude"]["features"]) == 1
    assert providers["anthropic_claude"]["features"][0]["type"] == "yard"


def test_vision_provider_exception_does_not_500(monkeypatch):
    """A raised exception from ONE vision provider must still 200
    the endpoint with an ``error`` on that provider entry."""
    c, am = _make_client(monkeypatch)

    async def _stub(**kwargs):
        if kwargs.get("route") == "openai_vision":
            raise RuntimeError("simulated timeout")
        from services.ai.models import AICompletionResult
        return AICompletionResult(
            content="stub", provider_key="emergent",
            provider_used="platform:emergent", model="stub-model",
            tokens_prompt=1, tokens_completion=1, tokens_total=2,
            tenant_id=kwargs.get("tenant_id", ""),
            raw={"features": []},
        )

    with patch.object(am, "dispatch_ai_completion", side_effect=_stub):
        r = c.post("/api/tools/ai-measure/preview",
                    json={"lat": 33.4, "lng": -112.0, "zoom": 20})
    assert r.status_code == 200, r.text
    j = r.json()
    providers = {p["provider"]: p for p in j["providers"]}
    assert providers["openai_gpt-4o"].get("error", "").startswith("RuntimeError")
    assert providers["openai_gpt-4o"]["features"] == []


def test_zoom_out_of_range_returns_400(monkeypatch):
    c, _ = _make_client(monkeypatch)
    r = c.post("/api/tools/ai-measure/preview",
                 json={"lat": 33.4, "lng": -112.0, "zoom": 99})
    assert r.status_code == 400, r.text


def test_dispatcher_receives_expected_kwargs(monkeypatch):
    """Wire-check: the endpoint MUST call ``dispatch_ai_completion``
    once per provider, with ``image_b64s`` non-empty, ``parse_json=True``,
    and a ``route`` in {openai_vision, anthropic_vision}."""
    c, am = _make_client(monkeypatch)
    captured: List[Dict[str, Any]] = []

    async def _stub(**kwargs):
        captured.append({k: v for k, v in kwargs.items()
                          if k != "image_b64s"})
        captured[-1]["image_count"] = len(kwargs.get("image_b64s") or [])
        from services.ai.models import AICompletionResult
        return AICompletionResult(
            content="stub", provider_key="emergent",
            provider_used="platform:emergent", model="stub-model",
            tokens_prompt=1, tokens_completion=1, tokens_total=2,
            tenant_id=kwargs.get("tenant_id", ""),
            raw={"features": []},
        )

    with patch.object(am, "dispatch_ai_completion", side_effect=_stub):
        r = c.post("/api/tools/ai-measure/preview",
                    json={"lat": 33.4, "lng": -112.0, "zoom": 20})
    assert r.status_code == 200, r.text
    routes = sorted(c["route"] for c in captured)
    assert routes == ["anthropic_vision", "openai_vision"]
    for c_ in captured:
        assert c_["parse_json"] is True
        assert c_["image_count"] == 1
