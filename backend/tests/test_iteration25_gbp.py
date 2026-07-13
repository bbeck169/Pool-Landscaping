"""GBP (Google Business Profile) endpoint tests — iteration 25.

Scope (backend-only):
- RBAC: /api/gbp/* is admin-only (technician / customer -> 403; no token -> 401/403)
- GET /api/gbp/settings shape (configured / connected / suggested_redirect_uri)
- PUT /api/gbp/settings persists client_id/redirect_uri (secret never echoed)
- GET /api/gbp/auth-url returns Google consent URL only AFTER settings saved
- Live-Google endpoints (locations, reviews, posts, replies, business PATCH)
  return clean 400 messages when not connected (no 500)
- POST /api/gbp/ai/reply-draft returns a drafted reply string (Emergent LLM)
- POST /api/gbp/ai/post-from-article returns {summary, cta_url}; 404 unknown id
- GET /api/gbp/callback (public) with missing code returns HTML (not crash)

Cleanup: any gbp_settings and TEST_ seo_articles inserted during the run are
removed by the module-level teardown (autouse fixture) so the app returns to
'Not set up' state.
"""
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or _ENV.get("APP_PUBLIC_URL", "")).rstrip("/")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}
CUST = {"email": "customer@aquaterra.com", "password": "password123"}


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def tokens():
    return {"admin": _login(ADMIN), "tech": _login(TECH), "cust": _login(CUST)}


def _h(t):
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Test-only DB teardown (removes gbp_settings + TEST_ seo_articles this run created)
# ---------------------------------------------------------------------------
TEST_ARTICLE_ID = f"TEST_gbp_article_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module", autouse=True)
def cleanup_gbp():
    yield
    if not (_MONGO_URL and _DB_NAME):
        return
    mc = MongoClient(_MONGO_URL)
    try:
        d = mc[_DB_NAME]
        # Wipe any settings/tokens the tests wrote so app returns to 'Not set up'
        d.gbp_settings.delete_many({})
        d.seo_articles.delete_many({"id": TEST_ARTICLE_ID})
    finally:
        mc.close()


# ---------------------------------------------------------------------------
# 1. RBAC — all /api/gbp/* endpoints reject non-admin and unauthenticated
# ---------------------------------------------------------------------------
PROTECTED_GET = [
    "/api/gbp/settings",
    "/api/gbp/auth-url",
    "/api/gbp/locations",
    "/api/gbp/reviews?location=accounts/1/locations/1",
    "/api/gbp/posts?location=accounts/1/locations/1",
]
PROTECTED_MUTATIONS = [
    ("PUT", "/api/gbp/settings", {"client_id": "x", "client_secret": "y", "redirect_uri": "https://z/api/gbp/callback"}),
    ("POST", "/api/gbp/posts", {"location": "accounts/1/locations/1", "summary": "hi"}),
    ("PUT", "/api/gbp/reviews/reply", {"review_name": "accounts/1/locations/1/reviews/1", "comment": "thx"}),
    ("PATCH", "/api/gbp/business", {"location": "accounts/1/locations/1", "phone": "555"}),
    ("POST", "/api/gbp/ai/reply-draft", {"review_text": "hi", "rating": 5}),
    ("POST", "/api/gbp/ai/post-from-article", {"article_id": "x"}),
    ("POST", "/api/gbp/disconnect", {}),
]


class TestRBAC:
    """All /api/gbp/* endpoints must be admin-only."""

    @pytest.mark.parametrize("path", PROTECTED_GET)
    def test_get_no_token_rejected(self, path):
        r = requests.get(f"{BASE_URL}{path}", timeout=30)
        assert r.status_code in (401, 403), f"{path} accepted no-token: {r.status_code}"

    @pytest.mark.parametrize("path", PROTECTED_GET)
    def test_get_technician_forbidden(self, tokens, path):
        r = requests.get(f"{BASE_URL}{path}", headers=_h(tokens["tech"]), timeout=30)
        assert r.status_code == 403, f"{path} allowed technician: {r.status_code} {r.text[:200]}"

    @pytest.mark.parametrize("path", PROTECTED_GET)
    def test_get_customer_forbidden(self, tokens, path):
        r = requests.get(f"{BASE_URL}{path}", headers=_h(tokens["cust"]), timeout=30)
        assert r.status_code == 403, f"{path} allowed customer: {r.status_code} {r.text[:200]}"

    @pytest.mark.parametrize("method,path,payload", PROTECTED_MUTATIONS)
    def test_mutation_no_token_rejected(self, method, path, payload):
        r = requests.request(method, f"{BASE_URL}{path}", json=payload, timeout=30)
        assert r.status_code in (401, 403), f"{method} {path} no-token: {r.status_code}"

    @pytest.mark.parametrize("method,path,payload", PROTECTED_MUTATIONS)
    def test_mutation_technician_forbidden(self, tokens, method, path, payload):
        r = requests.request(method, f"{BASE_URL}{path}", headers=_h(tokens["tech"]), json=payload, timeout=30)
        assert r.status_code == 403, f"{method} {path} allowed tech: {r.status_code}"

    @pytest.mark.parametrize("method,path,payload", PROTECTED_MUTATIONS)
    def test_mutation_customer_forbidden(self, tokens, method, path, payload):
        r = requests.request(method, f"{BASE_URL}{path}", headers=_h(tokens["cust"]), json=payload, timeout=30)
        assert r.status_code == 403, f"{method} {path} allowed customer: {r.status_code}"


# ---------------------------------------------------------------------------
# 2. Settings + auth-url flow (no OAuth creds saved yet)
# ---------------------------------------------------------------------------
class TestSettingsAndAuthUrl:
    def test_settings_initial_state(self, tokens):
        # Clean slate first
        if _MONGO_URL and _DB_NAME:
            mc = MongoClient(_MONGO_URL)
            try:
                mc[_DB_NAME].gbp_settings.delete_many({})
            finally:
                mc.close()

        r = requests.get(f"{BASE_URL}/api/gbp/settings", headers=_h(tokens["admin"]), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["configured"] is False
        assert data["connected"] is False
        assert "suggested_redirect_uri" in data
        assert data["suggested_redirect_uri"].endswith("/api/gbp/callback")
        assert data.get("client_id", "") == ""

    def test_auth_url_400_when_not_configured(self, tokens):
        r = requests.get(f"{BASE_URL}/api/gbp/auth-url", headers=_h(tokens["admin"]), timeout=30)
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text[:200]}"

    def test_put_settings_and_secret_not_echoed(self, tokens):
        payload = {
            "client_id": "TEST_client_id.apps.googleusercontent.com",
            "client_secret": "TEST_super_secret_value",
            "redirect_uri": "https://pool-app-mobile.preview.emergentagent.com/api/gbp/callback",
        }
        r = requests.put(f"{BASE_URL}/api/gbp/settings", headers=_h(tokens["admin"]), json=payload, timeout=30)
        assert r.status_code == 200, r.text
        saved = r.json()
        # Secret must not be echoed back in the PUT response
        assert "client_secret" not in saved, "client_secret must NOT be echoed on PUT response"
        # Confirm the GET also never returns client_secret
        g = requests.get(f"{BASE_URL}/api/gbp/settings", headers=_h(tokens["admin"]), timeout=30).json()
        assert "client_secret" not in g, "client_secret must NOT be echoed on GET"
        assert g["configured"] is True
        assert g["client_id"] == payload["client_id"]
        assert g["redirect_uri"] == payload["redirect_uri"]
        assert g["connected"] is False  # not connected until OAuth callback exchanges a code

    def test_auth_url_after_settings(self, tokens):
        r = requests.get(f"{BASE_URL}/api/gbp/auth-url", headers=_h(tokens["admin"]), timeout=30)
        assert r.status_code == 200, r.text
        url = r.json()["url"]
        assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert "client_id=TEST_client_id" in url
        assert "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fbusiness.manage" in url
        assert "access_type=offline" in url
        assert "prompt=consent" in url


# ---------------------------------------------------------------------------
# 3. Live-Google endpoints degrade gracefully (400, not 500) when not connected
# ---------------------------------------------------------------------------
class TestGracefulLiveFailures:
    """With OAuth creds saved but no tokens (never called callback), Google calls
    must return a clean 400 with an actionable message — NOT a 500 / crash."""

    def test_locations_400_not_connected(self, tokens):
        r = requests.get(f"{BASE_URL}/api/gbp/locations", headers=_h(tokens["admin"]), timeout=45)
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text[:200]}"
        detail = r.json().get("detail", "").lower()
        assert "connect" in detail or "credentials" in detail

    def test_reviews_400_not_connected(self, tokens):
        r = requests.get(
            f"{BASE_URL}/api/gbp/reviews?location=accounts/1/locations/1",
            headers=_h(tokens["admin"]), timeout=45,
        )
        assert r.status_code == 400, f"got {r.status_code} {r.text[:200]}"

    def test_posts_create_400_not_connected(self, tokens):
        r = requests.post(
            f"{BASE_URL}/api/gbp/posts",
            headers=_h(tokens["admin"]),
            json={"location": "accounts/1/locations/1", "summary": "hi"},
            timeout=45,
        )
        assert r.status_code == 400, f"got {r.status_code} {r.text[:200]}"

    def test_reviews_reply_400_not_connected(self, tokens):
        r = requests.put(
            f"{BASE_URL}/api/gbp/reviews/reply",
            headers=_h(tokens["admin"]),
            json={"review_name": "accounts/1/locations/1/reviews/1", "comment": "thanks"},
            timeout=45,
        )
        assert r.status_code == 400, f"got {r.status_code} {r.text[:200]}"

    def test_business_patch_400_not_connected(self, tokens):
        r = requests.patch(
            f"{BASE_URL}/api/gbp/business",
            headers=_h(tokens["admin"]),
            json={"location": "accounts/1/locations/1", "phone": "555-1212"},
            timeout=45,
        )
        assert r.status_code == 400, f"got {r.status_code} {r.text[:200]}"

    def test_no_creds_locations_400(self, tokens):
        """After wiping config entirely, locations must still return 400 (not 500)."""
        if _MONGO_URL and _DB_NAME:
            mc = MongoClient(_MONGO_URL)
            try:
                mc[_DB_NAME].gbp_settings.delete_many({})
            finally:
                mc.close()
        r = requests.get(f"{BASE_URL}/api/gbp/locations", headers=_h(tokens["admin"]), timeout=30)
        assert r.status_code == 400, f"got {r.status_code} {r.text[:200]}"
        detail = r.json().get("detail", "").lower()
        assert "credentials" in detail or "oauth" in detail


# ---------------------------------------------------------------------------
# 4. Public callback returns HTML (not crash) on missing code
# ---------------------------------------------------------------------------
class TestCallbackPublic:
    def test_callback_no_code_returns_html(self):
        r = requests.get(f"{BASE_URL}/api/gbp/callback", timeout=30)
        assert r.status_code == 200, f"got {r.status_code} {r.text[:200]}"
        assert "text/html" in r.headers.get("content-type", "").lower()
        assert "<html" in r.text.lower()

    def test_callback_with_error_returns_html(self):
        r = requests.get(f"{BASE_URL}/api/gbp/callback?error=access_denied", timeout=30)
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "").lower()
        assert "access_denied" in r.text or "cancelled" in r.text.lower()


# ---------------------------------------------------------------------------
# 5. AI drafting (works today via Emergent LLM key)
# ---------------------------------------------------------------------------
class TestAiDrafting:
    def test_ai_reply_draft_returns_string(self, tokens):
        payload = {
            "review_text": "The service was excellent — pool is spotless!",
            "rating": 5,
            "reviewer_name": "TEST_Jane",
        }
        r = requests.post(
            f"{BASE_URL}/api/gbp/ai/reply-draft",
            headers=_h(tokens["admin"]),
            json=payload,
            timeout=90,  # LLM latency
        )
        assert r.status_code == 200, f"got {r.status_code} {r.text[:200]}"
        data = r.json()
        assert isinstance(data.get("comment"), str)
        assert len(data["comment"]) > 5
        assert len(data["comment"]) <= 700

    def test_ai_post_from_article_404_unknown(self, tokens):
        r = requests.post(
            f"{BASE_URL}/api/gbp/ai/post-from-article",
            headers=_h(tokens["admin"]),
            json={"article_id": "does-not-exist-xyz"},
            timeout=60,
        )
        assert r.status_code == 404, f"got {r.status_code} {r.text[:200]}"

    def test_ai_post_from_article_ok(self, tokens):
        # Seed a TEST_ article directly into Mongo
        assert _MONGO_URL and _DB_NAME, "Mongo not configured in .env"
        mc = MongoClient(_MONGO_URL)
        try:
            mc[_DB_NAME].seo_articles.insert_one({
                "id": TEST_ARTICLE_ID,
                "title": "TEST_ 5 Ways to Keep Your Vistancia Pool Sparkling This Summer",
                "meta_description": "Simple tips from AquaTerra to keep your pool crystal clear in AZ heat.",
                "body_markdown": "Regular skimming, balanced chemistry, and a weekly service keep your pool healthy. "
                                 "AquaTerra offers monthly plans starting at $99 for Vistancia homes.",
                "wp_link": "https://example.com/blog/keep-pool-sparkling",
            })
        finally:
            mc.close()

        r = requests.post(
            f"{BASE_URL}/api/gbp/ai/post-from-article",
            headers=_h(tokens["admin"]),
            json={"article_id": TEST_ARTICLE_ID},
            timeout=120,
        )
        assert r.status_code == 200, f"got {r.status_code} {r.text[:200]}"
        data = r.json()
        assert isinstance(data.get("summary"), str)
        assert 20 < len(data["summary"]) <= 1490
        assert data.get("cta_url") == "https://example.com/blog/keep-pool-sparkling"
