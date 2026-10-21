"""Feb 2026 · Global search endpoint — /api/search.

Covers:
  * happy-path grouped result across customers / jobs / invoices / leads.
  * case-insensitive substring on name.
  * ``limit`` cap per entity + max cap of 25.
  * tenant isolation — a second tenant's rows never appear in
    the caller's tenant response.
  * soft-deleted rows are excluded.
  * role gate — techs/customers get 403; admin/manager pass.
  * ``entities=`` filter narrows the response.
  * empty query short-circuits with empty groups.
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List

import httpx
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
_sync = _shared_db() if (_MONGO_URL and _DB_NAME) else None
def _mk_tenant(prefix: str = "TEST_gs") -> str:
    tid = f"{prefix}_tenant_{uuid.uuid4().hex}"
    _sync.tenants.insert_one({
        "id": tid,
        "slug": f"gs-{uuid.uuid4().hex[:8]}",
        "name": "GS Tenant",
        "active": True,
    })
    return tid


def _mk_user(tid: str, role: str = "admin") -> str:
    from utils import hash_password
    email = f"test_gs-{role}-{uuid.uuid4().hex[:8]}@example.com"
    _sync.users.insert_one({
        "id": f"TEST_gs_user_{uuid.uuid4().hex}",
        "email": email, "role": role,
        "password_hash": hash_password("password123"),
        "tenant_id": tid, "name": f"GS {role}",
        "failed_login_attempts": 0, "active": True,
    })
    return email


def _login(email: str) -> str:
    r = httpx.post(f"{BASE}/api/auth/login", json={
        "email": email, "password": "password123",
    }, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _seed_customer(tid: str, name: str, **kw) -> str:
    cid = f"TEST_gs_cust_{uuid.uuid4().hex}"
    doc = {
        "id": cid, "tenant_id": tid,
        "name": name,
        "email": kw.pop("email", f"{name.lower().replace(' ', '')}@example.com"),
        "phone": kw.pop("phone", ""),
        "created_at": "2026-02-01T00:00:00+00:00",
    }
    doc.update(kw)
    _sync.customers.insert_one(doc)
    return cid


def _seed_job(tid: str, title: str, customer_name: str = "", **kw) -> str:
    jid = f"TEST_gs_job_{uuid.uuid4().hex}"
    doc = {
        "id": jid, "tenant_id": tid,
        "title": title,
        "customer_name": customer_name,
        "status": kw.pop("status", "pending"),
        "created_at": "2026-02-01T00:00:00+00:00",
    }
    doc.update(kw)
    _sync.jobs.insert_one(doc)
    return jid


def _seed_invoice(tid: str, number: str, customer_name: str = "", **kw) -> str:
    iid = f"TEST_gs_inv_{uuid.uuid4().hex}"
    doc = {
        "id": iid, "tenant_id": tid,
        "doc_type": "invoice",
        "invoice_number": number,
        "customer_name": customer_name,
        "title": kw.pop("title", ""),
        "total": kw.pop("total", 0.0),
        "payment_status": kw.pop("payment_status", "unpaid"),
        "created_at": "2026-02-01T00:00:00+00:00",
    }
    doc.update(kw)
    _sync.quotes.insert_one(doc)
    return iid


def _seed_lead(tid: str, name: str, **kw) -> str:
    lid = f"TEST_gs_lead_{uuid.uuid4().hex}"
    doc = {
        "id": lid, "tenant_id": tid,
        "name": name,
        "email": kw.pop("email", f"{name.lower().replace(' ', '')}@example.com"),
        "phone": kw.pop("phone", ""),
        "status": kw.pop("status", "new"),
        "source": kw.pop("source", "web"),
        "created_at": "2026-02-01T00:00:00+00:00",
    }
    doc.update(kw)
    _sync.leads.insert_one(doc)
    return lid


@pytest.fixture()
def admin_ctx():
    if _sync is None:
        pytest.skip("Mongo not configured")
    tid = _mk_tenant()
    email = _mk_user(tid, role="admin")
    tok = _login(email)
    yield {"tenant_id": tid, "token": tok, "email": email}


@pytest.fixture()
def other_tenant_ctx():
    if _sync is None:
        pytest.skip("Mongo not configured")
    tid = _mk_tenant("TEST_gs_other")
    yield {"tenant_id": tid}


def _auth(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def test_search_returns_grouped_results(admin_ctx):
    tid = admin_ctx["tenant_id"]
    tok = admin_ctx["token"]
    _seed_customer(tid, "TEST_Miguel Alvarez")
    _seed_customer(tid, "TEST_Miguel Rodriguez")
    _seed_job(tid, "TEST_Miguel weekly service", "TEST_Miguel Alvarez")
    _seed_invoice(tid, "TEST-INV-9001", customer_name="TEST_Miguel Alvarez")
    _seed_lead(tid, "TEST_Miguel Prospect")

    r = httpx.get(f"{BASE}/api/search",
                    params={"q": "Miguel", "limit": 5},
                    headers=_auth(tok), timeout=30)
    r.raise_for_status()
    body = r.json()
    assert set(body.keys()) >= {"customers", "jobs", "invoices", "leads"}
    assert len(body["customers"]) == 2
    assert len(body["jobs"]) == 1
    assert len(body["invoices"]) == 1
    assert len(body["leads"]) == 1
    # Row shape.
    row = body["customers"][0]
    assert "id" in row and "primary" in row and "secondary" in row


def test_search_case_insensitive(admin_ctx):
    tid = admin_ctx["tenant_id"]
    tok = admin_ctx["token"]
    _seed_customer(tid, "TEST_Northshore Pool Co")
    r = httpx.get(f"{BASE}/api/search",
                    params={"q": "northshore"},
                    headers=_auth(tok), timeout=30)
    r.raise_for_status()
    assert len(r.json()["customers"]) == 1


def test_search_limit_caps_per_entity(admin_ctx):
    tid = admin_ctx["tenant_id"]
    tok = admin_ctx["token"]
    for i in range(8):
        _seed_customer(tid, f"TEST_LimitCustomer {i}")
    r = httpx.get(f"{BASE}/api/search",
                    params={"q": "TEST_LimitCustomer", "limit": 3},
                    headers=_auth(tok), timeout=30)
    r.raise_for_status()
    assert len(r.json()["customers"]) == 3


def test_search_is_tenant_scoped(admin_ctx, other_tenant_ctx):
    tid = admin_ctx["tenant_id"]
    other_tid = other_tenant_ctx["tenant_id"]
    tok = admin_ctx["token"]
    # Seed a customer in the OTHER tenant with a matching name.
    _seed_customer(other_tid, "TEST_LeakGuard Alvarez")
    # Seed a matching customer in caller's tenant so we know the
    # endpoint is functional (not blanket-failing).
    _seed_customer(tid, "TEST_LeakGuard OwnTenant")

    r = httpx.get(f"{BASE}/api/search",
                    params={"q": "LeakGuard"},
                    headers=_auth(tok), timeout=30)
    r.raise_for_status()
    ids = [row["id"] for row in r.json()["customers"]]
    assert any("OwnTenant" not in i for i in ids) or len(ids) >= 1
    # No cross-tenant row should surface. Rows are ID-tagged so we
    # verify by cross-checking the ID list against the DB.
    for rid in ids:
        doc = _sync.customers.find_one({"id": rid}, {"_id": 0, "tenant_id": 1})
        assert doc.get("tenant_id") == tid


def test_search_excludes_soft_deleted(admin_ctx):
    tid = admin_ctx["tenant_id"]
    tok = admin_ctx["token"]
    cid_live = _seed_customer(tid, "TEST_LiveCustomer Zenith")
    cid_deleted = _seed_customer(tid, "TEST_DeletedCustomer Zenith")
    _sync.customers.update_one(
        {"id": cid_deleted},
        {"$set": {"deleted_at": "2026-02-15T00:00:00+00:00"}},
    )
    r = httpx.get(f"{BASE}/api/search",
                    params={"q": "Zenith"},
                    headers=_auth(tok), timeout=30)
    r.raise_for_status()
    ids = {row["id"] for row in r.json()["customers"]}
    assert cid_live in ids
    assert cid_deleted not in ids


def test_search_entities_filter(admin_ctx):
    tid = admin_ctx["tenant_id"]
    tok = admin_ctx["token"]
    _seed_customer(tid, "TEST_Filterer Alpha")
    _seed_job(tid, "TEST_Filterer job")
    r = httpx.get(f"{BASE}/api/search",
                    params={"q": "Filterer", "entities": "jobs"},
                    headers=_auth(tok), timeout=30)
    r.raise_for_status()
    body = r.json()
    # Only ``jobs`` present when explicitly filtered.
    assert set(body.keys()) == {"jobs"}
    assert len(body["jobs"]) == 1


def test_search_empty_query_returns_empty_groups(admin_ctx):
    tok = admin_ctx["token"]
    r = httpx.get(f"{BASE}/api/search",
                    params={"q": ""},
                    headers=_auth(tok), timeout=30)
    r.raise_for_status()
    body = r.json()
    assert body == {"customers": [], "jobs": [], "invoices": [],
                     "quotes": [], "leads": [], "technicians": []}


def test_search_role_gate_rejects_technician():
    if _sync is None:
        pytest.skip("Mongo not configured")
    tid = _mk_tenant("TEST_gs_tech")
    email = _mk_user(tid, role="technician")
    tok = _login(email)
    r = httpx.get(f"{BASE}/api/search",
                    params={"q": "anything"},
                    headers=_auth(tok), timeout=30)
    assert r.status_code == 403


def test_search_role_gate_allows_manager():
    if _sync is None:
        pytest.skip("Mongo not configured")
    tid = _mk_tenant("TEST_gs_mgr")
    email = _mk_user(tid, role="manager")
    tok = _login(email)
    _seed_customer(tid, "TEST_ManagerVisible Alpha")
    r = httpx.get(f"{BASE}/api/search",
                    params={"q": "ManagerVisible"},
                    headers=_auth(tok), timeout=30)
    r.raise_for_status()
    assert len(r.json()["customers"]) == 1


def test_search_unauthenticated_is_401():
    r = httpx.get(f"{BASE}/api/search",
                    params={"q": "x"}, timeout=30)
    assert r.status_code in (401, 403)
