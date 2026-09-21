"""Phase P10 · Feb-2026 — Schedule Reorder · crew-lane fix.

Locks in the widened lane resolver on ``POST /api/jobs/reorder``:

    * Crew-only jobs (``crew_id`` set, ``technician_id`` null)
      resolve when the client sends the ``crew_id`` as the lane id.
    * Mixed-lane batches → 409 ``reorder_lane_mismatch`` with
      ``missing_job_ids`` (the outsiders) + ``lane_id``.
    * Unassigned jobs (no tech and no crew) → 409
      ``reorder_unassigned_job`` — specific enough for the UI to
      surface "Assign a technician or crew before reordering."
    * Tenant scoping preserved — cross-tenant ids surface via 409
      (they can't match the lane filter).
    * Technician callers (should be admin-gated today but the
      defensive P9 pin still fires): payload's ``tech_user_id`` is
      silently pinned to the caller's own id.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from tests._shared_mongo import shared_db as _shared_db


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

_PREFIX = f"p10-reorder-{uuid.uuid4().hex[:8]}"
TODAY = datetime.now(timezone.utc).date().isoformat()


def _login(email: str, pw: str = "password123"):
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": pw}, timeout=30,
    )
    r.raise_for_status()
    tok = r.json()["access_token"]
    me = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tok}"}, timeout=30,
    ).json()
    return tok, me


@pytest.fixture(scope="module")
def admin():
    tok, me = _login("admin@aquaterra.com")
    return {"tok": tok, **me}


@pytest.fixture(scope="module")
def mike():
    tok, me = _login("mike@aquaterra.com")
    return {"tok": tok, **me}


@pytest.fixture(scope="module")
def carlos():
    tok, me = _login("carlos@aquaterra.com")
    return {"tok": tok, **me}


def _seed_job(*, tenant_id: str, technician_id=None, crew_id=None,
                tag: str, scheduled_date: str = TODAY) -> str:
    jid = f"{_PREFIX}-{tag}-{uuid.uuid4().hex[:6]}"
    _sync.jobs.insert_one({
        "id": jid,
        "tenant_id": tenant_id,
        "title": f"P10 reorder test · {tag}",
        "customer_id": "seed-customer",
        "customer_name": "P10 Seed",
        "service_type": "Pool Cleaning",
        "scheduled_date": scheduled_date,
        "arrival_window": "9-10am",
        "status": "scheduled",
        "technician_id": technician_id,
        "crew_id": crew_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return jid


def _cleanup() -> None:
    _sync.jobs.delete_many({"id": {"$regex": f"^{_PREFIX}"}})


def setup_module(module):
    _cleanup()


def teardown_module(module):
    _cleanup()


def _reorder(admin_tok: str, body: dict):
    return requests.post(
        f"{API}/jobs/reorder",
        headers={"Authorization": f"Bearer {admin_tok}"},
        json=body, timeout=30,
    )


# ═══════════════════════════════════════════════════════════════════
# 1 · Crew-only batch (technician_id null on both jobs) succeeds.
# ═══════════════════════════════════════════════════════════════════
def test_p10_crew_only_batch_succeeds(admin):
    tid = admin["tenant_id"]
    crew_id = f"{_PREFIX}-crew-{uuid.uuid4().hex[:6]}"
    a = _seed_job(tenant_id=tid, crew_id=crew_id, tag="crewA")
    b = _seed_job(tenant_id=tid, crew_id=crew_id, tag="crewB")
    try:
        r = _reorder(admin["tok"], {
            "tech_user_id": crew_id,
            "date": TODAY,
            "ordered_job_ids": [b, a],  # deliberately reverse order
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("updated") == 2
        # Verify the two jobs actually got their route_index set.
        docs = list(_sync.jobs.find(
            {"id": {"$in": [a, b]}},
            {"_id": 0, "id": 1, "route_index": 1},
        ))
        by_id = {d["id"]: d["route_index"] for d in docs}
        assert by_id[b] == 0
        assert by_id[a] == 1
    finally:
        _cleanup()


# ═══════════════════════════════════════════════════════════════════
# 2 · Mixed-lane batch → 409 reorder_lane_mismatch with outsiders.
# ═══════════════════════════════════════════════════════════════════
def test_p10_mixed_lane_batch_returns_409_mismatch(admin, mike, carlos):
    tid = admin["tenant_id"]
    m1 = _seed_job(tenant_id=tid,
                    technician_id=mike["technician_id"], tag="mike")
    m2 = _seed_job(tenant_id=tid,
                    technician_id=mike["technician_id"], tag="mike")
    c1 = _seed_job(tenant_id=tid,
                    technician_id=carlos["technician_id"], tag="carlos")
    try:
        r = _reorder(admin["tok"], {
            "tech_user_id": mike["technician_id"],
            "date": TODAY,
            "ordered_job_ids": [m1, m2, c1],   # c1 is the outsider
        })
        assert r.status_code == 409, r.text
        detail = r.json().get("detail")
        assert isinstance(detail, dict)
        assert detail.get("code") == "reorder_lane_mismatch"
        assert detail.get("lane_id") == mike["technician_id"]
        assert c1 in (detail.get("missing_job_ids") or [])
        # Mike's own jobs must NOT be in the outsider list.
        assert m1 not in (detail.get("missing_job_ids") or [])
        assert m2 not in (detail.get("missing_job_ids") or [])
    finally:
        _cleanup()


# ═══════════════════════════════════════════════════════════════════
# 3 · Unassigned job in the batch → 409 reorder_unassigned_job.
# ═══════════════════════════════════════════════════════════════════
def test_p10_unassigned_job_returns_409_unassigned(admin, mike):
    tid = admin["tenant_id"]
    m1 = _seed_job(tenant_id=tid,
                    technician_id=mike["technician_id"], tag="mike")
    m2 = _seed_job(tenant_id=tid,
                    technician_id=mike["technician_id"], tag="mike")
    # ``ghost`` has neither ``technician_id`` nor ``crew_id`` set.
    ghost = _seed_job(tenant_id=tid, tag="ghost")
    try:
        r = _reorder(admin["tok"], {
            "tech_user_id": mike["technician_id"],
            "date": TODAY,
            "ordered_job_ids": [m1, m2, ghost],
        })
        assert r.status_code == 409, r.text
        detail = r.json().get("detail")
        assert detail.get("code") == "reorder_unassigned_job"
        assert ghost in (detail.get("job_ids") or [])
        assert detail.get("lane_id") == mike["technician_id"]
    finally:
        _cleanup()


# ═══════════════════════════════════════════════════════════════════
# 4 · Technician caller — P9 pin-to-self defensive check.
#     The endpoint is admin-only today, so a technician gets 403
#     BEFORE the pin-to-self code path runs. Assert 403 so a future
#     scope widening that opens the endpoint to techs doesn't
#     regress the P9 jail contract without a test failure.
# ═══════════════════════════════════════════════════════════════════
def test_p10_technician_blocked_by_admin_gate(mike):
    tid = mike["tenant_id"]
    # Seed a job so the endpoint has something to consider — but
    # the admin gate should fire before any lane resolution runs.
    j = _seed_job(tenant_id=tid,
                   technician_id=mike["technician_id"], tag="mike")
    try:
        r = _reorder(mike["tok"], {
            "tech_user_id": mike["technician_id"],
            "date": TODAY,
            "ordered_job_ids": [j],
        })
        assert r.status_code == 403, r.text
    finally:
        _cleanup()


# ═══════════════════════════════════════════════════════════════════
# 5 · Cross-tenant lane id → 409 (never 200).
#     Seed a job in a foreign tenant with the same technician_id
#     as the caller's payload — the tenant filter must reject it.
# ═══════════════════════════════════════════════════════════════════
def test_p10_cross_tenant_lane_returns_409(admin, mike):
    foreign_tid = f"{_PREFIX}-foreign-{uuid.uuid4().hex[:8]}"
    foreign_job = _seed_job(tenant_id=foreign_tid,
                              technician_id=mike["technician_id"],
                              tag="foreign")
    try:
        r = _reorder(admin["tok"], {
            "tech_user_id": mike["technician_id"],
            "date": TODAY,
            "ordered_job_ids": [foreign_job],
        })
        # Cross-tenant id can never match the tenant-scoped filter,
        # so it surfaces as a lane mismatch (never 200).
        assert r.status_code == 409, r.text
        detail = r.json().get("detail")
        assert detail.get("code") in (
            "reorder_lane_mismatch", "reorder_unassigned_job",
        )
        assert r.status_code != 200
    finally:
        _cleanup()
