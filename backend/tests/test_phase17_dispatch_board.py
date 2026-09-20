"""Phase 17 · Feb-2026 — Dispatch Board API integration tests.

Covers:

  a) ``GET  /api/dispatch/board`` returns pins, tech_load, and
     route_stops when a day + tech is selected. Skips pins without
     ``service_lat`` / ``service_lng``. Enforces RBAC (403 for
     technicians).
  b) ``POST /api/dispatch/board/apply-order`` upserts a
     ``dispatch_route_orders`` row and the next ``GET`` picks it up.
  c) ``POST /api/dispatch/board/optimize`` calls Google Directions.
     Mocked with ``responses`` so we don't hit the live API. Verifies
     the reordered customer IDs + savings math.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
_TENANT_ID = _sync.tenants.find_one({"slug": "aquaterra"})["id"]
API = "http://localhost:8001/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=10)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin_headers():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def tech_headers():
    return _login("mike@aquaterra.com")


@pytest.fixture
def geocoded_customers():
    marker = uuid.uuid4().hex[:6]
    tech = f"phase17-tech-{marker}"
    docs = [
        {"id": f"phase17-a-{marker}", "tenant_id": _TENANT_ID,
          "name": "Alpha PhaseSeventeen", "first_name": "Alpha",
          "email": f"a-{marker}@ex.local", "phone": "+15550001111",
          "service_address": "1 Alpha Way", "is_active": True,
          "service_lat": 33.7, "service_lng": -112.3,
          "geocode_precision": "ROOFTOP",
          "service_days": ["mon"], "assigned_tech_ids": [tech]},
        {"id": f"phase17-b-{marker}", "tenant_id": _TENANT_ID,
          "name": "Bravo PhaseSeventeen", "first_name": "Bravo",
          "email": f"b-{marker}@ex.local", "phone": "+15550002222",
          "service_address": "2 Bravo Blvd", "is_active": True,
          "service_lat": 33.71, "service_lng": -112.31,
          "geocode_precision": "ROOFTOP",
          "service_days": ["mon"], "assigned_tech_ids": [tech]},
        {"id": f"phase17-c-{marker}", "tenant_id": _TENANT_ID,
          "name": "Charlie NoGeo", "first_name": "Charlie",
          "email": f"c-{marker}@ex.local", "phone": "+15550003333",
          "service_address": "3 Charlie Ct", "is_active": True,
          # NOT geocoded — must be omitted from board response.
          "service_days": ["mon"], "assigned_tech_ids": [tech]},
    ]
    _sync.customers.insert_many(docs)
    yield {"marker": marker, "tech": tech, "ids": [d["id"] for d in docs]}
    _sync.customers.delete_many({"id": {"$in": [d["id"] for d in docs]}})
    _sync.dispatch_route_orders.delete_many({"tenant_id": _TENANT_ID, "tech_user_id": tech})


def test_get_board_returns_geocoded_pins_only(admin_headers, geocoded_customers):
    r = requests.get(
        f"{API}/dispatch/board",
        params={"day": "mon", "tech_user_id": geocoded_customers["tech"]},
        headers=admin_headers, timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {p["customer_id"] for p in body["pins"]}
    assert f"phase17-a-{geocoded_customers['marker']}" in ids
    assert f"phase17-b-{geocoded_customers['marker']}" in ids
    # No-geocode row is filtered out.
    assert f"phase17-c-{geocoded_customers['marker']}" not in ids
    # tech_load enriched with tech id + count.
    assert any(t["tech_user_id"] == geocoded_customers["tech"]
               and t["count"] >= 2 for t in body["tech_load"])
    # route_stops populated on first visit (no saved order yet).
    assert len(body["route_stops"]) == 2


def test_technician_role_forbidden(tech_headers, geocoded_customers):
    r = requests.get(
        f"{API}/dispatch/board",
        params={"day": "mon", "tech_user_id": geocoded_customers["tech"]},
        headers=tech_headers, timeout=10,
    )
    assert r.status_code == 403


def test_apply_order_persists_and_reloads(admin_headers, geocoded_customers):
    aid = f"phase17-a-{geocoded_customers['marker']}"
    bid = f"phase17-b-{geocoded_customers['marker']}"
    # POST reversed order.
    r = requests.post(
        f"{API}/dispatch/board/apply-order",
        headers=admin_headers,
        json={"day": "mon", "tech_user_id": geocoded_customers["tech"],
               "ordered_customer_ids": [bid, aid]},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    # Next GET should surface the persisted order.
    r2 = requests.get(
        f"{API}/dispatch/board",
        params={"day": "mon", "tech_user_id": geocoded_customers["tech"]},
        headers=admin_headers, timeout=10,
    )
    body = r2.json()
    ids = [s["customer_id"] for s in body["route_stops"]]
    assert ids == [bid, aid]


def test_apply_order_rejects_day_all(admin_headers, geocoded_customers):
    r = requests.post(
        f"{API}/dispatch/board/apply-order",
        headers=admin_headers,
        json={"day": "all", "tech_user_id": geocoded_customers["tech"],
               "ordered_customer_ids": []},
        timeout=10,
    )
    assert r.status_code == 400


def test_optimize_requires_two_stops(admin_headers, geocoded_customers):
    aid = f"phase17-a-{geocoded_customers['marker']}"
    r = requests.post(
        f"{API}/dispatch/board/optimize",
        headers=admin_headers,
        json={"day": "mon", "tech_user_id": geocoded_customers["tech"],
               "stop_customer_ids": [aid]},
        timeout=10,
    )
    assert r.status_code == 400


def test_optimize_rejects_technician(tech_headers, geocoded_customers):
    aid = f"phase17-a-{geocoded_customers['marker']}"
    bid = f"phase17-b-{geocoded_customers['marker']}"
    r = requests.post(
        f"{API}/dispatch/board/optimize",
        headers=tech_headers,
        json={"day": "mon", "tech_user_id": geocoded_customers["tech"],
               "stop_customer_ids": [aid, bid]},
        timeout=10,
    )
    assert r.status_code == 403


# ─── Unit tests for the Google Directions wrapper ─────────────
# The endpoint-level test that verifies savings math would need to
# patch httpx inside the uvicorn process — mocks don't cross that
# boundary. Instead we unit-test the service module directly here.
import asyncio
import httpx


def test_optimize_route_parses_google_response(monkeypatch):
    """``optimize_route`` should decode the Routes API v2 payload into
    the {ordered_indices, polyline, total_*} shape the router
    consumes."""
    from services.google_maps import directions as _dir

    monkeypatch.setattr(_dir, "_API_KEY", "test-key")

    fake_payload = {
        "routes": [{
            "distanceMeters": 6437,
            "duration": "900s",
            "polyline": {"encodedPolyline": "abc_polyline"},
            "optimizedIntermediateWaypointIndex": [1, 0],
            "legs": [
                {"distanceMeters": 3218, "duration": "480s"},
                {"distanceMeters": 3219, "duration": "420s"},
            ],
        }],
    }

    class _MockClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            assert "routes.googleapis.com" in url
            assert headers.get("X-Goog-Api-Key") == "test-key"
            assert json.get("optimizeWaypointOrder") is True
            return httpx.Response(200, json=fake_payload)

    monkeypatch.setattr(_dir.httpx, "AsyncClient", _MockClient)

    result = asyncio.get_event_loop().run_until_complete(_dir.optimize_route(
        (33.7, -112.3),
        [(33.71, -112.31), (33.72, -112.32)],
    ))
    assert result is not None
    assert result["ordered_indices"] == [1, 0]
    assert result["polyline"] == "abc_polyline"
    assert result["total_distance_m"] == 6437
    assert result["total_duration_s"] == 900
    assert len(result["legs"]) == 2


def test_optimize_route_returns_none_on_empty_routes(monkeypatch):
    from services.google_maps import directions as _dir
    monkeypatch.setattr(_dir, "_API_KEY", "test-key")

    class _MockClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            return httpx.Response(200, json={"routes": []})

    monkeypatch.setattr(_dir.httpx, "AsyncClient", _MockClient)
    result = asyncio.get_event_loop().run_until_complete(_dir.optimize_route(
        (33.7, -112.3), [(33.71, -112.31)],
    ))
    assert result is None


def test_optimize_route_returns_none_without_api_key(monkeypatch):
    from services.google_maps import directions as _dir
    monkeypatch.setattr(_dir, "_API_KEY", "")
    result = asyncio.get_event_loop().run_until_complete(_dir.optimize_route(
        (33.7, -112.3), [(33.71, -112.31)],
    ))
    assert result is None
