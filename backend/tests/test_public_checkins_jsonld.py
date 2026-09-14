"""Phase Feb-2026 · Public Check-ins Feed — JSON-LD structured data tests.

Covers the pure builder (schema shape, description generator, geo
inclusion rules) plus the endpoint smoke — feed JSON, server-rendered
``feed.html``, and the widget preview HTML all carry the same
``LocalBusiness`` + ``ItemList`` schemas.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

from services.public_checkins_jsonld import (
    build_description,
    build_feed_jsonld,
    build_item_list,
    build_local_business,
    build_service_block,
)


_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = MongoClient(_MONGO_URL)[_DB_NAME]

_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL")
        or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE
API = f"{BASE}/api"


def _tenant_slug() -> str:
    row = _sync.tenants.find_one(
        {"name": {"$regex": "Vistancia"}}, {"_id": 0, "slug": 1},
    )
    if not row:
        row = _sync.tenants.find_one({}, {"_id": 0, "slug": 1})
    return row["slug"]


@pytest.fixture
def seeded_two_approved():
    """One with coords (geo), one without (fallback)."""
    tid = _sync.tenants.find_one(
        {"slug": _tenant_slug()}, {"_id": 0, "id": 1})["id"]
    ids = ["ld-smoke-with-coords", "ld-smoke-without-coords"]
    _sync.public_checkins.delete_many({"id": {"$in": ids}})
    _sync.public_checkins.insert_many([
        {
            "id": ids[0], "tenant_id": tid, "state": "approved",
            "source_checkin_id": "ld-sc-1",
            "service_name": "Pool Service",
            "service_category": "pool_service",
            "description": "cleaned filter",
            "tags": ["pool"], "photos": [],
            "raw_address": {"street": "1 A", "city": "Peoria",
                             "state": "AZ", "zip": "85383"},
            "masked_address": {"street_name": "A St", "city": "Peoria",
                                 "state": "AZ"},
            "lat_public": 33.7801,
            "lng_public": -112.3428,
            "approved_at": "2026-02-14T10:00:00Z",
            "submitted_at": "2026-02-14T09:00:00Z",
        },
        {
            "id": ids[1], "tenant_id": tid, "state": "approved",
            "source_checkin_id": "ld-sc-2",
            "service_name": "Landscape Trim",
            "service_category": "landscape",
            "description": "",
            "tags": [], "photos": [],
            "raw_address": {"street": "2 B", "city": "Sun City",
                             "state": "AZ", "zip": "85351"},
            "masked_address": {"street_name": "B Ave", "city": "Sun City",
                                 "state": "AZ"},
            # deliberately no coords → no geo block
            "approved_at": "2026-02-13T10:00:00Z",
            "submitted_at": "2026-02-13T09:00:00Z",
        },
    ])
    yield {"tenant_id": tid, "ids": ids}
    _sync.public_checkins.delete_many({"id": {"$in": ids}})


# ═══════════════════════ pure builder ═══════════════════════════════
class TestDescriptionGenerator:
    def test_full_locality_and_region(self):
        assert build_description("Pool Service", "Peoria", "AZ") == \
            "Pool Service service completed in Peoria, AZ."

    def test_with_zip(self):
        assert build_description("Pool Service", "Peoria", "AZ", "85383") == \
            "Pool Service service completed in Peoria, AZ 85383."

    def test_only_city(self):
        assert build_description("Landscape", "Peoria", "") == \
            "Landscape service completed in Peoria."

    def test_neutral_fallback(self):
        assert build_description(None, None, None) == \
            "Service completed in the local area."

    def test_underscore_type_gets_sentence_cased(self):
        assert build_description("pool_service", "Peoria", "AZ") == \
            "Pool service service completed in Peoria, AZ."


class TestLocalBusiness:
    def test_shape(self):
        tenant = {"name": "Pool & Landscaping"}
        card = {"company_name": "Pool & Landscaping",
                "phone": "602-887-4400",
                "website_url": "https://plofv.com",
                "service_area": "Peoria, Arizona"}
        lb = build_local_business(tenant, card)
        assert lb["@context"] == "https://schema.org"
        assert lb["@type"] == "LocalBusiness"
        assert lb["name"] == "Pool & Landscaping"
        assert lb["telephone"] == "602-887-4400"
        assert lb["url"] == "https://plofv.com"
        assert lb["address"] == {
            "@type": "PostalAddress",
            "addressLocality": "Peoria",
            "addressRegion": "Arizona",
        }

    def test_omits_empty_fields(self):
        lb = build_local_business({"name": "X"}, {})
        assert "telephone" not in lb
        assert "url" not in lb
        assert "address" not in lb


class TestServiceBlock:
    def test_geo_included_when_coords_present(self):
        c = {"service_name": "Pool",
             "masked_address": {"city": "Peoria", "state": "AZ"},
             "lat_public": 33.5, "lng_public": -112.3}
        s = build_service_block(c, provider_name="Biz")
        assert s["geo"] == {"@type": "GeoCoordinates",
                             "latitude": 33.5, "longitude": -112.3}
        assert s["areaServed"]["addressLocality"] == "Peoria"
        assert s["areaServed"]["addressRegion"] == "AZ"
        assert s["serviceType"] == "Pool"
        assert "completed in Peoria, AZ" in s["description"]

    def test_geo_omitted_when_coords_missing(self):
        c = {"service_name": "Pool",
             "masked_address": {"city": "Peoria", "state": "AZ"}}
        s = build_service_block(c, provider_name="Biz")
        assert "geo" not in s

    def test_geo_omitted_on_malformed_coords(self):
        c = {"service_name": "Pool",
             "masked_address": {"city": "P", "state": "A"},
             "lat_public": "not-a-number", "lng_public": "nope"}
        s = build_service_block(c, provider_name="Biz")
        assert "geo" not in s


class TestItemList:
    def test_shape(self):
        rows = [
            {"service_name": "Pool", "masked_address": {"city": "P", "state": "A"}},
            {"service_name": "Trim", "masked_address": {"city": "S", "state": "A"}},
        ]
        il = build_item_list(rows, provider_name="Biz")
        assert il["@type"] == "ItemList"
        assert len(il["itemListElement"]) == 2
        assert il["itemListElement"][0]["@type"] == "ListItem"
        assert il["itemListElement"][0]["position"] == 1
        assert il["itemListElement"][1]["position"] == 2
        assert il["itemListElement"][0]["item"]["@type"] == "Service"


class TestFeedJsonLd:
    def test_top_level_composition(self):
        payload = build_feed_jsonld(
            {"name": "Biz", "slug": "biz"},
            {"company_name": "Biz", "service_area": "Peoria, AZ",
             "phone": "555", "website_url": "https://biz.example"},
            [{"service_name": "Pool",
              "masked_address": {"city": "Peoria", "state": "AZ"},
              "lat_public": 33.5, "lng_public": -112.3}],
        )
        assert set(payload.keys()) == {"local_business", "item_list"}
        assert payload["local_business"]["@type"] == "LocalBusiness"
        assert payload["item_list"]["@type"] == "ItemList"


# ═══════════════════════ endpoint smoke ═════════════════════════════
class TestFeedJsonEndpoint:
    def test_feed_json_carries_jsonld(self, seeded_two_approved):
        r = requests.get(
            f"{API}/public/checkins/{_tenant_slug()}/feed",
            params={"limit": 20}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "jsonld" in body
        ld = body["jsonld"]
        assert ld["local_business"]["@type"] == "LocalBusiness"
        assert ld["item_list"]["@type"] == "ItemList"
        # Assert at least one Service is emitted per seeded check-in
        items = ld["item_list"]["itemListElement"]
        assert any(
            it["item"].get("serviceType") == "Pool Service" for it in items
        )
        # The geo block appears on the with-coords row only.
        with_coords = [it for it in items
                        if it["item"].get("serviceType") == "Pool Service"]
        assert with_coords and "geo" in with_coords[0]["item"]
        without_coords = [it for it in items
                          if it["item"].get("serviceType") == "Landscape Trim"]
        assert without_coords and "geo" not in without_coords[0]["item"]


class TestFeedHtmlEndpoint:
    def test_returns_html_with_jsonld_blocks(self, seeded_two_approved):
        r = requests.get(
            f"{API}/public/checkins/{_tenant_slug()}/feed.html",
            timeout=15,
        )
        assert r.status_code == 200, r.text
        assert "html" in r.headers.get("Content-Type", "")
        # Two blocks: LocalBusiness + ItemList
        assert r.text.count('application/ld+json') >= 2
        assert "LocalBusiness" in r.text
        assert "ItemList" in r.text
        # Parse the emitted JSON-LD scripts and make sure they're
        # valid JSON (no truncation / no broken escapes).
        matches = re.findall(
            r'<script type="application/ld\+json"[^>]*>(.*?)</script>',
            r.text, flags=re.DOTALL,
        )
        assert len(matches) >= 2
        for m in matches:
            parsed = json.loads(m)
            assert "@context" in parsed
            assert "@type" in parsed

    def test_cors_enabled(self, seeded_two_approved):
        r = requests.get(
            f"{API}/public/checkins/{_tenant_slug()}/feed.html",
            timeout=15,
        )
        assert r.headers.get("Access-Control-Allow-Origin") == "*"


class TestWidgetPreviewParity:
    def test_preview_html_carries_same_jsonld(self, seeded_two_approved):
        r = requests.get(
            f"{API}/widget/preview/{_tenant_slug()}",
            timeout=15,
        )
        assert r.status_code == 200
        assert r.text.count('application/ld+json') >= 2
        matches = re.findall(
            r'<script type="application/ld\+json"[^>]*>(.*?)</script>',
            r.text, flags=re.DOTALL,
        )
        types = {json.loads(m).get("@type") for m in matches}
        assert "LocalBusiness" in types
        assert "ItemList" in types
