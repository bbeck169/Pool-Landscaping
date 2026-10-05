"""TIMECARD-EDIT · pytest suite.

PATCH /api/workforce/timesheets/{eid} — admin/manager/owner/super_admin
edit of a time_entries row with embedded ``edits[]`` audit trail.

Follows test_workforce.py conventions (live HTTP, module-scoped
MongoClient). Cross-tenant isolation test is self-contained — it
seeds a row with a synthetic ``tenant_id`` and PATCHes with the
aquaterra admin token, expecting 404 without requiring a second
seeded admin account.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
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

_TAG = "TIMECARD_EDIT_TEST"


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


def _seed_entry(db, tenant_id, user_id, *, eid=None,
                clock_in="2026-02-15T08:00:00+00:00",
                clock_out="2026-02-15T16:00:00+00:00",
                breaks=None, duration_minutes=None, extra=None):
    eid = eid or f"{_TAG}_{datetime.now(timezone.utc).timestamp():.6f}"
    if duration_minutes is None and clock_out:
        ci = datetime.fromisoformat(clock_in.replace("Z", "+00:00"))
        co = datetime.fromisoformat(clock_out.replace("Z", "+00:00"))
        duration_minutes = round((co - ci).total_seconds() / 60.0, 2)
    doc = {
        "id": eid,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "user_name": "Mike Test",
        "job_id": f"{_TAG}_JOB",
        "job_title": "Timecard edit test",
        "clock_in_at": clock_in,
        "clock_out_at": clock_out,
        "clock_in_geo": None,
        "clock_out_geo": None,
        "out_of_geofence": False,
        "photo_url": None,
        "breaks": breaks or [],
        "duration_minutes": duration_minutes or 0,
        "mileage_miles": 0,
        "status": "submitted" if clock_out else "open",
        "notes": "",
        "created_at": clock_in,
        "_tag": _TAG,
    }
    if extra:
        doc.update(extra)
    db.time_entries.replace_one({"id": eid}, doc, upsert=True)
    return eid


def _cleanup(db):
    db.time_entries.delete_many({"_tag": _TAG})


@pytest.fixture(autouse=True)
def _per_test_cleanup(db):
    _cleanup(db)
    yield
    _cleanup(db)


def test_edit_both_times_happy_path(admin_h, db, aquaterra_id, mike_id):
    eid = _seed_entry(db, aquaterra_id, mike_id)
    r = requests.patch(
        f"{API}/workforce/timesheets/{eid}", headers=admin_h,
        json={"clock_in_at": "2026-02-15T09:00:00+00:00",
              "clock_out_at": "2026-02-15T17:30:00+00:00",
              "reason": "payroll correction"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["clock_in_at"] == "2026-02-15T09:00:00+00:00"
    assert row["clock_out_at"] == "2026-02-15T17:30:00+00:00"
    assert abs(row["duration_minutes"] - 510.0) < 0.01
    edits = row.get("edits") or []
    assert len(edits) == 1, edits
    e = edits[0]
    assert e["edited_by_role"] in ("admin", "super_admin", "owner")
    assert e["reason"] == "payroll correction"
    assert "clock_in_at" in e["changes"]
    assert e["changes"]["clock_in_at"]["from"] == "2026-02-15T08:00:00+00:00"
    assert e["changes"]["clock_in_at"]["to"] == "2026-02-15T09:00:00+00:00"
    assert "duration_minutes" in e["changes"]


def test_edit_date_only_reanchor(admin_h, db, aquaterra_id, mike_id):
    eid = _seed_entry(db, aquaterra_id, mike_id)
    r = requests.patch(
        f"{API}/workforce/timesheets/{eid}", headers=admin_h,
        json={"date": "2026-02-20"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["clock_in_at"].startswith("2026-02-20T08:00:00")
    assert row["clock_out_at"].startswith("2026-02-20T16:00:00")
    assert abs(row["duration_minutes"] - 480.0) < 0.01
    edits = row.get("edits")
    assert len(edits) == 1
    chg = edits[0]["changes"]
    assert chg["date"]["from"] == "2026-02-15"
    assert chg["date"]["to"] == "2026-02-20"


def test_edit_midnight_auto_advance_overnight(admin_h, db, aquaterra_id, mike_id):
    eid = _seed_entry(db, aquaterra_id, mike_id)
    r = requests.patch(
        f"{API}/workforce/timesheets/{eid}", headers=admin_h,
        json={"clock_in_at": "2026-02-15T22:00:00+00:00",
              "clock_out_at": "2026-02-15T06:00:00+00:00"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["clock_in_at"] == "2026-02-15T22:00:00+00:00"
    assert row["clock_out_at"] == "2026-02-16T06:00:00+00:00"
    assert abs(row["duration_minutes"] - 480.0) < 0.01


def test_edit_shift_duration_unreasonable_400(admin_h, db, aquaterra_id, mike_id):
    eid = _seed_entry(db, aquaterra_id, mike_id)
    r = requests.patch(
        f"{API}/workforce/timesheets/{eid}", headers=admin_h,
        json={"clock_in_at": "2026-02-15T02:00:00+00:00",
              "clock_out_at": "2026-02-15T00:30:00+00:00"},
        timeout=20,
    )
    assert r.status_code == 400, r.text
    assert "shift_duration_unreasonable" in r.text


def test_edit_open_shift_partial_edit_200(admin_h, db, aquaterra_id, mike_id):
    eid = _seed_entry(db, aquaterra_id, mike_id, clock_out=None,
                      duration_minutes=0)
    r = requests.patch(
        f"{API}/workforce/timesheets/{eid}", headers=admin_h,
        json={"clock_in_at": "2026-02-15T07:30:00+00:00"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["clock_in_at"] == "2026-02-15T07:30:00+00:00"
    assert row["clock_out_at"] is None
    assert row["duration_minutes"] == 0


def test_edit_open_shift_clock_out_rejected_400(admin_h, db, aquaterra_id, mike_id):
    eid = _seed_entry(db, aquaterra_id, mike_id, clock_out=None,
                      duration_minutes=0)
    r = requests.patch(
        f"{API}/workforce/timesheets/{eid}", headers=admin_h,
        json={"clock_out_at": "2026-02-15T16:00:00+00:00"},
        timeout=20,
    )
    assert r.status_code == 400, r.text
    assert "Open shift" in r.text or "clock-out" in r.text


def test_edit_no_op_short_circuit_no_audit(admin_h, db, aquaterra_id, mike_id):
    eid = _seed_entry(db, aquaterra_id, mike_id)
    r = requests.patch(
        f"{API}/workforce/timesheets/{eid}", headers=admin_h,
        json={"clock_in_at": "2026-02-15T08:00:00+00:00"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    row = r.json()
    assert row.get("edits") in (None, [])


def test_edit_paid_payroll_rejected_400(admin_h, db, aquaterra_id, mike_id):
    eid = _seed_entry(db, aquaterra_id, mike_id,
                      extra={"payroll_run_id": "PR_123",
                             "payroll_paid_at": "2026-02-16T12:00:00+00:00"})
    r = requests.patch(
        f"{API}/workforce/timesheets/{eid}", headers=admin_h,
        json={"clock_in_at": "2026-02-15T09:00:00+00:00"},
        timeout=20,
    )
    assert r.status_code == 400, r.text
    assert "paid payroll" in r.text.lower()


def test_edit_soft_deleted_404(admin_h, db, aquaterra_id, mike_id):
    eid = _seed_entry(db, aquaterra_id, mike_id,
                      extra={"deleted_at": "2026-02-16T00:00:00+00:00"})
    r = requests.patch(
        f"{API}/workforce/timesheets/{eid}", headers=admin_h,
        json={"clock_in_at": "2026-02-15T09:00:00+00:00"},
        timeout=20,
    )
    assert r.status_code == 404, r.text


def test_edit_tech_role_forbidden_403(tech_h, db, aquaterra_id, mike_id):
    eid = _seed_entry(db, aquaterra_id, mike_id)
    r = requests.patch(
        f"{API}/workforce/timesheets/{eid}", headers=tech_h,
        json={"clock_in_at": "2026-02-15T09:00:00+00:00"},
        timeout=20,
    )
    assert r.status_code == 403, r.text


def test_edit_cross_tenant_404(admin_h, db, mike_id):
    """Self-contained: seed the row under a synthetic foreign tenant_id
    so the aquaterra admin's tenant-scoped lookup 404s. Avoids depending
    on a second seeded admin account."""
    foreign_tid = f"{_TAG}_FOREIGN_TENANT"
    eid = _seed_entry(db, foreign_tid, mike_id)
    r = requests.patch(
        f"{API}/workforce/timesheets/{eid}", headers=admin_h,
        json={"clock_in_at": "2026-02-15T09:00:00+00:00"},
        timeout=20,
    )
    assert r.status_code == 404, r.text


def test_edit_reason_too_long_400(admin_h, db, aquaterra_id, mike_id):
    eid = _seed_entry(db, aquaterra_id, mike_id)
    r = requests.patch(
        f"{API}/workforce/timesheets/{eid}", headers=admin_h,
        json={"clock_in_at": "2026-02-15T09:00:00+00:00",
              "reason": "x" * 501},
        timeout=20,
    )
    assert r.status_code == 400, r.text
    assert "reason" in r.text.lower()


def test_edit_break_reanchor_matches_delta(admin_h, db, aquaterra_id, mike_id):
    eid = _seed_entry(
        db, aquaterra_id, mike_id,
        breaks=[{"start": "2026-02-15T12:00:00+00:00",
                 "end":   "2026-02-15T12:30:00+00:00"}],
    )
    r = requests.patch(
        f"{API}/workforce/timesheets/{eid}", headers=admin_h,
        json={"date": "2026-02-20"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["clock_in_at"].startswith("2026-02-20T")
    br = row["breaks"][0]
    assert br["start"] == "2026-02-20T12:00:00+00:00"
    assert br["end"] == "2026-02-20T12:30:00+00:00"
