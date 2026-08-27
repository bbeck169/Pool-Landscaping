"""Feb 2026 · Miguel Munoz P0 — duplicate-email login routing tests.

Coverage
--------
1. ``test_login_prefers_workforce_role_over_customer`` — seed a
   ``role=customer`` users record AND a ``role=technician`` users
   record with the SAME email + same password. Login must return
   ``user.role=="technician"`` (not "customer") so the web + mobile
   clients route to the workstream.
2. ``test_login_falls_back_to_customer_when_no_workforce_record`` —
   seed only a customer record; login returns ``user.role=="customer"``
   (regression preserved).
3. ``test_login_returns_tech_when_only_tech_record_exists`` — seed
   only a technician record; login returns ``user.role=="technician"``
   (existing behavior).
4. ``test_login_skips_soft_deleted_workforce_record`` — seed a
   soft-deleted (``deleted_at`` set) technician AND an active customer;
   login returns the customer (workforce-first only wins when the
   workforce record isn't soft-deleted).
5. ``test_admin_unlink_endpoint_dry_run_reports_customer_id`` — dry-run
   invocation reports the customer users id that WOULD be soft-deleted
   but doesn't write.
6. ``test_admin_unlink_endpoint_soft_deletes_customer_users_record`` —
   real run soft-deletes the customer users record; customers-collection
   doc is untouched; second call is a no-op.
7. ``test_admin_unlink_endpoint_rejects_non_super_admin`` — 403 for
   regular admin.
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
_sync_db = MongoClient(_MONGO_URL)[_DB_NAME] if (_MONGO_URL and _DB_NAME) else None


def _hash(pw: str) -> str:
    from utils import hash_password
    return hash_password(pw)


def _super_admin_token() -> str:
    r = httpx.post(f"{BASE}/api/auth/login", json={
        "email": "super@aquaterra.com", "password": "password123",
    }, timeout=60)
    r.raise_for_status()
    b = r.json()
    return b.get("access_token") or b.get("token") or ""


def _seed_user(*, email, role, password="password123", **extra):
    assert _sync_db is not None
    doc = {
        "id": f"TEST_{uuid.uuid4().hex}",
        "email": email,
        "role": role,
        "password_hash": _hash(password),
        "tenant_id": f"TEST_tenant_{uuid.uuid4().hex[:8]}",
        "name": extra.pop("name", f"Test {role}"),
        "failed_login_attempts": 0,
        "lockout_until": None,
        "active": True,
    }
    doc.update(extra)
    _sync_db.users.insert_one(doc)
    return doc


def _cleanup_email(email: str):
    if _sync_db is None:
        return
    _sync_db.users.delete_many({"email": email})
    _sync_db.customers.delete_many({"email": email})


# ────────────────────────────────────────────────────────────────────
# 1. Workforce role wins over customer when both exist
# ────────────────────────────────────────────────────────────────────
def test_login_prefers_workforce_role_over_customer():
    """The bug: Miguel had a customer users record AND a technician
    users record; ``find_one({email})`` returned the customer one,
    routing him to the portal. Fix: workforce records win."""
    email = f"test-dup-{uuid.uuid4().hex[:8]}@example.com"
    _seed_user(email=email, role="customer",
               customer_id="TEST_cust_" + uuid.uuid4().hex[:8])
    _seed_user(email=email, role="technician",
               technician_id="TEST_tech_" + uuid.uuid4().hex[:8],
               department="landscape_tech")
    try:
        r = httpx.post(f"{BASE}/api/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user"]["role"] == "technician", (
            f"expected technician, got {body['user']['role']}: {body}"
        )
        # Technician_id should be present (routes the mobile app to
        # the tech workstream).
        assert body["user"]["technician_id"] is not None
    finally:
        _cleanup_email(email)


# ────────────────────────────────────────────────────────────────────
# 2. Regression — customer-only records still route to portal
# ────────────────────────────────────────────────────────────────────
def test_login_falls_back_to_customer_when_no_workforce_record():
    email = f"test-cust-{uuid.uuid4().hex[:8]}@example.com"
    _seed_user(email=email, role="customer",
               customer_id="TEST_cust_" + uuid.uuid4().hex[:8])
    try:
        r = httpx.post(f"{BASE}/api/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=60)
        assert r.status_code == 200, r.text
        assert r.json()["user"]["role"] == "customer"
    finally:
        _cleanup_email(email)


# ────────────────────────────────────────────────────────────────────
# 3. Regression — tech-only records still route to workstream
# ────────────────────────────────────────────────────────────────────
def test_login_returns_tech_when_only_tech_record_exists():
    email = f"test-tech-{uuid.uuid4().hex[:8]}@example.com"
    _seed_user(email=email, role="technician",
               technician_id="TEST_tech_" + uuid.uuid4().hex[:8])
    try:
        r = httpx.post(f"{BASE}/api/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=60)
        assert r.status_code == 200, r.text
        assert r.json()["user"]["role"] == "technician"
    finally:
        _cleanup_email(email)


# ────────────────────────────────────────────────────────────────────
# 4. Soft-deleted workforce record is skipped — customer wins
# ────────────────────────────────────────────────────────────────────
def test_login_skips_soft_deleted_workforce_record():
    """A former tech who left the company (soft-deleted) but is now
    a paying customer should still be able to log in to the portal."""
    email = f"test-softd-{uuid.uuid4().hex[:8]}@example.com"
    _seed_user(email=email, role="technician",
               technician_id="TEST_tech_" + uuid.uuid4().hex[:8],
               deleted_at="2025-01-01T00:00:00+00:00")
    _seed_user(email=email, role="customer",
               customer_id="TEST_cust_" + uuid.uuid4().hex[:8])
    try:
        r = httpx.post(f"{BASE}/api/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=60)
        assert r.status_code == 200, r.text
        assert r.json()["user"]["role"] == "customer"
    finally:
        _cleanup_email(email)


# ────────────────────────────────────────────────────────────────────
# 5. Admin unlink endpoint — dry run
# ────────────────────────────────────────────────────────────────────
def test_admin_unlink_endpoint_dry_run_reports_customer_id():
    email = f"test-unlink-dry-{uuid.uuid4().hex[:8]}@example.com"
    tech = _seed_user(email=email, role="technician")
    cust = _seed_user(email=email, role="customer",
                       customer_id="TEST_cust_" + uuid.uuid4().hex[:8])
    try:
        tok = _super_admin_token()
        r = httpx.post(
            f"{BASE}/api/admin/migrations/unlink-tech-from-customer",
            headers={"Authorization": f"Bearer {tok}"},
            json={"email": email, "dry_run": True},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        report = r.json()
        assert report["email"] == email
        assert report["found_users_records"] == 2
        assert tech["id"] in report["workforce_records"]
        assert cust["id"] in report["customer_records_to_soft_delete"]
        assert report["customer_records_soft_deleted"] == []
        assert "dry_run_no_writes_performed" in report["actions"]

        # DB is unchanged.
        fresh = _sync_db.users.find_one({"id": cust["id"]})
        assert not fresh.get("deleted_at")
    finally:
        _cleanup_email(email)


# ────────────────────────────────────────────────────────────────────
# 6. Admin unlink endpoint — real run soft-deletes the customer users
# record; customers-collection doc untouched; second run is a no-op
# ────────────────────────────────────────────────────────────────────
def test_admin_unlink_endpoint_soft_deletes_customer_users_record():
    email = f"test-unlink-real-{uuid.uuid4().hex[:8]}@example.com"
    customer_collection_id = "TEST_customercoll_" + uuid.uuid4().hex[:8]
    tech = _seed_user(email=email, role="technician")
    cust = _seed_user(email=email, role="customer",
                       customer_id=customer_collection_id)
    # Also seed the parallel customers-collection doc — it must NOT
    # be touched (invoices/history still needs it).
    _sync_db.customers.insert_one({
        "id": customer_collection_id,
        "tenant_id": cust["tenant_id"],
        "email": email,
        "name": "Test Cust",
    })
    try:
        tok = _super_admin_token()
        r = httpx.post(
            f"{BASE}/api/admin/migrations/unlink-tech-from-customer",
            headers={"Authorization": f"Bearer {tok}"},
            json={"email": email, "dry_run": False},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        report = r.json()
        assert cust["id"] in report["customer_records_soft_deleted"]

        # Customer users record is soft-deleted.
        fresh = _sync_db.users.find_one({"id": cust["id"]})
        assert fresh.get("deleted_at")
        assert fresh.get("active") is False
        assert fresh.get("unlinked_by_migration", {}).get(
            "workforce_record_ids") == [tech["id"]]

        # customers-collection doc is UNTOUCHED (invoices etc. still
        # link here).
        cust_coll = _sync_db.customers.find_one({"id": customer_collection_id})
        assert cust_coll is not None
        assert not cust_coll.get("deleted_at")

        # Second call is a no-op — the only remaining active user is
        # the tech record.
        r2 = httpx.post(
            f"{BASE}/api/admin/migrations/unlink-tech-from-customer",
            headers={"Authorization": f"Bearer {tok}"},
            json={"email": email, "dry_run": False},
            timeout=60,
        )
        assert r2.status_code == 200
        assert r2.json()["customer_records_soft_deleted"] == []
    finally:
        _cleanup_email(email)


# ────────────────────────────────────────────────────────────────────
# 7. RBAC — non-super_admin gets 403
# ────────────────────────────────────────────────────────────────────
def test_admin_unlink_endpoint_rejects_non_super_admin():
    r = httpx.post(f"{BASE}/api/auth/login", json={
        "email": "admin@aquaterra.com", "password": "password123",
    }, timeout=60)
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok
    resp = httpx.post(
        f"{BASE}/api/admin/migrations/unlink-tech-from-customer",
        headers={"Authorization": f"Bearer {tok}"},
        json={"email": "someone@example.com", "dry_run": True},
        timeout=60,
    )
    assert resp.status_code == 403, resp.text
