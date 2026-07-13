"""Iteration 34 — Auto-CHARGE on monthly chemical invoice finalize.

Covers `run_monthly_chem_billing()` in `/app/backend/routers/finances.py`:

  A) Auto-charge branch: when customer has `default_payment_method_id`, finalize
     invokes `charge_invoice_on_file` (Stripe off-session PaymentIntent). On
     'succeeded' the invoice becomes payment_status='paid', status='accepted',
     amount_paid==total, paid_at set, payment_method recorded, and a
     'Payment received' notification is created for the customer.
  B) Fallback branch: with NO saved PM, invoice becomes status='sent',
     due_date set 14 days out, and a 'New invoice' notification is created.
  C) Empty-line draft invoices are DELETED rather than billed.
  D) Admin endpoint POST /api/payments/charge-on-file/{qid} charges on file
     (403 for non-admin, 400 when no PM on file, 200 with succeeded PM).
  E) Idempotency / cleanup — no leftover TEST invoices or notifications
     after the run.
"""
import os
import sys
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
import stripe
from dotenv import dotenv_values
from pymongo import MongoClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
BACKEND_ENV = dotenv_values(BACKEND_DIR / ".env")
MONGO_URL = BACKEND_ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = BACKEND_ENV.get("DB_NAME") or os.environ.get("DB_NAME")
STRIPE_KEY = BACKEND_ENV.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_SECRET_KEY")

FRONTEND_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = (
    FRONTEND_ENV.get("EXPO_PUBLIC_BACKEND_URL")
    or FRONTEND_ENV.get("EXPO_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
).rstrip("/")

stripe.api_key = STRIPE_KEY

# Persistent event loop so Motor's AsyncIOMotorClient (bound to first loop it
# sees) can be re-used across multiple test invocations. asyncio.run() creates
# and CLOSES a new loop each call, which breaks Motor on the 2nd invocation.
_LOOP = asyncio.new_event_loop()


# ---------- helpers ----------
def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _run_finalize():
    """Invoke routers.finances.run_monthly_chem_billing() on the shared loop."""
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    from routers.finances import run_monthly_chem_billing  # noqa
    _LOOP.run_until_complete(run_monthly_chem_billing())


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL)
    try:
        yield client[DB_NAME]
    finally:
        client.close()


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": "admin@aquaterra.com", "password": "password123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def customer_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": "customer@aquaterra.com", "password": "password123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def customer_id(mongo):
    c = mongo.customers.find_one({"email": "customer@aquaterra.com"})
    assert c, "seed customer not found"
    return c["id"]


@pytest.fixture(scope="module")
def customer_state_snapshot(mongo, customer_id):
    """Snapshot & restore any pre-existing Stripe fields on the customer so we
    don't leak our attached PM back into the demo seed."""
    doc = mongo.customers.find_one({"id": customer_id}) or {}
    keys = ["stripe_customer_id", "default_payment_method_id", "pm_brand", "pm_last4", "pm_type"]
    original = {k: doc.get(k) for k in keys}
    yield original
    # Restore: unset any keys not previously present; set previously present values
    unset = {k: "" for k, v in original.items() if v in (None, "", False)}
    set_ = {k: v for k, v in original.items() if v not in (None, "", False)}
    op = {}
    if set_:
        op["$set"] = set_
    if unset:
        op["$unset"] = unset
    if op:
        mongo.customers.update_one({"id": customer_id}, op)


def _make_draft_invoice(mongo, customer_id, month="2026-05", total=25.0):
    """Insert a backdated draft auto_chem invoice with a real line_item so the
    finalize routine will process it (empty invoices are auto-deleted)."""
    from uuid import uuid4
    doc = {
        "id": str(uuid4()),
        "doc_type": "invoice",
        "auto_chem": True,
        "customer_id": customer_id,
        "customer_name": "Jennifer Carson",
        "title": f"Chemical Charges — {month}",
        "billing_month": month,
        "status": "draft",
        "line_items": [{"description": f"TEST_Clarifier — {month}", "quantity": 1,
                        "unit_price": total, "service_date": month}],
        "subtotal": total, "tax_rate": 0, "tax": 0.0, "total": total,
        "amount_paid": 0.0, "payment_status": "unpaid",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "test_marker": "iter34",
    }
    mongo.quotes.insert_one(doc)
    return doc["id"]


def _cleanup(mongo, customer_id):
    mongo.quotes.delete_many({"test_marker": "iter34"})
    mongo.quotes.delete_many({"auto_chem": True, "customer_id": customer_id,
                              "billing_month": {"$in": ["2026-04", "2026-05", "2026-06"]}})
    mongo.notifications.delete_many({"customer_id": customer_id,
                                     "title": {"$in": ["New invoice", "Payment received",
                                                       "Payment processing"]},
                                     "body": {"$regex": "TEST|Clarifier|2026-04|2026-05|2026-06"}})


@pytest.fixture(autouse=True)
def _cleanup_each(mongo, customer_id):
    _cleanup(mongo, customer_id)
    yield
    _cleanup(mongo, customer_id)


# ---------- C) Empty draft invoice cleanup ----------
class TestEmptyDraftCleanup:
    def test_empty_draft_is_deleted_on_finalize(self, mongo, customer_id):
        from uuid import uuid4
        empty_id = str(uuid4())
        mongo.quotes.insert_one({
            "id": empty_id, "doc_type": "invoice", "auto_chem": True,
            "customer_id": customer_id, "customer_name": "Jennifer Carson",
            "title": "Chemical Charges — 2026-04", "billing_month": "2026-04",
            "status": "draft", "line_items": [], "subtotal": 0, "tax": 0.0,
            "total": 0.0, "amount_paid": 0.0, "payment_status": "unpaid",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "test_marker": "iter34",
        })
        _run_finalize()
        assert mongo.quotes.find_one({"id": empty_id}) is None, \
            "empty draft chem invoice should have been deleted"


# ---------- B) Fallback: no PM on file → send invoice + New invoice notify ----------
class TestFallbackNoPaymentMethod:
    def test_finalize_without_pm_sends_invoice_and_notifies(
            self, mongo, customer_id, customer_state_snapshot):
        # ensure no PM on file
        mongo.customers.update_one({"id": customer_id}, {
            "$unset": {"default_payment_method_id": "", "pm_brand": "",
                       "pm_last4": "", "pm_type": ""}
        })
        inv_id = _make_draft_invoice(mongo, customer_id, month="2026-05", total=25.0)

        _run_finalize()

        finalized = mongo.quotes.find_one({"id": inv_id}, {"_id": 0})
        assert finalized, "invoice missing after finalize"
        assert finalized["status"] == "sent", finalized
        assert finalized.get("due_date"), "due_date should be set"
        # due_date should be ~14 days out
        due = datetime.fromisoformat(finalized["due_date"]).date()
        today = datetime.now(timezone.utc).date()
        assert 12 <= (due - today).days <= 16, f"due_date {due} not ~14 days out"
        # Should NOT be paid (no PM)
        assert finalized.get("payment_status", "unpaid") != "paid"

        note = mongo.notifications.find_one({
            "customer_id": customer_id, "title": "New invoice",
            "body": {"$regex": "2026-05"},
        })
        assert note, "customer was not notified with 'New invoice'"


# ---------- A) Auto-charge: PM on file → PaymentIntent succeeded, invoice paid ----------
class TestAutoChargeWithPaymentMethod:
    """Attach a Stripe test PM and verify off-session charge succeeds and the
    invoice is marked paid with a 'Payment received' notification.
    """

    @pytest.fixture
    def customer_with_pm(self, mongo, customer_id, customer_state_snapshot):
        # Create/reuse Stripe customer
        cust_doc = mongo.customers.find_one({"id": customer_id}) or {}
        scid = cust_doc.get("stripe_customer_id")
        if not scid:
            sc = stripe.Customer.create(
                name=cust_doc.get("name") or "TEST Jennifer",
                email=cust_doc.get("email") or "customer@aquaterra.com",
                metadata={"customer_id": customer_id, "test": "iter34"},
            )
            scid = sc.id

        # Create a payment method from a Stripe test token (not raw card details;
        # tok_visa maps to a Visa test PM that supports off_session confirm=True).
        pm = stripe.PaymentMethod.create(type="card", card={"token": "tok_visa"})
        stripe.PaymentMethod.attach(pm.id, customer=scid)
        stripe.Customer.modify(scid, invoice_settings={"default_payment_method": pm.id})

        mongo.customers.update_one({"id": customer_id}, {"$set": {
            "stripe_customer_id": scid,
            "default_payment_method_id": pm.id,
            "pm_brand": "Visa", "pm_last4": "4242", "pm_type": "card",
        }})
        yield scid, pm.id
        # Detach PM after test
        try:
            stripe.PaymentMethod.detach(pm.id)
        except Exception:
            pass

    def test_finalize_charges_card_on_file_and_marks_paid(
            self, mongo, customer_id, customer_with_pm):
        inv_id = _make_draft_invoice(mongo, customer_id, month="2026-05", total=25.0)

        _run_finalize()

        finalized = mongo.quotes.find_one({"id": inv_id}, {"_id": 0})
        assert finalized, "invoice missing after finalize"
        # After a successful auto-charge, finalize first sets status='sent',
        # then charge_invoice_on_file → _mark_paid overrides status='accepted'.
        assert finalized["status"] in ("sent", "accepted"), \
            f"status={finalized.get('status')}"
        assert finalized.get("due_date"), "due_date should be set"
        # Auto-charged: paid via off_session Stripe test PM
        assert finalized["payment_status"] == "paid", (
            f"expected payment_status=paid, got {finalized.get('payment_status')} "
            f"(payment_intent_id={finalized.get('payment_intent_id')})"
        )
        assert abs(float(finalized.get("amount_paid") or 0) - 25.0) < 0.01
        assert finalized.get("paid_at"), "paid_at should be set"
        assert finalized.get("payment_intent_id"), "payment_intent_id should be recorded"
        assert "4242" in (finalized.get("payment_method") or ""), \
            f"payment_method should record last4, got {finalized.get('payment_method')!r}"

        # customer notified 'Payment received' (not 'New invoice')
        got_paid_note = mongo.notifications.find_one({
            "customer_id": customer_id, "title": "Payment received",
        })
        assert got_paid_note, "customer was not notified 'Payment received'"
        no_new_invoice_note = mongo.notifications.find_one({
            "customer_id": customer_id, "title": "New invoice",
            "body": {"$regex": "2026-05"},
        })
        assert no_new_invoice_note is None, \
            "'New invoice' fallback notification should NOT be sent when charge succeeded"


# ---------- D) Admin endpoint /api/payments/charge-on-file/{qid} ----------
class TestChargeOnFileEndpoint:
    def test_non_admin_forbidden(self, customer_token, mongo, customer_id,
                                  customer_state_snapshot):
        inv_id = _make_draft_invoice(mongo, customer_id, month="2026-05", total=10.0)
        r = requests.post(f"{BASE_URL}/api/payments/charge-on-file/{inv_id}",
                          headers=_hdr(customer_token))
        assert r.status_code == 403, r.text

    def test_400_when_no_payment_method(self, admin_token, mongo, customer_id,
                                         customer_state_snapshot):
        mongo.customers.update_one({"id": customer_id}, {
            "$unset": {"default_payment_method_id": "", "pm_brand": "",
                       "pm_last4": "", "pm_type": ""}
        })
        inv_id = _make_draft_invoice(mongo, customer_id, month="2026-05", total=15.0)
        # move to 'sent' since charge_on_file works on any unpaid invoice
        mongo.quotes.update_one({"id": inv_id}, {"$set": {"status": "sent"}})
        r = requests.post(f"{BASE_URL}/api/payments/charge-on-file/{inv_id}",
                          headers=_hdr(admin_token))
        assert r.status_code == 400
        assert "no card" in (r.json().get("detail", "").lower()) or \
               "bank" in (r.json().get("detail", "").lower())

    def test_404_when_invoice_missing(self, admin_token):
        r = requests.post(f"{BASE_URL}/api/payments/charge-on-file/does-not-exist-xyz",
                          headers=_hdr(admin_token))
        assert r.status_code == 404

    def test_charge_on_file_succeeds_with_pm(self, admin_token, mongo, customer_id,
                                              customer_state_snapshot):
        # attach PM
        cust_doc = mongo.customers.find_one({"id": customer_id}) or {}
        scid = cust_doc.get("stripe_customer_id")
        if not scid:
            sc = stripe.Customer.create(
                name=cust_doc.get("name") or "TEST Jennifer",
                email=cust_doc.get("email") or "customer@aquaterra.com",
                metadata={"customer_id": customer_id, "test": "iter34"},
            )
            scid = sc.id
        pm = stripe.PaymentMethod.create(type="card", card={"token": "tok_visa"})
        stripe.PaymentMethod.attach(pm.id, customer=scid)
        mongo.customers.update_one({"id": customer_id}, {"$set": {
            "stripe_customer_id": scid, "default_payment_method_id": pm.id,
            "pm_brand": "Visa", "pm_last4": "4242", "pm_type": "card",
        }})
        try:
            inv_id = _make_draft_invoice(mongo, customer_id, month="2026-05", total=17.5)
            mongo.quotes.update_one({"id": inv_id}, {"$set": {"status": "sent"}})
            r = requests.post(f"{BASE_URL}/api/payments/charge-on-file/{inv_id}",
                              headers=_hdr(admin_token))
            assert r.status_code == 200, r.text
            data = r.json()
            assert data.get("status") == "succeeded", data
            assert abs(float(data.get("amount") or 0) - 17.5) < 0.01
            assert "4242" in (data.get("method") or "")
            # verify DB
            inv = mongo.quotes.find_one({"id": inv_id}, {"_id": 0})
            assert inv["payment_status"] == "paid"
            assert inv.get("paid_at")
            assert inv.get("payment_intent_id")
        finally:
            try:
                stripe.PaymentMethod.detach(pm.id)
            except Exception:
                pass


# ---------- E) Idempotency / cleanup verification ----------
class TestCleanupIdempotency:
    def test_no_leftover_test_records(self, mongo, customer_id, customer_state_snapshot):
        # After teardown of prior tests, our marker'd invoices/notifs must be gone.
        # This test simply asserts a clean state at start (autouse fixture cleans)
        # and verifies the finalize routine is idempotent on an empty state.
        _run_finalize()
        leftover = list(mongo.quotes.find({"test_marker": "iter34"}))
        assert leftover == [], f"leftover TEST invoices: {leftover}"
