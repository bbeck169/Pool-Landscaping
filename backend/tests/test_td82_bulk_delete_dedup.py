"""TD-82-calendar-consolidate · Feb-2026.

Phase 2A — shim retire of ``POST /jobs/bulk-soft-delete``.

The outlier endpoint at ``routers/jobs.py:4253`` is replaced with a
thin shim that delegates to the canonical ``_generic_bulk_delete`` +
``_job_locked`` from ``routers/bulk_crm.py``. Response envelope is
reshaped back to the legacy shape so mobile ``calendar.tsx:617``
keeps working until its own follow-up migration lands.

Phase 2B (future) will convert the shim to a 410 Gone once the
mobile follow-up (``TD-82-mobile-calendar-bulk``) ships.

Covers:
  * Shim delegates to canonical pipeline (semantic parity).
  * Legacy response shape ``{ok, count, deleted, failed[{job_id, …}]}``
    preserved bit-for-bit — mobile relies on it.
  * Soft-delete semantics unchanged (``deleted_at`` set, row stays
    in collection).
  * Legacy 100-row cap preserved (tighter than canonical 400).
  * RBAC gate holds (``require_admin_or_manager``).
  * Tenant isolation preserved — can't soft-delete other tenant's
    jobs via the shim.
"""
from __future__ import annotations

import os
import uuid
from typing import Dict

import httpx
import pytest
from dotenv import dotenv_values
from tests._shared_mongo import shared_db as _shared_db


BASE = "http://localhost:8001"
_ENV = dotenv_values("/app/backend/.env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = _shared_db() if (_MONGO_URL and _DB_NAME) else None


def _mk_tenant(prefix: str = "TEST_td82shim") -> str:
    tid = f"{prefix}_tenant_{uuid.uuid4().hex}"
    _sync.tenants.insert_one({
        "id": tid, "slug": f"td82shim-{uuid.uuid4().hex[:8]}",
        "name": "TD82shim Tenant", "active": True,
    })
    return tid


def _mk_user(tid: str, role: str = "admin") -> str:
    from utils import hash_password
    email = f"td82shim-{role}-{uuid.uuid4().hex[:8]}@example.com"
    _sync.users.insert_one({
        "id": f"TEST_td82shim_user_{uuid.uuid4().hex}",
        "email": email, "role": role,
        "password_hash": hash_password("password123"),
        "tenant_id": tid, "name": f"TD82shim {role}",
        "failed_login_attempts": 0, "active": True,
    })
    return email


def _login(email: str) -> str:
    r = httpx.post(f"{BASE}/api/auth/login", json={
        "email": email, "password": "password123",
    }, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _mk_job(tid: str, *, status: str = "pending") -> str:
    jid = f"TEST_td82shim_job_{uuid.uuid4().hex}"
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "title": "Shim Fixture Job",
        "status": status,
        "created_at": "2026-02-01T00:00:00+00:00",
    })
    return jid


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_ctx():
    tid = _mk_tenant()
    yield {"tid": tid, "token": _login(_mk_user(tid, "admin"))}


# ──────────────────────────────────────────────────────────────────
# Shim delegation + legacy response shape
# ──────────────────────────────────────────────────────────────────
def test_shim_delegates_and_returns_legacy_shape(admin_ctx):
    """Shim must preserve legacy response envelope
    ``{ok, count, deleted, failed[{job_id, reason, status_code}]}``
    bit-for-bit — mobile calendar.tsx depends on this shape."""
    tid = admin_ctx["tid"]
    good1 = _mk_job(tid, status="pending")
    good2 = _mk_job(tid, status="pending")
    bad = f"TEST_td82shim_job_nonexistent_{uuid.uuid4().hex}"
    r = httpx.post(f"{BASE}/api/jobs/bulk-soft-delete",
                    json={"job_ids": [good1, good2, bad]},
                    headers=_auth(admin_ctx["token"]), timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    # Legacy shape: top-level keys must be exactly {ok, count, deleted, failed}.
    assert set(body.keys()) == {"ok", "count", "deleted", "failed"}
    assert body["ok"] is True
    assert body["count"] == 2
    assert good1 in body["deleted"] and good2 in body["deleted"]
    # Legacy failed shape: entry has job_id (NOT id), reason, status_code.
    assert len(body["failed"]) == 1
    failed = body["failed"][0]
    assert set(failed.keys()) == {"job_id", "reason", "status_code"}
    assert failed["job_id"] == bad
    assert failed["status_code"] == 404


def test_shim_actually_soft_deletes_via_canonical(admin_ctx):
    """Shim must actually flip ``deleted_at`` on the job rows
    (proves the delegation isn't a no-op response spoof)."""
    tid = admin_ctx["tid"]
    jid = _mk_job(tid, status="pending")
    r = httpx.post(f"{BASE}/api/jobs/bulk-soft-delete",
                    json={"job_ids": [jid]},
                    headers=_auth(admin_ctx["token"]), timeout=30)
    assert r.status_code == 200
    # DB check — ``deleted_at`` must be set (soft, not hard).
    doc = _sync.jobs.find_one({"id": jid})
    assert doc is not None, "shim must NOT hard-delete the row"
    assert doc.get("deleted_at"), "deleted_at must be stamped by delegate"
    assert doc.get("deleted_by_user_id"), "canonical audit field must be present"


# ──────────────────────────────────────────────────────────────────
# Legacy constraints preserved
# ──────────────────────────────────────────────────────────────────
def test_shim_100_row_cap_preserved(admin_ctx):
    """Legacy cap=100 preserved (tighter than canonical _CAP=400)."""
    r = httpx.post(f"{BASE}/api/jobs/bulk-soft-delete",
                    json={"job_ids": [f"x{i}" for i in range(101)]},
                    headers=_auth(admin_ctx["token"]), timeout=30)
    assert r.status_code == 400
    assert "100" in str(r.json().get("detail", ""))


def test_shim_empty_list_400(admin_ctx):
    r = httpx.post(f"{BASE}/api/jobs/bulk-soft-delete",
                    json={"job_ids": []},
                    headers=_auth(admin_ctx["token"]), timeout=30)
    assert r.status_code == 400


# ──────────────────────────────────────────────────────────────────
# RBAC gate
# ──────────────────────────────────────────────────────────────────
def test_shim_rbac_field_tech_403():
    tid = _mk_tenant("TEST_td82shim_rbac")
    tok = _login(_mk_user(tid, role="technician"))
    jid = _mk_job(tid, status="pending")
    r = httpx.post(f"{BASE}/api/jobs/bulk-soft-delete",
                    json={"job_ids": [jid]},
                    headers=_auth(tok), timeout=30)
    # ``require_admin_or_manager`` → field tech 403.
    assert r.status_code == 403


# ──────────────────────────────────────────────────────────────────
# Tenant isolation
# ──────────────────────────────────────────────────────────────────
def test_shim_tenant_isolation(admin_ctx):
    """Admin from tenant A cannot soft-delete a job from tenant B."""
    other_tid = _mk_tenant("TEST_td82shim_other")
    other_jid = _mk_job(other_tid, status="pending")
    r = httpx.post(f"{BASE}/api/jobs/bulk-soft-delete",
                    json={"job_ids": [other_jid]},
                    headers=_auth(admin_ctx["token"]), timeout=30)
    assert r.status_code == 200
    body = r.json()
    # Tenant A sees tenant B's job as "Not found" via the canonical
    # ``_generic_bulk_delete`` tenant-scoped find_one.
    assert body["count"] == 0
    assert len(body["failed"]) == 1
    assert body["failed"][0]["job_id"] == other_jid
    # DB confirms: tenant B's job still has no deleted_at.
    doc = _sync.jobs.find_one({"id": other_jid})
    assert not doc.get("deleted_at")
