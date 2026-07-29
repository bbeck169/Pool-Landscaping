"""MR1+MR2 · Feb-2026 — Public widget tests (feed + widget.js + preview)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

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

# For rate-limit test we hit the local backend directly (bypasses the
# ingress rate limiter that might sit between us and the public URL).
LOCAL = "http://localhost:8001/api"


def _super_headers():
    r = requests.post(f"{API}/auth/login",
                       json={"email": "super@aquaterra.com",
                              "password": "password123"}, timeout=15)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _tenant_slug() -> str:
    row = _sync.tenants.find_one({"name": {"$regex": "Vistancia"}},
                                    {"_id": 0, "slug": 1})
    if not row:
        row = _sync.tenants.find_one({}, {"_id": 0, "slug": 1})
    return row["slug"]


@pytest.fixture
def seeded_approved():
    """Insert a small approved+pending+rejected batch so we can assert
    the endpoint returns only the approved rows."""
    tid = _sync.tenants.find_one(
        {"slug": _tenant_slug()}, {"_id": 0, "id": 1})["id"]
    ids = []
    ids.append("mr1-smoke-approved")
    ids.append("mr1-smoke-pending")
    ids.append("mr1-smoke-rejected")
    _sync.public_checkins.delete_many({"id": {"$in": ids}})
    _sync.public_checkins.insert_many([
        {
            "id": ids[0], "tenant_id": tid, "state": "approved",
            "source_checkin_id": "sc-1",
            "source_job_id": "job-1",
            "submitted_by_user_id": "user-secret-1",
            "reviewer_notes": "internal note SECRET",
            "approved_by_user_id": "user-secret-2",
            "photo_license_ack": True,
            "service_name": "Weekly Pool", "service_category": "pool_service",
            "description": "Cleaned filter",
            "tags": ["pool"],
            "photos": [{"url": "https://x/photo-1.jpg", "alt": "front"}],
            "raw_address": {"street": "1234 Main St", "city": "Peoria",
                             "state": "AZ", "zip": "85383", "country": "US"},
            "masked_address": {"street_name": "Main St", "city": "Peoria",
                                 "state": "AZ"},
            "approved_at": "2026-02-14T10:00:00Z",
            "submitted_at": "2026-02-14T09:00:00Z",
        },
        {
            "id": ids[1], "tenant_id": tid, "state": "pending_review",
            "source_checkin_id": "sc-2",
            "submitted_by_user_id": "user-secret-3",
            "photo_license_ack": True,
            "service_name": "Pending — should NOT appear",
            "description": "",
            "tags": [], "photos": [],
            "raw_address": {"street": "5 Oak", "city": "Peoria",
                             "state": "AZ", "zip": "85383", "country": "US"},
            "submitted_at": "2026-02-14T08:00:00Z",
        },
        {
            "id": ids[2], "tenant_id": tid, "state": "rejected",
            "source_checkin_id": "sc-3",
            "reviewer_notes": "Not on brand",
            "photo_license_ack": True,
            "service_name": "Rejected — should NOT appear",
            "description": "",
            "tags": [], "photos": [],
            "submitted_at": "2026-02-14T07:00:00Z",
        },
    ])
    yield {"tenant_id": tid, "ids": ids}
    _sync.public_checkins.delete_many({"id": {"$in": ids}})


# ─── Feed: shape + approved-only ───────────────────────────────────

def test_feed_returns_only_approved(seeded_approved):
    r = requests.get(f"{API}/public/checkins/{_tenant_slug()}/feed",
                        params={"limit": 20}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [c["id"] for c in body["checkins"]]
    assert "mr1-smoke-approved" in ids
    assert "mr1-smoke-pending" not in ids
    assert "mr1-smoke-rejected" not in ids


def test_feed_sanitizes_no_pii(seeded_approved):
    r = requests.get(f"{API}/public/checkins/{_tenant_slug()}/feed",
                        params={"limit": 20}, timeout=15)
    body = r.json()
    approved = next(c for c in body["checkins"] if c["id"] == "mr1-smoke-approved")
    forbidden = {
        "raw_address", "submitted_by_user_id", "reviewer_notes",
        "source_checkin_id", "source_job_id", "reviewed_by_user_id",
        "approved_by_user_id", "photo_license_ack", "tenant_id",
    }
    leaked = forbidden.intersection(approved.keys())
    assert leaked == set(), f"leaked: {leaked}"
    # Positive assertions
    assert "service_name" in approved
    assert "photos" in approved
    assert approved["location"] == {
        "street_name": "Main St", "city": "Peoria", "state": "AZ"}
    # The internal 'SECRET' string must not appear anywhere in the body.
    assert "SECRET" not in r.text


def test_feed_first_item_keys_are_whitelist(seeded_approved):
    r = requests.get(f"{API}/public/checkins/{_tenant_slug()}/feed",
                        params={"limit": 20}, timeout=15)
    approved = next(c for c in r.json()["checkins"]
                     if c["id"] == "mr1-smoke-approved")
    allowed = {"id", "service_name", "service_category", "description",
                "tags", "photos", "location", "completed_at"}
    assert set(approved.keys()) == allowed, sorted(approved.keys())


def test_feed_returns_tenant_metadata_only(seeded_approved):
    r = requests.get(f"{API}/public/checkins/{_tenant_slug()}/feed",
                        timeout=15)
    body = r.json()
    tenant = body["tenant"]
    assert set(tenant.keys()) == {
        "name", "slug", "logo_url", "brand_primary", "brand_secondary"}
    # No internal tenant.id or settings.
    assert "id" not in tenant
    assert "settings" not in tenant


def test_feed_wrong_slug_404():
    r = requests.get(f"{API}/public/checkins/definitely-no-such-slug/feed",
                        timeout=15)
    assert r.status_code == 404, r.text


def test_feed_cors_headers_present():
    r = requests.get(f"{API}/public/checkins/{_tenant_slug()}/feed",
                        timeout=15)
    assert r.headers.get("Access-Control-Allow-Origin") == "*"


def test_feed_limit_capped_at_50(seeded_approved):
    r = requests.get(f"{API}/public/checkins/{_tenant_slug()}/feed",
                        params={"limit": 5000}, timeout=15)
    assert r.status_code == 200
    assert len(r.json()["checkins"]) <= 50


def test_feed_cache_ttl_advisory(seeded_approved):
    r = requests.get(f"{API}/public/checkins/{_tenant_slug()}/feed",
                        timeout=15)
    body = r.json()
    assert body["cache_ttl_s"] == 7 * 24 * 60 * 60


def test_feed_rate_limit_returns_429():
    """Hit the local backend fast enough to trigger the per-IP limiter
    (60 rpm). We use the local :8001 so the ingress can't reorder or
    reroute us."""
    url = f"{LOCAL}/public/checkins/{_tenant_slug()}/feed"
    # Best-effort. Some environments have the limiter primed already,
    # so this test simply asserts we can produce a 429 within N rapid
    # calls, or that we ever see one.
    saw_429 = False
    for _ in range(80):
        r = requests.get(url, timeout=5)
        if r.status_code == 429:
            saw_429 = True
            break
    assert saw_429, "expected to trigger 429 within 80 rapid requests"


# ─── widget.js ─────────────────────────────────────────────────────

def test_widget_js_served_as_javascript():
    r = requests.get(f"{API}/widget.js", timeout=10)
    assert r.status_code == 200
    ct = r.headers.get("Content-Type", "")
    assert "javascript" in ct, ct
    body = r.text
    for hint in ("data-tenant", "attachShadow", "application/ld+json",
                  "public/checkins"):
        assert hint in body, f"missing marker {hint!r} in widget.js"


def test_widget_js_cors_headers():
    r = requests.get(f"{API}/widget.js", timeout=10)
    assert r.headers.get("Access-Control-Allow-Origin") == "*"


# ─── Preview page (admin+) ─────────────────────────────────────────

def test_preview_returns_html_public():
    """The preview page renders the SAME public widget an external
    site would embed; it doesn't need admin auth. X-Frame-Options
    prevents third-party iframing."""
    r = requests.get(f"{API}/widget/preview/{_tenant_slug()}", timeout=15)
    assert r.status_code == 200
    ct = r.headers.get("Content-Type", "")
    assert "html" in ct
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"
    for hint in ("data-tenant", "widget.js", "Widget Preview"):
        assert hint in r.text


def test_preview_wrong_slug_404():
    r = requests.get(f"{API}/widget/preview/definitely-nope-slug", timeout=10)
    assert r.status_code == 404
