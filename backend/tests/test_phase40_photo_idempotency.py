"""Phase 40 · Step 2 — Photo upload idempotency.

The mobile write queue replays `POST /api/jobs/{jid}/photos` with the
same `X-Idempotency-Key` when a device reconnects. Guarantee: same key +
same body → cached response, exactly ONE photo appended to the job.
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


def _tenant_id():
    async def _t(): return await db.users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0})
    return _run(_t())["tenant_id"]


def _seed_job(tenant_id):
    async def _s():
        jid = new_id()
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tenant_id,
            "customer_id": "test-cust", "customer_name": "Photo Idem Test",
            "service_type": "pool", "title": "Photo idempotency job",
            "status": "scheduled", "photos": [],
            "created_at": now_iso(), "updated_at": now_iso(),
        })
        return jid
    return _run(_s())


def _photo_count(jid):
    async def _c():
        job = await db.jobs.find_one({"id": jid}, {"photos": 1, "_id": 0})
        return len((job or {}).get("photos") or [])
    return _run(_c())


def test_same_key_same_photo_only_one_uploaded(admin_h):
    tid = _tenant_id()
    jid = _seed_job(tid)
    key = new_id()
    body = {"data": "data:image/png;base64,AAAA", "label": "checklist-test"}
    try:
        h = {**admin_h, "X-Idempotency-Key": key}
        r1 = requests.post(f"{API}/jobs/{jid}/photos", headers=h, json=body, timeout=15).json()
        r2 = requests.post(f"{API}/jobs/{jid}/photos", headers=h, json=body, timeout=15).json()
        # Identical cached response on replay.
        assert r1 == r2
        # Only ONE photo landed on the job.
        assert _photo_count(jid) == 1
    finally:
        async def _c():
            await db.jobs.delete_one({"id": jid})
            await db.idempotency_keys.delete_many({"key": key})
        _run(_c())


def test_same_key_different_body_flagged_as_mismatch(admin_h):
    """Reusing an idempotency key with a different photo body is a client
    bug — surface it loudly instead of silently returning the first
    photo's cached response."""
    tid = _tenant_id()
    jid = _seed_job(tid)
    key = new_id()
    try:
        h = {**admin_h, "X-Idempotency-Key": key}
        b1 = {"data": "data:image/png;base64,AAAA", "label": "first"}
        b2 = {"data": "data:image/png;base64,BBBB", "label": "second"}
        r1 = requests.post(f"{API}/jobs/{jid}/photos", headers=h, json=b1, timeout=15).json()
        r2 = requests.post(f"{API}/jobs/{jid}/photos", headers=h, json=b2, timeout=15).json()
        assert "photos" in r1  # first landed as normal job response
        # Second replay under same key with different body → mismatch marker.
        assert r2.get("error") == "idempotency_key_body_mismatch"
        # Only the first photo actually got appended.
        assert _photo_count(jid) == 1
    finally:
        async def _c():
            await db.jobs.delete_one({"id": jid})
            await db.idempotency_keys.delete_many({"key": key})
        _run(_c())
