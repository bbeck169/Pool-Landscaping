"""Feb-2026 · Bulk-pay iteration 1 — Stripe path.

Contract tests for POST /api/payments/bulk-charge-on-file.

Design notes
------------
The endpoint delegates the actual charge to ``charge_invoice_on_file``
which hits Stripe's live API. To keep this suite safe (no real charges
against real cards) we ONLY seed data that lands in the pre-filter
buckets ``not_found`` / ``not_chargeable`` / ``no_card`` — never the
``succeeded`` bucket. That covers the routing logic exhaustively
without invoking Stripe.
"""
import os
import time
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE

_BE_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE_ENV.get("MONGO_URL") or os.environ.get("MONGO_URL", "")
DB_NAME = _BE_ENV.get("DB_NAME") or os.environ.get("DB_NAME", "")
assert MONGO_URL and DB_NAME

ADMIN = ("manager@aquaterra.com", "password123")
TECH = ("mike@aquaterra.com", "password123")
CUSTOMER = ("customer@aquaterra.com", "password123")


def _login(email, password):
    r = requests.post(f"{BASE}/api/auth/login",
                       json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["user"]


@pytest.fixture(scope="module")
def dbc():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture()
def admin_h():
    h, _ = _login(*ADMIN)
    return h


@pytest.fixture()
def tenant_id(dbc):
    t = dbc.tenants.find_one({"slug": "aquaterra"})
    assert t
    return t["id"]


def _seed_invoice(dbc, *, tenant_id, status="sent", payment_status="unpaid",
                    with_pm=False, customer_id=None, tag="BULKCHG"):
    """Seed a fresh invoice + optionally a customer with PM state.

    Returns (invoice_id, customer_id).
    """
    iid = f"test-bulk-{uuid.uuid4().hex[:12]}"
    cid = customer_id or f"test-cust-{uuid.uuid4().hex[:12]}"

    # Only create the customer row when we're seeding it fresh.
    if not customer_id:
        cust_doc = {
            "id": cid,
            "tenant_id": tenant_id,
            "name": f"{tag} customer {cid[:6]}",
            "email": f"{tag.lower()}-{cid[:6]}@example.test",
            "phone": "+15555550100",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        if with_pm:
            cust_doc["stripe_customer_id"] = f"cus_test_{cid[:12]}"
            cust_doc["default_payment_method_id"] = f"pm_test_{cid[:12]}"
            cust_doc["pm_brand"] = "Visa"
            cust_doc["pm_last4"] = "4242"
        dbc.customers.insert_one(cust_doc)

    inv_doc = {
        "id": iid,
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "title": f"{tag} inv {iid[-6:]}",
        "status": status,
        "payment_status": payment_status,
        "customer_id": cid,
        "customer_name": f"{tag} customer {cid[:6]}",
        "total": 150.00,
        "amount_paid": 0.0,
        "line_items": [{"description": "svc", "quantity": 1, "unit_price": 150.0}],
        "tax_rate": 0,
        "tax": 0,
        "subtotal": 150.0,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    dbc.quotes.insert_one(inv_doc)
    return iid, cid


def _cleanup(dbc, *, iids, cids):
    dbc.quotes.delete_many({"id": {"$in": iids}})
    dbc.customers.delete_many({"id": {"$in": cids}})


# ═══════════════════════════════════════════════════════════════════
# 1. Auth gate — non-admin roles get 403
# ═══════════════════════════════════════════════════════════════════
class TestAuth:
    def test_customer_gets_403(self):
        h, _ = _login(*CUSTOMER)
        r = requests.post(f"{BASE}/api/payments/bulk-charge-on-file",
                            headers=h, json={"invoice_ids": ["x"]}, timeout=15)
        assert r.status_code == 403, r.text

    def test_unauthenticated_gets_401_or_403(self):
        r = requests.post(f"{BASE}/api/payments/bulk-charge-on-file",
                            json={"invoice_ids": ["x"]}, timeout=15)
        assert r.status_code in (401, 403), r.text


# ═══════════════════════════════════════════════════════════════════
# 2. Empty invoice_ids → 400 with clear message
# ═══════════════════════════════════════════════════════════════════
class TestValidation:
    def test_empty_list_returns_400(self, admin_h):
        r = requests.post(f"{BASE}/api/payments/bulk-charge-on-file",
                            headers=admin_h, json={"invoice_ids": []}, timeout=15)
        assert r.status_code == 400, r.text
        assert "invoice_ids" in r.text.lower()

    def test_missing_key_returns_400(self, admin_h):
        r = requests.post(f"{BASE}/api/payments/bulk-charge-on-file",
                            headers=admin_h, json={}, timeout=15)
        assert r.status_code == 400, r.text

    def test_whitespace_only_ids_treated_as_empty(self, admin_h):
        r = requests.post(f"{BASE}/api/payments/bulk-charge-on-file",
                            headers=admin_h, json={"invoice_ids": ["", "  "]}, timeout=15)
        assert r.status_code == 400, r.text


# ═══════════════════════════════════════════════════════════════════
# 3. Mixed batch — no_card + not_chargeable(draft) + not_found
#     (skips the 'succeeded' bucket to avoid live Stripe charges)
# ═══════════════════════════════════════════════════════════════════
class TestMixedBatch:
    def test_mixed_batch_no_card_draft_not_found(self, admin_h, dbc, tenant_id):
        # Seed 3 invoices: one sent w/no PM (no_card), one draft w/no PM
        # (not_chargeable), plus one made-up id (not_found).
        i1, c1 = _seed_invoice(dbc, tenant_id=tenant_id, status="sent",
                                  payment_status="unpaid", with_pm=False,
                                  tag="BULKNOCARD")
        i2, c2 = _seed_invoice(dbc, tenant_id=tenant_id, status="draft",
                                  payment_status="unpaid", with_pm=False,
                                  tag="BULKDRAFT")
        fake = f"test-bulk-nonexistent-{uuid.uuid4().hex[:6]}"
        ids = [i1, i2, fake]

        try:
            r = requests.post(f"{BASE}/api/payments/bulk-charge-on-file",
                                headers=admin_h, json={"invoice_ids": ids},
                                timeout=20)
            assert r.status_code == 200, r.text
            body = r.json()
            assert "results" in body and "summary" in body
            assert len(body["results"]) == 3
            summary = body["summary"]
            assert summary["total"] == 3
            assert summary["no_card"] == 1
            assert summary["not_chargeable"] == 1
            assert summary["not_found"] == 1
            assert summary["succeeded"] == 0
            assert summary["failed"] == 0

            by_iid = {r["invoice_id"]: r for r in body["results"]}
            assert by_iid[i1]["status"] == "no_card"
            assert by_iid[i1]["customer_id"] == c1
            assert by_iid[i2]["status"] == "not_chargeable"
            assert by_iid[i2]["reason"].startswith("invoice_status_")
            assert by_iid[fake]["status"] == "not_found"
        finally:
            _cleanup(dbc, iids=[i1, i2], cids=[c1, c2])

    def test_paid_invoice_bucketed_as_not_chargeable(self, admin_h, dbc, tenant_id):
        # payment_status="paid" is the historical marker for a fully
        # paid invoice; must be filtered out before the charge attempt.
        i1, c1 = _seed_invoice(dbc, tenant_id=tenant_id, status="accepted",
                                  payment_status="paid", with_pm=True,
                                  tag="BULKPAID")
        try:
            r = requests.post(f"{BASE}/api/payments/bulk-charge-on-file",
                                headers=admin_h, json={"invoice_ids": [i1]}, timeout=20)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["summary"]["not_chargeable"] == 1
            assert body["summary"]["succeeded"] == 0
            assert body["results"][0]["status"] == "not_chargeable"
        finally:
            _cleanup(dbc, iids=[i1], cids=[c1])


# ═══════════════════════════════════════════════════════════════════
# 4. Cross-tenant safety — foreign tenant ids treated as not_found
# ═══════════════════════════════════════════════════════════════════
class TestTenantScope:
    def test_foreign_tenant_invoice_treated_as_not_found(self, admin_h, dbc):
        # Seed an invoice under a DIFFERENT tenant (sunbelt) with a real
        # PM configured — if scoping were broken this would look like a
        # legit charge candidate.
        sunbelt = dbc.tenants.find_one({"slug": "sunbelt"})
        assert sunbelt, "sunbelt tenant not present"
        i1, c1 = _seed_invoice(dbc, tenant_id=sunbelt["id"],
                                  status="sent", payment_status="unpaid",
                                  with_pm=True, tag="BULKSUNBELT")
        try:
            # Manager is on aquaterra; sunbelt invoice must not be
            # visible or chargeable.
            r = requests.post(f"{BASE}/api/payments/bulk-charge-on-file",
                                headers=admin_h, json={"invoice_ids": [i1]},
                                timeout=20)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["summary"]["not_found"] == 1
            assert body["summary"]["succeeded"] == 0
            assert body["results"][0]["status"] == "not_found"
        finally:
            _cleanup(dbc, iids=[i1], cids=[c1])


# ═══════════════════════════════════════════════════════════════════
# 5. Response shape sanity
# ═══════════════════════════════════════════════════════════════════
def test_response_envelope_keys(admin_h, dbc, tenant_id):
    i1, c1 = _seed_invoice(dbc, tenant_id=tenant_id, status="sent",
                              payment_status="unpaid", with_pm=False,
                              tag="BULKSHAPE")
    try:
        r = requests.post(f"{BASE}/api/payments/bulk-charge-on-file",
                            headers=admin_h, json={"invoice_ids": [i1]}, timeout=20)
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) >= {"results", "summary"}
        assert set(body["summary"].keys()) >= {
            "total", "succeeded", "processing", "no_card",
            "not_chargeable", "failed", "not_found", "requires_action",
        }
    finally:
        _cleanup(dbc, iids=[i1], cids=[c1])
