"""
Iteration 30 — Invoices AR: One-tap 'Send reminder' endpoint.

Covers:
- POST /api/quotes/{id}/send-reminder (ADMIN only; 403 for technician & customer)
- Success path returns {ok, email_sent, reminder_count, last_reminder_at}
- SMS/email skipped without keys (email_sent=false) — in-app notification still delivered
- Guard rails: PAID invoice -> 400, invoice with no customer_id -> 400, unknown id -> 404
- In-app notification lands in db.notifications AND is visible to customer via GET /api/notifications
- GET /api/invoices/overview reflects reminder_count + last_reminder_at after send
- reminder_count increments on repeated calls
"""
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = (_ENV.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL", "")).rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL not set"
API = BASE_URL + "/api"

_BE_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE_ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE_ENV.get("DB_NAME") or os.environ.get("DB_NAME")

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}
CUST = {"email": "customer@aquaterra.com", "password": "password123"}

MARKER = "TEST_ITER30_REMINDER_MARKER"


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
def customer_ctx(mongo_db):
    """Fetch the linked customer for customer@aquaterra.com so we can verify notifications."""
    user = mongo_db.users.find_one({"email": CUST["email"]}, {"_id": 0})
    assert user, "customer user missing"
    cid = user.get("customer_id")
    assert cid, "customer user has no customer_id"
    return {"user_id": user["id"], "customer_id": cid}


@pytest.fixture
def outstanding_invoice(mongo_db, customer_ctx):
    """Create a fresh outstanding invoice for the seeded customer."""
    inv_id = f"test-iter30-outstanding-{datetime.now(timezone.utc).timestamp()}"
    doc = {
        "id": inv_id, "customer_id": customer_ctx["customer_id"], "customer_name": "TEST",
        "title": "TEST_ITER30 Outstanding Invoice", "doc_type": "invoice",
        "line_items": [{"description": "svc", "quantity": 1, "unit_price": 250.0}],
        "tax_rate": 0.0, "subtotal": 250.0, "tax": 0.0, "total": 250.0,
        "amount_paid": 0.0,
        "due_date": (datetime.now(timezone.utc).date() + timedelta(days=7)).isoformat(),
        "status": "sent", "payment_status": "unpaid",
        "notes": MARKER, "created_at": datetime.now(timezone.utc).isoformat(),
    }
    mongo_db.quotes.insert_one(dict(doc))
    yield doc
    mongo_db.quotes.delete_one({"id": inv_id})
    mongo_db.notifications.delete_many({"title": "Payment reminder", "customer_id": customer_ctx["customer_id"]})


@pytest.fixture
def paid_invoice(mongo_db, customer_ctx):
    inv_id = f"test-iter30-paid-{datetime.now(timezone.utc).timestamp()}"
    doc = {
        "id": inv_id, "customer_id": customer_ctx["customer_id"], "customer_name": "TEST",
        "title": "TEST_ITER30 Paid Invoice", "doc_type": "invoice",
        "line_items": [{"description": "svc", "quantity": 1, "unit_price": 100.0}],
        "tax_rate": 0.0, "subtotal": 100.0, "tax": 0.0, "total": 100.0,
        "amount_paid": 100.0,
        "due_date": (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat(),
        "status": "accepted", "payment_status": "paid",
        "notes": MARKER, "created_at": datetime.now(timezone.utc).isoformat(),
    }
    mongo_db.quotes.insert_one(dict(doc))
    yield doc
    mongo_db.quotes.delete_one({"id": inv_id})


@pytest.fixture
def no_customer_invoice(mongo_db):
    inv_id = f"test-iter30-nocust-{datetime.now(timezone.utc).timestamp()}"
    doc = {
        "id": inv_id, "customer_id": None, "customer_name": "",
        "title": "TEST_ITER30 No Customer Invoice", "doc_type": "invoice",
        "line_items": [{"description": "svc", "quantity": 1, "unit_price": 50.0}],
        "tax_rate": 0.0, "subtotal": 50.0, "tax": 0.0, "total": 50.0,
        "amount_paid": 0.0, "due_date": None,
        "status": "sent", "payment_status": "unpaid",
        "notes": MARKER, "created_at": datetime.now(timezone.utc).isoformat(),
    }
    mongo_db.quotes.insert_one(dict(doc))
    yield doc
    mongo_db.quotes.delete_one({"id": inv_id})


# -------------------- RBAC --------------------
class TestReminderRBAC:
    def test_technician_forbidden(self, tech_token, outstanding_invoice):
        r = requests.post(f"{API}/quotes/{outstanding_invoice['id']}/send-reminder",
                          headers=_h(tech_token), json={}, timeout=15)
        assert r.status_code == 403, r.text

    def test_customer_forbidden(self, customer_token, outstanding_invoice):
        r = requests.post(f"{API}/quotes/{outstanding_invoice['id']}/send-reminder",
                          headers=_h(customer_token), json={}, timeout=15)
        assert r.status_code == 403, r.text

    def test_unauthenticated_forbidden(self, outstanding_invoice):
        r = requests.post(f"{API}/quotes/{outstanding_invoice['id']}/send-reminder",
                          json={}, timeout=15)
        assert r.status_code in (401, 403)


# -------------------- Guard rails --------------------
class TestReminderGuardRails:
    def test_unknown_id_returns_404(self, admin_token):
        r = requests.post(f"{API}/quotes/does-not-exist-xyz-30/send-reminder",
                          headers=_h(admin_token), json={}, timeout=15)
        assert r.status_code == 404

    def test_paid_invoice_returns_400(self, admin_token, paid_invoice):
        r = requests.post(f"{API}/quotes/{paid_invoice['id']}/send-reminder",
                          headers=_h(admin_token), json={}, timeout=15)
        assert r.status_code == 400, r.text
        assert "paid" in r.text.lower()

    def test_no_customer_invoice_returns_400(self, admin_token, no_customer_invoice):
        r = requests.post(f"{API}/quotes/{no_customer_invoice['id']}/send-reminder",
                          headers=_h(admin_token), json={}, timeout=15)
        assert r.status_code == 400, r.text
        assert "customer" in r.text.lower()


# -------------------- Success path --------------------
class TestReminderSuccess:
    def test_success_response_shape(self, admin_token, outstanding_invoice):
        r = requests.post(f"{API}/quotes/{outstanding_invoice['id']}/send-reminder",
                          headers=_h(admin_token), json={}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        # Resend/Twilio not configured — email_sent must be False
        assert body.get("email_sent") is False
        assert body.get("reminder_count") == 1
        assert body.get("last_reminder_at") is not None

    def test_reminder_count_increments(self, admin_token, outstanding_invoice):
        # First send
        r1 = requests.post(f"{API}/quotes/{outstanding_invoice['id']}/send-reminder",
                           headers=_h(admin_token), json={}, timeout=15)
        assert r1.status_code == 200
        c1 = r1.json()["reminder_count"]
        # Second send
        r2 = requests.post(f"{API}/quotes/{outstanding_invoice['id']}/send-reminder",
                           headers=_h(admin_token), json={}, timeout=15)
        assert r2.status_code == 200
        c2 = r2.json()["reminder_count"]
        assert c2 == c1 + 1

    def test_notification_landed_in_db(self, admin_token, mongo_db, customer_ctx, outstanding_invoice):
        r = requests.post(f"{API}/quotes/{outstanding_invoice['id']}/send-reminder",
                          headers=_h(admin_token), json={}, timeout=15)
        assert r.status_code == 200
        # In-app notification must be created for the customer
        notif = mongo_db.notifications.find_one(
            {"customer_id": customer_ctx["customer_id"], "title": "Payment reminder"},
            sort=[("created_at", -1)],
        )
        assert notif is not None, "Payment reminder notification not created"
        # Body should mention outstanding balance ($250.00)
        assert "$250" in (notif.get("body") or ""), f"balance missing from body: {notif.get('body')}"
        assert notif.get("user_id") == customer_ctx["user_id"]
        assert notif.get("read") is False

    def test_notification_visible_via_customer_endpoint(self, admin_token, customer_token,
                                                        outstanding_invoice):
        r = requests.post(f"{API}/quotes/{outstanding_invoice['id']}/send-reminder",
                          headers=_h(admin_token), json={}, timeout=15)
        assert r.status_code == 200
        # Customer fetches their notifications
        n = requests.get(f"{API}/notifications", headers=_h(customer_token), timeout=15)
        assert n.status_code == 200, n.text
        items = n.json()
        assert any(x.get("title") == "Payment reminder" and "$250" in (x.get("body") or "")
                   for x in items), f"reminder notification not surfaced to customer: {items[:3]}"


# -------------------- Overview reflects reminder state --------------------
class TestOverviewShowsReminder:
    def test_overview_returns_reminder_fields(self, admin_token, outstanding_invoice):
        # Send one reminder
        r = requests.post(f"{API}/quotes/{outstanding_invoice['id']}/send-reminder",
                          headers=_h(admin_token), json={}, timeout=15)
        assert r.status_code == 200
        expected_count = r.json()["reminder_count"]

        ov = requests.get(f"{API}/invoices/overview", headers=_h(admin_token), timeout=15)
        assert ov.status_code == 200
        row = next((i for i in ov.json()["invoices"] if i["id"] == outstanding_invoice["id"]), None)
        assert row is not None, "seeded outstanding invoice not in overview"
        assert row.get("reminder_count") == expected_count
        assert row.get("last_reminder_at") is not None
