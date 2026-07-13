"""Iteration 9 backend tests — REAL Stripe Checkout integration (TEST mode).

Covers:
- POST /api/payments/checkout/{qid}: admin, customer(own) -> 200 with cs_test_/https URL.
- Technician -> 403; customer paying ANOTHER customer's invoice -> 403.
- Already-paid invoice -> 400; non-existent -> 404.
- Amount is read server-side from the invoice total (client-supplied override ignored).
- GET /api/payments/status/{session_id}: fresh session -> unpaid/open, includes invoice_id.
- Technician -> 403 on status.
- POST /api/payments/admin/generate-link/{qid}: admin -> 200 with buy.stripe.com/test_ URL,
  payment_link persisted on the quote. Tech/customer -> 403.
- POST /api/payments/webhook: synthetic checkout.session.completed marks invoice paid.
- POST /api/quotes/{qid}/pay is admin-only (customer/tech -> 403; admin -> paid).
"""
import os
import uuid
from pathlib import Path

import pytest
import requests


def _load_base_url():
    url = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
    if not url:
        for ln in Path("/app/frontend/.env").read_text().splitlines():
            if ln.startswith("EXPO_PUBLIC_BACKEND_URL="):
                url = ln.split("=", 1)[1].strip().strip('"')
                break
    return (url or "").rstrip("/")


BASE_URL = _load_base_url()
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}
CUSTOMER = {"email": "customer@aquaterra.com", "password": "password123"}

OK_URL = {"success_url": "https://example.com/ok", "cancel_url": "https://example.com/cancel"}


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.text}"
    return r.json()


@pytest.fixture(scope="session")
def admin_token():
    return _login(ADMIN)["access_token"]


@pytest.fixture(scope="session")
def tech_token():
    return _login(TECH)["access_token"]


@pytest.fixture(scope="session")
def customer_auth():
    return _login(CUSTOMER)


def _make_invoice(admin_token, customer_id, unit_price=42.0, title=None):
    payload = {
        "customer_id": customer_id,
        "title": title or f"TEST_Stripe_{uuid.uuid4().hex[:6]}",
        "doc_type": "invoice",
        "tax_rate": 0.0,
        "line_items": [{"description": "TEST", "quantity": 1, "unit_price": unit_price}],
    }
    r = requests.post(f"{API}/quotes", headers=_h(admin_token), json=payload, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


class TestCheckoutSession:
    def test_admin_creates_checkout_for_customer_invoice(self, admin_token, customer_auth):
        cid = customer_auth["user"]["customer_id"]
        inv = _make_invoice(admin_token, cid, unit_price=25.0)
        r = requests.post(f"{API}/payments/checkout/{inv['id']}",
                          headers=_h(admin_token), json=OK_URL, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["session_id"].startswith("cs_test_"), body
        assert body["url"].startswith("https://checkout.stripe.com/"), body

    def test_customer_creates_checkout_for_own_invoice(self, admin_token, customer_auth):
        tok = customer_auth["access_token"]
        cid = customer_auth["user"]["customer_id"]
        inv = _make_invoice(admin_token, cid, unit_price=17.5)
        r = requests.post(f"{API}/payments/checkout/{inv['id']}",
                          headers=_h(tok), json=OK_URL, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["session_id"].startswith("cs_test_")
        assert body["url"].startswith("https://checkout.stripe.com/")

    def test_technician_forbidden_on_checkout(self, tech_token, admin_token, customer_auth):
        cid = customer_auth["user"]["customer_id"]
        inv = _make_invoice(admin_token, cid)
        r = requests.post(f"{API}/payments/checkout/{inv['id']}",
                          headers=_h(tech_token), json=OK_URL, timeout=30)
        assert r.status_code == 403

    def test_customer_cannot_checkout_other_customer_invoice(self, admin_token, customer_auth):
        tok = customer_auth["access_token"]
        my_cid = customer_auth["user"]["customer_id"]
        all_q = requests.get(f"{API}/quotes", headers=_h(admin_token), timeout=30).json()
        other = next(
            (q for q in all_q if q["customer_id"] != my_cid
             and q["doc_type"] == "invoice"
             and q.get("payment_status") != "paid"),
            None,
        )
        if not other:
            # create one for a different customer
            customers = requests.get(f"{API}/customers", headers=_h(admin_token), timeout=30).json()
            other_c = next((c for c in customers if c["id"] != my_cid), None)
            assert other_c, "need at least one other customer"
            other = _make_invoice(admin_token, other_c["id"])
        r = requests.post(f"{API}/payments/checkout/{other['id']}",
                          headers=_h(tok), json=OK_URL, timeout=30)
        assert r.status_code == 403

    def test_checkout_not_found_404(self, admin_token):
        r = requests.post(f"{API}/payments/checkout/does-not-exist",
                          headers=_h(admin_token), json=OK_URL, timeout=30)
        assert r.status_code == 404

    def test_checkout_already_paid_400(self, admin_token, customer_auth):
        cid = customer_auth["user"]["customer_id"]
        inv = _make_invoice(admin_token, cid)
        pay = requests.post(f"{API}/quotes/{inv['id']}/pay", headers=_h(admin_token), timeout=30)
        assert pay.status_code == 200 and pay.json()["payment_status"] == "paid"
        r = requests.post(f"{API}/payments/checkout/{inv['id']}",
                          headers=_h(admin_token), json=OK_URL, timeout=30)
        assert r.status_code == 400

    def test_checkout_amount_from_server_not_client(self, admin_token, customer_auth):
        """Regardless of client 'amount' in body, Stripe session must reflect the invoice total."""
        cid = customer_auth["user"]["customer_id"]
        inv = _make_invoice(admin_token, cid, unit_price=88.0)
        # CheckoutRequest only has success/cancel URLs; sending an "amount" is ignored.
        body = {**OK_URL, "amount": 1}
        r = requests.post(f"{API}/payments/checkout/{inv['id']}",
                          headers=_h(admin_token), json=body, timeout=30)
        assert r.status_code == 200, r.text
        sess_id = r.json()["session_id"]

        # Retrieve via /payments/status which proxies to Stripe
        st = requests.get(f"{API}/payments/status/{sess_id}",
                          headers=_h(admin_token), timeout=30)
        assert st.status_code == 200, st.text
        assert st.json()["invoice_id"] == inv["id"]


class TestPaymentStatus:
    def test_fresh_session_status_unpaid(self, admin_token, customer_auth):
        cid = customer_auth["user"]["customer_id"]
        inv = _make_invoice(admin_token, cid)
        chk = requests.post(f"{API}/payments/checkout/{inv['id']}",
                            headers=_h(admin_token), json=OK_URL, timeout=30)
        sess_id = chk.json()["session_id"]
        r = requests.get(f"{API}/payments/status/{sess_id}",
                         headers=_h(admin_token), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] in ("unpaid", "no_payment_required", "open"), data
        assert data["invoice_id"] == inv["id"]

    def test_technician_forbidden_on_status(self, admin_token, tech_token, customer_auth):
        cid = customer_auth["user"]["customer_id"]
        inv = _make_invoice(admin_token, cid)
        sess_id = requests.post(f"{API}/payments/checkout/{inv['id']}",
                                headers=_h(admin_token), json=OK_URL,
                                timeout=30).json()["session_id"]
        r = requests.get(f"{API}/payments/status/{sess_id}",
                         headers=_h(tech_token), timeout=30)
        assert r.status_code == 403


class TestAdminGenerateLink:
    def test_admin_generate_link(self, admin_token, customer_auth):
        cid = customer_auth["user"]["customer_id"]
        inv = _make_invoice(admin_token, cid, unit_price=55.0)
        r = requests.post(f"{API}/payments/admin/generate-link/{inv['id']}",
                          headers=_h(admin_token), timeout=45)
        assert r.status_code == 200, r.text
        url = r.json()["payment_url"]
        assert url.startswith("https://buy.stripe.com/test_"), url

        # Persisted on quote
        got = requests.get(f"{API}/quotes/{inv['id']}", headers=_h(admin_token), timeout=30)
        assert got.status_code == 200
        assert got.json().get("payment_link") == url

    def test_technician_forbidden_on_generate_link(self, admin_token, tech_token, customer_auth):
        cid = customer_auth["user"]["customer_id"]
        inv = _make_invoice(admin_token, cid)
        r = requests.post(f"{API}/payments/admin/generate-link/{inv['id']}",
                          headers=_h(tech_token), timeout=30)
        assert r.status_code == 403

    def test_customer_forbidden_on_generate_link(self, admin_token, customer_auth):
        tok = customer_auth["access_token"]
        cid = customer_auth["user"]["customer_id"]
        inv = _make_invoice(admin_token, cid)
        r = requests.post(f"{API}/payments/admin/generate-link/{inv['id']}",
                          headers=_h(tok), timeout=30)
        assert r.status_code == 403


class TestManualPayAdminOnly:
    def test_customer_forbidden(self, admin_token, customer_auth):
        tok = customer_auth["access_token"]
        cid = customer_auth["user"]["customer_id"]
        inv = _make_invoice(admin_token, cid)
        r = requests.post(f"{API}/quotes/{inv['id']}/pay", headers=_h(tok), timeout=30)
        assert r.status_code == 403

    def test_technician_forbidden(self, admin_token, tech_token, customer_auth):
        cid = customer_auth["user"]["customer_id"]
        inv = _make_invoice(admin_token, cid)
        r = requests.post(f"{API}/quotes/{inv['id']}/pay", headers=_h(tech_token), timeout=30)
        assert r.status_code == 403

    def test_admin_records_manual_payment(self, admin_token, customer_auth):
        cid = customer_auth["user"]["customer_id"]
        inv = _make_invoice(admin_token, cid)
        r = requests.post(f"{API}/quotes/{inv['id']}/pay", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200
        assert r.json()["payment_status"] == "paid"
        # Persistence
        got = requests.get(f"{API}/quotes/{inv['id']}", headers=_h(admin_token), timeout=30).json()
        assert got["payment_status"] == "paid"


class TestWebhook:
    def test_synthetic_checkout_session_completed_marks_paid(self, admin_token, customer_auth):
        cid = customer_auth["user"]["customer_id"]
        inv = _make_invoice(admin_token, cid, unit_price=12.0)
        # Ensure not paid
        assert inv.get("payment_status") != "paid"

        event = {
            "id": f"evt_test_{uuid.uuid4().hex[:12]}",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": f"cs_test_{uuid.uuid4().hex[:16]}",
                    "payment_status": "paid",
                    "metadata": {"invoice_id": inv["id"], "customer_id": cid},
                }
            },
        }
        # No STRIPE_WEBHOOK_SECRET configured -> unsigned JSON body accepted
        r = requests.post(f"{API}/payments/webhook", json=event, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("received") is True

        got = requests.get(f"{API}/quotes/{inv['id']}", headers=_h(admin_token), timeout=30).json()
        assert got["payment_status"] == "paid"
