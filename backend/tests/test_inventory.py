"""Phase 23 · Inventory tracker tests."""
import time
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status(); return r.json()


@pytest.fixture(scope="module")
def dbc(): return MongoClient(_BE["MONGO_URL"])[_BE["DB_NAME"]]

@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def customer_h():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def sunbelt_admin_h():
    try:
        return {"Authorization": f"Bearer {_login('admin@sunbelt.com')['access_token']}"}
    except Exception:
        pytest.skip("no sunbelt admin")


def test_defaults_seeded_on_first_get(admin_h, dbc):
    # Force clean and re-fetch
    t = dbc.tenants.find_one({"slug": "aquaterra"})
    dbc.inventory_items.delete_many({"tenant_id": t["id"]})
    r = requests.get(f"{API}/inventory/items", headers=admin_h,
                      timeout=15).json()
    names = {i["name"] for i in r["items"]}
    for req in ("Liquid Chlorine", "Muriatic Acid", "Pool Salt",
                 "DE Powder", "Pool Filter Cartridge"):
        assert req in names, f"seed missing: {req}"


def test_create_adjust_and_movements(admin_h, dbc):
    r = requests.post(f"{API}/inventory/items", headers=admin_h, json={
        "name": "Test-Widget-" + str(int(time.time())),
        "category": "part", "unit": "ea",
        "current_qty": 10, "reorder_point": 3, "reorder_qty": 5,
        "unit_cost": 12.50, "supplier": "Test Corp",
    }, timeout=15).json()
    iid = r["id"]
    assert r["current_qty"] == 10
    # Adjust -4
    adj = requests.post(f"{API}/inventory/items/{iid}/adjust",
                         headers=admin_h,
                         json={"delta": -4, "reason": "usage test"},
                         timeout=15).json()
    assert adj["current_qty"] == 6
    # Adjust +2 restock
    requests.post(f"{API}/inventory/items/{iid}/adjust",
                    headers=admin_h,
                    json={"delta": 2, "reason": "restock test"},
                    timeout=15)
    inv = requests.get(f"{API}/inventory/items/{iid}/movements",
                        headers=admin_h, timeout=15).json()
    assert inv["total"] >= 3  # initial + usage + restock
    kinds = {m["kind"] for m in inv["items"]}
    assert "usage" in kinds and "restock" in kinds
    dbc.inventory_items.delete_one({"id": iid})
    dbc.stock_movements.delete_many({"item_id": iid})


def test_low_stock_alerts(admin_h, dbc):
    r = requests.post(f"{API}/inventory/items", headers=admin_h, json={
        "name": "AlertWidget-" + str(int(time.time())),
        "category": "part", "unit": "ea",
        "current_qty": 2, "reorder_point": 5, "reorder_qty": 10,
    }, timeout=15).json()
    iid = r["id"]
    alerts = requests.get(f"{API}/inventory/alerts",
                            headers=admin_h, timeout=15).json()
    assert any(a["item_id"] == iid for a in alerts["items"])
    dbc.inventory_items.delete_one({"id": iid})
    dbc.stock_movements.delete_many({"item_id": iid})


def test_po_lifecycle_restocks(admin_h, dbc):
    r = requests.post(f"{API}/inventory/items", headers=admin_h, json={
        "name": "POTestItem-" + str(int(time.time())),
        "category": "part", "unit": "ea",
        "current_qty": 5, "reorder_point": 3, "reorder_qty": 10,
    }, timeout=15).json()
    iid = r["id"]
    po = requests.post(f"{API}/inventory/purchase-orders", headers=admin_h,
                        json={"supplier": "TestVendor",
                                "items": [{"item_id": iid, "qty": 8,
                                             "unit_cost": 5.0}]},
                        timeout=15).json()
    pid = po["id"]
    assert po["status"] == "pending"
    # Transition ordered
    requests.patch(f"{API}/inventory/purchase-orders/{pid}",
                    headers=admin_h, json={"status": "ordered"},
                    timeout=15)
    # Transition received → auto-restock
    requests.patch(f"{API}/inventory/purchase-orders/{pid}",
                    headers=admin_h, json={"status": "received"},
                    timeout=15)
    item_after = requests.get(f"{API}/inventory/items/{iid}",
                                headers=admin_h, timeout=15) if False else None
    # Fetch by list (no single-item GET endpoint)
    lst = requests.get(f"{API}/inventory/items?q=POTestItem",
                        headers=admin_h, timeout=15).json()
    it = next(i for i in lst["items"] if i["id"] == iid)
    assert it["current_qty"] == 13  # 5 + 8
    dbc.inventory_items.delete_one({"id": iid})
    dbc.purchase_orders.delete_one({"id": pid})
    dbc.stock_movements.delete_many({"item_id": iid})


def test_service_report_decrements_inventory(admin_h, dbc):
    """End-to-end: seed a job with `chemicals_added`, hit submit endpoint
    via the direct helper (bypasses auth complexity), and confirm the
    matching inventory item's qty drops + stock_movements record exists."""
    t = dbc.tenants.find_one({"slug": "aquaterra"})
    # Ensure Liquid Chlorine has a known baseline
    baseline = 30.0
    dbc.inventory_items.update_one(
        {"tenant_id": t["id"], "name": "Liquid Chlorine"},
        {"$set": {"current_qty": baseline}},
    )
    job = {
        "id": "test-inv-job-" + str(int(time.time())),
        "tenant_id": t["id"],
        "chemicals_added": [
            {"name": "Liquid Chlorine", "amount": 3.5},
            {"name": "Muriatic Acid", "amount": 12},
            {"name": "Unknown Chemical XYZ", "amount": 5},
        ],
    }
    import asyncio
    from routers.inventory import decrement_from_service_report
    result = asyncio.get_event_loop().run_until_complete(
        decrement_from_service_report(t["id"], job, "test-report-1", "u1"))
    assert len(result["decremented"]) == 2  # 2 matched
    assert "Unknown Chemical XYZ" in result["misses"]
    # Verify the actual DB state
    lc = dbc.inventory_items.find_one(
        {"tenant_id": t["id"], "name": "Liquid Chlorine"})
    assert abs(lc["current_qty"] - (baseline - 3.5)) < 0.01, (
        f"expected {baseline - 3.5}, got {lc['current_qty']}")
    # Movement record exists
    mv = dbc.stock_movements.find_one(
        {"tenant_id": t["id"], "item_id": lc["id"],
          "ref_id": "test-report-1"})
    assert mv is not None
    assert mv["kind"] == "usage"
    assert mv["delta"] == -3.5


def test_tenant_isolation(admin_h, sunbelt_admin_h, dbc):
    r = requests.post(f"{API}/inventory/items", headers=admin_h, json={
        "name": "IsoTest-" + str(int(time.time())),
        "category": "part", "unit": "ea",
        "current_qty": 5, "reorder_point": 2, "reorder_qty": 5,
    }, timeout=15).json()
    iid = r["id"]
    s = requests.patch(f"{API}/inventory/items/{iid}",
                        headers=sunbelt_admin_h, json={"notes": "x"},
                        timeout=15)
    assert s.status_code == 404
    dbc.inventory_items.delete_one({"id": iid})


def test_role_gating(tech_h, customer_h, dbc):
    # Tech: can list (200), cannot create (403)
    r = requests.get(f"{API}/inventory/items", headers=tech_h, timeout=15)
    assert r.status_code == 200
    r2 = requests.post(f"{API}/inventory/items", headers=tech_h, json={
        "name": "TechTry", "category": "part", "unit": "ea",
        "current_qty": 1, "reorder_point": 1, "reorder_qty": 1,
    }, timeout=15)
    assert r2.status_code == 403
    # Customer: 403 on list AND on create.
    r3 = requests.get(f"{API}/inventory/items",
                       headers=customer_h, timeout=15)
    assert r3.status_code == 403
    r4 = requests.get(f"{API}/inventory/analytics",
                       headers=customer_h, timeout=15)
    assert r4.status_code == 403
