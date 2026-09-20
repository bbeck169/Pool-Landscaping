"""Phase I1.7.c.2 · Feb-2026 — Tenant Maps BYO Providers · 14 cases.

Uses ``MAPS_TESTMODE_MOCK=true`` so adapters short-circuit without
outbound HTTP. Endpoint-level cases hit the live backend on
``localhost:8001``.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API = "http://localhost:8001/api"
_sync = _shared_db()
_LOOP: asyncio.AbstractEventLoop | None = None
_MOTOR_DB = None


def _setup_loop():
    global _LOOP, _MOTOR_DB
    if _LOOP is None:
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
        _client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        _MOTOR_DB = _client[os.environ["DB_NAME"]]
        import services.secrets.store as _store
        _store._default_db = lambda: _MOTOR_DB   # type: ignore
        import services.maps.usage as _usage_mod
        _usage_mod._default_db = lambda: _MOTOR_DB  # type: ignore
    return _LOOP, _MOTOR_DB


def _drive(coro_factory):
    loop, db = _setup_loop()
    return loop.run_until_complete(coro_factory(db))


def _login(email="super@aquaterra.com", password="password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _tenant_id(tok: str) -> str:
    r = requests.get(f"{API}/tenants/current", headers=_hdrs(tok), timeout=15)
    r.raise_for_status()
    return r.json()["id"]


@pytest.fixture(autouse=True)
def _clean_and_flag(monkeypatch):
    monkeypatch.setenv("MAPS_TESTMODE_MOCK", "true")
    from services.maps.registry import reset_cache_for_tests
    reset_cache_for_tests()
    yield


TENANT_LOCAL = f"i17c2-maps-{uuid.uuid4().hex[:8]}"


def _cleanup_tenant(tid: str) -> None:
    _sync.tenant_secrets.delete_many({"tenant_id": tid,
                                        "provider_key": {"$regex": r"^maps_"}})
    _sync.tenant_maps_provider.delete_many({"tenant_id": tid})
    _sync.tenant_maps_usage.delete_many({"tenant_id": tid})


# ── Case 01 — Registry lists both providers ────────────────────
def test_registry_lists_google_and_mapbox():
    from services.maps.registry import (
        list_registered_maps_provider_keys, list_short_names,
    )
    assert set(list_registered_maps_provider_keys()) == {"maps_google", "maps_mapbox"}
    assert set(list_short_names()) == {"google", "mapbox"}


# ── Case 02 — PUT maps_google stores encrypted + masks on GET ──
def test_put_maps_google_stores_encrypted_key_and_masks_on_get():
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        marker = f"gmk-{uuid.uuid4().hex}"
        r = requests.put(
            f"{API}/tenants/me/integrations/maps_google",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"api_key": marker, "region_bias": "us"},
                    "monthly_request_cap": 1000},
        )
        assert r.status_code == 200, r.text
        # Ciphertext at rest — marker must not appear on raw row.
        row = _sync.tenant_secrets.find_one({"tenant_id": tid,
                                                "provider_key": "maps_google"})
        assert row and "encrypted_blob" in row
        assert marker not in json.dumps(row, default=str)
        # GET list: last_4 present + marker never leaks.
        lst = requests.get(f"{API}/tenants/me/integrations",
                              headers=_hdrs(tok), timeout=15).json()
        assert marker not in json.dumps(lst)
        row_public = next(r for r in lst["integrations"]
                            if r["provider_key"] == "maps_google")
        assert row_public["connected"] is True
        assert row_public["last_4"] == marker[-4:]
    finally:
        _cleanup_tenant(tid)


# ── Case 03 — PUT maps_mapbox stores encrypted + masks on GET ──
def test_put_maps_mapbox_stores_encrypted_key_and_masks_on_get():
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        marker = f"pk.mapbox.{uuid.uuid4().hex}"
        r = requests.put(
            f"{API}/tenants/me/integrations/maps_mapbox",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"api_key": marker, "style": "mapbox/streets-v12"}},
        )
        assert r.status_code == 200, r.text
        row = _sync.tenant_secrets.find_one({"tenant_id": tid,
                                                "provider_key": "maps_mapbox"})
        assert row and marker not in json.dumps(row, default=str)
        lst = requests.get(f"{API}/tenants/me/integrations",
                              headers=_hdrs(tok), timeout=15).json()
        row_public = next(r for r in lst["integrations"]
                            if r["provider_key"] == "maps_mapbox")
        assert row_public["last_4"] == marker[-4:]
    finally:
        _cleanup_tenant(tid)


# ── Case 04 — DELETE clears secret + metadata ──────────────────
def test_delete_maps_provider_clears_secret():
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        requests.put(
            f"{API}/tenants/me/integrations/maps_google",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"api_key": "gmk-tobedeleted", "region_bias": "us"},
                    "monthly_request_cap": 5000},
        ).raise_for_status()
        assert _sync.tenant_secrets.count_documents(
            {"tenant_id": tid, "provider_key": "maps_google"}) == 1
        assert _sync.tenant_maps_provider.count_documents(
            {"tenant_id": tid, "provider": "google"}) == 1
        r = requests.delete(
            f"{API}/tenants/me/integrations/maps_google",
            headers=_hdrs(tok), timeout=15,
        )
        assert r.status_code == 200 and r.json()["removed"] is True
        assert _sync.tenant_secrets.count_documents(
            {"tenant_id": tid, "provider_key": "maps_google"}) == 0
        assert _sync.tenant_maps_provider.count_documents(
            {"tenant_id": tid, "provider": "google"}) == 0
    finally:
        _cleanup_tenant(tid)


# ── Case 05 — Dispatch uses tenant provider when configured ────
def test_dispatch_maps_uses_tenant_provider_when_configured():
    from services.maps import dispatch_maps_geocode
    from services.maps._helpers import save_provider_config
    from services.maps.google_maps_provider import GoogleMapsProvider

    provider = GoogleMapsProvider()

    async def _work(db):
        _cleanup_tenant(TENANT_LOCAL)
        await save_provider_config(
            tenant_id=TENANT_LOCAL, provider_key="maps_google",
            config={"api_key": "gmk-tenant-XY", "region_bias": "us"},
            schema=provider.config_fields,
            primary_secret_field=provider.primary_secret_field,
            db=db,
        )
        return await dispatch_maps_geocode(
            tenant_id=TENANT_LOCAL, address="1600 Amphitheatre Pkwy", db=db,
        )
    result = _drive(_work)
    assert result.provider_used == "tenant:google"
    assert result.formatted_address and "mock google" in result.formatted_address
    _cleanup_tenant(TENANT_LOCAL)


# ── Case 06 — Dispatch falls back to platform when unconfigured ──
def test_dispatch_maps_falls_back_to_platform_when_unconfigured():
    from services.maps import dispatch_maps_geocode

    fresh_tid = f"i17c2-no-byo-{uuid.uuid4().hex[:8]}"

    async def _work(db):
        _sync.tenant_secrets.delete_many({"tenant_id": fresh_tid})
        return await dispatch_maps_geocode(
            tenant_id=fresh_tid, address="test address", db=db,
        )
    result = _drive(_work)
    assert result.provider_key == "maps_platform"
    assert result.provider_used.startswith("platform:")


# ── Case 07 — Usage counters per operation ─────────────────────
def test_dispatch_maps_tracks_usage_per_operation():
    from services.maps import (
        dispatch_maps_geocode, dispatch_maps_route,
        dispatch_maps_static_map_url,
    )
    from services.maps._helpers import save_provider_config
    from services.maps.google_maps_provider import GoogleMapsProvider
    from services.maps.usage import get_usage_row

    provider = GoogleMapsProvider()

    async def _work(db):
        _cleanup_tenant(TENANT_LOCAL)
        await save_provider_config(
            tenant_id=TENANT_LOCAL, provider_key="maps_google",
            config={"api_key": "gmk-usage-XY", "region_bias": "us"},
            schema=provider.config_fields,
            primary_secret_field=provider.primary_secret_field,
            db=db,
        )
        await dispatch_maps_geocode(tenant_id=TENANT_LOCAL, address="a", db=db)
        await dispatch_maps_geocode(tenant_id=TENANT_LOCAL, address="b", db=db)
        await dispatch_maps_route(
            tenant_id=TENANT_LOCAL,
            origin=(1.0, 2.0), destinations=[(3.0, 4.0)], db=db,
        )
        await dispatch_maps_static_map_url(
            tenant_id=TENANT_LOCAL, center=(1.0, 2.0), db=db,
        )
        return await get_usage_row(
            tenant_id=TENANT_LOCAL, provider="google", db=db,
        )
    row = _drive(_work)
    assert row is not None
    assert row["geocode"] == 2
    assert row["route"] == 1
    assert row["static_map"] == 1
    assert row["total"] == 4
    _cleanup_tenant(TENANT_LOCAL)


# ── Case 08 — Soft warning at 80% ──────────────────────────────
def test_dispatch_maps_soft_warning_at_80pct():
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        r = requests.put(
            f"{API}/tenants/me/integrations/maps_google",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"api_key": "gmk-warn-XY", "region_bias": "us"},
                    "monthly_request_cap": 100},
        )
        assert r.status_code == 200
        from services.maps.usage import record_usage as _rec

        async def _seed(db):
            for _ in range(80):
                await _rec(tenant_id=tid, provider="google",
                            operation="geocode", db=db)
        _drive(_seed)
        usage = requests.get(
            f"{API}/tenants/me/integrations/maps/usage",
            headers=_hdrs(tok), timeout=15,
        ).json()
        google = next(p for p in usage["providers"] if p["provider"] == "google")
        assert google["total"] == 80
        assert google["monthly_request_cap"] == 100
        assert google["status"] == "warn"
        assert abs(google["pct_used"] - 0.8) < 1e-6
    finally:
        _cleanup_tenant(tid)


# ── Case 09 — Hard block at 100% → 429 shape ───────────────────
def test_dispatch_maps_hard_block_at_100pct_returns_429():
    from services.maps import (
        dispatch_maps_geocode, TenantMapsRequestCapExceeded,
    )
    from services.maps._helpers import save_provider_config
    from services.maps.google_maps_provider import GoogleMapsProvider
    from services.maps.usage import upsert_provider_meta, record_usage

    provider = GoogleMapsProvider()

    async def _work(db):
        _cleanup_tenant(TENANT_LOCAL)
        await save_provider_config(
            tenant_id=TENANT_LOCAL, provider_key="maps_google",
            config={"api_key": "gmk-block-XY"},
            schema=provider.config_fields,
            primary_secret_field=provider.primary_secret_field,
            db=db,
        )
        await upsert_provider_meta(
            tenant_id=TENANT_LOCAL, provider="google",
            monthly_request_cap=5, db=db,
        )
        for _ in range(5):
            await record_usage(
                tenant_id=TENANT_LOCAL, provider="google",
                operation="geocode", db=db,
            )
        try:
            await dispatch_maps_geocode(
                tenant_id=TENANT_LOCAL, address="a", db=db,
            )
            return "no_raise"
        except TenantMapsRequestCapExceeded as e:
            return e
    outcome = _drive(_work)
    assert isinstance(outcome, TenantMapsRequestCapExceeded)
    assert outcome.provider == "google"
    assert outcome.cap == 5 and outcome.used == 5
    _cleanup_tenant(TENANT_LOCAL)


# ── Case 10 — cap = 0 kill-switch ──────────────────────────────
def test_maps_cap_zero_blocks_immediately():
    from services.maps import (
        dispatch_maps_static_map_url, TenantMapsRequestCapExceeded,
    )
    from services.maps._helpers import save_provider_config
    from services.maps.mapbox_provider import MapboxProvider
    from services.maps.usage import upsert_provider_meta

    provider = MapboxProvider()

    async def _work(db):
        _cleanup_tenant(TENANT_LOCAL)
        await save_provider_config(
            tenant_id=TENANT_LOCAL, provider_key="maps_mapbox",
            config={"api_key": "pk.killswitch"},
            schema=provider.config_fields,
            primary_secret_field=provider.primary_secret_field,
            db=db,
        )
        await upsert_provider_meta(
            tenant_id=TENANT_LOCAL, provider="mapbox",
            monthly_request_cap=0, db=db,
        )
        try:
            await dispatch_maps_static_map_url(
                tenant_id=TENANT_LOCAL, center=(0.0, 0.0), db=db,
            )
            return "no_raise"
        except TenantMapsRequestCapExceeded as e:
            return e
    outcome = _drive(_work)
    assert isinstance(outcome, TenantMapsRequestCapExceeded)
    assert outcome.cap == 0 and outcome.used == 0
    _cleanup_tenant(TENANT_LOCAL)


# ── Case 11 — Hard-block MUST NOT fallback to platform ─────────
def test_maps_hard_block_does_not_fallback_to_platform():
    """Regression guard: when BYO is configured and cap is hit, the
    dispatcher must raise instead of silently returning a platform
    result."""
    from services.maps import (
        dispatch_maps_route, TenantMapsRequestCapExceeded,
    )
    from services.maps._helpers import save_provider_config
    from services.maps.google_maps_provider import GoogleMapsProvider
    from services.maps.usage import upsert_provider_meta, record_usage

    provider = GoogleMapsProvider()

    async def _work(db):
        _cleanup_tenant(TENANT_LOCAL)
        await save_provider_config(
            tenant_id=TENANT_LOCAL, provider_key="maps_google",
            config={"api_key": "gmk-no-fallback"},
            schema=provider.config_fields,
            primary_secret_field=provider.primary_secret_field,
            db=db,
        )
        await upsert_provider_meta(
            tenant_id=TENANT_LOCAL, provider="google",
            monthly_request_cap=1, db=db,
        )
        await record_usage(
            tenant_id=TENANT_LOCAL, provider="google",
            operation="route", db=db,
        )
        try:
            result = await dispatch_maps_route(
                tenant_id=TENANT_LOCAL,
                origin=(1.0, 2.0), destinations=[(3.0, 4.0)],
                db=db,
            )
        except TenantMapsRequestCapExceeded as e:
            return ("raised", e)
        return ("returned", result)
    outcome, val = _drive(_work)
    assert outcome == "raised"
    # NOT the platform fallback shape:
    assert not str(val).startswith("platform:")
    _cleanup_tenant(TENANT_LOCAL)


# ── Case 12 — GET /maps/usage returns current-period breakdown ──
def test_get_maps_usage_returns_current_period_per_operation():
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        requests.put(
            f"{API}/tenants/me/integrations/maps_mapbox",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"api_key": "pk.usage-XY", "style": "mapbox/streets-v12"},
                    "monthly_request_cap": 200},
        ).raise_for_status()
        from services.maps.usage import record_usage as _rec

        async def _seed(db):
            await _rec(tenant_id=tid, provider="mapbox", operation="geocode", db=db)
            await _rec(tenant_id=tid, provider="mapbox", operation="geocode", db=db)
            await _rec(tenant_id=tid, provider="mapbox", operation="route", db=db)
        _drive(_seed)
        usage = requests.get(
            f"{API}/tenants/me/integrations/maps/usage",
            headers=_hdrs(tok), timeout=15,
        ).json()
        mb = next(p for p in usage["providers"] if p["provider"] == "mapbox")
        assert mb["geocode"] == 2
        assert mb["route"] == 1
        assert mb["static_map"] == 0
        assert mb["total"] == 3
        assert mb["monthly_request_cap"] == 200
        assert mb["status"] == "ok"
    finally:
        _cleanup_tenant(tid)


# ── Case 13 — OpenAPI declares the new maps endpoints ──────────
def test_openapi_declares_new_maps_endpoints():
    r = requests.get(f"{API}/openapi.json", timeout=15)
    r.raise_for_status()
    paths = set(r.json().get("paths", {}).keys())
    # PUT + DELETE on the generic route handles maps_google/maps_mapbox
    # (both use the same ``{provider_key}`` template).
    assert "/api/tenants/me/integrations/{provider_key}" in paths
    assert "/api/tenants/me/integrations/maps/usage" in paths
    # Schemas endpoint returns the maps[] array — sanity check via HTTP.
    tok = _login()
    schemas = requests.get(
        f"{API}/tenants/me/integrations/schemas", headers=_hdrs(tok), timeout=15,
    ).json()
    keys = {p["provider_key"] for p in schemas["maps"]}
    assert keys == {"maps_google", "maps_mapbox"}


# ── Case 14 — Uniformity guard for the shared preserve helper ──
def test_cap_only_edit_preserves_stored_maps_secret():
    """Post-tester regression guard from I1.7.c.1 must apply to Maps
    providers too — cap-only edit on a connected provider preserves
    the stored api_key."""
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        marker = f"gmk-original_{uuid.uuid4().hex}"[:32]
        put1 = requests.put(
            f"{API}/tenants/me/integrations/maps_google",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"api_key": marker, "region_bias": "us"},
                    "monthly_request_cap": 1000},
        )
        assert put1.status_code == 200, put1.text
        lst_a = requests.get(f"{API}/tenants/me/integrations",
                                headers=_hdrs(tok), timeout=15).json()
        last4_before = next(r for r in lst_a["integrations"]
                              if r["provider_key"] == "maps_google")["last_4"]
        # Cap-only edit — no api_key in payload.
        put2 = requests.put(
            f"{API}/tenants/me/integrations/maps_google",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"region_bias": "us"},
                    "monthly_request_cap": 2000},
        )
        assert put2.status_code == 200, put2.text
        lst_b = requests.get(f"{API}/tenants/me/integrations",
                                headers=_hdrs(tok), timeout=15).json()
        row_b = next(r for r in lst_b["integrations"]
                       if r["provider_key"] == "maps_google")
        assert row_b["last_4"] == last4_before
        # Cap updated in /usage.
        usage = requests.get(f"{API}/tenants/me/integrations/maps/usage",
                                headers=_hdrs(tok), timeout=15).json()
        google = next(p for p in usage["providers"] if p["provider"] == "google")
        assert google["monthly_request_cap"] == 2000
        # Adapter still decrypts to the ORIGINAL api_key.
        from services.maps._helpers import load_provider_config

        async def _work(db):
            return await load_provider_config(
                tenant_id=tid, provider_key="maps_google", db=db,
            )
        cfg = _drive(_work)
        assert cfg["api_key"] == marker
    finally:
        _cleanup_tenant(tid)
