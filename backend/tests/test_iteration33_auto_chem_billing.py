"""Iteration 33 — Auto chemical invoice billing.

Covers: PUT /api/jobs/{id}/field-report -> accrue_chem_invoice creates/updates a
monthly draft invoice for the customer, keyed by billing_month + job_id line
items. Includes pricing verification, idempotent replace, multi-job accrue,
non-billable chemical ignore, empty-invoice cleanup, and run_monthly_chem_billing
finalize.
"""
import os
import sys
import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

BACKEND_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = BACKEND_ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = BACKEND_ENV.get("DB_NAME") or os.environ.get("DB_NAME")

FRONTEND_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = (
    FRONTEND_ENV.get("EXPO_PUBLIC_BACKEND_URL")
    or FRONTEND_ENV.get("EXPO_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
).rstrip("/")


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
def tech_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": "mike@aquaterra.com", "password": "password123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def customer_id(mongo):
    c = mongo.customers.find_one({"email": "customer@aquaterra.com"})
    assert c, "seed customer not found"
    return c["id"]


@pytest.fixture(scope="module")
def tech_id(mongo):
    u = mongo.users.find_one({"email": "mike@aquaterra.com"})
    assert u and u.get("technician_id")
    return u["technician_id"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture
def two_jobs(mongo, admin_token, customer_id, tech_id):
    """Create two jobs on the same day (same billing month) for the same customer,
    assigned to Mike, so PUT /field-report is authorized for the tech token too.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ids = []
    for i in range(2):
        r = requests.post(f"{BASE_URL}/api/jobs", headers=_hdr(admin_token), json={
            "title": f"TEST_ChemJob {i}",
            "customer_id": customer_id,
            "technician_id": tech_id,
            "service_type": "Pool Cleaning",
            "scheduled_date": today,
            "price": 0,
            "status": "active",
        })
        assert r.status_code == 200, r.text
        ids.append(r.json()["id"])
    yield ids, today
    # cleanup jobs + any auto_chem invoices we created
    for jid in ids:
        mongo.jobs.delete_one({"id": jid})
    mongo.quotes.delete_many({"auto_chem": True, "customer_id": customer_id})
    mongo.notifications.delete_many({"customer_id": customer_id, "title": "New invoice"})


# ---------- catalog ----------
class TestCatalog:
    """GET /api/jobs/{id} exposes the chemical catalog including Enzymes."""

    def test_catalog_includes_enzymes(self, admin_token, two_jobs):
        ids, _ = two_jobs
        r = requests.get(f"{BASE_URL}/api/jobs/{ids[0]}", headers=_hdr(admin_token))
        assert r.status_code == 200
        names = [c["name"] for c in r.json().get("chemical_catalog", [])]
        assert "Enzymes" in names
        assert "Shock (Cal-Hypo)" in names
        assert "Phosphate Remover" in names
        assert "Clarifier" in names


# ---------- pricing / accrual ----------
class TestAccrue:
    def test_pricing_and_invoice_creation(self, tech_token, admin_token, two_jobs, mongo, customer_id):
        ids, today = two_jobs
        jid = ids[0]
        # Log 2 lbs Shock + Phosphate + Enzymes + a non-billable Chlorine Tablets
        r = requests.put(f"{BASE_URL}/api/jobs/{jid}/field-report", headers=_hdr(tech_token), json={
            "chemicals_added": [
                {"id": "Shock (Cal-Hypo)", "name": "Shock (Cal-Hypo)", "amount": "2", "unit": "lbs"},
                {"id": "Phosphate Remover", "name": "Phosphate Remover", "amount": "1", "unit": "oz"},
                {"id": "Enzymes", "name": "Enzymes", "amount": "1", "unit": "oz"},
                {"id": "Chlorine Tablets", "name": "Chlorine Tablets", "amount": "3", "unit": "tabs"},
            ]
        })
        assert r.status_code == 200, r.text

        billing_month = today[:7]
        inv = mongo.quotes.find_one(
            {"doc_type": "invoice", "auto_chem": True, "customer_id": customer_id,
             "billing_month": billing_month, "status": "draft"}, {"_id": 0}
        )
        assert inv, "auto_chem invoice was not created"
        assert inv["title"] == f"Chemical Charges — {billing_month}"
        # 3 billable lines; Chlorine Tablets ignored
        lines = inv["line_items"]
        assert len(lines) == 3
        by_desc = {li["description"].split(" — ")[0]: li for li in lines}
        assert "Shock (2 lbs)" in by_desc
        assert by_desc["Shock (2 lbs)"]["quantity"] == 2
        assert by_desc["Shock (2 lbs)"]["unit_price"] == 12.0
        assert by_desc["Phosphate treatment"]["quantity"] == 1
        assert by_desc["Phosphate treatment"]["unit_price"] == 45.0
        assert by_desc["Enzymes"]["unit_price"] == 25.0
        # service date suffix present on every line
        for li in lines:
            assert " — " in li["description"], f"missing service date in {li['description']!r}"
            assert li["job_id"] == jid
        # total: 24 + 45 + 25 = 94
        assert inv["total"] == 94.0

    def test_idempotent_replace_same_job(self, tech_token, two_jobs, mongo, customer_id):
        ids, today = two_jobs
        jid = ids[0]
        # Re-save the same job with only Clarifier -> job's prior lines dropped, new $25 total
        r = requests.put(f"{BASE_URL}/api/jobs/{jid}/field-report", headers=_hdr(tech_token), json={
            "chemicals_added": [
                {"id": "Clarifier", "name": "Clarifier", "amount": "1", "unit": "oz"},
            ]
        })
        assert r.status_code == 200
        inv = mongo.quotes.find_one(
            {"doc_type": "invoice", "auto_chem": True, "customer_id": customer_id,
             "billing_month": today[:7]}, {"_id": 0}
        )
        assert inv, "invoice missing after replace"
        job_lines = [li for li in inv["line_items"] if li["job_id"] == jid]
        assert len(job_lines) == 1
        assert job_lines[0]["unit_price"] == 25.0
        assert "Clarifier" in job_lines[0]["description"]
        assert inv["total"] == 25.0

    def test_multi_job_same_month_accrues(self, tech_token, two_jobs, mongo, customer_id):
        ids, today = two_jobs
        j1, j2 = ids
        # Log Clarifier on j1 and Enzymes on j2 -> both accrue on ONE monthly invoice
        r1 = requests.put(f"{BASE_URL}/api/jobs/{j1}/field-report", headers=_hdr(tech_token), json={
            "chemicals_added": [{"id": "Clarifier", "name": "Clarifier", "amount": "1", "unit": "oz"}]
        })
        assert r1.status_code == 200
        r2 = requests.put(f"{BASE_URL}/api/jobs/{j2}/field-report", headers=_hdr(tech_token), json={
            "chemicals_added": [{"id": "Enzymes", "name": "Enzymes", "amount": "1", "unit": "oz"}]
        })
        assert r2.status_code == 200
        invs = list(mongo.quotes.find(
            {"doc_type": "invoice", "auto_chem": True, "customer_id": customer_id,
             "billing_month": today[:7]}, {"_id": 0}
        ))
        assert len(invs) == 1, f"expected ONE monthly invoice, got {len(invs)}"
        lines = invs[0]["line_items"]
        job1_lines = [li for li in lines if li["job_id"] == j1]
        job2_lines = [li for li in lines if li["job_id"] == j2]
        assert len(job1_lines) == 1 and job1_lines[0]["unit_price"] == 25.0
        assert len(job2_lines) == 1 and job2_lines[0]["unit_price"] == 25.0
        assert invs[0]["total"] == 50.0

    def test_clearing_chems_removes_lines_and_empty_invoice_deleted(self, tech_token, two_jobs, mongo, customer_id):
        ids, today = two_jobs
        j1, j2 = ids
        # Clear both jobs -> invoice should be deleted
        for jid in (j1, j2):
            r = requests.put(f"{BASE_URL}/api/jobs/{jid}/field-report", headers=_hdr(tech_token), json={
                "chemicals_added": []
            })
            assert r.status_code == 200
        inv = mongo.quotes.find_one(
            {"doc_type": "invoice", "auto_chem": True, "customer_id": customer_id,
             "billing_month": today[:7]}
        )
        assert inv is None, "empty auto_chem invoice was NOT deleted"


# ---------- monthly finalize ----------
class TestMonthlyFinalize:
    def test_run_monthly_chem_billing(self, tech_token, two_jobs, mongo, customer_id):
        """Backdate invoice to a past month, then invoke the finalize routine.
        Expect status -> 'sent', due_date set, and a customer 'New invoice' notification.
        """
        ids, _ = two_jobs
        jid = ids[0]
        # Create a fresh draft chem invoice
        r = requests.put(f"{BASE_URL}/api/jobs/{jid}/field-report", headers=_hdr(tech_token), json={
            "chemicals_added": [{"id": "Clarifier", "name": "Clarifier", "amount": "1", "unit": "oz"}]
        })
        assert r.status_code == 200
        inv = mongo.quotes.find_one({"doc_type": "invoice", "auto_chem": True,
                                     "customer_id": customer_id, "status": "draft"})
        assert inv, "no draft invoice to finalize"
        # Backdate to past month
        mongo.quotes.update_one({"id": inv["id"]}, {"$set": {"billing_month": "2026-06"}})
        # Invoke the routine directly from the backend module
        sys.path.insert(0, "/app/backend")
        try:
            from routers.finances import run_monthly_chem_billing  # noqa: E402
            asyncio.run(run_monthly_chem_billing())
        finally:
            if "/app/backend" in sys.path:
                sys.path.remove("/app/backend")
        finalized = mongo.quotes.find_one({"id": inv["id"]}, {"_id": 0})
        assert finalized["status"] == "sent", finalized
        assert finalized.get("due_date"), "due_date should be set on finalize"
        # notification pushed to customer
        note = mongo.notifications.find_one(
            {"customer_id": customer_id, "title": "New invoice"}
        )
        assert note, "customer was not notified of finalized invoice"
