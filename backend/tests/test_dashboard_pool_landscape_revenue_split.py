"""Feb 2026 · Batch 2 — Pool vs Landscape revenue split.

Backend pytest coverage for the additive fields on
``GET /api/dashboard``:

  * ``pool_revenue``       — dollars from invoices attributed to Pool
  * ``landscape_revenue``  — dollars from invoices attributed to Landscape
  * ``mixed_revenue``      — dollars from invoices in the mixed bucket

Cases exercised
---------------
1. Seed 3 paid invoices (2 pool, 1 landscape) under a fresh test
   tenant → the endpoint attributes each correctly.
2. Seed an unlabelled paid invoice (title = ``"Monthly Service"``,
   no pool/landscape keyword AND no customer service_type match) →
   goes to ``mixed_revenue``.
3. Seed zero paid invoices → all three fields are ``0``.
4. Regression — the existing ``revenue`` scalar equals the sum of
   the three new fields (invariant guaranteed by the mutually-
   exclusive bucket rule).
5. Existing consumers unaffected — every prior response key is
   still present.
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict

import httpx
import pytest
from dotenv import dotenv_values
from pymongo import MongoClient


BASE = "http://localhost:8001"

_ENV = dotenv_values("/app/backend/.env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync_db = MongoClient(_MONGO_URL)[_DB_NAME] if (_MONGO_URL and _DB_NAME) else None


def _hash(pw: str) -> str:
    from utils import hash_password
    return hash_password(pw)


def _seed_test_tenant() -> Dict[str, Any]:
    """Seed a fresh tenant with an admin user we can log in as, then
    yield ``{tenant_id, admin_email}`` to the test."""
    tenant_id = f"TEST_tenant_{uuid.uuid4().hex}"
    admin_email = f"test-dashadmin-{uuid.uuid4().hex[:8]}@example.com"
    _sync_db.tenants.insert_one({
        "id": tenant_id, "slug": f"test-dash-{uuid.uuid4().hex[:8]}",
        "name": "Test Dash Tenant", "active": True,
        "created_at": "2026-08-27T00:00:00+00:00",
    })
    _sync_db.users.insert_one({
        "id": f"TEST_admin_{uuid.uuid4().hex}",
        "email": admin_email, "role": "admin",
        "password_hash": _hash("password123"),
        "tenant_id": tenant_id, "name": "Test Dash Admin",
        "failed_login_attempts": 0, "active": True,
    })
    return {"tenant_id": tenant_id, "admin_email": admin_email}


def _cleanup(tenant_id: str, admin_email: str):
    if _sync_db is None:
        return
    _sync_db.tenants.delete_many({"id": tenant_id})
    _sync_db.users.delete_many({"email": admin_email})
    _sync_db.customers.delete_many({"tenant_id": tenant_id})
    _sync_db.quotes.delete_many({"tenant_id": tenant_id})


def _login(email: str) -> str:
    r = httpx.post(f"{BASE}/api/auth/login", json={
        "email": email, "password": "password123",
    }, timeout=60)
    r.raise_for_status()
    b = r.json()
    return b.get("access_token") or b.get("token") or ""


def _dashboard(tok: str) -> Dict[str, Any]:
    r = httpx.get(f"{BASE}/api/dashboard",
                   headers={"Authorization": f"Bearer {tok}"}, timeout=60)
    r.raise_for_status()
    return r.json()


def _mk_paid_invoice(*, tenant_id: str, title: str, total: float,
                       customer_id: str) -> str:
    """Insert a paid invoice via pymongo. Returns invoice id."""
    inv_id = f"TEST_inv_{uuid.uuid4().hex}"
    _sync_db.quotes.insert_one({
        "id": inv_id, "tenant_id": tenant_id,
        "customer_id": customer_id,
        "doc_type": "invoice",
        "title": title,
        "total": float(total),
        "payment_status": "paid",
        "status": "paid",
        "paid_at": "2026-08-27T00:00:00+00:00",
        "created_at": "2026-08-27T00:00:00+00:00",
    })
    return inv_id


def _mk_customer(*, tenant_id: str, service_type: str = "") -> str:
    cid = f"TEST_cust_{uuid.uuid4().hex}"
    _sync_db.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "Test Cust", "email": f"cust-{cid[:8]}@example.com",
        "service_type": service_type,
    })
    return cid


# ────────────────────────────────────────────────────────────────────
# 1. Seed 2 pool + 1 landscape → correct bucket totals
# ────────────────────────────────────────────────────────────────────
def test_pool_landscape_split_attributes_paid_invoices_correctly():
    seed = _seed_test_tenant()
    tid, email = seed["tenant_id"], seed["admin_email"]
    try:
        c1 = _mk_customer(tenant_id=tid, service_type="Weekly Pool Service")
        c2 = _mk_customer(tenant_id=tid, service_type="Landscape Maintenance")
        _mk_paid_invoice(tenant_id=tid, title="Monthly Pool Service",
                          total=200.00, customer_id=c1)
        _mk_paid_invoice(tenant_id=tid, title="Pool Repair",
                          total=350.00, customer_id=c1)
        _mk_paid_invoice(tenant_id=tid, title="Landscape Package",
                          total=450.00, customer_id=c2)

        tok = _login(email)
        d = _dashboard(tok)
        assert "pool_revenue" in d
        assert "landscape_revenue" in d
        assert "mixed_revenue" in d
        # 200 + 350 = 550 pool; 450 landscape; 0 mixed.
        assert d["pool_revenue"] == pytest.approx(550.00, abs=0.01)
        assert d["landscape_revenue"] == pytest.approx(450.00, abs=0.01)
        assert d["mixed_revenue"] == pytest.approx(0.00, abs=0.01)
        # Invariant: pool + landscape + mixed == revenue.
        assert (
            d["pool_revenue"] + d["landscape_revenue"] + d["mixed_revenue"]
        ) == pytest.approx(d["revenue"], abs=0.01)
    finally:
        _cleanup(tid, email)


# ────────────────────────────────────────────────────────────────────
# 2. Unlabelled invoice → mixed bucket
# ────────────────────────────────────────────────────────────────────
def test_ambiguous_invoice_goes_to_mixed_bucket():
    seed = _seed_test_tenant()
    tid, email = seed["tenant_id"], seed["admin_email"]
    try:
        c = _mk_customer(tenant_id=tid, service_type="")
        _mk_paid_invoice(tenant_id=tid, title="Monthly Service",
                          total=125.00, customer_id=c)
        _mk_paid_invoice(tenant_id=tid, title="Commercial Service",
                          total=75.00, customer_id=c)

        tok = _login(email)
        d = _dashboard(tok)
        assert d["pool_revenue"] == 0.0
        assert d["landscape_revenue"] == 0.0
        assert d["mixed_revenue"] == pytest.approx(200.00, abs=0.01)
        assert d["revenue"] == pytest.approx(200.00, abs=0.01)
    finally:
        _cleanup(tid, email)


# ────────────────────────────────────────────────────────────────────
# 3. Zero-revenue → all three fields 0
# ────────────────────────────────────────────────────────────────────
def test_zero_revenue_tenant_returns_all_zero_split():
    seed = _seed_test_tenant()
    tid, email = seed["tenant_id"], seed["admin_email"]
    try:
        tok = _login(email)
        d = _dashboard(tok)
        assert d["revenue"] == 0.0
        assert d["pool_revenue"] == 0.0
        assert d["landscape_revenue"] == 0.0
        assert d["mixed_revenue"] == 0.0
    finally:
        _cleanup(tid, email)


# ────────────────────────────────────────────────────────────────────
# 4. Mixed keywords (title has BOTH pool + landscape) → mixed bucket
# ────────────────────────────────────────────────────────────────────
def test_invoice_with_both_keywords_goes_to_mixed():
    seed = _seed_test_tenant()
    tid, email = seed["tenant_id"], seed["admin_email"]
    try:
        c = _mk_customer(tenant_id=tid, service_type="")
        _mk_paid_invoice(tenant_id=tid,
                          title="Pool + Landscape combo package",
                          total=800.00, customer_id=c)
        tok = _login(email)
        d = _dashboard(tok)
        assert d["mixed_revenue"] == pytest.approx(800.00, abs=0.01)
        assert d["pool_revenue"] == 0.0
        assert d["landscape_revenue"] == 0.0
    finally:
        _cleanup(tid, email)


# ────────────────────────────────────────────────────────────────────
# 5. Regression — customer service_type signal wins when title is
#    ambiguous ("Monthly Service") but customer.service_type is
#    "Weekly Pool Service" → pool
# ────────────────────────────────────────────────────────────────────
def test_customer_service_type_disambiguates_generic_title():
    seed = _seed_test_tenant()
    tid, email = seed["tenant_id"], seed["admin_email"]
    try:
        c_pool = _mk_customer(tenant_id=tid,
                                service_type="Weekly Pool Service")
        c_land = _mk_customer(tenant_id=tid,
                                service_type="Weekly Lawn Care")
        _mk_paid_invoice(tenant_id=tid, title="Monthly Service",
                          total=100.00, customer_id=c_pool)
        _mk_paid_invoice(tenant_id=tid, title="Monthly Service",
                          total=200.00, customer_id=c_land)

        tok = _login(email)
        d = _dashboard(tok)
        assert d["pool_revenue"] == pytest.approx(100.00, abs=0.01)
        assert d["landscape_revenue"] == pytest.approx(200.00, abs=0.01)
        assert d["mixed_revenue"] == 0.0
    finally:
        _cleanup(tid, email)


# ────────────────────────────────────────────────────────────────────
# 6. Regression — existing consumers unaffected. Every prior
#    response key still present alongside the new fields.
# ────────────────────────────────────────────────────────────────────
def test_existing_dashboard_response_keys_preserved():
    seed = _seed_test_tenant()
    tid, email = seed["tenant_id"], seed["admin_email"]
    try:
        tok = _login(email)
        d = _dashboard(tok)
        for key in (
            "role", "revenue", "outstanding", "active_jobs",
            "pending_jobs", "completed_jobs", "requested_jobs",
            "total_customers", "total_technicians", "total_leads",
            "open_leads", "recent_jobs", "revenue_series",
            "revenue_by_service", "recurring_vs_project",
        ):
            assert key in d, f"missing prior key: {key}"
        # New keys additive.
        for key in ("pool_revenue", "landscape_revenue", "mixed_revenue"):
            assert key in d, f"missing new key: {key}"
    finally:
        _cleanup(tid, email)
