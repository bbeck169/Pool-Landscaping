"""Feb-2026 · Dashboard Active/Inactive Customers tile — SECOND PASS.

Covers the REDEFINITION shipped in the Feb-2026 second pass:
customer-level ``is_active`` toggle (not the recurring-template
signal used in the first pass).

New contract:
  * Active   = ``is_active != False`` + not soft-deleted.
               Matches True + missing + null so legacy rows that
               never had ``is_active`` stamped still count as
               active (same read semantics as ``models.py:96`` +
               ``ActivationControl.jsx:33``).
  * Inactive = ``is_active == False`` + not muted (P28
               ``is_muted``) + not soft-deleted.
  * Muted-inactive rows EXCLUDED from both buckets.
  * Soft-deleted rows EXCLUDED from both buckets.
  * NO SUM INVARIANT — dropped in this pass.

Tests:
  1. Migration idempotent — creates + persists sentinel; force-run
     leaves the compound index intact.
  2. Active count matches ``is_active`` in (True, missing, null),
     soft-delete-guarded.
  3. Inactive count matches ``is_active == False`` + not muted +
     not soft-deleted.
  4. Muted inactive customer is EXCLUDED from both buckets.
  5. Soft-deleted customer is EXCLUDED from both buckets.
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


def _seed_customer(tid, name, *, is_active=True, is_muted=False,
                     deleted=False, omit_is_active=False):
    """Seed a customer row with the requested lifecycle state.

    ``omit_is_active=True`` deliberately DOES NOT write the
    ``is_active`` field — mirrors the 119 legacy rows on the demo
    tenant that never had the field stamped.
    """
    cid = f"TEST-actinact-c-{uuid.uuid4().hex[:6]}"
    doc = {"id": cid, "tenant_id": tid, "name": name}
    if not omit_is_active:
        doc["is_active"] = is_active
    if is_muted:
        doc["is_muted"] = True
    if deleted:
        from utils import now_iso
        doc["deleted_at"] = now_iso()
    _db.customers.insert_one(doc)
    return cid


def _cleanup(tid, uid):
    _db.users.delete_one({"id": uid})
    _db.tenants.delete_one({"id": tid})
    _db.customers.delete_many({"tenant_id": tid})


# ═════════════════════════════════════════════════════════════════════
# 1 · Migration idempotent + creates compound index
# ═════════════════════════════════════════════════════════════════════
def test_migration_creates_compound_index():
    """Sentinel-guarded migration writes the compound index the
    dashboard endpoint's ``count_documents`` queries piggyback on."""
    idxs = list(_db.customers.list_indexes())
    names = {i.get("name") for i in idxs}
    assert "customers_dashboard_active_inactive_idx" in names, (
        f"expected customers_dashboard_active_inactive_idx in {names}"
    )
    the_idx = next(i for i in idxs
                    if i.get("name") == "customers_dashboard_active_inactive_idx")
    keys = list(the_idx["key"].keys())
    assert keys == ["tenant_id", "is_active", "is_muted", "deleted_at"], keys


def test_migration_idempotent():
    """Force-run twice → both succeed; index still single-copy."""
    from services.migrations.customers_dashboard_active_inactive_idx import (
        run_customers_dashboard_active_inactive_idx_migration,
    )
    r1 = _loop_run(run_customers_dashboard_active_inactive_idx_migration(force=True))
    assert r1["status"] == "ok"
    r2 = _loop_run(run_customers_dashboard_active_inactive_idx_migration(force=True))
    assert r2["status"] == "ok"
    hits = [
        i for i in _db.customers.list_indexes()
        if i.get("name") == "customers_dashboard_active_inactive_idx"
    ]
    assert len(hits) == 1


# ═════════════════════════════════════════════════════════════════════
# 2 · Active count — True + missing + null all count
# ═════════════════════════════════════════════════════════════════════
def test_active_count_matches_true_missing_and_null():
    """Legacy rows with no ``is_active`` field MUST still count as
    active. This is the whole reason we picked Option A over a
    backfill migration (see /app/memory/PRD.md · Feb-2026 audit).
    """
    tid, uid, email = _seed_tenant()
    # 5 active in various shapes: explicit True, missing field, null.
    _seed_customer(tid, "A-true-1", is_active=True)
    _seed_customer(tid, "A-true-2", is_active=True)
    _seed_customer(tid, "A-missing", omit_is_active=True)
    # Explicit-None (rarely seen in practice but the model allows it).
    cid_null = f"TEST-actinact-c-{uuid.uuid4().hex[:6]}"
    _db.customers.insert_one({
        "id": cid_null, "tenant_id": tid, "name": "A-null",
        "is_active": None,
    })
    # 1 inactive (control).
    _seed_customer(tid, "I-false", is_active=False)
    try:
        tok = _login(email)
        r = requests.get(f"{API}/dashboard",
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["active_customers_count"] == 4, (
            f"expected 4 active (2 True + 1 missing + 1 null), got {d}"
        )
        assert d["inactive_customers_count"] == 1, d
    finally:
        _cleanup(tid, uid)


# ═════════════════════════════════════════════════════════════════════
# 3 · Inactive count — False + not muted + not soft-deleted
# ═════════════════════════════════════════════════════════════════════
def test_inactive_count_excludes_muted_and_soft_deleted():
    """3 active + 2 inactive-not-muted + 1 inactive-and-muted + 1
    soft-deleted (per the user's empirical proof spec). Query MUST
    return active=3, inactive=2."""
    tid, uid, email = _seed_tenant()
    # 3 active.
    _seed_customer(tid, "A1", is_active=True)
    _seed_customer(tid, "A2", is_active=True)
    _seed_customer(tid, "A3", is_active=True)
    # 2 inactive, not muted.
    _seed_customer(tid, "I1", is_active=False, is_muted=False)
    _seed_customer(tid, "I2", is_active=False, is_muted=False)
    # 1 inactive AND muted — MUST be excluded from BOTH buckets.
    _seed_customer(tid, "IM1", is_active=False, is_muted=True)
    # 1 soft-deleted (regardless of is_active) — MUST be excluded from BOTH.
    _seed_customer(tid, "D1", is_active=False, deleted=True)
    try:
        tok = _login(email)
        r = requests.get(f"{API}/dashboard",
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=15)
        d = r.json()
        assert d["active_customers_count"] == 3, d
        assert d["inactive_customers_count"] == 2, d
        # NO sum invariant — 4th and 5th rows are excluded from
        # both buckets. total_customers includes soft-deleted rows
        # per its unchanged legacy definition.
        assert d["active_customers_count"] + d["inactive_customers_count"] \
                < d["total_customers"], (
            "sum invariant intentionally dropped — muted-inactive + "
            "soft-deleted rows are excluded from both buckets"
        )
    finally:
        _cleanup(tid, uid)


# ═════════════════════════════════════════════════════════════════════
# 4 · Muted-inactive is excluded from BOTH buckets (regression guard)
# ═════════════════════════════════════════════════════════════════════
def test_muted_inactive_customer_excluded_from_both_buckets():
    """P28 muted lives in its own tab. A muted-inactive customer
    (``is_active=False`` + ``is_muted=True``) MUST NOT leak into
    either dashboard bucket."""
    tid, uid, email = _seed_tenant()
    # Just one row — muted + inactive.
    _seed_customer(tid, "IM-solo", is_active=False, is_muted=True)
    try:
        tok = _login(email)
        r = requests.get(f"{API}/dashboard",
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=15)
        d = r.json()
        assert d["active_customers_count"] == 0, d
        assert d["inactive_customers_count"] == 0, d
        # Muted customer still counts towards ``total_customers``
        # (legacy field, includes muted). Keeps the total in sync
        # with the customers page's "All" tab.
        assert d["total_customers"] == 1
    finally:
        _cleanup(tid, uid)


# ═════════════════════════════════════════════════════════════════════
# 5 · Soft-deleted excluded from BOTH buckets (regression guard)
# ═════════════════════════════════════════════════════════════════════
def test_soft_deleted_customer_excluded_from_both_buckets():
    """A soft-deleted customer with ANY ``is_active`` state MUST NOT
    leak into either dashboard bucket."""
    tid, uid, email = _seed_tenant()
    # One live active (baseline).
    _seed_customer(tid, "Live-A", is_active=True)
    # One soft-deleted but is_active=True (stale toggle).
    _seed_customer(tid, "Stale-A", is_active=True, deleted=True)
    # One soft-deleted with is_active=False.
    _seed_customer(tid, "Stale-I", is_active=False, deleted=True)
    try:
        tok = _login(email)
        r = requests.get(f"{API}/dashboard",
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=15)
        d = r.json()
        # Only the live-active row counts.
        assert d["active_customers_count"] == 1, d
        assert d["inactive_customers_count"] == 0, d
    finally:
        _cleanup(tid, uid)
