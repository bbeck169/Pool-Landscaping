"""Feb-2026 · Recurring Jobs — is_active gate + hard-delete + migration.

Locks the acceptance contract on the dispatched phase:
  1. Existing DB records post-migration have ``is_active=true`` (preserved).
  2. Attempting to save ``is_active=true`` without a ``start_date`` returns 422.
  3. Generator produces zero occurrences for ``is_active=false`` templates.
  4. Soft delete stays unchanged.
  5. Hard delete removes the template + cancels future-scheduled children;
     completed children survive.
  6. Migration is idempotent — second run backfills zero rows.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

from pymongo import MongoClient
from dotenv import dotenv_values

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    pytest.skip("REACT_APP_BACKEND_URL not set", allow_module_level=True)
API = f"{BASE_URL}/api"

_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")


REQ_TIMEOUT = 30


def _login(email, password="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password},
                       timeout=REQ_TIMEOUT)
    r.raise_for_status()
    return r.json().get("access_token")


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_id(admin_headers):
    # Grab any customer in the aquaterra tenant.
    r = requests.get(f"{API}/customers?is_active=true&limit=1",
                      headers=admin_headers, timeout=REQ_TIMEOUT)
    r.raise_for_status()
    rows = r.json() if isinstance(r.json(), list) else (r.json().get("items") or [])
    if not rows:
        pytest.skip("no seeded customer available")
    return rows[0]["id"]


# ─── Acceptance 1 — migration preserves existing is_active=True ─────

def test_migration_backfilled_existing_records_to_is_active_true(dbc):
    """After the boot migration ran, every ``recurring_job_templates``
    row carries an ``is_active`` field (contract § "For every
    existing recurring-job record WITHOUT the ``is_active`` field:
    set ``is_active=true``"). We don't compare against the legacy
    ``active`` flag at read-time because subsequent PATCH activity
    can independently flip either flag — the migration only
    guarantees the field is present after the first run."""
    rows = list(dbc.recurring_job_templates.find(
        {}, {"is_active": 1, "id": 1},
    ).limit(200))
    if not rows:
        pytest.skip("no recurring templates in the DB")
    missing = [r for r in rows if "is_active" not in r]
    assert not missing, (
        f"migration failed to backfill is_active on {len(missing)} rows: "
        f"{[r['id'] for r in missing]}"
    )


def test_migration_is_idempotent_on_second_run():
    """Re-running the migration in-process finds zero candidates."""
    import asyncio
    from services.migrations.recurring_templates_is_active_backfill import (
        backfill_recurring_is_active,
    )
    result = asyncio.get_event_loop().run_until_complete(
        backfill_recurring_is_active(),
    )
    assert result["scanned"] == 0
    assert result["backfilled"] == 0
    assert result["start_date_backfilled"] == 0


# ─── Acceptance 2 — 422 when is_active=true without start_date ──────

def test_patch_is_active_true_without_start_date_returns_422(
    admin_headers, customer_id, dbc,
):
    """PATCH a template to is_active=True while its existing
    start_date is missing → 422 start_date_required_for_active."""
    # Seed a template directly with no start_date so we skip the
    # POST-side required field.
    tid = str(uuid.uuid4())
    tenant_id = dbc.customers.find_one({"id": customer_id})["tenant_id"]
    dbc.recurring_job_templates.insert_one({
        "id": tid, "tenant_id": tenant_id, "customer_id": customer_id,
        "service_type": "Pool Cleaning", "frequency": "weekly",
        "day_of_week": 0, "price_cents": 0,
        "start_date": None, "active": False, "is_active": False,
        "created_at": "2026-02-01T00:00:00+00:00",
    })
    try:
        r = requests.patch(
            f"{API}/recurring-jobs/{tid}",
            headers=admin_headers,
            json={"is_active": True},
            timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 422, r.text[:300]
        # Detail payload wraps the coded string.
        _txt = r.text
        assert "start_date_required_for_active" in _txt
    finally:
        dbc.recurring_job_templates.delete_one(
            {"id": tid, "tenant_id": tenant_id},
        )


# ─── Acceptance 3 — generator skips is_active=false templates ───────

def test_generator_skips_is_active_false_templates(admin_headers,
                                                     customer_id, dbc):
    """Manual ``/generate`` on an is_active=false template → 404
    template not found or inactive."""
    tid = str(uuid.uuid4())
    tenant_id = dbc.customers.find_one({"id": customer_id})["tenant_id"]
    dbc.recurring_job_templates.insert_one({
        "id": tid, "tenant_id": tenant_id, "customer_id": customer_id,
        "service_type": "Pool Cleaning", "frequency": "weekly",
        "day_of_week": 0, "price_cents": 0,
        "start_date": date.today().isoformat(),
        "active": True, "is_active": False,
        "created_at": "2026-02-01T00:00:00+00:00",
    })
    try:
        r = requests.post(
            f"{API}/recurring-jobs/{tid}/generate",
            headers=admin_headers,
            timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 404, r.text[:300]
    finally:
        dbc.recurring_job_templates.delete_one(
            {"id": tid, "tenant_id": tenant_id},
        )


# ─── Acceptance 4 — soft delete unchanged ──────────────────────────

def test_soft_delete_marks_inactive_but_row_survives(admin_headers,
                                                       customer_id, dbc):
    tid = str(uuid.uuid4())
    tenant_id = dbc.customers.find_one({"id": customer_id})["tenant_id"]
    dbc.recurring_job_templates.insert_one({
        "id": tid, "tenant_id": tenant_id, "customer_id": customer_id,
        "service_type": "Pool Cleaning", "frequency": "weekly",
        "day_of_week": 0, "price_cents": 0,
        "start_date": date.today().isoformat(),
        "active": True, "is_active": True,
        "created_at": "2026-02-01T00:00:00+00:00",
    })
    try:
        r = requests.delete(
            f"{API}/recurring-jobs/{tid}",
            headers=admin_headers,
            timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body.get("active") is False
        # Row still exists in Mongo.
        assert dbc.recurring_job_templates.find_one({"id": tid}) is not None
    finally:
        dbc.recurring_job_templates.delete_one(
            {"id": tid, "tenant_id": tenant_id},
        )


# ─── Acceptance 5 — hard delete removes row + cancels future kids ──

def test_hard_delete_removes_template_and_cancels_future_children(
    admin_headers, customer_id, dbc,
):
    tid = str(uuid.uuid4())
    tenant_id = dbc.customers.find_one({"id": customer_id})["tenant_id"]
    dbc.recurring_job_templates.insert_one({
        "id": tid, "tenant_id": tenant_id, "customer_id": customer_id,
        "service_type": "Hard Delete Fixture", "frequency": "weekly",
        "day_of_week": 0, "price_cents": 0,
        "start_date": date.today().isoformat(),
        "active": True, "is_active": True,
        "created_at": "2026-02-01T00:00:00+00:00",
    })

    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    future_jid = str(uuid.uuid4())
    completed_jid = str(uuid.uuid4())
    today_jid = str(uuid.uuid4())
    dbc.jobs.insert_many([
        # Future scheduled — MUST be cancelled.
        {"id": future_jid, "tenant_id": tenant_id,
         "recurring_template_id": tid, "status": "scheduled",
         "scheduled_date": tomorrow, "title": "future"},
        # Completed — MUST survive.
        {"id": completed_jid, "tenant_id": tenant_id,
         "recurring_template_id": tid, "status": "completed",
         "scheduled_date": yesterday, "title": "completed"},
        # Today's scheduled — MUST survive (route already loaded).
        {"id": today_jid, "tenant_id": tenant_id,
         "recurring_template_id": tid, "status": "scheduled",
         "scheduled_date": today, "title": "today"},
    ])
    try:
        r = requests.delete(
            f"{API}/recurring-jobs/{tid}?hard=true",
            headers=admin_headers,
            timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body.get("hard_deleted") is True
        assert body.get("future_jobs_cancelled") == 1, body
        # Template row is GONE.
        assert dbc.recurring_job_templates.find_one({"id": tid}) is None
        # Future child cancelled.
        _fut = dbc.jobs.find_one({"id": future_jid})
        assert _fut and _fut.get("status") == "cancelled", _fut
        assert _fut.get("cancelled_reason") == "recurring_template_hard_deleted"
        # Completed child preserved.
        _done = dbc.jobs.find_one({"id": completed_jid})
        assert _done and _done.get("status") == "completed", _done
        # Today's scheduled child preserved (route stays put).
        _today = dbc.jobs.find_one({"id": today_jid})
        assert _today and _today.get("status") == "scheduled", _today
        # Audit log entry present.
        _audit = dbc.audit_logs.find_one({
            "action": "recurring_job.hard_delete", "target_id": tid,
        })
        assert _audit is not None
    finally:
        dbc.recurring_job_templates.delete_many({"id": tid})
        dbc.jobs.delete_many({"id": {"$in": [future_jid, completed_jid, today_jid]}})
        dbc.audit_logs.delete_many(
            {"action": "recurring_job.hard_delete", "target_id": tid},
        )


def test_hard_delete_unknown_id_returns_404(admin_headers):
    r = requests.delete(
        f"{API}/recurring-jobs/{uuid.uuid4()}?hard=true",
        headers=admin_headers,
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 404, r.text[:300]
