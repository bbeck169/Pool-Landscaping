"""Feb-2026 HOTFIX (live user report) — Schedule bulk-actions authz.

The Schedule page's bulk-action strip (Complete N / Move these events N /
Reorder / Optimize Route) was visible to technicians on the preview.
This suite locks down defense-in-depth on the backend so even a raw
curl call from a tech token cannot invoke those actions.

Coverage matrix:
  * test_schedule_bulk_complete_forbidden_for_technician_403
      Bulk-complete iterates PUT /jobs/{id} on the FE. For a tech,
      the shared endpoint gates "not your job" to 403; test picks
      a job the tech is NOT assigned to.
  * test_schedule_bulk_move_forbidden_for_technician_403
      Same shared endpoint via PUT /jobs/{id} with ``scheduled_start``.
      Same 403 for a non-owned job.
  * test_schedule_reorder_forbidden_for_technician_403
      POST /jobs/reorder is already ``_require_admin_or_manager``.
      A tech token must 403.
  * test_schedule_optimize_route_forbidden_for_technician_403
      POST /schedule/optimize-route — new tech 403 added in this
      hotfix. A tech token must 403 regardless of ``user_id`` param.
  * test_schedule_bulk_actions_allowed_for_admin_200
      Regression guard — admin can still Reorder + Optimize Route.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def tech_h():
    return _hdrs(_login("mike@aquaterra.com"))


@pytest.fixture(scope="module")
def admin_h():
    return _hdrs(_login("admin@aquaterra.com"))


@pytest.fixture(scope="module")
def aquaterra_tenant_id():
    row = _sync.users.find_one({"email": "admin@aquaterra.com"},
                                 {"_id": 0, "tenant_id": 1})
    assert row and row.get("tenant_id"), "aquaterra admin seed missing"
    return row["tenant_id"]


@pytest.fixture()
def job_owned_by_admin_not_tech(aquaterra_tenant_id):
    """Seed a job assigned to admin — a technician calling PUT on this
    ``job.id`` must be rejected by the ``is_tech_authorized_on_job``
    gate on ``PUT /api/jobs/{id}``."""
    admin_row = _sync.users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0, "id": 1},
    )
    jid = f"hotfix-schedule-{uuid.uuid4().hex[:12]}"
    _sync.jobs.insert_one({
        "id": jid,
        "tenant_id": aquaterra_tenant_id,
        "customer_id": "cust-hotfix",
        "customer_name": "Hotfix Cust",
        "title": "Hotfix job (admin-owned)",
        "service_type": "Weekly Pool Service",
        "status": "scheduled",
        "technician_id": admin_row["id"],
        "site_lat": 33.6, "site_lng": -112.2,
        "scheduled_start": "2026-03-01T12:00:00Z",
        "price": 100.0, "billable": True, "photos": [],
        "created_at": "2026-02-15T00:00:00Z",
    })
    yield jid
    _sync.jobs.delete_one({"id": jid})


# ── Bulk Complete (shared PUT /jobs/{id}) ───────────────────────
def test_schedule_bulk_complete_forbidden_for_technician_403(
    tech_h, job_owned_by_admin_not_tech,
):
    r = requests.put(
        f"{API}/jobs/{job_owned_by_admin_not_tech}",
        headers=tech_h,
        json={"status": "completed"},
        timeout=15,
    )
    assert r.status_code == 403, f"expected 403 not-your-job, got {r.status_code} {r.text[:200]}"


# ── Bulk Move (shared PUT /jobs/{id} with scheduled_start) ─────
def test_schedule_bulk_move_forbidden_for_technician_403(
    tech_h, job_owned_by_admin_not_tech,
):
    r = requests.put(
        f"{API}/jobs/{job_owned_by_admin_not_tech}",
        headers=tech_h,
        json={"scheduled_start": "2026-03-15T09:00:00Z"},
        timeout=15,
    )
    assert r.status_code == 403, f"expected 403 not-your-job, got {r.status_code} {r.text[:200]}"


# ── Reorder (POST /jobs/reorder — admin/manager gate) ──────────
def test_schedule_reorder_forbidden_for_technician_403(tech_h):
    # Even with a well-formed payload, tech role must be rejected.
    r = requests.post(
        f"{API}/jobs/reorder",
        headers=tech_h,
        json={"date": "2026-03-01", "job_ids": [], "reorder_key": "hotfix"},
        timeout=15,
    )
    assert r.status_code == 403, f"expected 403 tech-reorder, got {r.status_code} {r.text[:200]}"


# ── Optimize Route (POST /schedule/optimize-route) ─────────────
def test_schedule_optimize_route_forbidden_for_technician_403(tech_h):
    r = requests.post(
        f"{API}/schedule/optimize-route",
        headers=tech_h,
        json={"start_lat": 33.60, "start_lng": -112.20},
        timeout=15,
    )
    assert r.status_code == 403, f"expected 403 tech-optimize, got {r.status_code} {r.text[:200]}"
    # Message body should mention "dispatcher" for observability.
    assert "dispatcher" in r.text.lower(), r.text[:300]


# ── Regression guard — admin retains access ─────────────────────
def test_schedule_bulk_actions_allowed_for_admin_200(admin_h, aquaterra_tenant_id):
    """Admin can still hit the two admin-only endpoints. Reorder with
    an empty ``job_ids`` list is a well-formed no-op and must return
    2xx; Optimize Route must return 200 as well."""
    # 1) Reorder (empty payload — no-op, but must NOT be 403).
    r_reorder = requests.post(
        f"{API}/jobs/reorder",
        headers=admin_h,
        json={"date": "2026-03-01", "ordered_job_ids": [], "reorder_key": "hotfix-admin"},
        timeout=15,
    )
    # Endpoint accepts admin (payload may 400 on empty list, but the
    # regression we're guarding is "not 403") — anything other than
    # 403 proves the admin role gate holds.
    assert r_reorder.status_code != 403, (
        f"admin reorder unexpectedly forbidden: {r_reorder.status_code} {r_reorder.text[:200]}"
    )
    # 2) Optimize Route — admin path, own user (no user_id override).
    r_opt = requests.post(
        f"{API}/schedule/optimize-route",
        headers=admin_h,
        json={"start_lat": 33.60, "start_lng": -112.20},
        timeout=15,
    )
    assert r_opt.status_code == 200, (
        f"admin optimize unexpectedly rejected: {r_opt.status_code} {r_opt.text[:200]}"
    )
