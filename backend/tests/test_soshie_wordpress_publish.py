"""Feb-2026 · Soshie · WordPress publish + platforms + audit + idem tests.

Covers the P2 ship: adapter check + publish, POST /soshie/publish
fan-out, GET /soshie/platforms grid, idempotency replay, audit
log row written.

The WordPress publisher is mocked at the ``_publish_to_wp`` seam
so we never hit the real WP site during tests.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = _shared_client()
_db = _shared_db()
def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _login(email: str = "admin@aquaterra.com") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h() -> dict:
    return {"Authorization": f"Bearer {_login()}"}


# ═════════════════════════════════════════════════════════════════════
# 1 · GET /soshie/platforms grid — WordPress green + 6 stubs red
# ═════════════════════════════════════════════════════════════════════
def test_platforms_grid_wordpress_green_stubs_red(admin_h):
    r = requests.get(f"{API}/soshie/platforms",
                      headers=admin_h, timeout=10)
    assert r.status_code == 200, r.text
    grid = r.json()["platforms"]
    by_name = {p["platform"]: p for p in grid}
    # Every platform except X (dropped) is present — 8 total after
    # GBP addition.
    for name in ("wordpress", "gbp", "facebook", "instagram",
                  "linkedin", "youtube", "reddit", "tiktok"):
        assert name in by_name, f"missing platform: {name}"
    assert "x" not in by_name, "X must NOT appear — dropped from scope"
    assert "twitter" not in by_name
    # WordPress creds ARE configured on this preview env (.env).
    assert by_name["wordpress"]["ok"] is True, by_name["wordpress"]
    # GBP is code-live but OAuth typically not completed on preview
    # env — we just assert the detail is one of the tri-state
    # messages (either config missing, connect missing, or ready).
    gbp = by_name["gbp"]
    assert isinstance(gbp["ok"], bool)
    if not gbp["ok"]:
        assert any(k in gbp["detail"] for k in
                     ("not configured", "not connected"))
    # All 6 pure stubs pending.
    for name in ("facebook", "instagram", "linkedin", "youtube",
                  "reddit", "tiktok"):
        entry = by_name[name]
        assert entry["ok"] is False, entry
        assert "Pending operator setup" in entry["detail"], entry


# ═════════════════════════════════════════════════════════════════════
# 2 · POST /soshie/publish → fan-out semantics (stub platforms)
# ═════════════════════════════════════════════════════════════════════
def test_publish_fan_out_stubs_return_not_configured_per_platform(admin_h):
    """The router runs the fan-out and captures per-platform
    results without letting one adapter's failure block another.
    We test this against two text-supporting stub adapters
    (facebook + reddit) so the fan-out mechanics are exercised
    without needing to reach WP or invoke a video-only platform."""
    r = requests.post(
        f"{API}/soshie/publish", headers=admin_h,
        json={"platforms": ["facebook", "reddit"],
                "text": f"stub fan-out {uuid.uuid4().hex[:6]}",
                "title": "Pytest stubs fan-out"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    by_platform = {row["platform"]: row for row in body["results"]}
    assert by_platform["facebook"]["status"] == "not_configured"
    assert "Pending operator setup" in by_platform["facebook"]["error"]
    assert by_platform["reddit"]["status"] == "not_configured"
    assert "Pending operator setup" in by_platform["reddit"]["error"]
    # Failed rows landed in social_posts audit collection.
    audit = list(_db.social_posts.find(
        {"content_text": {"$exists": False}, "status": "failed"},
    ).sort("published_at", -1).limit(5))
    assert any(a.get("platform") == "facebook" for a in audit)
    assert any(a.get("platform") == "reddit" for a in audit)


# ═════════════════════════════════════════════════════════════════════
# 3 · POST /soshie/publish idempotency — same key → cached response
# ═════════════════════════════════════════════════════════════════════
def test_publish_idempotency_replay_returns_cached(admin_h):
    """Uses two stub platforms so we exercise idempotency without
    touching WP. Second call with the SAME X-Idempotency-Key MUST
    return the byte-identical response AND write no new
    social_posts rows on the replay."""
    idem = str(uuid.uuid4())
    payload = {"platforms": ["facebook", "reddit"],
                "text": f"idem test {uuid.uuid4().hex[:6]}",
                "title": "Pytest Soshie Idem"}
    r1 = requests.post(f"{API}/soshie/publish",
                        headers={**admin_h, "X-Idempotency-Key": idem},
                        json=payload, timeout=15).json()
    # Count failed rows post-first-call.
    count_after_1 = _db.social_posts.count_documents(
        {"platform": {"$in": ["facebook", "reddit"]},
          "status": "failed"})
    r2 = requests.post(f"{API}/soshie/publish",
                        headers={**admin_h, "X-Idempotency-Key": idem},
                        json=payload, timeout=15).json()
    assert r1 == r2, "replay MUST return cached response verbatim"
    # Replay should NOT write additional social_posts rows.
    count_after_2 = _db.social_posts.count_documents(
        {"platform": {"$in": ["facebook", "reddit"]},
          "status": "failed"})
    assert count_after_1 == count_after_2, \
        f"replay wrote extra rows: {count_after_1} -> {count_after_2}"


# ═════════════════════════════════════════════════════════════════════
# 3b · WordPressAdapter direct unit test — mockable publisher path
# ═════════════════════════════════════════════════════════════════════
def test_wordpress_adapter_publish_path_direct(monkeypatch):
    """Direct adapter unit test — monkeypatches ``_publish_to_wp``
    in-process so we can verify the reshape logic without hitting
    a real WP site.  This complements the HTTP-level fan-out test
    above (which uses stubs to keep WP out of the loop)."""
    from routers import seo as seo_router
    from services.social.wordpress_adapter import WordPressAdapter

    async def _fake(art, status):
        return {"wp_status": status, "wp_post_id": 999,
                 "link": f"https://example.test/?p=999&s={status}"}
    monkeypatch.setattr(seo_router, "_publish_to_wp", _fake)

    a = WordPressAdapter()
    res = _run(a.publish_text(
        tenant_id="TEST-t", text="Hello world.\n\nSecond para.",
        title="Test Article", status="draft"))
    assert res["platform_post_id"] == "999"
    assert res["status"] == "draft"
    assert "example.test" in res["url"]
    assert res["article_id"]  # ephemeral seo_articles row created
    # Ephemeral row visible on seo_articles collection.
    art = _db.seo_articles.find_one({"id": res["article_id"]})
    assert art is not None
    assert art["source"] == "soshie"
    # Cleanup so subsequent test runs stay clean.
    _db.seo_articles.delete_one({"id": res["article_id"]})


# ═════════════════════════════════════════════════════════════════════
# 4 · Adapter check_credentials happy path (WordPress)
# ═════════════════════════════════════════════════════════════════════
def test_wordpress_adapter_check_credentials_ok_with_env():
    from services.social.wordpress_adapter import WordPressAdapter
    a = WordPressAdapter()
    r = _run(a.check_credentials(tenant_id="anything"))
    # Preview env has WORDPRESS_URL / _USERNAME / _APP_PASSWORD.
    assert r["ok"] is True
    assert "Connected to" in r["detail"]


# ═════════════════════════════════════════════════════════════════════
# 5 · Migration idempotent — creates 5 indexes, sentinel written
# ═════════════════════════════════════════════════════════════════════
def test_migration_creates_all_indexes():
    names = {i.get("name") for i in _db.social_publish_log.list_indexes()}
    assert "social_publish_log_uniq" in names
    assert "social_publish_log_by_platform" in names
    names = {i.get("name") for i in _db.social_posts.list_indexes()}
    assert "social_posts_by_platform" in names
    assert "social_posts_by_status" in names
    names = {i.get("name") for i in _db.social_platform_credentials.list_indexes()}
    assert "social_platform_credentials_uniq" in names


def test_migration_sentinel_written():
    row = _db.migrations.find_one({"id": "social_publish_log_indexes_v1"})
    assert row is not None


# ═════════════════════════════════════════════════════════════════════
# 6 · Missing platform key → 422
# ═════════════════════════════════════════════════════════════════════
def test_publish_unknown_platform_rejected(admin_h):
    r = requests.post(f"{API}/soshie/publish", headers=admin_h,
                       json={"platforms": ["myspace"], "text": "hi"},
                       timeout=10)
    assert r.status_code == 422, r.text
    assert "unknown platforms" in r.text


def test_publish_empty_platforms_rejected(admin_h):
    r = requests.post(f"{API}/soshie/publish", headers=admin_h,
                       json={"platforms": [], "text": "hi"},
                       timeout=10)
    assert r.status_code == 422


# ═════════════════════════════════════════════════════════════════════
# 7 · X (Twitter) is explicitly NOT in the registry
# ═════════════════════════════════════════════════════════════════════
def test_x_platform_not_registered():
    from services.social import PLATFORMS
    assert "x" not in PLATFORMS
    assert "twitter" not in PLATFORMS
