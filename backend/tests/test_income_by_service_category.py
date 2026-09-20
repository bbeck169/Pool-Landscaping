"""Income by Service Category tile · Feb-2026."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = _shared_client()
_db = _shared_db()
_CACHE: dict = {}


def _login(email: str) -> str:
    key = f"tok:{email}"
    if _CACHE.get(key):
        return _CACHE[key]
    for _ in range(3):
        try:
            r = requests.post(f"{API}/auth/login",
                               json={"email": email, "password": "password123"},
                               timeout=30)
            if r.status_code == 200:
                _CACHE[key] = r.json()["access_token"]
                return _CACHE[key]
        except requests.exceptions.RequestException:
            continue
    raise RuntimeError(f"login failed for {email}")


def _seed_isolated_tenant():
    tid = f"TEST-isvc-tenant-{uuid.uuid4().hex[:6]}"
    _db.tenants.insert_one({"id": tid,
                             "slug": f"test-isvc-{uuid.uuid4().hex[:6]}",
                             "name": "TEST_isvc", "active": True})
    return tid


def _seed_admin(tid):
    from utils import hash_password
    uid = f"TEST-isvc-u-{uuid.uuid4().hex[:6]}"
    email = f"isvc-{uuid.uuid4().hex[:6]}@example.com"
    _db.users.insert_one({"id": uid, "tenant_id": tid, "email": email,
                           "name": "TEST_isvc_admin", "role": "admin",
                           "password_hash": hash_password("password123")})
    return uid, email, _login(email)


def _cleanup(tid, uid, email):
    _db.users.delete_one({"id": uid})
    _db.tenants.delete_one({"id": tid})
    _db.service_categories.delete_many({"tenant_id": tid})
    _db.items.delete_many({"tenant_id": tid})
    _db.quotes.delete_many({"tenant_id": tid})
    _CACHE.pop(f"tok:{email}", None)


def _seed_svc_cat(tid, name):
    cid = f"TEST-svccat-{uuid.uuid4().hex[:6]}"
    _db.service_categories.insert_one({
        "id": cid, "tenant_id": tid, "name": name, "is_archived": False,
        "sort_order": 0, "color": "#000000",
    })
    return cid


def _seed_pricebook_item(tid, svc_id, name):
    iid = f"TEST-item-{uuid.uuid4().hex[:6]}"
    _db.items.insert_one({
        "id": iid, "tenant_id": tid, "name": name,
        "service_category_id": svc_id, "unit_price": 100.0,
    })
    return iid


def _seed_invoice(tid, *, created_at, line_items):
    iid = f"TEST-inv-{uuid.uuid4().hex[:6]}"
    total = sum((li.get("quantity", 0) * li.get("unit_price", 0))
                for li in line_items)
    _db.quotes.insert_one({
        "id": iid, "tenant_id": tid, "doc_type": "invoice",
        "invoice_number": iid, "created_at": created_at,
        # Feb-2026 · fixture-drift fix: the ``dashboard_revenue.py``
        # handler filters on ``payment_status="paid"`` (added by the
        # Feb-2026 Dashboard consistency ship), NOT on the document
        # ``status`` field which tracks lifecycle state (draft →
        # sent → paid).  Seed both so the fixture matches the
        # handler's read contract.
        "status": "paid", "payment_status": "paid",
        "currency": "USD",
        "total": total, "subtotal": total,
        "line_items": line_items,
    })
    return iid


# 1. Admin happy path
def test_income_by_service_category_admin_success():
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin(tid)
    pool = _seed_svc_cat(tid, "Pool")
    land = _seed_svc_cat(tid, "Landscaping")
    p_item = _seed_pricebook_item(tid, pool, "Weekly Pool")
    l_item = _seed_pricebook_item(tid, land, "Lawn Care")
    inv = _seed_invoice(tid, created_at="2027-04-15T12:00:00+00:00",
                          line_items=[
                              {"description": "P1", "quantity": 2, "unit_price": 50,
                                "item_id": p_item},
                              {"description": "P2", "quantity": 4, "unit_price": 25,
                                "item_id": p_item},
                              {"description": "L1", "quantity": 1, "unit_price": 150,
                                "item_id": l_item},
                          ])
    try:
        r = requests.get(
            f"{API}/admin/dashboard/income-by-service-category"
            f"?start=2027-04-01&end=2027-04-30",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        by = {i["category"]: i for i in body["items"]}
        assert by["Pool"]["amount"] == 200.0     # 2*50 + 4*25
        assert by["Pool"]["count"] == 2
        assert by["Landscaping"]["amount"] == 150.0
        assert body["total"] == 350.0
    finally:
        _cleanup(tid, uid, email)


# 2. Non-admin 403
def test_income_by_service_category_non_admin_403():
    tok = _login("customer@aquaterra.com")
    r = requests.get(
        f"{API}/admin/dashboard/income-by-service-category"
        f"?start=2027-01-01&end=2027-01-31",
        headers={"Authorization": f"Bearer {tok}"}, timeout=15,
    )
    assert r.status_code == 403


# 3. Tenant isolation
def test_income_by_service_category_tenant_isolation():
    # Seed tenant A with data; login as tenant B admin (isolated) and
    # confirm A's data doesn't leak.
    tid_a = _seed_isolated_tenant()
    uid_a, email_a, _tok_a = _seed_admin(tid_a)
    pool = _seed_svc_cat(tid_a, "Pool")
    p_item = _seed_pricebook_item(tid_a, pool, "Weekly")
    _seed_invoice(tid_a, created_at="2027-05-15T12:00:00+00:00",
                  line_items=[{"description": "leak", "quantity": 1,
                                "unit_price": 9999, "item_id": p_item}])
    tid_b = _seed_isolated_tenant()
    uid_b, email_b, tok_b = _seed_admin(tid_b)
    try:
        r = requests.get(
            f"{API}/admin/dashboard/income-by-service-category"
            f"?start=2027-05-01&end=2027-05-31",
            headers={"Authorization": f"Bearer {tok_b}"}, timeout=15,
        ).json()
        assert r["total"] == 0, f"tenant leak: {r}"
    finally:
        _cleanup(tid_a, uid_a, email_a)
        _cleanup(tid_b, uid_b, email_b)


# 4. Uncategorized bucket
def test_income_by_service_category_uncategorized_bucket():
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin(tid)
    inv = _seed_invoice(tid, created_at="2027-06-15T12:00:00+00:00",
                          line_items=[
                              # No item_id → falls through to Uncategorized.
                              {"description": "misc", "quantity": 1,
                                "unit_price": 42.0},
                          ])
    try:
        r = requests.get(
            f"{API}/admin/dashboard/income-by-service-category"
            f"?start=2027-06-01&end=2027-06-30",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        ).json()
        assert r["items"][0]["category"] == "Uncategorized"
        assert r["items"][0]["amount"] == 42.0
        assert r["items"][0]["color"] == "#94A3B8"
    finally:
        _cleanup(tid, uid, email)


# 5. Empty range
def test_income_by_service_category_empty_range():
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        r = requests.get(
            f"{API}/admin/dashboard/income-by-service-category"
            f"?start=1999-01-01&end=1999-01-31",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        )
        assert r.status_code == 200
        b = r.json()
        assert b["items"] == []
        assert b["total"] == 0
    finally:
        _cleanup(tid, uid, email)
