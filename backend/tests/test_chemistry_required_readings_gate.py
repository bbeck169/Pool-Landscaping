"""Feb-2026 · Chemistry required-readings gate — end-to-end tests.

12 cases, all three enforcement points exercised.  Uses the same
loop-binding fixture pattern as ``test_door_hanger_auto_send.py``.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException


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
    import routers.jobs as _j
    _j.db = fresh_db
    import routers.service_reports as _sr
    _sr.db = fresh_db
    import routers.mobile_sync as _ms
    _ms.db = fresh_db
    yield


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(
        os.environ["MONGO_URL"], io_loop=_LOOP,
    )[os.environ["DB_NAME"]]


async def _tenant_id() -> str:
    u = await _db().users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0, "tenant_id": 1},
    )
    return u["tenant_id"]


async def _mk_pool_job(tid: str, *, cid: str | None = None,
                       status: str = "pending") -> str:
    from utils import now_iso
    jid = f"cg-job-{uuid.uuid4().hex[:10]}"
    await _db().jobs.insert_one({
        "id": jid, "tenant_id": tid, "customer_id": cid,
        "customer_name": "CG Test", "service_type": "Weekly Pool Service",
        "technician_id": "cg-tech",
        "status": status, "scheduled_date": now_iso(),
        "title": "Weekly Pool", "created_at": now_iso(),
    })
    return jid


async def _mk_service_report(tid: str, jid: str, *,
                             readings: List[Dict[str, Any]] | None = None,
                             tech_id: str = "cg-tech") -> str:
    from utils import now_iso
    sr_id = f"cg-sr-{uuid.uuid4().hex[:10]}"
    await _db().service_reports.insert_one({
        "id": sr_id, "tenant_id": tid, "job_id": jid, "tech_id": tech_id,
        "chemical_readings": readings or [],
        "created_at": now_iso(), "updated_at": now_iso(),
    })
    return sr_id


def _full_readings() -> List[Dict[str, Any]]:
    return [
        {"key": "free_chlorine",  "value": 2.5},
        {"key": "total_chlorine", "value": 3.0},
        {"key": "ph",             "value": 7.4},
        {"key": "alkalinity",     "value": 80},
        {"key": "cyanuric_acid",  "value": 40},
    ]


async def _drain(tid: str, jid: str) -> None:
    for coll in ("jobs", "service_reports", "customers",
                 "marketing_deliveries", "marketing_event_ledger"):
        await _db()[coll].delete_many(
            {"tenant_id": tid, "$or": [{"id": jid}, {"job_id": jid},
                                         {"trigger_entity.id": jid}]})


# ═════════════════════════════════════════════════════════════════════
# Unit-level: helper contract (fast, no DB).
# ═════════════════════════════════════════════════════════════════════
def test_helper_valid_reading_accepts_zero_and_negative():
    from services.chemistry_gate import assert_core_readings_present
    # Zero and negatives are REAL chemistry values → gate passes.
    assert_core_readings_present({
        "free_chlorine": 0, "total_chlorine": -1.5,
        "ph": "7.0", "alkalinity": 80, "cyanuric_acid": 40,
    })  # no raise


def test_helper_rejects_empty_whitespace_and_unparseable_strings():
    from services.chemistry_gate import missing_core_readings
    r = missing_core_readings({
        "free_chlorine": "",
        "total_chlorine": "   ",
        "ph": "not-a-number",
        "alkalinity": 80,
        "cyanuric_acid": 40,
    })
    assert set(r) == {"free_cl", "total_cl", "ph"}


def test_helper_accepts_list_of_dicts_shape():
    from services.chemistry_gate import missing_core_readings
    r = missing_core_readings([
        {"key": "free_chlorine", "value": 2.5},
        {"key": "total_chlorine", "value": 3.0},
        {"key": "ph", "value": 7.4},
        {"key": "alkalinity", "value": 80},
        # cya missing
    ])
    assert r == ["cya"]


def test_helper_accepts_aliased_keys():
    from services.chemistry_gate import missing_core_readings
    # UI-friendly aliases fold onto canonical keys.
    r = missing_core_readings({
        "free_cl": 2.5, "total_cl": 3.0,
        "ph": 7.4, "alk": 80, "cya": 40,
    })
    assert r == []


# ═════════════════════════════════════════════════════════════════════
# service-report submit path.
# ═════════════════════════════════════════════════════════════════════
def test_submit_with_all_5_cores_completes_the_job():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_pool_job(tid)
        await _mk_service_report(tid, jid, readings=_full_readings())
        try:
            from routers.service_reports import submit_service_report
            # A tech user whose ``technician_id`` matches the report.
            tech_user = {"id": "u-cg", "role": "technician",
                         "technician_id": "cg-tech",
                         "tenant_id": tid}
            tenant = await _db().tenants.find_one({"id": tid}, {"_id": 0}) or {"id": tid}
            r = await submit_service_report(
                jid, user=tech_user, tenant=tenant,
            )
            assert r.get("submitted_at")
            after = await _db().jobs.find_one({"id": jid}, {"_id": 0, "status": 1})
            assert after["status"] == "completed"
        finally:
            await _drain(tid, jid)

    _run(_go())


def test_submit_with_one_core_missing_raises_422():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_pool_job(tid)
        partial = _full_readings()
        # Drop CYA + pH.
        partial = [r for r in partial if r["key"] not in ("cyanuric_acid", "ph")]
        await _mk_service_report(tid, jid, readings=partial)
        try:
            from routers.service_reports import submit_service_report
            tech_user = {"id": "u-cg", "role": "technician",
                         "technician_id": "cg-tech", "tenant_id": tid}
            tenant = await _db().tenants.find_one({"id": tid}, {"_id": 0}) or {"id": tid}
            with pytest.raises(HTTPException) as ei:
                await submit_service_report(jid, user=tech_user, tenant=tenant)
            assert ei.value.status_code == 422
            detail = ei.value.detail
            assert detail["detail"] == "chemistry_core_readings_missing"
            assert set(detail["missing_fields"]) == {"ph", "cya"}
            after = await _db().jobs.find_one({"id": jid}, {"_id": 0, "status": 1})
            assert after["status"] != "completed"
        finally:
            await _drain(tid, jid)

    _run(_go())


def test_submit_ok_with_optionals_blank():
    """Water temp + calcium hardness stay blank — job still closes."""
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_pool_job(tid)
        readings = _full_readings() + [
            {"key": "water_temp", "value": None},
            {"key": "calcium_hardness", "value": ""},
        ]
        await _mk_service_report(tid, jid, readings=readings)
        try:
            from routers.service_reports import submit_service_report
            tech_user = {"id": "u-cg", "role": "technician",
                         "technician_id": "cg-tech", "tenant_id": tid}
            tenant = await _db().tenants.find_one({"id": tid}, {"_id": 0}) or {"id": tid}
            r = await submit_service_report(jid, user=tech_user, tenant=tenant)
            assert r.get("submitted_at")
        finally:
            await _drain(tid, jid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# PUT /jobs/{jid} — admin edit path.
# ═════════════════════════════════════════════════════════════════════
def test_admin_put_to_completed_with_missing_cores_raises_422():
    async def _go():
        tid = await _tenant_id()
        admin = await _db().users.find_one({"email": "admin@aquaterra.com"}, {"_id": 0})
        jid = await _mk_pool_job(tid)
        # No service_report + no legacy job.chemical_readings → gate blocks.
        try:
            from routers.jobs import update_job
            # Body model — a minimal object with a ``.dict()`` shim.
            class _B:
                def dict(self):
                    return {"status": "completed"}
            tenant = await _db().tenants.find_one({"id": tid}, {"_id": 0}) or {"id": tid}
            with pytest.raises(HTTPException) as ei:
                await update_job(jid, _B(), user=admin, tenant=tenant)
            assert ei.value.status_code == 422
            assert ei.value.detail["detail"] == "chemistry_core_readings_missing"
            after = await _db().jobs.find_one({"id": jid}, {"_id": 0, "status": 1})
            assert after["status"] != "completed"
        finally:
            await _drain(tid, jid)

    _run(_go())


def test_admin_put_to_could_not_service_is_not_gated():
    async def _go():
        tid = await _tenant_id()
        admin = await _db().users.find_one({"email": "admin@aquaterra.com"}, {"_id": 0})
        jid = await _mk_pool_job(tid)
        try:
            from routers.jobs import update_job

            class _B:
                def dict(self):
                    return {"status": "could_not_service"}
            tenant = await _db().tenants.find_one({"id": tid}, {"_id": 0}) or {"id": tid}
            # No raise — gate must NOT apply to CNS transitions.
            await update_job(jid, _B(), user=admin, tenant=tenant)
            after = await _db().jobs.find_one({"id": jid}, {"_id": 0, "status": 1})
            assert after["status"] == "could_not_service"
        finally:
            await _drain(tid, jid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# mobile_sync._handle_job_close.
# ═════════════════════════════════════════════════════════════════════
def test_mobile_replay_close_with_missing_cores_raises_422():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_pool_job(tid)
        try:
            from routers.mobile_sync import _handle_job_close, _SyncOp
            from utils import now_iso
            op = _SyncOp(client_op_id=uuid.uuid4().hex, op_type="job_close",
                         entity_id=jid,
                         payload={"completed_at": now_iso()},
                         client_ts=now_iso())
            with pytest.raises(HTTPException) as ei:
                await _handle_job_close(op, tid, "u-cg")
            assert ei.value.status_code == 422
            after = await _db().jobs.find_one({"id": jid}, {"_id": 0, "status": 1})
            assert after["status"] != "completed"
        finally:
            await _drain(tid, jid)

    _run(_go())


def test_mobile_replay_close_with_full_readings_completes_job():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_pool_job(tid)
        await _mk_service_report(tid, jid, readings=_full_readings())
        try:
            from routers.mobile_sync import _handle_job_close, _SyncOp
            from utils import now_iso
            op = _SyncOp(client_op_id=uuid.uuid4().hex, op_type="job_close",
                         entity_id=jid,
                         payload={"completed_at": now_iso()},
                         client_ts=now_iso())
            r = await _handle_job_close(op, tid, "u-cg")
            assert r["server_id"] == jid
            after = await _db().jobs.find_one({"id": jid}, {"_id": 0, "status": 1})
            assert after["status"] == "completed"
        finally:
            await _drain(tid, jid)

    _run(_go())
