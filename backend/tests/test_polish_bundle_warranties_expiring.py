"""Phase Feb-2026 · Polish bundle · Item 3 tests.

``GET /api/warranties/expiring-soon`` — returns active contracts
within ``days`` of expiry, sorted ASC, with ``linked_summary``
short strings.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]

_FE_ENV = dotenv_values(
    Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL")
        or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE
API = f"{BASE}/api"


def _login(email: str, pwd: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pwd}, timeout=15)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def h_admin():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def h_customer():
    return _login("customer@aquaterra.com")


@pytest.fixture(scope="module")
def tenant_id(h_admin):
    r = requests.get(f"{API}/auth/me", headers=h_admin, timeout=15)
    return r.json()["tenant_id"]


def _mk_contract(tid: str, cid: str, cname: str, end_offset_days: int,
                  linked_type: str = "none", linked_id=None,
                  status: str = "active") -> str:
    wid = f"TEST_pb3-w-{uuid.uuid4().hex[:8]}"
    _sync.warranty_contracts.insert_one({
        "id": wid, "tenant_id": tid,
        "customer_id": cid,
        "customer_name_snapshot": cname,
        "plan_name_snapshot": f"TEST_pb3 Plan {end_offset_days}d",
        "plan_kind_snapshot": "warranty",
        "start_date": (date.today() - timedelta(days=180)).isoformat(),
        "end_date": (date.today() + timedelta(days=end_offset_days)).isoformat(),
        "status": status,
        "linked_type": linked_type,
        "linked_id": linked_id,
    })
    return wid


@pytest.fixture()
def wty_fixtures(tenant_id):
    """Seed a customer + install job + equipment + several contracts:
       - c1 ends in 5 days (active, install-linked)
       - c2 ends in 20 days (active, equipment-linked)
       - c3 ends in 100 days (active, out of window)
       - c4 ends in 5 days (cancelled, must be excluded)
       - c5 ends in -3 days (active, already expired — excluded)
    """
    cid = f"TEST_pb3-c-{uuid.uuid4().hex[:8]}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": f"TEST_pb3_cust_{cid[-6:]}",
    })
    jid = f"TEST_pb3-j-{uuid.uuid4().hex[:8]}"
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id, "customer_id": cid,
        "title": "TEST_pb3 Install", "service_type": "Pool Install",
        "status": "completed",
    })
    eid = f"TEST_pb3-e-{uuid.uuid4().hex[:8]}"
    _sync.customer_equipment.insert_one({
        "id": eid, "tenant_id": tenant_id, "customer_id": cid,
        "equipment_type": "Heater", "brand": "AquaCal", "model": "XR-500",
        "serial_number": "SN123", "is_deleted": False,
    })
    w1 = _mk_contract(tenant_id, cid, "TEST_pb3 Cust",
                        end_offset_days=5,
                        linked_type="install", linked_id=jid)
    w2 = _mk_contract(tenant_id, cid, "TEST_pb3 Cust",
                        end_offset_days=20,
                        linked_type="equipment", linked_id=eid)
    w3 = _mk_contract(tenant_id, cid, "TEST_pb3 Cust",
                        end_offset_days=100)
    w4 = _mk_contract(tenant_id, cid, "TEST_pb3 Cust",
                        end_offset_days=5, status="cancelled")
    w5 = _mk_contract(tenant_id, cid, "TEST_pb3 Cust",
                        end_offset_days=-3)
    yield {"customer_id": cid, "install_id": jid, "equipment_id": eid,
             "w1": w1, "w2": w2, "w3": w3, "w4": w4, "w5": w5}
    _sync.warranty_contracts.delete_many(
        {"id": {"$in": [w1, w2, w3, w4, w5]}})
    _sync.customer_equipment.delete_many({"id": eid})
    _sync.jobs.delete_many({"id": jid})
    _sync.customers.delete_many({"id": cid})


class TestExpiringSoon:
    def test_returns_active_within_window_sorted_asc(self, h_admin,
                                                      wty_fixtures):
        r = requests.get(
            f"{API}/warranties/expiring-soon?days=30",
            headers=h_admin, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["days"] == 30
        ids = [it["id"] for it in body["items"]]
        # w1 (5d) + w2 (20d) present; w3/w4/w5 excluded
        assert wty_fixtures["w1"] in ids
        assert wty_fixtures["w2"] in ids
        assert wty_fixtures["w3"] not in ids
        assert wty_fixtures["w4"] not in ids
        assert wty_fixtures["w5"] not in ids
        # ASC by coverage_end — w1 before w2
        assert ids.index(wty_fixtures["w1"]) < ids.index(wty_fixtures["w2"])

    def test_linked_summary_shapes(self, h_admin, wty_fixtures):
        r = requests.get(
            f"{API}/warranties/expiring-soon?days=30",
            headers=h_admin, timeout=15,
        )
        by_id = {it["id"]: it for it in r.json()["items"]}
        w1 = by_id[wty_fixtures["w1"]]
        assert w1["linked_summary"].startswith("Install job #")
        w2 = by_id[wty_fixtures["w2"]]
        assert "Heater" in w2["linked_summary"]
        assert "AquaCal" in w2["linked_summary"]
        assert "XR-500" in w2["linked_summary"]

    def test_days_remaining_computed(self, h_admin, wty_fixtures):
        r = requests.get(
            f"{API}/warranties/expiring-soon?days=30",
            headers=h_admin, timeout=15,
        )
        by_id = {it["id"]: it for it in r.json()["items"]}
        assert by_id[wty_fixtures["w1"]]["days_remaining"] == 5
        assert by_id[wty_fixtures["w2"]]["days_remaining"] == 20

    def test_unlinked_contract_omits_summary(self, h_admin, tenant_id,
                                                wty_fixtures):
        wid = _mk_contract(tenant_id,
                             wty_fixtures["customer_id"], "TEST_pb3 Cust",
                             end_offset_days=10)
        try:
            r = requests.get(
                f"{API}/warranties/expiring-soon?days=30",
                headers=h_admin, timeout=15,
            )
            by_id = {it["id"]: it for it in r.json()["items"]}
            assert wid in by_id
            # ``linked_summary`` field must be OMITTED (not "—" / null)
            assert "linked_summary" not in by_id[wid]
        finally:
            _sync.warranty_contracts.delete_one({"id": wid})

    def test_customer_forbidden(self, h_customer):
        r = requests.get(
            f"{API}/warranties/expiring-soon?days=30",
            headers=h_customer, timeout=15,
        )
        assert r.status_code == 403

    def test_narrow_window_excludes_farther_contract(self, h_admin,
                                                       wty_fixtures):
        r = requests.get(
            f"{API}/warranties/expiring-soon?days=7",
            headers=h_admin, timeout=15,
        )
        ids = [it["id"] for it in r.json()["items"]]
        assert wty_fixtures["w1"] in ids       # 5d
        assert wty_fixtures["w2"] not in ids   # 20d

    def test_days_out_of_range_422(self, h_admin):
        r = requests.get(
            f"{API}/warranties/expiring-soon?days=0",
            headers=h_admin, timeout=15,
        )
        assert r.status_code == 422
