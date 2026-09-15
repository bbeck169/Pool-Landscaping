"""Phase R1 · Feb-2026 — Recurring-Jobs Bulk Hard Delete acceptance.

Covers the phase-brief acceptance list:

  1. Happy path — 3 templates each with a mix of past/completed/
     today/future visits → all 3 removed from
     ``recurring_job_templates``; every future ``scheduled`` child
     (``scheduled_date >= today``) flipped to ``cancelled``; past
     + completed rows preserved; response summary is exact.
  2. Ownership isolation — id owned by a DIFFERENT tenant returns
     ``forbidden`` for that id, does NOT delete the row.
  3. Non-existent id returns ``not_found`` for that id; the rest
     of the batch still processes.
  4. Role guard — non-admin user gets 403 on the endpoint.
  5. Audit trail — every ``deleted`` id emits an ``audit_logs``
     entry with ``action == "recurring_job.hard_delete"``.
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
    r = requests.get(f"{API}/customers?is_active=true&limit=1",
                      headers=admin_headers, timeout=REQ_TIMEOUT)
    r.raise_for_status()
    rows = r.json() if isinstance(r.json(), list) else (r.json().get("items") or [])
    if not rows:
        pytest.skip("no seeded customer available")
    return rows[0]["id"]


def _mint_tpl(dbc, *, tenant_id, customer_id, tid=None):
    tid = tid or str(uuid.uuid4())
    dbc.recurring_job_templates.insert_one({
        "id": tid, "tenant_id": tenant_id, "customer_id": customer_id,
        "service_type": "Bulk Delete Fixture", "frequency": "weekly",
        "day_of_week": 0, "price_cents": 0,
        "start_date": date.today().isoformat(),
        "active": True, "is_active": True,
        "created_at": "2026-02-01T00:00:00+00:00",
    })
    return tid


def _mint_visits(dbc, *, tenant_id, tid):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    two_days_ago = (date.today() - timedelta(days=2)).isoformat()
    ids = {
        "future": str(uuid.uuid4()),
        "today": str(uuid.uuid4()),
        "past_scheduled": str(uuid.uuid4()),
        "completed": str(uuid.uuid4()),
    }
    dbc.jobs.insert_many([
        # Future scheduled → MUST cancel under bulk (>= today).
        {"id": ids["future"], "tenant_id": tenant_id,
          "recurring_template_id": tid, "status": "scheduled",
          "scheduled_date": tomorrow, "title": "future"},
        # Today scheduled → MUST cancel under bulk (>= today).  This
        # is where bulk diverges from per-row semantics.
        {"id": ids["today"], "tenant_id": tenant_id,
          "recurring_template_id": tid, "status": "scheduled",
          "scheduled_date": today, "title": "today"},
        # Past scheduled → preserved (< today).  Note: the
        # ``(recurring_template_id, scheduled_date)`` unique index
        # forces distinct dates per template, hence the split.
        {"id": ids["past_scheduled"], "tenant_id": tenant_id,
          "recurring_template_id": tid, "status": "scheduled",
          "scheduled_date": yesterday, "title": "past-scheduled"},
        # Completed → preserved (status filter).
        {"id": ids["completed"], "tenant_id": tenant_id,
          "recurring_template_id": tid, "status": "completed",
          "scheduled_date": two_days_ago, "title": "completed"},
    ])
    return ids


# ─── 1. Happy path ─────────────────────────────────────────────────
def test_bulk_delete_happy_path(admin_headers, customer_id, dbc):
    tenant_id = dbc.customers.find_one({"id": customer_id})["tenant_id"]
    tpl_ids = [_mint_tpl(dbc, tenant_id=tenant_id, customer_id=customer_id)
                for _ in range(3)]
    visit_bundles = {tid: _mint_visits(dbc, tenant_id=tenant_id, tid=tid)
                       for tid in tpl_ids}
    all_visit_ids = [v for bundle in visit_bundles.values() for v in bundle.values()]

    try:
        r = requests.post(
            f"{API}/recurring-jobs/bulk-delete",
            json={"recurring_job_ids": tpl_ids},
            headers=admin_headers, timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        # Per-id results — order-preserving.
        results = body.get("results") or []
        assert len(results) == 3
        for res, tid in zip(results, tpl_ids):
            assert res["recurring_job_id"] == tid
            assert res["status"] == "deleted", res
            assert res["future_visits_deleted"] == 2, res  # today + future
        # Aggregate summary — 3 tpls · (today+future)*3 visits = 6.
        summary = body.get("summary") or {}
        assert summary.get("templates_deleted") == 3, summary
        assert summary.get("future_visits_deleted") == 6, summary
        assert summary.get("errors") == 0, summary
        # DB assertions — all templates gone.
        for tid in tpl_ids:
            assert dbc.recurring_job_templates.find_one({"id": tid}) is None
        # Future + today visits flipped to cancelled.
        for bundle in visit_bundles.values():
            for label in ("future", "today"):
                row = dbc.jobs.find_one({"id": bundle[label]})
                assert row and row["status"] == "cancelled", (label, row)
                assert row["cancelled_reason"] == "recurring_template_hard_deleted"
            # Past + completed preserved.
            past = dbc.jobs.find_one({"id": bundle["past_scheduled"]})
            assert past and past["status"] == "scheduled", past
            done = dbc.jobs.find_one({"id": bundle["completed"]})
            assert done and done["status"] == "completed", done
        # ─── Audit trail — one entry per deleted template ───
        audits = list(dbc.audit_logs.find({
            "action": "recurring_job.hard_delete",
            "target_id": {"$in": tpl_ids},
        }))
        assert len(audits) == 3, audits
        for a in audits:
            assert a["actor_email"] == "admin@aquaterra.com"
            assert a["target_type"] == "recurring_job_template"
            assert a["future_jobs_cancelled"] == 2
    finally:
        dbc.recurring_job_templates.delete_many({"id": {"$in": tpl_ids}})
        dbc.jobs.delete_many({"id": {"$in": all_visit_ids}})
        dbc.audit_logs.delete_many({
            "action": "recurring_job.hard_delete",
            "target_id": {"$in": tpl_ids},
        })


# ─── 2. Ownership isolation — cross-tenant id returns forbidden ────
def test_bulk_delete_cross_tenant_id_returns_forbidden(admin_headers,
                                                          customer_id, dbc):
    tenant_id = dbc.customers.find_one({"id": customer_id})["tenant_id"]
    # Foreign tenant fixture id (safe pseudo-tenant that MUST NOT
    # match the caller's tenant).
    foreign_tid = str(uuid.uuid4())
    dbc.recurring_job_templates.insert_one({
        "id": foreign_tid, "tenant_id": "some-other-tenant",
        "customer_id": "foreign-customer",
        "service_type": "Foreign Fixture", "frequency": "weekly",
        "day_of_week": 0, "price_cents": 0,
        "start_date": date.today().isoformat(),
        "active": True, "is_active": True,
        "created_at": "2026-02-01T00:00:00+00:00",
    })
    # Also mint a legit tpl in the caller's tenant to prove the
    # batch keeps processing after a forbidden entry.
    own_tid = _mint_tpl(dbc, tenant_id=tenant_id, customer_id=customer_id)
    try:
        r = requests.post(
            f"{API}/recurring-jobs/bulk-delete",
            json={"recurring_job_ids": [foreign_tid, own_tid]},
            headers=admin_headers, timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 200, r.text[:400]
        results = r.json()["results"]
        by_id = {r["recurring_job_id"]: r for r in results}
        assert by_id[foreign_tid]["status"] == "forbidden"
        assert by_id[foreign_tid]["future_visits_deleted"] == 0
        assert by_id[own_tid]["status"] == "deleted"
        # Foreign row survives.
        assert dbc.recurring_job_templates.find_one({"id": foreign_tid}) is not None
        # Own row gone.
        assert dbc.recurring_job_templates.find_one({"id": own_tid}) is None
        # Summary: 1 deleted, 1 error-ish (forbidden counts).
        assert r.json()["summary"]["templates_deleted"] == 1
        assert r.json()["summary"]["errors"] == 1
    finally:
        dbc.recurring_job_templates.delete_many(
            {"id": {"$in": [foreign_tid, own_tid]}},
        )
        dbc.audit_logs.delete_many({
            "action": "recurring_job.hard_delete",
            "target_id": {"$in": [foreign_tid, own_tid]},
        })


# ─── 3. Non-existent id returns not_found ──────────────────────────
def test_bulk_delete_unknown_id_returns_not_found(admin_headers,
                                                     customer_id, dbc):
    tenant_id = dbc.customers.find_one({"id": customer_id})["tenant_id"]
    ghost_tid = str(uuid.uuid4())
    own_tid = _mint_tpl(dbc, tenant_id=tenant_id, customer_id=customer_id)
    try:
        r = requests.post(
            f"{API}/recurring-jobs/bulk-delete",
            json={"recurring_job_ids": [ghost_tid, own_tid]},
            headers=admin_headers, timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 200, r.text[:400]
        by_id = {r["recurring_job_id"]: r for r in r.json()["results"]}
        assert by_id[ghost_tid]["status"] == "not_found"
        assert by_id[own_tid]["status"] == "deleted"
    finally:
        dbc.recurring_job_templates.delete_many({"id": own_tid})
        dbc.audit_logs.delete_many({
            "action": "recurring_job.hard_delete", "target_id": own_tid,
        })


# ─── 4. Role guard — non-admin gets 403 ────────────────────────────
def test_bulk_delete_non_admin_gets_403():
    # ``customer@aquaterra.com`` has role ``customer`` — not admin.
    try:
        tok = _login("customer@aquaterra.com")
    except Exception:
        pytest.skip("customer test account not seeded")
    r = requests.post(
        f"{API}/recurring-jobs/bulk-delete",
        json={"recurring_job_ids": [str(uuid.uuid4())]},
        headers={"Authorization": f"Bearer {tok}"},
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 403, r.text[:400]


# ─── 5. Validation — empty body → 422 ──────────────────────────────
def test_bulk_delete_empty_id_list_returns_422(admin_headers):
    r = requests.post(
        f"{API}/recurring-jobs/bulk-delete",
        json={"recurring_job_ids": []},
        headers=admin_headers, timeout=REQ_TIMEOUT,
    )
    # Pydantic ``min_items=1`` → 422.
    assert r.status_code == 422, r.text[:400]


# ─── 6. Validation — over-cap (200) → 422 ──────────────────────────
def test_bulk_delete_over_cap_returns_422(admin_headers):
    over_cap = [str(uuid.uuid4()) for _ in range(201)]
    r = requests.post(
        f"{API}/recurring-jobs/bulk-delete",
        json={"recurring_job_ids": over_cap},
        headers=admin_headers, timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 422, r.text[:400]
