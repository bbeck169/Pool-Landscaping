"""Iteration 31 — Card/ACH on file: setup-session, method, request-method, charge-on-file.

Covers: /api/payments/setup-session, /api/payments/method,
/api/payments/request-method/{cid}, /api/payments/charge-on-file/{qid},
and /api/invoices/overview enrichment (has_payment_method/pm_label/processing).
"""
import os
import time
import uuid
import pytest
import requests

# Configure Stripe SDK for happy-path attach flow
import stripe as _stripe
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
_stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

# Direct Mongo for setup/cleanup + verification
from pymongo import MongoClient
_mc = MongoClient(os.environ["MONGO_URL"])
_db = _mc[os.environ["DB_NAME"]]

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")


def _login(email, password="password123"):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def tech_tok():
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def customer_tok():
    return _login("customer@aquaterra.com")


@pytest.fixture(scope="module")
def customer_id():
    u = _db.users.find_one({"email": "customer@aquaterra.com"})
    assert u and u.get("customer_id")
    return u["customer_id"]


# ---------- setup-session (customer for self, admin with cid, 403 tech) ----------
class TestSetupSession:
    def test_customer_self(self, customer_tok):
        r = requests.post(f"{BASE_URL}/api/payments/setup-session",
                          headers=_hdr(customer_tok),
                          json={"return_url": "https://example.com/portal/payment-method"},
                          timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["url"].startswith("https://checkout.stripe.com"), data
        assert data.get("session_id", "").startswith("cs_")

    def test_admin_needs_customer_id(self, admin_tok):
        r = requests.post(f"{BASE_URL}/api/payments/setup-session",
                          headers=_hdr(admin_tok),
                          json={"return_url": "https://example.com/x"}, timeout=30)
        assert r.status_code == 400

    def test_admin_with_cid(self, admin_tok, customer_id):
        r = requests.post(f"{BASE_URL}/api/payments/setup-session",
                          headers=_hdr(admin_tok),
                          json={"return_url": "https://example.com/x", "customer_id": customer_id},
                          timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["url"].startswith("https://checkout.stripe.com")

    def test_tech_forbidden(self, tech_tok):
        r = requests.post(f"{BASE_URL}/api/payments/setup-session",
                          headers=_hdr(tech_tok),
                          json={"return_url": "https://example.com/x"}, timeout=30)
        assert r.status_code == 403


# ---------- /payments/method (customer only) ----------
class TestMethod:
    def test_customer_no_method(self, customer_tok, customer_id):
        # Ensure clean state
        _db.customers.update_one({"id": customer_id},
                                 {"$unset": {"default_payment_method_id": "", "pm_brand": "",
                                             "pm_last4": "", "pm_type": ""}})
        r = requests.get(f"{BASE_URL}/api/payments/method", headers=_hdr(customer_tok), timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert data["has_method"] is False
        assert data["label"] == ""

    def test_admin_forbidden(self, admin_tok):
        r = requests.get(f"{BASE_URL}/api/payments/method", headers=_hdr(admin_tok), timeout=30)
        assert r.status_code == 403

    def test_tech_forbidden(self, tech_tok):
        r = requests.get(f"{BASE_URL}/api/payments/method", headers=_hdr(tech_tok), timeout=30)
        assert r.status_code == 403


# ---------- /payments/request-method/{cid} ----------
class TestRequestMethod:
    def test_admin_creates_notification(self, admin_tok, customer_id):
        # clean notifs for that customer
        _db.notifications.delete_many({"customer_id": customer_id, "title": "Payment method required"})
        r = requests.post(f"{BASE_URL}/api/payments/request-method/{customer_id}",
                          headers=_hdr(admin_tok), timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True
        assert _db.notifications.count_documents(
            {"customer_id": customer_id, "title": "Payment method required"}) >= 1
        _db.notifications.delete_many({"customer_id": customer_id, "title": "Payment method required"})

    def test_unknown_customer_404(self, admin_tok):
        r = requests.post(f"{BASE_URL}/api/payments/request-method/does-not-exist",
                          headers=_hdr(admin_tok), timeout=30)
        assert r.status_code == 404

    def test_customer_forbidden(self, customer_tok, customer_id):
        r = requests.post(f"{BASE_URL}/api/payments/request-method/{customer_id}",
                          headers=_hdr(customer_tok), timeout=30)
        assert r.status_code == 403

    def test_tech_forbidden(self, tech_tok, customer_id):
        r = requests.post(f"{BASE_URL}/api/payments/request-method/{customer_id}",
                          headers=_hdr(tech_tok), timeout=30)
        assert r.status_code == 403


# ---------- /payments/charge-on-file/{qid} guard rails ----------
class TestChargeGuards:
    def test_unknown_invoice_404(self, admin_tok):
        r = requests.post(f"{BASE_URL}/api/payments/charge-on-file/nope-{uuid.uuid4()}",
                          headers=_hdr(admin_tok), timeout=30)
        assert r.status_code == 404

    def test_no_method_400(self, admin_tok, customer_id):
        # ensure customer has NO stripe method
        _db.customers.update_one({"id": customer_id}, {"$unset": {
            "default_payment_method_id": "", "pm_brand": "", "pm_last4": "", "pm_type": "",
            "stripe_customer_id": ""}})
        inv_id = f"test-iter31-nomethod-{uuid.uuid4().hex[:8]}"
        _db.quotes.insert_one({
            "id": inv_id, "doc_type": "invoice", "customer_id": customer_id,
            "customer_name": "Jennifer Carson", "title": "TEST_ITER31 no-method",
            "line_items": [], "tax_rate": 0.0, "total": 100.0, "amount_paid": 0.0,
            "status": "sent", "payment_status": "unpaid",
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        try:
            r = requests.post(f"{BASE_URL}/api/payments/charge-on-file/{inv_id}",
                              headers=_hdr(admin_tok), timeout=30)
            assert r.status_code == 400
            assert "No card or bank" in r.text
        finally:
            _db.quotes.delete_one({"id": inv_id})

    def test_paid_400(self, admin_tok, customer_id):
        inv_id = f"test-iter31-paid-{uuid.uuid4().hex[:8]}"
        _db.quotes.insert_one({
            "id": inv_id, "doc_type": "invoice", "customer_id": customer_id,
            "customer_name": "Jennifer Carson", "title": "TEST_ITER31 paid",
            "line_items": [], "tax_rate": 0.0, "total": 50.0, "amount_paid": 50.0,
            "status": "accepted", "payment_status": "paid",
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        try:
            r = requests.post(f"{BASE_URL}/api/payments/charge-on-file/{inv_id}",
                              headers=_hdr(admin_tok), timeout=30)
            assert r.status_code == 400
            assert "already paid" in r.text.lower()
        finally:
            _db.quotes.delete_one({"id": inv_id})

    def test_tech_forbidden(self, tech_tok):
        r = requests.post(f"{BASE_URL}/api/payments/charge-on-file/anything",
                          headers=_hdr(tech_tok), timeout=30)
        assert r.status_code == 403

    def test_customer_forbidden(self, customer_tok):
        r = requests.post(f"{BASE_URL}/api/payments/charge-on-file/anything",
                          headers=_hdr(customer_tok), timeout=30)
        assert r.status_code == 403


# ---------- /invoices/overview enrichment ----------
class TestOverviewEnrichment:
    def test_fields_present(self, admin_tok):
        r = requests.get(f"{BASE_URL}/api/invoices/overview", headers=_hdr(admin_tok), timeout=30)
        assert r.status_code == 200
        rows = r.json().get("invoices", [])
        assert isinstance(rows, list)
        if rows:
            row = rows[0]
            for k in ("has_payment_method", "pm_label", "processing"):
                assert k in row, f"missing key {k} in overview row"


# ---------- Off-session happy path (attach pm_card_visa) ----------
class TestChargeHappyPath:
    def test_charge_succeeds_and_resets(self, admin_tok, customer_id):
        # Fetch or create Stripe customer for this app customer
        cust = _db.customers.find_one({"id": customer_id})
        assert cust
        scid = cust.get("stripe_customer_id")
        if not scid:
            sc = _stripe.Customer.create(name=cust.get("name") or "Test",
                                         email=cust.get("email") or None,
                                         metadata={"customer_id": customer_id})
            scid = sc.id

        # Attach test PM
        pm = _stripe.PaymentMethod.attach("pm_card_visa", customer=scid)
        _stripe.Customer.modify(scid, invoice_settings={"default_payment_method": pm.id})

        _db.customers.update_one({"id": customer_id}, {"$set": {
            "stripe_customer_id": scid,
            "default_payment_method_id": pm.id,
            "pm_brand": "Visa", "pm_last4": "4242", "pm_type": "card",
        }})

        # Pick an outstanding invoice for this customer, or create one
        inv = _db.quotes.find_one({"doc_type": "invoice", "customer_id": customer_id,
                                   "payment_status": "unpaid", "total": {"$gt": 0}})
        created = False
        if not inv:
            inv_id = f"test-iter31-charge-{uuid.uuid4().hex[:8]}"
            _db.quotes.insert_one({
                "id": inv_id, "doc_type": "invoice", "customer_id": customer_id,
                "customer_name": cust.get("name", "Jennifer Carson"),
                "title": "TEST_ITER31 charge happy",
                "line_items": [], "tax_rate": 0.0, "total": 25.0, "amount_paid": 0.0,
                "status": "sent", "payment_status": "unpaid",
                "created_at": "2026-01-01T00:00:00+00:00", "due_date": "2026-01-15",
            })
            inv = _db.quotes.find_one({"id": inv_id})
            created = True

        inv_id = inv["id"]
        orig_total = float(inv["total"])
        orig_status = inv.get("payment_status", "unpaid")
        orig_gstatus = inv.get("status", "sent")
        orig_paid = float(inv.get("amount_paid") or 0)

        try:
            # Overview should now indicate has_payment_method for this row
            ov = requests.get(f"{BASE_URL}/api/invoices/overview",
                              headers=_hdr(admin_tok), timeout=30).json()
            row = next((x for x in ov.get("invoices", []) if x["id"] == inv_id), None)
            assert row and row["has_payment_method"] is True
            assert row["pm_label"].startswith("Visa")

            r = requests.post(f"{BASE_URL}/api/payments/charge-on-file/{inv_id}",
                              headers=_hdr(admin_tok), timeout=60)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["status"] == "succeeded", body

            # Verify invoice is now paid
            time.sleep(0.5)
            updated = _db.quotes.find_one({"id": inv_id})
            assert updated["payment_status"] == "paid"
            assert float(updated["amount_paid"]) == orig_total
            assert updated.get("paid_at")

            # Row should DROP OFF /invoices/overview
            ov2 = requests.get(f"{BASE_URL}/api/invoices/overview",
                               headers=_hdr(admin_tok), timeout=30).json()
            assert not any(x["id"] == inv_id for x in ov2.get("invoices", []))
        finally:
            # RESET invoice to original state (or delete if we created it)
            if created:
                _db.quotes.delete_one({"id": inv_id})
            else:
                _db.quotes.update_one({"id": inv_id}, {
                    "$set": {
                        "payment_status": orig_status,
                        "status": orig_gstatus,
                        "amount_paid": orig_paid,
                    },
                    "$unset": {"paid_at": "", "payment_method": "", "payment_intent_id": ""},
                })
            # Clean saved method
            _db.customers.update_one({"id": customer_id}, {"$unset": {
                "stripe_customer_id": "", "default_payment_method_id": "",
                "pm_brand": "", "pm_last4": "", "pm_type": "",
            }})
            # Remove any Payment received / method required notifications generated
            _db.notifications.delete_many({"customer_id": customer_id,
                                           "title": {"$in": ["Payment received",
                                                              "Payment method required"]}})
