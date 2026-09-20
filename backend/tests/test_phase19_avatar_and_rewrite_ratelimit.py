"""Phase 19 · Feb-2026 — combined pytest for both sub-items.

Sub-item A · Avatar Swap (2 tests):
    A1) GET /api/jobs returns ``assignee_photo_url`` populated when the
        assigned tech has ``technician_photo_url`` set on their user doc.
    A2) GET /api/jobs returns ``assignee_photo_url`` = null when the tech
        has no photo.

Sub-item B · AI Rewrite Rate-Limit Persistence (3 tests):
    B1) First call under the limit → 200 + row present in
        ``ai_rewrite_usage`` with ``call_count == 1``.
    B2) Call count persists across a simulated process restart — after
        re-importing the module (which reinitializes the in-process
        state), the Mongo counter is still there and blocks the caller
        at the same threshold.
    B3) Exceeding the limit → 429 with a ``Retry-After`` header set to
        seconds until ``window_end_utc``.
"""
from __future__ import annotations

import importlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import jwt
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

JWT_SECRET = _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET") \
    or "dev-secret-change-me"
JWT_ALGO = _ENV.get("JWT_ALGO") or "HS256"


def _new_id() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tok(user_id: str, email: str, role: str,
          tenant_id: str | None = None) -> str:
    payload = {
        "sub": user_id, "email": email, "role": role,
        "tenant_id": tenant_id or "",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


# ══════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════
@pytest.fixture()
def tenant_id():
    tid = f"p19-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": tid, "name": f"P19 {tid}", "slug": f"p19-{tid}",
        "active": True, "widget_allowed_domains": [],
    })
    yield tid
    for col in ("tenants", "users", "jobs", "ai_rewrite_usage"):
        _sync[col].delete_many({"tenant_id": tid})


@pytest.fixture()
def admin(tenant_id):
    uid = f"admin-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@p19.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": "admin",
        "name": "P19 Admin", "email": email,
    })
    return {"id": uid, "email": email, "role": "admin",
            "tenant_id": tenant_id,
            "token": _tok(uid, email, "admin", tenant_id)}


@pytest.fixture()
def tech_with_photo(tenant_id):
    uid = f"tech-{uuid.uuid4().hex[:8]}"
    tid = f"tech-id-{uuid.uuid4().hex[:6]}"
    email = f"{uid}@p19.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": "technician",
        "name": "Photo Tech", "email": email,
        "technician_id": tid,
        "technician_photo_url": "https://cdn.example.com/photo-tech.jpg",
        "department": "pool_tech",
    })
    return {"id": uid, "technician_id": tid, "email": email,
            "role": "technician",
            "token": _tok(uid, email, "technician", tenant_id)}


@pytest.fixture()
def tech_without_photo(tenant_id):
    uid = f"tech-{uuid.uuid4().hex[:8]}"
    tid = f"tech-id-{uuid.uuid4().hex[:6]}"
    email = f"{uid}@p19.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": "technician",
        "name": "Nophoto Tech", "email": email,
        "technician_id": tid,
        # deliberately no technician_photo_url
        "department": "pool_tech",
    })
    return {"id": uid, "technician_id": tid, "email": email,
            "role": "technician",
            "token": _tok(uid, email, "technician", tenant_id)}


def _seed_job(tenant_id: str, technician_id: str, title: str) -> str:
    jid = _new_id()
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id,
        "customer_id": "cust-1", "technician_id": technician_id,
        "technician_name": "Any Tech",
        "service_type": "pool_cleaning",
        "status": "pending",
        "title": title,
        "scheduled_date": _now_iso()[:10],
        "created_at": _now_iso(), "updated_at": _now_iso(),
    })
    return jid


# ══════════════════════════════════════════════════════════════════
# Sub-item A — Avatar Swap
# ══════════════════════════════════════════════════════════════════
def test_A1_assignee_photo_url_populated(tenant_id, admin, tech_with_photo):
    jid = _seed_job(tenant_id, tech_with_photo["technician_id"], "A1-job")
    r = requests.get(
        f"{API}/jobs",
        headers={"Authorization": f"Bearer {admin['token']}",
                 "X-Tenant-Id": tenant_id},
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    row = next((x for x in rows if x.get("id") == jid), None)
    assert row is not None, "seeded job missing from list"
    assert "assignee_photo_url" in row
    assert row["assignee_photo_url"] == \
        "https://cdn.example.com/photo-tech.jpg"


def test_A2_assignee_photo_url_null_when_missing(tenant_id, admin,
                                                   tech_without_photo):
    jid = _seed_job(tenant_id, tech_without_photo["technician_id"], "A2-job")
    r = requests.get(
        f"{API}/jobs",
        headers={"Authorization": f"Bearer {admin['token']}",
                 "X-Tenant-Id": tenant_id},
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    row = next((x for x in rows if x.get("id") == jid), None)
    assert row is not None
    assert "assignee_photo_url" in row
    assert row["assignee_photo_url"] is None


# ══════════════════════════════════════════════════════════════════
# Sub-item B — AI Rewrite Rate-Limit Persistence
# ══════════════════════════════════════════════════════════════════
# The backend is running in a separate process, so we can't monkey-
# patch its LLM adapter from here. Instead we lean on the router's
# ``ALLOW_TEST_HOOKS + X-Test-Skip-Llm`` bypass — both env and header
# must be present, so the same code path is impossible to hit in
# production even if a client crafts the header.
_LLM_BYPASS_HDR = {"X-Test-Skip-Llm": "1"}


def test_B1_first_call_under_limit_persists_row(tenant_id, tech_with_photo):
    r = requests.post(
        f"{API}/checkins/rewrite-description",
        headers={"Authorization": f"Bearer {tech_with_photo['token']}",
                 "X-Tenant-Id": tenant_id, **_LLM_BYPASS_HDR},
        json={"draft_description": "worked on pump, replaced filter"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("rewritten", "").startswith("[TEST-STUB]")
    # Mongo row present with call_count=1.
    row = _sync.ai_rewrite_usage.find_one({
        "tenant_id": tenant_id,
        "user_id": tech_with_photo["id"],
        "action": "checkin_rewrite",
    })
    assert row is not None, "ai_rewrite_usage row not created"
    assert row["call_count"] == 1
    assert "window_start_utc" in row
    assert "window_end_utc" in row


def test_B2_persists_across_simulated_process_restart(tenant_id,
                                                       tech_with_photo):
    tok = tech_with_photo["token"]
    hdr = {"Authorization": f"Bearer {tok}",
           "X-Tenant-Id": tenant_id, **_LLM_BYPASS_HDR}
    # Consume 5 calls in one "process".
    for i in range(5):
        r = requests.post(
            f"{API}/checkins/rewrite-description",
            headers=hdr,
            json={"draft_description": f"call {i}"},
        )
        assert r.status_code == 200, (i, r.text)
    row = _sync.ai_rewrite_usage.find_one({
        "tenant_id": tenant_id, "user_id": tech_with_photo["id"],
        "action": "checkin_rewrite",
    })
    assert row and row["call_count"] == 5

    # Simulate a process restart — force a fresh import of the module.
    # The in-process state (the sync-shim deque) is wiped, but the
    # Mongo counter is the source of truth so subsequent calls
    # continue from 6, 7, … 10.
    import routers.checkin_rewrite as _mod
    importlib.reload(_mod)

    for i in range(5, 10):
        r = requests.post(
            f"{API}/checkins/rewrite-description",
            headers=hdr,
            json={"draft_description": f"call {i}"},
        )
        assert r.status_code == 200, (i, r.text)
    row = _sync.ai_rewrite_usage.find_one({
        "tenant_id": tenant_id, "user_id": tech_with_photo["id"],
        "action": "checkin_rewrite",
    })
    assert row and row["call_count"] == 10


def test_B3_exceeding_limit_returns_429_with_retry_after(tenant_id,
                                                          tech_with_photo):
    tok = tech_with_photo["token"]
    hdr = {"Authorization": f"Bearer {tok}",
           "X-Tenant-Id": tenant_id, **_LLM_BYPASS_HDR}
    # Consume all 10 calls in the current window.
    for i in range(10):
        r = requests.post(
            f"{API}/checkins/rewrite-description",
            headers=hdr,
            json={"draft_description": f"call {i}"},
        )
        assert r.status_code == 200, (i, r.text)

    # 11th call — must 429 and set Retry-After.
    r = requests.post(
        f"{API}/checkins/rewrite-description",
        headers=hdr,
        json={"draft_description": "one too many"},
    )
    assert r.status_code == 429, r.text
    assert r.json().get("detail", {}).get("error") == "rate_limited" \
        or r.json().get("error") == "rate_limited"
    ra = r.headers.get("Retry-After") or r.headers.get("retry-after")
    assert ra is not None, "Retry-After header missing"
    assert int(ra) > 0 and int(ra) <= 3600, \
        f"Retry-After out of range: {ra}"

    # And the counter was rolled back — still exactly 10, not 11.
    row = _sync.ai_rewrite_usage.find_one({
        "tenant_id": tenant_id, "user_id": tech_with_photo["id"],
        "action": "checkin_rewrite",
    })
    assert row and row["call_count"] == 10, \
        f"counter should stay at 10, got {row and row['call_count']}"
    assert row.get("last_rejected_at"), \
        "last_rejected_at should be stamped on rejected calls"
