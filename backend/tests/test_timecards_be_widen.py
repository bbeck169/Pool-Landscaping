"""TIMECARDS-BE-WIDEN · pytest suite.

Verifies the 3 ``/time-entries`` endpoints widened from
``require_admin`` to ``require_admin_or_manager``:

  * GET  /api/time-entries
  * POST /api/time-entries/bulk-delete
  * POST /api/time-entries/bulk-update

Positive: a manager-role user can hit all three.
Negative: a technician-role user still 403s on all three.
"""
import os
import pytest
import requests
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from pymongo import MongoClient

_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = (
    _FE_ENV.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = _BE_ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE_ENV.get("DB_NAME") or os.environ.get("DB_NAME")

_TAG = "TIMECARDS_BE_WIDEN_TEST"


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def manager_h():
    return {"Authorization": f"Bearer {_login('manager@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def aquaterra_id(db):
    return db.tenants.find_one({"slug": "aquaterra"})["id"]


@pytest.fixture(scope="module")
def mike_id(db):
    return db.users.find_one({"email": "mike@aquaterra.com"})["id"]


def _seed_entry(db, tenant_id, user_id, suffix: str,
                is_approved: bool = False):
    eid = f"{_TAG}_{suffix}"
    doc = {
        "id": eid,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "user_name": "Mike Tech (BE-WIDEN)",
        "job_id": f"{_TAG}_JOB",
        "job_title": "Timecards BE-widen test",
        "clock_in_at": "2026-02-15T08:00:00+00:00",
        "clock_out_at": "2026-02-15T16:00:00+00:00",
        "breaks": [],
        "duration_minutes": 480,
        "mileage_miles": 0,
        "status": "submitted",
        "out_of_geofence": False,
        "created_at": "2026-02-15T08:00:00+00:00",
        "is_approved": is_approved,
        "_tag": _TAG,
    }
    db.time_entries.replace_one({"id": eid}, doc, upsert=True)
    return eid


def _cleanup(db):
    db.time_entries.delete_many({"_tag": _TAG})


@pytest.fixture(autouse=True)
def _per_test_cleanup(db):
    _cleanup(db)
    yield
    _cleanup(db)


def test_timecards_be_widen_manager_list_200(manager_h, db, aquaterra_id, mike_id):
    _seed_entry(db, aquaterra_id, mike_id, "LIST_1")
    _seed_entry(db, aquaterra_id, mike_id, "LIST_2")
    r = requests.get(f"{API}/time-entries", headers=manager_h, timeout=30)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    tagged = [row for row in rows if row.get("_tag") == _TAG]
    assert len(tagged) >= 2, f"expected >= 2 seeded rows, got {len(tagged)}"


def test_timecards_be_widen_manager_bulk_update_200(manager_h, db, aquaterra_id, mike_id):
    eid1 = _seed_entry(db, aquaterra_id, mike_id, "UPD_1", is_approved=False)
    eid2 = _seed_entry(db, aquaterra_id, mike_id, "UPD_2", is_approved=False)
    r = requests.post(
        f"{API}/time-entries/bulk-update",
        headers=manager_h,
        json={"ids": [eid1, eid2], "patch": {"is_approved": True}},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    for eid in (eid1, eid2):
        doc = db.time_entries.find_one({"id": eid}, {"is_approved": 1})
        assert doc["is_approved"] is True


def test_timecards_be_widen_manager_bulk_delete_200(manager_h, db, aquaterra_id, mike_id):
    eid = _seed_entry(db, aquaterra_id, mike_id, "DEL_1")
    r = requests.post(
        f"{API}/time-entries/bulk-delete",
        headers=manager_h,
        json={"ids": [eid]},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    doc = db.time_entries.find_one({"id": eid}, {"deleted_at": 1})
    assert doc is not None
    assert doc.get("deleted_at") is not None


def test_timecards_be_widen_tech_still_403_list(tech_h, db, aquaterra_id, mike_id):
    _seed_entry(db, aquaterra_id, mike_id, "TLIST")
    r = requests.get(f"{API}/time-entries", headers=tech_h, timeout=30)
    assert r.status_code == 403, r.text


def test_timecards_be_widen_tech_still_403_bulk_update(tech_h, db, aquaterra_id, mike_id):
    eid = _seed_entry(db, aquaterra_id, mike_id, "TUPD")
    r = requests.post(
        f"{API}/time-entries/bulk-update",
        headers=tech_h,
        json={"ids": [eid], "patch": {"is_approved": True}},
        timeout=30,
    )
    assert r.status_code == 403, r.text


def test_timecards_be_widen_tech_still_403_bulk_delete(tech_h, db, aquaterra_id, mike_id):
    eid = _seed_entry(db, aquaterra_id, mike_id, "TDEL")
    r = requests.post(
        f"{API}/time-entries/bulk-delete",
        headers=tech_h,
        json={"ids": [eid]},
        timeout=30,
    )
    assert r.status_code == 403, r.text
