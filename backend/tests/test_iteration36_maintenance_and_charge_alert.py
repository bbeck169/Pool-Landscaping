"""Iteration 36 — Maintenance tracker + Auto-charge failure alert.

Two feature sets:
  A) Filter / Salt-cell maintenance module:
      - GET  /api/maintenance/overview          (admin only)
      - POST /api/maintenance/schedule          (admin only, 400/404 validation)
      - POST /api/jobs/{jid}/maintenance-log    (admin OR assigned tech; 403 for customer)
      - GET  /api/maintenance/records           (admin+tech)
      - PUT  /api/maintenance/settings/{cid}    (admin only)
      - Overview reflects last_date + next_due + status (ok/due_soon/overdue).
  B) Auto-charge failure alert on invoices/overview:
      - Attach failing test PM (tok_chargeCustomerFail) to seed customer
      - Create unpaid invoice, POST /api/payments/charge-on-file/{qid} -> 402
      - GET /api/invoices/overview shows charge_failed=true + charge_error, summary.failed.count>=1
      - POST /api/quotes/{qid}/record-payment clears the flag
"""
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

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

TEST_MARKER = "iter36"


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------------- fixtures ----------------
@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    try:
        yield c[DB_NAME]
    finally:
        c.close()


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": "admin@aquaterra.com", "password": "password123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def tech_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": "mike@aquaterra.com", "password": "password123"})
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
    assert c, "seed customer missing"
    return c["id"]


@pytest.fixture(scope="module")
def tech_info(mongo):
    """Return (technician_id, user technician_id) for Mike; jobs are linked to
    technician_id (which for the seed user equals user['technician_id'])."""
    u = mongo.users.find_one({"email": "mike@aquaterra.com"}) or {}
    tid = u.get("technician_id")
    assert tid, "seed technician user missing technician_id"
    return tid


@pytest.fixture(scope="module")
def customer_snapshot(mongo, customer_id):
    """Save/restore Stripe fields on the seed customer so the demo isn't polluted."""
    doc = mongo.customers.find_one({"id": customer_id}) or {}
    keys = ["stripe_customer_id", "default_payment_method_id", "pm_brand",
            "pm_last4", "pm_type", "maintenance_intervals"]
    original = {k: doc.get(k) for k in keys}
    yield original
    unset = {k: "" for k, v in original.items() if v in (None, "", False)}
    set_ = {k: v for k, v in original.items() if v not in (None, "", False)}
    op = {}
    if set_:
        op["$set"] = set_
    if unset:
        op["$unset"] = unset
    if op:
        mongo.customers.update_one({"id": customer_id}, op)


@pytest.fixture(autouse=True)
def _cleanup_between(mongo, customer_id):
    """Remove all iter36 test artifacts before AND after each test."""
    def _purge():
        # jobs we created (title = maintenance labels + our marker in notes)
        job_ids = [j["id"] for j in mongo.jobs.find(
            {"customer_id": customer_id, "title": {"$in": ["Filter Cleaning", "Salt Cell Cleaning"]}},
            {"id": 1, "_id": 0})]
        if job_ids:
            mongo.jobs.delete_many({"id": {"$in": job_ids}})
            mongo.maintenance_records.delete_many({"job_id": {"$in": job_ids}})
        mongo.maintenance_records.delete_many({"customer_id": customer_id})
        mongo.notifications.delete_many(
            {"customer_id": customer_id, "title": "Service scheduled"})
        mongo.quotes.delete_many({"test_marker": TEST_MARKER})
        mongo.notifications.delete_many(
            {"customer_id": customer_id, "title": {"$in": ["Payment recorded"]},
             "body": {"$regex": "TEST_"}})
    _purge()
    yield
    _purge()


# =================================================================
# A) Maintenance tracker
# =================================================================
class TestMaintenanceRBAC:
    def test_overview_requires_admin_403_tech(self, tech_token):
        r = requests.get(f"{BASE_URL}/api/maintenance/overview", headers=_hdr(tech_token))
        assert r.status_code == 403, r.text

    def test_overview_requires_admin_403_customer(self, customer_token):
        r = requests.get(f"{BASE_URL}/api/maintenance/overview", headers=_hdr(customer_token))
        assert r.status_code == 403, r.text

    def test_overview_admin_ok(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/maintenance/overview", headers=_hdr(admin_token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "summary" in body and "rows" in body
        for k in ("overdue", "due_soon", "scheduled", "never"):
            assert k in body["summary"]
        if body["rows"]:
            row = body["rows"][0]
            assert "customer_id" in row and "customer_name" in row
            assert "filter" in row and "salt_cell" in row
            for sub in ("filter", "salt_cell"):
                assert row[sub]["label"] in ("Filter Cleaning", "Salt Cell Cleaning")
                assert "status" in row[sub] and "interval_days" in row[sub]


class TestMaintenanceScheduleValidation:
    def test_invalid_type_returns_400(self, admin_token, customer_id):
        r = requests.post(f"{BASE_URL}/api/maintenance/schedule",
                          headers=_hdr(admin_token),
                          json={"customer_id": customer_id, "type": "bogus",
                                "scheduled_date": "2026-06-01"})
        assert r.status_code == 400, r.text

    def test_unknown_customer_returns_404(self, admin_token):
        r = requests.post(f"{BASE_URL}/api/maintenance/schedule",
                          headers=_hdr(admin_token),
                          json={"customer_id": "no-such-cid", "type": "filter",
                                "scheduled_date": "2026-06-01"})
        assert r.status_code == 404, r.text

    def test_tech_cannot_schedule(self, tech_token, customer_id):
        r = requests.post(f"{BASE_URL}/api/maintenance/schedule",
                          headers=_hdr(tech_token),
                          json={"customer_id": customer_id, "type": "filter",
                                "scheduled_date": "2026-06-01"})
        assert r.status_code == 403, r.text


class TestMaintenanceEndToEnd:
    """Schedule -> assigned tech logs -> overview shows last_date/next_due/status."""

    def test_schedule_creates_job_and_updates_interval(
            self, admin_token, customer_id, tech_info, mongo):
        tech_id = tech_info
        body = {"customer_id": customer_id, "type": "filter",
                "scheduled_date": "2026-06-15", "technician_id": tech_id,
                "interval_days": 100}
        r = requests.post(f"{BASE_URL}/api/maintenance/schedule",
                          headers=_hdr(admin_token), json=body)
        assert r.status_code == 200, r.text
        job = r.json()
        assert job["service_type"] == "Filter Cleaning"
        assert job["maintenance_type"] == "filter"
        assert job["customer_id"] == customer_id
        assert job["technician_id"] == tech_id

        # interval persisted on customer
        c = mongo.customers.find_one({"id": customer_id}, {"_id": 0})
        assert (c.get("maintenance_intervals") or {}).get("filter_interval_days") == 100

    def test_log_permissions_and_persistence(
            self, admin_token, tech_token, customer_token, customer_id, tech_info, mongo):
        tech_id = tech_info
        # Schedule a filter job assigned to Mike
        r = requests.post(f"{BASE_URL}/api/maintenance/schedule",
                          headers=_hdr(admin_token),
                          json={"customer_id": customer_id, "type": "filter",
                                "scheduled_date": "2026-06-20",
                                "technician_id": tech_id})
        assert r.status_code == 200, r.text
        jid = r.json()["id"]

        # Customer cannot log
        r = requests.post(f"{BASE_URL}/api/jobs/{jid}/maintenance-log",
                          headers=_hdr(customer_token), json={"psi": 12})
        assert r.status_code == 403

        # Assigned tech CAN log
        payload = {
            "psi": 15, "filter_condition": "clean", "notes": "TEST_ log by tech",
            "photos": [{"label": "before", "data": "data:image/png;base64,AAA"}],
        }
        r = requests.post(f"{BASE_URL}/api/jobs/{jid}/maintenance-log",
                          headers=_hdr(tech_token), json=payload)
        assert r.status_code == 200, r.text
        updated = r.json()
        assert updated.get("maintenance_logged") is True
        assert updated.get("maintenance", {}).get("psi") == 15

        # Verify db.maintenance_records upsert keyed by job_id
        rec = mongo.maintenance_records.find_one({"job_id": jid})
        assert rec and rec["type"] == "filter"
        assert rec["psi"] == 15 and len(rec.get("photos", [])) == 1

        # Records endpoint returns it (admin)
        r = requests.get(
            f"{BASE_URL}/api/maintenance/records",
            headers=_hdr(admin_token),
            params={"customer_id": customer_id, "type": "filter"})
        assert r.status_code == 200
        recs = r.json()
        assert any(x["job_id"] == jid for x in recs)
        # Customer role forbidden
        r = requests.get(
            f"{BASE_URL}/api/maintenance/records",
            headers=_hdr(customer_token),
            params={"customer_id": customer_id})
        assert r.status_code == 403

    def test_non_maintenance_job_log_400(self, admin_token, tech_token, mongo, customer_id, tech_info):
        # Create a non-maintenance job
        jid = str(uuid4())
        mongo.jobs.insert_one({
            "id": jid, "title": "Weekly Pool Service", "customer_id": customer_id,
            "customer_name": "Jennifer Carson", "technician_id": tech_info,
            "service_type": "Weekly Service", "scheduled_date": "2026-06-25",
            "status": "pending", "created_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            r = requests.post(f"{BASE_URL}/api/jobs/{jid}/maintenance-log",
                              headers=_hdr(tech_token), json={"psi": 10})
            assert r.status_code == 400, r.text
        finally:
            mongo.jobs.delete_one({"id": jid})

    def test_overdue_status_and_overview_reflects_log(
            self, admin_token, tech_token, customer_id, tech_info, mongo):
        tech_id = tech_info
        # Schedule salt-cell job well in the past to force OVERDUE next_due
        r = requests.post(f"{BASE_URL}/api/maintenance/schedule",
                          headers=_hdr(admin_token),
                          json={"customer_id": customer_id, "type": "salt_cell",
                                "scheduled_date": "2024-01-01",
                                "technician_id": tech_id,
                                "interval_days": 30})
        assert r.status_code == 200, r.text
        jid = r.json()["id"]
        # Log it (admin can log any job)
        r = requests.post(f"{BASE_URL}/api/jobs/{jid}/maintenance-log",
                          headers=_hdr(admin_token),
                          json={"salt_ppm": 3200, "cell_condition": "scaled"})
        assert r.status_code == 200, r.text

        r = requests.get(f"{BASE_URL}/api/maintenance/overview", headers=_hdr(admin_token))
        assert r.status_code == 200, r.text
        body = r.json()
        me = next((x for x in body["rows"] if x["customer_id"] == customer_id), None)
        assert me, "seed customer row missing from overview"
        salt = me["salt_cell"]
        assert salt["last_date"] == "2024-01-01", salt
        # next_due = last_date + interval_days (30) = 2024-01-31 -> < today -> overdue
        assert salt["status"] == "overdue", salt
        assert salt["interval_days"] == 30
        assert salt["next_due"] and salt["next_due"] < datetime.now(timezone.utc).date().isoformat()
        assert body["summary"]["overdue"] >= 1


class TestMaintenanceSettings:
    def test_admin_updates_intervals(self, admin_token, customer_id, mongo, customer_snapshot):
        r = requests.put(f"{BASE_URL}/api/maintenance/settings/{customer_id}",
                         headers=_hdr(admin_token),
                         json={"filter_interval_days": 45, "salt_cell_interval_days": 400})
        assert r.status_code == 200, r.text
        c = mongo.customers.find_one({"id": customer_id}, {"_id": 0}) or {}
        mi = c.get("maintenance_intervals") or {}
        assert mi.get("filter_interval_days") == 45
        assert mi.get("salt_cell_interval_days") == 400

    def test_settings_unknown_customer_404(self, admin_token):
        r = requests.put(f"{BASE_URL}/api/maintenance/settings/no-such-cid",
                         headers=_hdr(admin_token),
                         json={"filter_interval_days": 90})
        assert r.status_code == 404, r.text

    def test_settings_forbidden_for_tech(self, tech_token, customer_id):
        r = requests.put(f"{BASE_URL}/api/maintenance/settings/{customer_id}",
                         headers=_hdr(tech_token),
                         json={"filter_interval_days": 90})
        assert r.status_code == 403, r.text


# =================================================================
# B) Auto-charge failure alert on invoices/overview
# =================================================================
class TestChargeFailureAlert:
    """Attach a declining test PM, charge -> 402, invoice flagged; record-payment clears."""

    @pytest.fixture
    def customer_with_failing_pm(self, mongo, customer_id, customer_snapshot):
        cust = mongo.customers.find_one({"id": customer_id}) or {}
        scid = cust.get("stripe_customer_id")
        if not scid:
            sc = stripe.Customer.create(
                name=cust.get("name") or "TEST Jennifer",
                email=cust.get("email") or "customer@aquaterra.com",
                metadata={"customer_id": customer_id, "test": TEST_MARKER})
            scid = sc.id
        # Declining test PM: charge_customer_fail
        pm = stripe.PaymentMethod.create(
            type="card", card={"token": "tok_chargeCustomerFail"})
        stripe.PaymentMethod.attach(pm.id, customer=scid)
        stripe.Customer.modify(scid, invoice_settings={"default_payment_method": pm.id})
        mongo.customers.update_one({"id": customer_id}, {"$set": {
            "stripe_customer_id": scid, "default_payment_method_id": pm.id,
            "pm_brand": "Visa", "pm_last4": "0341", "pm_type": "card",
        }})
        yield scid, pm.id
        try:
            stripe.PaymentMethod.detach(pm.id)
        except Exception:
            pass

    def _make_invoice(self, mongo, customer_id, total=42.5, title="TEST_ Fail-Alert Invoice"):
        qid = str(uuid4())
        mongo.quotes.insert_one({
            "id": qid, "doc_type": "invoice", "customer_id": customer_id,
            "customer_name": "Jennifer Carson", "title": title,
            "line_items": [{"description": "TEST_ fail line", "quantity": 1,
                            "unit_price": total, "service_date": "2026-06-01"}],
            "subtotal": total, "tax_rate": 0, "tax": 0.0, "total": total,
            "amount_paid": 0.0, "payment_status": "unpaid", "status": "sent",
            "due_date": (datetime.now(timezone.utc) + timedelta(days=14)).date().isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "test_marker": TEST_MARKER,
        })
        return qid

    def test_charge_on_file_fails_and_flags_invoice(
            self, admin_token, mongo, customer_id, customer_with_failing_pm):
        qid = self._make_invoice(mongo, customer_id)
        r = requests.post(f"{BASE_URL}/api/payments/charge-on-file/{qid}",
                          headers=_hdr(admin_token))
        assert r.status_code == 402, r.text
        # Persisted flag on quote
        q = mongo.quotes.find_one({"id": qid}, {"_id": 0})
        assert q.get("charge_failed") is True
        assert isinstance(q.get("charge_error"), str) and q["charge_error"]

        # Overview surfaces it
        r = requests.get(f"{BASE_URL}/api/invoices/overview", headers=_hdr(admin_token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["summary"]["failed"]["count"] >= 1
        row = next((i for i in body["invoices"] if i["id"] == qid), None)
        assert row, "flagged invoice missing from overview"
        assert row["charge_failed"] is True
        assert row["charge_error"], "charge_error should surface"

    def test_record_payment_clears_flag(
            self, admin_token, mongo, customer_id, customer_with_failing_pm):
        qid = self._make_invoice(mongo, customer_id)
        # First trigger failure
        r = requests.post(f"{BASE_URL}/api/payments/charge-on-file/{qid}",
                          headers=_hdr(admin_token))
        assert r.status_code == 402
        # Now record manual payment for full amount
        r = requests.post(f"{BASE_URL}/api/quotes/{qid}/record-payment",
                          headers=_hdr(admin_token), json={"amount": 42.5})
        assert r.status_code == 200, r.text
        q = mongo.quotes.find_one({"id": qid}, {"_id": 0})
        assert q.get("charge_failed") is False
        assert q.get("payment_status") == "paid"

        # Overview should no longer flag this invoice (it's paid & excluded)
        r = requests.get(f"{BASE_URL}/api/invoices/overview", headers=_hdr(admin_token))
        body = r.json()
        row = next((i for i in body["invoices"] if i["id"] == qid), None)
        assert row is None, "paid invoice should be excluded from AR overview"
