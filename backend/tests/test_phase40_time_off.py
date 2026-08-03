"""Phase 40 · Feb-2026 — Time-off requests, policy, and balance tests.

Follows the ``test_workforce.py`` convention: sync ``requests`` +
``pymongo``, seeded demo accounts, no async fixtures.
"""
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = (
    _FE_ENV.get("REACT_APP_BACKEND_URL")
    or _FE_ENV.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("REACT_APP_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = _BE_ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE_ENV.get("DB_NAME") or os.environ.get("DB_NAME")


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('landscaper@aquaterra.com')}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def tenant_id(db):
    return db.tenants.find_one({"slug": "aquaterra"})["id"]


@pytest.fixture(scope="module")
def tech_user(db, tenant_id):
    return db.users.find_one({"tenant_id": tenant_id, "email": "landscaper@aquaterra.com"})


# ─── Policy CRUD ────────────────────────────────────────────────

def test_policy_read_default(admin_h):
    r = requests.get(f"{API}/time-off/policy", headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["accrual_numerator"] == 1
    assert p["accrual_denominator"] == 30
    assert p["annual_cap_hours"] == 24
    assert p["waiting_period_days"] == 90


def test_policy_upsert_admin_only(admin_h, tech_h):
    payload = {"accrual_numerator": 1, "accrual_denominator": 30,
               "annual_cap_hours": 24, "waiting_period_days": 90, "active": True}
    r = requests.put(f"{API}/time-off/policy", headers=tech_h, json=payload, timeout=15)
    assert r.status_code in (401, 403), r.text
    r = requests.put(f"{API}/time-off/policy", headers=admin_h, json=payload, timeout=15)
    assert r.status_code == 200, r.text


# ─── Balance ───────────────────────────────────────────────────

def test_balance_me_shape(tech_h):
    r = requests.get(f"{API}/time-off/balance/me", headers=tech_h, timeout=15)
    assert r.status_code == 200, r.text
    b = r.json()
    for k in ("worked_hours_ytd", "accrued_hours_ytd", "used_hours_ytd",
              "available_hours", "annual_cap_hours",
              "waiting_period_remaining_days", "can_use_balance", "policy"):
        assert k in b, f"missing key {k}"


def test_balance_annual_cap(db, tenant_id, tech_user, tech_h):
    # Insert a large closed shift for the tech so accrual maxes out
    now = datetime.now(timezone.utc)
    year_start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    entry = {
        "id": "test_te_phase40_cap",
        "tenant_id": tenant_id, "user_id": tech_user["id"],
        "clock_in_at": year_start + timedelta(days=1),
        # 1000 worked hours -> 1000/30 ≈ 33.3 accrued -> capped at 24
        "clock_out_at": year_start + timedelta(days=1, hours=1000),
        "breaks": [],
    }
    db.time_entries.delete_many({"id": entry["id"]})
    db.time_entries.insert_one(entry)
    try:
        r = requests.get(f"{API}/time-off/balance/me", headers=tech_h, timeout=15)
        b = r.json()
        assert b["worked_hours_ytd"] >= 1000
        assert b["accrued_hours_ytd"] == 24  # capped
        assert b["accrued_uncapped_hours_ytd"] > 24
    finally:
        db.time_entries.delete_many({"id": entry["id"]})


# ─── Requests ───────────────────────────────────────────────────

def test_submit_request_within_balance(db, tenant_id, tech_user, tech_h):
    # Ensure lots of worked hours for the tech so balance covers 2 hrs.
    entry = {
        "id": "test_te_phase40_submit",
        "tenant_id": tenant_id, "user_id": tech_user["id"],
        "clock_in_at": datetime(datetime.now(timezone.utc).year, 1, 2, tzinfo=timezone.utc),
        "clock_out_at": datetime(datetime.now(timezone.utc).year, 1, 2, tzinfo=timezone.utc) + timedelta(hours=200),
        "breaks": [],
    }
    db.time_entries.delete_many({"id": entry["id"]})
    db.time_entries.insert_one(entry)
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    try:
        r = requests.post(f"{API}/time-off/requests", headers=tech_h,
                          json={"type": "sick", "from_date": tomorrow, "to_date": tomorrow,
                                "hours": 2, "reason": "phase40 test"}, timeout=15)
        assert r.status_code == 200, r.text
        rid = r.json()["id"]
        assert r.json()["status"] == "pending"
        # cleanup
        db.time_off_requests.delete_one({"id": rid})
    finally:
        db.time_entries.delete_many({"id": entry["id"]})


def test_submit_request_waiting_period(db, tenant_id, tech_user, tech_h):
    # Temporarily set hire_date to today so tech is inside waiting period.
    original_hire = tech_user.get("hire_date")
    db.users.update_one({"id": tech_user["id"]},
                        {"$set": {"hire_date": datetime.now(timezone.utc)}})
    try:
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
        r = requests.post(f"{API}/time-off/requests", headers=tech_h,
                          json={"type": "sick", "from_date": tomorrow, "to_date": tomorrow,
                                "hours": 1, "reason": "waiting test"}, timeout=15)
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "waiting_period"
    finally:
        db.users.update_one({"id": tech_user["id"]}, {"$set": {"hire_date": original_hire}})


def test_submit_request_insufficient_balance(db, tenant_id, tech_user, tech_h):
    # Clear all time_entries for the tech YTD → 0 available hours.
    year_start = datetime(datetime.now(timezone.utc).year, 1, 1, tzinfo=timezone.utc)
    backup = list(db.time_entries.find({"tenant_id": tenant_id, "user_id": tech_user["id"],
                                       "clock_out_at": {"$gte": year_start}}))
    db.time_entries.delete_many({"tenant_id": tenant_id, "user_id": tech_user["id"],
                                 "clock_out_at": {"$gte": year_start}})
    try:
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
        r = requests.post(f"{API}/time-off/requests", headers=tech_h,
                          json={"type": "sick", "from_date": tomorrow, "to_date": tomorrow,
                                "hours": 5, "reason": "insufficient test"}, timeout=15)
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "insufficient_balance"
    finally:
        if backup:
            for d in backup:
                d.pop("_id", None)
                db.time_entries.insert_one(d)


def test_approve_reject_cancel_lifecycle(db, tenant_id, tech_user, tech_h, admin_h):
    # Seed a worked shift → give balance
    year = datetime.now(timezone.utc).year
    entry = {
        "id": "test_te_phase40_lifecycle",
        "tenant_id": tenant_id, "user_id": tech_user["id"],
        "clock_in_at": datetime(year, 1, 3, tzinfo=timezone.utc),
        "clock_out_at": datetime(year, 1, 3, tzinfo=timezone.utc) + timedelta(hours=200),
        "breaks": [],
    }
    db.time_entries.delete_many({"id": entry["id"]})
    db.time_entries.insert_one(entry)
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat()
    created_ids = []
    try:
        # Submit two — one to approve, one to reject
        for _ in range(2):
            r = requests.post(f"{API}/time-off/requests", headers=tech_h,
                              json={"type": "sick", "from_date": tomorrow, "to_date": tomorrow,
                                    "hours": 1, "reason": "lifecycle"}, timeout=15)
            assert r.status_code == 200, r.text
            created_ids.append(r.json()["id"])

        # Approve
        rid_a = created_ids[0]
        r = requests.post(f"{API}/time-off/requests/{rid_a}/approve", headers=admin_h,
                          json={"decision_notes": "ok"}, timeout=15)
        assert r.status_code == 200
        assert r.json()["status"] == "approved"

        # Reject
        rid_r = created_ids[1]
        r = requests.post(f"{API}/time-off/requests/{rid_r}/reject", headers=admin_h,
                          json={"decision_notes": "denied"}, timeout=15)
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"

        # Tech cannot approve
        r = requests.post(f"{API}/time-off/requests/{rid_a}/approve", headers=tech_h,
                          json={"decision_notes": ""}, timeout=15)
        assert r.status_code in (401, 403, 409)

        # Cancel own approved
        r = requests.post(f"{API}/time-off/requests/{rid_a}/cancel", headers=tech_h, timeout=15)
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"
    finally:
        for rid in created_ids:
            db.time_off_requests.delete_one({"id": rid})
        db.time_entries.delete_many({"id": entry["id"]})


def test_scope_all_admin_only(tech_h):
    r = requests.get(f"{API}/time-off/requests?scope=all", headers=tech_h, timeout=15)
    assert r.status_code in (401, 403)
