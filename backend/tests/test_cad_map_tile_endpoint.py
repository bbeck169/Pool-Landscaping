"""Phase CAD-1 · Feb-2026 — ``GET /api/cad/map-tile`` contract.

Server proxies a Google Static Maps satellite tile so the FE never
sees ``GOOGLE_MAPS_API_KEY``. Coordinates are geocoded on demand
and cached in ``geocode_cache`` (30-day TTL).

Every outbound call to ``maps.googleapis.com`` is mocked via
``routers.cad._geocode_live`` / ``routers.cad._fetch_static_map_bytes``
monkey-patches — the tests never hit Google.
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
from dotenv import load_dotenv
from pymongo import MongoClient

from tests._f7_loop_fixture import run_test


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

TENANT_A = "test-cad1-tenant-a"
TENANT_B = "test-cad1-tenant-b"


# ── DB helpers ──────────────────────────────────────────────────
def _sync_db():
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME")
    if not (url and name):
        pytest.skip("MONGO_URL / DB_NAME not configured")
    return MongoClient(url)[name]


def _reset_fixtures():
    db = _sync_db()
    db.tenants.delete_many({"id": {"$in": [TENANT_A, TENANT_B]}})
    db.customers.delete_many(
        {"tenant_id": {"$in": [TENANT_A, TENANT_B]}},
    )
    db.geocode_cache.delete_many({})
    db.tenants.insert_one({"id": TENANT_A, "name": "Tenant A"})
    db.tenants.insert_one({"id": TENANT_B, "name": "Tenant B"})


def _seed_customer(cid: str, *, tenant_id: str = TENANT_A,
                   address: str = "123 Main St, Miami FL 33101"):
    db = _sync_db()
    db.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "Robert Blake", "address": address,
    })


# ── Auth overrides (pattern from test_ticket3_ticket4_org_settings.py) ──
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
    """Captures the arguments the endpoint passed into
    ``_fetch_static_map_bytes`` so we can assert on zoom + size
    clamping without inspecting the outbound HTTP call itself."""

    def __init__(self, png: bytes = _PNG_1x1):
        self.calls: list[dict] = []
        self.png = png

    async def __call__(self, *, lat, lng, zoom, width, height):
        self.calls.append({
            "lat": lat, "lng": lng, "zoom": zoom,
            "width": width, "height": height,
        })
        return self.png


def _install_google_mocks(monkeypatch, *,
                          geocode_result=None,
                          static_bytes: bytes = _PNG_1x1,
                          static_raises=None):
    """Replace ``routers.cad._geocode_live`` +
    ``routers.cad._fetch_static_map_bytes`` and return the static-
    call recorder so tests can assert on how the endpoint drove the
    Static Maps call."""
    import routers.cad as cad_mod

    async def _fake_geocode(_addr):
        return geocode_result

    if static_raises is not None:
        async def _fake_static(**_kw):
            raise static_raises
        rec = None
        monkeypatch.setattr(cad_mod, "_geocode_live", _fake_geocode)
        monkeypatch.setattr(cad_mod, "_fetch_static_map_bytes",
                            _fake_static)
    else:
        rec = _StaticCallRecorder(png=static_bytes)
        monkeypatch.setattr(cad_mod, "_geocode_live", _fake_geocode)
        monkeypatch.setattr(cad_mod, "_fetch_static_map_bytes", rec)
    return rec


# ═══════════════════════════════════════════════════════════════════
# §1 · Cache hit → 200 + X-Geocode-Source: cache
# ═══════════════════════════════════════════════════════════════════
def test_map_tile_cache_hit_returns_bytes_and_metadata(monkeypatch):
    _reset_fixtures()
    _seed_customer("cust-1")
    # Pre-warm the cache. Same normalization the endpoint uses.
    from routers.cad import _address_hash
    db_sync = _sync_db()
    db_sync.geocode_cache.insert_one({
        "address_hash": _address_hash("123 Main St, Miami FL 33101"),
        "lat": 25.7617, "lng": -80.1918,
        "formatted_address": "123 Main St, Miami, FL 33101, USA",
    })
    rec = _install_google_mocks(monkeypatch, geocode_result=None)

    async def _t(ac, _db):
        r = await ac.get("/api/cad/map-tile",
                         params={"customer_id": "cust-1", "zoom": 19,
                                 "size": "800x500"})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("image/png")
        assert r.content == _PNG_1x1
        assert r.headers["X-Geocode-Source"] == "cache"
        assert r.headers["X-Map-Zoom"] == "19"
        # 7-decimal float format from the handler.
        assert r.headers["X-Map-Lat"].startswith("25.7617")
        assert r.headers["X-Map-Lng"].startswith("-80.1918")
        # feet_per_pixel is emitted with 6 decimals.
        assert float(r.headers["X-Feet-Per-Pixel"]) > 0
        # Static Maps was called exactly once with the cached lat/lng.
        assert len(rec.calls) == 1
        c = rec.calls[0]
        assert abs(c["lat"] - 25.7617) < 1e-6
        assert abs(c["lng"] - -80.1918) < 1e-6
        assert c["zoom"] == 19
        assert c["width"] == 800 and c["height"] == 500

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §2 · Cache miss → live geocode → cache write → subsequent hit
# ═══════════════════════════════════════════════════════════════════
def test_map_tile_cache_miss_then_hit(monkeypatch):
    _reset_fixtures()
    _seed_customer("cust-2")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")
    rec = _install_google_mocks(
        monkeypatch,
        geocode_result={"lat": 25.7617, "lng": -80.1918,
                        "formatted": "Miami"},
    )

    async def _t(ac, _db):
        # First call — cache miss, live geocode.
        r1 = await ac.get("/api/cad/map-tile",
                          params={"customer_id": "cust-2"})
        assert r1.status_code == 200, r1.text
        assert r1.headers["X-Geocode-Source"] == "live"
        # Cache write happened (via the endpoint's ``update_one``
        # upsert). Read it back with the sync client on the same DB
        # bound to the endpoint's loop.
        from routers.cad import _address_hash
        db_sync = _sync_db()
        cached = db_sync.geocode_cache.find_one({
            "address_hash": _address_hash(
                "123 Main St, Miami FL 33101"),
        })
        assert cached is not None
        assert abs(cached["lat"] - 25.7617) < 1e-6
        # Second call — cache hit, no additional geocode.
        r2 = await ac.get("/api/cad/map-tile",
                          params={"customer_id": "cust-2"})
        assert r2.status_code == 200, r2.text
        assert r2.headers["X-Geocode-Source"] == "cache"
        # Static Maps was called twice, geocode was not needed the
        # second time (the recorder only tracks Static Maps calls).
        assert len(rec.calls) == 2

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §3 · Missing customer → 404
# ═══════════════════════════════════════════════════════════════════
def test_map_tile_missing_customer_404(monkeypatch):
    _reset_fixtures()
    _install_google_mocks(monkeypatch, geocode_result=None)

    async def _t(ac, _db):
        r = await ac.get(
            "/api/cad/map-tile",
            params={"customer_id": "does-not-exist"},
        )
        assert r.status_code == 404, r.text
        assert r.json()["detail"]["error_code"] == "customer_not_found"

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §4 · Customer with empty address → 424 customer_address_missing
# ═══════════════════════════════════════════════════════════════════
def test_map_tile_customer_empty_address_424(monkeypatch):
    _reset_fixtures()
    _seed_customer("cust-noaddr", address="")
    _install_google_mocks(monkeypatch, geocode_result=None)

    async def _t(ac, _db):
        r = await ac.get(
            "/api/cad/map-tile",
            params={"customer_id": "cust-noaddr"},
        )
        assert r.status_code == 424, r.text
        assert r.json()["detail"]["error_code"] == "customer_address_missing"

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §5 · Geocode returns no results → 424 geocode_failed
# ═══════════════════════════════════════════════════════════════════
def test_map_tile_geocode_no_results_424(monkeypatch):
    _reset_fixtures()
    _seed_customer("cust-badaddr")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")
    _install_google_mocks(monkeypatch, geocode_result=None)

    async def _t(ac, _db):
        r = await ac.get(
            "/api/cad/map-tile",
            params={"customer_id": "cust-badaddr"},
        )
        assert r.status_code == 424, r.text
        assert r.json()["detail"]["error_code"] == "geocode_failed"

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §6 · Static Maps upstream non-200 → 502 map_tile_upstream_error
# ═══════════════════════════════════════════════════════════════════
def test_map_tile_upstream_non_200_502(monkeypatch):
    _reset_fixtures()
    _seed_customer("cust-3")
    from fastapi import HTTPException
    _install_google_mocks(
        monkeypatch,
        geocode_result={"lat": 25.7617, "lng": -80.1918,
                        "formatted": "Miami"},
        static_raises=HTTPException(
            502,
            {"error_code": "map_tile_upstream_error",
             "detail": "upstream 403: forbidden"},
        ),
    )

    async def _t(ac, _db):
        r = await ac.get(
            "/api/cad/map-tile",
            params={"customer_id": "cust-3"},
        )
        assert r.status_code == 502, r.text
        body = r.json()
        assert body["detail"]["error_code"] == "map_tile_upstream_error"

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §7 · Missing GOOGLE_MAPS_API_KEY → 424
# ═══════════════════════════════════════════════════════════════════
def test_map_tile_missing_google_api_key_424(monkeypatch):
    _reset_fixtures()
    _seed_customer("cust-4")
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    # Do NOT mock ``_geocode_live`` — its real implementation reads
    # the env var and returns None when it's absent, which is the
    # exact code path we want to lock.
    import routers.cad as cad_mod

    async def _fake_static(**_kw):
        raise AssertionError(
            "static maps should not be called when key is missing",
        )

    monkeypatch.setattr(cad_mod, "_fetch_static_map_bytes", _fake_static)

    async def _t(ac, _db):
        r = await ac.get(
            "/api/cad/map-tile",
            params={"customer_id": "cust-4"},
        )
        assert r.status_code == 424, r.text
        assert r.json()["detail"]["error_code"] == "google_maps_key_missing"

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §8 · Zoom clamping — 14 → 15, 22 → 21
# ═══════════════════════════════════════════════════════════════════
def test_map_tile_zoom_clamping(monkeypatch):
    _reset_fixtures()
    _seed_customer("cust-5")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")
    rec = _install_google_mocks(
        monkeypatch,
        geocode_result={"lat": 25.7617, "lng": -80.1918,
                        "formatted": "Miami"},
    )

    async def _t(ac, _db):
        r_lo = await ac.get(
            "/api/cad/map-tile",
            params={"customer_id": "cust-5", "zoom": 14},
        )
        assert r_lo.status_code == 200
        assert r_lo.headers["X-Map-Zoom"] == "15"
        r_hi = await ac.get(
            "/api/cad/map-tile",
            params={"customer_id": "cust-5", "zoom": 22},
        )
        assert r_hi.status_code == 200
        assert r_hi.headers["X-Map-Zoom"] == "21"
        assert rec.calls[0]["zoom"] == 15
        assert rec.calls[1]["zoom"] == 21

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §9 · Size clamping — 100→200, 2000→1280
# ═══════════════════════════════════════════════════════════════════
def test_map_tile_size_clamping(monkeypatch):
    _reset_fixtures()
    _seed_customer("cust-6")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")
    rec = _install_google_mocks(
        monkeypatch,
        geocode_result={"lat": 25.7617, "lng": -80.1918,
                        "formatted": "Miami"},
    )

    async def _t(ac, _db):
        r_lo = await ac.get(
            "/api/cad/map-tile",
            params={"customer_id": "cust-6", "size": "100x100"},
        )
        assert r_lo.status_code == 200
        assert rec.calls[-1]["width"] == 200
        assert rec.calls[-1]["height"] == 200
        r_hi = await ac.get(
            "/api/cad/map-tile",
            params={"customer_id": "cust-6", "size": "2000x2000"},
        )
        assert r_hi.status_code == 200
        assert rec.calls[-1]["width"] == 1280
        assert rec.calls[-1]["height"] == 1280

    _run(_t)


# ═══════════════════════════════════════════════════════════════════
# §10 · Tenant isolation — cust in Tenant A invisible from Tenant B
# ═══════════════════════════════════════════════════════════════════
def test_map_tile_tenant_isolation(monkeypatch):
    _reset_fixtures()
    _seed_customer("cust-7", tenant_id=TENANT_A)
    _install_google_mocks(
        monkeypatch,
        geocode_result={"lat": 25.7617, "lng": -80.1918,
                        "formatted": "Miami"},
    )

    async def _t(ac, _db):
        # Fetch with Tenant B session — customer belongs to Tenant A.
        r = await ac.get(
            "/api/cad/map-tile",
            params={"customer_id": "cust-7"},
        )
        assert r.status_code == 404, r.text
        assert r.json()["detail"]["error_code"] == "customer_not_found"

    _run(_t, tenant_id=TENANT_B)


# ═══════════════════════════════════════════════════════════════════
# §11 · Non-admin → 403
# ═══════════════════════════════════════════════════════════════════
def test_map_tile_non_admin_403(monkeypatch):
    _reset_fixtures()
    _seed_customer("cust-8")
    _install_google_mocks(
        monkeypatch,
        geocode_result={"lat": 25.7617, "lng": -80.1918,
                        "formatted": "Miami"},
    )

    async def _t(ac, _db):
        r = await ac.get(
            "/api/cad/map-tile",
            params={"customer_id": "cust-8"},
        )
        assert r.status_code == 403, r.text

    _run(_t, role="technician")


# ═══════════════════════════════════════════════════════════════════
# §12 · feet_per_pixel math — Miami (lat 25.7617) at zoom 19
# ═══════════════════════════════════════════════════════════════════
def test_map_tile_feet_per_pixel_math(monkeypatch):
    _reset_fixtures()
    _seed_customer("cust-9")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIfake")
    _install_google_mocks(
        monkeypatch,
        geocode_result={"lat": 25.7617, "lng": -80.1918,
                        "formatted": "Miami"},
    )
    # Expected: 156543.03392 * cos(25.7617°) / 2^19 * 3.28084
    import math
    expected = (
        156543.03392
        * math.cos(math.radians(25.7617))
        / (2 ** 19)
        * 3.28084
    )

    async def _t(ac, _db):
        r = await ac.get(
            "/api/cad/map-tile",
            params={"customer_id": "cust-9", "zoom": 19},
        )
        assert r.status_code == 200
        got = float(r.headers["X-Feet-Per-Pixel"])
        assert abs(got - expected) < 1e-4, (got, expected)

    _run(_t)
