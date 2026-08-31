"""Feb-2026 · Widget-Embed extension · map.html + pins JSON contract."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from fastapi import Request

from routers import public_checkins_map as pcm
from routers import public_widget as pw
from tests._map_endpoint_fakes import make_map_db


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _fake_request():
    """Minimal ``Request`` shim for the rate-limit + client-ip
    helpers used by the map endpoints."""
    scope = {
        "type": "http", "method": "GET", "path": "/",
        "headers": [], "query_string": b"",
        "client": ("127.0.0.1", 0),
    }
    return Request(scope)


def _fresh_bucket():
    """Rate-limit helper in ``public_widget`` shares process-wide
    state; clear between tests so 429 assertions are deterministic."""
    if hasattr(pw, "_ip_buckets"):
        pw._ip_buckets.clear()


def test_map_html_renders_leaflet_scaffold(monkeypatch):
    _fresh_bucket()
    fake = make_map_db(
        tenants=[{"id": "t1", "name": "AquaTerra Pools",
                   "slug": "aquaterra", "settings":
                    {"website_url": "https://aquaterra.example",
                     "phone": "+15551112222",
                     "business_card": {"city": "Peoria", "state": "AZ"}}}],
        checkins=[{
            "id": "pc-1", "tenant_id": "t1", "state": "approved",
            "lat_public": 33.5722, "lng_public": -112.3237,
            "service_name": "Pool Cleaning",
            "area_label": "Peoria, AZ",
            "completed_at_month_year": "August 2026",
            "approved_at": _iso_days_ago(5),
        }],
    )
    monkeypatch.setattr(pcm, "db", fake)
    monkeypatch.setattr(pw, "db", fake)

    resp = _run(pcm.public_map_html("aquaterra", request=_fake_request()))
    assert resp.status_code == 200
    body = resp.body.decode("utf-8")
    # Scaffold assertions.
    assert "<title>AquaTerra Pools · Recent Service Check-ins</title>" in body
    assert 'data-testid="widget-map-container"' in body
    assert "leaflet.js" in body
    assert "leaflet.markercluster.js" in body
    # Pin surfaces in the inline JS.
    assert '"lat": 33.572' in body or '"lat":33.572' in body \
           or "33.572" in body
    assert "Pool Cleaning" in body
    assert "Peoria, AZ" in body


def test_map_html_includes_schema_org_json_ld(monkeypatch):
    _fresh_bucket()
    fake = make_map_db(
        tenants=[{"id": "t1", "name": "AquaTerra Pools",
                   "slug": "aquaterra", "settings":
                    {"website_url": "https://aquaterra.example",
                     "phone": "+15551112222",
                     "business_card": {"city": "Peoria", "state": "AZ"}}}],
        checkins=[
            {"id": "pc-1", "tenant_id": "t1", "state": "approved",
             "lat_public": 33.57, "lng_public": -112.32,
             "service_name": "Pool Cleaning",
             "area_label": "Peoria, AZ",
             "completed_at_month_year": "August 2026",
             "approved_at": _iso_days_ago(5)},
            {"id": "pc-2", "tenant_id": "t1", "state": "approved",
             "lat_public": 33.65, "lng_public": -112.15,
             "service_name": "Landscape Trim",
             "area_label": "Glendale, AZ",
             "completed_at_month_year": "August 2026",
             "approved_at": _iso_days_ago(3)},
            {"id": "pc-3", "tenant_id": "t1", "state": "approved",
             "lat_public": 33.575, "lng_public": -112.325,
             "service_name": "Pool Cleaning",
             "area_label": "Peoria, AZ",   # dup — should dedupe
             "completed_at_month_year": "August 2026",
             "approved_at": _iso_days_ago(1)},
        ],
    )
    monkeypatch.setattr(pcm, "db", fake)
    monkeypatch.setattr(pw, "db", fake)

    resp = _run(pcm.public_map_html("aquaterra", request=_fake_request()))
    body = resp.body.decode("utf-8")

    assert '<script type="application/ld+json"' in body
    # Extract the JSON-LD content and parse.
    start = body.index("application/ld+json")
    ld_start = body.index(">", start) + 1
    ld_end = body.index("</script>", ld_start)
    ld = json.loads(body[ld_start:ld_end])

    assert ld["@context"] == "https://schema.org"
    assert ld["@type"] == "LocalBusiness"
    assert ld["name"] == "AquaTerra Pools"
    assert ld["telephone"] == "+15551112222"
    assert ld["url"] == "https://aquaterra.example"
    # Address block from settings.business_card.
    assert ld["address"]["addressLocality"] == "Peoria"
    assert ld["address"]["addressRegion"] == "AZ"
    # areaServed dedupes Peoria — 2 unique labels.
    areas = ld["areaServed"]
    assert len(areas) == 2
    assert {a["name"] for a in areas} == {"Peoria, AZ", "Glendale, AZ"}
    assert all(a["@type"] == "Place" for a in areas)
    assert all(a["geo"]["@type"] == "GeoCoordinates" for a in areas)
    # makesOffer dedupes Pool Cleaning — 2 unique services.
    services = ld["makesOffer"]
    assert {s["itemOffered"]["name"] for s in services} == {
        "Pool Cleaning", "Landscape Trim",
    }
    assert all(s["itemOffered"]["@type"] == "Service" for s in services)


def test_pins_endpoint_returns_obfuscated_only(monkeypatch):
    _fresh_bucket()
    fake = make_map_db(
        tenants=[{"id": "t1", "name": "T", "slug": "t-slug",
                   "settings": {}}],
        checkins=[{
            "id": "pc-1", "tenant_id": "t1", "state": "approved",
            "lat_public": 33.5, "lng_public": -112.0,
            "service_name": "Pool Cleaning",
            "area_label": "Peoria, AZ",
            "completed_at_month_year": "August 2026",
            "approved_at": _iso_days_ago(5),
        }],
    )
    monkeypatch.setattr(pcm, "db", fake)
    monkeypatch.setattr(pw, "db", fake)

    class _RespShim:
        headers = {}
    resp_shim = _RespShim()
    payload = _run(pcm.public_pins("t-slug", request=_fake_request(),
                                       response=resp_shim))

    assert payload["count"] == 1
    pin = payload["pins"][0]
    # ONLY these keys allowed.
    assert set(pin.keys()) == {"lat", "lng", "service_type",
                                 "completed_at_month_year",
                                 "area_label"}
    assert pin["lat"] == 33.5
    assert pin["lng"] == -112.0
    assert pin["service_type"] == "Pool Cleaning"
