"""Phase S1.5 · Feb-2026 — Soshie Autopilot scheduler tests.

Covers:
* Kill switch — disabled config never dispatches.
* 24hr window — actions younger than 24hr aren't picked up.
* Moderation-flag skip — flagged actions never auto-approved.
* requires_human_approval skip — low brand-score rows blocked.
* Credit throttle — below floor → status flips to
  ``deferred_no_credits``; on next tick with credits restored,
  the row is requeued to ``pending``.
* Reddit hard-block — even with enabled=True, Reddit skipped.
* Scheduler lease dedupe — two concurrent ``_process_tenant``
  calls only run the pipeline once.

All tests are in-process (no HTTP) and monkeypatch the
``execute_publish_for_action`` seam so no real adapter fires.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
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


def _iso_hours_ago(hours: int) -> str:
    return (datetime.now(timezone.utc)
             - timedelta(hours=hours)).isoformat()


def _mk_action(*, tenant_id: str, platform: str,
                    hours_old: float = 25.0,
                    moderation_flags=None,
                    requires_human_approval: bool = False,
                    text: str = "Autopilot test body",
                    ) -> str:
    aid = str(uuid.uuid4())
    _db.ai_employee_actions.insert_one({
        "id": aid,
        "tenant_id": tenant_id,
        "employee_id": "TEST-e",
        "employee_key": "soshie",
        "conversation_id": None,
        "action": ("soshie.publish_blog" if platform == "wordpress"
                     else "soshie.draft_post"),
        "params": {"platform": platform},
        "draft": {"text": text, "title": "T", "platform": platform},
        "title": "Blog draft",
        "summary": text[:200],
        "status": "pending",
        "requested_by": "TEST-u",
        "moderation_flags": moderation_flags or [],
        "requires_human_approval": requires_human_approval,
        "media_url": None, "media_source": None, "brand_score": None,
        "created_at": _iso_hours_ago(hours_old),
        "updated_at": _iso_hours_ago(hours_old),
    })
    return aid


def _enable_platform(tenant_id: str, platform: str,
                          posts_per_day=None, posts_per_week=None):
    _db.soshie_autopilot_config.update_one(
        {"tenant_id": tenant_id, "platform": platform},
        {"$set": {
            "tenant_id": tenant_id, "platform": platform,
            "enabled": True,
            "posts_per_day": posts_per_day,
            "posts_per_week": posts_per_week if posts_per_week is not None
                                    else (3 if not posts_per_day else None),
            "manual_only": False,
            "timezone": "America/Phoenix",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )


def _set_tenant_credits(tenant_id: str, balance: int) -> None:
    _db.tenants.update_one(
        {"id": tenant_id},
        {"$set": {"ai_credits_balance": int(balance),
                    "ai_credits_plan": "essentials",
                    "ai_credits_monthly_grant": 1000}},
        upsert=True,
    )


def _cleanup(tenant_id: str) -> None:
    _db.ai_employee_actions.delete_many({"tenant_id": tenant_id})
    _db.soshie_autopilot_config.delete_many({"tenant_id": tenant_id})
    _db.social_publish_log.delete_many({"tenant_id": tenant_id})
    _db.social_posts.delete_many({"tenant_id": tenant_id})
    _db.idempotency_keys.delete_many({"tenant_id": tenant_id})
    _db.scheduler_leases.delete_many({"tenant_id": tenant_id})
    _db.tenants.delete_many({"id": tenant_id})
    _db.seo_articles.delete_many({"tenant_id": tenant_id})


# ═════════════════════════════════════════════════════════════════════
# 1 · Kill switch — enabled=False → no dispatch
# ═════════════════════════════════════════════════════════════════════
def test_kill_switch_disabled_platform_never_dispatches(monkeypatch):
    from services.soshie import autopilot_scheduler as aps

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    _set_tenant_credits(tid, 500)
    aid = _mk_action(tenant_id=tid, platform="wordpress", hours_old=48)
    # Autopilot config for WP explicitly DISABLED.
    _db.soshie_autopilot_config.update_one(
        {"tenant_id": tid, "platform": "wordpress"},
        {"$set": {"tenant_id": tid, "platform": "wordpress",
                    "enabled": False,
                    "posts_per_week": 3, "timezone": "America/Phoenix",
                    "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    calls = []

    async def _fake_exec(**kw):
        calls.append(kw)
        return {"results": [{"platform": "wordpress",
                              "status": "published",
                              "platform_post_id": "1", "url": ""}]}
    monkeypatch.setattr(
        "routers.soshie_publishing.execute_publish_for_action",
        _fake_exec,
    )
    try:
        summary = _run(aps._process_tenant(tid))
        assert calls == [], f"disabled platform should not dispatch: {calls}"
        assert summary["tenant"] == tid
        row = _db.ai_employee_actions.find_one({"id": aid})
        assert row["status"] == "pending"
    finally:
        _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# 2 · 24hr window — younger actions ignored
# ═════════════════════════════════════════════════════════════════════
def test_actions_younger_than_24hr_not_dispatched(monkeypatch):
    from services.soshie import autopilot_scheduler as aps

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    _set_tenant_credits(tid, 500)
    _enable_platform(tid, "wordpress")
    # 23hr old — must NOT dispatch this tick.
    aid = _mk_action(tenant_id=tid, platform="wordpress", hours_old=23)
    calls = []

    async def _fake_exec(**kw):
        calls.append(kw)
        return {"results": []}
    monkeypatch.setattr(
        "routers.soshie_publishing.execute_publish_for_action",
        _fake_exec,
    )
    try:
        _run(aps._process_tenant(tid))
        assert calls == [], "24hr window not enforced"
        row = _db.ai_employee_actions.find_one({"id": aid})
        assert row["status"] == "pending"
    finally:
        _cleanup(tid)


def test_actions_older_than_24hr_dispatch(monkeypatch):
    from services.soshie import autopilot_scheduler as aps

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    _set_tenant_credits(tid, 500)
    _enable_platform(tid, "wordpress")
    aid = _mk_action(tenant_id=tid, platform="wordpress", hours_old=25)

    async def _fake_exec(**kw):
        return {"results": [{"platform": "wordpress",
                              "status": "draft",
                              "platform_post_id": "auto-1",
                              "url": "https://x.test/1"}]}
    monkeypatch.setattr(
        "routers.soshie_publishing.execute_publish_for_action",
        _fake_exec,
    )
    try:
        _run(aps._process_tenant(tid))
        row = _db.ai_employee_actions.find_one({"id": aid})
        assert row["status"] == "published", row
        assert row["result"]["kind"] == "soshie_autopilot_published"
    finally:
        _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# 3 · Moderation flag skip
# ═════════════════════════════════════════════════════════════════════
def test_moderation_flagged_action_skipped(monkeypatch):
    from services.soshie import autopilot_scheduler as aps

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    _set_tenant_credits(tid, 500)
    _enable_platform(tid, "wordpress")
    aid = _mk_action(
        tenant_id=tid, platform="wordpress", hours_old=48,
        moderation_flags=[{"type": "phrase", "match": "guaranteed",
                              "source": "banned_phrases"}],
    )
    calls = []

    async def _fake_exec(**kw):
        calls.append(kw)
        return {"results": []}
    monkeypatch.setattr(
        "routers.soshie_publishing.execute_publish_for_action",
        _fake_exec,
    )
    try:
        _run(aps._process_tenant(tid))
        assert calls == [], "flagged action must not autopilot"
        row = _db.ai_employee_actions.find_one({"id": aid})
        assert row["status"] == "pending"
    finally:
        _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# 4 · requires_human_approval skip
# ═════════════════════════════════════════════════════════════════════
def test_requires_human_approval_skipped(monkeypatch):
    from services.soshie import autopilot_scheduler as aps

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    _set_tenant_credits(tid, 500)
    _enable_platform(tid, "wordpress")
    aid = _mk_action(
        tenant_id=tid, platform="wordpress", hours_old=48,
        requires_human_approval=True,
    )
    calls = []

    async def _fake_exec(**kw):
        calls.append(kw)
        return {"results": []}
    monkeypatch.setattr(
        "routers.soshie_publishing.execute_publish_for_action",
        _fake_exec,
    )
    try:
        _run(aps._process_tenant(tid))
        assert calls == []
        row = _db.ai_employee_actions.find_one({"id": aid})
        assert row["status"] == "pending"
    finally:
        _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# 5 · Credit throttle → deferred_no_credits, then requeue
# ═════════════════════════════════════════════════════════════════════
def test_credit_throttle_defers_then_requeues(monkeypatch):
    from services.soshie import autopilot_scheduler as aps

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    _set_tenant_credits(tid, 2)   # below CREDIT_FLOOR=5
    _enable_platform(tid, "wordpress")
    aid = _mk_action(tenant_id=tid, platform="wordpress", hours_old=48)
    calls = []

    async def _fake_exec(**kw):
        calls.append(kw)
        return {"results": []}
    monkeypatch.setattr(
        "routers.soshie_publishing.execute_publish_for_action",
        _fake_exec,
    )
    try:
        _run(aps._process_tenant(tid))
        assert calls == []
        row = _db.ai_employee_actions.find_one({"id": aid})
        assert row["status"] == "deferred_no_credits", row
        # Top up credits, run again → row requeued to pending, then dispatched.
        _set_tenant_credits(tid, 500)

        async def _fake_ok(**kw):
            return {"results": [{"platform": "wordpress",
                                  "status": "draft",
                                  "platform_post_id": "auto-2",
                                  "url": ""}]}
        monkeypatch.setattr(
            "routers.soshie_publishing.execute_publish_for_action",
            _fake_ok,
        )
        _run(aps._process_tenant(tid))
        row2 = _db.ai_employee_actions.find_one({"id": aid})
        assert row2["status"] == "published", row2
    finally:
        _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# 6 · Reddit hard-block
# ═════════════════════════════════════════════════════════════════════
def test_reddit_hardblock_never_dispatches(monkeypatch):
    from services.soshie import autopilot_scheduler as aps

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    _set_tenant_credits(tid, 500)
    # Force Reddit config to enabled=True — the scheduler must still skip.
    _db.soshie_autopilot_config.update_one(
        {"tenant_id": tid, "platform": "reddit"},
        {"$set": {"tenant_id": tid, "platform": "reddit",
                    "enabled": True, "manual_only": True,
                    "posts_per_week": 3,
                    "timezone": "America/Phoenix",
                    "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    aid = _mk_action(tenant_id=tid, platform="reddit", hours_old=48)
    calls = []

    async def _fake_exec(**kw):
        calls.append(kw)
        return {"results": []}
    monkeypatch.setattr(
        "routers.soshie_publishing.execute_publish_for_action",
        _fake_exec,
    )
    try:
        _run(aps._process_tenant(tid))
        assert calls == [], "reddit MUST NOT autopilot"
        row = _db.ai_employee_actions.find_one({"id": aid})
        assert row["status"] == "pending"
    finally:
        _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# 7 · Scheduler lease dedupe — concurrent ticks only run once
# ═════════════════════════════════════════════════════════════════════
def test_scheduler_lease_dedupes_concurrent_ticks(monkeypatch):
    from services.soshie import autopilot_scheduler as aps

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    _set_tenant_credits(tid, 500)
    _enable_platform(tid, "wordpress")
    aid = _mk_action(tenant_id=tid, platform="wordpress", hours_old=48)
    call_count = {"n": 0}

    async def _fake_exec(**kw):
        call_count["n"] += 1
        return {"results": [{"platform": "wordpress",
                              "status": "draft",
                              "platform_post_id": f"c{call_count['n']}",
                              "url": ""}]}
    monkeypatch.setattr(
        "routers.soshie_publishing.execute_publish_for_action",
        _fake_exec,
    )
    try:
        async def _both():
            return await asyncio.gather(
                aps._process_tenant(tid),
                aps._process_tenant(tid),
            )
        results = _run(_both())
        # One winner + one lease-skip.
        outcomes = [r.get("skipped") for r in results]
        assert outcomes.count("lease_lost") >= 1, results
        assert call_count["n"] <= 1, \
            "action must not double-dispatch across concurrent ticks"
    finally:
        _cleanup(tid)
