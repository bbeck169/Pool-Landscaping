"""Phase 39 · Step 3 · Truck Inventory Reservation tests."""
import sys
from pathlib import Path

import asyncio
import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def cust_h():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')['access_token']}"}


from config import db  # noqa: E402
from utils import new_id, now_iso  # noqa: E402


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _tenant():
    async def _t(): return await db.users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0})
    return _run(_t())["tenant_id"]


def _seed_item(tenant_id, name, unit, qty):
    async def _s():
        iid = new_id()
        await db.inventory_items.insert_one({
            "id": iid, "tenant_id": tenant_id, "name": name,
            "category": "chemical", "unit": unit,
            "current_qty": float(qty), "reorder_point": 0,
            "reorder_qty": 0, "unit_cost": 0, "created_at": now_iso(),
            "updated_at": now_iso()})
        return iid
    return _run(_s())


def _cleanup(tenant_id, item_id, job_id):
    async def _c():
        await db.inventory_items.delete_one({"id": item_id})
        await db.inventory_reservations.delete_many({"job_id": job_id})
        await db.stock_movements.delete_many({"job_id": job_id})
    _run(_c())


def test_reserve_and_update_and_release(admin_h):
    tid = _tenant()
    item = f"TestChem-{new_id()[:6]}"
    iid = _seed_item(tid, item, "tabs", 100.0)
    jid = new_id()
    try:
        # 1) Reserve 5.
        r = requests.post(f"{API}/inventory/reserve", headers=admin_h, timeout=10,
                          json={"chemical": item, "quantity": 5, "unit": "tabs",
                                "job_id": jid}).json()
        assert r["ok"] is True and r["delta"] == 5.0
        assert r.get("warning") in (None, "")
        rid = r["reservation_id"]

        # 2) Update to 7 → delta +2.
        r2 = requests.post(f"{API}/inventory/reserve", headers=admin_h, timeout=10,
                           json={"chemical": item, "quantity": 7, "unit": "tabs",
                                 "job_id": jid, "reservation_id": rid}).json()
        assert r2["ok"] and r2["delta"] == 2.0

        # 3) Reserve more than available → warning but still active.
        r3 = requests.post(f"{API}/inventory/reserve", headers=admin_h, timeout=10,
                           json={"chemical": item, "quantity": 200,
                                 "unit": "tabs", "job_id": jid}).json()
        assert r3["ok"] is True
        assert "short" in (r3.get("warning") or "").lower()
        assert (r3.get("suggested_restock") or 0) >= 1

        # 4) Release the second reservation.
        d = requests.delete(f"{API}/inventory/reserve/{r3['reservation_id']}",
                            headers=admin_h, timeout=10)
        assert d.status_code == 200

        # 5) Consume all remaining reservations → item stock drops.
        c = requests.post(f"{API}/inventory/reservations/{jid}/consume",
                          headers=admin_h, timeout=10).json()
        assert c["count"] >= 1
        async def _get_qty():
            it = await db.inventory_items.find_one({"id": iid}, {"_id": 0})
            return float(it["current_qty"])
        assert _run(_get_qty()) == 93.0  # 100 - 7 consumed
    finally:
        _cleanup(tid, iid, jid)


def test_release_job_reservations(admin_h):
    tid = _tenant()
    item = f"TestChem-{new_id()[:6]}"
    iid = _seed_item(tid, item, "tabs", 50.0)
    jid = new_id()
    try:
        requests.post(f"{API}/inventory/reserve", headers=admin_h, timeout=10,
                      json={"chemical": item, "quantity": 3, "job_id": jid}).json()
        r = requests.post(f"{API}/inventory/reservations/{jid}/release",
                          headers=admin_h, timeout=10).json()
        assert r["released"] == 1
        # Stock untouched.
        async def _q():
            return (await db.inventory_items.find_one({"id": iid}, {"_id": 0}))["current_qty"]
        assert _run(_q()) == 50.0
    finally:
        _cleanup(tid, iid, jid)


def test_rbac_customer_denied(cust_h):
    r = requests.post(f"{API}/inventory/reserve", headers=cust_h, timeout=10,
                      json={"chemical": "x", "quantity": 1, "job_id": "x"})
    assert r.status_code == 403


def test_unmatched_chemical_still_reserves(admin_h):
    """Unknown chemical name → reservation created, `unmatched:true`, no warning."""
    tid = _tenant()
    jid = new_id()
    try:
        r = requests.post(f"{API}/inventory/reserve", headers=admin_h, timeout=10,
                          json={"chemical": f"UnknownXyz-{new_id()[:6]}",
                                "quantity": 3, "job_id": jid}).json()
        assert r["ok"] and r.get("unmatched") is True
        assert r.get("warning") in (None, "")
    finally:
        async def _c(): await db.inventory_reservations.delete_many({"job_id": jid})
        _run(_c())
