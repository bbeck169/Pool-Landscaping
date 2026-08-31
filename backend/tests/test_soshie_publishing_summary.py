"""Phase F3 · Feb-2026 — /soshie/publishing/today-summary tests."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from tests._f7_loop_fixture import run_test


def _now_iso_plus(minutes: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


async def _seed(db):
    tid = "TEST_F3S_" + uuid.uuid4().hex[:8]
    await db.tenants.insert_one({"id": tid, "name": "F3S",
                                   "slug": tid.lower()})
    admin = {"id": "a", "role": "admin", "tenant_id": tid,
             "email": "a@example.com"}
    return tid, admin


async def _cleanup(db, tid):
    await db.tenants.delete_many({"id": tid})
    await db.ai_employee_actions.delete_many({"tenant_id": tid})


async def _seed_actions_across_statuses(db, tid):
    # 2 pending, 1 published (today), 1 awaiting_review, 1 blocked,
    # 1 failed (today), 1 rejected.
    now = _now_iso_plus(0)
    later = _now_iso_plus(60)
    later_later = _now_iso_plus(120)
    await db.ai_employee_actions.insert_many([
        {"id": "p1", "tenant_id": tid, "status": "pending",
         "platform": "facebook", "scheduled_at": later,
         "draft": {"text": "Hello Peoria"}},
        {"id": "p2", "tenant_id": tid, "status": "scheduled",
         "platform": "instagram", "scheduled_at": later_later,
         "draft": {"text": "Hello IG"}},
        {"id": "p3", "tenant_id": tid, "status": "published",
         "platform": "gbp", "executed_at": now,
         "draft": {"text": "shipped"}},
        {"id": "p4", "tenant_id": tid, "status": "awaiting_review",
         "platform": "tiktok", "scheduled_at": later,
         "draft": {"text": "review me"}},
        {"id": "p5", "tenant_id": tid, "status": "blocked",
         "platform": "facebook", "scheduled_at": later,
         "draft": {"text": "no way"}},
        {"id": "p6", "tenant_id": tid, "status": "failed",
         "platform": "facebook", "executed_at": now,
         "draft": {"text": "network glitch"}},
        {"id": "p7", "tenant_id": tid, "status": "rejected",
         "platform": "instagram", "scheduled_at": later,
         "draft": {"text": "no thanks"}},
    ])


def test_f3s_counts_and_next_up():
    from routers.soshie_moderation import publishing_today_summary

    async def _go(db):
        tid, admin = await _seed(db)
        await _cleanup(db, tid)
        await _seed_actions_across_statuses(db, tid)
        try:
            res = await publishing_today_summary(user=admin,
                                                    tenant={"id": tid})
            assert res["scheduled"] == 2, res
            assert res["published"] == 1, res
            assert res["flagged"] == 1, res
            assert res["blocked"] == 1, res
            assert res["failed"] == 1, res
            assert len(res["next_up"]) <= 3
            # next_up must include the earliest scheduled_at.
            platforms = [n["platform"] for n in res["next_up"]]
            assert "facebook" in platforms or "instagram" in platforms
        finally:
            await _cleanup(db, tid)

    run_test(_go)


def test_f3s_tenant_isolation():
    from routers.soshie_moderation import publishing_today_summary

    async def _go(db):
        tid_a, admin_a = await _seed(db)
        tid_b, admin_b = await _seed(db)
        await _cleanup(db, tid_a); await _cleanup(db, tid_b)
        await _seed_actions_across_statuses(db, tid_a)
        try:
            res_b = await publishing_today_summary(
                user=admin_b, tenant={"id": tid_b},
            )
            assert res_b["scheduled"] == 0
            assert res_b["published"] == 0
            assert res_b["flagged"] == 0
            assert res_b["blocked"] == 0
            assert res_b["failed"] == 0
            assert res_b["next_up"] == []
        finally:
            await _cleanup(db, tid_a); await _cleanup(db, tid_b)

    run_test(_go)
