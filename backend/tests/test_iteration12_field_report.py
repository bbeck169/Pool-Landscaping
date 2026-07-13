"""Iteration 12 — Field Report (pool vs landscaping) for jobs.

Covers:
- GET /api/jobs/{id} returns job_type, default checklist template, reading_fields,
  chemical_readings, chemicals_added, and reading_report (with qualitative ratings).
- PUT /api/jobs/{id}/field-report — admin & assigned technician can save
  {checklist, chemical_readings, chemicals_added}; response recomputes ratings.
- Customer PUT → 403; Technician PUT on job NOT assigned to them → 403.
- Rating tiers: Below Average / Average / Above Average / High.
- Seed data guarantees: 'Backyard Landscaping Service' job for demo customer + one unpaid invoice.
"""
import os
import pytest
import requests
from dotenv import dotenv_values
from pathlib import Path

# Prefer preview URL from frontend env (public URL user sees), fallback to EXPO_BACKEND_URL
_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or _FE_ENV.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
).rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    d = r.json()
    return d.get("access_token") or d.get("token")


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def tech_tok():
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def cust_tok():
    return _login("customer@aquaterra.com")


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def customer_jobs(cust_tok):
    r = requests.get(f"{API}/jobs", headers=_h(cust_tok), timeout=15)
    assert r.status_code == 200
    jobs = r.json()
    assert len(jobs) >= 1, "customer should have at least one seeded job"
    return jobs


@pytest.fixture(scope="module")
def pool_job_id(customer_jobs):
    for j in customer_jobs:
        st = (j.get("service_type") or "").lower()
        if "pool" in st or st in ("inspection",):
            return j["id"]
    return customer_jobs[0]["id"]


@pytest.fixture(scope="module")
def landscaping_job_id(customer_jobs):
    for j in customer_jobs:
        if "landscap" in (j.get("service_type") or "").lower():
            return j["id"]
    pytest.skip("no landscaping job seeded for demo customer")


# ---------- Seed guarantees ----------

class TestSeedGuarantees:
    def test_customer_has_pool_and_landscaping_jobs(self, customer_jobs):
        types = [(j.get("service_type") or "").lower() for j in customer_jobs]
        assert any("landscap" in t for t in types), "seed must include a landscaping job for demo customer"
        assert any(("pool" in t) or t == "inspection" for t in types), "seed must include a pool/inspection job"

    def test_customer_has_unpaid_invoice(self, cust_tok):
        r = requests.get(f"{API}/quotes", headers=_h(cust_tok), timeout=15)
        assert r.status_code == 200
        unpaid = [q for q in r.json() if q.get("doc_type") == "invoice" and q.get("payment_status") == "unpaid"]
        assert len(unpaid) >= 1, "seed_extras must preserve one unpaid invoice for demo customer"


# ---------- GET /jobs/{id} shape ----------

class TestGetJobShape:
    def test_pool_job_returns_full_field_report(self, admin_tok, pool_job_id):
        r = requests.get(f"{API}/jobs/{pool_job_id}", headers=_h(admin_tok), timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert j["job_type"] == "pool"
        assert isinstance(j.get("checklist"), list) and len(j["checklist"]) == 8
        assert all("label" in c and "done" in c and "id" in c for c in j["checklist"])
        assert isinstance(j.get("reading_fields"), list) and len(j["reading_fields"]) == 5
        assert isinstance(j.get("chemical_readings"), dict)
        assert isinstance(j.get("chemicals_added"), list)
        assert isinstance(j.get("reading_report"), list)

    def test_landscaping_job_returns_landscaping_checklist_no_readings(self, admin_tok, landscaping_job_id):
        r = requests.get(f"{API}/jobs/{landscaping_job_id}", headers=_h(admin_tok), timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert j["job_type"] == "landscaping"
        assert len(j["checklist"]) == 8
        assert "Mow" in j["checklist"][0]["label"]
        assert "reading_fields" not in j
        assert "reading_report" not in j

    def test_customer_can_read_own_pool_job(self, cust_tok, pool_job_id):
        r = requests.get(f"{API}/jobs/{pool_job_id}", headers=_h(cust_tok), timeout=15)
        assert r.status_code == 200
        assert r.json()["job_type"] == "pool"


# ---------- PUT /field-report RBAC + persistence ----------

class TestFieldReportRBAC:
    def test_customer_cannot_update(self, cust_tok, pool_job_id):
        r = requests.put(
            f"{API}/jobs/{pool_job_id}/field-report",
            headers=_h(cust_tok),
            json={"chemical_readings": {"ph": 7.5}},
            timeout=15,
        )
        assert r.status_code == 403

    def test_technician_not_assigned_gets_403(self, tech_tok, admin_tok):
        # Find a job NOT assigned to Mike (tech1). Pool job for Whitmore HOA is on Sara.
        r = requests.get(f"{API}/jobs", headers=_h(admin_tok), timeout=15)
        assert r.status_code == 200
        mine_target = None
        for j in r.json():
            if j.get("technician_id") and "Sara" in (j.get("technician_name") or ""):
                mine_target = j["id"]
                break
        if not mine_target:
            pytest.skip("no non-Mike job in seed")
        r = requests.put(
            f"{API}/jobs/{mine_target}/field-report",
            headers=_h(tech_tok),
            json={"chemical_readings": {"ph": 7.5}},
            timeout=15,
        )
        assert r.status_code == 403


class TestFieldReportPersistence:
    """Assigned technician updates field report; verify persistence + rating recompute."""

    def _pick_mike_pool_job(self, tech_tok):
        r = requests.get(f"{API}/jobs", headers=_h(tech_tok), timeout=15)
        assert r.status_code == 200
        for j in r.json():
            if "pool" in (j.get("service_type") or "").lower():
                return j["id"]
        pytest.skip("Mike has no pool job in seed")

    def test_technician_can_save_and_ratings_recompute(self, tech_tok):
        jid = self._pick_mike_pool_job(tech_tok)
        payload = {
            "checklist": [{"id": f"c{i}", "label": "x", "done": (i % 2 == 0)} for i in range(8)],
            "chemical_readings": {"ph": 7.5, "chlorine": 0.5, "alkalinity": 100, "cyanuric": 60, "salt": 6000},
            "chemicals_added": [{"id": "1", "name": "TEST_Chlorine", "amount": "3"}],
        }
        r = requests.put(f"{API}/jobs/{jid}/field-report", headers=_h(tech_tok), json=payload, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        # Persistence via GET
        g = requests.get(f"{API}/jobs/{jid}", headers=_h(tech_tok), timeout=15).json()
        assert g["chemical_readings"]["ph"] == 7.5
        assert g["chemicals_added"][0]["name"] == "TEST_Chlorine"
        assert sum(1 for c in g["checklist"] if c["done"]) == 4
        # Ratings recompute:
        rr = {r["key"]: r["rating"] for r in j["reading_report"]}
        assert rr["ph"] == "Average"          # 7.4-7.6
        assert rr["chlorine"] == "Below Average"  # <1
        assert rr["alkalinity"] == "Average"  # 80-120
        assert rr["cyanuric"] == "Above Average"  # 50 < 60 <= 70
        assert rr["salt"] == "High"            # > 4100 upper bound

    def test_admin_can_save(self, admin_tok, tech_tok):
        jid = self._pick_mike_pool_job(tech_tok)
        r = requests.put(
            f"{API}/jobs/{jid}/field-report",
            headers=_h(admin_tok),
            json={"chemical_readings": {"ph": 7.0}},
            timeout=15,
        )
        assert r.status_code == 200
        rr = {x["key"]: x["rating"] for x in r.json()["reading_report"]}
        assert rr["ph"] == "Below Average"  # <7.4


# ---------- Rating tier boundaries ----------

class TestRatingTiers:
    @pytest.mark.parametrize("ph,expected", [
        (7.0, "Below Average"),   # <7.4
        (7.5, "Average"),         # 7.4..7.6
        (7.7, "Above Average"),   # up to 7.6+(0.2)=7.8
        (8.2, "High"),            # >7.8
    ])
    def test_ph_rating_boundaries(self, tech_tok, ph, expected):
        r = requests.get(f"{API}/jobs", headers=_h(tech_tok), timeout=15)
        jid = None
        for j in r.json():
            if "pool" in (j.get("service_type") or "").lower():
                jid = j["id"]; break
        assert jid, "need Mike pool job"
        rr = requests.put(
            f"{API}/jobs/{jid}/field-report",
            headers=_h(tech_tok),
            json={"chemical_readings": {"ph": ph}},
            timeout=15,
        )
        assert rr.status_code == 200
        rep = {x["key"]: x["rating"] for x in rr.json()["reading_report"]}
        assert rep["ph"] == expected, f"pH {ph} expected {expected}, got {rep['ph']}"


# ---------- Customer read-only view sees rated report ----------

class TestCustomerReadOnlyView:
    def test_customer_pool_job_returns_reading_report_with_ratings(self, cust_tok, pool_job_id):
        r = requests.get(f"{API}/jobs/{pool_job_id}", headers=_h(cust_tok), timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert j["job_type"] == "pool"
        assert "reading_report" in j
        assert isinstance(j["reading_report"], list)
        # ratings must be one of the four qualitative labels (or empty if no readings on this job)
        allowed = {"Below Average", "Average", "Above Average", "High"}
        for row in j["reading_report"]:
            assert row["rating"] in allowed
            assert "value" in row and "label" in row and "ideal" in row
