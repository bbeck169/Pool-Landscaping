"""Feb-2026 · Slice 6 — Customer-portal reviews endpoint tests."""
from __future__ import annotations

import asyncio
import os
import time
from typing import Optional

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


def _purge_reviews_and_rate_limit():
    """Fresh state per module — drop the caller customer's slice-6
    reviews so the rate-limit doesn't spill over from prior test
    runs."""
    async def _go():
        from motor.motor_asyncio import AsyncIOMotorClient
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        db = AsyncIOMotorClient(
            os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        u = await db.users.find_one({"email": "customer@aquaterra.com"},
                                      {"_id": 0, "customer_id": 1, "tenant_id": 1})
        if not u:
            return
        await db.customer_portal_reviews.delete_many(
            {"tenant_id": u["tenant_id"], "customer_id": u["customer_id"]},
        )
    asyncio.new_event_loop().run_until_complete(_go())


@pytest.fixture(scope="module", autouse=True)
def _reset_state():
    _purge_reviews_and_rate_limit()
    yield
    _purge_reviews_and_rate_limit()


def _set_tenant_google_url(url: Optional[str]):
    async def _go():
        from motor.motor_asyncio import AsyncIOMotorClient
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        db = AsyncIOMotorClient(
            os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        u = await db.users.find_one({"email": "customer@aquaterra.com"},
                                      {"_id": 0, "tenant_id": 1})
        await db.tenants.update_one(
            {"id": u["tenant_id"]},
            {"$set": {"google_review_url": url}},
        )
    asyncio.new_event_loop().run_until_complete(_go())


# ═══════════════════════════════════════════════════════════════════════
# Tenant Google URL config
# ═══════════════════════════════════════════════════════════════════════
def test_google_url_read_allowed_for_all_roles(customer_headers,
                                                  admin_headers, tech_headers):
    for h in (customer_headers, admin_headers, tech_headers):
        r = requests.get(f"{API}/tenants/mine/google-review-url",
                          headers=h, timeout=15)
        assert r.status_code == 200, r.text
        assert "url" in r.json()


def test_google_url_write_super_only(super_headers, admin_headers, customer_headers):
    good = "https://g.page/r/some-place/review"
    # Super admin — 200
    r = requests.patch(f"{API}/tenants/mine/google-review-url",
                        headers=super_headers, json={"url": good}, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["url"] == good

    # Admin — 403
    r = requests.patch(f"{API}/tenants/mine/google-review-url",
                        headers=admin_headers, json={"url": good}, timeout=15)
    assert r.status_code == 403

    # Customer — 403
    r = requests.patch(f"{API}/tenants/mine/google-review-url",
                        headers=customer_headers, json={"url": good}, timeout=15)
    assert r.status_code == 403


def test_google_url_write_rejects_non_google(super_headers):
    for bad in ("https://yelp.com/biz/foo", "not-a-url", "ftp://google.com",
                 "https://example.com/reviews", ""):
        # Empty string is treated as "clear the URL" — valid.
        r = requests.patch(f"{API}/tenants/mine/google-review-url",
                            headers=super_headers, json={"url": bad}, timeout=15)
        if bad == "":
            assert r.status_code == 200
        else:
            assert r.status_code == 422, (
                f"URL {bad!r} should have been rejected but got {r.status_code}"
            )


def test_google_url_accepts_valid_variants(super_headers):
    for good in (
        "https://g.page/r/CAxyz/review",
        "https://search.google.com/local/writereview?placeid=abc123",
        "https://maps.google.com/maps?cid=1234567890",
        "https://www.google.com/maps/place/foo/@33.5,-112.1",
    ):
        r = requests.patch(f"{API}/tenants/mine/google-review-url",
                            headers=super_headers, json={"url": good}, timeout=15)
        assert r.status_code == 200, f"URL {good!r} rejected: {r.text}"
        assert r.json()["url"] == good


# ═══════════════════════════════════════════════════════════════════════
# Review submission — rating branch
# ═══════════════════════════════════════════════════════════════════════
def test_low_rating_flags_private_and_escalates(customer_headers, admin_headers):
    _purge_reviews_and_rate_limit()
    _set_tenant_google_url("https://g.page/r/testtenant/review")

    r = requests.get(f"{API}/notifications?limit=1", headers=admin_headers,
                      timeout=15)
    before_bell = requests.get(f"{API}/notifications/unread-count",
                                headers=admin_headers, timeout=15).json().get(
        "count", 0)

    r = requests.post(f"{API}/customer-portal/reviews",
                       headers=customer_headers,
                       json={"rating": 2, "comment": "Slice6-low-test — pool wasn't cleaned properly."},
                       timeout=15)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["is_public"] is False
    assert body.get("google_review_url") is None, (
        "low ratings must NEVER return the Google CTA URL"
    )

    # Bell must have incremented — the review fired an escalation.
    after_bell = requests.get(f"{API}/notifications/unread-count",
                               headers=admin_headers, timeout=15).json().get(
        "count", 0)
    assert after_bell >= before_bell + 1, (
        f"admin bell did not increment after private review "
        f"(before={before_bell}, after={after_bell})"
    )

    # Locate the escalation row and confirm it deep-links to the
    # working /communication/{cid} route (regression on the 3D bug).
    rows = requests.get(f"{API}/notifications?limit=50",
                        headers=admin_headers, timeout=15).json() or []
    target = next(
        (n for n in rows
         if (n.get("source_ref") or {}).get("kind") == "review"),
        None,
    )
    assert target is not None, "no ``review`` bell row visible to admin"
    href = target.get("href") or ""
    assert href.startswith("/communication/"), (
        f"review bell href must open the admin thread — got {href!r}"
    )


def test_high_rating_returns_google_url_when_configured(customer_headers):
    _purge_reviews_and_rate_limit()
    _set_tenant_google_url("https://g.page/r/testtenant/review")
    r = requests.post(f"{API}/customer-portal/reviews",
                       headers=customer_headers,
                       json={"rating": 5, "comment": "Great service, thanks!"},
                       timeout=15)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["is_public"] is True
    assert body["google_review_url"] == "https://g.page/r/testtenant/review"


def test_high_rating_graceful_when_no_url(customer_headers):
    _purge_reviews_and_rate_limit()
    _set_tenant_google_url(None)
    r = requests.post(f"{API}/customer-portal/reviews",
                       headers=customer_headers,
                       json={"rating": 4, "comment": "Good visit."},
                       timeout=15)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["is_public"] is True
    assert body["google_review_url"] in (None, "")


def test_invalid_rating_rejected(customer_headers):
    _purge_reviews_and_rate_limit()
    for bad in (0, 6, -1, "five"):
        r = requests.post(f"{API}/customer-portal/reviews",
                           headers=customer_headers,
                           json={"rating": bad, "comment": ""},
                           timeout=15)
        assert r.status_code in (400, 422), (
            f"rating={bad!r} should be rejected — got {r.status_code}"
        )


def test_rate_limit_second_within_five_min(customer_headers):
    _purge_reviews_and_rate_limit()
    _set_tenant_google_url(None)
    r1 = requests.post(f"{API}/customer-portal/reviews",
                        headers=customer_headers,
                        json={"rating": 5, "comment": "First!"},
                        timeout=15)
    assert r1.status_code == 201, r1.text
    r2 = requests.post(f"{API}/customer-portal/reviews",
                        headers=customer_headers,
                        json={"rating": 5, "comment": "Second!"},
                        timeout=15)
    assert r2.status_code == 429, r2.text


# ═══════════════════════════════════════════════════════════════════════
# History / RBAC
# ═══════════════════════════════════════════════════════════════════════
def test_customer_sees_only_own_reviews(customer_headers, admin_headers):
    _purge_reviews_and_rate_limit()
    r = requests.post(f"{API}/customer-portal/reviews",
                       headers=customer_headers,
                       json={"rating": 5, "comment": "History test"},
                       timeout=15)
    assert r.status_code == 201, r.text
    r2 = requests.get(f"{API}/customer-portal/reviews/my",
                       headers=customer_headers, timeout=15)
    assert r2.status_code == 200
    rows = r2.json()
    assert len(rows) >= 1
    for row in rows:
        # Admin-only fields must never surface here.
        assert "admin_notes" not in row
        assert "status" not in row


def test_customer_history_forbidden_for_non_customers(admin_headers, tech_headers):
    for h in (admin_headers, tech_headers):
        r = requests.get(f"{API}/customer-portal/reviews/my",
                          headers=h, timeout=15)
        assert r.status_code == 403


def test_admin_lists_all_reviews(admin_headers, customer_headers):
    _purge_reviews_and_rate_limit()
    requests.post(f"{API}/customer-portal/reviews",
                   headers=customer_headers,
                   json={"rating": 3, "comment": "admin-visible-test"},
                   timeout=15)
    r = requests.get(f"{API}/admin/reviews",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "reviews" in body
    assert body["total"] >= 1
    # Filter tests
    r = requests.get(f"{API}/admin/reviews?is_public=false",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200
    for row in r.json()["reviews"]:
        assert row["is_public"] is False


def test_admin_reviews_forbidden_for_customer(customer_headers):
    r = requests.get(f"{API}/admin/reviews",
                      headers=customer_headers, timeout=15)
    assert r.status_code == 403


def test_admin_can_patch_status_and_notes(admin_headers, customer_headers):
    _purge_reviews_and_rate_limit()
    r = requests.post(f"{API}/customer-portal/reviews",
                       headers=customer_headers,
                       json={"rating": 2, "comment": "patch-test"},
                       timeout=15).json()
    rid = r["review_id"]
    p = requests.patch(f"{API}/admin/reviews/{rid}",
                        headers=admin_headers,
                        json={"status": "resolved",
                              "admin_notes": "Rang customer 2/14; sorted."},
                        timeout=15)
    assert p.status_code == 200, p.text
    body = p.json()
    assert body["status"] == "resolved"
    assert body["admin_notes"].startswith("Rang customer")
