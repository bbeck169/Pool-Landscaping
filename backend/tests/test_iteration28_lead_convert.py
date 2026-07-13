"""Iteration 28 backend tests: Lead conversion to Job / Quote / Customer.

Covers:
- POST /api/leads/{id}/convert-to-job — admin only (403 for tech + customer)
  creates job (status=pending, price defaults to lead.est_value, service_type
  & scheduled_date from body), sets lead status='won' with converted={type:'job',id}
- POST /api/leads/{id}/convert-to-quote — admin only (403 others), creates quote
  doc_type='quote' status='sent' with one line item, subtotal/tax/total computed,
  sets lead status='quoted' with converted={type:'quote',id}
- Customer reuse: converting two leads with same phone -> ONE customer (no duplicates)
- POST /api/leads/{id}/convert (Convert to Customer) still works, lead -> 'won'
"""
import os
import uuid
import pytest
import requests
from pathlib import Path
from dotenv import dotenv_values
from pymongo import MongoClient

_FE_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_BE_ENV = Path(__file__).resolve().parents[1] / ".env"
_MONGO_URL = dotenv_values(_BE_ENV).get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = dotenv_values(_BE_ENV).get("DB_NAME") or os.environ.get("DB_NAME")
BASE_URL = (
    dotenv_values(_FE_ENV).get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
).rstrip("/")

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}
CUST = {"email": "customer@aquaterra.com", "password": "password123"}


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    j = r.json()
    return j.get("access_token") or j.get("token")


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def tokens():
    return {"admin": _login(**ADMIN), "tech": _login(**TECH), "cust": _login(**CUST)}


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    """After this module runs, purge any jobs/quotes/customers created by the
    convert flow keyed off our TEST_ConvertLead_* lead names."""
    yield
    if not (_MONGO_URL and _DB_NAME):
        return
    client = MongoClient(_MONGO_URL)
    try:
        db = client[_DB_NAME]
        prefix = {"$regex": "^TEST_ConvertLead_"}
        # jobs / quotes converted from these leads carry customer_name == lead["name"]
        db["jobs"].delete_many({"customer_name": prefix})
        db["quotes"].delete_many({"$or": [{"customer_name": prefix}, {"title": prefix}, {"title": {"$regex": "^Estimate for TEST_ConvertLead_"}}, {"title": "TEST_Custom Estimate"}]})
        db["customers"].delete_many({"name": prefix})
        db["leads"].delete_many({"name": prefix})
    finally:
        client.close()


def _make_lead(admin_tok, name_suffix, phone=None, est_value=350.0):
    body = {
        "name": f"TEST_ConvertLead_{name_suffix}",
        "phone": phone or f"+1555{uuid.uuid4().hex[:7]}",
        "email": f"TEST_{uuid.uuid4().hex[:6]}@example.com",
        "source": "Website",
        "status": "new",
        "notes": "Would like weekly pool service",
        "est_value": est_value,
    }
    r = requests.post(f"{BASE_URL}/api/leads", json=body, headers=_hdr(admin_tok))
    assert r.status_code in (200, 201), r.text
    return r.json()


def _get_lead(admin_tok, lid):
    # Filter leads and find our lead by id (no direct GET /leads/{id} exposed)
    r = requests.get(f"{BASE_URL}/api/leads", headers=_hdr(admin_tok))
    assert r.status_code == 200
    for l in r.json():
        if l["id"] == lid:
            return l
    return None


class TestConvertToJob:
    def test_admin_convert_to_job_success(self, tokens):
        lead = _make_lead(tokens["admin"], "job1", est_value=450.0)
        r = requests.post(
            f"{BASE_URL}/api/leads/{lead['id']}/convert-to-job",
            headers=_hdr(tokens["admin"]),
            json={"service_type": "Landscaping", "scheduled_date": "2026-02-01"},
        )
        assert r.status_code == 200, r.text
        job = r.json()
        # verify job shape
        assert job["status"] == "pending"
        assert job["service_type"] == "Landscaping"
        assert job["scheduled_date"] == "2026-02-01"
        assert job["price"] == 450.0  # defaults to lead.est_value
        assert job.get("customer_id")
        assert job.get("customer_name") == lead["name"]
        assert "_id" not in job
        # verify lead status via list
        updated = _get_lead(tokens["admin"], lead["id"])
        assert updated["status"] == "won"
        assert updated["converted"]["type"] == "job"
        assert updated["converted"]["id"] == job["id"]

        # verify job is persisted (GET /api/jobs contains it)
        rj = requests.get(f"{BASE_URL}/api/jobs", headers=_hdr(tokens["admin"]))
        assert rj.status_code == 200
        assert any(j["id"] == job["id"] for j in rj.json())

    def test_convert_to_job_price_override(self, tokens):
        lead = _make_lead(tokens["admin"], "job2", est_value=200.0)
        r = requests.post(
            f"{BASE_URL}/api/leads/{lead['id']}/convert-to-job",
            headers=_hdr(tokens["admin"]),
            json={"service_type": "Pool Service", "price": 999.99},
        )
        assert r.status_code == 200, r.text
        assert r.json()["price"] == 999.99

    def test_convert_to_job_forbidden_technician(self, tokens):
        lead = _make_lead(tokens["admin"], "job_tech403")
        r = requests.post(
            f"{BASE_URL}/api/leads/{lead['id']}/convert-to-job",
            headers=_hdr(tokens["tech"]),
            json={"service_type": "Pool Service"},
        )
        assert r.status_code == 403, r.text

    def test_convert_to_job_forbidden_customer(self, tokens):
        lead = _make_lead(tokens["admin"], "job_cust403")
        r = requests.post(
            f"{BASE_URL}/api/leads/{lead['id']}/convert-to-job",
            headers=_hdr(tokens["cust"]),
            json={"service_type": "Pool Service"},
        )
        assert r.status_code == 403, r.text


class TestConvertToQuote:
    def test_admin_convert_to_quote_success(self, tokens):
        lead = _make_lead(tokens["admin"], "quote1", est_value=500.0)
        r = requests.post(
            f"{BASE_URL}/api/leads/{lead['id']}/convert-to-quote",
            headers=_hdr(tokens["admin"]),
            json={},
        )
        assert r.status_code == 200, r.text
        q = r.json()
        assert q["doc_type"] == "quote"
        assert q["status"] == "sent"
        assert len(q["line_items"]) == 1
        assert q["line_items"][0]["unit_price"] == 500.0
        assert q["subtotal"] == 500.0
        assert q["tax"] == 0.0
        assert q["total"] == 500.0
        assert q["customer_name"] == lead["name"]
        assert "_id" not in q
        # lead status
        updated = _get_lead(tokens["admin"], lead["id"])
        assert updated["status"] == "quoted"
        assert updated["converted"]["type"] == "quote"
        assert updated["converted"]["id"] == q["id"]

    def test_convert_to_quote_with_tax_and_overrides(self, tokens):
        lead = _make_lead(tokens["admin"], "quote2", est_value=100.0)
        r = requests.post(
            f"{BASE_URL}/api/leads/{lead['id']}/convert-to-quote",
            headers=_hdr(tokens["admin"]),
            json={"title": "TEST_Custom Estimate", "unit_price": 200.0, "tax_rate": 10.0},
        )
        assert r.status_code == 200, r.text
        q = r.json()
        assert q["title"] == "TEST_Custom Estimate"
        assert q["subtotal"] == 200.0
        assert q["tax"] == 20.0
        assert q["total"] == 220.0

    def test_convert_to_quote_forbidden_technician(self, tokens):
        lead = _make_lead(tokens["admin"], "quote_tech403")
        r = requests.post(
            f"{BASE_URL}/api/leads/{lead['id']}/convert-to-quote",
            headers=_hdr(tokens["tech"]),
            json={},
        )
        assert r.status_code == 403

    def test_convert_to_quote_forbidden_customer(self, tokens):
        lead = _make_lead(tokens["admin"], "quote_cust403")
        r = requests.post(
            f"{BASE_URL}/api/leads/{lead['id']}/convert-to-quote",
            headers=_hdr(tokens["cust"]),
            json={},
        )
        assert r.status_code == 403


class TestCustomerReuse:
    def test_same_phone_reuses_customer(self, tokens):
        phone = f"+1555{uuid.uuid4().hex[:7]}"
        lead1 = _make_lead(tokens["admin"], "dupA", phone=phone)
        lead2 = _make_lead(tokens["admin"], "dupB", phone=phone)

        r1 = requests.post(
            f"{BASE_URL}/api/leads/{lead1['id']}/convert-to-job",
            headers=_hdr(tokens["admin"]), json={"service_type": "Pool Service"},
        )
        assert r1.status_code == 200, r1.text
        cust_id_1 = r1.json()["customer_id"]

        r2 = requests.post(
            f"{BASE_URL}/api/leads/{lead2['id']}/convert-to-quote",
            headers=_hdr(tokens["admin"]), json={},
        )
        assert r2.status_code == 200, r2.text
        cust_id_2 = r2.json()["customer_id"]

        assert cust_id_1 == cust_id_2, "same phone should reuse the same customer"

        # confirm only ONE customer exists with this phone
        rc = requests.get(f"{BASE_URL}/api/customers", headers=_hdr(tokens["admin"]))
        assert rc.status_code == 200
        matching = [c for c in rc.json() if c.get("phone") == phone]
        assert len(matching) == 1, f"expected 1 customer for phone, got {len(matching)}"


class TestConvertToCustomer:
    def test_admin_convert_to_customer(self, tokens):
        lead = _make_lead(tokens["admin"], "custconv")
        r = requests.post(
            f"{BASE_URL}/api/leads/{lead['id']}/convert",
            headers=_hdr(tokens["admin"]),
        )
        assert r.status_code == 200, r.text
        cust = r.json()
        assert cust["name"] == lead["name"]
        assert "_id" not in cust
        # lead moved to won
        updated = _get_lead(tokens["admin"], lead["id"])
        assert updated["status"] == "won"
        assert updated["converted"]["type"] == "customer"
        assert updated["converted"]["id"] == cust["id"]

    def test_convert_to_customer_forbidden_technician(self, tokens):
        lead = _make_lead(tokens["admin"], "custconv_tech")
        r = requests.post(
            f"{BASE_URL}/api/leads/{lead['id']}/convert",
            headers=_hdr(tokens["tech"]),
        )
        assert r.status_code == 403

    def test_convert_to_customer_forbidden_customer(self, tokens):
        lead = _make_lead(tokens["admin"], "custconv_cust")
        r = requests.post(
            f"{BASE_URL}/api/leads/{lead['id']}/convert",
            headers=_hdr(tokens["cust"]),
        )
        assert r.status_code == 403


class TestConvertNotFound:
    def test_convert_to_job_404(self, tokens):
        r = requests.post(
            f"{BASE_URL}/api/leads/does-not-exist-xyz/convert-to-job",
            headers=_hdr(tokens["admin"]), json={},
        )
        assert r.status_code == 404

    def test_convert_to_quote_404(self, tokens):
        r = requests.post(
            f"{BASE_URL}/api/leads/does-not-exist-xyz/convert-to-quote",
            headers=_hdr(tokens["admin"]), json={},
        )
        assert r.status_code == 404
