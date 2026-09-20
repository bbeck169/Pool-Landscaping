"""Feb-2026 · P28 — ``GET /api/customers?is_muted=...`` filter pin.

Three assertions covering the saved-view query param:
  * ``is_muted=true``  → only muted rows visible
  * ``is_muted=false`` → only non-muted rows visible (both explicit-False
     and legacy field-missing count as non-muted; P27 only stamps
     ``is_muted`` on mute)
  * absent           → no filter on this dimension (existing behaviour)

Tech role rejected 403 (admin/manager/super_admin only).
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture
def tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one(
        {"email": "admin@aquaterra.com"})["tenant_id"]


def _seed(tid: str, *, muted: bool) -> str:
    cid = f"TEST_p28_{uuid.uuid4().hex[:8]}"
    doc = {
        "id": cid, "tenant_id": tid,
        "name": f"TEST P28 {'muted' if muted else 'live'}",
        "email": f"{cid}@example.com", "phone": "6235550100",
        "is_active": not muted,
        "created_at": "2026-06-01T09:00:00+00:00",
    }
    if muted:
        doc["is_muted"] = True
        doc["muted_at"] = "2026-06-01T10:00:00+00:00"
    _sync.customers.insert_one(doc)
    return cid


def _cleanup(ids: list[str]) -> None:
    if ids:
        _sync.customers.delete_many({"id": {"$in": ids}})


def test_is_muted_query_param_filters_correctly(admin_h, tech_h, aquaterra_tid):
    muted_id = _seed(aquaterra_tid, muted=True)
    live_id = _seed(aquaterra_tid, muted=False)
    try:
        # is_muted=true → only the muted row.
        r_true = requests.get(f"{API}/customers?is_muted=true",
                                 headers=admin_h, timeout=15)
        assert r_true.status_code == 200, r_true.text
        ids_true = {row["id"] for row in r_true.json()}
        assert muted_id in ids_true
        assert live_id not in ids_true

        # is_muted=false → only non-muted rows (includes the live seed
        # AND any pre-existing tenant customers that never had the
        # field stamped — validates the ``$exists: false`` branch).
        r_false = requests.get(f"{API}/customers?is_muted=false",
                                  headers=admin_h, timeout=15)
        assert r_false.status_code == 200, r_false.text
        ids_false = {row["id"] for row in r_false.json()}
        assert live_id in ids_false
        assert muted_id not in ids_false

        # Absent → no filter on this dimension. Both rows visible.
        r_none = requests.get(f"{API}/customers", headers=admin_h, timeout=15)
        assert r_none.status_code == 200, r_none.text
        ids_none = {row["id"] for row in r_none.json()}
        assert muted_id in ids_none
        assert live_id in ids_none

        # Tech role gets 403 when the param is present (either value).
        r_tech = requests.get(f"{API}/customers?is_muted=true",
                                 headers=tech_h, timeout=15)
        assert r_tech.status_code == 403, r_tech.text
        r_tech_f = requests.get(f"{API}/customers?is_muted=false",
                                   headers=tech_h, timeout=15)
        assert r_tech_f.status_code == 403, r_tech_f.text
        # But absent-param request still works for tech.
        r_tech_none = requests.get(f"{API}/customers",
                                       headers=tech_h, timeout=15)
        assert r_tech_none.status_code == 200
    finally:
        _cleanup([muted_id, live_id])
