"""Feb-2026 · P4 — pinned soft-delete read-filter tests for /api/jobs.

Coverage-only phase. NO router changes. Four assertions locking in the
current read-filter contract so future edits can't silently unhide
deleted jobs:

  1. ``GET /api/jobs`` — default response excludes soft-deleted rows.
  2. ``GET /api/jobs/{jid}`` — soft-deleted docs return 404.
     ⚠️ MARKED ``xfail(strict=True)``. Discovery grep proved this
     handler at ``routers/jobs.py:878-901`` does NOT apply the
     ``deleted_at`` filter — it returns the soft-deleted doc as-is.
     Per the P4 spec ("STOP and flag if a real bug shows up, do not
     fix in this phase") we PIN the assertion here so CI documents
     the gap. When the fix lands the test will XPASS and CI will
     tell the maintainer to remove the xfail decorator.
  3. ``?include_deleted=true`` — surfaces soft-deleted jobs for
     ``super_admin``; silently ignored for lower roles.
  4. Cross-tenant isolation — tenant A soft-deleting one of its jobs
     doesn't leak into tenant B's list, and tenant B's own non-deleted
     job stays visible.

Follows the ``test_route_optimization_approval.py`` conventions —
live HTTP + sync ``pymongo`` for setup + assertions.
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
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


@pytest.fixture
def admin_h():
    return _hdrs("admin@aquaterra.com")


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one({"email": "admin@aquaterra.com"})["tenant_id"]


def _seed_job(tid: str, *, deleted: bool = False) -> str:
    jid = f"TEST_p4_j_{uuid.uuid4().hex[:8]}"
    doc = {
        "id": jid, "tenant_id": tid,
        "title": "TEST P4 soft-delete",
        "customer_name": "TEST cust",
        "service_type": "pool",
        "status": "scheduled",
        "scheduled_date": "2026-06-01",
        "created_at": "2026-06-01T09:00:00+00:00",
    }
    if deleted:
        doc["deleted_at"] = "2026-06-01T10:00:00+00:00"
    _sync.jobs.insert_one(doc)
    return jid


def _cleanup(ids: list[str]) -> None:
    if ids:
        _sync.jobs.delete_many({"id": {"$in": ids}})


# ── 1. Default list excludes soft-deleted ─────────────────────────
def test_list_jobs_excludes_soft_deleted_by_default(admin_h, aquaterra_tid):
    tid = aquaterra_tid
    alive_1 = _seed_job(tid, deleted=False)
    alive_2 = _seed_job(tid, deleted=False)
    gone = _seed_job(tid, deleted=True)
    try:
        r = requests.get(f"{API}/jobs", headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        rows = r.json()
        ids = {j["id"] for j in rows}
        assert alive_1 in ids
        assert alive_2 in ids
        assert gone not in ids, (
            "soft-deleted job leaked into the default list — read filter regressed"
        )
    finally:
        _cleanup([alive_1, alive_2, gone])


# ── 2. Get-by-id · 404 on soft-deleted ─────────────────────────────
def test_get_job_by_id_returns_404_when_soft_deleted(admin_h, aquaterra_tid):
    """P4.5 — soft-delete gate landed on ``get_job()``; the xfail was
    lifted and this test now proves the non-super-admin branch (stock
    404 so the mere existence of the soft-deleted row doesn't leak)."""
    tid = aquaterra_tid
    gone = _seed_job(tid, deleted=True)
    try:
        r = requests.get(f"{API}/jobs/{gone}", headers=admin_h, timeout=15)
        assert r.status_code == 404, (
            f"expected 404 for soft-deleted job, got {r.status_code}: {r.text}"
        )
    finally:
        _cleanup([gone])


def test_get_job_by_id_returns_409_when_soft_deleted_for_super_admin(aquaterra_tid):
    """Super_admin gets a 409 with ``detail == "job_soft_deleted"`` so
    restore tooling can distinguish "row is gone" (404) from "row is
    soft-deleted, restore first" (409). Sibling of the 404 test above."""
    from utils import hash_password
    su_email = f"test_p45_su_{uuid.uuid4().hex[:6]}@example.com"
    su_id = f"test_p45_su_{uuid.uuid4().hex[:8]}"
    tid = aquaterra_tid
    _sync.users.insert_one({
        "id": su_id, "tenant_id": tid, "email": su_email,
        "name": "TEST P4.5 super admin", "role": "super_admin",
        "active": True, "password_hash": hash_password("password123"),
    })
    gone = _seed_job(tid, deleted=True)
    try:
        su_h = _hdrs(su_email)
        r = requests.get(f"{API}/jobs/{gone}", headers=su_h, timeout=15)
        assert r.status_code == 409, (
            f"expected 409 for super_admin on soft-deleted job, "
            f"got {r.status_code}: {r.text}"
        )
        body = r.json()
        # FastAPI wraps HTTPException(detail=dict) as ``{"detail": {...}}``.
        inner = body.get("detail") or {}
        if isinstance(inner, dict):
            assert inner.get("detail") == "job_soft_deleted", inner
        else:
            assert inner == "job_soft_deleted", body
    finally:
        _cleanup([gone])
        _sync.users.delete_one({"id": su_id})


# ── 3. ?include_deleted=true surfaces soft-deleted (super_admin) ──
def test_include_deleted_query_param_surfaces_soft_deleted_for_super_admin(
    admin_h, aquaterra_tid,
):
    """The escape hatch on ``/jobs`` is guarded by ``role == super_admin``
    per ``jobs.py:335``. Non-super-admins passing the flag are silently
    ignored (defense in depth). This test seeds a synthetic super_admin
    at fixture time so the pin doesn't depend on the demo seed shape.
    """
    from utils import hash_password
    su_email = f"test_p4_su_{uuid.uuid4().hex[:6]}@example.com"
    su_id = f"test_p4_su_{uuid.uuid4().hex[:8]}"
    tid = aquaterra_tid
    _sync.users.insert_one({
        "id": su_id, "tenant_id": tid, "email": su_email,
        "name": "TEST P4 super admin", "role": "super_admin",
        "active": True, "password_hash": hash_password("password123"),
    })
    gone = _seed_job(tid, deleted=True)
    try:
        su_h = _hdrs(su_email)
        # Default — soft-deleted still hidden.
        r_default = requests.get(f"{API}/jobs", headers=su_h, timeout=15)
        assert r_default.status_code == 200
        assert gone not in {j["id"] for j in r_default.json()}
        # Flag on — surfaces the soft-deleted row for super_admin.
        r_incl = requests.get(f"{API}/jobs?include_deleted=true",
                                headers=su_h, timeout=15)
        assert r_incl.status_code == 200
        assert gone in {j["id"] for j in r_incl.json()}, (
            "?include_deleted=true failed to surface the soft-deleted row "
            "for super_admin"
        )
        # Same flag but a non-super_admin — must be silently ignored.
        r_lower = requests.get(f"{API}/jobs?include_deleted=true",
                                 headers=admin_h, timeout=15)
        assert r_lower.status_code == 200
        assert gone not in {j["id"] for j in r_lower.json()}, (
            "non-super_admin was granted the escape hatch — permission leak"
        )
    finally:
        _cleanup([gone])
        _sync.users.delete_one({"id": su_id})


# ── 4. Cross-tenant isolation vs soft-delete filter ───────────────
def test_cross_tenant_soft_delete_isolation(admin_h, aquaterra_tid):
    """Tenant A soft-deletes one job. Tenant B (separate tenant) must:
    (a) still see its OWN non-deleted job in its listing,
    (b) never see tenant A's job (deleted OR not) — the soft-delete
        filter must not bypass tenant scope by any read path.
    """
    from utils import hash_password
    other_tid = f"test_p4_tenant_{uuid.uuid4().hex[:8]}"
    other_email = f"test_p4_admin_{uuid.uuid4().hex[:6]}@example.com"
    _sync.tenants.insert_one({"id": other_tid, "name": "TEST_p4_tenant", "active": True})
    _sync.users.insert_one({
        "id": f"test_p4_u_{uuid.uuid4().hex[:8]}",
        "tenant_id": other_tid, "email": other_email,
        "name": "TEST P4 tenant admin", "role": "admin",
        "active": True, "password_hash": hash_password("password123"),
    })

    tid_a = aquaterra_tid
    a_alive = _seed_job(tid_a, deleted=False)
    a_gone = _seed_job(tid_a, deleted=True)
    b_alive = _seed_job(other_tid, deleted=False)
    try:
        # Tenant B's admin lists their own jobs.
        b_h = _hdrs(other_email)
        r_b = requests.get(f"{API}/jobs", headers=b_h, timeout=15)
        assert r_b.status_code == 200, r_b.text
        b_ids = {j["id"] for j in r_b.json()}
        assert b_alive in b_ids, "tenant B's own alive job dropped from listing"
        assert a_alive not in b_ids, (
            "tenant A's alive job leaked into tenant B's list — tenant scope broken"
        )
        assert a_gone not in b_ids, (
            "tenant A's soft-deleted job leaked into tenant B's list — "
            "soft-delete filter bypassed tenant scope"
        )
    finally:
        _cleanup([a_alive, a_gone, b_alive])
        _sync.users.delete_many({"email": other_email})
        _sync.tenants.delete_one({"id": other_tid})
