"""Phase K12 · Feb-2026 — verify the workstream jobs endpoint
surfaces ``completed_at`` on each row so the Frontend can render
the K12 "Completed" column."""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

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
    for mod in ("routers.workstream",):
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


def test_k12_workstream_response_includes_completed_at():
    async def _go():
        u = await _db().users.find_one({"email": "super@aquaterra.com"},
                                        {"_id": 0, "id": 1, "tenant_id": 1,
                                         "role": 1})
        tid = u["tenant_id"]
        jid = f"k12-completed-{uuid.uuid4().hex[:6]}"
        cid = f"k12-cust-{uuid.uuid4().hex[:6]}"
        completed_iso = datetime.now(timezone.utc).isoformat()
        await _db().customers.insert_one({
            "id": cid, "tenant_id": tid, "name": "K12 Cust",
            "created_at": completed_iso,
        })
        await _db().jobs.insert_one({
            "id": jid, "tenant_id": tid, "customer_id": cid,
            "service_type": "K12 Landscape",
            "status": "completed",
            "completed_at": completed_iso,
            "scheduled_date": completed_iso[:10],
            "created_at": completed_iso,
            "updated_at": completed_iso,
        })
        try:
            from routers.workstream import list_workstream_jobs
            tenant = await _db().tenants.find_one({"id": tid},
                                                    {"_id": 0}) or {"id": tid}
            resp = await list_workstream_jobs(
                since=None, until=None,
                status="completed", tech_id=None,
                customer_id=None,
                offset=0, limit=500, sort="newest",
                user={**u, "tenant_id": tid, "role": u["role"] or "super_admin"},
                tenant=tenant,
            )
            rows = resp.get("jobs") or []
            k12 = next((r for r in rows if r["id"] == jid), None)
            assert k12 is not None, "K12 seed job missing from response"
            assert "completed_at" in k12, k12
            assert k12["completed_at"] == completed_iso
        finally:
            await _db().jobs.delete_one({"id": jid})
            await _db().customers.delete_one({"id": cid})
    _run(_go())
