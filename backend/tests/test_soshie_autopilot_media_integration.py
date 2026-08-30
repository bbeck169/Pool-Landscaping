"""Phase S1.5 — end-to-end: pending IG draft past 24hr window,
hybrid media selected, published; and AI-fallback with low brand
score → blocked from autopilot.

These tests exercise ``_process_tenant`` end-to-end with the
adapter seam mocked at ``execute_publish_for_action``.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_sync = MongoClient(os.environ["MONGO_URL"])
_db = _sync[os.environ["DB_NAME"]]


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _iso_hours_ago(h: float) -> str:
    return (datetime.now(timezone.utc)
             - timedelta(hours=h)).isoformat()


def _iso_days_ago(d: float) -> str:
    return (datetime.now(timezone.utc)
             - timedelta(days=d)).isoformat()


class _FakeProvider:
    async def generate(self, **kw):
        return {"provider": "fake", "tool_used": "fake",
                "image_urls": ["data:image/png;base64,ZmFrZQ=="]}


def _seed(tid: str, credits: int = 500) -> None:
    _db.tenants.update_one(
        {"id": tid},
        {"$set": {"id": tid, "business_name": "Test Co",
                    "service_area": "Peoria, AZ",
                    "timezone": "America/Phoenix",
                    "ai_credits_balance": credits,
                    "ai_credits_plan": "essentials",
                    "ai_credits_monthly_grant": 1000}},
        upsert=True,
    )


def _enable(tid: str, platform: str,
                ppd=None, ppw=3) -> None:
    _db.soshie_autopilot_config.update_one(
        {"tenant_id": tid, "platform": platform},
        {"$set": {"tenant_id": tid, "platform": platform,
                    "enabled": True,
                    "posts_per_day": ppd, "posts_per_week": ppw,
                    "manual_only": False,
                    "timezone": "America/Phoenix",
                    "updated_at": _iso_hours_ago(0)}},
        upsert=True,
    )


def _mk_action(tid: str, platform: str,
                    service_type: str = "pool") -> str:
    aid = str(uuid.uuid4())
    _db.ai_employee_actions.insert_one({
        "id": aid, "tenant_id": tid,
        "employee_id": "TEST-e", "employee_key": "soshie",
        "conversation_id": None,
        "action": "soshie.draft_post",
        "params": {"platform": platform,
                     "service_type": service_type},
        "draft": {"text": "Post body", "title": "T",
                    "platform": platform},
        "title": "Draft", "summary": "T",
        "status": "pending", "requested_by": "TEST-u",
        "moderation_flags": [],
        "requires_human_approval": False,
        "media_url": None, "media_source": None, "brand_score": None,
        "created_at": _iso_hours_ago(48),
        "updated_at": _iso_hours_ago(48),
    })
    return aid


def _cleanup(tid: str) -> None:
    _db.ai_employee_actions.delete_many({"tenant_id": tid})
    _db.soshie_autopilot_config.delete_many({"tenant_id": tid})
    _db.social_publish_log.delete_many({"tenant_id": tid})
    _db.social_posts.delete_many({"tenant_id": tid})
    _db.idempotency_keys.delete_many({"tenant_id": tid})
    _db.scheduler_leases.delete_many({"tenant_id": tid})
    _db.tenants.delete_many({"id": tid})
    _db.customers.delete_many({"tenant_id": tid})
    _db.jobs.delete_many({"tenant_id": tid})
    _db.service_reports.delete_many({"tenant_id": tid})
    _db.brand_brain.delete_many({"tenant_id": tid})
    _db.soshie_ai_generated_media.delete_many({"tenant_id": tid})


# ═════════════════════════════════════════════════════════════════════
# 1 · Happy path — IG action + real job photo → published
# ═════════════════════════════════════════════════════════════════════
def test_ig_autopilot_with_job_photo_publishes(monkeypatch):
    from services.soshie import autopilot_scheduler as aps

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    _seed(tid, credits=500)
    _enable(tid, "instagram", ppw=3)
    aid = _mk_action(tid, "instagram", service_type="pool")

    # Seed a customer + job + service_report with a real photo.
    cid = f"TEST-cx-{uuid.uuid4().hex[:6]}"
    jid = f"TEST-j-{uuid.uuid4().hex[:6]}"
    rid = f"TEST-r-{uuid.uuid4().hex[:6]}"
    _db.customers.insert_one({
        "id": cid, "tenant_id": tid, "media_consent": True,
    })
    _db.jobs.insert_one({
        "id": jid, "tenant_id": tid, "customer_id": cid,
        "service_type": "pool", "job_type": "pool",
        "updated_at": _iso_days_ago(2), "photos": [],
    })
    _db.service_reports.insert_one({
        "id": rid, "tenant_id": tid, "job_id": jid,
        "submitted_at": _iso_days_ago(3),
        "photos": [{"id": "p1", "url": "https://ex.test/real.jpg",
                      "width": 1600, "height": 1200}],
    })

    captured: Dict[str, Any] = {}

    async def _fake_exec(**kw):
        captured.update(kw)
        return {"results": [{"platform": "instagram",
                              "status": "published",
                              "platform_post_id": "ig-1",
                              "url": "https://ig.test/1"}]}
    monkeypatch.setattr(
        "routers.soshie_publishing.execute_publish_for_action",
        _fake_exec,
    )

    try:
        _run(aps._process_tenant(tid))
        row = _db.ai_employee_actions.find_one({"id": aid})
        assert row["status"] == "published", row
        assert row["media_url"] == "https://ex.test/real.jpg"
        assert row["media_source"] == "job_photo"
        # brand_score MUST be absent — real photos skip AI scoring.
        assert row.get("brand_score") is None
    finally:
        _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# 2 · AI fallback with low brand score → blocked
# ═════════════════════════════════════════════════════════════════════
def test_ai_fallback_low_brand_score_blocks_autopilot(monkeypatch):
    from services.soshie import autopilot_scheduler as aps
    from services.soshie import ai_image_gen
    from services import media_provider as _mp

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    _seed(tid, credits=500)
    _enable(tid, "facebook", ppw=3)
    aid = _mk_action(tid, "facebook", service_type="pool")

    # NO job photos → media_selector returns none → AI fallback.
    # Mock provider + persister + brand-score.
    async def _fake_pick(tenant_id: str):
        return _FakeProvider()

    async def _fake_persist(url_or_datauri: str):
        return "img-fb", "/api/objects/generated/media/img-fb.png"

    async def _fake_score(**kw):
        return 0.30   # below 0.75

    monkeypatch.setattr(_mp, "pick_provider", _fake_pick)
    monkeypatch.setattr(_mp, "_persist_image", _fake_persist)
    monkeypatch.setattr(ai_image_gen, "score_brand_consistency",
                          _fake_score)
    dispatch_calls = []

    async def _fake_exec(**kw):
        dispatch_calls.append(kw)
        return {"results": []}
    monkeypatch.setattr(
        "routers.soshie_publishing.execute_publish_for_action",
        _fake_exec,
    )

    try:
        _run(aps._process_tenant(tid))
        assert dispatch_calls == [], \
            "low brand score must block dispatch"
        row = _db.ai_employee_actions.find_one({"id": aid})
        assert row["status"] == "pending", row
        assert row["requires_human_approval"] is True
        assert row["media_url"] == "/api/objects/generated/media/img-fb.png"
        assert row["media_source"] == "ai_generated"
        assert row["brand_score"] == 0.30
    finally:
        _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# 3 · AI fallback with high brand score → publishes with AI image
# ═════════════════════════════════════════════════════════════════════
def test_ai_fallback_high_brand_score_publishes(monkeypatch):
    from services.soshie import autopilot_scheduler as aps
    from services.soshie import ai_image_gen
    from services import media_provider as _mp

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    _seed(tid, credits=500)
    _enable(tid, "instagram", ppw=3)
    aid = _mk_action(tid, "instagram", service_type="pool")

    async def _fake_pick(tenant_id: str):
        return _FakeProvider()

    async def _fake_persist(url_or_datauri: str):
        return "img-ok", "/api/objects/generated/media/img-ok.png"

    async def _fake_score(**kw):
        return 0.85   # above threshold

    monkeypatch.setattr(_mp, "pick_provider", _fake_pick)
    monkeypatch.setattr(_mp, "_persist_image", _fake_persist)
    monkeypatch.setattr(ai_image_gen, "score_brand_consistency",
                          _fake_score)

    async def _fake_exec(**kw):
        return {"results": [{"platform": "instagram",
                              "status": "published",
                              "platform_post_id": "ig-hi",
                              "url": ""}]}
    monkeypatch.setattr(
        "routers.soshie_publishing.execute_publish_for_action",
        _fake_exec,
    )

    try:
        _run(aps._process_tenant(tid))
        row = _db.ai_employee_actions.find_one({"id": aid})
        assert row["status"] == "published", row
        assert row["media_source"] == "ai_generated"
        assert row["brand_score"] == 0.85
        assert row["media_url"].endswith("img-ok.png")
    finally:
        _cleanup(tid)
