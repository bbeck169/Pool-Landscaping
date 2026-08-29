"""Feb-2026 · Dashboard Active/Inactive Customers tile swap coverage.

Covers:
  1. Migration idempotent — creates + persists sentinel; force-run
     leaves the compound index intact.
  2. ``active_customers_count`` matches distinct customer_ids with
     ``active=True`` recurring templates.
  3. ``inactive_customers_count`` = total_customers - active
     (sum invariant with the legacy ``total_customers`` field).
  4. Belt-and-suspenders: a soft-deleted customer with a stale
     ``active=True`` template does NOT leak into ``active`` count.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])
_db = _sync[os.environ["DB_NAME"]]


def _loop_run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _login(email: str) -> str:
    for _ in range(3):
        try:
            r = requests.post(f"{API}/auth/login",
                                json={"email": email, "password": "password123"},
                                timeout=30)
            if r.status_code == 200:
                return r.json()["access_token"]
        except requests.exceptions.RequestException:
            continue
    raise RuntimeError(f"login failed for {email}")


def _seed_tenant():
    from utils import hash_password
    tid = f"TEST-actinact-tenant-{uuid.uuid4().hex[:6]}"
    _db.tenants.insert_one({
        "id": tid, "slug": f"test-actinact-{uuid.uuid4().hex[:6]}",
        "name": "TEST_actinact", "active": True,
    })
    uid = f"TEST-actinact-u-{uuid.uuid4().hex[:6]}"
    email = f"admin-{uuid.uuid4().hex[:6]}@example.com"
    _db.users.insert_one({
        "id": uid, "tenant_id": tid, "email": email,
        "name": "TEST_actinact_admin", "role": "admin",
        "password_hash": hash_password("password123"),
    })
    return tid, uid, email


def _seed_customer(tid, name, *, deleted=False):
    cid = f"TEST-actinact-c-{uuid.uuid4().hex[:6]}"
    doc = {"id": cid, "tenant_id": tid, "name": name, "is_active": True}
    if deleted:
        from utils import now_iso
        doc["deleted_at"] = now_iso()
    _db.customers.insert_one(doc)
    return cid


def _seed_template(tid, cid, *, active=True):
    rid = f"TEST-actinact-rjt-{uuid.uuid4().hex[:6]}"
    _db.recurring_job_templates.insert_one({
        "id": rid, "tenant_id": tid, "customer_id": cid,
        "service_type": "pool_service", "frequency": "weekly",
        "active": active, "created_at": "2026-01-01T00:00:00Z",
    })
    return rid


def _cleanup(tid, uid):
    _db.users.delete_one({"id": uid})
    _db.tenants.delete_one({"id": tid})
    _db.customers.delete_many({"tenant_id": tid})
    _db.recurring_job_templates.delete_many({"tenant_id": tid})


# ═════════════════════════════════════════════════════════════════════
# 1 · Migration idempotent + creates compound index
# ═════════════════════════════════════════════════════════════════════
def test_migration_creates_compound_index():
    idxs = list(_db.recurring_job_templates.list_indexes())
    names = {i.get("name") for i in idxs}
    assert "rjt_tenant_active_customer_idx" in names, (
        f"expected rjt_tenant_active_customer_idx in {names}"
    )
    the_idx = next(i for i in idxs
                    if i.get("name") == "rjt_tenant_active_customer_idx")
    keys = list(the_idx["key"].keys())
    assert keys == ["tenant_id", "active", "customer_id"], keys


def test_migration_idempotent():
    """Force-run twice → both succeed; index still single-copy."""
    from services.migrations.recurring_templates_active_customer_idx import (
        run_recurring_templates_active_customer_idx_migration,
    )
    r1 = _loop_run(run_recurring_templates_active_customer_idx_migration(force=True))
    assert r1["status"] == "ok"
    r2 = _loop_run(run_recurring_templates_active_customer_idx_migration(force=True))
    assert r2["status"] == "ok"
    # Only ONE index with our name — no duplicates.
    hits = [
        i for i in _db.recurring_job_templates.list_indexes()
        if i.get("name") == "rjt_tenant_active_customer_idx"
    ]
    assert len(hits) == 1


# ═════════════════════════════════════════════════════════════════════
# 2-3 · Dashboard endpoint returns correct counts + sum invariant
# ═════════════════════════════════════════════════════════════════════
def test_dashboard_active_inactive_counts_and_sum_invariant():
    tid, uid, email = _seed_tenant()
    # Seed 5 customers · 3 with active templates, 1 with an inactive
    # template, 1 with no template.
    active_cids = [_seed_customer(tid, f"A{i}") for i in range(3)]
    inactive_no_template = _seed_customer(tid, "N1")
    inactive_disabled = _seed_customer(tid, "N2")
    for cid in active_cids:
        _seed_template(tid, cid, active=True)
    _seed_template(tid, inactive_disabled, active=False)
    try:
        tok = _login(email)
        r = requests.get(f"{API}/dashboard",
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["active_customers_count"] == 3, d
        assert d["inactive_customers_count"] == 2, d
        # Sum invariant: active + inactive == total_customers
        assert d["active_customers_count"] + d["inactive_customers_count"] \
               == d["total_customers"], d
        # Legacy fields still present (deprecation window).
        assert "total_technicians" in d
    finally:
        _cleanup(tid, uid)


# ═════════════════════════════════════════════════════════════════════
# 4 · Soft-deleted customer with stale active template — NO leak
# ═════════════════════════════════════════════════════════════════════
def test_soft_deleted_customer_does_not_leak_into_active():
    """Regression guard for the belt-and-suspenders filter — a
    soft-deleted customer whose recurring template still has
    ``active=True`` must count as INACTIVE."""
    tid, uid, email = _seed_tenant()
    # Live active customer (baseline).
    live_cid = _seed_customer(tid, "Live")
    _seed_template(tid, live_cid, active=True)
    # Soft-deleted customer with a stale active template (bug scenario).
    stale_cid = _seed_customer(tid, "Stale", deleted=True)
    _seed_template(tid, stale_cid, active=True)
    try:
        tok = _login(email)
        r = requests.get(f"{API}/dashboard",
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=15)
        d = r.json()
        # Only ``live_cid`` counts as active despite BOTH templates
        # having ``active=True``.
        assert d["active_customers_count"] == 1, d
        # ``total_customers`` counts BOTH (legacy behaviour includes
        # soft-deleted). Inactive folds the soft-deleted row in.
        assert d["total_customers"] == 2
        assert d["inactive_customers_count"] == 1
        # Sum invariant still holds.
        assert d["active_customers_count"] + d["inactive_customers_count"] \
               == d["total_customers"]
    finally:
        _cleanup(tid, uid)
