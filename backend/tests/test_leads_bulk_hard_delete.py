"""Phase LD1 · Feb 2026 — Leads bulk HARD delete.

Guards:
  * Admin/Super Admin only (role gate).
  * `{ lead_ids: [] }` payload — new distinct shape vs. the
    Task-BB soft-delete's ``ids`` selector.
  * Response envelope `{ results, summary }` — 200 on partial
    failures, per-row status inside ``results[]``.
  * Rows are removed from the ``leads`` collection (real
    hard delete — NOT a ``deleted_at`` stamp).
  * `audit_log.action == "lead.hard_delete"` written per success.
  * Converted / linked / open-task leads are surfaced in
    ``results[]`` with ``ok=false`` and a human-readable reason.

Fixture pattern mirrors ``test_phase34_task_nn_p1.py`` so we share
the same in-process ASGI shim + tenant login machinery.
"""
from __future__ import annotations

import os
import uuid

import pytest

from tests._phase34_http_shim import http
from tests._phase34_asyncio import batch_safe_run as _run

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = http.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}",
            "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}",
            "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}",
            "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def db():
    from config import db as _db
    return _db


@pytest.fixture(scope="module")
def tid(db):
    async def _go():
        t = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
        return t["id"]
    return _run(_go())


def _plant_lead(db, tid, **overrides):
    """Insert a fresh lead row + return its id."""
    lid = uuid.uuid4().hex
    doc = {"id": lid, "tenant_id": tid, "name": f"LD1-{lid[:6]}",
             "email": f"{lid[:6]}@t.local", "phone": "+15551234567",
             "status": "new", "source": "admin_manual",
             "created_at": "2026-02-15T00:00:00Z"}
    doc.update(overrides)
    _run(db.leads.insert_one(doc))
    return lid


# ═══════════════════════════════════════════════════════════════════════
# Role gate
# ═══════════════════════════════════════════════════════════════════════
def test_bulk_hard_delete_rejects_customer(customer_headers):
    r = http.post(f"{API}/leads/bulk-hard-delete", headers=customer_headers,
                  json={"lead_ids": ["nope"]}, timeout=30)
    assert r.status_code in (401, 403)


def test_bulk_hard_delete_rejects_unauthenticated():
    r = http.post(f"{API}/leads/bulk-hard-delete",
                  headers={"Content-Type": "application/json"},
                  json={"lead_ids": ["nope"]}, timeout=30)
    assert r.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════
# Payload validation
# ═══════════════════════════════════════════════════════════════════════
def test_bulk_hard_delete_requires_non_empty_ids(super_headers):
    r = http.post(f"{API}/leads/bulk-hard-delete", headers=super_headers,
                  json={"lead_ids": []}, timeout=30)
    assert r.status_code == 400


def test_bulk_hard_delete_caps_batch_size(super_headers):
    r = http.post(f"{API}/leads/bulk-hard-delete", headers=super_headers,
                  json={"lead_ids": [uuid.uuid4().hex for _ in range(401)]},
                  timeout=30)
    assert r.status_code == 400
    assert "capped" in r.text.lower()


# ═══════════════════════════════════════════════════════════════════════
# Happy path — rows are removed + audit_log rows written.
# ═══════════════════════════════════════════════════════════════════════
def test_bulk_hard_delete_happy_path(db, super_headers, tid):
    a = _plant_lead(db, tid)
    b = _plant_lead(db, tid)
    r = http.post(f"{API}/leads/bulk-hard-delete", headers=super_headers,
                  json={"lead_ids": [a, b]}, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["succeeded"] == 2
    assert body["summary"]["failed"] == 0
    assert body["summary"]["total"] == 2
    ok_ids = {row["id"] for row in body["results"] if row["ok"]}
    assert ok_ids == {a, b}
    # Rows are gone from the collection (true hard delete — NOT a
    # soft-delete ``deleted_at`` stamp).
    for lid in (a, b):
        row = _run(db.leads.find_one({"id": lid}))
        assert row is None
    # Per-row audit entries.
    for lid in (a, b):
        audit = _run(db.audit_log.find_one({
            "action": "lead.hard_delete", "target_id": lid,
            "tenant_id": tid,
        }))
        assert audit is not None, f"missing audit for {lid}"


def test_bulk_hard_delete_partial_failure(db, super_headers, tid):
    """Missing id + converted lead surface as ``ok=false`` while the
    valid rows still get purged. Endpoint returns HTTP 200."""
    a = _plant_lead(db, tid)                          # valid
    missing = uuid.uuid4().hex                          # 404
    converted = _plant_lead(db, tid,
                            converted_customer_id=uuid.uuid4().hex,
                            status="closed_won")        # 409
    r = http.post(f"{API}/leads/bulk-hard-delete", headers=super_headers,
                  json={"lead_ids": [a, missing, converted]}, timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["succeeded"] == 1
    assert body["summary"]["failed"] == 2
    by_id = {row["id"]: row for row in body["results"]}
    assert by_id[a]["ok"] is True
    assert by_id[missing]["ok"] is False
    assert by_id[missing]["status_code"] == 404
    assert by_id[converted]["ok"] is False
    assert by_id[converted]["status_code"] == 409
    # Valid row is really gone; converted row is still there.
    assert _run(db.leads.find_one({"id": a})) is None
    assert _run(db.leads.find_one({"id": converted})) is not None


def test_bulk_hard_delete_open_tasks_locked(db, super_headers, tid):
    a = _plant_lead(db, tid, open_task_ids=["task-1", "task-2"])
    r = http.post(f"{API}/leads/bulk-hard-delete", headers=super_headers,
                  json={"lead_ids": [a]}, timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["succeeded"] == 0
    assert body["summary"]["failed"] == 1
    row = body["results"][0]
    assert row["ok"] is False
    assert "follow-up task" in row["reason"].lower()
    # Lead survives.
    assert _run(db.leads.find_one({"id": a})) is not None


def test_bulk_hard_delete_tenant_isolation(db, super_headers, tid):
    """Rows outside the caller's tenant are treated as 404 — NEVER
    hard-deleted from a foreign tenant."""
    other_tid = "tenant-foreign-" + uuid.uuid4().hex[:6]
    foreign = uuid.uuid4().hex
    _run(db.leads.insert_one({
        "id": foreign, "tenant_id": other_tid, "name": "foreign",
        "status": "new", "created_at": "2026-02-15T00:00:00Z",
    }))
    r = http.post(f"{API}/leads/bulk-hard-delete", headers=super_headers,
                  json={"lead_ids": [foreign]}, timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["succeeded"] == 0
    assert body["summary"]["failed"] == 1
    assert body["results"][0]["status_code"] == 404
    # Foreign row untouched.
    survivor = _run(db.leads.find_one({"id": foreign}))
    assert survivor is not None
    # Cleanup so this row doesn't linger across suite runs.
    _run(db.leads.delete_one({"id": foreign}))


def test_bulk_hard_delete_admin_role_allowed(db, admin_headers, tid):
    """Admin role (not just super_admin) is authorised."""
    a = _plant_lead(db, tid)
    r = http.post(f"{API}/leads/bulk-hard-delete", headers=admin_headers,
                  json={"lead_ids": [a]}, timeout=30)
    assert r.status_code == 200
    assert r.json()["summary"]["succeeded"] == 1
    assert _run(db.leads.find_one({"id": a})) is None
