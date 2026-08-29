"""Phase O4 · Feb-2026 — Client-UUID acceptance on 3 endpoints (G2).

Contract per endpoint::

    * The mobile app mints a UUID for a fresh resource offline.
    * When the queue drains, POSTing with ``client_uuid`` bootstraps
      the row on the server with ``id = client_uuid``.
    * Re-POSTing the same ``client_uuid`` returns the existing row
      verbatim (no duplicate, no side-effects re-run).

Endpoints covered:
    * POST /service-reports            (NEW endpoint)
    * POST /jobs/{jid}/photos
    * POST /jobs/{jid}/issues
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os as _os_local
_ENV_BASE = _os_local.environ.get("PHASE_O4_TEST_BASE")
BASE = (_ENV_BASE or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

from config import db  # noqa: E402
from utils import new_id, now_iso  # noqa: E402


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h() -> dict:
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def admin_ctx() -> dict:
    async def _find():
        u = await db.users.find_one(
            {"email": "admin@aquaterra.com"}, {"_id": 0})
        j = await db.jobs.find_one(
            {"tenant_id": u["tenant_id"]}, {"_id": 0, "id": 1})
        return u["tenant_id"], j["id"], u["id"]
    tid, jid, uid = _run(_find())
    return {"tenant_id": tid, "job_id": jid, "user_id": uid}


# ═══════════ POST /service-reports ═════════════════════════════════════
def test_service_reports_create_with_client_uuid_is_idempotent(admin_h, admin_ctx):
    """Two POSTs with the same client_uuid MUST return the same row
    and MUST NOT create a duplicate service report."""
    # Seed a fresh job so the (tenant, job, tech) uniqueness rule
    # doesn't collide with an existing report on the shared demo job.
    tid = admin_ctx["tenant_id"]
    jid = new_id()
    async def _seed():
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tid, "title": "phase-o4-svc-create",
            "service_type": "landscape", "status": "scheduled",
            "created_at": now_iso(), "updated_at": now_iso(),
        })
    _run(_seed())
    client_uuid = str(uuid.uuid4())
    body = {"job_id": jid, "client_uuid": client_uuid}
    try:
        r1 = requests.post(f"{API}/service-reports", headers=admin_h,
                            json=body, timeout=10).json()
        r2 = requests.post(f"{API}/service-reports", headers=admin_h,
                            json=body, timeout=10).json()
        assert r1["id"] == client_uuid, "client_uuid MUST become the row id"
        assert r2["id"] == client_uuid
        # Exactly ONE row on the DB with that id.
        async def _count():
            return await db.service_reports.count_documents(
                {"id": client_uuid, "tenant_id": tid})
        assert _run(_count()) == 1
    finally:
        async def _c():
            await db.jobs.delete_one({"id": jid})
            await db.service_reports.delete_many({"id": client_uuid})
        _run(_c())


def test_service_reports_create_without_client_uuid_falls_back(admin_h, admin_ctx):
    """When the mobile client didn't mint a UUID, the server still
    generates one — the endpoint MUST NOT reject the call."""
    tid = admin_ctx["tenant_id"]
    jid = new_id()
    async def _seed():
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tid,
            "title": "phase-o4-svc-create-noguid",
            "service_type": "landscape", "status": "scheduled",
            "created_at": now_iso(), "updated_at": now_iso(),
        })
    _run(_seed())
    try:
        r = requests.post(f"{API}/service-reports", headers=admin_h,
                           json={"job_id": jid}, timeout=10).json()
        assert r.get("id") and len(r["id"]) >= 16
        assert r.get("job_id") == jid
    finally:
        async def _c():
            await db.jobs.delete_one({"id": jid})
            await db.service_reports.delete_many({"job_id": jid})
        _run(_c())


# ═══════════ POST /jobs/{jid}/photos ═══════════════════════════════════
def test_jobs_photos_client_uuid_dedupes(admin_h, admin_ctx):
    jid = admin_ctx["job_id"]
    client_uuid = str(uuid.uuid4())
    tiny_data = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    body = {"data": tiny_data, "label": "phase-o4",
             "client_uuid": client_uuid}
    try:
        r1 = requests.post(f"{API}/jobs/{jid}/photos", headers=admin_h,
                            json=body, timeout=10).json()
        r2 = requests.post(f"{API}/jobs/{jid}/photos", headers=admin_h,
                            json=body, timeout=10).json()
        # Same photo id — the second call returned the row as-is.
        matches_r1 = [p for p in (r1.get("photos") or [])
                       if p.get("id") == client_uuid]
        matches_r2 = [p for p in (r2.get("photos") or [])
                       if p.get("id") == client_uuid]
        assert len(matches_r1) == 1
        assert len(matches_r2) == 1  # NOT duplicated
    finally:
        async def _c():
            await db.jobs.update_one(
                {"id": jid},
                {"$pull": {"photos": {"id": client_uuid}}})
        _run(_c())


# ═══════════ POST /jobs/{jid}/issues ═══════════════════════════════════
def test_jobs_issues_client_uuid_dedupes(admin_h, admin_ctx):
    jid = admin_ctx["job_id"]
    client_uuid = str(uuid.uuid4())
    body = {"description": f"phase-o4-{client_uuid[:6]}", "cost": 42.0,
             "client_uuid": client_uuid}
    try:
        r1 = requests.post(f"{API}/jobs/{jid}/issues", headers=admin_h,
                            json=body, timeout=10).json()
        r2 = requests.post(f"{API}/jobs/{jid}/issues", headers=admin_h,
                            json=body, timeout=10).json()
        matches_r1 = [i for i in (r1.get("service_issues") or [])
                       if i.get("id") == client_uuid]
        matches_r2 = [i for i in (r2.get("service_issues") or [])
                       if i.get("id") == client_uuid]
        assert len(matches_r1) == 1
        assert len(matches_r2) == 1
    finally:
        async def _c():
            await db.jobs.update_one(
                {"id": jid},
                {"$pull": {"service_issues": {"id": client_uuid}}})
        _run(_c())
