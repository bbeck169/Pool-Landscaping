"""Iteration 11 — Admin Dashboard Payments widget: /payments/summary + /quotes/{id}/remind.

Self-provisions its own TEST_ unpaid invoice for Jennifer Carson so it does not
depend on the seed's current payment state (which older test iterations may have
marked paid). Conftest teardown removes anything with a TEST_ prefix.
"""
import os
import time
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

_FRONTEND_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_CFG = dotenv_values(_FRONTEND_ENV)
BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or _CFG.get("EXPO_PUBLIC_BACKEND_URL") or "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be set"

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}
CUSTOMER = {"email": "customer@aquaterra.com", "password": "password123"}


def _login(session: requests.Session, creds: dict) -> dict:
    r = session.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login {creds['email']}: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login(requests.Session(), ADMIN)['access_token']}"}


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login(requests.Session(), TECH)['access_token']}"}


@pytest.fixture(scope="module")
def customer_auth():
    return _login(requests.Session(), CUSTOMER)


@pytest.fixture(scope="module")
def customer_headers(customer_auth):
    return {"Authorization": f"Bearer {customer_auth['access_token']}"}


@pytest.fixture(scope="module")
def unpaid_invoice(admin_headers, customer_auth):
    """Create a TEST_ unpaid invoice for Jennifer Carson (the seed customer)."""
    cid = customer_auth["user"]["customer_id"]
    payload = {
        "customer_id": cid,
        "title": f"TEST_Widget_Unpaid_{uuid.uuid4().hex[:6]}",
        "doc_type": "invoice",
        "tax_rate": 0.0,
        "line_items": [{"description": "TEST widget invoice", "quantity": 1, "unit_price": 75.0}],
    }
    r = requests.post(f"{BASE_URL}/api/quotes", headers=admin_headers, json=payload, timeout=30)
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv.get("payment_status") == "unpaid"
    return inv


# ----------------------- /payments/summary -----------------------
class TestPaymentsSummary:
    def test_summary_admin_shape(self, admin_headers, unpaid_invoice):
        r = requests.get(f"{BASE_URL}/api/payments/summary", headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("collected_this_month", "outstanding_total", "outstanding_count", "month_label", "overdue"):
            assert k in data, f"missing key {k} in summary: {list(data.keys())}"
        assert isinstance(data["overdue"], list)
        assert isinstance(data["outstanding_count"], int)
        assert isinstance(data["collected_this_month"], (int, float))
        assert isinstance(data["outstanding_total"], (int, float))
        assert isinstance(data["month_label"], str) and len(data["month_label"]) > 3

    def test_summary_has_our_unpaid_invoice(self, admin_headers, unpaid_invoice):
        r = requests.get(f"{BASE_URL}/api/payments/summary", headers=admin_headers, timeout=30)
        data = r.json()
        assert data["outstanding_count"] >= 1
        assert data["outstanding_total"] >= 75.0
        row = next((o for o in data["overdue"] if o["id"] == unpaid_invoice["id"]), None)
        assert row, f"our TEST_ unpaid invoice missing from overdue list"
        for k in ("id", "customer_id", "customer_name", "title", "total", "days", "reminded_at"):
            assert k in row, f"missing key {k} in overdue row"
        assert row["customer_name"] == "Jennifer Carson"
        assert row["total"] == 75.0

    def test_summary_forbidden_for_technician(self, tech_headers):
        r = requests.get(f"{BASE_URL}/api/payments/summary", headers=tech_headers, timeout=30)
        assert r.status_code == 403, r.text

    def test_summary_forbidden_for_customer(self, customer_headers):
        r = requests.get(f"{BASE_URL}/api/payments/summary", headers=customer_headers, timeout=30)
        assert r.status_code == 403, r.text

    def test_summary_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/payments/summary", timeout=30)
        assert r.status_code in (401, 403)


# ----------------------- /quotes/{id}/remind -----------------------
class TestRemindInvoice:
    def test_remind_forbidden_for_technician(self, tech_headers, unpaid_invoice):
        r = requests.post(f"{BASE_URL}/api/quotes/{unpaid_invoice['id']}/remind",
                          headers=tech_headers, timeout=30)
        assert r.status_code == 403, r.text

    def test_remind_forbidden_for_customer(self, customer_headers, unpaid_invoice):
        r = requests.post(f"{BASE_URL}/api/quotes/{unpaid_invoice['id']}/remind",
                          headers=customer_headers, timeout=30)
        assert r.status_code == 403, r.text

    def test_remind_unknown_invoice_returns_404(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/quotes/does-not-exist-xyz/remind",
                          headers=admin_headers, timeout=30)
        assert r.status_code == 404, r.text

    def test_remind_success_and_notification(self, admin_headers, customer_headers, unpaid_invoice):
        qid = unpaid_invoice["id"]

        before = requests.get(f"{BASE_URL}/api/notifications", headers=customer_headers, timeout=30).json()
        before_reminders = [n for n in before if n.get("title") == "Payment reminder"]

        r = requests.post(f"{BASE_URL}/api/quotes/{qid}/remind", headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("reminded_at"), "reminded_at missing in response"

        time.sleep(0.5)
        summary = requests.get(f"{BASE_URL}/api/payments/summary", headers=admin_headers, timeout=30).json()
        row = next((o for o in summary["overdue"] if o["id"] == qid), None)
        assert row and row.get("reminded_at"), f"reminded_at not persisted on quote: {row}"

        after = requests.get(f"{BASE_URL}/api/notifications", headers=customer_headers, timeout=30).json()
        after_reminders = [n for n in after if n.get("title") == "Payment reminder"]
        assert len(after_reminders) >= len(before_reminders) + 1, (
            f"Payment reminder notification not created. before={len(before_reminders)} "
            f"after={len(after_reminders)}"
        )

    def test_remind_paid_invoice_returns_400(self, admin_headers, customer_auth):
        """Create a fresh invoice, mark it paid, then verify remind returns 400."""
        cid = customer_auth["user"]["customer_id"]
        payload = {
            "customer_id": cid,
            "title": f"TEST_Widget_Paid_{uuid.uuid4().hex[:6]}",
            "doc_type": "invoice",
            "tax_rate": 0.0,
            "line_items": [{"description": "TEST paid", "quantity": 1, "unit_price": 10.0}],
        }
        inv = requests.post(f"{BASE_URL}/api/quotes", headers=admin_headers, json=payload, timeout=30).json()
        pay = requests.post(f"{BASE_URL}/api/quotes/{inv['id']}/pay", headers=admin_headers, timeout=30)
        assert pay.status_code == 200 and pay.json()["payment_status"] == "paid"
        r = requests.post(f"{BASE_URL}/api/quotes/{inv['id']}/remind", headers=admin_headers, timeout=30)
        assert r.status_code == 400, r.text
