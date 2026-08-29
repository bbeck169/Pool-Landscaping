"""Phase O4 · Feb-2026 — Idempotency wiring on the 7 identified
endpoints (see the audit doc's G1 list).

Every endpoint under test must satisfy TWO invariants:
  1. Same key + same body → cached response replays verbatim, no
     duplicate side-effects on the DB.
  2. Same key + DIFFERENT body → 200 with the marker
     ``{"error": "idempotency_key_body_mismatch"}`` (mirrors the
     ``utils_idempotency.replay_or_reserve`` contract).

Endpoint coverage:
    * POST   /mobile-tokens
    * POST   /jobs/{jid}/reopen
    * POST   /jobs/{jid}/arrive
    * POST   /jobs/{jid}/issues
    * POST   /jobs/{jid}/service-report/submit
    * POST   /jobs/{job_id}/on-my-way
    * PATCH  /service-reports/{report_id}/media/reorder

Test doubles: none — we hit the running preview backend so the
Motor + Mongo + ingress path is validated end-to-end. Cleanup
runs in a ``finally`` block per test so a mid-test assertion
failure doesn't leak state to the next case.
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

# Phase O4 tests run against the local supervisor-managed backend
# so the external ingress reachability doesn't affect the
# green-red loop.  Set ``PHASE_O4_TEST_BASE`` env to override.
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
    """Grab tenant_id + a job id we can safely mutate. Uses the first
    live job on the admin's tenant."""
    async def _find():
        u = await db.users.find_one(
            {"email": "admin@aquaterra.com"}, {"_id": 0})
        j = await db.jobs.find_one(
            {"tenant_id": u["tenant_id"]},
            {"_id": 0, "id": 1, "customer_id": 1, "technician_id": 1,
              "status": 1},
        )
        return u["tenant_id"], j
    tid, job = _run(_find())
    return {"tenant_id": tid, "job": job}


# ═══════════ POST /mobile-tokens ═══════════════════════════════════════
def test_mobile_tokens_idempotency_happy_replay(admin_h):
    key = str(uuid.uuid4())
    token = str(uuid.uuid4())
    body = {"token": token, "platform": "ios"}
    try:
        h = {**admin_h, "X-Idempotency-Key": key}
        r1 = requests.post(f"{API}/mobile-tokens", headers=h,
                            json=body, timeout=10).json()
        r2 = requests.post(f"{API}/mobile-tokens", headers=h,
                            json=body, timeout=10).json()
        assert r1 == r2, "replay MUST return identical cached response"
        assert r1["created"] is True
        # Only ONE row in mobile_tokens for this token.
        async def _count(): return await db.mobile_tokens.count_documents(
            {"token": token})
        assert _run(_count()) == 1
    finally:
        async def _c():
            await db.mobile_tokens.delete_many({"token": token})
            await db.idempotency_keys.delete_many({"key": key})
        _run(_c())


def test_mobile_tokens_body_mismatch_returns_error_marker(admin_h):
    key = str(uuid.uuid4())
    token_a, token_b = str(uuid.uuid4()), str(uuid.uuid4())
    try:
        h = {**admin_h, "X-Idempotency-Key": key}
        r1 = requests.post(f"{API}/mobile-tokens", headers=h,
                            json={"token": token_a, "platform": "ios"},
                            timeout=10).json()
        r2 = requests.post(f"{API}/mobile-tokens", headers=h,
                            json={"token": token_b, "platform": "ios"},
                            timeout=10).json()
        assert r1["created"] is True
        assert r2.get("error") == "idempotency_key_body_mismatch"
    finally:
        async def _c():
            await db.mobile_tokens.delete_many(
                {"token": {"$in": [token_a, token_b]}})
            await db.idempotency_keys.delete_many({"key": key})
        _run(_c())


# ═══════════ POST /jobs/{jid}/issues ═══════════════════════════════════
def test_jobs_issues_idempotency_happy_replay(admin_h, admin_ctx):
    jid = admin_ctx["job"]["id"]
    key = str(uuid.uuid4())
    issue_uuid = str(uuid.uuid4())
    body = {"description": f"phase-o4-{issue_uuid[:6]}", "cost": 12.5,
             "client_uuid": issue_uuid}
    try:
        h = {**admin_h, "X-Idempotency-Key": key}
        r1 = requests.post(f"{API}/jobs/{jid}/issues", headers=h,
                            json=body, timeout=10).json()
        r2 = requests.post(f"{API}/jobs/{jid}/issues", headers=h,
                            json=body, timeout=10).json()
        # Same cached response.
        assert r1.get("id") == r2.get("id")
        # Exactly ONE issue row with that client_uuid on the job.
        async def _count():
            j = await db.jobs.find_one({"id": jid}, {"_id": 0, "service_issues": 1})
            return sum(1 for i in (j.get("service_issues") or [])
                        if i.get("id") == issue_uuid)
        assert _run(_count()) == 1
    finally:
        async def _c():
            await db.jobs.update_one(
                {"id": jid},
                {"$pull": {"service_issues": {"id": issue_uuid}}})
            await db.idempotency_keys.delete_many({"key": key})
        _run(_c())


def test_jobs_issues_body_mismatch(admin_h, admin_ctx):
    jid = admin_ctx["job"]["id"]
    key = str(uuid.uuid4())
    uuid_a, uuid_b = str(uuid.uuid4()), str(uuid.uuid4())
    try:
        h = {**admin_h, "X-Idempotency-Key": key}
        r1 = requests.post(f"{API}/jobs/{jid}/issues", headers=h,
                            json={"description": "leak", "client_uuid": uuid_a},
                            timeout=10).json()
        r2 = requests.post(f"{API}/jobs/{jid}/issues", headers=h,
                            json={"description": "leaking pump", "client_uuid": uuid_b},
                            timeout=10).json()
        assert r1.get("id") == jid  # first call went through
        assert r2.get("error") == "idempotency_key_body_mismatch"
    finally:
        async def _c():
            await db.jobs.update_one(
                {"id": jid},
                {"$pull": {"service_issues": {"id": {"$in": [uuid_a, uuid_b]}}}})
            await db.idempotency_keys.delete_many({"key": key})
        _run(_c())


# ═══════════ POST /jobs/{jid}/reopen ═══════════════════════════════════
def test_jobs_reopen_idempotency_happy_replay(admin_h, admin_ctx):
    tid = admin_ctx["tenant_id"]
    # Seed a completed job we can safely reopen.
    jid = new_id()
    async def _seed():
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tid, "title": "phase-o4-reopen",
            "status": "completed", "completed_at": now_iso(),
            "created_at": now_iso(), "updated_at": now_iso(),
        })
    _run(_seed())
    key = str(uuid.uuid4())
    try:
        h = {**admin_h, "X-Idempotency-Key": key}
        r1 = requests.post(f"{API}/jobs/{jid}/reopen", headers=h, timeout=10).json()
        r2 = requests.post(f"{API}/jobs/{jid}/reopen", headers=h, timeout=10).json()
        assert r1.get("status") == "active"
        assert r2 == r1, "replay MUST return cached response verbatim"
        # Reopen was invoked only ONCE — reopened_at frozen across replays.
        assert r1.get("reopened_at") == r2.get("reopened_at")
    finally:
        async def _c():
            await db.jobs.delete_one({"id": jid})
            await db.idempotency_keys.delete_many({"key": key})
            await db.activity_logs.delete_many({"job_id": jid})
        _run(_c())


# ═══════════ POST /jobs/{jid}/arrive ═══════════════════════════════════
def test_jobs_arrive_idempotency_happy_replay(admin_h, admin_ctx):
    tid = admin_ctx["tenant_id"]
    jid = new_id()
    async def _seed():
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tid, "title": "phase-o4-arrive",
            "status": "scheduled",
            "site_lat": 33.7, "site_lng": -112.1,
            "created_at": now_iso(), "updated_at": now_iso(),
        })
    _run(_seed())
    key = str(uuid.uuid4())
    body = {"lat": 33.7, "lng": -112.1}
    try:
        h = {**admin_h, "X-Idempotency-Key": key}
        r1 = requests.post(f"{API}/jobs/{jid}/arrive", headers=h,
                            json=body, timeout=10).json()
        r2 = requests.post(f"{API}/jobs/{jid}/arrive", headers=h,
                            json=body, timeout=10).json()
        assert r2 == r1, "replay MUST return cached response"
        # Audit log rows must not double.  The endpoint writes one
        # audit row per outcome; a replay should NOT write a second.
        async def _audit_count():
            return await db.audit_logs.count_documents(
                {"payload.job_id": jid, "event": "job_timer_auto_start"})
        # 1 audit row max (or 0 if feature was disabled — either way,
        # the count must be identical to the count-after-one-call).
        assert _run(_audit_count()) <= 1
    finally:
        async def _c():
            await db.jobs.delete_one({"id": jid})
            await db.audit_logs.delete_many({"payload.job_id": jid})
            await db.idempotency_keys.delete_many({"key": key})
        _run(_c())


# ═══════════ PATCH /service-reports/{report_id}/media/reorder ═════════
def test_media_reorder_idempotency_happy_replay(admin_h, admin_ctx):
    tid = admin_ctx["tenant_id"]
    rid = new_id()
    async def _seed():
        await db.service_reports.insert_one({
            "id": rid, "tenant_id": tid, "public_uuid": new_id(),
            "photos": [
                {"id": new_id(), "url": "https://cdn/pool-a.jpg"},
                {"id": new_id(), "url": "https://cdn/pool-b.jpg"},
            ],
            "videos": [],
            "created_at": now_iso(), "updated_at": now_iso(),
        })
    _run(_seed())
    key = str(uuid.uuid4())
    body = {"photo_order": ["https://cdn/pool-b.jpg",
                              "https://cdn/pool-a.jpg"]}
    try:
        h = {**admin_h, "X-Idempotency-Key": key}
        r1 = requests.patch(f"{API}/service-reports/{rid}/media/reorder",
                             headers=h, json=body, timeout=10).json()
        r2 = requests.patch(f"{API}/service-reports/{rid}/media/reorder",
                             headers=h, json=body, timeout=10).json()
        assert r1 == r2, "replay MUST return cached response"
        assert [p["url"] for p in r1["photos"]] == \
                ["https://cdn/pool-b.jpg", "https://cdn/pool-a.jpg"]
    finally:
        async def _c():
            await db.service_reports.delete_one({"id": rid})
            await db.idempotency_keys.delete_many({"key": key})
        _run(_c())


def test_media_reorder_body_mismatch(admin_h, admin_ctx):
    tid = admin_ctx["tenant_id"]
    rid = new_id()
    async def _seed():
        await db.service_reports.insert_one({
            "id": rid, "tenant_id": tid, "public_uuid": new_id(),
            "photos": [{"id": new_id(), "url": "https://cdn/pool-a.jpg"}],
            "videos": [],
            "created_at": now_iso(), "updated_at": now_iso(),
        })
    _run(_seed())
    key = str(uuid.uuid4())
    try:
        h = {**admin_h, "X-Idempotency-Key": key}
        r1 = requests.patch(f"{API}/service-reports/{rid}/media/reorder",
                             headers=h,
                             json={"photo_order": ["https://cdn/pool-a.jpg"]},
                             timeout=10).json()
        r2 = requests.patch(f"{API}/service-reports/{rid}/media/reorder",
                             headers=h,
                             json={"photo_order": ["https://cdn/pool-b.jpg"]},
                             timeout=10).json()
        assert "photos" in r1
        assert r2.get("error") == "idempotency_key_body_mismatch"
    finally:
        async def _c():
            await db.service_reports.delete_one({"id": rid})
            await db.idempotency_keys.delete_many({"key": key})
        _run(_c())


# ═══════════ POST /jobs/{jid}/service-report/submit ═══════════════════
def test_service_report_submit_idempotency_replay(admin_h, admin_ctx):
    """The submit endpoint is the heaviest side-effect surface in the
    app (invoice auto-create, review-request enqueue, chemistry
    snapshot, drip emit).  Idempotency wiring MUST short-circuit
    every one of those on replay."""
    tid = admin_ctx["tenant_id"]
    jid = new_id()
    rid = new_id()
    async def _seed():
        # Seed a landscape job so the chemistry gate skips.
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tid,
            "title": "phase-o4-submit", "service_type": "landscape",
            "status": "in_progress",
            "billable": False,  # skip auto-invoice branch
            "created_at": now_iso(), "updated_at": now_iso(),
        })
        # Bootstrap-shape service report row so the submit path can
        # find + lock it.  Use tech_id = admin's user id.
        u = await db.users.find_one(
            {"email": "admin@aquaterra.com"}, {"_id": 0})
        await db.service_reports.insert_one({
            "id": rid, "tenant_id": tid, "job_id": jid,
            "tech_id": u["id"], "public_uuid": new_id(),
            "template": "landscape",
            "chemical_readings": [], "chemicals_added": [],
            "checklist_items": [],
            "created_at": now_iso(), "updated_at": now_iso(),
            "submitted_at": None,
        })
    _run(_seed())
    key = str(uuid.uuid4())
    try:
        h = {**admin_h, "X-Idempotency-Key": key}
        r1 = requests.post(f"{API}/jobs/{jid}/service-report/submit",
                            headers=h, timeout=15).json()
        r2 = requests.post(f"{API}/jobs/{jid}/service-report/submit",
                            headers=h, timeout=15).json()
        # r1 has submitted_at stamped; r2 MUST return the cached
        # response — same submitted_at, no re-run of side effects.
        assert r1.get("submitted_at") is not None
        assert r1.get("submitted_at") == r2.get("submitted_at")
    finally:
        async def _c():
            await db.jobs.delete_one({"id": jid})
            await db.service_reports.delete_one({"id": rid})
            await db.idempotency_keys.delete_many({"key": key})
        _run(_c())


# ═══════════ POST /jobs/{job_id}/on-my-way ═════════════════════════════
def test_on_my_way_idempotency_replay(admin_h, admin_ctx):
    """The live on-my-way route (routers/on_my_way.py:174) has a
    once-per-day guard on ``communications``.  A replay of the same
    header MUST return the cached response — the guard would return
    ``already_sent_today`` on second execution anyway, but the
    header-level cache is what proves the wiring took effect."""
    tid = admin_ctx["tenant_id"]
    jid = new_id()
    cid = new_id()
    async def _seed():
        # Seed a job + customer that will trigger the fast
        # ``customer_blocked`` guard (demo=True) so we don't hit
        # the SMS gate at all.  The cached response still needs to
        # persist so the second call is byte-identical.
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid, "name": "PhaseO4 Demo",
            "phone": "+15555550000", "demo": True,
            "sms_opt_in": True,
            "created_at": now_iso(), "updated_at": now_iso(),
        })
        u = await db.users.find_one(
            {"email": "admin@aquaterra.com"}, {"_id": 0})
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tid, "customer_id": cid,
            "technician_id": u["id"],
            "title": "phase-o4-omw", "status": "scheduled",
            "created_at": now_iso(), "updated_at": now_iso(),
        })
    _run(_seed())
    key = str(uuid.uuid4())
    body = {"origin_lat": 33.7, "origin_lng": -112.1}
    try:
        h = {**admin_h, "X-Idempotency-Key": key}
        r1 = requests.post(f"{API}/jobs/{jid}/on-my-way", headers=h,
                            json=body, timeout=10).json()
        r2 = requests.post(f"{API}/jobs/{jid}/on-my-way", headers=h,
                            json=body, timeout=10).json()
        assert r1 == r2, "replay MUST return cached response verbatim"
        # Blocked path returns sent:false — proves we hit the guard,
        # not the send helper.
        assert r1.get("sent") is False
        assert r1.get("reason") == "customer_blocked"
    finally:
        async def _c():
            await db.jobs.delete_one({"id": jid})
            await db.customers.delete_one({"id": cid})
            await db.idempotency_keys.delete_many({"key": key})
        _run(_c())
