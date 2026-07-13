"""
Iteration 29 — Invoices (Accounts Receivable) & Partial Payments.

Covers:
- GET /api/invoices/overview (ADMIN only; 403 for technician & customer)
- Bucketing correctness: pending / past_due / partial / outstanding
- POST /api/quotes/{id}/record-payment (partial → 'partial', full → 'paid', edge cases)
- POST /api/quotes (invoice) defaults due_date to +14 days and amount_paid=0
- POST /api/quotes/{id}/pay (full manual pay) sets amount_paid=total
- Full payment removes invoice from /invoices/overview
"""
import os
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://pool-app-mobile.preview.emergentagent.com").rstrip("/")
API = BASE_URL + "/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}
CUST = {"email": "customer@aquaterra.com", "password": "password123"}

MARKER = "TEST_ITER29_AR_MARKER"


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    j = r.json()
    return j.get("access_token") or j.get("token")


def _h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def tech_token():
    return _login(TECH)


@pytest.fixture(scope="module")
def customer_token():
    return _login(CUST)


@pytest.fixture(scope="module")
def mongo_db():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


@pytest.fixture(scope="module")
def sample_customer_id(mongo_db):
    doc = mongo_db.customers.find_one({}, {"_id": 0, "id": 1})
    assert doc, "No seeded customer present"
    return doc["id"]


@pytest.fixture(scope="module")
def seeded_invoices(mongo_db, sample_customer_id):
    """Seed 3 invoices: pending (future due), past_due (past due), partial (paid > 0)."""
    today = datetime.now(timezone.utc).date()
    future = (today + timedelta(days=10)).isoformat()
    past = (today - timedelta(days=5)).isoformat()

    docs = [
        {
            "id": "test-iter29-pending", "customer_id": sample_customer_id, "customer_name": "TEST",
            "title": "TEST_ITER29 Pending Invoice", "doc_type": "invoice",
            "line_items": [{"description": "x", "quantity": 1, "unit_price": 100.0}],
            "tax_rate": 0.0, "subtotal": 100.0, "tax": 0.0, "total": 100.0,
            "amount_paid": 0.0, "due_date": future, "status": "sent", "payment_status": "unpaid",
            "notes": MARKER, "created_at": datetime.now(timezone.utc).isoformat(),
        },
        {
            "id": "test-iter29-pastdue", "customer_id": sample_customer_id, "customer_name": "TEST",
            "title": "TEST_ITER29 Past Due Invoice", "doc_type": "invoice",
            "line_items": [{"description": "x", "quantity": 1, "unit_price": 200.0}],
            "tax_rate": 0.0, "subtotal": 200.0, "tax": 0.0, "total": 200.0,
            "amount_paid": 0.0, "due_date": past, "status": "sent", "payment_status": "unpaid",
            "notes": MARKER, "created_at": datetime.now(timezone.utc).isoformat(),
        },
        {
            "id": "test-iter29-partial", "customer_id": sample_customer_id, "customer_name": "TEST",
            "title": "TEST_ITER29 Partial Invoice", "doc_type": "invoice",
            "line_items": [{"description": "x", "quantity": 1, "unit_price": 300.0}],
            "tax_rate": 0.0, "subtotal": 300.0, "tax": 0.0, "total": 300.0,
            "amount_paid": 100.0, "due_date": future, "status": "sent", "payment_status": "partial",
            "notes": MARKER, "created_at": datetime.now(timezone.utc).isoformat(),
        },
    ]
    mongo_db.quotes.insert_many([dict(d) for d in docs])
    yield {d["id"]: d for d in docs}
    # Cleanup any created invoices with our marker (including ones created via API in tests)
    mongo_db.quotes.delete_many({"notes": {"$regex": MARKER}})


# -------------------- RBAC on /invoices/overview --------------------
class TestOverviewRBAC:
    def test_admin_can_access(self, admin_token):
        r = requests.get(f"{API}/invoices/overview", headers=_h(admin_token), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "summary" in body and "invoices" in body
        s = body["summary"]
        for k in ("pending", "past_due", "partial", "outstanding"):
            assert k in s and "count" in s[k] and "amount" in s[k]

    def test_technician_forbidden(self, tech_token):
        r = requests.get(f"{API}/invoices/overview", headers=_h(tech_token), timeout=15)
        assert r.status_code == 403, r.text

    def test_customer_forbidden(self, customer_token):
        r = requests.get(f"{API}/invoices/overview", headers=_h(customer_token), timeout=15)
        assert r.status_code == 403, r.text

    def test_unauthenticated_forbidden(self):
        r = requests.get(f"{API}/invoices/overview", timeout=15)
        assert r.status_code in (401, 403)


# -------------------- Bucketing correctness --------------------
class TestBucketing:
    def test_pending_invoice_bucket(self, admin_token, seeded_invoices):
        r = requests.get(f"{API}/invoices/overview", headers=_h(admin_token), timeout=15)
        assert r.status_code == 200
        rows = {i["id"]: i for i in r.json()["invoices"]}
        assert "test-iter29-pending" in rows
        inv = rows["test-iter29-pending"]
        assert inv["pending"] is True
        assert inv["past_due"] is False
        assert inv["partial"] is False
        assert inv["balance"] == 100.0
        assert inv["total"] == 100.0
        assert inv["amount_paid"] == 0.0

    def test_past_due_invoice_bucket(self, admin_token, seeded_invoices):
        r = requests.get(f"{API}/invoices/overview", headers=_h(admin_token), timeout=15)
        rows = {i["id"]: i for i in r.json()["invoices"]}
        inv = rows["test-iter29-pastdue"]
        assert inv["past_due"] is True
        assert inv["pending"] is False
        assert inv["balance"] == 200.0

    def test_partial_invoice_bucket(self, admin_token, seeded_invoices):
        r = requests.get(f"{API}/invoices/overview", headers=_h(admin_token), timeout=15)
        rows = {i["id"]: i for i in r.json()["invoices"]}
        inv = rows["test-iter29-partial"]
        assert inv["partial"] is True
        assert inv["pending"] is False  # partial invoices should NOT be marked pending
        assert inv["balance"] == 200.0  # 300 - 100
        assert inv["amount_paid"] == 100.0

    def test_summary_includes_seeded(self, admin_token, seeded_invoices):
        r = requests.get(f"{API}/invoices/overview", headers=_h(admin_token), timeout=15)
        s = r.json()["summary"]
        # Our seeded rows must contribute at least these amounts
        assert s["outstanding"]["count"] >= 3
        assert s["outstanding"]["amount"] >= 500.0  # 100 + 200 + 200
        assert s["past_due"]["count"] >= 1
        assert s["partial"]["count"] >= 1
        assert s["pending"]["count"] >= 1


# -------------------- POST /quotes/{id}/record-payment --------------------
class TestRecordPayment:
    def test_technician_forbidden(self, tech_token, seeded_invoices):
        r = requests.post(f"{API}/quotes/test-iter29-pending/record-payment",
                          headers=_h(tech_token), json={"amount": 10}, timeout=15)
        assert r.status_code == 403

    def test_customer_forbidden(self, customer_token, seeded_invoices):
        r = requests.post(f"{API}/quotes/test-iter29-pending/record-payment",
                          headers=_h(customer_token), json={"amount": 10}, timeout=15)
        assert r.status_code == 403

    def test_amount_zero_returns_400(self, admin_token, seeded_invoices):
        r = requests.post(f"{API}/quotes/test-iter29-pending/record-payment",
                          headers=_h(admin_token), json={"amount": 0}, timeout=15)
        assert r.status_code == 400

    def test_negative_amount_returns_400(self, admin_token, seeded_invoices):
        r = requests.post(f"{API}/quotes/test-iter29-pending/record-payment",
                          headers=_h(admin_token), json={"amount": -5}, timeout=15)
        assert r.status_code == 400

    def test_unknown_id_returns_404(self, admin_token):
        r = requests.post(f"{API}/quotes/does-not-exist-xyz/record-payment",
                          headers=_h(admin_token), json={"amount": 10}, timeout=15)
        assert r.status_code == 404

    def test_partial_payment_updates_state(self, admin_token, mongo_db, sample_customer_id):
        # Fresh invoice for this test
        inv_id = "test-iter29-partial-flow"
        mongo_db.quotes.insert_one({
            "id": inv_id, "customer_id": sample_customer_id, "customer_name": "TEST",
            "title": "TEST_ITER29 partial flow", "doc_type": "invoice",
            "line_items": [{"description": "x", "quantity": 1, "unit_price": 500.0}],
            "tax_rate": 0.0, "subtotal": 500.0, "tax": 0.0, "total": 500.0,
            "amount_paid": 0.0, "due_date": (datetime.now(timezone.utc).date() + timedelta(days=7)).isoformat(),
            "status": "sent", "payment_status": "unpaid", "notes": MARKER,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        r = requests.post(f"{API}/quotes/{inv_id}/record-payment",
                          headers=_h(admin_token), json={"amount": 200}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["payment_status"] == "partial"
        assert body["amount_paid"] == 200.0

        # Verify in overview it is now bucketed as partial
        ov = requests.get(f"{API}/invoices/overview", headers=_h(admin_token), timeout=15).json()
        row = next((i for i in ov["invoices"] if i["id"] == inv_id), None)
        assert row is not None
        assert row["partial"] is True
        assert row["balance"] == 300.0

    def test_full_payment_marks_paid_and_removes_from_overview(self, admin_token, mongo_db, sample_customer_id):
        inv_id = "test-iter29-fullpay-flow"
        mongo_db.quotes.insert_one({
            "id": inv_id, "customer_id": sample_customer_id, "customer_name": "TEST",
            "title": "TEST_ITER29 fullpay", "doc_type": "invoice",
            "line_items": [{"description": "x", "quantity": 1, "unit_price": 400.0}],
            "tax_rate": 0.0, "subtotal": 400.0, "tax": 0.0, "total": 400.0,
            "amount_paid": 100.0, "due_date": (datetime.now(timezone.utc).date() + timedelta(days=7)).isoformat(),
            "status": "sent", "payment_status": "partial", "notes": MARKER,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        # Pay remaining balance
        r = requests.post(f"{API}/quotes/{inv_id}/record-payment",
                          headers=_h(admin_token), json={"amount": 300}, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body["payment_status"] == "paid"
        assert body["status"] == "accepted"
        assert body["amount_paid"] == 400.0

        # Should disappear from overview
        ov = requests.get(f"{API}/invoices/overview", headers=_h(admin_token), timeout=15).json()
        assert not any(i["id"] == inv_id for i in ov["invoices"])

    def test_overpayment_caps_at_total(self, admin_token, mongo_db, sample_customer_id):
        inv_id = "test-iter29-overpay-flow"
        mongo_db.quotes.insert_one({
            "id": inv_id, "customer_id": sample_customer_id, "customer_name": "TEST",
            "title": "TEST_ITER29 overpay", "doc_type": "invoice",
            "line_items": [{"description": "x", "quantity": 1, "unit_price": 150.0}],
            "tax_rate": 0.0, "subtotal": 150.0, "tax": 0.0, "total": 150.0,
            "amount_paid": 0.0, "due_date": None,
            "status": "sent", "payment_status": "unpaid", "notes": MARKER,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        r = requests.post(f"{API}/quotes/{inv_id}/record-payment",
                          headers=_h(admin_token), json={"amount": 500}, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body["payment_status"] == "paid"
        assert body["amount_paid"] == 150.0  # capped at total


# -------------------- POST /quotes (invoice) defaults --------------------
class TestInvoiceCreationDefaults:
    def test_invoice_defaults_due_date_and_amount_paid(self, admin_token, sample_customer_id, mongo_db):
        payload = {
            "customer_id": sample_customer_id,
            "title": "TEST_ITER29 create-invoice-defaults",
            "doc_type": "invoice",
            "line_items": [{"description": "svc", "quantity": 1, "unit_price": 250.0}],
            "tax_rate": 0.0,
            "notes": MARKER,
        }
        r = requests.post(f"{API}/quotes", headers=_h(admin_token), json=payload, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["doc_type"] == "invoice"
        assert body["amount_paid"] == 0.0
        assert body["due_date"] is not None
        # Should be roughly +14 days from today
        expected = (datetime.now(timezone.utc).date() + timedelta(days=14)).isoformat()
        assert body["due_date"] == expected
        # Cleanup handled by fixture

    def test_invoice_respects_explicit_due_date(self, admin_token, sample_customer_id):
        explicit = (datetime.now(timezone.utc).date() + timedelta(days=30)).isoformat()
        payload = {
            "customer_id": sample_customer_id,
            "title": "TEST_ITER29 explicit-due",
            "doc_type": "invoice",
            "line_items": [{"description": "svc", "quantity": 1, "unit_price": 50.0}],
            "tax_rate": 0.0,
            "due_date": explicit,
            "notes": MARKER,
        }
        r = requests.post(f"{API}/quotes", headers=_h(admin_token), json=payload, timeout=15)
        assert r.status_code == 200
        assert r.json()["due_date"] == explicit


# -------------------- POST /quotes/{id}/pay (full manual) --------------------
class TestFullManualPay:
    def test_pay_endpoint_sets_amount_paid_to_total(self, admin_token, mongo_db, sample_customer_id):
        inv_id = "test-iter29-manualpay"
        mongo_db.quotes.insert_one({
            "id": inv_id, "customer_id": sample_customer_id, "customer_name": "TEST",
            "title": "TEST_ITER29 manual pay", "doc_type": "invoice",
            "line_items": [{"description": "x", "quantity": 1, "unit_price": 175.0}],
            "tax_rate": 0.0, "subtotal": 175.0, "tax": 0.0, "total": 175.0,
            "amount_paid": 0.0, "due_date": None,
            "status": "sent", "payment_status": "unpaid", "notes": MARKER,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        r = requests.post(f"{API}/quotes/{inv_id}/pay", headers=_h(admin_token), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["payment_status"] == "paid"
        assert body["status"] == "accepted"
        assert body["amount_paid"] == 175.0
