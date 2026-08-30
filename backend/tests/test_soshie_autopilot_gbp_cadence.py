"""Phase S1.5 · AM1 — GBP cadence: 1 per day.

Covers:
* At most 1 GBP dispatch per calendar day (tenant TZ).
* Two eligible GBP drafts on the same day → only the first fires;
  the second stays pending for the next day slot.
* No-backfill on credit pause — day counter doesn't advance while
  credits are exhausted.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def _iso_hours_ago(hours: float) -> str:
    return (datetime.now(timezone.utc)
             - timedelta(hours=hours)).isoformat()


def _mk_gbp_action(tid: str) -> str:
    aid = str(uuid.uuid4())
    _db.ai_employee_actions.insert_one({
        "id": aid, "tenant_id": tid,
        "employee_id": "TEST-e", "employee_key": "soshie",
        "conversation_id": None,
        "action": "soshie.draft_post",
        "params": {"platform": "gbp", "service_type": "pool"},
        "draft": {"text": "GBP post body", "title": "T",
                    "platform": "gbp"},
        "title": "GBP draft", "summary": "GBP",
        "status": "pending", "requested_by": "TEST-u",
        "moderation_flags": [],
        "requires_human_approval": False,
        # Pre-attach a job_photo so we skip AI + brand-score in tests.
        "media_url": "https://example.test/pic.jpg",
        "media_source": "job_photo",
        "brand_score": None,
        "created_at": _iso_hours_ago(48),
        "updated_at": _iso_hours_ago(48),
    })
    return aid


def _seed(tid: str, credits: int = 500) -> None:
    _db.tenants.update_one(
        {"id": tid},
        {"$set": {"id": tid, "ai_credits_balance": credits,
                    "ai_credits_plan": "essentials",
                    "ai_credits_monthly_grant": 1000,
                    "timezone": "America/Phoenix"}},
        upsert=True,
    )
    _db.soshie_autopilot_config.update_one(
        {"tenant_id": tid, "platform": "gbp"},
        {"$set": {"tenant_id": tid, "platform": "gbp",
                    "enabled": True,
                    "posts_per_day": 1, "posts_per_week": None,
                    "manual_only": False,
                    "timezone": "America/Phoenix",
                    "updated_at": _iso_hours_ago(0)}},
        upsert=True,
    )


def _cleanup(tid: str) -> None:
    _db.ai_employee_actions.delete_many({"tenant_id": tid})
    _db.soshie_autopilot_config.delete_many({"tenant_id": tid})
    _db.social_publish_log.delete_many({"tenant_id": tid})
    _db.social_posts.delete_many({"tenant_id": tid})
    _db.idempotency_keys.delete_many({"tenant_id": tid})
    _db.scheduler_leases.delete_many({"tenant_id": tid})
    _db.tenants.delete_many({"id": tid})


# ═════════════════════════════════════════════════════════════════════
# 1 · At most 1 GBP dispatch per calendar day
# ═════════════════════════════════════════════════════════════════════
def test_gbp_at_most_one_per_day(monkeypatch):
    from services.soshie import autopilot_scheduler as aps

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    _seed(tid, credits=500)
    aid1 = _mk_gbp_action(tid)
    aid2 = _mk_gbp_action(tid)
    call_count = {"n": 0}

    async def _fake_exec(**kw):
        call_count["n"] += 1
        # Simulate ``social_publish_log`` write that the real executor
        # would have done (adapter path is mocked so we do it here).
        _db.social_publish_log.insert_one({
            "tenant_id": kw["tenant_id"], "platform": "gbp",
            "action_id": kw["action_id"],
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
        })
        return {"results": [{"platform": "gbp",
                              "status": "published",
                              "platform_post_id": f"gbp-{call_count['n']}",
                              "url": ""}]}
    monkeypatch.setattr(
        "routers.soshie_publishing.execute_publish_for_action",
        _fake_exec,
    )
    try:
        # Tick 1 → first dispatch; second action skipped by cadence.
        _run(aps._process_tenant(tid))
        assert call_count["n"] == 1
        row1 = _db.ai_employee_actions.find_one({"id": aid1})
        row2 = _db.ai_employee_actions.find_one({"id": aid2})
        published = [r for r in (row1, row2) if r["status"] == "published"]
        pending = [r for r in (row1, row2) if r["status"] == "pending"]
        assert len(published) == 1, (row1, row2)
        assert len(pending) == 1, (row1, row2)
        # Tick 2 same-day → cadence still full, no new dispatch.
        _run(aps._process_tenant(tid))
        assert call_count["n"] == 1, "cadence must not re-fire same day"
    finally:
        _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# 2 · No-backfill on credit pause
# ═════════════════════════════════════════════════════════════════════
def test_gbp_no_backfill_on_credit_pause(monkeypatch):
    """Credit-throttled today → tomorrow's slot fires exactly ONCE
    even if 3 pending actions accumulated overnight."""
    from services.soshie import autopilot_scheduler as aps

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    _seed(tid, credits=0)   # zero credits → throttle
    aid1 = _mk_gbp_action(tid)
    aid2 = _mk_gbp_action(tid)
    aid3 = _mk_gbp_action(tid)
    calls = {"n": 0}

    async def _fake_exec(**kw):
        calls["n"] += 1
        _db.social_publish_log.insert_one({
            "tenant_id": kw["tenant_id"], "platform": "gbp",
            "action_id": kw["action_id"],
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
        })
        return {"results": [{"platform": "gbp",
                              "status": "published",
                              "platform_post_id": f"c{calls['n']}",
                              "url": ""}]}
    monkeypatch.setattr(
        "routers.soshie_publishing.execute_publish_for_action",
        _fake_exec,
    )
    try:
        # Tick 1 — credits=0 → all 3 flip to deferred_no_credits.
        _run(aps._process_tenant(tid))
        assert calls["n"] == 0
        deferred = _db.ai_employee_actions.count_documents(
            {"tenant_id": tid, "status": "deferred_no_credits"})
        assert deferred == 3
        # Top up credits, next tick — 3 rows requeue to pending, but
        # cadence still allows only ONE dispatch (no backfill).
        _db.tenants.update_one(
            {"id": tid}, {"$set": {"ai_credits_balance": 500}},
        )
        _run(aps._process_tenant(tid))
        assert calls["n"] == 1, \
            f"credit-pause backfill triggered — expected 1 dispatch, got {calls['n']}"
        published = _db.ai_employee_actions.count_documents(
            {"tenant_id": tid, "status": "published"})
        assert published == 1
        pending = _db.ai_employee_actions.count_documents(
            {"tenant_id": tid, "status": "pending"})
        assert pending == 2, \
            f"remaining rows must stay pending for future days, got {pending}"
    finally:
        _cleanup(tid)
