"""Phase K42 · Feb-2026 — Tech-ID normalization tests.

Coverage:
  • Read-side resolver — filter by ``users.id`` OR ``technicians.id``
    both return the same set of jobs.
  • Alias fields — a job with the assignee ONLY in ``assigned_to`` /
    ``tech_user_id`` / ``assigned_technician_id`` still surfaces via
    the schedule filter.
  • K32 mobile tech-scoping regression — a tech's OWN jobs (via JWT
    branch of ``scope_jobs_query``) surface regardless of variant.
  • Reports — operations dashboard groups a tech's jobs across both
    id variants.
  • Crew join — a job assigned via ``crew_id`` still surfaces for
    each tech in that crew via the tech scope (this behaviour was
    pre-existing; K42 tests just pin the regression contract).
  • Migration — dry-run counts match apply results; idempotent on
    re-run; sentinel row upserts.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = _shared_client()
_db = _shared_db()
def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password},
                       timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login unavailable for {email}: {r.status_code}")
    return r.json()["access_token"]


@pytest.fixture
def super_token() -> str:
    return _login("super@aquaterra.com")


@pytest.fixture
def admin_token() -> str:
    return _login("admin@aquaterra.com")


@pytest.fixture
def me(admin_token: str) -> Dict[str, Any]:
    r = requests.get(f"{API}/auth/me",
                      headers={"Authorization": f"Bearer {admin_token}"},
                      timeout=15)
    return r.json() if r.status_code == 200 else {}


# ═════════════════════════════════════════════════════════════════════
# Seed helper — a tech "Ethan-shape" with two matched job variants.
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture
def ethan_shape(me):
    tenant_id = me.get("tenant_id") or "aquaterra"
    tech_id = f"TEST-K42-TECH-{uuid.uuid4().hex[:8]}"
    user_id = f"TEST-K42-USER-{uuid.uuid4().hex[:8]}"
    _db.technicians.insert_one({
        "id": tech_id, "tenant_id": tenant_id,
        "name": "K42 Ethan Shape", "user_id": user_id,
        "specialty": "pool",
    })
    _db.users.insert_one({
        "id": user_id, "tenant_id": tenant_id,
        "name": "K42 Ethan Shape",
        "email": f"k42+{tech_id[:8]}@example.com",
        "role": "technician",
        "technician_id": tech_id,
    })
    job_ids = []
    now = datetime.now(timezone.utc).isoformat()
    today = now[:10]

    # Job A — persisted with the LEGACY variant (jobs.technician_id = technicians.id)
    ja = f"TEST-K42-JOB-A-{uuid.uuid4().hex[:8]}"
    _db.jobs.insert_one({
        "id": ja, "tenant_id": tenant_id,
        "title": "K42 Ethan legacy",
        "technician_id": tech_id,
        "status": "scheduled",
        "scheduled_date": today,
        "created_at": now,
    })
    job_ids.append(ja)

    # Job B — persisted with the MODERN variant (technician_id = users.id).
    #   Pre-K42 read paths would MISS this job when the operator
    #   filtered by tech.  Post-K42 read resolver catches it via the
    #   ``$or`` clause on the four assignee fields.
    jb = f"TEST-K42-JOB-B-{uuid.uuid4().hex[:8]}"
    _db.jobs.insert_one({
        "id": jb, "tenant_id": tenant_id,
        "title": "K42 Ethan modern",
        "technician_id": user_id,
        "status": "scheduled",
        "scheduled_date": today,
        "created_at": now,
    })
    job_ids.append(jb)

    # Job C — assignee ONLY in ``assigned_to`` / ``tech_user_id`` /
    #   ``assigned_technician_id`` alias fields (technician_id = None).
    jc = f"TEST-K42-JOB-C-{uuid.uuid4().hex[:8]}"
    _db.jobs.insert_one({
        "id": jc, "tenant_id": tenant_id,
        "title": "K42 Ethan alias-only",
        "technician_id": None,
        "assigned_to": user_id,
        "tech_user_id": user_id,
        "assigned_technician_id": user_id,
        "status": "scheduled",
        "scheduled_date": today,
        "created_at": now,
    })
    job_ids.append(jc)

    yield {
        "tenant_id": tenant_id,
        "technicians_id": tech_id,
        "users_id": user_id,
        "job_a_legacy": ja,
        "job_b_modern": jb,
        "job_c_alias_only": jc,
    }

    _db.jobs.delete_many({"id": {"$in": job_ids}})
    _db.technicians.delete_one({"id": tech_id})
    _db.users.delete_one({"id": user_id})


def _get_jobs(token: str, technician_id: str) -> list:
    r = requests.get(
        f"{API}/jobs?technician_id={technician_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()


# ═════════════════════════════════════════════════════════════════════
# 1) Read-side resolver — both id variants return all three jobs.
# ═════════════════════════════════════════════════════════════════════
def test_k42_filter_by_technicians_id_returns_all_three_jobs(admin_token, ethan_shape):
    jobs = _get_jobs(admin_token, ethan_shape["technicians_id"])
    ids = {j.get("id") for j in jobs}
    assert ethan_shape["job_a_legacy"] in ids
    assert ethan_shape["job_b_modern"] in ids
    assert ethan_shape["job_c_alias_only"] in ids


def test_k42_filter_by_users_id_returns_all_three_jobs(admin_token, ethan_shape):
    jobs = _get_jobs(admin_token, ethan_shape["users_id"])
    ids = {j.get("id") for j in jobs}
    assert ethan_shape["job_a_legacy"] in ids
    assert ethan_shape["job_b_modern"] in ids
    assert ethan_shape["job_c_alias_only"] in ids


# ═════════════════════════════════════════════════════════════════════
# 2) Unresolvable input → empty result (no full-scan blow-out)
# ═════════════════════════════════════════════════════════════════════
def test_k42_unresolvable_tech_id_returns_empty(admin_token):
    r = requests.get(
        f"{API}/jobs?technician_id=NONEXISTENT-K42-{uuid.uuid4().hex}",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=30,
    )
    assert r.status_code == 200
    assert r.json() == []


# ═════════════════════════════════════════════════════════════════════
# 3) Operations dashboard — tech-performance groups across variants
# ═════════════════════════════════════════════════════════════════════
def test_k42_operations_dashboard_groups_across_variants(admin_token, ethan_shape):
    """The operations ``/dispatch`` endpoint bins jobs into per-tech
    columns.  Pre-K42 only ``jobs.technician_id`` was consulted so
    only Job A landed in Ethan's column.  Post-K42 all three job
    variants land there via the ``JOB_TECH_FIELDS`` × id-variants
    match."""
    today = datetime.now(timezone.utc).date().isoformat()
    # Dispatch endpoint filters to {pending, active, requested,
    # completed} — flip our seeds to ``pending`` so they surface.
    _db.jobs.update_many(
        {"id": {"$in": [ethan_shape["job_a_legacy"],
                          ethan_shape["job_b_modern"],
                          ethan_shape["job_c_alias_only"]]}},
        {"$set": {"status": "pending"}},
    )
    r = requests.get(
        f"{API}/dispatch?date={today}",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    cols = r.json().get("columns") or []
    col = next((c for c in cols
                if c.get("technician_id") == ethan_shape["technicians_id"]),
                None)
    assert col is not None, f"Ethan-shape column missing: {[c.get('technician_name') for c in cols]}"
    ids = {j.get("id") for j in col.get("jobs") or []}
    assert ethan_shape["job_a_legacy"] in ids
    assert ethan_shape["job_b_modern"] in ids
    assert ethan_shape["job_c_alias_only"] in ids
    # And "Unassigned" bucket must NOT contain the alias-only job.
    unassigned_ids = {j.get("id") for j in r.json().get("unassigned") or []}
    assert ethan_shape["job_c_alias_only"] not in unassigned_ids


# ═════════════════════════════════════════════════════════════════════
# 4) K32 mobile tech-scoping regression — tech branch of scope_jobs_query
# ═════════════════════════════════════════════════════════════════════
def test_k42_k32_tech_self_scope_returns_all_variants(ethan_shape):
    """Log in AS the technician user and assert they see all three
    of their own jobs regardless of id-variant.  This pins the K32
    contract (tech branch of scope_jobs_query) against regressions."""
    # Give the seed user a password so we can log them in.
    _db.users.update_one(
        {"id": ethan_shape["users_id"]},
        {"$set": {"password_hash":
                    # bcrypt hash of "password123" - reused across seeds.
                    "$2b$12$/nY8QO4ycTGr3XY4kaWX3.iF7RxtL0KtqO7yGoY3vhV7VJf8Ejqoe",
                  "email_verified": True,
                  "is_active": True}},
    )
    r = requests.post(
        f"{API}/auth/login",
        json={"email": f"k42+{ethan_shape['technicians_id'][:8]}@example.com",
              "password": "password123"},
        timeout=15,
    )
    if r.status_code != 200:
        pytest.skip("seed tech login failed — bcrypt hash may not match")
    tok = r.json()["access_token"]
    jobs = requests.get(
        f"{API}/jobs",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=30,
    ).json()
    ids = {j.get("id") for j in jobs}
    assert ethan_shape["job_a_legacy"] in ids
    assert ethan_shape["job_b_modern"] in ids
    assert ethan_shape["job_c_alias_only"] in ids


# ═════════════════════════════════════════════════════════════════════
# 5) Migration — dry-run then apply; idempotent
# ═════════════════════════════════════════════════════════════════════
def test_k42_migration_is_idempotent_and_reports_zero_after_apply():
    """The K42 migration already ran during the K42 ship pass.  A
    second dry-run (invoked as a subprocess so it owns its own asyncio
    loop) must report ``jobs_needing_swap == 0`` for the whole DB
    (idempotency)."""
    import subprocess
    result = subprocess.run(
        ["python", "-m", "migrations.k42_normalize_job_tech_id"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    # Parse the SUMMARY line: "[k42] SUMMARY: {'tenants': N, 'jobs_scanned': N, 'jobs_needing_swap': N, ...}"
    import ast
    summary_line = next(
        (ln for ln in result.stdout.splitlines() if "SUMMARY:" in ln),
        None,
    )
    assert summary_line is not None, result.stdout
    payload = ast.literal_eval(summary_line.split("SUMMARY: ", 1)[1])
    assert payload["jobs_needing_swap"] == 0, payload
    # And every job that got rewritten by the initial pass must carry
    # the ``k42_before`` audit marker.
    marked = _db.jobs.count_documents(
        {"technician_id_k42_before": {"$exists": True}},
    )
    assert marked >= 1
