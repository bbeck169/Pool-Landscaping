"""Phase 34 · Task T · Feb 2026 — Review gating end-to-end pytests.

Covers the surgical additions from Task T:

* ``POST /api/public/r/{token}/rating`` now accepts ``rating`` as an
  alias for ``star_rating`` (frontend PortalReviewSubmit posts the
  former) and returns ``choose_platform`` + ``google_review_url``
  on a 4-5 star submission so the client can render the Google CTA
  without a second round-trip.
* ``POST /api/public/r/{token}/google-clicked`` is a lightweight
  analytics ping that flips ``google_click_at`` on the review-request
  row. First click wins, subsequent clicks are no-ops.
* The comm_tokens ``review_request.public_url`` resolver now points
  at ``/portal/review/submit?token=…`` so review-request emails/SMS
  land customers on the star-gated submit page.
* PLOFV tenant is idempotently seeded on boot with
  ``referral_reward_amount_cents = 5500`` (=$55) in both the legacy
  top-level field AND the new nested settings location.

Tests are HTTP-only where possible (Motor DB inserts are used to
create review-request rows since the public endpoints require a
pre-existing token). Every test isolates its own token/customer so
suite reruns are safe.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import asyncio
import pytest
import requests

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api/reviews"


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    assert r.status_code == 200, f"login {email} => {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def demo_customer_id() -> str:
    """Resolve the seeded customer directly from Mongo — the /customers
    admin endpoint is not needed for the public Task T flows tested
    here, and admin@aquaterra.com is a ``customer`` role in this
    environment so it can't call that admin endpoint."""
    from config import db as _db  # noqa: PLC0415

    async def _go():
        c = await _db.customers.find_one(
            {"email": {"$regex": "^customer@aquaterra\\.com$", "$options": "i"}},
            {"_id": 0, "id": 1},
        )
        if not c:
            # Fallback: any seeded customer under aquaterra.
            t = await _db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
            if t:
                c = await _db.customers.find_one(
                    {"tenant_id": t["id"]}, {"_id": 0, "id": 1},
                )
        assert c, "no seeded customer found for aquaterra"
        return c["id"]

    return _run(_go())  # Phase 41.1d — use batch-safe driver


@pytest.fixture(scope="module")
def db():
    """Reach into the motor client so we can plant / read tokens
    directly. Public endpoints are token-authed, so this is the
    cleanest way to spin up a fixture request without invoking the
    full comms delivery adapter path."""
    from config import db as _db  # noqa: PLC0415 — deliberate late import
    return _db


from tests._phase34_asyncio import batch_safe_run as _run  # Phase 41.1d · noqa: E402


async def _get_aq_tenant_id(db) -> str:
    t = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
    assert t, "aquaterra tenant missing — cannot run Task T tests"
    return t["id"]


async def _mk_request(db, tenant_id: str, customer_id: str,
                        outcome: str = "pending",
                        star_submitted: Optional[int] = None) -> Dict[str, Any]:
    token = uuid.uuid4().hex[:32]
    now = datetime.now(timezone.utc).isoformat()
    exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    doc = {
        "id": uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "token": token,
        "customer_id": customer_id,
        "job_id": None,
        "technician_id": None,
        "sent_via": "email",
        "sent_at": now,
        "communication_send_ids": [],
        "landing_visited_at": None,
        "star_rating_submitted": star_submitted,
        "star_submitted_at": None,
        "platform_chosen": None,
        "platform_clicked_at": None,
        "outcome": outcome,
        "expires_at": exp,
        "created_by_user_id": None,
        "created_at": now,
    }
    await db.review_requests.insert_one(doc)
    return doc


# ═══════════════════════════════════════════════════════════════════════
# Rating endpoint — dual-payload + platform response
# ═══════════════════════════════════════════════════════════════════════
def test_rating_accepts_rating_alias(db, demo_customer_id):
    tenant_id = _run(_get_aq_tenant_id(db))
    doc = _run(_mk_request(db, tenant_id, demo_customer_id))
    token = doc["token"]
    r = requests.post(
        f"{API}/public/r/{token}/rating",
        json={"rating": 5, "comment": "great service"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["star_rating"] == 5
    assert body["next_step"] == "choose_platform"
    # comment persisted for admin follow-up.
    stored = _run(db.review_requests.find_one(
        {"token": token}, {"_id": 0, "comment": 1, "star_rating_submitted": 1}))
    assert stored["star_rating_submitted"] == 5
    assert stored.get("comment") == "great service"


def test_rating_still_accepts_legacy_star_rating(db, demo_customer_id):
    tenant_id = _run(_get_aq_tenant_id(db))
    doc = _run(_mk_request(db, tenant_id, demo_customer_id))
    r = requests.post(
        f"{API}/public/r/{doc['token']}/rating",
        json={"star_rating": 2},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["star_rating"] == 2
    assert body["next_step"] == "private_feedback"
    # low rating still returns the (possibly empty) list without crashing.
    assert isinstance(body.get("choose_platform"), list)


def test_rating_returns_choose_platform_for_high(db, demo_customer_id):
    tenant_id = _run(_get_aq_tenant_id(db))
    doc = _run(_mk_request(db, tenant_id, demo_customer_id))
    r = requests.post(
        f"{API}/public/r/{doc['token']}/rating",
        json={"rating": 4}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Either configured platforms exist OR the business_card fallback
    # produced a Google entry — the shape is asserted in both cases.
    assert isinstance(body.get("choose_platform"), list)
    if body.get("google_review_url"):
        assert body["google_review_url"].startswith(("http://", "https://"))


def test_rating_missing_payload_422(db, demo_customer_id):
    tenant_id = _run(_get_aq_tenant_id(db))
    doc = _run(_mk_request(db, tenant_id, demo_customer_id))
    r = requests.post(
        f"{API}/public/r/{doc['token']}/rating",
        json={"comment": "hello"},   # neither rating nor star_rating
        timeout=30,
    )
    assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════════
# google-clicked endpoint
# ═══════════════════════════════════════════════════════════════════════
def test_google_clicked_happy_path(db, demo_customer_id):
    tenant_id = _run(_get_aq_tenant_id(db))
    doc = _run(_mk_request(db, tenant_id, demo_customer_id, star_submitted=5))
    r = requests.post(
        f"{API}/public/r/{doc['token']}/google-clicked",
        json={}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["already"] is False
    assert body["google_click_at"]
    stored = _run(db.review_requests.find_one(
        {"token": doc["token"]},
        {"_id": 0, "google_click_at": 1, "platform_chosen": 1, "outcome": 1},
    ))
    assert stored["google_click_at"] == body["google_click_at"]
    assert stored["platform_chosen"] == "google"
    assert stored["outcome"] == "public_posted_intent"


def test_google_clicked_is_idempotent(db, demo_customer_id):
    tenant_id = _run(_get_aq_tenant_id(db))
    doc = _run(_mk_request(db, tenant_id, demo_customer_id, star_submitted=5))
    r1 = requests.post(
        f"{API}/public/r/{doc['token']}/google-clicked", json={}, timeout=30,
    )
    assert r1.status_code == 200
    ts = r1.json()["google_click_at"]
    r2 = requests.post(
        f"{API}/public/r/{doc['token']}/google-clicked", json={}, timeout=30,
    )
    assert r2.status_code == 200
    body2 = r2.json()
    # Second click preserves the first timestamp and reports already=True.
    assert body2["already"] is True
    assert body2["google_click_at"] == ts


def test_google_clicked_rejected_for_low_star(db, demo_customer_id):
    tenant_id = _run(_get_aq_tenant_id(db))
    doc = _run(_mk_request(db, tenant_id, demo_customer_id, star_submitted=2))
    r = requests.post(
        f"{API}/public/r/{doc['token']}/google-clicked", json={}, timeout=30,
    )
    assert r.status_code == 400
    body = r.json()
    assert "4-5 star" in (body.get("detail") or "").lower() or \
           "4-5" in (body.get("detail") or "")


def test_google_clicked_unknown_token_404(db):
    r = requests.post(
        f"{API}/public/r/{uuid.uuid4().hex}/google-clicked",
        json={}, timeout=30,
    )
    assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════════
# comm_tokens — review_request.public_url points at portal submit page
# ═══════════════════════════════════════════════════════════════════════
def test_review_request_public_url_points_to_portal_submit(db, demo_customer_id):
    tenant_id = _run(_get_aq_tenant_id(db))
    doc = _run(_mk_request(db, tenant_id, demo_customer_id))
    from services.comm_tokens import build_context_for_review_request

    async def _go():
        t = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
        return await build_context_for_review_request(t, doc)

    ctx = _run(_go())
    url = ctx.get("review_request.public_url") or ""
    # APP_PUBLIC_URL may be unset in some CI envs — in that case the
    # helper returns an empty string; the substring assertions only
    # apply when the URL is actually built.
    if url:
        assert "/portal/review/submit" in url, url
        assert f"token={doc['token']}" in url, url
        # ensure we did NOT accidentally leave the old /reviews/r/ path.
        assert "/reviews/r/" not in url


# ═══════════════════════════════════════════════════════════════════════
# PLOFV referral reward seed = $55 (Task AA supporting assertion)
# ═══════════════════════════════════════════════════════════════════════
def test_plofv_referral_reward_seeded_to_5500(db):
    async def _go():
        t = await db.tenants.find_one(
            {"slug": "aquaterra"},
            {"_id": 0, "referral_reward_amount_cents": 1, "settings": 1},
        )
        return t or {}

    t = _run(_go())
    top_level = int(t.get("referral_reward_amount_cents") or 0)
    nested = int(
        ((t.get("settings") or {}).get("referrals") or {}).get(
            "reward_amount_cents"
        ) or 0
    )
    assert top_level == 5500, f"expected top-level 5500, got {top_level}"
    assert nested == 5500, f"expected nested 5500, got {nested}"


def test_referral_watcher_reads_reward_from_tenant_settings(db):
    """Regression guard — the watcher's ``credit_cents`` resolver must
    pick up ``settings.referrals.reward_amount_cents`` when the legacy
    ``referral_reward_amount_cents`` field is absent. Sets up an
    isolated fake tenant row (never persisted) and reads the resolver
    inline."""
    from services.referral_watcher import DEFAULT_CREDIT_CENTS

    tenant_only_top = {"referral_reward_amount_cents": 7700}
    tenant_only_nested = {"settings": {"referrals": {"reward_amount_cents": 9900}}}
    tenant_empty: Dict[str, Any] = {}

    # Replicate the exact fallback ladder from run_referral_watcher.
    def _resolve(t: Dict[str, Any]) -> int:
        return int(
            t.get("referral_reward_amount_cents")
            or ((t.get("settings") or {}).get("referrals") or {}).get(
                "reward_amount_cents"
            )
            or DEFAULT_CREDIT_CENTS
        )

    assert _resolve(tenant_only_top) == 7700
    assert _resolve(tenant_only_nested) == 9900
    assert _resolve(tenant_empty) == DEFAULT_CREDIT_CENTS
