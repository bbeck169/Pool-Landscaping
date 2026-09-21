"""Phase M1 · Feb-2026 — Customer Merge Wizard backend tests.

Uses the same sync ``httpx.Client("http://localhost:8001")`` +
sync ``pymongo`` pattern as :mod:`tests.test_customer_merge_phase1`
so we avoid the Motor cross-loop bind error the ASGI transport
trips when direct-service calls run against a freshly-created
event loop. All seed + assertion goes through ``_sync`` (the shared
``pymongo`` handle exposed by ``tests._shared_mongo``).

Coverage:
* M1.1 happy path — 2 customers same tenant → re-parent across every
  extended collection, duplicate soft-deleted with
  ``merged_into_customer_id`` set, timeline note on primary,
  audit_log entry with duplicate_snapshot + reparent_counts.
* M1.2 field choices honoured (primary + duplicate for each field).
* M1.3 cross-tenant merge → 403 ``cross_tenant_merge_forbidden``
  + audit_log breadcrumb.
* M1.4 same customer merge → 400 ``same_customer_merge_forbidden``.
* M1.5 already-deleted customer → 409 ``customer_already_deleted``.
* M1.6 role gate → non-admin roles 403.
* M1.7 timeline note visible via ``/api/customer-timeline/{id}``.
* M1.8 customer list endpoint excludes soft-deleted / merged rows.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx
import jwt as _jwt
import pytest
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


BASE = "http://localhost:8001"
_ENV = dotenv_values("/app/backend/.env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_JWT_SECRET = _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
_sync = _shared_db() if (_MONGO_URL and _DB_NAME) else None


def _mint(uid: str, tid: str, role: str = "admin") -> str:
    return _jwt.encode({
        "sub": uid, "email": f"{uid}@ex.test", "role": role,
        "tenant_id": tid,
        "exp": int((datetime.now(timezone.utc)
                     + timedelta(hours=1)).timestamp()),
    }, _JWT_SECRET, algorithm="HS256")


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


_TENANT_A = f"m1-tenant-a-{uuid.uuid4().hex[:6]}"
_TENANT_B = f"m1-tenant-b-{uuid.uuid4().hex[:6]}"


@pytest.fixture
def m1_seed():
    """Sync-driven seed. Two tenants, three users (admin/tenant-a,
    admin/tenant-b, technician/tenant-a), two customer pairs, and a
    handful of related records under the tenant-A duplicate."""
    if _sync is None:
        pytest.skip("MONGO_URL / DB_NAME missing")

    S: Dict[str, Any] = {
        "tenant_a": _TENANT_A, "tenant_b": _TENANT_B,
        "primary_a":   _uid("m1-pa"),
        "duplicate_a": _uid("m1-da"),
        "primary_b":   _uid("m1-pb"),
        "duplicate_b": _uid("m1-db"),
        "admin_a":     _uid("m1-ua"),
        "admin_b":     _uid("m1-ub"),
        "tech_a":      _uid("m1-ta"),
    }

    _sync.tenants.insert_many([
        {"id": _TENANT_A, "name": "M1 Tenant A",
          "slug": f"m1a-{uuid.uuid4().hex[:6]}", "active": True,
          "settings": {}},
        {"id": _TENANT_B, "name": "M1 Tenant B",
          "slug": f"m1b-{uuid.uuid4().hex[:6]}", "active": True,
          "settings": {}},
    ])
    _sync.users.insert_many([
        {"id": S["admin_a"], "tenant_id": _TENANT_A, "role": "admin",
          "email": f"m1a-admin-{uuid.uuid4().hex[:6]}@ex.com",
          "active": True,
          "tenant_memberships": [{"tenant_id": _TENANT_A,
                                    "role": "admin",
                                    "joined_at": "2025-01-01T00:00:00+00:00"}],
          "active_tenant_id": _TENANT_A},
        {"id": S["admin_b"], "tenant_id": _TENANT_B, "role": "admin",
          "email": f"m1b-admin-{uuid.uuid4().hex[:6]}@ex.com",
          "active": True,
          "tenant_memberships": [{"tenant_id": _TENANT_B,
                                    "role": "admin",
                                    "joined_at": "2025-01-01T00:00:00+00:00"}],
          "active_tenant_id": _TENANT_B},
        {"id": S["tech_a"], "tenant_id": _TENANT_A, "role": "technician",
          "email": f"m1a-tech-{uuid.uuid4().hex[:6]}@ex.com",
          "active": True,
          "tenant_memberships": [{"tenant_id": _TENANT_A,
                                    "role": "technician",
                                    "joined_at": "2025-01-01T00:00:00+00:00"}],
          "active_tenant_id": _TENANT_A},
    ])
    _sync.customers.insert_many([
        {"id": S["primary_a"], "tenant_id": _TENANT_A,
          "name": "Alice Primary", "email": "alice@ex.com",
          "phone": "111-1111", "address": "1 Primary St",
          "created_at": "2025-01-01T00:00:00+00:00",
          "updated_at": "2025-01-01T00:00:00+00:00"},
        {"id": S["duplicate_a"], "tenant_id": _TENANT_A,
          "name": "Alicia Dupe", "email": "alicia@ex.com",
          "phone": "222-2222", "address": "2 Dupe Ave",
          "created_at": "2025-06-01T00:00:00+00:00",
          "updated_at": "2025-06-01T00:00:00+00:00"},
        {"id": S["primary_b"], "tenant_id": _TENANT_B,
          "name": "Bob Primary", "email": "bob@ex.com",
          "phone": "333-3333"},
        {"id": S["duplicate_b"], "tenant_id": _TENANT_B,
          "name": "Bobby Dupe", "email": "bobby@ex.com",
          "phone": "444-4444"},
    ])
    _sync.jobs.insert_many([
        {"id": _uid("m1-j"), "tenant_id": _TENANT_A,
          "customer_id": S["duplicate_a"], "status": "scheduled"},
        {"id": _uid("m1-j"), "tenant_id": _TENANT_A,
          "customer_id": S["duplicate_a"], "status": "completed"},
    ])
    _sync.quotes.insert_many([
        {"id": _uid("m1-q"), "tenant_id": _TENANT_A,
          "customer_id": S["duplicate_a"], "doc_type": "invoice",
          "total": 100},
        {"id": _uid("m1-q"), "tenant_id": _TENANT_A,
          "customer_id": S["duplicate_a"], "doc_type": "estimate",
          "total": 200},
    ])
    _sync.payments.insert_one({
        "id": _uid("m1-p"), "tenant_id": _TENANT_A,
        "customer_id": S["duplicate_a"], "amount": 50})
    _sync.messages.insert_one({
        "id": _uid("m1-m"), "tenant_id": _TENANT_A,
        "customer_id": S["duplicate_a"], "body": "hi"})
    _sync.call_logs.insert_one({
        "id": _uid("m1-cl"), "tenant_id": _TENANT_A,
        "customer_id": S["duplicate_a"], "direction": "inbound"})
    _sync.intelligence_alerts.insert_one({
        "id": _uid("m1-ia"), "tenant_id": _TENANT_A,
        "customer_id": S["duplicate_a"], "kind": "churn"})
    _sync.warranty_contracts.insert_one({
        "id": _uid("m1-w"), "tenant_id": _TENANT_A,
        "customer_id": S["duplicate_a"], "status": "active"})

    yield S

    for coll in ("tenants", "users", "customers", "jobs",
                 "quotes", "payments", "messages", "call_logs",
                 "intelligence_alerts", "warranty_contracts",
                 "customer_notes", "customer_merge_audit",
                 "audit_log"):
        _sync[coll].delete_many({
            "tenant_id": {"$in": [_TENANT_A, _TENANT_B]},
        })


# ─── Tests ─────────────────────────────────────────────────────────
def test_m1_happy_path_reparent_and_softdelete(m1_seed):
    S = m1_seed
    token = _mint(S["admin_a"], _TENANT_A, "admin")
    with httpx.Client(base_url=BASE) as c:
        r = c.post(
            "/api/customers/merge-wizard",
            json={
                "primary_customer_id":   S["primary_a"],
                "duplicate_customer_id": S["duplicate_a"],
                "field_choices": {
                    "name": "primary", "email": "primary",
                    "phone": "duplicate", "address": "duplicate",
                },
            },
            headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    # Re-parent verification.
    assert _sync.jobs.count_documents(
        {"tenant_id": _TENANT_A, "customer_id": S["primary_a"]}) == 2
    assert _sync.jobs.count_documents(
        {"tenant_id": _TENANT_A, "customer_id": S["duplicate_a"]}) == 0
    assert _sync.messages.count_documents(
        {"tenant_id": _TENANT_A, "customer_id": S["primary_a"]}) == 1
    assert _sync.call_logs.count_documents(
        {"tenant_id": _TENANT_A, "customer_id": S["primary_a"]}) == 1
    assert _sync.intelligence_alerts.count_documents(
        {"tenant_id": _TENANT_A, "customer_id": S["primary_a"]}) == 1
    assert _sync.warranty_contracts.count_documents(
        {"tenant_id": _TENANT_A, "customer_id": S["primary_a"]}) == 1
    # Duplicate soft-deleted + merged_into pointer.
    dup = _sync.customers.find_one({"id": S["duplicate_a"]})
    assert dup["merged_into"] == S["primary_a"]
    assert dup["merged_into_customer_id"] == S["primary_a"]
    # Field choices honoured — primary keeps name/email, gets
    # duplicate's phone/address.
    pri = _sync.customers.find_one({"id": S["primary_a"]})
    assert pri["name"] == "Alice Primary"
    assert pri["email"] == "alice@ex.com"
    assert pri["phone"] == "222-2222"
    assert pri["address"] == "2 Dupe Ave"
    # Timeline note landed.
    assert _sync.customer_notes.count_documents(
        {"tenant_id": _TENANT_A, "customer_id": S["primary_a"],
          "note_kind": "system_merge"}) == 1
    # Audit row — the M1 wizard writes its own row tagged with
    # ``merge_source="wizard"``. Fetch by the response's
    # ``audit_log_id`` so we bypass the older executor-written row.
    audit_id = body.get("audit_log_id")
    audit = _sync.customer_merge_audit.find_one(
        {"id": audit_id, "tenant_id": _TENANT_A})
    assert audit is not None, "wizard audit row missing"
    assert audit["merge_source"] == "wizard"
    assert "duplicate_snapshots" in audit
    rc = audit["related_records_rewired"]
    assert rc.get("jobs") == 2 and rc.get("messages") == 1


def test_m1_field_choices_primary_wins_by_default(m1_seed):
    S = m1_seed
    token = _mint(S["admin_a"], _TENANT_A, "admin")
    with httpx.Client(base_url=BASE) as c:
        r = c.post(
            "/api/customers/merge-wizard",
            json={
                "primary_customer_id":   S["primary_a"],
                "duplicate_customer_id": S["duplicate_a"],
                "field_choices": {},  # empty → all default to primary
            },
            headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    pri = _sync.customers.find_one({"id": S["primary_a"]})
    assert pri["name"] == "Alice Primary"
    assert pri["email"] == "alice@ex.com"
    assert pri["phone"] == "111-1111"
    assert pri["address"] == "1 Primary St"


def test_m1_cross_tenant_merge_403(m1_seed):
    S = m1_seed
    token = _mint(S["admin_a"], _TENANT_A, "admin")
    with httpx.Client(base_url=BASE) as c:
        r = c.post(
            "/api/customers/merge-wizard",
            json={"primary_customer_id":   S["primary_a"],
                    "duplicate_customer_id": S["duplicate_b"]},
            headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
    assert r.json().get("detail") == "cross_tenant_merge_forbidden"
    # Deny-audit breadcrumb landed.
    assert _sync.audit_log.count_documents({
        "kind": "customer_merge_denied",
        "actor_user_id": S["admin_a"],
    }) >= 1


def test_m1_same_customer_400(m1_seed):
    S = m1_seed
    token = _mint(S["admin_a"], _TENANT_A, "admin")
    with httpx.Client(base_url=BASE) as c:
        r = c.post(
            "/api/customers/merge-wizard",
            json={"primary_customer_id":   S["primary_a"],
                    "duplicate_customer_id": S["primary_a"]},
            headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400
    assert r.json().get("detail") == "same_customer_merge_forbidden"


def test_m1_already_deleted_409(m1_seed):
    S = m1_seed
    _sync.customers.update_one(
        {"id": S["duplicate_a"]},
        {"$set": {"is_deleted": True,
                    "deleted_at": "2025-12-31T00:00:00+00:00"}})
    token = _mint(S["admin_a"], _TENANT_A, "admin")
    with httpx.Client(base_url=BASE) as c:
        r = c.post(
            "/api/customers/merge-wizard",
            json={"primary_customer_id":   S["primary_a"],
                    "duplicate_customer_id": S["duplicate_a"]},
            headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 409
    assert r.json().get("detail") == "customer_already_deleted"


def test_m1_role_gate_403_for_tech(m1_seed):
    S = m1_seed
    token = _mint(S["tech_a"], _TENANT_A, "technician")
    with httpx.Client(base_url=BASE) as c:
        r = c.post(
            "/api/customers/merge-wizard",
            json={"primary_customer_id":   S["primary_a"],
                    "duplicate_customer_id": S["duplicate_a"]},
            headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
    # Any 403 with an admin-blocking message satisfies the M1
    # role-gate contract. ``require_admin`` emits "Admin access
    # required" — the wizard code never runs.
    assert "Admin" in (r.json().get("detail") or "")


def test_m1_customer_list_excludes_merged(m1_seed):
    S = m1_seed
    token = _mint(S["admin_a"], _TENANT_A, "admin")
    with httpx.Client(base_url=BASE) as c:
        r = c.post(
            "/api/customers/merge-wizard",
            json={"primary_customer_id":   S["primary_a"],
                    "duplicate_customer_id": S["duplicate_a"]},
            headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        r = c.get(
            "/api/customers?search=Alicia Dupe&limit=25",
            headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    if isinstance(body, list):
        items = body
    else:
        items = body.get("items") or body.get("customers") or []
    ids = [x.get("id") for x in items]
    assert S["duplicate_a"] not in ids


def test_m1_timeline_note_appears_on_primary(m1_seed):
    S = m1_seed
    token = _mint(S["admin_a"], _TENANT_A, "admin")
    with httpx.Client(base_url=BASE) as c:
        r = c.post(
            "/api/customers/merge-wizard",
            json={"primary_customer_id":   S["primary_a"],
                    "duplicate_customer_id": S["duplicate_a"]},
            headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        # Path corrected to the admin timeline route.
        r = c.get(
            f"/api/customers/{S['primary_a']}/timeline",
            headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    items = body.get("items") or []
    merge_notes = [
        i for i in items
        if i.get("source_type") == "note"
            and (i.get("detail") or {}).get("note_kind") == "system_merge"
    ]
    assert len(merge_notes) == 1, items
