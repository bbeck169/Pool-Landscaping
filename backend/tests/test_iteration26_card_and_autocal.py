"""Iteration 26 — Digital Business Card + GBP Auto Content Calendar.

Backend scope:
- GET /api/me/card requires auth (no token → 401/403)
- GET /api/me/card returns name/title/phone/email/company{...} for admin, technician, customer
- GET /api/gbp/autopost is admin-only, default true
- PUT /api/gbp/autopost toggles the flag (persists)
- GET /api/gbp/calendar returns list; admin-only
- PATCH /api/gbp/calendar/{id} edits summary/cta_url
- DELETE /api/gbp/calendar/{id} removes
- POST /api/gbp/calendar/{id}/publish returns 400/424 (never 500) when GBP not connected
- Direct hook: routers.gbp.auto_gbp_from_article seeds a draft when autopost=ON
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
BASE_URL = (
    os.environ.get("EXPO_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or _ENV.get("APP_PUBLIC_URL", "")
).rstrip("/")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}
CUST = {"email": "customer@aquaterra.com", "password": "password123"}

TEST_ARTICLE_ID = f"TEST_it26_article_{uuid.uuid4().hex[:8]}"


def _h(t):
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login failed {creds['email']}: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def tokens():
    return {"admin": _login(ADMIN), "tech": _login(TECH), "cust": _login(CUST)}


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    if not (_MONGO_URL and _DB_NAME):
        return
    mc = MongoClient(_MONGO_URL)
    try:
        d = mc[_DB_NAME]
        d.gbp_settings.delete_many({})           # autopost, config, tokens
        d.gbp_posts.delete_many({"article_id": TEST_ARTICLE_ID})
        d.gbp_posts.delete_many({"article_title": {"$regex": "^TEST_"}})
        d.seo_articles.delete_many({"id": TEST_ARTICLE_ID})
    finally:
        mc.close()


# ----------------- /api/me/card -----------------
class TestBusinessCard:
    def test_card_no_token_rejected(self):
        r = requests.get(f"{BASE_URL}/api/me/card", timeout=30)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"

    @pytest.mark.parametrize("role", ["admin", "tech", "cust"])
    def test_card_returns_shape(self, tokens, role):
        r = requests.get(f"{BASE_URL}/api/me/card", headers=_h(tokens[role]), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("name", "title", "phone", "email", "company"):
            assert k in data, f"missing '{k}' for {role}: {data}"
        assert isinstance(data["name"], str) and data["name"]
        assert isinstance(data["title"], str) and data["title"]
        assert isinstance(data["phone"], str) and data["phone"]
        assert "@" in data["email"]
        c = data["company"]
        for k in ("name", "region", "tagline", "phone", "email", "website", "google_review"):
            assert k in c, f"company missing '{k}' for {role}: {c}"
        assert c["website"].startswith("http")
        assert c["google_review"].startswith("http")

    def test_card_title_varies_by_role(self, tokens):
        admin = requests.get(f"{BASE_URL}/api/me/card", headers=_h(tokens["admin"]), timeout=30).json()
        tech = requests.get(f"{BASE_URL}/api/me/card", headers=_h(tokens["tech"]), timeout=30).json()
        cust = requests.get(f"{BASE_URL}/api/me/card", headers=_h(tokens["cust"]), timeout=30).json()
        assert "Admin" in admin["title"] or "Owner" in admin["title"]
        assert cust["title"] == "Valued Customer"
        # Tech title comes from technicians.specialty or fallback "Service Technician"
        assert tech["title"] and tech["title"] != "Valued Customer"


# ----------------- /api/gbp/autopost -----------------
class TestAutopost:
    def test_get_default_true(self, tokens):
        # ensure autopost setting wiped before checking default
        if _MONGO_URL and _DB_NAME:
            mc = MongoClient(_MONGO_URL)
            try:
                mc[_DB_NAME].gbp_settings.delete_one({"id": "autopost"})
            finally:
                mc.close()
        r = requests.get(f"{BASE_URL}/api/gbp/autopost", headers=_h(tokens["admin"]), timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("enabled") is True

    def test_autopost_rbac(self, tokens):
        for role in ("tech", "cust"):
            r = requests.get(f"{BASE_URL}/api/gbp/autopost", headers=_h(tokens[role]), timeout=30)
            assert r.status_code == 403, f"{role} allowed on GET autopost: {r.status_code}"
            r = requests.put(f"{BASE_URL}/api/gbp/autopost", headers=_h(tokens[role]),
                             json={"enabled": False}, timeout=30)
            assert r.status_code == 403, f"{role} allowed on PUT autopost: {r.status_code}"
        # no token
        r = requests.get(f"{BASE_URL}/api/gbp/autopost", timeout=30)
        assert r.status_code in (401, 403)

    def test_toggle_persists(self, tokens):
        r = requests.put(f"{BASE_URL}/api/gbp/autopost", headers=_h(tokens["admin"]),
                         json={"enabled": False}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("enabled") is False
        g = requests.get(f"{BASE_URL}/api/gbp/autopost", headers=_h(tokens["admin"]), timeout=30).json()
        assert g.get("enabled") is False
        # toggle back on
        r = requests.put(f"{BASE_URL}/api/gbp/autopost", headers=_h(tokens["admin"]),
                         json={"enabled": True}, timeout=30)
        assert r.status_code == 200 and r.json().get("enabled") is True


# ----------------- /api/gbp/calendar CRUD + publish gating -----------------
class TestCalendar:
    def _seed_post(self, extra=None):
        assert _MONGO_URL and _DB_NAME
        mc = MongoClient(_MONGO_URL)
        pid = f"TEST_calpost_{uuid.uuid4().hex[:8]}"
        doc = {
            "id": pid,
            "article_id": TEST_ARTICLE_ID,
            "article_title": "TEST_ Calendar Post",
            "summary": "Original summary text for pool care in Vistancia.",
            "cta_url": "https://example.com/original",
            "status": "draft",
            "google_post_name": None,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        if extra:
            doc.update(extra)
        try:
            mc[_DB_NAME].gbp_posts.insert_one(doc)
        finally:
            mc.close()
        return pid

    def test_calendar_rbac(self, tokens):
        for role in ("tech", "cust"):
            r = requests.get(f"{BASE_URL}/api/gbp/calendar", headers=_h(tokens[role]), timeout=30)
            assert r.status_code == 403
        r = requests.get(f"{BASE_URL}/api/gbp/calendar", timeout=30)
        assert r.status_code in (401, 403)

    def test_calendar_list_admin(self, tokens):
        r = requests.get(f"{BASE_URL}/api/gbp/calendar", headers=_h(tokens["admin"]), timeout=30)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_calendar_patch_summary_and_cta(self, tokens):
        pid = self._seed_post()
        payload = {"summary": "TEST_ updated summary text 🌊", "cta_url": "https://example.com/updated"}
        r = requests.patch(f"{BASE_URL}/api/gbp/calendar/{pid}", headers=_h(tokens["admin"]),
                           json=payload, timeout=30)
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["summary"] == payload["summary"]
        assert doc["cta_url"] == payload["cta_url"]
        # verify via list
        lst = requests.get(f"{BASE_URL}/api/gbp/calendar", headers=_h(tokens["admin"]), timeout=30).json()
        found = next((x for x in lst if x["id"] == pid), None)
        assert found and found["summary"] == payload["summary"]

    def test_calendar_delete(self, tokens):
        pid = self._seed_post()
        r = requests.delete(f"{BASE_URL}/api/gbp/calendar/{pid}", headers=_h(tokens["admin"]), timeout=30)
        assert r.status_code == 200 and r.json().get("ok") is True
        # verify gone
        r2 = requests.patch(f"{BASE_URL}/api/gbp/calendar/{pid}", headers=_h(tokens["admin"]),
                            json={"summary": "x"}, timeout=30)
        assert r2.status_code == 404

    def test_calendar_publish_graceful_when_not_connected(self, tokens):
        # wipe any oauth config/tokens so it is definitely 'not connected'
        if _MONGO_URL and _DB_NAME:
            mc = MongoClient(_MONGO_URL)
            try:
                mc[_DB_NAME].gbp_settings.delete_many({"id": {"$in": ["config", "tokens"]}})
            finally:
                mc.close()
        pid = self._seed_post()
        r = requests.post(f"{BASE_URL}/api/gbp/calendar/{pid}/publish",
                          headers=_h(tokens["admin"]), timeout=45)
        assert r.status_code in (400, 424), f"expected 400/424, got {r.status_code} {r.text[:200]}"
        assert r.status_code != 500

    def test_calendar_publish_missing_id_404(self, tokens):
        r = requests.post(f"{BASE_URL}/api/gbp/calendar/does-not-exist/publish",
                          headers=_h(tokens["admin"]), timeout=30)
        assert r.status_code == 404


# ----------------- auto_gbp_from_article hook (direct import) -----------------
class TestAutoHook:
    """Direct unit-style test: calls the hook function without needing WP connected."""

    def test_hook_creates_draft_when_autopost_on(self):
        # Import the running backend module directly
        backend_path = str(Path(__file__).resolve().parents[1])
        if backend_path not in sys.path:
            sys.path.insert(0, backend_path)
        # Ensure autopost is ON
        assert _MONGO_URL and _DB_NAME
        mc = MongoClient(_MONGO_URL)
        try:
            mc[_DB_NAME].gbp_settings.update_one(
                {"id": "autopost"}, {"$set": {"id": "autopost", "enabled": True}}, upsert=True
            )
            # Also make sure no OAuth tokens exist so hook keeps status=draft
            mc[_DB_NAME].gbp_settings.delete_many({"id": {"$in": ["config", "tokens"]}})
            # Clean previous run for this article id
            mc[_DB_NAME].gbp_posts.delete_many({"article_id": TEST_ARTICLE_ID})
        finally:
            mc.close()

        article = {
            "id": TEST_ARTICLE_ID,
            "title": "TEST_ Vistancia Pool Care Tips",
            "meta_description": "Local tips to keep your pool clean.",
            "body_markdown": "Keep chlorine balanced, skim daily, and schedule weekly service.",
            "wp_link": "https://example.com/blog/vistancia-pool-tips",
        }

        from routers.gbp import auto_gbp_from_article  # noqa: E402
        asyncio.get_event_loop().run_until_complete(auto_gbp_from_article(article))

        # Verify a draft was created
        mc = MongoClient(_MONGO_URL)
        try:
            doc = mc[_DB_NAME].gbp_posts.find_one({"article_id": TEST_ARTICLE_ID}, {"_id": 0})
        finally:
            mc.close()
        assert doc, "expected gbp_posts draft to be inserted by auto_gbp_from_article"
        assert doc["status"] == "draft", f"expected status=draft (GBP not connected), got {doc['status']}"
        assert doc["cta_url"] == article["wp_link"]
        assert doc["article_title"] == article["title"]
        assert isinstance(doc["summary"], str) and len(doc["summary"]) > 10

    def test_hook_no_op_when_autopost_off(self):
        assert _MONGO_URL and _DB_NAME
        another_id = f"TEST_it26_off_{uuid.uuid4().hex[:8]}"
        mc = MongoClient(_MONGO_URL)
        try:
            mc[_DB_NAME].gbp_settings.update_one(
                {"id": "autopost"}, {"$set": {"id": "autopost", "enabled": False}}, upsert=True
            )
            mc[_DB_NAME].gbp_posts.delete_many({"article_id": another_id})
        finally:
            mc.close()

        backend_path = str(Path(__file__).resolve().parents[1])
        if backend_path not in sys.path:
            sys.path.insert(0, backend_path)
        from routers.gbp import auto_gbp_from_article  # noqa: E402
        asyncio.get_event_loop().run_until_complete(auto_gbp_from_article({
            "id": another_id, "title": "TEST_ off", "meta_description": "",
            "body_markdown": "x", "wp_link": "",
        }))
        mc = MongoClient(_MONGO_URL)
        try:
            doc = mc[_DB_NAME].gbp_posts.find_one({"article_id": another_id})
            mc[_DB_NAME].gbp_posts.delete_many({"article_id": another_id})
            # Restore autopost to ON for cleanup default
            mc[_DB_NAME].gbp_settings.update_one(
                {"id": "autopost"}, {"$set": {"id": "autopost", "enabled": True}}, upsert=True
            )
        finally:
            mc.close()
        assert doc is None, "hook should be a no-op when autopost is disabled"
