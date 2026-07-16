"""Phase 31 · Step 2c — checklist reorder + idempotency.

The mobile client's drag-reorder handler PATCHes the service report
with the new `checklist_items` order (using an `X-Idempotency-Key` so
the offline `writeQueue.ts` can safely retry the same call after a
reconnect without duplicating writes).

Guarantees under test:
1. Reorder round-trips: submitted order === persisted order.
2. Same idempotency key + identical reorder body → cached response,
   no double-write.
3. Different final orders under different keys both persist (the last
   PATCH wins, which is the expected "last-writer" semantic).
"""
import sys
import asyncio
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

from config import db  # noqa: E402
from utils import new_id, now_iso  # noqa: E402


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _admin_user():
    async def _t():
        return await db.users.find_one({"email": "admin@aquaterra.com"}, {"_id": 0})
    return _run(_t())


def _tenant_id():
    return _admin_user()["tenant_id"]


def _seed_job_with_checklist(tid, initial_items):
    """Seed a job + service report so the PATCH has something to write to.

    The service_reports collection is scoped by `(tenant_id, job_id,
    tech_id)`. For an admin caller the endpoint falls back to
    `user.id` when the job has no assigned technician — we mirror that
    here so the PATCH resolves cleanly.
    """
    admin = _admin_user()
    tech_id = admin["id"]

    async def _s():
        jid = new_id()
        rid = new_id()
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tid,
            "customer_id": "test-cust", "customer_name": "Reorder Test",
            "service_type": "pool", "title": "Reorder idempotency job",
            "status": "in_progress",
            "created_at": now_iso(), "updated_at": now_iso(),
        })
        await db.service_reports.insert_one({
            "id": rid, "tenant_id": tid, "job_id": jid, "tech_id": tech_id,
            "chemical_readings": [], "chemicals_added": [],
            "checklist_items": initial_items,
            "notes": "", "photos": [],
            "created_at": now_iso(), "updated_at": now_iso(),
        })
        return jid
    return _run(_s())


def _fetch_report(jid):
    async def _f():
        return await db.service_reports.find_one({"job_id": jid}, {"_id": 0})
    return _run(_f())


def test_reorder_persists_and_idempotency_replays(admin_h):
    tid = _tenant_id()
    initial = [
        {"id": "chk-1", "label": "Skim", "checked": False},
        {"id": "chk-2", "label": "Brush", "checked": False},
        {"id": "chk-3", "label": "Vacuum", "checked": False},
    ]
    jid = _seed_job_with_checklist(tid, initial)
    reordered = [initial[2], initial[0], initial[1]]  # Vacuum, Skim, Brush
    key = new_id()
    try:
        h = {**admin_h, "X-Idempotency-Key": key,
              "Content-Type": "application/json"}
        body = {"checklist_items": reordered}
        r1 = requests.patch(f"{API}/jobs/{jid}/service-report",
                             headers=h, json=body, timeout=15)
        assert r1.status_code == 200, r1.text
        j1 = r1.json()

        # Replay the identical PATCH with the same key. Cached response
        # returned; the underlying document does NOT flip back-and-forth.
        r2 = requests.patch(f"{API}/jobs/{jid}/service-report",
                             headers=h, json=body, timeout=15)
        assert r2.status_code == 200, r2.text
        j2 = r2.json()
        assert j1 == j2

        # Persisted order matches what we sent.
        persisted = _fetch_report(jid)
        got_ids = [c["id"] for c in (persisted or {}).get("checklist_items", [])]
        assert got_ids == ["chk-3", "chk-1", "chk-2"], got_ids
    finally:
        async def _c():
            await db.jobs.delete_one({"id": jid})
            await db.service_reports.delete_many({"job_id": jid})
            await db.idempotency_keys.delete_many({"key": key})
        _run(_c())


def test_different_keys_both_persist_last_writer_wins(admin_h):
    tid = _tenant_id()
    initial = [
        {"id": "chk-a", "label": "A", "checked": False},
        {"id": "chk-b", "label": "B", "checked": False},
        {"id": "chk-c", "label": "C", "checked": False},
    ]
    jid = _seed_job_with_checklist(tid, initial)
    key1 = new_id()
    key2 = new_id()
    try:
        # First reorder — [B, A, C]
        h1 = {**admin_h, "X-Idempotency-Key": key1, "Content-Type": "application/json"}
        r1 = requests.patch(f"{API}/jobs/{jid}/service-report", headers=h1,
                             json={"checklist_items": [initial[1], initial[0], initial[2]]},
                             timeout=15)
        assert r1.status_code == 200

        # Second reorder under a NEW key — [C, B, A]
        h2 = {**admin_h, "X-Idempotency-Key": key2, "Content-Type": "application/json"}
        r2 = requests.patch(f"{API}/jobs/{jid}/service-report", headers=h2,
                             json={"checklist_items": [initial[2], initial[1], initial[0]]},
                             timeout=15)
        assert r2.status_code == 200

        persisted = _fetch_report(jid)
        got_ids = [c["id"] for c in (persisted or {}).get("checklist_items", [])]
        assert got_ids == ["chk-c", "chk-b", "chk-a"], got_ids
    finally:
        async def _c():
            await db.jobs.delete_one({"id": jid})
            await db.service_reports.delete_many({"job_id": jid})
            await db.idempotency_keys.delete_many({"key": {"$in": [key1, key2]}})
        _run(_c())
