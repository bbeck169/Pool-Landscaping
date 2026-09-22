"""Phase P23 · Feb-2026 — Technician soft-delete endpoint tests.

Covers all 8 acceptance points from the P23 spec for
``DELETE /api/technicians/{id}``:

  1. Zero active jobs → 200 + soft-delete stamp + audit row.
  2. N > 0 active jobs → 409 with ``TECHNICIAN_HAS_ACTIVE_JOBS`` +
     ``assigned_job_count``. Doc UNCHANGED.
  3. ``?force=true&reassign_to=<valid>`` → 200, jobs moved, N job
     audit rows + 1 tech audit row, tech soft-deleted.
  4. ``?force=true`` without ``reassign_to`` → 400.
  5. ``?force=true&reassign_to=<self>`` → 400.
  6. ``?force=true&reassign_to=<cross-tenant-id>`` → 400.
  7. Non-admin caller → 403.
  8. Deleted / completed / cancelled jobs do NOT count toward the
     block threshold.

Uses the direct function-call harness (mirrors ``test_p22_*`` +
``test_jobs_crew_filter.py``) so we can inject deterministic seeds
without a live uvicorn.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


TAG = "TEST_P23_DEL_"


async def _seed_tenant(db):
    tenant = await db.tenants.find_one(
        {"slug": "aquaterra"}, {"_id": 0, "id": 1},
    )
    return tenant["id"]


async def _cleanup(db, tid):
    await db.technicians.delete_many({"id": {"$regex": f"^{TAG}"}})
    await db.jobs.delete_many({"id": {"$regex": f"^{TAG}"}})
    # Purge audit rows we produced.
    await db.deletion_audit.delete_many({
        "resource_id": {"$regex": f"^{TAG}"},
    })


async def _seed_tech(db, tid, tech_id):
    await db.technicians.insert_one({
        "id": tech_id, "tenant_id": tid,
        "name": f"P23-{tech_id[-4:]}",
        "department": "pool_tech",
        "email": f"{tech_id[-4:]}@p23.test",
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


async def _seed_active_job(db, tid, tech_id, jid=None, status="scheduled"):
    _jid = jid or f"{TAG}JOB_{uuid.uuid4().hex[:8]}"
    await db.jobs.insert_one({
        "id": _jid, "tenant_id": tid,
        "technician_id": tech_id,
        "status": status,
        "customer_id": "p23-fake",
        "scheduled_date": "2026-06-01",
    })
    return _jid


def _admin(tid):
    return {"id": "p23-admin", "role": "admin",
            "tenant_id": tid, "email": "admin@p23.test"}


def _call(**overrides):
    """Direct-call harness — matches the shape used by other
    ``list_jobs`` / crew-filter tests."""
    from routers.technicians import soft_delete_technician
    kwargs = dict(
        force=False, reassign_to=None,
    )
    kwargs.update(overrides)
    return soft_delete_technician(**kwargs)


# ── 1) Zero active jobs → 200 + soft-delete + audit ────────────────
def test_p23_soft_delete_no_active_jobs_returns_200_stamps_flags():
    async def _go(db):
        tid = await _seed_tenant(db)
        await _cleanup(db, tid)
        tech_id = f"{TAG}TECH_A_{uuid.uuid4().hex[:6]}"
        await _seed_tech(db, tid, tech_id)
        try:
            res = await _call(tid=tech_id, user=_admin(tid), tenant={"id": tid})
            assert res["ok"] is True
            assert res["id"] == tech_id
            assert res["deleted_at"]
            assert res["active_jobs_reassigned"] == 0

            after = await db.technicians.find_one({"id": tech_id})
            assert after["active"] is False
            assert after["deleted_at"]
            assert after["deleted_by"] == "p23-admin"

            audit = await db.deletion_audit.find_one({
                "resource_type": "technician", "resource_id": tech_id,
            })
            assert audit is not None
            assert audit["deletion_reason"] == "technician_soft_deleted"
        finally:
            await _cleanup(db, tid)
    run_test(_go)


# ── 2) N > 0 active jobs → 409 with count, doc unchanged ──────────
def test_p23_soft_delete_active_jobs_returns_409_doc_unchanged():
    async def _go(db):
        tid = await _seed_tenant(db)
        await _cleanup(db, tid)
        tech_id = f"{TAG}TECH_B_{uuid.uuid4().hex[:6]}"
        await _seed_tech(db, tid, tech_id)
        for _ in range(5):
            await _seed_active_job(db, tid, tech_id)
        try:
            try:
                await _call(tid=tech_id, user=_admin(tid), tenant={"id": tid})
                assert False, "expected 409 from active-job block"
            except HTTPException as e:
                assert e.status_code == 409
                detail = e.detail
                assert detail["code"] == "TECHNICIAN_HAS_ACTIVE_JOBS"
                assert detail["assigned_job_count"] == 5
                assert "5 active jobs" in detail["message"]

            # Doc UNCHANGED — still active, no deleted_at stamp.
            after = await db.technicians.find_one({"id": tech_id})
            assert after["active"] is True
            assert after.get("deleted_at") is None
        finally:
            await _cleanup(db, tid)
    run_test(_go)


# ── 3) force=true+reassign_to=<valid> → 200, jobs moved, audits ────
def test_p23_force_reassign_moves_jobs_and_writes_full_audit_trail():
    async def _go(db):
        tid = await _seed_tenant(db)
        await _cleanup(db, tid)
        tech_a = f"{TAG}TECH_C_{uuid.uuid4().hex[:6]}"
        tech_b = f"{TAG}TECH_D_{uuid.uuid4().hex[:6]}"
        await _seed_tech(db, tid, tech_a)
        await _seed_tech(db, tid, tech_b)
        seeded_jids = []
        for _ in range(5):
            seeded_jids.append(await _seed_active_job(db, tid, tech_a))
        try:
            res = await _call(
                tid=tech_a, user=_admin(tid), tenant={"id": tid},
                force=True, reassign_to=tech_b,
            )
            assert res["ok"] is True
            assert res["active_jobs_reassigned"] == 5
            assert res["reassigned_to"] == tech_b
            bulk_op_id = res["bulk_op_id"]
            assert bulk_op_id

            # Jobs moved.
            for jid in seeded_jids:
                job = await db.jobs.find_one({"id": jid})
                assert job["technician_id"] == tech_b
                assert job["reassigned_from"] == tech_a
                assert job["reassigned_reason"] == "technician_deleted"
                assert job["reassigned_at"]

            # 5 job-audit rows + 1 tech-audit row = 6, all sharing the
            # same ``bulk_op_id``.
            audits = await db.deletion_audit.find({
                "bulk_op_id": bulk_op_id,
            }).to_list(50)
            types = sorted(a["resource_type"] for a in audits)
            assert types == ["job"] * 5 + ["technician"], (
                f"audit shape mismatch: {types}"
            )

            # Tech is soft-deleted.
            after = await db.technicians.find_one({"id": tech_a})
            assert after["active"] is False
            assert after["deleted_at"]
        finally:
            await _cleanup(db, tid)
    run_test(_go)


# ── 4) force=true missing reassign_to → 400 ────────────────────────
def test_p23_force_without_reassign_to_returns_400():
    async def _go(db):
        tid = await _seed_tenant(db)
        await _cleanup(db, tid)
        tech_id = f"{TAG}TECH_E_{uuid.uuid4().hex[:6]}"
        await _seed_tech(db, tid, tech_id)
        await _seed_active_job(db, tid, tech_id)
        try:
            try:
                await _call(
                    tid=tech_id, user=_admin(tid), tenant={"id": tid},
                    force=True,   # no reassign_to
                )
                assert False, "expected 400"
            except HTTPException as e:
                assert e.status_code == 400
                assert "reassign_to" in str(e.detail).lower()
        finally:
            await _cleanup(db, tid)
    run_test(_go)


# ── 5) reassign_to == self → 400 ───────────────────────────────────
def test_p23_reassign_to_self_returns_400():
    async def _go(db):
        tid = await _seed_tenant(db)
        await _cleanup(db, tid)
        tech_id = f"{TAG}TECH_F_{uuid.uuid4().hex[:6]}"
        await _seed_tech(db, tid, tech_id)
        await _seed_active_job(db, tid, tech_id)
        try:
            try:
                await _call(
                    tid=tech_id, user=_admin(tid), tenant={"id": tid},
                    force=True, reassign_to=tech_id,
                )
                assert False, "expected 400"
            except HTTPException as e:
                assert e.status_code == 400
                assert "cannot equal" in str(e.detail).lower()
        finally:
            await _cleanup(db, tid)
    run_test(_go)


# ── 6) reassign_to lives in a different tenant → 400 ───────────────
def test_p23_reassign_to_cross_tenant_returns_400():
    async def _go(db):
        tid = await _seed_tenant(db)
        # Fake other tenant id — we just need any string that DOESN'T
        # match ``tid`` because our lookup is tenant-scoped.
        other_tid = f"{TAG}OTHER_TENANT_{uuid.uuid4().hex[:6]}"
        await _cleanup(db, tid)
        tech_a = f"{TAG}TECH_G_{uuid.uuid4().hex[:6]}"
        tech_b = f"{TAG}TECH_H_{uuid.uuid4().hex[:6]}"
        await _seed_tech(db, tid, tech_a)
        # Insert tech_b under the OTHER tenant.
        await db.technicians.insert_one({
            "id": tech_b, "tenant_id": other_tid,
            "name": "Foreign Tech", "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        await _seed_active_job(db, tid, tech_a)
        try:
            try:
                await _call(
                    tid=tech_a, user=_admin(tid), tenant={"id": tid},
                    force=True, reassign_to=tech_b,
                )
                assert False, "expected 400"
            except HTTPException as e:
                assert e.status_code == 400
                assert "not found" in str(e.detail).lower()
        finally:
            await db.technicians.delete_one({"id": tech_b})
            await _cleanup(db, tid)
    run_test(_go)


# ── 7) Non-admin caller → 403 ──────────────────────────────────────
def test_p23_non_admin_caller_returns_403():
    async def _go(db):
        tid = await _seed_tenant(db)
        await _cleanup(db, tid)
        tech_id = f"{TAG}TECH_I_{uuid.uuid4().hex[:6]}"
        await _seed_tech(db, tid, tech_id)
        try:
            # ``require_admin`` gates the endpoint; we simulate what the
            # dep injection would do by calling it directly with a tech
            # role and asserting 403.
            from utils import require_admin
            fake_tech_user = {"id": "u-tech", "role": "technician",
                               "tenant_id": tid}
            try:
                require_admin(fake_tech_user)
                assert False, "expected 403 from require_admin"
            except HTTPException as e:
                assert e.status_code == 403
        finally:
            await _cleanup(db, tid)
    run_test(_go)


# ── 8) Completed / cancelled / soft-deleted jobs don't count ───────
def test_p23_inactive_jobs_do_not_count_toward_block():
    async def _go(db):
        tid = await _seed_tenant(db)
        await _cleanup(db, tid)
        tech_id = f"{TAG}TECH_J_{uuid.uuid4().hex[:6]}"
        await _seed_tech(db, tid, tech_id)
        # One completed, one cancelled, one soft-deleted — none should
        # count toward the block threshold.
        await _seed_active_job(db, tid, tech_id, status="completed")
        await _seed_active_job(db, tid, tech_id, status="cancelled")
        jid_soft = await _seed_active_job(db, tid, tech_id)
        await db.jobs.update_one(
            {"id": jid_soft},
            {"$set": {"deleted_at": datetime.now(timezone.utc).isoformat()}},
        )
        try:
            res = await _call(
                tid=tech_id, user=_admin(tid), tenant={"id": tid},
            )
            # Passes the block check → gets soft-deleted directly.
            assert res["ok"] is True
            assert res["active_jobs_reassigned"] == 0
        finally:
            await _cleanup(db, tid)
    run_test(_go)
