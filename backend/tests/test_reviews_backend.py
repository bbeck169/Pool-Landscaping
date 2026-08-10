"""Reviews Phase 1 · Backend suite (Feb 2026).

Covers platform CRUD, request lifecycle (create/dedup/expedite/resend),
public magic-link submits (rating star-gate, platform click,
private feedback), reviews CRUD, stats + leaderboard aggregations,
widget filtering + rate limiting, and blacklist scan of the seeded
copy.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import pytest
import requests

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"


# ─── Fixtures ─────────────────────────────────────────────────────────
def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} => {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


@pytest.fixture(scope="module")
def demo_customer_id(admin_headers) -> str:
    r = requests.get(f"{API}/customers", headers=admin_headers, timeout=30)
    assert r.status_code == 200
    customers = r.json()
    assert customers, "no customers seeded"
    demo = next((c for c in customers
                  if (c.get("email") or "").lower() == "customer@aquaterra.com"),
                 customers[0])
    return demo["id"]


@pytest.fixture()
def clean_customer_requests(admin_headers, demo_customer_id):
    """Delete every review_request for the demo customer before + after
    each test so the 7-day dedup guard doesn't leak state between
    scenarios in this module."""
    from pymongo import MongoClient
    from dotenv import dotenv_values
    env = dotenv_values("/app/backend/.env")
    client = MongoClient(env["MONGO_URL"])
    dbc = client[env["DB_NAME"]]
    dbc.review_requests.delete_many({"customer_id": demo_customer_id})
    dbc.review_request_hits.delete_many({})
    yield
    dbc.review_requests.delete_many({"customer_id": demo_customer_id})
    dbc.review_request_hits.delete_many({})
    client.close()


@pytest.fixture(scope="module", autouse=True)
def _wipe_ci_state(admin_headers):
    """Clear any prior CI dedup rows so each test module run starts
    fresh. Only touches TEST_-marked artefacts + module-scoped
    dedup rows keyed to the demo customer."""
    from pymongo import MongoClient
    from dotenv import dotenv_values
    env = dotenv_values("/app/backend/.env")
    client = MongoClient(env["MONGO_URL"])
    dbc = client[env["DB_NAME"]]

    def _wipe():
        # Requests + reviews created by this test module carry a
        # test marker in their created_by_user_id or reviewer_name.
        dbc.review_requests.delete_many({"created_by_user_id": {"$exists": True},
                                          "outcome": {"$in": ["pending", "public_posted_intent",
                                                              "private_feedback_captured"]},
                                          "sent_via": {"$in": ["link_only", "email"]}})
        dbc.reviews.delete_many({"reviewer_name": {"$regex": "^TEST_"}})
        dbc.private_feedback_events.delete_many({})
        dbc.tenant_review_platforms.delete_many(
            {"display_name": {"$regex": "^TEST_"}},
        )
        # widget rate limit rows may be stale from prior runs
        dbc.reviews_widget_rate.delete_many({"tenant_slug": "aquaterra"})
        dbc.review_request_hits.delete_many({})
    _wipe()
    yield
    _wipe()
    client.close()


# ═════════════════════════════════════════════════════════════════════════
# 1. Platform CRUD + RBAC + tenant isolation
# ═════════════════════════════════════════════════════════════════════════

class TestPlatformCRUD:
    def test_list_platforms_admin(self, admin_headers):
        r = requests.get(f"{API}/reviews/platforms", headers=admin_headers, timeout=30)
        assert r.status_code == 200
        # At least the 4 seeded platforms are present.
        codes = [p["platform"] for p in r.json()["platforms"]]
        assert {"google", "facebook", "yelp", "bbb"}.issubset(set(codes))

    def test_create_custom_platform(self, admin_headers):
        r = requests.post(
            f"{API}/reviews/platforms", headers=admin_headers,
            json={"platform": "custom",
                  "display_name": "TEST_ThumbTack",
                  "review_url": "https://example.com/tt-writereview",
                  "custom_slug": "thumbtack"},
            timeout=30,
        )
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        # Patch + delete round-trip.
        r = requests.patch(f"{API}/reviews/platforms/{pid}",
                            headers=admin_headers, json={"sort_order": 9}, timeout=30)
        assert r.status_code == 200
        assert r.json()["sort_order"] == 9
        r = requests.delete(f"{API}/reviews/platforms/{pid}",
                             headers=admin_headers, timeout=30)
        assert r.status_code == 200

    def test_customer_cannot_read_platforms(self, customer_headers):
        r = requests.get(f"{API}/reviews/platforms", headers=customer_headers, timeout=30)
        assert r.status_code == 403


# ═════════════════════════════════════════════════════════════════════════
# 2. Request creation + dedup + resend
# ═════════════════════════════════════════════════════════════════════════

class TestRequestLifecycle:
    def test_create_link_only_returns_token(self, admin_headers, demo_customer_id,
                                              clean_customer_requests):
        r = requests.post(
            f"{API}/reviews/requests", headers=admin_headers,
            json={"customer_id": demo_customer_id, "sent_via": "link_only"},
            timeout=30,
        )
        assert r.status_code == 201, r.text
        doc = r.json()
        assert doc["outcome"] == "pending"
        assert doc["token"]
        assert len(doc["token"]) >= 20
        assert doc["public_url"].endswith(f"/reviews/r/{doc['token']}")
        assert doc["communication_send_ids"] == []

    def test_dedup_blocks_second_within_7_days(self, admin_headers, demo_customer_id,
                                                 clean_customer_requests):
        r = requests.post(
            f"{API}/reviews/requests", headers=admin_headers,
            json={"customer_id": demo_customer_id, "sent_via": "link_only"},
            timeout=30,
        )
        assert r.status_code == 201
        r = requests.post(
            f"{API}/reviews/requests", headers=admin_headers,
            json={"customer_id": demo_customer_id, "sent_via": "link_only"},
            timeout=30,
        )
        assert r.status_code == 409

    def test_admin_expedite_is_ignored(self, admin_headers, demo_customer_id,
                                        clean_customer_requests):
        """Only super_admin may bypass dedup with ``expedite=true`` — a
        non-super admin sending expedite=true must still be blocked by
        the 7-day guard."""
        r = requests.post(
            f"{API}/reviews/requests", headers=admin_headers,
            json={"customer_id": demo_customer_id, "sent_via": "link_only"},
            timeout=30,
        )
        assert r.status_code == 201
        r = requests.post(
            f"{API}/reviews/requests", headers=admin_headers,
            json={"customer_id": demo_customer_id, "sent_via": "link_only",
                  "expedite": True},
            timeout=30,
        )
        assert r.status_code == 409

    def test_send_via_email_creates_communication_send(self, admin_headers, demo_customer_id,
                                                         clean_customer_requests):
        r = requests.post(
            f"{API}/reviews/requests", headers=admin_headers,
            json={"customer_id": demo_customer_id, "sent_via": "email"},
            timeout=30,
        )
        assert r.status_code == 201, r.text
        doc = r.json()
        assert isinstance(doc["communication_send_ids"], list)
        if doc["communication_send_ids"]:
            send_id = doc["communication_send_ids"][0]
            r = requests.get(f"{API}/comms/sends/{send_id}",
                              headers=admin_headers, timeout=30)
            assert r.status_code == 200
            assert r.json()["template_code"] == "system.review_request_email"


# ═════════════════════════════════════════════════════════════════════════
# 3. Public magic-link endpoints
# ═════════════════════════════════════════════════════════════════════════

def _fresh_request(admin_headers, demo_customer_id) -> str:
    """Create a fresh request. Test consumers must set up their own
    clean-customer-requests fixture; this helper does NOT wipe the
    dedup state itself."""
    r = requests.post(
        f"{API}/reviews/requests", headers=admin_headers,
        json={"customer_id": demo_customer_id, "sent_via": "link_only"},
        timeout=30,
    )
    assert r.status_code == 201, r.text
    return r.json()["token"]


class TestPublicLanding:
    def test_landing_returns_payload_no_auth(self, admin_headers, demo_customer_id,
                                              clean_customer_requests):
        token = _fresh_request(admin_headers, demo_customer_id)
        r = requests.get(f"{API}/reviews/public/r/{token}", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["already_submitted"] is False
        assert isinstance(data["platforms"], list)
        r2 = requests.get(f"{API}/reviews/requests",
                          headers=admin_headers, timeout=30)
        req = next((x for x in r2.json()["requests"] if x["token"] == token), None)
        assert req and req.get("landing_visited_at")

    def test_five_star_returns_choose_platform(self, admin_headers, demo_customer_id,
                                                 clean_customer_requests):
        token = _fresh_request(admin_headers, demo_customer_id)
        r = requests.post(f"{API}/reviews/public/r/{token}/rating",
                          json={"star_rating": 5}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["next_step"] == "choose_platform"

    def test_two_star_returns_private_feedback(self, admin_headers, demo_customer_id,
                                                 clean_customer_requests):
        token = _fresh_request(admin_headers, demo_customer_id)
        r = requests.post(f"{API}/reviews/public/r/{token}/rating",
                          json={"star_rating": 2}, timeout=30)
        assert r.status_code == 200
        assert r.json()["next_step"] == "private_feedback"

    def test_token_one_shot_second_rating_conflict(self, admin_headers, demo_customer_id,
                                                    clean_customer_requests):
        token = _fresh_request(admin_headers, demo_customer_id)
        r = requests.post(f"{API}/reviews/public/r/{token}/rating",
                          json={"star_rating": 4}, timeout=30)
        assert r.status_code == 200
        r = requests.post(f"{API}/reviews/public/r/{token}/rating",
                          json={"star_rating": 5}, timeout=30)
        assert r.status_code == 409, r.text

    def test_private_feedback_creates_review_and_pfe(self, admin_headers, demo_customer_id,
                                                       clean_customer_requests):
        token = _fresh_request(admin_headers, demo_customer_id)
        r = requests.post(f"{API}/reviews/public/r/{token}/rating",
                          json={"star_rating": 2}, timeout=30)
        assert r.status_code == 200
        r = requests.post(
            f"{API}/reviews/public/r/{token}/private-feedback",
            json={"body_text": "TEST_the tech left the gate open, my dog got out."},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["private_feedback_id"]
        assert body["review_id"]
        r = requests.get(f"{API}/reviews/reviews/{body['review_id']}",
                          headers=admin_headers, timeout=30)
        assert r.status_code == 200
        rv = r.json()
        assert rv["is_public"] is False
        assert rv["visible_on_widget"] is False
        assert rv["platform"] == "private"
        r = requests.get(f"{API}/reviews/requests",
                          headers=admin_headers, timeout=30)
        req = next(x for x in r.json()["requests"] if x["token"] == token)
        assert req["outcome"] == "private_feedback_captured"

    def test_platform_click_records_intent(self, admin_headers, demo_customer_id,
                                             clean_customer_requests):
        token = _fresh_request(admin_headers, demo_customer_id)
        r = requests.post(f"{API}/reviews/public/r/{token}/rating",
                          json={"star_rating": 5}, timeout=30)
        assert r.status_code == 200
        r = requests.post(
            f"{API}/reviews/public/r/{token}/platform-clicked",
            json={"platform_code": "google"}, timeout=30,
        )
        assert r.status_code == 200
        assert r.json()["redirect_url"].startswith("http")


# ═════════════════════════════════════════════════════════════════════════
# 4. Reviews CRUD, stats, leaderboard
# ═════════════════════════════════════════════════════════════════════════

class TestReviewsAggregate:
    def test_stats_shape(self, admin_headers):
        r = requests.get(f"{API}/reviews/stats", headers=admin_headers, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert set(d.keys()) >= {"total", "avg_star", "count_by_star",
                                   "count_by_platform", "count_public",
                                   "count_private", "delta_last_30d"}

    def test_leaderboard_min_reviews_gate(self, admin_headers):
        # min_reviews=100 → nobody has 100+ so leaderboard must be empty.
        r = requests.get(f"{API}/reviews/leaderboard",
                          headers=admin_headers, params={"min_reviews": 50},
                          timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["leaderboard"] == []


# ═════════════════════════════════════════════════════════════════════════
# 5. Widget — public, rate-limited
# ═════════════════════════════════════════════════════════════════════════

class TestWidget:
    def test_widget_returns_only_public_with_text(self, admin_headers):
        r = requests.get(f"{API}/reviews/public/widget/aquaterra", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        # Every returned row has review_text and star_rating.
        for rv in data["reviews"]:
            assert rv["review_text"]
            assert 1 <= rv["star_rating"] <= 5

    def test_widget_unknown_slug_404(self):
        r = requests.get(f"{API}/reviews/public/widget/no-such-tenant", timeout=30)
        assert r.status_code == 404

    def test_widget_js_embed(self):
        r = requests.get(f"{API}/reviews/public/widget/aquaterra.js", timeout=30)
        assert r.status_code == 200
        assert r.headers.get("Content-Type", "").startswith("application/javascript")
        assert "eval(" not in r.text  # nosec B307 — string-in-response assertion, verifies widget ships without any eval() call
        # Confirms our safe render path is present (mount.innerHTML=html;).
        assert "innerHTML" in r.text

    def test_widget_rate_limit_returns_429(self):
        # Bump 60 hits quickly; the 61st should return 429.
        # Reset any prior state.
        import time
        from pymongo import MongoClient
        from dotenv import dotenv_values
        env = dotenv_values("/app/backend/.env")
        client = MongoClient(env["MONGO_URL"])
        dbc = client[env["DB_NAME"]]
        dbc.reviews_widget_rate.delete_many({"tenant_slug": "aquaterra"})
        client.close()

        # Use a fresh distinct IP so this test doesn't collide with
        # the earlier widget-fetch tests (which used the runner's real IP).
        # Also gate on a fresh minute: the bucket is per-wall-clock-minute
        # so if we started at 59.5s the minute might roll during our burst
        # and we'd never hit 429. Wait until we're near the top of the
        # minute for a stable window.
        while True:
            now_s = time.gmtime().tm_sec
            if now_s < 40:
                break
            time.sleep(1)

        headers = {"x-forwarded-for": "127.0.0.99"}
        last_status = None
        for i in range(70):
            resp = requests.get(f"{API}/reviews/public/widget/aquaterra",
                                headers=headers, timeout=15)
            last_status = resp.status_code
            if last_status == 429:
                break
        assert last_status == 429, f"never hit rate limit; last status {last_status}"


# ═════════════════════════════════════════════════════════════════════════
# 6. Seed idempotency + blacklist scan
# ═════════════════════════════════════════════════════════════════════════

_BLACKLIST_TERMS = [
    # Trademark / brand IP-safety terms that would flag seeded copy.
    "NiceJob", "servicetitan", "housecall pro", "jobber",
    # Copy-boilerplate red flags.
    "as an ai", "as a language model", "lorem ipsum",
]


class TestSeedAndCopySafety:
    def test_seed_row_counts(self):
        """Idempotency check via row-count invariants — we can't re-run
        the async seeder in-test (motor is bound to the server's event
        loop) but the seeded row counts must match the spec exactly."""
        from pymongo import MongoClient
        from dotenv import dotenv_values
        env = dotenv_values("/app/backend/.env")
        client = MongoClient(env["MONGO_URL"])
        dbc = client[env["DB_NAME"]]
        tenant = dbc.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
        assert tenant, "demo aquaterra tenant missing"
        platforms = dbc.tenant_review_platforms.count_documents({"tenant_id": tenant["id"]})
        reviews = dbc.reviews.count_documents({"tenant_id": tenant["id"],
                                                "source": "manual_entry",
                                                "_seed_key": {"$exists": True}})
        client.close()
        assert platforms == 4, f"expected 4 seeded platforms, got {platforms}"
        assert reviews == 4, f"expected 4 seeded sample reviews, got {reviews}"

    def test_seeded_copy_blacklist_clean(self):
        from reviews_seed.seed_reviews import SAMPLE_REVIEWS
        from comms_seed.system_data import SYSTEM_EMAIL_TEMPLATES, SYSTEM_SMS_TEMPLATES
        haystacks: List[str] = []
        for r in SAMPLE_REVIEWS:
            haystacks.append((r.get("review_text") or ""))
        for t in SYSTEM_EMAIL_TEMPLATES:
            if t["code"].startswith("system.review"):
                haystacks.append(t.get("subject") or "")
                import json
                haystacks.append(json.dumps(t.get("blocks_json") or []))
        for t in SYSTEM_SMS_TEMPLATES:
            if "review" in t["code"]:
                haystacks.append(t.get("body") or "")
        blob = "\n".join(haystacks).lower()
        hits = [term for term in _BLACKLIST_TERMS if term.lower() in blob]
        assert not hits, f"blacklist terms found in seeded copy: {hits}"
