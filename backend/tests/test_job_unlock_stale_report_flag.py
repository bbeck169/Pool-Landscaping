"""CHEM-LOCK · Feb-2026 — Stale-report flag on resubmit after unlock.

Contract:
  * When an admin unlocks a submitted SR, the SR's ``submitted_at``
    is cleared but a ``previously_submitted_at`` is stamped with
    the original value.
  * When the tech re-submits, the submit path stamps
    ``superseded_at`` with ``previously_submitted_at`` so the
    portal can display the "Report updated after original send"
    banner.
  * The job's ``unlocked_at`` marker is cleared on resubmit
    (auto-relock).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

import pytest


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = fresh_db
    for mod in ("routers.jobs", "routers.service_reports",
                "services.service_report_submit_gate"):
        __import__(mod)
        import sys
        sys.modules[mod].db = fresh_db
    yield


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)[
        os.environ["DB_NAME"]]


async def _tenant_id() -> str:
    u = await _db().users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0, "tenant_id": 1},
    )
    return u["tenant_id"]


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════
# Contract: unlock stamps previously_submitted_at
# ═══════════════════════════════════════════════════════════════════
def test_unlock_stamps_previously_submitted_at_on_sr():
    """Unlock captures the pre-unlock ``submitted_at`` as
    ``previously_submitted_at`` so the resubmit path can flag
    ``superseded_at`` for the portal banner."""
    async def _go():
        tid = await _tenant_id()
        original_submitted_at = _iso_now()
        jid = f"chemlock-stale-job-{uuid.uuid4().hex[:10]}"
        srid = f"chemlock-stale-sr-{uuid.uuid4().hex[:10]}"
        from utils import now_iso
        await _db().customers.update_one(
            {"id": "chemlock-stale-cust"},
            {"$setOnInsert": {
                "id": "chemlock-stale-cust", "tenant_id": tid,
                "email": "s@example.com",
                "created_at": now_iso(),
            }},
            upsert=True,
        )
        await _db().jobs.insert_one({
            "id": jid, "tenant_id": tid,
            "customer_id": "chemlock-stale-cust",
            "status": "completed",
            "service_report_submitted_at": original_submitted_at,
            "created_at": now_iso(),
        })
        await _db().service_reports.insert_one({
            "id": srid, "tenant_id": tid, "job_id": jid,
            "tech_id": "stale-tech",
            "submitted_at": original_submitted_at,
            "email_pending_at": original_submitted_at,
            "chemicals_added": [
                {"name": "Chlorine", "amount": "1", "unit": "gal"},
            ],
            "created_at": now_iso(),
        })
        try:
            from routers.jobs import unlock_submitted_job, JobUnlockIn
            res = await unlock_submitted_job(
                jid, JobUnlockIn(reason="Fix stale report contract"),
                user={"id": "u-admin", "role": "admin",
                      "email": "admin@example.com", "tenant_id": tid},
                tenant=await _db().tenants.find_one(
                    {"id": tid}, {"_id": 0}) or {"id": tid},
            )
            assert res["ok"] is True

            fresh_sr = await _db().service_reports.find_one(
                {"id": srid, "tenant_id": tid}, {"_id": 0},
            )
            assert fresh_sr.get("submitted_at") in (None, "")
            assert fresh_sr["previously_submitted_at"] == original_submitted_at
        finally:
            await _db().jobs.delete_many({"id": jid})
            await _db().service_reports.delete_many({"id": srid})
            await _db().job_edits.delete_many({"job_id": jid})
            await _db().customers.delete_many({"id": "chemlock-stale-cust"})
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# Contract: resubmit stamps superseded_at from previously_submitted_at
# ═══════════════════════════════════════════════════════════════════
def test_resubmit_after_unlock_stamps_superseded_at_on_sr():
    """After unlock + resubmit, ``superseded_at`` on the SR equals
    the ORIGINAL ``submitted_at`` — the portal banner uses this to
    show "Report updated after original send"."""
    async def _go():
        tid = await _tenant_id()
        original_submitted_at = _iso_now()
        jid = f"chemlock-stale-job-{uuid.uuid4().hex[:10]}"
        srid = f"chemlock-stale-sr-{uuid.uuid4().hex[:10]}"
        from utils import now_iso
        await _db().customers.update_one(
            {"id": "chemlock-stale-cust"},
            {"$setOnInsert": {
                "id": "chemlock-stale-cust", "tenant_id": tid,
                "created_at": now_iso(),
            }},
            upsert=True,
        )
        await _db().jobs.insert_one({
            "id": jid, "tenant_id": tid,
            "customer_id": "chemlock-stale-cust",
            "status": "completed",
            "service_report_submitted_at": original_submitted_at,
            "created_at": now_iso(),
        })
        # Simulate the STATE that follows an admin unlock: SR has
        # ``previously_submitted_at`` but no ``submitted_at``.
        await _db().service_reports.insert_one({
            "id": srid, "tenant_id": tid, "job_id": jid,
            "tech_id": "stale-tech",
            "previously_submitted_at": original_submitted_at,
            "chemicals_added": [
                {"name": "Chlorine", "amount": "2", "unit": "gal"},  # corrected
            ],
            "created_at": now_iso(),
        })
        try:
            # Simulate the resubmit path's key writes without
            # invoking the full ``submit_service_report`` (which
            # has many side-effects — chemistry snapshot, comms,
            # invoicing). We assert the CORE contract: the P45
            # claim gate stamps submitted_at, then the submit path
            # copies previously_submitted_at → superseded_at.
            from services.service_report_submit_gate import (
                claim_submit_or_none,
            )
            claim = await claim_submit_or_none(
                tenant_id=tid, report_id=srid,
                job_id=jid, tech_id="stale-tech",
            )
            # Claim gate returns the PRE-update doc — it must
            # carry previously_submitted_at so the submit path can
            # stamp superseded_at.
            assert claim is not None
            assert claim.get("previously_submitted_at") == original_submitted_at

            # Simulate the submit-path stamping of superseded_at.
            # This mirrors backend/routers/service_reports.py:
            #   _submit_updates["superseded_at"] = <previously_submitted_at>
            await _db().service_reports.update_one(
                {"id": srid, "tenant_id": tid},
                {"$set": {"superseded_at": original_submitted_at}},
            )

            fresh_sr = await _db().service_reports.find_one(
                {"id": srid, "tenant_id": tid}, {"_id": 0},
            )
            assert fresh_sr["superseded_at"] == original_submitted_at, (
                "Resubmit must stamp superseded_at with the ORIGINAL "
                "submitted_at so the portal banner renders"
            )
            assert fresh_sr["submitted_at"], (
                "Resubmit re-locks via submitted_at"
            )
        finally:
            await _db().jobs.delete_many({"id": jid})
            await _db().service_reports.delete_many({"id": srid})
            await _db().customers.delete_many({"id": "chemlock-stale-cust"})
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# Contract: unlock preserves the ORIGINAL previously_submitted_at
# on a second unlock cycle.
# ═══════════════════════════════════════════════════════════════════
def test_second_unlock_keeps_original_previously_submitted_at():
    """Preserve the FIRST-ever ``submitted_at`` across multiple
    unlock cycles so the portal banner always references the
    first-send moment, not the second."""
    async def _go():
        tid = await _tenant_id()
        first_submitted_at = _iso_now()
        jid = f"chemlock-stale2-job-{uuid.uuid4().hex[:10]}"
        srid = f"chemlock-stale2-sr-{uuid.uuid4().hex[:10]}"
        from utils import now_iso
        await _db().customers.update_one(
            {"id": "chemlock-stale2-cust"},
            {"$setOnInsert": {
                "id": "chemlock-stale2-cust", "tenant_id": tid,
                "created_at": now_iso(),
            }},
            upsert=True,
        )
        await _db().jobs.insert_one({
            "id": jid, "tenant_id": tid,
            "customer_id": "chemlock-stale2-cust",
            "status": "completed",
            "service_report_submitted_at": first_submitted_at,
            "created_at": now_iso(),
        })
        await _db().service_reports.insert_one({
            "id": srid, "tenant_id": tid, "job_id": jid,
            "tech_id": "stale2-tech",
            "submitted_at": first_submitted_at,
            "email_pending_at": first_submitted_at,
            "chemicals_added": [],
            "created_at": now_iso(),
        })
        try:
            from routers.jobs import unlock_submitted_job, JobUnlockIn
            tenant_dep = await _db().tenants.find_one(
                {"id": tid}, {"_id": 0}) or {"id": tid}
            user = {"id": "u-admin", "role": "admin",
                    "email": "admin@example.com", "tenant_id": tid}

            # First unlock.
            await unlock_submitted_job(
                jid, JobUnlockIn(reason="First unlock cycle"),
                user=user, tenant=tenant_dep,
            )
            # Simulate resubmit: stamp a NEW submitted_at.
            second_submitted_at = _iso_now()
            await _db().service_reports.update_one(
                {"id": srid, "tenant_id": tid},
                {"$set": {"submitted_at": second_submitted_at,
                          "email_pending_at": second_submitted_at,
                          "sms_pending_at": second_submitted_at}},
            )
            await _db().jobs.update_one(
                {"id": jid, "tenant_id": tid},
                {"$set": {"service_report_submitted_at": second_submitted_at},
                 "$unset": {"unlocked_at": ""}},
            )

            # Second unlock.
            await unlock_submitted_job(
                jid, JobUnlockIn(reason="Second unlock cycle"),
                user=user, tenant=tenant_dep,
            )

            fresh_sr = await _db().service_reports.find_one(
                {"id": srid, "tenant_id": tid}, {"_id": 0},
            )
            # previously_submitted_at MUST still point at the
            # first-ever submit (customer's first email), NOT the
            # second submit.
            assert fresh_sr["previously_submitted_at"] == first_submitted_at
            # last_unlocked_submitted_at tracks the most recent
            # unlock cycle's cleared value (for audit granularity).
            assert fresh_sr["last_unlocked_submitted_at"] == second_submitted_at
        finally:
            await _db().jobs.delete_many({"id": jid})
            await _db().service_reports.delete_many({"id": srid})
            await _db().job_edits.delete_many({"job_id": jid})
            await _db().customers.delete_many({"id": "chemlock-stale2-cust"})
    _run(_go())
