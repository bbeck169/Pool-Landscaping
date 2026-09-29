"""Phase CAD-ADDR · Feb-2026 — ``GET /api/cad/map-tile-by-coords``.

Address-based site mapping: the caller supplies ``lat`` / ``lng``
directly (skipping geocoding) so the CAD editor's
``AddressAutocomplete`` can drop a pin without a round-trip through
the customer record.

Every outbound call to ``maps.googleapis.com`` is mocked via
``routers.cad._fetch_static_map_bytes`` monkey-patches — the tests
never hit Google.  ``routers.cad._geocode_live`` is monkey-patched
too so we can assert it is **NEVER** invoked on this endpoint.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Dict, Any

import httpx
import pytest
from dotenv import load_dotenv
from pymongo import MongoClient

from tests._f7_loop_fixture import run_test


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

TENANT_A = "test-cad-addr-tenant-a"


# ── DB helpers ──────────────────────────────────────────────────
def _sync_db():
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME")
    if not (url and name):
        pytest.skip("MONGO_URL / DB_NAME not configured")
    return MongoClient(url)[name]


def _reset_fixtures():
    db = _sync_db()
    db.tenants.delete_many({"id": TENANT_A})
    db.tenants.insert_one({"id": TENANT_A, "name": "Tenant A"})


# ── Auth overrides ──────────────────────────────────────────────
def _install_overrides(*, role: str = "admin",
                       tenant_id: str = TENANT_A):
    from server import app
    from utils import get_current_user, require_admin
    from routers.tenants import get_current_tenant

    async def _u():
        return {"id": "u_admin", "role": role, "email": "a@x",
                "tenant_id": tenant_id}

    async def _t():
        d = _sync_db().tenants.find_one({"id": tenant_id}) or {}
        d.pop("_id", None)
        return d

    async def _require_admin_dep():
        if role in ("admin", "super_admin"):
            return await _u()
        from fastapi import HTTPException
        raise HTTPException(403, "admin only")

    app.dependency_overrides[get_current_user] = _u
    app.dependency_overrides[get_current_tenant] = _t
    app.dependency_overrides[require_admin] = _require_admin_dep

    def _clear():
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_tenant, None)
        app.dependency_overrides.pop(require_admin, None)
    return _clear


def _run(coro_factory, *, role="admin", tenant_id=TENANT_A):
    clear = _install_overrides(role=role, tenant_id=tenant_id)
    try:
        async def _go(db):
            from server import app
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                await coro_factory(ac, db)
        run_test(_go)
    finally:
        clear()


# ── Google mocks ────────────────────────────────────────────────
_PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00"
    b"\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx"
    b"\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\xc4\x00\x00\x00\x00"
    b"IEND\xaeB`\x82"
)


class _StaticCallRecorder:
    def __init__(self, png: bytes = _PNG_1x1):
        self.calls: List[Dict[str, Any]] = []
        self.png = png

    async def __call__(self, *, lat, lng, zoom, width, height):
        self.calls.append({
            "lat": lat, "lng": lng, "zoom": zoom,
            "width": width, "height": height,
        })
        return self.png


class _GeocodeSpy:
    """Asserts nothing calls the geocoder on this endpoint."""

    def __init__(self):
        self.calls: List[Any] = []

    async def __call__(self, addr):
        self.calls.append(addr)
        return None


def _install_google_mocks(monkeypatch, *,
                          static_bytes: bytes = _PNG_1x1,
                          static_raises=None):
    import routers.cad as cad_mod
    geo = _GeocodeSpy()
    monkeypatch.setattr(cad_mod, "_geocode_live", geo)
    if static_raises is not None:
        async def _fake_static(**_kw):
            raise static_raises
        monkeypatch.setattr(cad_mod, "_fetch_static_map_bytes",
                            _fake_static)
        return None, geo
    rec = _StaticCallRecorder(png=static_bytes)
    monkeypatch.setattr(cad_mod, "_fetch_static_map_bytes", rec)
    return rec, geo


# ═══════════════════════════════════════════════════════════════════
# §1 · Happy path — 200 + correct X-Map-* headers
# ═══════════════════════════════════════════════════════════════════
def test_happy_path_returns_png_and_metadata(monkeypatch):
    _reset_fixtures()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")
    rec, geo = _install_google_mocks(monkeypatch)

    async def _t(ac, _db):
        r = await ac.get("/api/cad/map-tile-by-coords",
                         params={"lat": 25.7617, "lng": -80.1918,
                                 "zoom": 19, "size": "800x500"})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("image/png")
        assert r.content == _PNG_1x1
        assert r.headers["X-Geocode-Source"] == "coords"
        assert r.headers["X-Map-Zoom"] == "19"
        assert r.headers["X-Map-Lat"].startswith("25.7617")
        assert r.headers["X-Map-Lng"].startswith("-80.1918")
        assert float(r.headers["X-Feet-Per-Pixel"]) > 0
        # Geocoder MUST NOT be called on this endpoint.
        assert geo.calls == []
        # Static Maps was called with the caller-provided coords.
        assert len(rec.calls) == 1
        c = rec.calls[0]
        assert abs(c["lat"] - 25.7617) < 1e-6
        assert abs(c["lng"] - -80.1918) < 1e-6
        assert c["zoom"] == 19
        assert c["width"] == 800 and c["height"] == 500

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §2 · X-Map-Label passthrough
# ═══════════════════════════════════════════════════════════════════
def test_label_query_param_echoes_on_response_header(monkeypatch):
    _reset_fixtures()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")
    _install_google_mocks(monkeypatch)

    async def _t(ac, _db):
        r = await ac.get(
            "/api/cad/map-tile-by-coords",
            params={
                "lat": 33.6, "lng": -112.2, "zoom": 19,
                "size": "800x500",
                "label": "1 Test St, Miami, FL",
            },
        )
        assert r.status_code == 200, r.text
        assert r.headers.get("X-Map-Label") == "1 Test St, Miami, FL"
        # Label is on the CORS expose list so cross-origin fetch
        # can read it.
        assert "X-Map-Label" in r.headers.get(
            "Access-Control-Expose-Headers", "",
        )

    _run(_t)


def test_label_omitted_when_not_provided(monkeypatch):
    _reset_fixtures()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")
    _install_google_mocks(monkeypatch)

    async def _t(ac, _db):
        r = await ac.get(
            "/api/cad/map-tile-by-coords",
            params={"lat": 33.6, "lng": -112.2},
        )
        assert r.status_code == 200, r.text
        assert "X-Map-Label" not in r.headers
        # Expose list also stays lean when label is absent.
        assert "X-Map-Label" not in r.headers.get(
            "Access-Control-Expose-Headers", "",
        )

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §3 · feet_per_pixel matches the shared helper
# ═══════════════════════════════════════════════════════════════════
def test_feet_per_pixel_header_matches_shared_helper(monkeypatch):
    _reset_fixtures()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")
    _install_google_mocks(monkeypatch)

    async def _t(ac, _db):
        from routers.cad import _feet_per_pixel
        expected = _feet_per_pixel(33.6, 19)
        r = await ac.get(
            "/api/cad/map-tile-by-coords",
            params={"lat": 33.6, "lng": -112.2, "zoom": 19},
        )
        assert r.status_code == 200, r.text
        got = float(r.headers["X-Feet-Per-Pixel"])
        assert abs(got - expected) < 1e-4

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §4 · Missing lat / lng → 422 (FastAPI required-query rejection)
# ═══════════════════════════════════════════════════════════════════
def test_missing_lat_returns_422(monkeypatch):
    _reset_fixtures()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")
    _install_google_mocks(monkeypatch)

    async def _t(ac, _db):
        r = await ac.get("/api/cad/map-tile-by-coords",
                         params={"lng": -80.19})
        assert r.status_code == 422, r.text
        r = await ac.get("/api/cad/map-tile-by-coords",
                         params={"lat": 25.76})
        assert r.status_code == 422, r.text

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §5 · Out-of-range lat / lng → 400 invalid_coords
# ═══════════════════════════════════════════════════════════════════
def test_out_of_range_returns_400_invalid_coords(monkeypatch):
    _reset_fixtures()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")
    _install_google_mocks(monkeypatch)

    async def _t(ac, _db):
        for params in (
            {"lat": 95.0, "lng": 0},         # lat > 90
            {"lat": -95.0, "lng": 0},        # lat < -90
            {"lat": 0, "lng": 190.0},        # lng > 180
            {"lat": 0, "lng": -190.0},       # lng < -180
        ):
            r = await ac.get("/api/cad/map-tile-by-coords",
                             params=params)
            assert r.status_code == 400, (params, r.text)
            assert (r.json()["detail"]["error_code"]
                    == "invalid_coords")

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §6 · Missing GOOGLE_MAPS_API_KEY → 424
# ═══════════════════════════════════════════════════════════════════
def test_missing_google_key_returns_424(monkeypatch):
    _reset_fixtures()
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

    # Note: we DON'T install a static-map mock — the real
    # ``_fetch_static_map_bytes`` will raise 424 when the key is
    # unset, and that's exactly what we're asserting.
    async def _t(ac, _db):
        r = await ac.get("/api/cad/map-tile-by-coords",
                         params={"lat": 25.76, "lng": -80.19})
        assert r.status_code == 424, r.text
        assert (r.json()["detail"]["error_code"]
                == "google_maps_key_missing")

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §7 · Upstream non-200 → 502 map_tile_upstream_error
# ═══════════════════════════════════════════════════════════════════
def test_upstream_non_200_returns_502(monkeypatch):
    _reset_fixtures()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")
    from fastapi import HTTPException
    _install_google_mocks(
        monkeypatch,
        static_raises=HTTPException(
            502, {"error_code": "map_tile_upstream_error"},
        ),
    )

    async def _t(ac, _db):
        r = await ac.get("/api/cad/map-tile-by-coords",
                         params={"lat": 25.76, "lng": -80.19})
        assert r.status_code == 502, r.text
        assert (r.json()["detail"]["error_code"]
                == "map_tile_upstream_error")

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §8 · Non-admin → 403
# ═══════════════════════════════════════════════════════════════════
def test_non_admin_gets_403(monkeypatch):
    _reset_fixtures()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")
    _install_google_mocks(monkeypatch)

    async def _t(ac, _db):
        r = await ac.get("/api/cad/map-tile-by-coords",
                         params={"lat": 25.76, "lng": -80.19})
        assert r.status_code == 403, r.text

    _run(_t, role="viewer")


# ═══════════════════════════════════════════════════════════════════
# §9 · Zoom + size clamping matches /cad/map-tile
# ═══════════════════════════════════════════════════════════════════
def test_zoom_and_size_clamp_to_shared_bounds(monkeypatch):
    _reset_fixtures()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")
    rec, _geo = _install_google_mocks(monkeypatch)

    async def _t(ac, _db):
        # Zoom past the upper bound → clamps to 21.
        r = await ac.get(
            "/api/cad/map-tile-by-coords",
            params={"lat": 25.76, "lng": -80.19,
                    "zoom": 99, "size": "9999x9999"},
        )
        assert r.status_code == 200, r.text
        c = rec.calls[-1]
        assert c["zoom"] == 21
        assert c["width"] <= 2048 and c["height"] <= 2048
        # Zoom below lower bound → clamps to 15 (shared bound).
        r = await ac.get(
            "/api/cad/map-tile-by-coords",
            params={"lat": 25.76, "lng": -80.19, "zoom": 1},
        )
        assert r.status_code == 200, r.text
        c = rec.calls[-1]
        assert c["zoom"] == 15

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §10 · NaN lat/lng → 400 invalid_coords
# ═══════════════════════════════════════════════════════════════════
def test_nan_lat_lng_returns_400_invalid_coords(monkeypatch):
    _reset_fixtures()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")
    _install_google_mocks(monkeypatch)

    async def _t(ac, _db):
        r = await ac.get(
            "/api/cad/map-tile-by-coords",
            params={"lat": "nan", "lng": -80.19},
        )
        # ``float("nan")`` succeeds in Query coercion, then our
        # ``isfinite`` guard rejects with 400.  Some Pydantic
        # builds instead reject at coercion (422). Either
        # rejection is acceptable — both are non-2xx and no
        # tile is issued.
        assert r.status_code in (400, 422), r.text

    _run(_t)
