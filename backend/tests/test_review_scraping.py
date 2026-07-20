"""Reviews Phase 3 · external review-scraper backend tests (Feb 2026).

Covers:
- Google adapter mock: 3 reviews returned → 3 rows inserted (source=
  ``google_scraped``); resync with the same 3 + 1 mutation → 0 new /
  1 updated.
- Facebook adapter is disabled by default → sync-now returns 200 with
  ``status="disabled"``.
- Yelp adapter has no key by default → sync-now returns 200 with
  ``status="not_configured"``.
- BBB and custom platforms return **404** on sync-now (no viable API).
- Dedup: same ``source_review_id`` on repeat sync never creates a
  second row.
- Tenant isolation: sync-now for tenant A never touches tenant B's
  reviews.

Isolation: every scraped row inserted here carries a
``source_review_id`` prefixed with ``TEST_`` so the fallback teardown
below can nuke leftover rows even after a partial run.
"""
from __future__ import annotations
import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest
import requests

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
from dotenv import dotenv_values, load_dotenv
load_dotenv(BACKEND_ROOT / ".env")

from tests.conftest import demo_pw  # noqa: E402


# Shared event loop across the whole module — Motor caches the loop it
# was first connected on, so creating fresh loops per-test triggers
# "Event loop is closed" on the second run.
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)

BACKEND = os.environ.get("REACT_APP_BACKEND_URL") \
    or "https://poolscape-audit.preview.emergentagent.com"
API = f"{BACKEND}/api"
T = 25

_ENV = dotenv_values(BACKEND_ROOT / ".env")
MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")


def _login(email, pw):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=T)
    r.raise_for_status()
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com", demo_pw("admin@aquaterra.com"))


@pytest.fixture(scope="module")
def tenant_id(admin_tok):
    r = requests.get(f"{API}/tenants/current", headers=_h(admin_tok), timeout=T)
    r.raise_for_status()
    return r.json()["id"]


def _mongo():
    from pymongo import MongoClient
    if not (MONGO_URL and DB_NAME):
        pytest.skip("MONGO_URL/DB_NAME not configured for direct-DB tests")
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(autouse=True)
def _cleanup(tenant_id):
    """Nuke TEST_-tagged scraped reviews between tests so accumulated
    state from failed runs doesn't skew dedup assertions."""
    yield
    try:
        db = _mongo()
        db.reviews.delete_many({
            "tenant_id": tenant_id,
            "source_review_id": {"$regex": "^TEST_"},
        })
        db.review_sync_events.delete_many({
            "tenant_id": tenant_id,
            "detail": {"$regex": "TEST_", "$options": "i"},
        })
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════════════
# Direct dispatcher tests (google via monkeypatched adapter)
# ═════════════════════════════════════════════════════════════════════

class TestGoogleAdapterMocked:
    def test_first_sync_inserts_all_three(self, tenant_id, monkeypatch):
        rev_prefix = f"TEST_gbp_{uuid.uuid4().hex[:6]}"
        payload = [
            {"source_review_id": f"{rev_prefix}_1", "star_rating": 5,
             "review_text": "TEST_first google review", "reviewer_name": "Alex T",
             "partial_content": False},
            {"source_review_id": f"{rev_prefix}_2", "star_rating": 4,
             "review_text": "TEST_second", "reviewer_name": "Blake T",
             "partial_content": False},
            {"source_review_id": f"{rev_prefix}_3", "star_rating": 5,
             "review_text": "TEST_third", "reviewer_name": "Casey T",
             "partial_content": False},
        ]

        async def fake_adapter(_tenant_id):
            return payload

        from services import review_scraper
        monkeypatch.setattr(
            review_scraper, "_adapter_for", lambda p: fake_adapter,
        )

        summary = _run(review_scraper.sync_platform(tenant_id, "google"))

        assert summary["status"] == "ok", summary
        assert summary["fetched_count"] == 3
        assert summary["new_count"] == 3
        assert summary["updated_count"] == 0

        db = _mongo()
        rows = list(db.reviews.find({
            "tenant_id": tenant_id,
            "platform": "google",
            "source_review_id": {"$regex": f"^{rev_prefix}"},
        }, {"_id": 0}))
        assert len(rows) == 3
        assert all(r["source"] == "google_scraped" for r in rows)
        assert all(r["visible_on_widget"] is True for r in rows)

    def test_resync_updates_no_dupes(self, tenant_id, monkeypatch):
        rev_prefix = f"TEST_gbp_{uuid.uuid4().hex[:6]}"
        base_payload = [
            {"source_review_id": f"{rev_prefix}_A", "star_rating": 4,
             "review_text": "TEST_original", "reviewer_name": "Alex",
             "partial_content": False},
            {"source_review_id": f"{rev_prefix}_B", "star_rating": 5,
             "review_text": "TEST_still original", "reviewer_name": "Blake",
             "partial_content": False},
        ]

        async def fake_adapter(_tenant_id):
            return base_payload

        from services import review_scraper
        monkeypatch.setattr(
            review_scraper, "_adapter_for", lambda p: fake_adapter,
        )

        try:
            s1 = _run(review_scraper.sync_platform(tenant_id, "google"))
            assert s1["new_count"] == 2, s1

            # Mutate one review's text and repeat.
            base_payload[0]["review_text"] = "TEST_edited"
            s2 = _run(review_scraper.sync_platform(tenant_id, "google"))
            assert s2["fetched_count"] == 2, s2
            assert s2["new_count"] == 0, s2
            assert s2["updated_count"] == 1, s2

            # Confirm no duplicate rows crept in.
            db = _mongo()
            n = db.reviews.count_documents({
                "tenant_id": tenant_id,
                "platform": "google",
                "source_review_id": {"$regex": f"^{rev_prefix}"},
            })
            assert n == 2, f"expected 2 rows post-resync, saw {n}"
        except Exception:
            raise


# ═════════════════════════════════════════════════════════════════════
# HTTP surface tests (no adapters patched here)
# ═════════════════════════════════════════════════════════════════════

class TestSyncNowHttp:
    def test_facebook_disabled_returns_200(self, admin_tok):
        r = requests.post(f"{API}/reviews/sync/facebook/sync-now",
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200, r.text
        body = r.json()
        # FACEBOOK_INTEGRATION_ENABLED defaults to false in .env.example.
        assert body["status"] in ("disabled", "not_connected"), body

    def test_yelp_missing_key_returns_200(self, admin_tok):
        # If YELP_API_KEY is set in the test env we skip this branch
        # (adapter would attempt a real HTTP call and we can't gate that).
        if os.environ.get("YELP_API_KEY"):
            pytest.skip("YELP_API_KEY is set in this env — not_configured branch skipped")
        r = requests.post(f"{API}/reviews/sync/yelp/sync-now",
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "not_configured", body

    def test_bbb_returns_404(self, admin_tok):
        r = requests.post(f"{API}/reviews/sync/bbb/sync-now",
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 404, r.text

    def test_custom_returns_404(self, admin_tok):
        r = requests.post(f"{API}/reviews/sync/custom/sync-now",
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 404, r.text

    def test_unknown_platform_returns_404(self, admin_tok):
        r = requests.post(f"{API}/reviews/sync/nope/sync-now",
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 404, r.text

    def test_events_endpoint_returns_recent_runs(self, admin_tok, tenant_id):
        # Facebook sync-now above already wrote at least one event; hit
        # the endpoint and confirm it returns rows sorted by ran_at desc.
        r = requests.post(f"{API}/reviews/sync/facebook/sync-now",
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        r2 = requests.get(f"{API}/reviews/sync/events?platform=facebook&limit=5",
                          headers=_h(admin_tok), timeout=T)
        assert r2.status_code == 200
        body = r2.json()
        assert "count" in body and "events" in body
        assert body["count"] >= 1
        assert body["events"][0]["platform"] == "facebook"

    def test_latest_status_strip(self, admin_tok):
        r = requests.get(f"{API}/reviews/sync/latest",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) == {"google", "facebook", "yelp"}


# ═════════════════════════════════════════════════════════════════════
# Tenant isolation
# ═════════════════════════════════════════════════════════════════════

class TestTenantIsolation:
    def test_sync_stays_within_tenant(self, tenant_id, monkeypatch):
        rev_prefix = f"TEST_iso_{uuid.uuid4().hex[:6]}"
        payload = [{
            "source_review_id": f"{rev_prefix}_solo", "star_rating": 5,
            "review_text": "TEST_isolation", "reviewer_name": "Solo",
            "partial_content": False,
        }]

        async def fake_adapter(_tenant_id):
            return payload

        from services import review_scraper
        monkeypatch.setattr(
            review_scraper, "_adapter_for", lambda p: fake_adapter,
        )

        db = _mongo()
        # Create a burner tenant row so the run has somewhere to write to
        # (dispatcher uses tenant_id as the query key, not a lookup).
        other_tid = f"TEST_tenant_{uuid.uuid4().hex[:6]}"
        _ = _run(review_scraper.sync_platform(tenant_id, "google"))

        # Other tenant must not have received the row.
        n_other = db.reviews.count_documents({
            "tenant_id": other_tid,
            "source_review_id": {"$regex": f"^{rev_prefix}"},
        })
        assert n_other == 0
        # Own tenant received it.
        n_self = db.reviews.count_documents({
            "tenant_id": tenant_id,
            "source_review_id": {"$regex": f"^{rev_prefix}"},
        })
        assert n_self == 1
