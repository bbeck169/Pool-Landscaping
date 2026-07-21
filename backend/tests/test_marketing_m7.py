"""Feb-2026 · Marketing Slice M7 — analytics endpoints, cache and
AI-employee narrative actions."""
from __future__ import annotations

import asyncio, os, time, uuid
from datetime import datetime, timedelta, timezone

import pytest, requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers(): return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}
@pytest.fixture(scope="module")
def tech_headers(): return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}
@pytest.fixture(scope="module")
def customer_headers(): return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
def _run(coro): return _LOOP.run_until_complete(coro)


def _rebind_db_to_loop():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = fresh_db
    import routers.marketing_analytics as _ma
    _ma.db = fresh_db
    return fresh_db


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    _rebind_db_to_loop()
    yield


def _clear_cache_via_http(admin_headers):
    """Clears the LIVE backend's in-process cache (test process has a
    separate copy).  Idempotent + safe to call before every test that
    asserts on ``_cache: "miss"``."""
    requests.post(f"{API}/marketing/analytics/_cache/clear",
                   headers=admin_headers, timeout=15)


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(os.environ["MONGO_URL"],
                               io_loop=_LOOP)[os.environ["DB_NAME"]]


async def _tenant_of_admin():
    u = await _db().users.find_one({"email": "admin@aquaterra.com"},
                                    {"_id": 0, "tenant_id": 1})
    return u["tenant_id"]


# ═══════════════════════════════════════════════════════════════════════
# RBAC + basic shape
# ═══════════════════════════════════════════════════════════════════════
def test_overview_admin_only(admin_headers, tech_headers, customer_headers):
    r = requests.get(f"{API}/marketing/analytics/overview?window=7d",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    for k in ("window", "campaigns", "sequences", "review_requests",
              "top_sequences", "top_campaigns", "trend"):
        assert k in body, f"missing key {k}"
    for k in ("total_sent", "active", "delivered", "opened", "clicked", "converted"):
        assert k in body["campaigns"]
    for k in ("total_enrolments", "active", "completed", "halted",
               "avg_completion_hours"):
        assert k in body["sequences"]
    for k in ("queued", "sent", "opened", "reviewed", "expired",
               "avg_rating", "review_rate_pct"):
        assert k in body["review_requests"]

    for h in (tech_headers, customer_headers):
        assert requests.get(f"{API}/marketing/analytics/overview",
                             headers=h, timeout=15).status_code in (401, 403)


def test_overview_window_validation(admin_headers):
    r = requests.get(f"{API}/marketing/analytics/overview?window=bogus",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 422


def test_review_request_endpoint_shape(admin_headers):
    r = requests.get(f"{API}/marketing/analytics/review-requests?window=30d",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["window"] == "30d"
    assert "funnel" in body
    stages = [s["stage"] for s in body["funnel"]]
    assert stages == ["queued", "sent", "opened", "reviewed"]


def test_campaign_and_sequence_shape_or_404(admin_headers):
    # Random ids → 404
    for path in (
        "/marketing/analytics/campaigns/does-not-exist",
        "/marketing/analytics/sequences/does-not-exist",
    ):
        assert requests.get(f"{API}{path}", headers=admin_headers,
                             timeout=15).status_code == 404


# ═══════════════════════════════════════════════════════════════════════
# Seeded fixture → assert counts + windowing
# ═══════════════════════════════════════════════════════════════════════
def test_seeded_counts_and_window_filtering(admin_headers):
    """Insert 3 fresh drip enrolments (2 completed, 1 active) + 2
    review requests (1 reviewed, 1 sent) inside the 7d window, plus a
    60-day-old completed enrolment that should NOT show up in the 7d
    window but must appear in ``all``."""
    

    async def _seed():
        db = _db()
        tid = await _tenant_of_admin()
        now = datetime.now(timezone.utc)
        # Recent fixtures
        recent = now - timedelta(hours=6)
        ids = {"seq": f"m7-seq-{uuid.uuid4().hex[:6]}",
                "e1": f"m7-e1-{uuid.uuid4().hex[:6]}",
                "e2": f"m7-e2-{uuid.uuid4().hex[:6]}",
                "e3": f"m7-e3-{uuid.uuid4().hex[:6]}",
                "rr1": f"m7-rr1-{uuid.uuid4().hex[:6]}",
                "rr2": f"m7-rr2-{uuid.uuid4().hex[:6]}",
                "old": f"m7-old-{uuid.uuid4().hex[:6]}",
                }
        await db.marketing_sequences.insert_one({
            "id": ids["seq"], "tenant_id": tid, "name": "M7 fixture",
            "trigger_type": "manual", "trigger_config": {},
            "steps": [{"order": 0, "channel": "email", "template_id": "x",
                        "delay_from": "trigger", "delay_hours": 0,
                        "condition": None}],
            "active": True, "stop_on_reply": True, "stop_on_unsubscribe": True,
            "system": False, "created_at": recent.isoformat(),
            "updated_at": recent.isoformat(),
        })
        # 2 completed, 1 active — enrolled 6h ago
        for eid, status, hist in (
            (ids["e1"], "completed",
             [{"channel": "email", "template_id": "x",
                "sent_at": (recent + timedelta(hours=2)).isoformat()}]),
            (ids["e2"], "completed",
             [{"channel": "email", "template_id": "x",
                "sent_at": (recent + timedelta(hours=3)).isoformat()}]),
            (ids["e3"], "active", []),
        ):
            await db.marketing_drip_enrolments.insert_one({
                "id": eid, "tenant_id": tid, "sequence_id": ids["seq"],
                "customer_id": f"cust-{eid[:8]}",
                "trigger_source": "manual",
                "enrolled_at": recent.isoformat(),
                "current_step": 1 if status == "completed" else 0,
                "next_send_at": None if status == "completed" else recent.isoformat(),
                "status": status, "halt_reason": None, "history": hist,
            })
        # A 60-day-old completed enrolment (out of 7d window).
        old = now - timedelta(days=60)
        await db.marketing_drip_enrolments.insert_one({
            "id": ids["old"], "tenant_id": tid, "sequence_id": ids["seq"],
            "customer_id": "cust-old", "trigger_source": "manual",
            "enrolled_at": old.isoformat(), "current_step": 1,
            "next_send_at": None, "status": "completed",
            "halt_reason": None,
            "history": [{"channel": "email", "template_id": "x",
                          "sent_at": (old + timedelta(hours=1)).isoformat()}],
        })
        # Review requests — 1 reviewed w/ rating=5, 1 sent (open funnel).
        for rrid, status, rating in (
            (ids["rr1"], "reviewed", 5),
            (ids["rr2"], "sent", None),
        ):
            await db.marketing_review_requests.insert_one({
                "id": rrid, "tenant_id": tid,
                "customer_id": f"cust-{rrid[:6]}",
                "service_report_id": None, "drip_enrolment_id": None,
                "channel": "email", "template_id": None, "delivery_id": None,
                "magic_link": "/r/review?token=x",
                "status": status,
                "requested_at": recent.isoformat(),
                "next_send_at": recent.isoformat(),
                "expire_at": (recent + timedelta(days=30)).isoformat(),
                "sent_at": recent.isoformat() if status != "queued" else None,
                "opened_at": None,
                "reviewed_at": recent.isoformat() if status == "reviewed" else None,
                "review_id": None,
                "review_rating": rating,
                "source": "manual",
                "created_at": recent.isoformat(),
                "updated_at": recent.isoformat(),
            })
        return tid, ids

    tid, ids = _run(_seed())
    try:
        _clear_cache_via_http(admin_headers)
        r7 = requests.get(f"{API}/marketing/analytics/overview?window=7d",
                           headers=admin_headers, timeout=15).json()
        # 7d window MUST include our 3 fresh enrolments but NOT the 60d-old row.
        assert r7["sequences"]["total_enrolments"] >= 3
        # 60-day-old completed row shouldn't sneak in.
        cnt_recent = r7["sequences"]["completed"]
        _clear_cache_via_http(admin_headers)
        r_all = requests.get(f"{API}/marketing/analytics/overview?window=all",
                              headers=admin_headers, timeout=15).json()
        assert r_all["sequences"]["completed"] >= cnt_recent + 1, \
            "the 60d-old completed enrolment must count in the 'all' window"

        # Review-request funnel — must include our reviewed row.
        _clear_cache_via_http(admin_headers)
        rr = requests.get(
            f"{API}/marketing/analytics/review-requests?window=7d",
            headers=admin_headers, timeout=15,
        ).json()
        assert rr["counts"]["reviewed"] >= 1
        assert rr["counts"]["sent"] >= 1
        assert rr["avg_rating"] is not None

        # Per-sequence funnel — 2 of 3 enrolments reached step 1 (fired).
        seq_id = ids["seq"]
        r_seq = requests.get(
            f"{API}/marketing/analytics/sequences/{seq_id}",
            headers=admin_headers, timeout=15,
        ).json()
        assert r_seq["counts"]["total"] == 4       # 3 recent + 1 old
        assert r_seq["counts"]["completed"] == 3   # 2 recent + 1 old
        assert r_seq["step_count"] == 1
        # step_reached: all 4 reach step 0; 3 pushed history so also 1.
        assert r_seq["funnel"][0]["reached"] == 4
        assert r_seq["funnel"][1]["reached"] == 3
        # rate_from_start_pct sanity — index 1 = 75.0%
        assert r_seq["funnel"][1]["rate_from_start_pct"] == 75.0
    finally:
        async def _clean():
            db = _db()
            await db.marketing_sequences.delete_one({"id": ids["seq"]})
            await db.marketing_drip_enrolments.delete_many(
                {"id": {"$in": [ids["e1"], ids["e2"], ids["e3"], ids["old"]]}},
            )
            await db.marketing_review_requests.delete_many(
                {"id": {"$in": [ids["rr1"], ids["rr2"]]}},
            )
        _run(_clean())


# ═══════════════════════════════════════════════════════════════════════
# Cache
# ═══════════════════════════════════════════════════════════════════════
def test_cache_hit_on_repeat(admin_headers):
    
    _clear_cache_via_http(admin_headers)
    r1 = requests.get(f"{API}/marketing/analytics/overview?window=7d",
                       headers=admin_headers, timeout=15).json()
    assert r1["_cache"] == "miss"
    r2 = requests.get(f"{API}/marketing/analytics/overview?window=7d",
                       headers=admin_headers, timeout=15).json()
    assert r2["_cache"] == "hit"


# ═══════════════════════════════════════════════════════════════════════
# Cross-tenant isolation on drilldown
# ═══════════════════════════════════════════════════════════════════════
def test_cross_tenant_isolation(admin_headers):
    async def _seed_foreign():
        db = _db()
        mine = await _tenant_of_admin()
        others = await db.tenants.find(
            {"id": {"$ne": mine}}, {"_id": 0, "id": 1},
        ).to_list(1)
        assert others
        sid = f"m7-cross-{uuid.uuid4().hex[:6]}"
        await db.marketing_sequences.insert_one({
            "id": sid, "tenant_id": others[0]["id"],
            "name": "foreign", "trigger_type": "manual",
            "trigger_config": {}, "steps": [], "active": True,
            "stop_on_reply": True, "stop_on_unsubscribe": True,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        })
        return sid
    sid = _run(_seed_foreign())
    try:
        assert requests.get(
            f"{API}/marketing/analytics/sequences/{sid}",
            headers=admin_headers, timeout=15,
        ).status_code == 404
    finally:
        async def _clean():
            await _db().marketing_sequences.delete_one({"id": sid})
        _run(_clean())


# ═══════════════════════════════════════════════════════════════════════
# AI-employee analytics actions
# ═══════════════════════════════════════════════════════════════════════
def test_ai_marketing_actions_dispatch(admin_headers):
    """Buddy / Vizzy / Dexter M7 handlers return non-empty markdown."""

    async def _go():
        from routers.ai_employees import (
            _buddy_marketing_weekly_recap,
            _vizzy_top_performing_sequences,
            _dexter_review_pipeline_health,
        )
        tid = await _tenant_of_admin()
        tenant = {"id": tid}
        b, _ = await _buddy_marketing_weekly_recap(tenant=tenant, params={})
        v, _ = await _vizzy_top_performing_sequences(tenant=tenant, params={})
        d, _ = await _dexter_review_pipeline_health(tenant=tenant, params={})
        assert "Marketing recap" in b
        assert "last 7 days" in b
        # v is either the empty-state message or the top-performing header
        assert ("Top-performing sequences" in v or "No sequences" in v)
        assert ("review request pipeline" in d.lower() or "no review requests" in d.lower())

    _run(_go())
