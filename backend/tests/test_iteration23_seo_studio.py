"""
Iteration 23 — SEO Studio + WordPress publishing
Covers:
- Keyword suggest (admin, AI)
- Article generate/list/get (admin, AI)
- SEO audit by article_id
- WordPress settings CRUD (initially empty, save, test)
- Publish gating (no WP config -> 400, unknown id -> 404)
- RBAC: 403 for technician & customer
"""

import os
import pytest
import requests
from dotenv import dotenv_values
from pathlib import Path

_FE_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_ENV = dotenv_values(_FE_ENV)
BASE_URL = (_ENV.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}
CUSTOMER = {"email": "customer@aquaterra.com", "password": "password123"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_headers():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def tech_headers():
    return _login(TECH)


@pytest.fixture(scope="module")
def customer_headers():
    return _login(CUSTOMER)


# ---------------- RBAC ----------------

class TestSeoRBAC:
    def test_seo_keywords_tech_forbidden(self, tech_headers):
        r = requests.post(f"{API}/seo/keywords/suggest", json={"seed": "x"}, headers=tech_headers, timeout=30)
        assert r.status_code == 403, r.text

    def test_seo_articles_list_customer_forbidden(self, customer_headers):
        r = requests.get(f"{API}/seo/articles", headers=customer_headers, timeout=30)
        assert r.status_code == 403, r.text

    def test_wp_settings_tech_forbidden(self, tech_headers):
        r = requests.get(f"{API}/seo/wp-settings", headers=tech_headers, timeout=30)
        assert r.status_code == 403, r.text

    def test_seo_no_token(self):
        r = requests.get(f"{API}/seo/articles", timeout=30)
        assert r.status_code in (401, 403), r.text


# ---------------- Keyword suggest ----------------

class TestKeywords:
    def test_suggest_returns_list(self, admin_headers):
        r = requests.post(
            f"{API}/seo/keywords/suggest",
            json={"seed": "pool maintenance TEST_", "location": "Vistancia, Arizona"},
            headers=admin_headers,
            timeout=90,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "keywords" in body
        kws = body["keywords"]
        assert isinstance(kws, list) and len(kws) >= 1
        # spot check first item shape
        k0 = kws[0]
        assert "keyword" in k0 and isinstance(k0["keyword"], str)


# ---------------- Articles (create -> get -> list -> audit) ----------------

class TestArticles:
    aid = None

    def test_generate_article(self, admin_headers):
        r = requests.post(
            f"{API}/seo/articles",
            json={"keyword": "TEST_ pool cleaning tips", "word_count": 300},
            headers=admin_headers,
            timeout=180,
        )
        assert r.status_code == 200, r.text
        art = r.json()
        assert art.get("id")
        assert art.get("title")
        assert art.get("body_markdown")
        assert isinstance(art.get("faqs", []), list)
        assert art.get("status") == "draft"
        TestArticles.aid = art["id"]

    def test_get_article(self, admin_headers):
        assert TestArticles.aid, "article id not set"
        r = requests.get(f"{API}/seo/articles/{TestArticles.aid}", headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        art = r.json()
        assert art["id"] == TestArticles.aid
        assert "_id" not in art
        assert art.get("body_markdown")

    def test_list_articles_contains_new(self, admin_headers):
        r = requests.get(f"{API}/seo/articles", headers=admin_headers, timeout=30)
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list)
        ids = [a.get("id") for a in items]
        assert TestArticles.aid in ids
        # list should not include full body per projection
        for it in items:
            assert "body_markdown" not in it
            assert "_id" not in it

    def test_get_unknown_article_404(self, admin_headers):
        r = requests.get(f"{API}/seo/articles/does-not-exist-xyz", headers=admin_headers, timeout=30)
        assert r.status_code == 404

    def test_audit_by_article_id(self, admin_headers):
        assert TestArticles.aid
        r = requests.post(
            f"{API}/seo/audit",
            json={"keyword": "pool cleaning tips", "article_id": TestArticles.aid},
            headers=admin_headers,
            timeout=120,
        )
        assert r.status_code == 200, r.text
        a = r.json()
        assert "score" in a and isinstance(a["score"], int)
        assert 0 <= a["score"] <= 100
        assert isinstance(a.get("checks", []), list)

    def test_audit_missing_inputs_400(self, admin_headers):
        r = requests.post(
            f"{API}/seo/audit",
            json={"keyword": "pool"},
            headers=admin_headers,
            timeout=30,
        )
        assert r.status_code == 400


# ---------------- WordPress settings + gating ----------------

class TestWpSettingsAndPublish:
    def test_initial_wp_settings(self, admin_headers):
        # Reset the collection state via API: use PUT then verify test endpoint fails
        r = requests.get(f"{API}/seo/wp-settings", headers=admin_headers, timeout=30)
        assert r.status_code == 200
        data = r.json()
        # We don't assert connected=False strictly because previous runs may have saved settings.
        assert set(["connected", "url", "username"]).issubset(data.keys())
        assert "app_password" not in data  # never echo password

    def test_put_wp_settings_saves_and_no_password_echo(self, admin_headers):
        payload = {
            "url": "https://TEST-invalid-wp.example.com",
            "username": "TEST_admin",
            "app_password": "xxxx xxxx xxxx xxxx",
        }
        r = requests.put(f"{API}/seo/wp-settings", json=payload, headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b.get("connected") is True
        assert b.get("url") == payload["url"]
        assert b.get("username") == payload["username"]
        assert "app_password" not in b

    def test_put_wp_settings_bad_url_400(self, admin_headers):
        r = requests.put(
            f"{API}/seo/wp-settings",
            json={"url": "notaurl.com", "username": "x", "app_password": "y"},
            headers=admin_headers,
            timeout=30,
        )
        assert r.status_code == 400

    def test_wp_test_fails_gracefully(self, admin_headers):
        # After saving fake creds, test endpoint should fail with a graceful HTTP error status.
        # NOTE: Cloudflare intercepts origin 502s and replaces the body with its own HTML error
        # page, so JSON body may not be present. We assert on status only + non-crash behaviour.
        r = requests.post(f"{API}/seo/wp-settings/test", headers=admin_headers, timeout=60)
        assert r.status_code in (400, 401, 404, 500, 502), f"unexpected {r.status_code}: {r.text[:200]}"
        # If backend response passes through (non-502), body should be JSON with detail
        if r.status_code != 502:
            body = r.json()
            assert "detail" in body

    def test_publish_unknown_article_404(self, admin_headers):
        r = requests.post(
            f"{API}/seo/articles/does-not-exist/publish",
            json={"status": "publish"},
            headers=admin_headers,
            timeout=30,
        )
        assert r.status_code == 404

    def test_publish_gated_when_wp_not_reachable(self, admin_headers):
        # WP creds are saved but URL is fake -> publish should fail gracefully (502) not crash.
        # NOTE: Cloudflare intercepts 502 so body may be HTML — assert status only.
        assert TestArticles.aid, "need article id from earlier test"
        r = requests.post(
            f"{API}/seo/articles/{TestArticles.aid}/publish",
            json={"status": "publish"},
            headers=admin_headers,
            timeout=60,
        )
        assert r.status_code in (400, 401, 502, 500), f"unexpected {r.status_code}: {r.text[:200]}"
        if r.status_code != 502:
            body = r.json()
            assert "detail" in body

    def test_publish_gated_when_wp_not_configured(self, admin_headers):
        """When WP settings don't exist at all, publish must return 400 with the friendly message."""
        # Directly clear settings via Mongo to simulate "not configured"
        from pymongo import MongoClient
        from dotenv import dotenv_values as _dv
        be_env = _dv(Path(__file__).resolve().parents[1] / ".env")
        c = MongoClient(be_env["MONGO_URL"])
        try:
            c[be_env["DB_NAME"]].seo_settings.delete_many({})
        finally:
            c.close()

        assert TestArticles.aid
        r = requests.post(
            f"{API}/seo/articles/{TestArticles.aid}/publish",
            json={"status": "publish"},
            headers=admin_headers,
            timeout=30,
        )
        assert r.status_code == 400, r.text
        detail = r.json().get("detail", "")
        assert "WordPress" in detail

        # And wp-settings should now report connected=false
        r2 = requests.get(f"{API}/seo/wp-settings", headers=admin_headers, timeout=30)
        assert r2.status_code == 200
        assert r2.json().get("connected") is False


# ---------------- Cleanup ----------------

def teardown_module(module):
    """Cleanup: delete TEST article + clear WP settings from Mongo."""
    from dotenv import dotenv_values as _dv
    from pymongo import MongoClient
    be_env = _dv(Path(__file__).resolve().parents[1] / ".env")
    murl = be_env.get("MONGO_URL")
    dbn = be_env.get("DB_NAME")
    if not (murl and dbn):
        return
    c = MongoClient(murl)
    try:
        d = c[dbn]
        if TestArticles.aid:
            d.seo_articles.delete_one({"id": TestArticles.aid})
        d.seo_articles.delete_many({"keyword": {"$regex": "^TEST_"}})
        d.seo_keywords.delete_many({"seed": {"$regex": "TEST_"}})
        d.seo_settings.delete_many({"url": {"$regex": "TEST-invalid-wp"}})
    finally:
        c.close()
