"""Phase SEO-A · Feb-2026 — Free SEO auditor tests.

Split into two flavours:

* Unit tests for pure parsers / scorers / SSRF guards — no network,
  no DB. Fast, deterministic.
* Live-server tests for the ``/api/seo/scans*`` endpoints — same
  paradigm as :mod:`test_moderation_bulk` (talks to the running
  backend at ``BACKEND_API_URL`` / ``REACT_APP_BACKEND_URL``).
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

# ─── Env / API base ────────────────────────────────────────────────

_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = MongoClient(_MONGO_URL)[_DB_NAME]

_REACT_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_REACT = dotenv_values(_REACT_ENV) if _REACT_ENV.is_file() else {}
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL") or os.environ.get(
    "REACT_APP_BACKEND_URL")
API = os.environ.get("BACKEND_API_URL") or (
    (_PUBLIC_URL.rstrip("/") + "/api") if _PUBLIC_URL else
    "http://localhost:8001/api"
)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdr(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


def _super_headers():
    return _hdr("super@aquaterra.com")


def _customer_headers():
    return _hdr("customer@aquaterra.com")


def _tech_headers():
    tech = _sync.users.find_one({"role": "technician",
                                  "email": {"$exists": True, "$ne": None}})
    return _hdr(tech["email"])


# ═══════════════════════ UNIT TESTS (no network) ══════════════════

class TestParseOnPage:
    def test_extracts_title_and_meta(self):
        from services.seo_scanner import parse_on_page
        html = (
            b"<html lang='en'><head>"
            b"<title>Sunbelt Pool Service</title>"
            b"<meta name='description' content='"
            b"Weekly pool cleaning and equipment service in Phoenix, AZ.'>"
            b"<meta name='viewport' content='width=device-width'>"
            b"<link rel='canonical' href='https://example.com/'>"
            b"</head><body><h1>Welcome</h1></body></html>"
        )
        r = parse_on_page(html, "https://example.com/")
        assert r["title"]["present"] is True
        assert r["title"]["value"] == "Sunbelt Pool Service"
        assert r["title"].get("issue") in (None, "too_short_19")  # 19 chars
        assert r["meta_description"]["present"] is True
        assert r["canonical"]["present"] is True
        assert r["viewport"]["present"] is True
        assert r["h1"]["count"] == 1

    def test_flags_missing_title_and_meta(self):
        from services.seo_scanner import parse_on_page
        html = b"<html><head></head><body><h1>A</h1><h1>B</h1></body></html>"
        r = parse_on_page(html, "https://example.com/")
        assert r["title"]["present"] is False
        assert r["title"]["issue"] == "missing"
        assert r["meta_description"]["present"] is False
        assert r["meta_description"]["issue"] == "missing"
        assert r["h1"]["count"] == 2
        assert r["h1"]["issue"] == "multiple_2"
        assert r["canonical"]["present"] is False

    def test_counts_missing_img_alt(self):
        from services.seo_scanner import parse_on_page
        html = (b"<html><body>"
                b"<img src='a.jpg' alt='cover'>"
                b"<img src='b.jpg'>"
                b"<img src='c.jpg' alt=''>"
                b"</body></html>")
        r = parse_on_page(html, "https://example.com/")
        assert r["images_total"] == 3
        assert r["images_missing_alt"] == 2


class TestSchemaOrg:
    def test_multi_block_valid(self):
        from services.seo_scanner import parse_schema_org
        html = (b'<html><body>'
                b'<script type="application/ld+json">'
                b'{"@type":"LocalBusiness","name":"Sunbelt"}</script>'
                b'<script type="application/ld+json">'
                b'{"@type":"Service","name":"Pool cleaning"}</script>'
                b'</body></html>')
        r = parse_schema_org(html)
        assert r["blocks_found"] == 2
        assert r["valid"] is True
        assert set(r["types"]) == {"LocalBusiness", "Service"}
        assert r["warnings"] == []

    def test_malformed_json_produces_warning(self):
        from services.seo_scanner import parse_schema_org
        html = (b'<html><body>'
                b'<script type="application/ld+json">not-json{</script>'
                b'</body></html>')
        r = parse_schema_org(html)
        assert r["blocks_found"] == 1
        assert r["valid"] is False
        assert any("parse_error" in w for w in r["warnings"])


class TestSecurityHeaders:
    def test_https_and_hsts_recognized(self):
        from services.seo_scanner import security_headers
        r = security_headers("https",
                                {"Strict-Transport-Security": "max-age=31536000",
                                 "X-Content-Type-Options": "nosniff",
                                 "Referrer-Policy": "no-referrer"})
        assert r["https"] is True
        assert r["hsts"] is True
        assert r["x_content_type_options"] is True
        assert r["referrer_policy"] is True
        assert r["content_security_policy"] is False

    def test_http_scheme_flags_no_https(self):
        from services.seo_scanner import security_headers
        r = security_headers("http", {})
        assert r["https"] is False


class TestComputeScore:
    def _canned(self, **overrides):
        base = {
            "on_page": {
                "title": {"present": True, "length": 40},
                "meta_description": {"present": True, "length": 120},
                "h1": {"count": 1},
                "canonical": {"present": True},
                "og_tags": {"present": True},
                "viewport": {"present": True},
                "images_total": 5,
                "images_missing_alt": 0,
                "broken_internal_links": [],
            },
            "schema_org": {"types": ["LocalBusiness"]},
            "performance": {
                "pagespeed_mobile_score": 100,
                "pagespeed_desktop_score": 100,
            },
            "security": {"https": True},
            "robots_txt": {"present": True},
            "sitemap_xml": {"present": True},
        }
        base.update(overrides or {})
        return base

    def test_perfect_score_is_100(self):
        from services.seo_scanner import compute_score
        score, counts = compute_score(self._canned())
        assert score == 100
        assert counts == {"critical": 0, "warning": 0, "notice": 0}

    def test_missing_title_drops_score_and_adds_critical(self):
        from services.seo_scanner import compute_score
        r = self._canned()
        r["on_page"]["title"] = {"present": False, "length": 0}
        score, counts = compute_score(r)
        assert score < 100
        assert counts["critical"] >= 1

    def test_no_https_flags_critical(self):
        from services.seo_scanner import compute_score
        r = self._canned()
        r["security"]["https"] = False
        score, counts = compute_score(r)
        assert score <= 95
        assert counts["critical"] >= 1

    def test_partial_image_alt_coverage(self):
        from services.seo_scanner import compute_score
        r = self._canned()
        r["on_page"]["images_total"] = 10
        r["on_page"]["images_missing_alt"] = 5
        score, counts = compute_score(r)
        # Missing 5/10 alt loses 5 points and adds a warning.
        assert score == 95
        assert counts["warning"] >= 1


class TestSsrfGuards:
    def test_localhost_blocked(self):
        from services.seo_scanner import normalize_url, validate_target
        with pytest.raises(ValueError) as ei:
            validate_target(normalize_url("http://localhost/"))
        assert "blocked_host" in str(ei.value) or "private_ip" in str(ei.value)

    def test_private_ip_blocked(self):
        from services.seo_scanner import validate_target
        with pytest.raises(ValueError):
            validate_target("http://192.168.1.1/")

    def test_preview_domain_blocked(self):
        from services.seo_scanner import validate_target
        with pytest.raises(ValueError) as ei:
            validate_target("https://x.preview.emergentagent.com/")
        assert "blocked_host" in str(ei.value)


# ═══════════════════════ LIVE-SERVER TESTS ════════════════════════

@pytest.fixture
def cleanup_scans():
    """Purge any scans this test file wrote before/after."""
    _sync.seo_scans.delete_many({"target_url": {"$regex": r"seotest-"}})
    yield
    _sync.seo_scans.delete_many({"target_url": {"$regex": r"seotest-"}})


class TestSeoScanEndpoints:
    def test_customer_forbidden(self):
        r = requests.post(f"{API}/seo/scans",
                            json={"target_url": "https://example.com"},
                            headers=_customer_headers(), timeout=15)
        assert r.status_code == 403

    def test_tech_forbidden(self):
        r = requests.post(f"{API}/seo/scans",
                            json={"target_url": "https://example.com"},
                            headers=_tech_headers(), timeout=15)
        assert r.status_code == 403

    def test_localhost_rejected_400(self):
        r = requests.post(f"{API}/seo/scans",
                            json={"target_url": "http://localhost/"},
                            headers=_super_headers(), timeout=15)
        assert r.status_code == 400
        assert "blocked_host" in r.text or "private_ip" in r.text

    def test_preview_domain_rejected_400(self):
        r = requests.post(f"{API}/seo/scans",
                            json={"target_url":
                                    "https://x.preview.emergentagent.com/"},
                            headers=_super_headers(), timeout=15)
        assert r.status_code == 400

    def test_async_scan_creates_queued_row(self, cleanup_scans):
        # Use a bogus target that will resolve so validate_target passes
        # but we don't actually care about the scan result — we're
        # testing that the queued row is created immediately.
        r = requests.post(f"{API}/seo/scans",
                            json={"target_url":
                                    "https://example.com/seotest-async",
                                    "async": True},
                            headers=_super_headers(), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "queued"
        assert body["scan_id"]
        # Confirm the row landed in Mongo.
        row = _sync.seo_scans.find_one({"id": body["scan_id"]})
        assert row is not None
        assert row["status"] in ("queued", "running", "complete")

    def test_sync_scan_returns_results(self, cleanup_scans):
        # ``async=false`` — waits for the full scan. example.com is
        # tiny and returns quickly; PSI may still take ~20-30s. Bump
        # timeout to 90s.
        r = requests.post(f"{API}/seo/scans",
                            json={"target_url":
                                    "https://example.com/seotest-sync",
                                    "async": False},
                            headers=_super_headers(), timeout=90)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] in ("complete", "error")
        if body["status"] == "complete":
            res = body["results"]
            assert "on_page" in res
            assert "schema_org" in res
            assert "score" in res
            assert 0 <= res["score"] <= 100

    def test_list_scans_scoped_to_tenant(self, cleanup_scans):
        # Seed one row for the super_admin's tenant.
        tid = _sync.users.find_one(
            {"email": "super@aquaterra.com"})["tenant_id"]
        # super_admin has no tenant_id — use aquaterra explicitly.
        if not tid:
            tid = _sync.tenants.find_one({"slug": "aquaterra"})["id"]
        _sync.seo_scans.insert_one({
            "id": str(uuid.uuid4()),
            "tenant_id": tid,
            "requested_by_user_id": "seed",
            "requested_at": "2026-02-14T09:00:00Z",
            "target_url": "https://example.com/seotest-list",
            "status": "complete",
            "results": {"score": 82,
                         "issue_count": {"critical": 1, "warning": 2,
                                          "notice": 0}},
        })
        h = {**_super_headers(), "X-Tenant-Slug": "aquaterra"}
        r = requests.get(f"{API}/seo/scans?limit=50", headers=h, timeout=15)
        assert r.status_code == 200
        items = r.json()["items"]
        # Our seeded row must appear.
        hits = [i for i in items
                if i.get("target_url") == "https://example.com/seotest-list"]
        assert hits, "seeded scan not returned"
        assert hits[0]["results"]["score"] == 82

    def test_history_returns_score_over_time(self, cleanup_scans):
        tid = _sync.tenants.find_one({"slug": "aquaterra"})["id"]
        for i, sc in enumerate([50, 70, 88]):
            _sync.seo_scans.insert_one({
                "id": str(uuid.uuid4()),
                "tenant_id": tid,
                "requested_by_user_id": "seed",
                "requested_at": f"2026-02-1{i}T09:00:00Z",
                "target_url": "https://example.com/seotest-hist",
                "status": "complete",
                "results": {"score": sc,
                             "issue_count": {"critical": 0,
                                              "warning": 0, "notice": 0}},
            })
        h = {**_super_headers(), "X-Tenant-Slug": "aquaterra"}
        r = requests.get(
            f"{API}/seo/scans/history"
            f"?target_url=https://example.com/seotest-hist",
            headers=h, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["target_url"] == "https://example.com/seotest-hist"
        assert len(body["points"]) == 3
        # Sorted oldest -> newest (reversed inside handler).
        assert [p["score"] for p in body["points"]] == [50, 70, 88]
