"""Iteration 18 — Customer Portal (Phase 1 + 2) backend tests.

Covers:
- Customer /dashboard shape (outstanding, unpaid_invoices, pending_estimates,
  unread_messages, documents_count, next_service)
- GET/PUT /me profile round-trip
- /quotes?doc_type=invoice & =quote scoping to logged-in customer
- POST /quotes/{id}/decision (approve / decline)
- GET /me/payments (total_paid, count, payments[])
- GET/POST /me/messages (send + persist + read receipt)
- Admin /communications (list threads) + GET /communications/{cid} +
  POST /communications/{cid}/reply
- GET /me/documents (customer view) and admin POST/GET/DELETE /documents
- Role guards (customer redirect / staff still works)
"""
import os
import pytest
import requests
from pathlib import Path
from dotenv import dotenv_values

_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = (_ENV.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL", "")).rstrip("/")
API = f"{BASE_URL}/api"

CUSTOMER = {"email": "customer@aquaterra.com", "password": "password123"}
ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    body = r.json()
    return body.get("access_token") or body.get("token"), body["user"]


@pytest.fixture(scope="module")
def customer_ctx():
    tok, user = _login(CUSTOMER)
    return {"headers": {"Authorization": f"Bearer {tok}"}, "user": user}


@pytest.fixture(scope="module")
def admin_ctx():
    tok, user = _login(ADMIN)
    return {"headers": {"Authorization": f"Bearer {tok}"}, "user": user}


@pytest.fixture(scope="module")
def tech_ctx():
    tok, user = _login(TECH)
    return {"headers": {"Authorization": f"Bearer {tok}"}, "user": user}


# ---------------- Dashboard ----------------
class TestCustomerDashboard:
    def test_dashboard_shape(self, customer_ctx):
        r = requests.get(f"{API}/dashboard", headers=customer_ctx["headers"], timeout=15)
        assert r.status_code == 200
        d = r.json()
        for k in ("role", "outstanding", "unpaid_invoices", "pending_estimates",
                 "unread_messages", "documents_count", "active_jobs",
                 "completed_jobs", "next_service"):
            assert k in d, f"missing key {k}: {d.keys()}"
        assert d["role"] == "customer"
        assert isinstance(d["unpaid_invoices"], int)
        assert isinstance(d["pending_estimates"], int)
        assert isinstance(d["unread_messages"], int)
        assert isinstance(d["documents_count"], int)


# ---------------- Profile /me ----------------
class TestProfile:
    def test_get_me(self, customer_ctx):
        r = requests.get(f"{API}/me", headers=customer_ctx["headers"], timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d.get("name")
        assert "id" in d
        assert "_id" not in d

    def test_put_me_roundtrip(self, customer_ctx):
        # Save current, patch, restore
        cur = requests.get(f"{API}/me", headers=customer_ctx["headers"], timeout=15).json()
        original = {
            "name": cur.get("name"),
            "phone": cur.get("phone", ""),
            "address": cur.get("address", ""),
            "billing_address": cur.get("billing_address", ""),
        }
        new_phone = "555-TEST-018"
        r = requests.put(f"{API}/me",
                         json={"phone": new_phone, "billing_address": "TEST_BILL_18"},
                         headers=customer_ctx["headers"], timeout=15)
        assert r.status_code == 200
        upd = r.json()
        assert upd["phone"] == new_phone
        assert upd["billing_address"] == "TEST_BILL_18"
        # Verify with GET
        got = requests.get(f"{API}/me", headers=customer_ctx["headers"], timeout=15).json()
        assert got["phone"] == new_phone
        assert got["billing_address"] == "TEST_BILL_18"
        # Restore
        requests.put(f"{API}/me", json=original,
                     headers=customer_ctx["headers"], timeout=15)

    def test_put_me_forbidden_for_admin(self, admin_ctx):
        r = requests.put(f"{API}/me", json={"name": "should_fail"},
                         headers=admin_ctx["headers"], timeout=15)
        assert r.status_code == 403


# ---------------- Quotes filtering + decision ----------------
class TestQuotesCustomer:
    def test_invoices_scoped_to_customer(self, customer_ctx):
        r = requests.get(f"{API}/quotes?doc_type=invoice",
                         headers=customer_ctx["headers"], timeout=15)
        assert r.status_code == 200
        cid = customer_ctx["user"].get("customer_id")
        for q in r.json():
            assert q["doc_type"] == "invoice"
            assert q["customer_id"] == cid

    def test_estimates_scoped_to_customer(self, customer_ctx):
        r = requests.get(f"{API}/quotes?doc_type=quote",
                         headers=customer_ctx["headers"], timeout=15)
        assert r.status_code == 200
        cid = customer_ctx["user"].get("customer_id")
        for q in r.json():
            assert q["doc_type"] == "quote"
            assert q["customer_id"] == cid

    def test_estimate_approve_decline_flow(self, customer_ctx, admin_ctx):
        # Create a new estimate as admin for THIS customer
        cid = customer_ctx["user"].get("customer_id")
        payload = {
            "customer_id": cid, "title": "TEST_estimate_iter18",
            "doc_type": "quote", "tax_rate": 0.0,
            "line_items": [{"description": "test", "quantity": 1, "unit_price": 100.0}],
        }
        r = requests.post(f"{API}/quotes", json=payload,
                          headers=admin_ctx["headers"], timeout=15)
        assert r.status_code == 200
        qid = r.json()["id"]

        # Approve
        r = requests.post(f"{API}/quotes/{qid}/decision?decision=approve",
                          headers=customer_ctx["headers"], timeout=15)
        assert r.status_code == 200
        assert r.json()["status"] == "accepted"

        # Create second and decline
        payload["title"] = "TEST_estimate_iter18_decline"
        r = requests.post(f"{API}/quotes", json=payload,
                          headers=admin_ctx["headers"], timeout=15)
        qid2 = r.json()["id"]
        r = requests.post(f"{API}/quotes/{qid2}/decision?decision=decline",
                          headers=customer_ctx["headers"], timeout=15)
        assert r.status_code == 200
        assert r.json()["status"] == "declined"

        # Cleanup: delete both
        requests.delete(f"{API}/quotes/{qid}", headers=admin_ctx["headers"], timeout=15)
        requests.delete(f"{API}/quotes/{qid2}", headers=admin_ctx["headers"], timeout=15)

    def test_decision_rejects_non_customer(self, admin_ctx):
        # Any dummy id → admin gets 403
        r = requests.post(f"{API}/quotes/xxx/decision?decision=approve",
                          headers=admin_ctx["headers"], timeout=15)
        assert r.status_code == 403

    def test_decision_rejects_invoice(self, customer_ctx, admin_ctx):
        # Create an invoice, decision should 400
        cid = customer_ctx["user"].get("customer_id")
        r = requests.post(f"{API}/quotes", json={
            "customer_id": cid, "title": "TEST_invoice_iter18",
            "doc_type": "invoice", "tax_rate": 0.0,
            "line_items": [{"description": "x", "quantity": 1, "unit_price": 1.0}],
        }, headers=admin_ctx["headers"], timeout=15)
        qid = r.json()["id"]
        r = requests.post(f"{API}/quotes/{qid}/decision?decision=approve",
                          headers=customer_ctx["headers"], timeout=15)
        assert r.status_code == 400
        requests.delete(f"{API}/quotes/{qid}", headers=admin_ctx["headers"], timeout=15)


# ---------------- Payments ----------------
class TestMyPayments:
    def test_my_payments_shape(self, customer_ctx):
        r = requests.get(f"{API}/me/payments", headers=customer_ctx["headers"], timeout=15)
        assert r.status_code == 200
        d = r.json()
        for k in ("total_paid", "count", "payments"):
            assert k in d
        assert isinstance(d["payments"], list)
        assert d["count"] == len(d["payments"])
        if d["payments"]:
            p = d["payments"][0]
            for k in ("id", "title", "amount", "paid_at", "method"):
                assert k in p

    def test_my_payments_forbidden_for_tech(self, tech_ctx):
        r = requests.get(f"{API}/me/payments", headers=tech_ctx["headers"], timeout=15)
        assert r.status_code == 403


# ---------------- Messages ----------------
class TestMessages:
    def test_send_and_persist(self, customer_ctx):
        text = "TEST_customer_msg_iter18"
        r = requests.post(f"{API}/me/messages", json={"text": text},
                          headers=customer_ctx["headers"], timeout=15)
        assert r.status_code == 200
        m = r.json()
        assert m["sender"] == "customer"
        assert m["text"] == text
        assert "_id" not in m

        # Verify GET returns it
        r = requests.get(f"{API}/me/messages", headers=customer_ctx["headers"], timeout=15)
        assert r.status_code == 200
        assert any(x["id"] == m["id"] for x in r.json())

    def test_admin_reply_flow(self, customer_ctx, admin_ctx):
        cid = customer_ctx["user"]["customer_id"]
        # Send a customer msg first so thread exists
        requests.post(f"{API}/me/messages", json={"text": "TEST_thread_starter_18"},
                      headers=customer_ctx["headers"], timeout=15)

        # Admin lists threads
        r = requests.get(f"{API}/communications", headers=admin_ctx["headers"], timeout=15)
        assert r.status_code == 200
        threads = r.json()
        assert any(t["customer_id"] == cid for t in threads)

        # Admin gets thread
        r = requests.get(f"{API}/communications/{cid}", headers=admin_ctx["headers"], timeout=15)
        assert r.status_code == 200
        assert "messages" in r.json()
        assert r.json()["customer_name"]

        # Admin replies
        reply_text = "TEST_admin_reply_18"
        r = requests.post(f"{API}/communications/{cid}/reply",
                          json={"text": reply_text}, headers=admin_ctx["headers"], timeout=15)
        assert r.status_code == 200
        assert r.json()["sender"] == "business"
        assert r.json()["text"] == reply_text

        # Customer sees it and unread was flipped after GET
        r = requests.get(f"{API}/me/messages", headers=customer_ctx["headers"], timeout=15)
        assert any(m["text"] == reply_text for m in r.json())

    def test_customer_forbidden_communications(self, customer_ctx):
        r = requests.get(f"{API}/communications", headers=customer_ctx["headers"], timeout=15)
        assert r.status_code == 403


# ---------------- Documents ----------------
class TestDocuments:
    def test_admin_upload_customer_view_delete(self, customer_ctx, admin_ctx):
        cid = customer_ctx["user"]["customer_id"]
        # Admin uploads
        payload = {
            "customer_id": cid, "name": "TEST_doc_iter18.pdf",
            "type": "agreement", "data": "data:application/pdf;base64,JVBERi0="
        }
        r = requests.post(f"{API}/documents", json=payload,
                          headers=admin_ctx["headers"], timeout=15)
        assert r.status_code == 200, r.text
        did = r.json()["id"]
        assert r.json()["uploaded_by"]

        # Customer sees it
        r = requests.get(f"{API}/me/documents", headers=customer_ctx["headers"], timeout=15)
        assert r.status_code == 200
        assert any(d["id"] == did for d in r.json())

        # Admin lists per customer
        r = requests.get(f"{API}/documents?customer_id={cid}",
                         headers=admin_ctx["headers"], timeout=15)
        assert r.status_code == 200
        assert any(d["id"] == did for d in r.json())

        # Admin deletes → customer no longer sees
        r = requests.delete(f"{API}/documents/{did}",
                            headers=admin_ctx["headers"], timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{API}/me/documents", headers=customer_ctx["headers"], timeout=15)
        assert not any(d["id"] == did for d in r.json())

    def test_customer_cannot_upload(self, customer_ctx):
        r = requests.post(f"{API}/documents",
                          json={"customer_id": "x", "name": "TEST_x.pdf", "data": "x"},
                          headers=customer_ctx["headers"], timeout=15)
        assert r.status_code == 403


# ---------------- Sanity: staff APIs still work ----------------
class TestStaffUnaffected:
    def test_admin_dashboard(self, admin_ctx):
        r = requests.get(f"{API}/dashboard", headers=admin_ctx["headers"], timeout=15)
        assert r.status_code == 200
        assert r.json()["role"] == "admin"

    def test_tech_dashboard(self, tech_ctx):
        r = requests.get(f"{API}/dashboard", headers=tech_ctx["headers"], timeout=15)
        assert r.status_code == 200
        assert r.json()["role"] == "technician"
