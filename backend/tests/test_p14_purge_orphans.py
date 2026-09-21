"""Phase P14 · Feb-2026 · Item 2 — Recurring-jobs orphan PURGE.

Locks in the acceptance points:

  * Happy path — an admin can purge orphaned recurring_job_templates
    (customer_id no longer resolves). Response returns
    ``deleted_count + purged_ids``, audit rows are written.
  * Non-admin (manager) → 403.
  * Tenant isolation — a purge in tenant A doesn't touch tenant B.
  * Audit rows land in ``deletion_audit`` with the right
    ``resource_type`` and ``bulk_op_id`` grouping.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import bcrypt
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_h() -> dict:
    return {"Authorization":
             f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def other_tenant_admin(dbc):
    """Seed a fresh cross-tenant admin for isolation testing."""
    tid = "p14-cross-t-" + uuid.uuid4().hex[:8]
    uid = str(uuid.uuid4())
    email = f"admin+{tid}@p14.example"
    dbc.tenants.insert_one({
        "id": tid, "name": "P14 Cross-Tenant", "slug": tid, "active": True,
    })
    dbc.users.insert_one({
        "id": uid, "email": email,
        "password_hash": bcrypt.hashpw(b"password123", bcrypt.gensalt(rounds=4)).decode(),
        "tenant_id": tid, "role": "admin",
        "name": "P14 Cross Admin", "is_active": True,
    })
    try:
        tok = _login(email, "password123")["access_token"]
        yield {"tenant_id": tid, "user_id": uid,
                "headers": {"Authorization": f"Bearer {tok}"}}
    finally:
        dbc.users.delete_one({"id": uid})
        dbc.tenants.delete_one({"id": tid})


@pytest.fixture
def _cleanup(dbc):
    bag: dict = {"templates": [], "customers": [], "audit_bulk_ops": []}
    yield bag
    for tid in bag["templates"]:
        dbc.recurring_job_templates.delete_one({"id": tid})
    for cid in bag["customers"]:
        dbc.customers.delete_one({"id": cid})
    for bop in bag["audit_bulk_ops"]:
        dbc.deletion_audit.delete_many({"bulk_op_id": bop})


def _seed_orphan(dbc, tenant_id: str, cleanup) -> str:
    """Insert a recurring_job_template pointing at a non-existent
    customer id. Returns the template id."""
    tpl_id = str(uuid.uuid4())
    dbc.recurring_job_templates.insert_one({
        "id": tpl_id, "tenant_id": tenant_id,
        "customer_id": f"ghost-customer-{uuid.uuid4().hex[:6]}",
        "customer_name": "Ghost Customer",
        "service_type": "Weekly Pool Service",
        "frequency": "weekly",
        "is_active": True,
    })
    cleanup["templates"].append(tpl_id)
    return tpl_id


def _seed_good(dbc, tenant_id: str, cleanup) -> str:
    """Insert a recurring_job_template whose customer exists."""
    cid = str(uuid.uuid4())
    dbc.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "P14 Good Customer", "is_active": True,
    })
    cleanup["customers"].append(cid)
    tpl_id = str(uuid.uuid4())
    dbc.recurring_job_templates.insert_one({
        "id": tpl_id, "tenant_id": tenant_id,
        "customer_id": cid,
        "customer_name": "P14 Good Customer",
        "service_type": "Weekly Pool Service",
        "frequency": "weekly",
        "is_active": True,
    })
    cleanup["templates"].append(tpl_id)
    return tpl_id


# ── Preview ─────────────────────────────────────────────────────────
def test_p14_preview_returns_count_and_ids(admin_h, dbc, _cleanup):
    admin = dbc.users.find_one({"email": "admin@aquaterra.com"})
    tenant_id = admin["tenant_id"]

    orphan_a = _seed_orphan(dbc, tenant_id, _cleanup)
    orphan_b = _seed_orphan(dbc, tenant_id, _cleanup)
    _seed_good(dbc, tenant_id, _cleanup)  # not an orphan

    r = requests.get(
        f"{API}/recurring-jobs/purge-orphans-preview",
        headers=admin_h, timeout=15,
    )
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    ids = set(body.get("ids") or [])
    assert orphan_a in ids
    assert orphan_b in ids
    assert body.get("count") >= 2


# ── Happy path (admin) ──────────────────────────────────────────────
def test_p14_purge_admin_deletes_and_writes_audit(admin_h, dbc, _cleanup):
    admin = dbc.users.find_one({"email": "admin@aquaterra.com"})
    tenant_id = admin["tenant_id"]

    orphan_a = _seed_orphan(dbc, tenant_id, _cleanup)
    orphan_b = _seed_orphan(dbc, tenant_id, _cleanup)
    good = _seed_good(dbc, tenant_id, _cleanup)

    r = requests.post(
        f"{API}/recurring-jobs/purge-orphans",
        headers=admin_h, json={"confirm": "DELETE"}, timeout=20,
    )
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    purged = set(body.get("purged_ids") or [])
    assert orphan_a in purged
    assert orphan_b in purged
    assert good not in purged, "non-orphan was deleted (regression)"
    assert body.get("deleted_count") == len(purged)
    bulk_op_id = body.get("bulk_op_id")
    assert bulk_op_id, "expected bulk_op_id for forensic grouping"
    _cleanup["audit_bulk_ops"].append(bulk_op_id)

    # Audit rows persisted.
    audits = list(dbc.deletion_audit.find(
        {"bulk_op_id": bulk_op_id, "resource_type": "recurring_job"},
        {"_id": 0},
    ))
    assert len(audits) >= 2
    for a in audits:
        assert a.get("tenant_id") == tenant_id
        assert a.get("resource_id") in purged
        assert a.get("deletion_reason") == "purge_orphaned_customer_ref"

    # Rows really are gone.
    for tid in purged:
        assert dbc.recurring_job_templates.find_one({"id": tid}) is None


# ── Confirm string gate ─────────────────────────────────────────────
def test_p14_purge_rejects_without_confirm_delete(admin_h, dbc, _cleanup):
    admin = dbc.users.find_one({"email": "admin@aquaterra.com"})
    tenant_id = admin["tenant_id"]
    _seed_orphan(dbc, tenant_id, _cleanup)

    r = requests.post(
        f"{API}/recurring-jobs/purge-orphans",
        headers=admin_h, json={"confirm": "not-the-word"}, timeout=15,
    )
    assert r.status_code == 422
    assert "confirm_required" in r.text


# ── Non-admin (manager) 403 ─────────────────────────────────────────
def test_p14_purge_403_for_manager(dbc, _cleanup):
    """A user with role='manager' can preview (require_admin_or_manager)
    but MUST NOT be able to fire the destructive purge — the endpoint
    secondary-checks for ``admin`` and 403s on any other role."""
    admin = dbc.users.find_one({"email": "admin@aquaterra.com"})
    tenant_id = admin["tenant_id"]

    mgr_uid = str(uuid.uuid4())
    mgr_email = f"mgr-p14-{uuid.uuid4().hex[:6]}@p14.example"
    dbc.users.insert_one({
        "id": mgr_uid, "email": mgr_email,
        "password_hash": bcrypt.hashpw(b"password123", bcrypt.gensalt(rounds=4)).decode(),
        "tenant_id": tenant_id, "role": "manager",
        "name": "P14 Manager", "is_active": True,
    })
    try:
        tok = _login(mgr_email, "password123")["access_token"]
        r = requests.post(
            f"{API}/recurring-jobs/purge-orphans",
            headers={"Authorization": f"Bearer {tok}"},
            json={"confirm": "DELETE"}, timeout=15,
        )
        assert r.status_code == 403, r.text[:200]
        assert "admin_required" in r.text
    finally:
        dbc.users.delete_one({"id": mgr_uid})


# ── Tenant isolation ────────────────────────────────────────────────
def test_p14_purge_scoped_to_caller_tenant(
    other_tenant_admin, admin_h, dbc, _cleanup,
):
    """A purge fired from tenant B must not touch tenant A's orphans."""
    aqua = dbc.users.find_one({"email": "admin@aquaterra.com"})
    tenant_a = aqua["tenant_id"]
    tenant_b = other_tenant_admin["tenant_id"]

    orphan_a = _seed_orphan(dbc, tenant_a, _cleanup)  # in aquaterra
    orphan_b = _seed_orphan(dbc, tenant_b, _cleanup)  # in P14 cross-tenant

    r = requests.post(
        f"{API}/recurring-jobs/purge-orphans",
        headers=other_tenant_admin["headers"],
        json={"confirm": "DELETE"}, timeout=20,
    )
    assert r.status_code == 200, r.text[:200]
    purged_b = set(r.json().get("purged_ids") or [])
    _cleanup["audit_bulk_ops"].append(r.json().get("bulk_op_id"))
    assert orphan_b in purged_b, "tenant B's own orphan was NOT purged"
    assert orphan_a not in purged_b, (
        "SAFETY: tenant B's purge deleted a tenant A row"
    )
    # And tenant A's orphan is still there.
    assert dbc.recurring_job_templates.find_one({"id": orphan_a}) is not None
