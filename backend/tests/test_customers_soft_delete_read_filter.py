"""Feb-2026 · P25 — soft-delete read-filter tests for /api/customers.

Mirrors the P4/P4.5 job soft-delete pins.  Assertions:

  1. ``GET /api/customers`` — default response excludes soft-deleted
     customers.
  2. ``GET /api/customers/{cid}`` — soft-deleted docs return 404 for
     non-super_admin.
  3. ``GET /api/customers/{cid}`` — super_admin gets a 409
     ``customer_soft_deleted`` so restore tooling knows the row exists.
  4. ``?include_deleted=true`` — super_admin surfaces the soft-deleted
     row; non-super_admin (admin, technician) is rejected 403.
  5. Cross-tenant isolation — tenant A soft-deleting one of its
     customers doesn't affect tenant B's list, and tenant B's own
     non-deleted customer stays visible.
  6. P11b anonymized customers (``deleted_at`` + ``anonymized_at``)
     are hidden too — proving the filter matches every write path.

Live HTTP + sync ``pymongo`` for setup, following the
``test_jobs_soft_delete_read_filter.py`` conventions.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


@pytest.fixture
def super_h():
    return _hdrs("super@aquaterra.com")


@pytest.fixture
def admin_h():
    return _hdrs("admin@aquaterra.com")


@pytest.fixture
def tech_h():
    return _hdrs("mike@aquaterra.com")


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one(
        {"email": "admin@aquaterra.com"})["tenant_id"]


def _seed_customer(tid: str, *, deleted: bool = False,
                     anonymized: bool = False) -> str:
    cid = f"TEST_p25_c_{uuid.uuid4().hex[:8]}"
    doc = {
        "id": cid, "tenant_id": tid,
        "name": f"TEST P25 {'(deleted)' if deleted else '(active)'}",
        "email": f"{cid}@example.com",
        "phone": "6235550100",
        "address": "1 Test St",
        "created_at": "2026-06-01T09:00:00+00:00",
    }
    if deleted:
        doc["deleted_at"] = "2026-06-01T10:00:00+00:00"
    if anonymized:
        # Mirror the P11b anonymization write path: name/email/phone
        # scrubbed, deleted_at + anonymized_at stamped.
        doc["name"] = "Deleted Customer"
        doc["email"] = None
        doc["phone"] = None
        doc["address"] = None
        doc["deleted_at"] = "2026-06-01T10:00:00+00:00"
        doc["anonymized_at"] = "2026-06-01T10:00:00+00:00"
    _sync.customers.insert_one(doc)
    return cid


def _cleanup(ids: list[str]) -> None:
    if ids:
        _sync.customers.delete_many({"id": {"$in": ids}})


# ─── 1. List excludes soft-deleted by default ────────────────────────

def test_list_customers_excludes_soft_deleted_by_default(admin_h, aquaterra_tid):
    active_id = _seed_customer(aquaterra_tid, deleted=False)
    deleted_id = _seed_customer(aquaterra_tid, deleted=True)
    try:
        r = requests.get(f"{API}/customers", headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        ids = {row["id"] for row in r.json()}
        assert active_id in ids, "active customer should appear in list"
        assert deleted_id not in ids, \
            "soft-deleted customer must NOT leak into list"
    finally:
        _cleanup([active_id, deleted_id])


# ─── 2. Detail 404 for non-super_admin ───────────────────────────────

def test_get_customer_by_id_returns_404_when_soft_deleted_for_non_super_admin(
    admin_h, aquaterra_tid,
):
    deleted_id = _seed_customer(aquaterra_tid, deleted=True)
    try:
        r = requests.get(f"{API}/customers/{deleted_id}",
                            headers=admin_h, timeout=15)
        assert r.status_code == 404, r.text
        assert r.json().get("detail") == "Customer not found"
    finally:
        _cleanup([deleted_id])


# ─── 3. Detail 409 for super_admin ───────────────────────────────────

def test_get_customer_by_id_returns_409_when_soft_deleted_for_super_admin(
    super_h, aquaterra_tid,
):
    deleted_id = _seed_customer(aquaterra_tid, deleted=True)
    try:
        r = requests.get(f"{API}/customers/{deleted_id}",
                            headers=super_h, timeout=15)
        assert r.status_code == 409, r.text
        body = r.json().get("detail") or {}
        # Detail is a dict (matches the P4.5 job 409 shape).
        assert isinstance(body, dict), body
        assert body.get("detail") == "customer_soft_deleted"
    finally:
        _cleanup([deleted_id])


# ─── 4. include_deleted=true is super_admin-only ─────────────────────

def test_include_deleted_query_param_surfaces_soft_deleted_for_super_admin_only(
    super_h, admin_h, tech_h, aquaterra_tid,
):
    deleted_id = _seed_customer(aquaterra_tid, deleted=True)
    try:
        # super_admin sees the row.
        r = requests.get(f"{API}/customers?include_deleted=true",
                            headers=super_h, timeout=15)
        assert r.status_code == 200, r.text
        ids = {row["id"] for row in r.json()}
        assert deleted_id in ids, \
            "super_admin with include_deleted must see soft-deleted rows"

        # admin (non-super) is rejected 403 — silent-ignore is a footgun.
        r_admin = requests.get(f"{API}/customers?include_deleted=true",
                                  headers=admin_h, timeout=15)
        assert r_admin.status_code == 403, r_admin.text

        # technician is also rejected.
        r_tech = requests.get(f"{API}/customers?include_deleted=true",
                                 headers=tech_h, timeout=15)
        assert r_tech.status_code == 403, r_tech.text
    finally:
        _cleanup([deleted_id])


# ─── 5. Cross-tenant isolation ───────────────────────────────────────

def test_cross_tenant_soft_delete_isolation(admin_h, aquaterra_tid):
    """Seed a soft-deleted row in a foreign tenant + an active row in
    the caller's tenant. The list must only surface the caller's own
    active row."""
    foreign_tid = f"tenant_p25_{uuid.uuid4().hex[:8]}"
    foreign_deleted = _seed_customer(foreign_tid, deleted=True)
    active_id = _seed_customer(aquaterra_tid, deleted=False)
    try:
        r = requests.get(f"{API}/customers", headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        ids = {row["id"] for row in r.json()}
        assert active_id in ids
        assert foreign_deleted not in ids, \
            "foreign-tenant soft-deleted customer must never leak in"
    finally:
        _cleanup([active_id, foreign_deleted])


# ─── 6. P11b anonymized rows are hidden ──────────────────────────────

def test_anonymized_customer_from_p11b_also_hidden(admin_h, super_h, aquaterra_tid):
    """P11b account deletion stamps ``deleted_at`` + ``anonymized_at``
    and scrubs the PII fields. The list filter must hide these rows
    the same way it hides admin-driven soft-deletes."""
    anon_id = _seed_customer(aquaterra_tid, anonymized=True)
    try:
        # Not in the default list.
        r = requests.get(f"{API}/customers", headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        ids = {row["id"] for row in r.json()}
        assert anon_id not in ids, \
            "P11b anonymized customer must NOT surface in list"

        # 404 on detail for admin.
        r_det = requests.get(f"{API}/customers/{anon_id}",
                                headers=admin_h, timeout=15)
        assert r_det.status_code == 404, r_det.text

        # 409 on detail for super_admin (restore branch).
        r_sup = requests.get(f"{API}/customers/{anon_id}",
                                headers=super_h, timeout=15)
        assert r_sup.status_code == 409, r_sup.text
        assert r_sup.json().get("detail", {}).get("detail") == \
            "customer_soft_deleted"
    finally:
        _cleanup([anon_id])
