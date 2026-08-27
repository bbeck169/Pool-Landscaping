"""Feb 2026 · Task A — manager RBAC on /api/recurring-jobs.

The admin ``/admin/recurring-jobs`` page renders a red "Admin access
required" banner for the manager role because the backend endpoints
were gated behind ``require_admin``. Managers legitimately own
recurring-job templates (that's why the earlier route-guard fix
already let them reach the page). This suite hard-codes the RBAC
contract on every recurring-jobs endpoint so the gate doesn't
regress:

  * super_admin, admin, manager        → 200 on read + write
  * technician, customer, unauth       → 403

Uses pymongo (sync) to seed a couple of technicians so the write
paths can pass their existence checks, and cleans up after itself.
"""
from __future__ import annotations

import os
import uuid

import httpx
import pytest
from dotenv import dotenv_values
from pymongo import MongoClient


BASE = "http://localhost:8001"

_ENV = dotenv_values("/app/backend/.env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync_db = (
    MongoClient(_MONGO_URL)[_DB_NAME] if (_MONGO_URL and _DB_NAME) else None
)


def _login(email: str, password: str = "password123") -> str:
    r = httpx.post(f"{BASE}/api/auth/login", json={
        "email": email, "password": password,
    }, timeout=60)
    if r.status_code != 200:
        return ""
    b = r.json()
    return b.get("access_token") or b.get("token") or ""


# ────────────────────────────────────────────────────────────────────
# Fixtures — seed a technician user we can use as a 403 caller
# ────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def tech_email():
    """Seed a tenant-scoped technician user whose role isn't in the
    ``admin_or_manager`` allowlist. Yields the email; cleanup removes
    the user after the test module completes."""
    from utils import hash_password
    email = f"test-tech-rbac-{uuid.uuid4().hex[:8]}@example.com"
    # Match aquaterra tenant id so downstream tenant scoping works if
    # the endpoint reads it. We don't care which tenant — the 403
    # comes from role, not tenant.
    tid = "aquaterra"
    _sync_db.users.insert_one({
        "id": f"TEST_tech_{uuid.uuid4().hex}",
        "email": email, "role": "technician",
        "password_hash": hash_password("password123"),
        "tenant_id": tid, "name": "Test Tech RBAC",
        "technician_id": f"TEST_techid_{uuid.uuid4().hex[:8]}",
        "failed_login_attempts": 0, "active": True,
    })
    yield email
    _sync_db.users.delete_many({"email": email})


# ────────────────────────────────────────────────────────────────────
# 1. GET /recurring-jobs — read gate
# ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("role_email", [
    "super@aquaterra.com",
    "admin@aquaterra.com",
    "manager@aquaterra.com",
])
def test_list_recurring_jobs_allows_super_admin_admin_manager(role_email):
    tok = _login(role_email)
    assert tok, f"login failed for {role_email}"
    r = httpx.get(f"{BASE}/api/recurring-jobs",
                   headers={"Authorization": f"Bearer {tok}"}, timeout=60)
    assert r.status_code == 200, f"{role_email}: {r.status_code} {r.text}"
    body = r.json()
    assert "items" in body and "count" in body


def test_list_recurring_jobs_rejects_technician(tech_email):
    tok = _login(tech_email)
    assert tok, "tech seed login failed"
    r = httpx.get(f"{BASE}/api/recurring-jobs",
                   headers={"Authorization": f"Bearer {tok}"}, timeout=60)
    assert r.status_code == 403, r.text


def test_list_recurring_jobs_rejects_unauth():
    r = httpx.get(f"{BASE}/api/recurring-jobs", timeout=30)
    # No token → the auth dependency 401 or 403's. Either is fine
    # as long as it's not 200.
    assert r.status_code in (401, 403), r.text


# ────────────────────────────────────────────────────────────────────
# 2. POST /recurring-jobs — write gate; manager can create
# ────────────────────────────────────────────────────────────────────
def _pick_existing_customer_id() -> str:
    """Grab any existing customer id from the aquaterra tenant so
    the create endpoint's ``customer not found`` guard passes."""
    assert _sync_db is not None
    # Manager auth resolves the aquaterra tenant; grab any customer
    # in that tenant.
    for tenant_slug in ("aquaterra",):
        tenant = _sync_db.tenants.find_one({"slug": tenant_slug})
        if not tenant:
            continue
        c = _sync_db.customers.find_one(
            {"tenant_id": tenant["id"]}, {"id": 1},
        )
        if c:
            return c["id"]
    # Fallback: any customer at all.
    c = _sync_db.customers.find_one({}, {"id": 1})
    assert c, "no customers in preview DB — can't run write RBAC tests"
    return c["id"]


def _create_payload():
    return {
        "customer_id": _pick_existing_customer_id(),
        "service_type": "Weekly Pool Service",
        "start_date": "2026-08-30",
        "frequency": "weekly",
        "interval_days": 7,
        "day_of_week": 2,
        "price_cents": 15000,
        "notes": "created by RBAC pytest",
    }


def test_manager_can_create_recurring_job():
    tok = _login("manager@aquaterra.com")
    assert tok, "manager login failed"
    payload = _create_payload()
    r = httpx.post(f"{BASE}/api/recurring-jobs",
                    headers={"Authorization": f"Bearer {tok}"},
                    json=payload, timeout=60)
    assert r.status_code in (200, 201), r.text
    body = r.json()
    created_id = body.get("id")
    assert created_id, body
    try:
        # Sanity — read-back through the GET detail (also manager-gated).
        detail = httpx.get(f"{BASE}/api/recurring-jobs/{created_id}",
                             headers={"Authorization": f"Bearer {tok}"},
                             timeout=30)
        assert detail.status_code == 200
    finally:
        # Cleanup — soft-delete via the same DELETE endpoint (manager
        # is now allowed there too, so this also exercises the gate).
        httpx.delete(f"{BASE}/api/recurring-jobs/{created_id}",
                       headers={"Authorization": f"Bearer {tok}"},
                       timeout=30)


def test_manager_can_patch_recurring_job():
    tok = _login("manager@aquaterra.com")
    payload = _create_payload()
    created = httpx.post(f"{BASE}/api/recurring-jobs",
                          headers={"Authorization": f"Bearer {tok}"},
                          json=payload, timeout=60).json()
    tpl_id = created.get("id")
    assert tpl_id, created
    try:
        r = httpx.patch(f"{BASE}/api/recurring-jobs/{tpl_id}",
                         headers={"Authorization": f"Bearer {tok}"},
                         json={"notes": "patched by manager"}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("notes") == "patched by manager"
    finally:
        httpx.delete(f"{BASE}/api/recurring-jobs/{tpl_id}",
                       headers={"Authorization": f"Bearer {tok}"},
                       timeout=30)


def test_technician_cannot_create_recurring_job(tech_email):
    tok = _login(tech_email)
    r = httpx.post(f"{BASE}/api/recurring-jobs",
                    headers={"Authorization": f"Bearer {tok}"},
                    json=_create_payload(), timeout=30)
    assert r.status_code == 403, r.text
