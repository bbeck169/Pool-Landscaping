"""Feb-2026 · P1 · Auto-Activate + Bulk Activate + Instant Generation.

Locks the acceptance contract on the phase:
  1. Create defaults ``is_active`` to True and fires 14-day inline
     generation (``generated_count`` > 0 for a same-day weekly start).
  2. Create with ``is_active: False`` runs zero inline generation.
  3. Instant generation is skipped (INFO log, ``skipped_no_start_
     date: true``) when the template has no valid ``start_date``.
  4. PATCH flipping ``is_active`` False → True fires 14-day inline
     generation.
  5. PATCH that doesn't touch ``is_active`` performs zero inline
     generation.
  6. Bulk-activate returns per-id status
     (``activated`` / ``already_active`` / ``failed``) with
     ``generated_count`` and ``skipped_no_start_date`` fields.
  7. Bulk-activate cap is 100; > 100 ids returns 400
     ``batch_too_large``.
  8. Already-active templates still run instant generation and may
     report ``generated_count`` > 0 with status ``already_active``.
  9. Missing-``start_date`` template inside a mixed batch reports
     ``skipped_no_start_date: true`` while still activating the flag.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values, load_dotenv
from pymongo import MongoClient


load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    pytest.skip("REACT_APP_BACKEND_URL not set", allow_module_level=True)
API = f"{BASE_URL}/api"

_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

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
    r = requests.get(f"{API}/customers?is_active=true&limit=1",
                      headers=admin_headers, timeout=REQ_TIMEOUT)
    r.raise_for_status()
    rows = r.json() if isinstance(r.json(), list) else (r.json().get("items") or [])
    if not rows:
        pytest.skip("no seeded customer available")
    return rows[0]["id"]


@pytest.fixture(scope="module")
def tenant_id(admin_headers, customer_id):
    """Derive the caller's tenant_id via a one-off create → introspect
    → delete round-trip. Avoids assuming the tenant slug matches any
    literal (env-dependent DB seeding varies across forks)."""
    payload = {
        "customer_id": customer_id,
        "service_type": f"P1 tenant-id probe · {uuid.uuid4().hex[:8]}",
        "frequency": "weekly",
        "day_of_week": 0,
        "start_date": (date.today() - timedelta(days=30)).isoformat(),
        "price_cents": 100,
        "is_active": False,
    }
    r = requests.post(f"{API}/recurring-jobs", json=payload,
                       headers=admin_headers, timeout=REQ_TIMEOUT)
    r.raise_for_status()
    body = r.json()
    tid_local = body["id"]
    tenant = body.get("tenant_id")
    # Cleanup the probe.
    requests.delete(f"{API}/recurring-jobs/{tid_local}?hard=true",
                     headers=admin_headers, timeout=REQ_TIMEOUT)
    assert tenant, f"probe response missing tenant_id: {body!r}"
    return tenant


def _mk_weekly_payload(customer_id: str, *, start_date: str | None = None,
                       is_active: bool | None = None):
    """Build a minimal weekly-Monday RecurringJobIn payload. When
    ``start_date`` is None we pick a Monday from the past two weeks so
    the generator has occurrences to materialize inside the 14-day
    horizon. When explicitly set to ``""`` (empty string), pass a
    Pydantic-acceptable empty (the guard fires downstream)."""
    if start_date is None:
        today = date.today()
        # Walk back to the previous Monday (weekday()==0) so today's
        # 14-day horizon spans at least two weekly occurrences.
        anchor = today - timedelta(days=today.weekday() + 7)
        start_date = anchor.isoformat()
    payload = {
        "customer_id": customer_id,
        "service_type": f"P1 Instant Gen · {uuid.uuid4().hex[:8]}",
        "frequency": "weekly",
        "day_of_week": 0,  # Monday
        "start_date": start_date,
        "price_cents": 15000,
    }
    if is_active is not None:
        payload["is_active"] = is_active
    return payload


# ─── Acceptance 1: default is_active=True + inline generation ─────────

def test_create_defaults_is_active_true_and_fires_instant_generation(
    admin_headers, customer_id, dbc,
):
    payload = _mk_weekly_payload(customer_id)
    # NOTE: is_active omitted → default kicks in.
    r = requests.post(f"{API}/recurring-jobs",
                       json=payload,
                       headers=admin_headers, timeout=REQ_TIMEOUT)
    r.raise_for_status()
    body = r.json()
    tpl_id = body["id"]
    try:
        assert body["is_active"] is True, "default should be True post-P1"
        assert body["generated_count"] >= 1, (
            f"expected 14-day horizon to materialize at least 1 weekly "
            f"occurrence, got {body!r}"
        )
        assert body["skipped_no_start_date"] is False
    finally:
        dbc.recurring_job_templates.delete_one({"id": tpl_id})
        dbc.jobs.delete_many({"recurring_template_id": tpl_id})


# ─── Acceptance 2: draft (is_active=False) skips inline generation ────

def test_create_with_is_active_false_skips_instant_generation(
    admin_headers, customer_id, dbc,
):
    payload = _mk_weekly_payload(customer_id, is_active=False)
    r = requests.post(f"{API}/recurring-jobs",
                       json=payload,
                       headers=admin_headers, timeout=REQ_TIMEOUT)
    r.raise_for_status()
    body = r.json()
    tpl_id = body["id"]
    try:
        assert body["is_active"] is False
        assert body["generated_count"] == 0
        # No jobs should have been created for the template.
        assert dbc.jobs.count_documents(
            {"recurring_template_id": tpl_id}) == 0
    finally:
        dbc.recurring_job_templates.delete_one({"id": tpl_id})


# ─── Acceptance 3: missing start_date → skip guard fires ──────────────

def test_instant_generation_skipped_missing_start_date(
    admin_headers, customer_id, tenant_id, dbc,
):
    # The public POST endpoint requires ``start_date`` at the Pydantic
    # layer, so we exercise the guard via a DB-seeded template + the
    # bulk-activate endpoint (which reads the doc as-is).
    tpl_id = f"tpl-p1-nosd-{uuid.uuid4().hex[:8]}"
    dbc.recurring_job_templates.insert_one({
        "id": tpl_id, "tenant_id": tenant_id,
        "customer_id": customer_id, "service_type": "P1 no-sd",
        "frequency": "weekly", "day_of_week": 0,
        "start_date": None, "active": False, "is_active": False,
        "price_cents": 10000,
        "created_at": date.today().isoformat(),
    })
    try:
        r = requests.post(f"{API}/recurring-jobs/bulk-activate",
                           json={"recurring_job_ids": [tpl_id]},
                           headers=admin_headers, timeout=REQ_TIMEOUT)
        r.raise_for_status()
        body = r.json()
        assert body["activated"] == 1
        row = body["results"][0]
        assert row["status"] == "activated"
        assert row["generated_count"] == 0
        assert row["skipped_no_start_date"] is True
    finally:
        dbc.recurring_job_templates.delete_one({"id": tpl_id})


# ─── Acceptance 4: PATCH False→True fires inline generation ───────────

def test_patch_recurring_activation_triggers_generation(
    admin_headers, customer_id, dbc,
):
    # Start with is_active=False so the create path skips generation.
    payload = _mk_weekly_payload(customer_id, is_active=False)
    r = requests.post(f"{API}/recurring-jobs",
                       json=payload,
                       headers=admin_headers, timeout=REQ_TIMEOUT)
    r.raise_for_status()
    tpl_id = r.json()["id"]
    try:
        # Flip is_active True — expect inline generation to run.
        r2 = requests.patch(f"{API}/recurring-jobs/{tpl_id}",
                             json={"is_active": True},
                             headers=admin_headers, timeout=REQ_TIMEOUT)
        r2.raise_for_status()
        body = r2.json()
        assert body["is_active"] is True
        assert body["generated_count"] >= 1
        assert body["skipped_no_start_date"] is False
        # Verify jobs actually landed in the collection.
        assert dbc.jobs.count_documents(
            {"recurring_template_id": tpl_id}) >= 1
    finally:
        dbc.recurring_job_templates.delete_one({"id": tpl_id})
        dbc.jobs.delete_many({"recurring_template_id": tpl_id})


# ─── Acceptance 5: PATCH without is_active does not generate ──────────

def test_patch_recurring_no_activation_no_generation(
    admin_headers, customer_id, dbc,
):
    payload = _mk_weekly_payload(customer_id, is_active=False)
    r = requests.post(f"{API}/recurring-jobs",
                       json=payload,
                       headers=admin_headers, timeout=REQ_TIMEOUT)
    r.raise_for_status()
    tpl_id = r.json()["id"]
    try:
        # PATCH a non-is_active field; expect NO generation.
        r2 = requests.patch(f"{API}/recurring-jobs/{tpl_id}",
                             json={"notes": "some updated note"},
                             headers=admin_headers, timeout=REQ_TIMEOUT)
        r2.raise_for_status()
        body = r2.json()
        assert body["generated_count"] == 0
        assert body["skipped_no_start_date"] is False
        assert dbc.jobs.count_documents(
            {"recurring_template_id": tpl_id}) == 0
    finally:
        dbc.recurring_job_templates.delete_one({"id": tpl_id})


# ─── Acceptance 6+8: bulk-activate mixed batch, per-id status ─────────

def test_bulk_activate_reports_per_id_status_and_generation(
    admin_headers, customer_id, dbc,
):
    # Seed three templates: one draft (activated), one already active,
    # one nonexistent id (failed).
    p1 = _mk_weekly_payload(customer_id, is_active=False)
    p2 = _mk_weekly_payload(customer_id, is_active=True)
    r_draft = requests.post(f"{API}/recurring-jobs", json=p1,
                             headers=admin_headers, timeout=REQ_TIMEOUT)
    r_draft.raise_for_status()
    r_active = requests.post(f"{API}/recurring-jobs", json=p2,
                              headers=admin_headers, timeout=REQ_TIMEOUT)
    r_active.raise_for_status()
    tpl_draft = r_draft.json()["id"]
    tpl_active = r_active.json()["id"]
    bogus = f"tpl-p1-bogus-{uuid.uuid4().hex[:8]}"
    try:
        r = requests.post(f"{API}/recurring-jobs/bulk-activate",
                           json={"recurring_job_ids": [tpl_draft, tpl_active, bogus]},
                           headers=admin_headers, timeout=REQ_TIMEOUT)
        r.raise_for_status()
        body = r.json()
        assert body["activated"] == 1
        assert body["already_active"] == 1
        assert body["failed"] == 1
        by_id = {row["id"]: row for row in body["results"]}
        assert by_id[tpl_draft]["status"] == "activated"
        assert by_id[tpl_draft]["generated_count"] >= 1
        assert by_id[tpl_draft]["skipped_no_start_date"] is False
        assert by_id[tpl_active]["status"] == "already_active"
        # Already-active templates still run generation; they may or
        # may not insert new jobs depending on ``last_generated_through``.
        assert by_id[tpl_active]["skipped_no_start_date"] is False
        assert by_id[bogus]["status"] == "failed"
        assert by_id[bogus]["error"] == "not_found"
    finally:
        dbc.recurring_job_templates.delete_many(
            {"id": {"$in": [tpl_draft, tpl_active]}})
        dbc.jobs.delete_many(
            {"recurring_template_id": {"$in": [tpl_draft, tpl_active]}})


# ─── Acceptance 7: > 100 ids → 400 batch_too_large ────────────────────

def test_bulk_activate_batch_cap_returns_400(admin_headers):
    ids = [f"id-{i}" for i in range(101)]
    r = requests.post(f"{API}/recurring-jobs/bulk-activate",
                       json={"recurring_job_ids": ids},
                       headers=admin_headers, timeout=REQ_TIMEOUT)
    assert r.status_code == 400
    detail = r.json().get("detail") or r.json()
    assert detail.get("error") == "batch_too_large"
    assert detail.get("max") == 100
    assert detail.get("received") == 101


# ─── Acceptance 9: bulk-activate mixed batch flags no-start-date ──────

def test_bulk_activate_reports_skipped_no_start_date(
    admin_headers, customer_id, tenant_id, dbc,
):
    # One valid template + one DB-seeded template without a
    # ``start_date`` — the batch should activate both but only the
    # valid one reports ``generated_count`` > 0.
    ok_payload = _mk_weekly_payload(customer_id, is_active=False)
    r_ok = requests.post(f"{API}/recurring-jobs", json=ok_payload,
                          headers=admin_headers, timeout=REQ_TIMEOUT)
    r_ok.raise_for_status()
    tpl_ok = r_ok.json()["id"]
    tpl_nosd = f"tpl-p1-nosd-{uuid.uuid4().hex[:8]}"
    dbc.recurring_job_templates.insert_one({
        "id": tpl_nosd, "tenant_id": tenant_id,
        "customer_id": customer_id, "service_type": "P1 no-sd batch",
        "frequency": "weekly", "day_of_week": 0,
        "start_date": None, "active": False, "is_active": False,
        "price_cents": 10000,
        "created_at": date.today().isoformat(),
    })
    try:
        r = requests.post(f"{API}/recurring-jobs/bulk-activate",
                           json={"recurring_job_ids": [tpl_ok, tpl_nosd]},
                           headers=admin_headers, timeout=REQ_TIMEOUT)
        r.raise_for_status()
        body = r.json()
        assert body["activated"] == 2
        by_id = {row["id"]: row for row in body["results"]}
        assert by_id[tpl_ok]["skipped_no_start_date"] is False
        assert by_id[tpl_ok]["generated_count"] >= 1
        assert by_id[tpl_nosd]["skipped_no_start_date"] is True
        assert by_id[tpl_nosd]["generated_count"] == 0
    finally:
        dbc.recurring_job_templates.delete_many(
            {"id": {"$in": [tpl_ok, tpl_nosd]}})
        dbc.jobs.delete_many({"recurring_template_id": tpl_ok})
