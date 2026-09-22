"""Phase P18 · Feb-2026 — Pause a recurring template ⇒ auto-cancel
future ``pending`` / ``scheduled`` visits + write ``deletion_audit``
rows with a shared ``bulk_op_id``.

Acceptance:
  1. Pausing a template flips every FUTURE ``pending`` / ``scheduled``
     child job to ``status="cancelled"``, stamps ``cancelled_reason
     = "recurring_paused"``.
  2. Past visits (``scheduled_date < today``) are NEVER touched.
  3. Non-pending / non-scheduled visits (``completed``, ``in_progress``,
     ``cancelled``, ``on_hold``) are NEVER touched.
  4. The PATCH response body carries ``cancelled_visit_count`` —
     matches the Mongo modified_count.
  5. One ``deletion_audit`` row per affected job, all sharing a
     single ``bulk_op_id``.  ``resource_type == "job"``,
     ``deletion_reason == "recurring_paused"``.
  6. Idempotent: a second PATCH ``is_active=false`` on an already-
     paused template does NOT re-cancel anything (True→False
     transition guard).
  7. Resume (``is_active=false → true``) does NOT re-cancel anything.
  8. Tenant isolation: pausing tenant A's template never touches
     tenant B's visits — even if the shared ``recurring_template_id``
     happens to collide (defense in depth via tenant scope).
  9. Both storage shapes are honoured — visits stored with
     ``scheduled_date`` (YYYY-MM-DD; the shape the recurring
     generator uses) AND visits stored with ``scheduled_start``
     (ISO datetime; the shape manual scheduling uses) both get
     cancelled when in the future.

Every seeded job uses a DISTINCT ``scheduled_date`` value so the
``(recurring_template_id, scheduled_date)`` unique index — set up by
``routers/recurring_jobs.py::_ensure_indexes`` — never fires during
setup.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_h() -> dict:
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def admin_tid(dbc) -> str:
    u = dbc.users.find_one({"email": "admin@aquaterra.com"},
                            {"_id": 0, "tenant_id": 1})
    assert u and u.get("tenant_id"), "seed admin missing tenant_id"
    return u["tenant_id"]


# ─────────────────────────────────────────────────────────────────────
# Helpers.  Each seeded job takes a distinct integer day-offset so the
# ``(recurring_template_id, scheduled_date)`` unique index never fires.
# ─────────────────────────────────────────────────────────────────────
def _seed_template(dbc, tenant_id: str, *, is_active: bool = True) -> str:
    tid = f"TEST-p18pause-tpl-{uuid.uuid4().hex[:8]}"
    dbc.recurring_job_templates.insert_one({
        "id": tid,
        "tenant_id": tenant_id,
        "customer_id": f"TEST-p18pause-cust-{uuid.uuid4().hex[:6]}",
        "frequency": "weekly",
        "day_of_week": 0,
        "start_date": date.today().isoformat(),
        "price_cents": 12000,
        "is_active": is_active,
        "active": is_active,
        "created_at": "2026-01-01T00:00:00+00:00",
    })
    return tid


def _iso_off(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _seed_job(
    dbc,
    tenant_id: str,
    tpl_id: str,
    *,
    day_offset: int | None,
    status: str,
    scheduled_start: str | None = None,
) -> str:
    jid = f"TEST-p18pause-job-{uuid.uuid4().hex[:8]}"
    doc: dict = {
        "id": jid,
        "tenant_id": tenant_id,
        "recurring_template_id": tpl_id,
        "status": status,
        "title": "P18 pause fixture",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    if day_offset is not None:
        doc["scheduled_date"] = _iso_off(day_offset)
    if scheduled_start is not None:
        doc["scheduled_start"] = scheduled_start
    dbc.jobs.insert_one(doc)
    return jid


def _pause_template(admin_h: dict, tpl_id: str) -> dict:
    """PATCH ``is_active=false`` — mirrors the wire contract the
    UI's ``togglePause`` handler sends (both keys)."""
    r = requests.patch(
        f"{API}/recurring-jobs/{tpl_id}",
        headers=admin_h,
        json={"is_active": False, "active": False},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def _resume_template(admin_h: dict, tpl_id: str) -> dict:
    r = requests.patch(
        f"{API}/recurring-jobs/{tpl_id}",
        headers=admin_h,
        json={"is_active": True, "active": True},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


# ═════════════════════════════════════════════════════════════════════
# Acceptance 1 · Pausing cancels every FUTURE pending / scheduled
# visit; past + non-eligible visits stay untouched.
# ═════════════════════════════════════════════════════════════════════
def test_pause_cancels_future_pending_and_scheduled_only(admin_h, admin_tid, dbc):
    tpl_id = _seed_template(dbc, admin_tid, is_active=True)

    # Past visits (yesterday / -2d) — MUST survive.
    past_scheduled = _seed_job(dbc, admin_tid, tpl_id,
                                 day_offset=-1, status="scheduled")
    past_completed = _seed_job(dbc, admin_tid, tpl_id,
                                 day_offset=-2, status="completed")

    # Future eligible (+1d, +2d) — MUST be cancelled.
    future_scheduled = _seed_job(dbc, admin_tid, tpl_id,
                                   day_offset=1, status="scheduled")
    future_pending = _seed_job(dbc, admin_tid, tpl_id,
                                 day_offset=2, status="pending")

    # Future non-eligible (+3d..+6d) — MUST survive.
    future_completed = _seed_job(dbc, admin_tid, tpl_id,
                                   day_offset=3, status="completed")
    future_cancelled = _seed_job(dbc, admin_tid, tpl_id,
                                   day_offset=4, status="cancelled")
    future_on_hold = _seed_job(dbc, admin_tid, tpl_id,
                                 day_offset=5, status="on_hold")
    future_in_progress = _seed_job(dbc, admin_tid, tpl_id,
                                     day_offset=6, status="in_progress")

    _all_seeded = [past_scheduled, past_completed,
                    future_scheduled, future_pending,
                    future_completed, future_cancelled,
                    future_on_hold, future_in_progress]

    try:
        body = _pause_template(admin_h, tpl_id)
        # Response contract — additive field with the modified count.
        assert body.get("cancelled_visit_count") == 2, body
        # Future eligible → cancelled with the correct reason.
        for jid in (future_scheduled, future_pending):
            j = dbc.jobs.find_one({"id": jid})
            assert j["status"] == "cancelled", (jid, j)
            assert j["cancelled_reason"] == "recurring_paused", j
            assert j.get("cancelled_at"), j
        # Past + non-eligible → untouched.
        for jid, expected in [
            (past_scheduled, "scheduled"),
            (past_completed, "completed"),
            (future_completed, "completed"),
            (future_cancelled, "cancelled"),
            (future_on_hold, "on_hold"),
            (future_in_progress, "in_progress"),
        ]:
            j = dbc.jobs.find_one({"id": jid})
            assert j["status"] == expected, (jid, j)
            assert j.get("cancelled_reason") != "recurring_paused", j
    finally:
        dbc.jobs.delete_many({"id": {"$in": _all_seeded}})
        dbc.recurring_job_templates.delete_one({"id": tpl_id})
        dbc.deletion_audit.delete_many({"resource_id": {"$in": _all_seeded}})


# ═════════════════════════════════════════════════════════════════════
# Acceptance 2 · deletion_audit is written per affected job with a
# SHARED bulk_op_id, resource_type="job", reason="recurring_paused".
# ═════════════════════════════════════════════════════════════════════
def test_pause_writes_deletion_audit_shared_bulk_op_id(admin_h, admin_tid, dbc):
    tpl_id = _seed_template(dbc, admin_tid, is_active=True)
    j1 = _seed_job(dbc, admin_tid, tpl_id,
                    day_offset=1, status="scheduled")
    j2 = _seed_job(dbc, admin_tid, tpl_id,
                    day_offset=2, status="pending")
    try:
        _pause_template(admin_h, tpl_id)
        rows = list(dbc.deletion_audit.find(
            {"resource_id": {"$in": [j1, j2]}},
            {"_id": 0},
        ))
        assert len(rows) == 2, rows
        bulk_ids = {r.get("bulk_op_id") for r in rows}
        assert len(bulk_ids) == 1, bulk_ids
        assert None not in bulk_ids
        for r in rows:
            assert r["resource_type"] == "job", r
            assert r["deletion_reason"] == "recurring_paused", r
            assert r["tenant_id"] == admin_tid, r
            # Snapshot carries the PRE-flip status.
            snap_status = (r.get("snapshot") or {}).get("status")
            assert snap_status in ("pending", "scheduled"), r
    finally:
        dbc.jobs.delete_many({"id": {"$in": [j1, j2]}})
        dbc.recurring_job_templates.delete_one({"id": tpl_id})
        dbc.deletion_audit.delete_many({"resource_id": {"$in": [j1, j2]}})


# ═════════════════════════════════════════════════════════════════════
# Acceptance 3 · No-op when the template has no future visits.
# ═════════════════════════════════════════════════════════════════════
def test_pause_is_noop_when_no_future_visits(admin_h, admin_tid, dbc):
    tpl_id = _seed_template(dbc, admin_tid, is_active=True)
    only_past = _seed_job(dbc, admin_tid, tpl_id,
                            day_offset=-1, status="scheduled")
    try:
        body = _pause_template(admin_h, tpl_id)
        assert body.get("cancelled_visit_count") == 0, body
        # No audit rows written for the past visit.
        assert dbc.deletion_audit.find_one(
            {"resource_id": only_past}
        ) is None
    finally:
        dbc.jobs.delete_one({"id": only_past})
        dbc.recurring_job_templates.delete_one({"id": tpl_id})


# ═════════════════════════════════════════════════════════════════════
# Acceptance 4 · Idempotent — pausing an already-paused template
# does NOT re-cancel anything (True→False transition gate).
# ═════════════════════════════════════════════════════════════════════
def test_pause_is_idempotent_on_already_paused_template(
    admin_h, admin_tid, dbc,
):
    tpl_id = _seed_template(dbc, admin_tid, is_active=True)
    j1 = _seed_job(dbc, admin_tid, tpl_id,
                    day_offset=1, status="scheduled")
    try:
        body_a = _pause_template(admin_h, tpl_id)
        assert body_a.get("cancelled_visit_count") == 1, body_a
        # Re-scheduled job appears (someone recreated it manually)
        # on a DIFFERENT date to avoid the unique index collision
        # with the now-cancelled j1.
        j2 = _seed_job(dbc, admin_tid, tpl_id,
                        day_offset=3, status="scheduled")
        try:
            body_b = _pause_template(admin_h, tpl_id)
            # No transition happened (already False → False), so no
            # side-effect fires.
            assert body_b.get("cancelled_visit_count") == 0, body_b
            # The newly-added job is UNTOUCHED.
            j2_doc = dbc.jobs.find_one({"id": j2})
            assert j2_doc["status"] == "scheduled", j2_doc
        finally:
            dbc.jobs.delete_one({"id": j2})
            dbc.deletion_audit.delete_many({"resource_id": j2})
    finally:
        dbc.jobs.delete_many({"id": j1})
        dbc.recurring_job_templates.delete_one({"id": tpl_id})
        dbc.deletion_audit.delete_many({"resource_id": j1})


# ═════════════════════════════════════════════════════════════════════
# Acceptance 5 · Resume (False → True) never cancels anything and
# the response carries cancelled_visit_count=0.
# ═════════════════════════════════════════════════════════════════════
def test_resume_does_not_cancel_anything(admin_h, admin_tid, dbc):
    tpl_id = _seed_template(dbc, admin_tid, is_active=True)
    j1 = _seed_job(dbc, admin_tid, tpl_id,
                    day_offset=1, status="scheduled")
    try:
        _pause_template(admin_h, tpl_id)
        # Manually add a future visit AFTER the pause (different date
        # to bypass the unique index against the cancelled j1).
        j2 = _seed_job(dbc, admin_tid, tpl_id,
                        day_offset=4, status="scheduled")
        try:
            body = _resume_template(admin_h, tpl_id)
            assert body.get("cancelled_visit_count") == 0, body
            # The manually-added visit survives.
            j2_doc = dbc.jobs.find_one({"id": j2})
            assert j2_doc["status"] == "scheduled", j2_doc
        finally:
            dbc.jobs.delete_one({"id": j2})
            dbc.deletion_audit.delete_many({"resource_id": j2})
    finally:
        dbc.jobs.delete_many({"id": j1})
        dbc.recurring_job_templates.delete_one({"id": tpl_id})
        dbc.deletion_audit.delete_many({"resource_id": j1})


# ═════════════════════════════════════════════════════════════════════
# Acceptance 6 · Tenant isolation — pausing tenant A never touches
# tenant B's visits (even ones tied to a same-id template).
# ═════════════════════════════════════════════════════════════════════
def test_pause_is_tenant_scoped(admin_h, admin_tid, dbc):
    # Provision a throwaway tenant and seed a visit against it that
    # shares the SAME recurring_template_id as the tenant-A template.
    # The tenant filter must still keep them apart.
    other_tid = f"TEST-p18pause-other-{uuid.uuid4().hex[:8]}"
    dbc.tenants.insert_one({
        "id": other_tid, "name": "P18 · Other Tenant",
        "slug": f"p18pause-other-{other_tid}", "active": True,
    })

    tpl_id = _seed_template(dbc, admin_tid, is_active=True)
    tomorrow = _iso_off(1)

    # Tenant-A visit — MUST be cancelled.
    j_a = _seed_job(dbc, admin_tid, tpl_id,
                     day_offset=1, status="scheduled")
    # Tenant-B visit tied to the SAME recurring_template_id — MUST
    # survive because it belongs to a different tenant.  The unique
    # index is on ``(recurring_template_id, scheduled_date)`` which
    # WOULD collide with j_a; use a 2-day offset to keep them apart.
    j_b_id = f"TEST-p18pause-job-{uuid.uuid4().hex[:8]}"
    dbc.jobs.insert_one({
        "id": j_b_id,
        "tenant_id": other_tid,
        "recurring_template_id": tpl_id,
        "status": "scheduled",
        "scheduled_date": _iso_off(2),
        "title": "other-tenant fixture",
    })

    try:
        _pause_template(admin_h, tpl_id)
        # A cancelled.
        assert dbc.jobs.find_one({"id": j_a})["status"] == "cancelled"
        # B untouched.
        assert dbc.jobs.find_one({"id": j_b_id})["status"] == "scheduled"
        # No deletion_audit row for tenant-B's job.
        assert dbc.deletion_audit.find_one({"resource_id": j_b_id}) is None
    finally:
        dbc.jobs.delete_many({"id": {"$in": [j_a, j_b_id]}})
        dbc.recurring_job_templates.delete_one({"id": tpl_id})
        dbc.deletion_audit.delete_many({"resource_id": {"$in": [j_a, j_b_id]}})
        dbc.tenants.delete_one({"id": other_tid})


# ═════════════════════════════════════════════════════════════════════
# Acceptance 7 · Both storage shapes are handled — visits stored
# with ``scheduled_date`` AND visits stored with ``scheduled_start``
# are both cancelled when in the future.
# ═════════════════════════════════════════════════════════════════════
def test_pause_matches_both_scheduled_date_and_scheduled_start(
    admin_h, admin_tid, dbc,
):
    tpl_id = _seed_template(dbc, admin_tid, is_active=True)
    # A future datetime with NO scheduled_date field — mirrors a
    # manually-created job with a specific start time.
    tomorrow_dt = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    # Visit with only scheduled_date (recurring-generator shape).
    j_date = _seed_job(dbc, admin_tid, tpl_id,
                        day_offset=1, status="scheduled")
    # Visit with only scheduled_start (manual-scheduling shape).
    # ``day_offset=None`` skips setting scheduled_date so this shape
    # is faithful.
    j_dt = _seed_job(dbc, admin_tid, tpl_id,
                      day_offset=None, status="pending",
                      scheduled_start=tomorrow_dt)

    try:
        body = _pause_template(admin_h, tpl_id)
        assert body.get("cancelled_visit_count") == 2, body
        for jid in (j_date, j_dt):
            j = dbc.jobs.find_one({"id": jid})
            assert j["status"] == "cancelled", (jid, j)
            assert j["cancelled_reason"] == "recurring_paused", j
    finally:
        dbc.jobs.delete_many({"id": {"$in": [j_date, j_dt]}})
        dbc.recurring_job_templates.delete_one({"id": tpl_id})
        dbc.deletion_audit.delete_many(
            {"resource_id": {"$in": [j_date, j_dt]}}
        )
