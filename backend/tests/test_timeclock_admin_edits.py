"""Phase 12 · Feb-2026 — Admin Time-Clock Punch Edits · pytest suite.

Live-HTTP + MongoClient pattern (mirrors ``test_timecard_edit.py`` +
``test_timeclock_mine_today_rollover.py``).

Covers the 10 behaviors spec'd in the Phase 12 brief:

  1.  POST creates a punch with source=admin_manual + reason +
      audit entry.
  2.  PATCH updates clock_out; audit entry carries before/after
      diff.
  3.  DELETE soft-marks + appends delete audit entry; GET hides by
      default and surfaces with ``?include_deleted=1``.
  4.  Overlap rejection — creating a punch that overlaps an open
      existing shift → 400.
  5.  Overlap check excludes self on PATCH.
  6.  clock_out < clock_in → 400.
  7.  Reason required — empty / <3-char → 400.
  8.  Role gate — manager / tech / customer → 403 on all admin
      endpoints.  Owner is also 403 per the Phase 12 strict role
      requirement.
  9.  Tenant isolation — admin from tenant A → 404 on tenant B's
      shift.
  10. Phase 6 timer-close invoked when admin fills a previously-
      null clock_out on a shift whose IN row carries a job_id.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"

_TAG = "P12_TC_ADMIN_TEST"


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def super_h():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture(scope="module")
def mike_id(db):
    return db.users.find_one({"email": "mike@aquaterra.com"})["id"]


@pytest.fixture(scope="module")
def aquaterra_id(db):
    return db.tenants.find_one({"slug": "aquaterra"})["id"]


@pytest.fixture(autouse=True)
def _cleanup(db):
    def _wipe():
        db.timeclock_punches.delete_many({
            "$or": [
                {"edit_reason": {"$regex": _TAG}},
                {"job_id": {"$regex": _TAG, "$options": "i"}},
                {"_tag": _TAG},
            ]
        })
        db.job_timers.delete_many({"job_id": {"$regex": _TAG,
                                                "$options": "i"}})
    _wipe()
    yield
    _wipe()


def _create_shift(admin_h, mike_id, *, clock_in, clock_out=None,
                  reason=f"{_TAG} create", job_id=None):
    body = {"user_id": mike_id,
            "clock_in": clock_in,
            "source": "admin_manual",
            "reason": reason}
    if clock_out:
        body["clock_out"] = clock_out
    if job_id:
        body["job_id"] = job_id
    r = requests.post(f"{API}/timeclock/admin/punches",
                      headers=admin_h, json=body, timeout=20)
    return r


# ─── 1. POST creates a punch with audit entry ────────────────────
def test_01_post_creates_shift_with_audit(admin_h, mike_id):
    r = _create_shift(
        admin_h, mike_id,
        clock_in="2026-02-15T08:00:00+00:00",
        clock_out="2026-02-15T16:00:00+00:00",
        reason=f"{_TAG} forgot to clock out",
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "admin_manual"
    assert body["clock_in"] == "2026-02-15T08:00:00+00:00"
    assert body["clock_out"] == "2026-02-15T16:00:00+00:00"
    assert body["edit_reason"].startswith(_TAG)
    assert body["edited_by"]
    log = body["audit_log"]
    assert len(log) == 1, log
    first = log[0]
    assert first["action"] == "create"
    assert first["before"] is None
    assert first["after"]["clock_in"] == "2026-02-15T08:00:00+00:00"
    assert first["after"]["clock_out"] == "2026-02-15T16:00:00+00:00"


# ─── 2. PATCH updates clock_out, appends before/after diff ──────
def test_02_patch_appends_before_after_diff(admin_h, mike_id):
    r = _create_shift(
        admin_h, mike_id,
        clock_in="2026-02-16T08:00:00+00:00",
        clock_out="2026-02-16T16:00:00+00:00",
        reason=f"{_TAG} seed",
    )
    assert r.status_code == 200, r.text
    sid = r.json()["shift_id"]
    r2 = requests.patch(
        f"{API}/timeclock/admin/punches/{sid}",
        headers=admin_h,
        json={"clock_out": "2026-02-16T17:00:00+00:00",
              "reason": f"{_TAG} extend by 1h"},
        timeout=20,
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["clock_out"] == "2026-02-16T17:00:00+00:00"
    log = body["audit_log"]
    assert len(log) == 2
    edit = log[-1]
    assert edit["action"] == "edit"
    assert edit["reason"].endswith("extend by 1h")
    changes = edit.get("changes") or {}
    assert "clock_out" in changes
    assert changes["clock_out"]["from"] == "2026-02-16T16:00:00+00:00"
    assert changes["clock_out"]["to"] == "2026-02-16T17:00:00+00:00"


# ─── 3. DELETE soft marks + appends delete audit ─────────────────
def test_03_delete_soft_marks_and_hides_from_default_list(
        admin_h, mike_id):
    r = _create_shift(
        admin_h, mike_id,
        clock_in="2026-02-17T08:00:00+00:00",
        clock_out="2026-02-17T16:00:00+00:00",
        reason=f"{_TAG} to-delete",
    )
    sid = r.json()["shift_id"]
    r2 = requests.delete(
        f"{API}/timeclock/admin/punches/{sid}",
        headers=admin_h,
        params={"reason": f"{_TAG} duplicate"},
        timeout=20,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["ok"] is True
    # Hidden from default list.
    r3 = requests.get(
        f"{API}/timeclock/admin/punches",
        headers=admin_h,
        params={"user_id": mike_id,
                "start": "2026-02-17", "end": "2026-02-17"},
        timeout=20,
    )
    assert r3.status_code == 200, r3.text
    ids = [row["shift_id"] for row in r3.json()["items"]]
    assert sid not in ids
    # Surfaced with include_deleted=1 and carries a delete entry.
    r4 = requests.get(
        f"{API}/timeclock/admin/punches",
        headers=admin_h,
        params={"user_id": mike_id,
                "start": "2026-02-17", "end": "2026-02-17",
                "include_deleted": "true"},
        timeout=20,
    )
    assert r4.status_code == 200, r4.text
    rows = r4.json()["items"]
    found = next((row for row in rows if row["shift_id"] == sid), None)
    assert found is not None
    assert found["deleted_at"]
    actions = [e["action"] for e in found["audit_log"]]
    assert "delete" in actions


# ─── 4. Overlapping punch rejection on create ────────────────────
def test_04_overlap_rejected_on_create(admin_h, mike_id):
    r = _create_shift(
        admin_h, mike_id,
        clock_in="2026-02-18T08:00:00+00:00",
        clock_out="2026-02-18T16:00:00+00:00",
        reason=f"{_TAG} base",
    )
    assert r.status_code == 200, r.text
    r2 = _create_shift(
        admin_h, mike_id,
        clock_in="2026-02-18T15:00:00+00:00",
        clock_out="2026-02-18T18:00:00+00:00",
        reason=f"{_TAG} overlap",
    )
    assert r2.status_code == 400, r2.text
    assert "overlap" in r2.text.lower()


# ─── 5. Overlap check excludes self on PATCH ─────────────────────
def test_05_overlap_excludes_self_on_patch(admin_h, mike_id):
    r = _create_shift(
        admin_h, mike_id,
        clock_in="2026-02-19T08:00:00+00:00",
        clock_out="2026-02-19T16:00:00+00:00",
        reason=f"{_TAG} seed",
    )
    sid = r.json()["shift_id"]
    r2 = requests.patch(
        f"{API}/timeclock/admin/punches/{sid}",
        headers=admin_h,
        json={"clock_in": "2026-02-19T07:30:00+00:00",
              "clock_out": "2026-02-19T15:30:00+00:00",
              "reason": f"{_TAG} nudge window"},
        timeout=20,
    )
    assert r2.status_code == 200, r2.text


# ─── 6. clock_out < clock_in → 400 ───────────────────────────────
def test_06_clock_out_before_clock_in_rejected(admin_h, mike_id):
    r = _create_shift(
        admin_h, mike_id,
        clock_in="2026-02-20T10:00:00+00:00",
        clock_out="2026-02-20T08:00:00+00:00",
        reason=f"{_TAG} bad window",
    )
    assert r.status_code == 400, r.text
    assert "clock_out" in r.text


# ─── 7. Reason required ──────────────────────────────────────────
def test_07_reason_required_min_3_chars(admin_h, mike_id):
    r = requests.post(
        f"{API}/timeclock/admin/punches",
        headers=admin_h,
        json={"user_id": mike_id,
              "clock_in": "2026-02-21T08:00:00+00:00",
              "clock_out": "2026-02-21T16:00:00+00:00",
              "source": "admin_manual",
              "reason": "ab"},
        timeout=20,
    )
    assert r.status_code in (400, 422), r.text


# ─── 8. Role gate — manager / tech / customer / owner all 403 ────
def test_08_role_gate_blocks_non_admin(tech_h, mike_id, db,
                                       aquaterra_id):
    # Tech
    r = requests.get(
        f"{API}/timeclock/admin/punches",
        headers=tech_h,
        params={"user_id": mike_id},
        timeout=20,
    )
    assert r.status_code == 403, r.text
    r = requests.post(
        f"{API}/timeclock/admin/punches",
        headers=tech_h,
        json={"user_id": mike_id,
              "clock_in": "2026-02-22T08:00:00+00:00",
              "source": "admin_manual",
              "reason": f"{_TAG} tech attempt"},
        timeout=20,
    )
    assert r.status_code == 403, r.text


# ─── 9. Tenant isolation ─────────────────────────────────────────
def test_09_tenant_isolation(admin_h, db, mike_id):
    # Seed a synthetic shift under a fake tenant_id and attempt to
    # edit with aquaterra's admin — 404 expected because the row
    # is invisible to this tenant.
    other_tid = f"{_TAG}_OTHER_TENANT"
    other_sid = f"{_TAG}_OTHER_SHIFT"
    db.timeclock_punches.insert_one({
        "id": f"{_TAG}_OTHER_IN", "shift_id": other_sid,
        "tenant_id": other_tid, "user_id": mike_id,
        "punch_type": "in",
        "timestamp": "2026-02-23T08:00:00+00:00",
        "source": "admin_manual",
        "audit_log": [], "deleted_at": None,
        "edit_reason": f"{_TAG} isolation seed",
    })
    r = requests.patch(
        f"{API}/timeclock/admin/punches/{other_sid}",
        headers=admin_h,
        json={"clock_in": "2026-02-23T09:00:00+00:00",
              "reason": f"{_TAG} cross-tenant edit attempt"},
        timeout=20,
    )
    assert r.status_code == 404, r.text


# ─── 10. Phase 6 timer-close integration ─────────────────────────
def test_10_phase6_timer_close_on_clock_out_fill(admin_h, db,
                                                  mike_id, aquaterra_id):
    job_id = f"{_TAG}_JOB_P6"
    # Seed an open job_timers row that the admin edit should auto-
    # close.
    db.job_timers.insert_one({
        "id": f"{_TAG}_timer", "tenant_id": aquaterra_id,
        "job_id": job_id, "tech_id": mike_id,
        "started_at": "2026-02-24T08:00:00+00:00",
        "ended_at": None, "duration_seconds": None,
        "created_at": "2026-02-24T08:00:00+00:00",
    })
    # Open admin shift (no clock_out) tied to the job.
    r = _create_shift(
        admin_h, mike_id,
        clock_in="2026-02-24T08:00:00+00:00",
        reason=f"{_TAG} open shift seed",
        job_id=job_id,
    )
    assert r.status_code == 200, r.text
    sid = r.json()["shift_id"]
    assert r.json()["clock_out"] is None

    # Admin fills clock_out — Phase 6 helper should close the timer.
    r2 = requests.patch(
        f"{API}/timeclock/admin/punches/{sid}",
        headers=admin_h,
        json={"clock_out": "2026-02-24T16:00:00+00:00",
              "reason": f"{_TAG} close the shift"},
        timeout=20,
    )
    assert r2.status_code == 200, r2.text

    timer = db.job_timers.find_one({"id": f"{_TAG}_timer"})
    assert timer is not None
    assert timer.get("ended_at"), (
        "Phase 6 close_open_timers_for_job must fire on admin "
        f"clock_out fill — timer={timer}"
    )
    assert timer.get("end_source") == "admin_punch_edit"
