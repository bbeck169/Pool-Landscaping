"""Phase 4b · Feb-2026 — Quotes bulk Accept / Decline / Delete endpoints.

Locks the contract on the three new routes:

  * ``POST /api/quotes/bulk-accept``
  * ``POST /api/quotes/bulk-decline``
  * ``POST /api/quotes/bulk-delete``

Each returns ``{"succeeded": [...], "skipped": [{"id","reason"}, ...],
"counts": {...}}`` and never 4xxs on partial / zero success.

Scenarios:
  * All eligible → succeeded only
  * Mixed → partial envelope shape
  * Role gate (admin/super_admin/owner/manager allowed; tech/dispatcher 403)
  * Tenant isolation — quote owned by another tenant surfaces as
    ``skipped[reason="not_found"]``
  * Delete respects the "no converted invoice" guard (bulk soft-delete
    with ``converted_invoice_id`` set is skipped, not actioned)
  * Duplicate ids in a single batch are de-duplicated once
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import dotenv_values

from tests._shared_mongo import shared_db as _shared_db


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

JWT_SECRET = (
    _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
    or "dev-secret-change-me"
)
JWT_ALGO = "HS256"


def _tok(uid, email, tid, role):
    return jwt.encode(
        {"sub": uid, "email": email, "role": role, "tenant_id": tid,
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        JWT_SECRET, algorithm=JWT_ALGO,
    )


def _auth(token, tenant_id):
    return {"Authorization": f"Bearer {token}", "X-Tenant-Id": tenant_id}


def _seed_user(tenant_id, role, label):
    uid = f"{label}-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@p4b.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": f"P4b {role}", "email": email,
    })
    return {
        "id": uid, "email": email, "tenant_id": tenant_id,
        "role": role, "token": _tok(uid, email, tenant_id, role),
    }


def _seed_quote(tenant_id, *, status="draft", decision=None,
                doc_type="quote", converted_invoice_id=None,
                deleted_at=None, title=None):
    qid = f"q-{uuid.uuid4().hex[:8]}"
    doc = {
        "id":            qid,
        "tenant_id":     tenant_id,
        "doc_type":      doc_type,
        "status":        status,
        "customer_id":   f"c-{uuid.uuid4().hex[:6]}",
        "customer_name": "P4b Customer",
        "title":         title or f"P4b quote {qid}",
        "total":         150.0,
        "created_at":    "2026-02-10T12:00:00+00:00",
    }
    if decision:
        doc["decision"] = decision
    if converted_invoice_id:
        doc["converted_invoice_id"] = converted_invoice_id
    if deleted_at:
        doc["deleted_at"] = deleted_at
    _sync.quotes.insert_one(doc)
    return qid


@pytest.fixture
def tenant_id():
    tid = f"p4b-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": tid, "name": "P4b smoke", "slug": tid, "active": True,
    })
    yield tid
    for col in ("tenants", "users", "quotes", "audit_logs",
                "audit_log", "doc_edit_audit",
                "deletion_audit"):
        _sync[col].delete_many({"tenant_id": tid})


@pytest.fixture
def admin(tenant_id):
    return _seed_user(tenant_id, "admin", "adm")


@pytest.fixture
def manager(tenant_id):
    return _seed_user(tenant_id, "manager", "mgr")


@pytest.fixture
def tech(tenant_id):
    return _seed_user(tenant_id, "technician", "tech")


# ══════════════════════════════════════════════════════════════════
#  Bulk Accept
# ══════════════════════════════════════════════════════════════════

def test_bulk_accept_all_eligible(tenant_id, admin):
    ids = [_seed_quote(tenant_id, status="draft") for _ in range(3)]
    r = requests.post(f"{API}/quotes/bulk-accept",
                      headers=_auth(admin["token"], tenant_id),
                      json={"quote_ids": ids}, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["succeeded"]) == set(ids)
    assert body["skipped"] == []
    assert body["counts"] == {"succeeded": 3, "skipped": 0, "total": 3}
    for qid in ids:
        doc = _sync.quotes.find_one({"id": qid, "tenant_id": tenant_id},
                                      {"_id": 0, "decision": 1, "status": 1})
        assert doc["decision"] == "accepted"
        assert doc["status"] == "accepted"


def test_bulk_accept_mixed_eligibility_returns_partial_envelope(tenant_id, admin):
    ok_a = _seed_quote(tenant_id, status="draft")
    ok_b = _seed_quote(tenant_id, status="sent")
    already_declined = _seed_quote(tenant_id, status="declined")
    already_decided  = _seed_quote(tenant_id, status="sent",
                                     decision="accepted")
    converted = _seed_quote(tenant_id, status="draft",
                              converted_invoice_id="inv-x")
    not_a_quote = _seed_quote(tenant_id, doc_type="invoice",
                               status="draft")
    r = requests.post(
        f"{API}/quotes/bulk-accept",
        headers=_auth(admin["token"], tenant_id),
        json={"quote_ids": [ok_a, already_declined, ok_b,
                             already_decided, converted,
                             not_a_quote, "ghost-id-xyz"]},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["succeeded"]) == {ok_a, ok_b}
    reasons = {s["id"]: s["reason"] for s in body["skipped"]}
    assert reasons[already_declined] == "already_declined"
    assert reasons[already_decided]  == "already_decided"
    assert reasons[converted]        == "already_converted"
    assert reasons[not_a_quote]      == "not_a_quote"
    assert reasons["ghost-id-xyz"]   == "not_found"
    assert body["counts"]["succeeded"] == 2
    assert body["counts"]["skipped"]   == 5


def test_bulk_accept_deduplicates_duplicate_ids(tenant_id, admin):
    qid = _seed_quote(tenant_id, status="draft")
    r = requests.post(f"{API}/quotes/bulk-accept",
                      headers=_auth(admin["token"], tenant_id),
                      json={"quote_ids": [qid, qid, qid]}, timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert body["succeeded"] == [qid]
    # Two duplicate occurrences skipped with duplicate_id reason.
    dupes = [s for s in body["skipped"] if s["reason"] == "duplicate_id"]
    assert len(dupes) == 2


# ══════════════════════════════════════════════════════════════════
#  Bulk Decline
# ══════════════════════════════════════════════════════════════════

def test_bulk_decline_all_eligible(tenant_id, admin):
    ids = [_seed_quote(tenant_id, status=s) for s in ("draft", "sent", "accepted")]
    r = requests.post(f"{API}/quotes/bulk-decline",
                      headers=_auth(admin["token"], tenant_id),
                      json={"quote_ids": ids}, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["succeeded"]) == set(ids)
    assert body["skipped"] == []
    for qid in ids:
        doc = _sync.quotes.find_one({"id": qid, "tenant_id": tenant_id},
                                      {"_id": 0, "status": 1,
                                       "previous_status": 1})
        assert doc["status"] == "declined"
        assert doc["previous_status"] in ("draft", "sent", "accepted")


def test_bulk_decline_mixed_eligibility(tenant_id, admin):
    ok = _seed_quote(tenant_id, status="draft")
    already_declined = _seed_quote(tenant_id, status="declined")
    converted = _seed_quote(tenant_id, status="draft",
                              converted_invoice_id="inv-x")
    not_a_quote = _seed_quote(tenant_id, doc_type="invoice",
                               status="draft")
    r = requests.post(
        f"{API}/quotes/bulk-decline",
        headers=_auth(admin["token"], tenant_id),
        json={"quote_ids": [ok, already_declined, converted,
                             not_a_quote, "ghost"]},
        timeout=20,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["succeeded"] == [ok]
    reasons = {s["id"]: s["reason"] for s in body["skipped"]}
    assert reasons[already_declined] == "already_declined"
    assert reasons[converted]        == "already_converted"
    assert reasons[not_a_quote]      == "not_a_quote"
    assert reasons["ghost"]          == "not_found"


# ══════════════════════════════════════════════════════════════════
#  Bulk Delete
# ══════════════════════════════════════════════════════════════════

def test_bulk_delete_all_eligible(tenant_id, admin):
    ids = [_seed_quote(tenant_id, status="draft") for _ in range(3)]
    r = requests.post(f"{API}/quotes/bulk-delete",
                      headers=_auth(admin["token"], tenant_id),
                      json={"quote_ids": ids}, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["succeeded"]) == set(ids)
    assert body["skipped"] == []
    for qid in ids:
        doc = _sync.quotes.find_one({"id": qid, "tenant_id": tenant_id},
                                      {"_id": 0, "deleted_at": 1})
        assert doc.get("deleted_at")


def test_bulk_delete_mixed_eligibility_including_invoiced(tenant_id, admin):
    ok = _seed_quote(tenant_id, status="draft")
    already_deleted = _seed_quote(tenant_id, status="draft",
                                    deleted_at="2026-02-10T00:00:00+00:00")
    converted = _seed_quote(tenant_id, status="draft",
                              converted_invoice_id="inv-x")
    r = requests.post(
        f"{API}/quotes/bulk-delete",
        headers=_auth(admin["token"], tenant_id),
        json={"quote_ids": [ok, already_deleted, converted, "ghost"]},
        timeout=20,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["succeeded"] == [ok]
    reasons = {s["id"]: s["reason"] for s in body["skipped"]}
    assert reasons[already_deleted] == "already_deleted"
    assert reasons[converted]       == "already_converted"
    assert reasons["ghost"]         == "not_found"


# ══════════════════════════════════════════════════════════════════
#  Role gate
# ══════════════════════════════════════════════════════════════════

def test_tech_cannot_call_bulk_accept(tenant_id, tech):
    qid = _seed_quote(tenant_id, status="draft")
    r = requests.post(f"{API}/quotes/bulk-accept",
                      headers=_auth(tech["token"], tenant_id),
                      json={"quote_ids": [qid]}, timeout=20)
    assert r.status_code == 403, r.text


def test_tech_cannot_call_bulk_decline(tenant_id, tech):
    qid = _seed_quote(tenant_id, status="draft")
    r = requests.post(f"{API}/quotes/bulk-decline",
                      headers=_auth(tech["token"], tenant_id),
                      json={"quote_ids": [qid]}, timeout=20)
    assert r.status_code == 403, r.text


def test_tech_cannot_call_bulk_delete(tenant_id, tech):
    qid = _seed_quote(tenant_id, status="draft")
    r = requests.post(f"{API}/quotes/bulk-delete",
                      headers=_auth(tech["token"], tenant_id),
                      json={"quote_ids": [qid]}, timeout=20)
    assert r.status_code == 403, r.text


def test_manager_can_call_all_three(tenant_id, manager):
    for route in ("bulk-accept", "bulk-decline", "bulk-delete"):
        qid = _seed_quote(tenant_id, status="draft")
        r = requests.post(f"{API}/quotes/{route}",
                          headers=_auth(manager["token"], tenant_id),
                          json={"quote_ids": [qid]}, timeout=20)
        assert r.status_code == 200, (route, r.text)
        assert qid in r.json()["succeeded"], (route, r.text)


# ══════════════════════════════════════════════════════════════════
#  Tenant isolation
# ══════════════════════════════════════════════════════════════════

def test_cross_tenant_quote_surfaces_as_not_found(tenant_id, admin):
    # Spin up a second tenant and seed a quote there — the admin from
    # ``tenant_id`` must NOT be able to act on it; the bulk endpoint
    # should surface it as ``skipped[reason=not_found]`` and NEVER
    # mutate the row.
    other_tid = f"p4b-other-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": other_tid, "name": "P4b other tenant", "slug": other_tid,
        "active": True,
    })
    try:
        other_qid = _seed_quote(other_tid, status="draft")
        mine     = _seed_quote(tenant_id, status="draft")
        r = requests.post(
            f"{API}/quotes/bulk-accept",
            headers=_auth(admin["token"], tenant_id),
            json={"quote_ids": [mine, other_qid]}, timeout=20,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["succeeded"] == [mine]
        reasons = {s["id"]: s["reason"] for s in body["skipped"]}
        assert reasons[other_qid] == "not_found", body
        # Cross-tenant row untouched.
        other_doc = _sync.quotes.find_one({"id": other_qid},
                                           {"_id": 0, "decision": 1,
                                            "status": 1})
        assert other_doc.get("decision") in (None, "")
        assert other_doc.get("status") == "draft"
    finally:
        for col in ("tenants", "quotes"):
            _sync[col].delete_many({"tenant_id": other_tid})


# ══════════════════════════════════════════════════════════════════
#  OpenAPI contract
# ══════════════════════════════════════════════════════════════════

def test_openapi_lists_all_three_bulk_endpoints():
    r = requests.get(f"{API}/openapi.json", timeout=15)
    assert r.status_code == 200
    paths = r.json().get("paths", {})
    for route in ("/api/quotes/bulk-accept",
                  "/api/quotes/bulk-decline",
                  "/api/quotes/bulk-delete"):
        assert route in paths, f"{route} missing from OpenAPI"
        assert "post" in paths[route], (
            f"{route} must expose a POST operation"
        )
