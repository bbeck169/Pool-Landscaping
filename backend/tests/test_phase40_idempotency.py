"""Phase 40 · Idempotency-key tests.

Covers:
1. Same key + same body replayed → identical response, only one
   underlying write.
2. Different keys same body → both execute (as expected).
3. Expired key → new execution.
"""
import sys
import time
from pathlib import Path

import asyncio
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


def _seed_item(tenant_id, name, qty=100.0):
    async def _s():
        iid = new_id()
        await db.inventory_items.insert_one({
            "id": iid, "tenant_id": tenant_id, "name": name,
            "category": "chemical", "unit": "tabs",
            "current_qty": float(qty), "reorder_point": 0,
            "reorder_qty": 0, "unit_cost": 0, "created_at": now_iso(),
            "updated_at": now_iso()})
        return iid
    return _run(_s())


def test_same_key_replay_returns_cached_response(admin_h):
    """POST /inventory/reserve twice with the same key + body → identical
    response and only ONE reservation row in the DB."""
    tid = _tenant_id()
    item = f"IdemChem-{new_id()[:6]}"
    iid = _seed_item(tid, item, 50.0)
    jid = new_id()
    key = new_id()
    try:
        h = {**admin_h, "X-Idempotency-Key": key}
        body = {"chemical": item, "quantity": 4, "job_id": jid}
        r1 = requests.post(f"{API}/inventory/reserve",
                            headers=h, json=body, timeout=10).json()
        r2 = requests.post(f"{API}/inventory/reserve",
                            headers=h, json=body, timeout=10).json()
        assert r1["reservation_id"] == r2["reservation_id"]
        assert r1 == r2  # entire payload matches (cached replay)
        # Only ONE reservation row was created.
        async def _count():
            return await db.inventory_reservations.count_documents(
                {"job_id": jid, "tenant_id": tid})
        assert _run(_count()) == 1
    finally:
        async def _c():
            await db.inventory_items.delete_one({"id": iid})
            await db.inventory_reservations.delete_many({"job_id": jid})
            await db.idempotency_keys.delete_many({"key": key})
        _run(_c())


def test_different_keys_same_body_both_execute(admin_h):
    """Two different X-Idempotency-Keys with the same body must both
    create their own reservation — the client is intentionally saying
    'these are two different attempts'."""
    tid = _tenant_id()
    item = f"IdemChem-{new_id()[:6]}"
    iid = _seed_item(tid, item, 100.0)
    jid = new_id()
    k1, k2 = new_id(), new_id()
    try:
        body = {"chemical": item, "quantity": 3, "job_id": jid}
        r1 = requests.post(f"{API}/inventory/reserve",
                            headers={**admin_h, "X-Idempotency-Key": k1},
                            json=body, timeout=10).json()
        r2 = requests.post(f"{API}/inventory/reserve",
                            headers={**admin_h, "X-Idempotency-Key": k2},
                            json=body, timeout=10).json()
        assert r1["reservation_id"] != r2["reservation_id"]
        async def _count():
            return await db.inventory_reservations.count_documents(
                {"job_id": jid, "tenant_id": tid})
        assert _run(_count()) == 2
    finally:
        async def _c():
            await db.inventory_items.delete_one({"id": iid})
            await db.inventory_reservations.delete_many({"job_id": jid})
            await db.idempotency_keys.delete_many({"key": {"$in": [k1, k2]}})
        _run(_c())


def test_expired_key_treated_as_new(admin_h):
    """Manually mark the cached entry as expired → the next call must
    execute again and create a second reservation."""
    tid = _tenant_id()
    item = f"IdemChem-{new_id()[:6]}"
    iid = _seed_item(tid, item, 100.0)
    jid = new_id()
    key = new_id()
    try:
        h = {**admin_h, "X-Idempotency-Key": key}
        body = {"chemical": item, "quantity": 2, "job_id": jid}
        requests.post(f"{API}/inventory/reserve", headers=h,
                       json=body, timeout=10)
        # Force-expire the cached row.
        async def _expire():
            await db.idempotency_keys.update_one(
                {"key": key, "tenant_id": tid},
                {"$set": {"expires_at": "2000-01-01T00:00:00Z"}})
        _run(_expire())
        # New call should EXECUTE (create a second reservation).
        r2 = requests.post(f"{API}/inventory/reserve", headers=h,
                            json=body, timeout=10).json()
        async def _count():
            return await db.inventory_reservations.count_documents(
                {"job_id": jid, "tenant_id": tid})
        assert _run(_count()) == 2
        assert r2.get("reservation_id")
    finally:
        async def _c():
            await db.inventory_items.delete_one({"id": iid})
            await db.inventory_reservations.delete_many({"job_id": jid})
            await db.idempotency_keys.delete_many({"key": key})
        _run(_c())
