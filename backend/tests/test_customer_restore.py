"""Feb-2026 · P26 — PATCH /customers/{cid}/restore.

Six assertions covering the round-trip on top of P25's read-filter:

  1. Non-super_admin (admin, technician, customer) → 403 role_not_permitted.
  2. Happy path — soft-deleted customer restored; ``deleted_at`` unset;
     response shape ``{restored: true, customer_id, was_anonymized, restored_at}``.
  3. Idempotent — restoring a non-soft-deleted customer returns 200 with
     ``{restored: false, reason: "not_soft_deleted"}``.
  4. Anonymized customer restore surfaces ``was_anonymized: true`` and
     clears BOTH ``deleted_at`` and ``anonymized_at``; PII stays scrubbed.
  5. 404 for a non-existent customer id.
  6. Audit-log entry lands in ``audit_logs`` with the expected event
     name and actor metadata.

Live HTTP + sync pymongo, mirrors the P25 test scaffolding.
"""
from __future__ import annotations

import time
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
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


@pytest.fixture
def super_h():
    return _hdrs("super@aquaterra.com")


@pytest.fixture
def admin_h():
    return _hdrs("admin@aquaterra.com")


@pytest.fixture
def tech_h():
    return _hdrs("mike@aquaterra.com")


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one(
        {"email": "admin@aquaterra.com"})["tenant_id"]


def _seed_customer(tid: str, *, deleted: bool = False,
                     anonymized: bool = False) -> str:
    cid = f"TEST_p26_c_{uuid.uuid4().hex[:8]}"
    doc = {
        "id": cid, "tenant_id": tid,
        "name": f"TEST P26 {'(anon)' if anonymized else '(active)'}",
        "email": f"{cid}@example.com",
        "phone": "6235550100",
        "address": "1 Test St",
        "created_at": "2026-06-01T09:00:00+00:00",
    }
    if deleted or anonymized:
        doc["deleted_at"] = "2026-06-01T10:00:00+00:00"
    if anonymized:
        doc["name"] = "Deleted Customer"
        doc["email"] = None
        doc["phone"] = None
        doc["address"] = None
        doc["anonymized_at"] = "2026-06-01T10:00:00+00:00"
    _sync.customers.insert_one(doc)
    return cid


def _cleanup(ids: list[str]) -> None:
    if ids:
        _sync.customers.delete_many({"id": {"$in": ids}})
        _sync.audit_logs.delete_many({"customer_id": {"$in": ids}})


# ─── 1. Auth gating ──────────────────────────────────────────────────

def test_restore_requires_super_admin(admin_h, tech_h, aquaterra_tid):
    cid = _seed_customer(aquaterra_tid, deleted=True)
    try:
        r_admin = requests.patch(f"{API}/customers/{cid}/restore",
                                    headers=admin_h, timeout=15)
        assert r_admin.status_code == 403, r_admin.text
        body = r_admin.json().get("detail") or {}
        assert isinstance(body, dict), body
        assert body.get("detail") == "role_not_permitted"

        r_tech = requests.patch(f"{API}/customers/{cid}/restore",
                                   headers=tech_h, timeout=15)
        assert r_tech.status_code == 403, r_tech.text

        # And the row is still soft-deleted (nothing was mutated).
        doc = _sync.customers.find_one({"id": cid})
        assert doc.get("deleted_at"), "403 must not touch the row"
    finally:
        _cleanup([cid])


# ─── 2. Happy path ───────────────────────────────────────────────────

def test_restore_happy_path_unsets_deleted_at(super_h, aquaterra_tid):
    cid = _seed_customer(aquaterra_tid, deleted=True)
    try:
        r = requests.patch(f"{API}/customers/{cid}/restore",
                              headers=super_h, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["restored"] is True
        assert body["customer_id"] == cid
        assert body["was_anonymized"] is False
        assert "restored_at" in body

        doc = _sync.customers.find_one({"id": cid}) or {}
        assert "deleted_at" not in doc or doc.get("deleted_at") in (None, ""), \
            "deleted_at must be unset after restore"
        assert doc.get("restored_at"), "restored_at breadcrumb should be set"

        # And the row is now visible in the default list.
        r_list = requests.get(f"{API}/customers", headers=super_h, timeout=15)
        assert r_list.status_code == 200
        ids = {row["id"] for row in r_list.json()}
        assert cid in ids
    finally:
        _cleanup([cid])


# ─── 3. Idempotent branch ────────────────────────────────────────────

def test_restore_on_non_deleted_customer_is_idempotent(super_h, aquaterra_tid):
    cid = _seed_customer(aquaterra_tid, deleted=False)
    try:
        r = requests.patch(f"{API}/customers/{cid}/restore",
                              headers=super_h, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body == {
            "restored": False,
            "reason": "not_soft_deleted",
            "customer_id": cid,
            "was_anonymized": False,
        }
    finally:
        _cleanup([cid])


# ─── 4. Anonymized restore ───────────────────────────────────────────

def test_restore_anonymized_customer_flags_was_anonymized(super_h, aquaterra_tid):
    """P11b anonymized rows: restore clears both deleted_at AND
    anonymized_at, response flags was_anonymized=true, PII stays scrubbed."""
    cid = _seed_customer(aquaterra_tid, anonymized=True)
    try:
        r = requests.patch(f"{API}/customers/{cid}/restore",
                              headers=super_h, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["restored"] is True
        assert body["was_anonymized"] is True

        doc = _sync.customers.find_one({"id": cid}) or {}
        assert "deleted_at" not in doc or doc.get("deleted_at") in (None, "")
        assert "anonymized_at" not in doc or doc.get("anonymized_at") in (None, "")
        # PII scrub is one-way — name is still the placeholder.
        assert doc.get("name") == "Deleted Customer"
        assert doc.get("email") is None
        assert doc.get("phone") is None
    finally:
        _cleanup([cid])


# ─── 5. 404 for non-existent id ──────────────────────────────────────

def test_restore_returns_404_for_nonexistent_customer(super_h):
    fake_id = f"TEST_p26_missing_{uuid.uuid4().hex[:8]}"
    r = requests.patch(f"{API}/customers/{fake_id}/restore",
                          headers=super_h, timeout=15)
    assert r.status_code == 404, r.text
    assert r.json().get("detail") == "Customer not found"


# ─── 6. Audit log entry ──────────────────────────────────────────────

def test_restore_writes_audit_log_entry(super_h, aquaterra_tid):
    cid = _seed_customer(aquaterra_tid, deleted=True)
    try:
        r = requests.patch(f"{API}/customers/{cid}/restore",
                              headers=super_h, timeout=15)
        assert r.status_code == 200, r.text
        # The audit-log write is wrapped in try/except so give the
        # server a tick to persist before asserting.
        entry = None
        for _ in range(10):
            entry = _sync.audit_logs.find_one({
                "event": "customer_restore",
                "customer_id": cid,
            })
            if entry:
                break
            time.sleep(0.05)
        assert entry is not None, "audit_logs entry not found"
        assert entry["tenant_id"] == aquaterra_tid
        assert entry["actor_email"] == "super@aquaterra.com"
        assert entry["actor_role"] == "super_admin"
        assert entry["was_anonymized"] is False
        assert entry.get("restored_at")
        assert entry.get("created_at")
    finally:
        _cleanup([cid])
