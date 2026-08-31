"""Phase F3 · Feb-2026 — Soshie moderation queue tests.

RBAC + audit + status transitions for the queue endpoints.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


async def _seed(db):
    tid = "TEST_F3Q_" + uuid.uuid4().hex[:8]
    await db.tenants.insert_one({"id": tid, "name": "F3Q", "slug": tid.lower()})
    admin = {"id": "admin-" + uuid.uuid4().hex[:6], "role": "admin",
             "tenant_id": tid, "email": "admin@example.com"}
    tech = {"id": "tech-" + uuid.uuid4().hex[:6], "role": "technician",
            "tenant_id": tid, "email": "tech@example.com"}
    return tid, admin, tech


async def _cleanup(db, tid: str) -> None:
    await db.tenants.delete_many({"id": tid})
    await db.ai_employee_actions.delete_many({"tenant_id": tid})
    await db.audit_events.delete_many(
        {"tenant_id": tid,
         "event_type": {"$in": ["soshie_moderation_approve",
                                    "soshie_moderation_reject"]}},
    )


async def _seed_action(db, tid, *, status="awaiting_review",
                          text="probe", platform="facebook"):
    aid = "p_" + uuid.uuid4().hex[:8]
    await db.ai_employee_actions.insert_one({
        "id": aid, "tenant_id": tid,
        "status": status, "platform": platform,
        "scheduled_at": "2026-02-06T09:00:00+00:00",
        "created_at": "2026-02-05T09:00:00+00:00",
        "draft": {"text": text},
        "moderation_decision": "flag" if status == "awaiting_review"
                                     else status,
        "moderation_reasons": ["aggressive_tone"],
        "moderation_risk_level": "medium",
    })
    return aid


# ─── list_moderation_queue ────────────────────────────────────────────
def test_f3q_list_awaiting_review():
    from routers.soshie_moderation import list_moderation_queue

    async def _go(db):
        tid, admin, _tech = await _seed(db)
        await _cleanup(db, tid)
        aid1 = await _seed_action(db, tid, status="awaiting_review")
        aid2 = await _seed_action(db, tid, status="awaiting_review",
                                        text="second one")
        _blocked = await _seed_action(db, tid, status="blocked",
                                          text="blocked one")
        try:
            res = await list_moderation_queue(
                status="awaiting_review", user=admin, tenant={"id": tid},
            )
            ids = {p["id"] for p in res["posts"]}
            assert aid1 in ids and aid2 in ids
            assert res["count"] == 2
        finally:
            await _cleanup(db, tid)

    run_test(_go)


def test_f3q_list_blocked_channel():
    from routers.soshie_moderation import list_moderation_queue

    async def _go(db):
        tid, admin, _tech = await _seed(db)
        await _cleanup(db, tid)
        await _seed_action(db, tid, status="blocked", text="blocked X")
        try:
            res = await list_moderation_queue(
                status="blocked", user=admin, tenant={"id": tid},
            )
            assert res["count"] == 1
            assert res["status"] == "blocked"
        finally:
            await _cleanup(db, tid)

    run_test(_go)


# ─── approve — moves to pending + writes audit ─────────────────────────
def test_f3q_approve_writes_audit_and_pending():
    from routers.soshie_moderation import approve_post

    async def _go(db):
        tid, admin, _tech = await _seed(db)
        await _cleanup(db, tid)
        aid = await _seed_action(db, tid, status="awaiting_review")
        try:
            res = await approve_post(post_id=aid, user=admin,
                                       tenant={"id": tid})
            assert res["ok"] is True
            row = await db.ai_employee_actions.find_one(
                {"id": aid}, {"_id": 0},
            )
            assert row["status"] == "pending"
            assert row["moderation_override"] is True
            audits = await db.audit_events.find(
                {"tenant_id": tid, "post_id": aid,
                 "event_type": "soshie_moderation_approve"},
            ).to_list(5)
            assert len(audits) == 1
        finally:
            await _cleanup(db, tid)

    run_test(_go)


# ─── reject — writes audit + marks post rejected ───────────────────────
def test_f3q_reject_writes_audit_and_rejected():
    from routers.soshie_moderation import reject_post, RejectBody

    async def _go(db):
        tid, admin, _tech = await _seed(db)
        await _cleanup(db, tid)
        aid = await _seed_action(db, tid, status="awaiting_review")
        try:
            res = await reject_post(post_id=aid,
                                       body=RejectBody(reason="off-brand"),
                                       user=admin, tenant={"id": tid})
            assert res["new_status"] == "rejected"
            row = await db.ai_employee_actions.find_one(
                {"id": aid}, {"_id": 0},
            )
            assert row["status"] == "rejected"
            assert row["moderation_reject_reason"] == "off-brand"
            audits = await db.audit_events.find(
                {"tenant_id": tid, "post_id": aid,
                 "event_type": "soshie_moderation_reject"},
            ).to_list(5)
            assert len(audits) == 1
        finally:
            await _cleanup(db, tid)

    run_test(_go)


# ─── approve on non-queue status → 409 ────────────────────────────────
def test_f3q_approve_on_published_is_409():
    from routers.soshie_moderation import approve_post

    async def _go(db):
        tid, admin, _tech = await _seed(db)
        await _cleanup(db, tid)
        aid = await _seed_action(db, tid, status="published")
        try:
            try:
                await approve_post(post_id=aid, user=admin,
                                     tenant={"id": tid})
                raise AssertionError("expected 409")
            except HTTPException as e:
                assert e.status_code == 409
        finally:
            await _cleanup(db, tid)

    run_test(_go)


# ─── tenant isolation on the queue ────────────────────────────────────
def test_f3q_tenant_isolation():
    from routers.soshie_moderation import list_moderation_queue

    async def _go(db):
        tid_a, admin_a, _t = await _seed(db)
        tid_b, admin_b, _t2 = await _seed(db)
        await _cleanup(db, tid_a); await _cleanup(db, tid_b)
        await _seed_action(db, tid_a, status="awaiting_review",
                              text="A only")
        try:
            res_b = await list_moderation_queue(
                status="awaiting_review", user=admin_b,
                tenant={"id": tid_b},
            )
            assert res_b["count"] == 0
        finally:
            await _cleanup(db, tid_a); await _cleanup(db, tid_b)

    run_test(_go)
