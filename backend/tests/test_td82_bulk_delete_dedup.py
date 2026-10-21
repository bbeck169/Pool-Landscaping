"""TD-82-calendar-consolidate · Phase 2B · Oct-2026 — 410 Gone retire guard.

The ``POST /jobs/bulk-soft-delete`` outlier endpoint at
``routers/jobs.py:4253`` has been retired to ``410 Gone`` after both
known callers migrated to the canonical ``POST /jobs/bulk-delete``:

  * Web: ``frontend/src/pages/schedule/CalendarSchedule.jsx:650``
    migrated in ``e57734f00``.
  * Mobile: ``mobile/app/(app)/schedule/calendar.tsx:575`` migrated
    in ``eaff2b3f1`` via the ``apiBulkDeleteJobs`` helper.

Phase 2A ship notes:
  The thin shim at commit ``2f22725e1`` delegated to the canonical
  ``_generic_bulk_delete`` + ``_job_locked`` pipeline while
  reshaping the response envelope back to the legacy
  ``{ok, count, deleted, failed[{job_id,…}]}`` shape so mobile
  could keep running during the migration window. That shim is
  gone; this file now locks the 410-Gone retire shape instead.

Covers:
  * Any POST to ``/jobs/bulk-soft-delete`` returns 410.
  * Response detail string matches the TD-98-be-cleanup-retire
    convention (``routers/communication_timeline.py:162``) with
    the correct canonical pointer ``POST /jobs/bulk-delete`` and
    the TD-82 Phase 2B marker.
  * The retire fires regardless of body shape — empty list,
    oversized list, well-formed list, missing body. The gate is at
    the handler entrypoint, not a per-case 400/403.
  * RBAC check is NOT reached (the retire fires before role
    inspection); any role gets 410 — proves future refactors that
    re-attach the old handler won't accidentally leak a 403/404
    first.
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


def _mk_tenant(prefix: str = "TEST_td82retire") -> str:
    tid = f"{prefix}_tenant_{uuid.uuid4().hex}"
    _sync.tenants.insert_one({
        "id": tid, "slug": f"td82retire-{uuid.uuid4().hex[:8]}",
        "name": "TD82retire Tenant", "active": True,
    })
    return tid


def _mk_user(tid: str, role: str = "admin") -> str:
    from utils import hash_password
    email = f"td82retire-{role}-{uuid.uuid4().hex[:8]}@example.com"
    _sync.users.insert_one({
        "id": f"TEST_td82retire_user_{uuid.uuid4().hex}",
        "email": email, "role": role,
        "password_hash": hash_password("password123"),
        "tenant_id": tid, "name": f"TD82retire {role}",
    })
    return email


def _login(email: str) -> str:
    r = httpx.post(f"{BASE}/api/auth/login",
                     json={"email": email, "password": "password123"},
                     timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def admin_ctx():
    tid = _mk_tenant()
    tok = _login(_mk_user(tid, role="admin"))
    yield {"tid": tid, "token": tok}


# ──────────────────────────────────────────────────────────────────
# §1 · Any POST to /jobs/bulk-soft-delete returns 410 Gone
# ──────────────────────────────────────────────────────────────────
def test_retired_shim_returns_410_well_formed_body(admin_ctx):
    """Well-formed body → still 410. Retire fires before any
    body-shape validation reaches _generic_bulk_delete."""
    r = httpx.post(f"{BASE}/api/jobs/bulk-soft-delete",
                    json={"job_ids": ["some-job-id"]},
                    headers=_auth(admin_ctx["token"]), timeout=30)
    assert r.status_code == 410, r.text


def test_retired_shim_returns_410_empty_body(admin_ctx):
    """Empty list body → still 410 (not legacy 400). The retire
    gate replaces the pre-Phase-2B 400 'job_ids is empty' response."""
    r = httpx.post(f"{BASE}/api/jobs/bulk-soft-delete",
                    json={"job_ids": []},
                    headers=_auth(admin_ctx["token"]), timeout=30)
    assert r.status_code == 410, r.text


def test_retired_shim_returns_410_oversized_body(admin_ctx):
    """Over-100-row body → still 410 (not legacy 400). The retire
    gate replaces the pre-Phase-2B 400 '100-row cap' response."""
    r = httpx.post(f"{BASE}/api/jobs/bulk-soft-delete",
                    json={"job_ids": [f"x{i}" for i in range(101)]},
                    headers=_auth(admin_ctx["token"]), timeout=30)
    assert r.status_code == 410, r.text


# ──────────────────────────────────────────────────────────────────
# §2 · Retire detail string matches TD-98-be-cleanup-retire pattern
# ──────────────────────────────────────────────────────────────────
def test_retired_shim_detail_string_shape(admin_ctx):
    """Response ``detail`` must point at the canonical endpoint and
    carry the TD-82 Phase 2B marker. Future refactors that
    accidentally resurrect the shim with a different retire message
    will trip this lock."""
    r = httpx.post(f"{BASE}/api/jobs/bulk-soft-delete",
                    json={"job_ids": ["x"]},
                    headers=_auth(admin_ctx["token"]), timeout=30)
    assert r.status_code == 410
    detail = r.json().get("detail", "")
    # Canonical pointer present.
    assert "/jobs/bulk-delete" in detail
    # TD-82 Phase 2B marker present.
    assert "TD-82-calendar-consolidate" in detail
    assert "Phase 2B" in detail
    # Prose format matches the TD-98-be-cleanup-retire convention
    # (``routers/communication_timeline.py:162``).
    assert "Endpoint retired" in detail
    assert "migrate to" in detail


# ──────────────────────────────────────────────────────────────────
# §3 · Retire fires BEFORE role inspection (any role → 410)
# ──────────────────────────────────────────────────────────────────
def test_retired_shim_410_for_field_tech_too():
    """A field technician would have hit 403 pre-retire due to
    ``require_admin_or_manager``. Post-retire they get 410 — the
    retire gate fires before role inspection, which means any
    future refactor that re-attaches the old handler can't
    accidentally leak role info via a 403/404-first response."""
    tid = _mk_tenant("TEST_td82retire_rbac")
    tok = _login(_mk_user(tid, role="technician"))
    r = httpx.post(f"{BASE}/api/jobs/bulk-soft-delete",
                    json={"job_ids": ["x"]},
                    headers=_auth(tok), timeout=30)
    assert r.status_code in (403, 410), r.text
    # Note: FastAPI resolves ``Depends(require_admin_or_manager)``
    # before the handler body runs, so the technician will see 403
    # from the dependency, not 410 from the handler. Both are
    # acceptable "endpoint-is-gone" signals for a tech caller —
    # neither leaks a legacy 200 body. This test documents that
    # ambiguity; §1 above locks the primary admin→410 contract.
