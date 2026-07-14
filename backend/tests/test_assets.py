"""Phase 20B.3 — Assets & maintenance."""
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status(); return r.json()


@pytest.fixture(scope="module")
def dbc(): return MongoClient(MONGO_URL)[DB_NAME]

@pytest.fixture(scope="module")
def admin_h(): return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def tech_h(): return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def customer_h(): return {"Authorization": f"Bearer {_login('customer@aquaterra.com')['access_token']}"}


def test_asset_crud(admin_h, dbc):
    body = {"name": "Test Truck 20B3", "category": "vehicle",
            "asset_tag": "TT-001", "serial_number": "SN-123"}
    a = requests.post(f"{API}/assets", headers=admin_h, json=body, timeout=15).json()
    aid = a["id"]
    fetched = requests.get(f"{API}/assets/{aid}", headers=admin_h, timeout=15).json()
    assert fetched["name"] == "Test Truck 20B3"

    upd = requests.put(f"{API}/assets/{aid}", headers=admin_h,
                       json={"notes": "Front-line truck"}, timeout=15).json()
    assert upd["notes"] == "Front-line truck"

    lst = requests.get(f"{API}/assets", headers=admin_h,
                       params={"category": "vehicle"}, timeout=15).json()
    assert any(x["id"] == aid for x in lst)

    d = requests.delete(f"{API}/assets/{aid}", headers=admin_h, timeout=15)
    assert d.status_code == 200


def test_asset_assign_creates_log_entry(admin_h, dbc):
    body = {"name": "Test Pump 20B3", "category": "equipment"}
    a = requests.post(f"{API}/assets", headers=admin_h, json=body, timeout=15).json()
    aid = a["id"]
    mike = dbc.users.find_one({"email": "mike@aquaterra.com"})
    r = requests.post(f"{API}/assets/{aid}/assign", headers=admin_h,
                     json={"user_id": mike["id"], "notes": "initial"}, timeout=15).json()
    assert r["assigned_to_user_id"] == mike["id"]

    log = requests.get(f"{API}/assets/{aid}/assignments",
                       headers=admin_h, timeout=15).json()
    assert any(e["to_user_id"] == mike["id"] and e["unassigned_at"] is None for e in log)

    # Unassign → previous log entry closes.
    r2 = requests.post(f"{API}/assets/{aid}/assign", headers=admin_h,
                      json={"user_id": None, "notes": "unassigned"}, timeout=15).json()
    assert r2["assigned_to_user_id"] is None
    log2 = requests.get(f"{API}/assets/{aid}/assignments",
                        headers=admin_h, timeout=15).json()
    assert all(e.get("unassigned_at") is not None for e in log2 if e["to_user_id"] == mike["id"])

    requests.delete(f"{API}/assets/{aid}", headers=admin_h, timeout=15)


def test_asset_tech_only_sees_own_and_customer_403(admin_h, tech_h, customer_h, dbc):
    body = {"name": "Techn Asset 20B3", "category": "tool"}
    a = requests.post(f"{API}/assets", headers=admin_h, json=body, timeout=15).json()
    mike = dbc.users.find_one({"email": "mike@aquaterra.com"})
    requests.post(f"{API}/assets/{a['id']}/assign", headers=admin_h,
                  json={"user_id": mike["id"]}, timeout=15)
    lst = requests.get(f"{API}/assets", headers=tech_h, timeout=15).json()
    assert any(x["id"] == a["id"] for x in lst)
    # Unassigned asset must not appear.
    other = requests.post(f"{API}/assets", headers=admin_h,
                          json={"name": "Unassigned tool 20B3", "category": "tool"},
                          timeout=15).json()
    lst2 = requests.get(f"{API}/assets", headers=tech_h, timeout=15).json()
    assert all(x["id"] != other["id"] for x in lst2)

    # Customer → 403.
    c = requests.get(f"{API}/assets", headers=customer_h, timeout=15)
    assert c.status_code == 403

    requests.delete(f"{API}/assets/{a['id']}", headers=admin_h, timeout=15)
    requests.delete(f"{API}/assets/{other['id']}", headers=admin_h, timeout=15)


def test_asset_maintenance_and_next_due_reminder(admin_h, dbc):
    a = requests.post(f"{API}/assets", headers=admin_h,
                     json={"name": "Truck Reminder 20B3", "category": "vehicle"},
                     timeout=15).json()
    due = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    m = requests.post(f"{API}/assets/{a['id']}/maintenance", headers=admin_h,
                     json={"kind": "service", "cost": 250.0, "next_due_at": due,
                           "notes": "oil change"}, timeout=15).json()
    assert m["next_due_at"] == due

    ml = requests.get(f"{API}/assets/{a['id']}/maintenance",
                      headers=admin_h, timeout=15).json()
    assert len(ml) >= 1

    reminders = requests.get(f"{API}/assets/reminders/due?days=7",
                              headers=admin_h, timeout=15).json()
    ids = [x["id"] for x in reminders["upcoming"]]
    assert a["id"] in ids

    dbc.asset_maintenance.delete_many({"asset_id": a["id"]})
    requests.delete(f"{API}/assets/{a['id']}", headers=admin_h, timeout=15)
