"""
Iteration 24 — SEO Studio: Weekly auto-publish scheduler

Covers the NEW endpoints:
- GET  /api/seo/schedule            -> {settings, queued}
- PUT  /api/seo/schedule            -> persists day_of_week/hour/paused/enabled
- POST /api/seo/articles/{id}/schedule mode=auto  -> next weekly slot, +7d for 2nd
- POST /api/seo/articles/{id}/schedule mode=manual -> requires scheduled_for
- POST /api/seo/articles/{id}/unschedule -> reverts to draft
- RBAC: admin only (403 for tech/customer)

Directly seeds draft articles into Mongo (no LLM call) to conserve budget.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

# ------------------------- Config -------------------------
_FE_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_BE_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_FE_ENV)
_BENV = dotenv_values(_BE_ENV)
BASE_URL = (_ENV.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = _BENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BENV.get("DB_NAME") or os.environ.get("DB_NAME")

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


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def seeded_articles(mongo):
    """Seed two draft articles directly in Mongo (avoid burning LLM budget)."""
    ids = ["TEST_seo_sched_a1", "TEST_seo_sched_a2"]
    now = datetime.now(timezone.utc).isoformat()
    docs = [
        {
            "id": ids[0],
            "keyword": "TEST_ pool filter cleaning",
            "title": "TEST_ Article A",
            "slug": "test-article-a",
            "meta_description": "meta A",
            "tags": ["pool"],
            "body_markdown": "## body A",
            "faqs": [],
            "word_count": 100,
            "status": "draft",
            "created_at": now,
        },
        {
            "id": ids[1],
            "keyword": "TEST_ pool pump priming",
            "title": "TEST_ Article B",
            "slug": "test-article-b",
            "meta_description": "meta B",
            "tags": ["pool"],
            "body_markdown": "## body B",
            "faqs": [],
            "word_count": 100,
            "status": "draft",
            "created_at": now,
        },
    ]
    mongo.seo_articles.delete_many({"id": {"$in": ids}})
    mongo.seo_articles.insert_many(docs)
    yield ids
    mongo.seo_articles.delete_many({"id": {"$in": ids}})


# ------------------------- RBAC -------------------------

class TestScheduleRBAC:
    def test_get_schedule_tech_forbidden(self, tech_headers):
        r = requests.get(f"{API}/seo/schedule", headers=tech_headers, timeout=30)
        assert r.status_code == 403, r.text

    def test_get_schedule_customer_forbidden(self, customer_headers):
        r = requests.get(f"{API}/seo/schedule", headers=customer_headers, timeout=30)
        assert r.status_code == 403, r.text

    def test_put_schedule_tech_forbidden(self, tech_headers):
        r = requests.put(f"{API}/seo/schedule", json={"paused": True}, headers=tech_headers, timeout=30)
        assert r.status_code == 403, r.text

    def test_schedule_article_customer_forbidden(self, customer_headers):
        r = requests.post(f"{API}/seo/articles/anything/schedule", json={"mode": "auto"}, headers=customer_headers, timeout=30)
        assert r.status_code == 403, r.text

    def test_unschedule_tech_forbidden(self, tech_headers):
        r = requests.post(f"{API}/seo/articles/anything/unschedule", json={}, headers=tech_headers, timeout=30)
        assert r.status_code == 403, r.text

    def test_no_token_401_or_403(self):
        r = requests.get(f"{API}/seo/schedule", timeout=30)
        assert r.status_code in (401, 403)


# ------------------------- GET /api/seo/schedule -------------------------

class TestGetSchedule:
    def test_returns_settings_and_queued(self, admin_headers):
        r = requests.get(f"{API}/seo/schedule", headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "settings" in body and "queued" in body
        s = body["settings"]
        for k in ("enabled", "paused", "day_of_week", "hour", "minute"):
            assert k in s, f"missing key {k} in settings"
        assert isinstance(body["queued"], list)


# ------------------------- PUT /api/seo/schedule -------------------------

class TestUpdateSchedule:
    def test_update_persists(self, admin_headers, mongo):
        payload = {"day_of_week": 3, "hour": 14, "paused": True, "enabled": True}
        r = requests.put(f"{API}/seo/schedule", json=payload, headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["day_of_week"] == 3
        assert body["hour"] == 14
        assert body["paused"] is True
        assert body["enabled"] is True

        # Verify persistence via a fresh GET
        r2 = requests.get(f"{API}/seo/schedule", headers=admin_headers, timeout=30)
        assert r2.status_code == 200
        s = r2.json()["settings"]
        assert s["day_of_week"] == 3
        assert s["hour"] == 14
        assert s["paused"] is True

        # Reset to sane defaults (unpause so subsequent tests don't affect flow) — but
        # NOTE: leave paused=True so the background APScheduler tick can't accidentally
        # try to publish our TEST articles (WP is intentionally not connected).
        # We restore day_of_week/hour but keep paused=True for safety.
        requests.put(
            f"{API}/seo/schedule",
            json={"day_of_week": 0, "hour": 9, "minute": 0, "paused": True, "enabled": True},
            headers=admin_headers, timeout=30,
        )


# ------------------------- POST schedule (auto + manual) -------------------------

class TestArticleScheduling:
    def test_schedule_auto_first_returns_future_iso(self, admin_headers, seeded_articles):
        aid = seeded_articles[0]
        r = requests.post(
            f"{API}/seo/articles/{aid}/schedule",
            json={"mode": "auto"},
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["mode"] == "auto"
        assert b["scheduled_for"]
        when1 = datetime.fromisoformat(b["scheduled_for"])
        if when1.tzinfo is None:
            when1 = when1.replace(tzinfo=timezone.utc)
        assert when1 > datetime.now(timezone.utc), "auto schedule must be in the future"

        # Verify article status was updated
        art = requests.get(f"{API}/seo/articles/{aid}", headers=admin_headers, timeout=30).json()
        assert art["status"] == "scheduled"
        assert art.get("queue_mode") == "auto"
        assert art.get("scheduled_for")

        # Save for next test via class attribute
        TestArticleScheduling._when1 = when1

    def test_schedule_auto_second_is_7_days_after_first(self, admin_headers, seeded_articles):
        aid2 = seeded_articles[1]
        r = requests.post(
            f"{API}/seo/articles/{aid2}/schedule",
            json={"mode": "auto"},
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        b = r.json()
        when2 = datetime.fromisoformat(b["scheduled_for"])
        if when2.tzinfo is None:
            when2 = when2.replace(tzinfo=timezone.utc)

        delta = (when2 - TestArticleScheduling._when1).total_seconds()
        # Expect exactly 7 days between the two auto-queued items
        assert 6 * 86400 < delta < 8 * 86400, f"expected ~7 days between auto items, got {delta / 86400:.2f} days"

    def test_manual_requires_scheduled_for(self, admin_headers, seeded_articles):
        aid = seeded_articles[0]
        r = requests.post(
            f"{API}/seo/articles/{aid}/schedule",
            json={"mode": "manual"},
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 400, r.text
        assert "date" in r.json().get("detail", "").lower()

    def test_manual_accepts_iso_and_sets_scheduled(self, admin_headers, seeded_articles):
        aid = seeded_articles[0]
        target = "2030-01-15T09:00:00+00:00"
        r = requests.post(
            f"{API}/seo/articles/{aid}/schedule",
            json={"mode": "manual", "scheduled_for": target},
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["mode"] == "manual"
        got = datetime.fromisoformat(b["scheduled_for"])
        exp = datetime.fromisoformat(target)
        assert got == exp

        art = requests.get(f"{API}/seo/articles/{aid}", headers=admin_headers, timeout=30).json()
        assert art["status"] == "scheduled"
        assert art.get("queue_mode") == "manual"

    def test_manual_invalid_date_400(self, admin_headers, seeded_articles):
        aid = seeded_articles[0]
        r = requests.post(
            f"{API}/seo/articles/{aid}/schedule",
            json={"mode": "manual", "scheduled_for": "not-a-date"},
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 400, r.text

    def test_schedule_unknown_article_404(self, admin_headers):
        r = requests.post(
            f"{API}/seo/articles/does-not-exist-xyz/schedule",
            json={"mode": "auto"},
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 404

    def test_queued_appears_in_schedule_list(self, admin_headers, seeded_articles):
        r = requests.get(f"{API}/seo/schedule", headers=admin_headers, timeout=30)
        assert r.status_code == 200
        queued_ids = [a["id"] for a in r.json()["queued"]]
        # Both seeded ids should be present (one manual, one auto)
        for aid in seeded_articles:
            assert aid in queued_ids, f"expected {aid} in queue, got {queued_ids}"


# ------------------------- POST unschedule -------------------------

class TestUnschedule:
    def test_unschedule_reverts_to_draft(self, admin_headers, seeded_articles):
        aid = seeded_articles[0]
        r = requests.post(f"{API}/seo/articles/{aid}/unschedule", json={}, headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        art = requests.get(f"{API}/seo/articles/{aid}", headers=admin_headers, timeout=30).json()
        assert art["status"] == "draft"
        assert art.get("scheduled_for") in (None, "")
        assert art.get("queue_mode") in (None, "")

        # Also drops out of queue list
        sch = requests.get(f"{API}/seo/schedule", headers=admin_headers, timeout=30).json()
        assert aid not in [a["id"] for a in sch["queued"]]

    def test_unschedule_unknown_article_404(self, admin_headers):
        r = requests.post(f"{API}/seo/articles/does-not-exist-xyz/unschedule", json={}, headers=admin_headers, timeout=30)
        assert r.status_code == 404


# ------------------------- Cleanup -------------------------

def teardown_module(module):
    if not (MONGO_URL and DB_NAME):
        return
    c = MongoClient(MONGO_URL)
    try:
        d = c[DB_NAME]
        d.seo_articles.delete_many({"id": {"$regex": "^TEST_seo_sched_"}})
    finally:
        c.close()
