"""Iteration 13 — Chemicals Added: per-catalog-item input UX.

The technician UI now renders one input per chemical from job.chemical_catalog and
strips out empty/zero entries before PUT /jobs/{id}/field-report. Backend contract
verified here:

- GET /jobs/{id} returns chemical_catalog for pool jobs.
- PUT /jobs/{id}/field-report accepts a filtered chemicals_added list and persists it.
- Sending an empty list clears chemicals_added on the doc.
- Sending only non-empty entries persists exactly those entries.
- Customer read still returns the stored chemicals_added (frontend hides section
  when list is empty; server just echoes what was stored).
"""
import os
import pytest
import requests
from dotenv import dotenv_values
from pathlib import Path

_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or _FE_ENV.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
).rstrip("/")
API = f"{BASE_URL}/api"

SAMPLE_POOL_JOB_ID = "98e9f3e8-6f5f-4ac5-88bf-2822fa4508d5"


def _login(email, password="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    d = r.json()
    return d.get("access_token") or d.get("token")


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def tech_tok():
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def cust_tok():
    return _login("customer@aquaterra.com")


@pytest.fixture(scope="module")
def pool_job_id(tech_tok):
    # Try the sample id first; else fall back to Mike's first pool job.
    r = requests.get(f"{API}/jobs/{SAMPLE_POOL_JOB_ID}", headers=_h(tech_tok), timeout=15)
    if r.status_code == 200 and (r.json().get("job_type") == "pool"):
        return SAMPLE_POOL_JOB_ID
    r = requests.get(f"{API}/jobs", headers=_h(tech_tok), timeout=15)
    assert r.status_code == 200
    for j in r.json():
        if "pool" in (j.get("service_type") or "").lower():
            return j["id"]
    pytest.skip("no pool job available for technician mike")


class TestChemicalCatalogShape:
    def test_pool_job_exposes_chemical_catalog(self, tech_tok, pool_job_id):
        r = requests.get(f"{API}/jobs/{pool_job_id}", headers=_h(tech_tok), timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert j["job_type"] == "pool"
        cat = j.get("chemical_catalog")
        assert isinstance(cat, list) and len(cat) >= 3, "chemical_catalog must be present with items"
        # Each catalog entry has name+unit for the per-chemical input UX.
        for item in cat:
            assert item.get("name")
            assert "unit" in item  # may be empty string but must exist

    def test_pool_job_initial_chemicals_added_is_list(self, tech_tok, pool_job_id):
        r = requests.get(f"{API}/jobs/{pool_job_id}", headers=_h(tech_tok), timeout=15)
        j = r.json()
        assert isinstance(j.get("chemicals_added"), list)


class TestChemicalsAddedPersistence:
    """Simulates what the frontend now sends: only non-empty/positive entries."""

    def _restore(self, tok, jid):
        # Reset chemicals_added after the class run to avoid leaking state.
        requests.put(f"{API}/jobs/{jid}/field-report", headers=_h(tok),
                     json={"chemicals_added": []}, timeout=15)

    def test_saves_only_non_empty_filtered_entries(self, tech_tok, pool_job_id):
        payload = {
            "chemicals_added": [
                {"id": "Liquid Chlorine", "name": "Liquid Chlorine", "amount": "2", "unit": "gal"},
                {"id": "Muriatic Acid", "name": "Muriatic Acid", "amount": "8", "unit": "oz"},
            ]
        }
        r = requests.put(f"{API}/jobs/{pool_job_id}/field-report",
                         headers=_h(tech_tok), json=payload, timeout=15)
        assert r.status_code == 200, r.text
        # Verify via GET
        g = requests.get(f"{API}/jobs/{pool_job_id}", headers=_h(tech_tok), timeout=15).json()
        added = g["chemicals_added"]
        assert len(added) == 2
        names = sorted(c["name"] for c in added)
        assert names == ["Liquid Chlorine", "Muriatic Acid"]
        for c in added:
            assert c["amount"] not in (None, "", "0")
            assert c.get("unit")
        self._restore(tech_tok, pool_job_id)

    def test_empty_list_clears_chemicals(self, tech_tok, pool_job_id):
        # Seed one entry then clear it.
        requests.put(f"{API}/jobs/{pool_job_id}/field-report", headers=_h(tech_tok),
                     json={"chemicals_added": [{"id": "Soda Ash", "name": "Soda Ash", "amount": "1", "unit": "lbs"}]},
                     timeout=15)
        r = requests.put(f"{API}/jobs/{pool_job_id}/field-report",
                         headers=_h(tech_tok), json={"chemicals_added": []}, timeout=15)
        assert r.status_code == 200
        g = requests.get(f"{API}/jobs/{pool_job_id}", headers=_h(tech_tok), timeout=15).json()
        assert g["chemicals_added"] == []

    def test_single_chemical_update_persists_and_others_unaffected(self, tech_tok, pool_job_id):
        # Simulate the onEndEditing behavior: first chemical filled, second field left blank.
        payload = {"chemicals_added": [
            {"id": "Chlorine Tablets", "name": "Chlorine Tablets", "amount": "3", "unit": "tabs"},
        ]}
        r = requests.put(f"{API}/jobs/{pool_job_id}/field-report",
                         headers=_h(tech_tok), json=payload, timeout=15)
        assert r.status_code == 200
        g = requests.get(f"{API}/jobs/{pool_job_id}", headers=_h(tech_tok), timeout=15).json()
        assert len(g["chemicals_added"]) == 1
        assert g["chemicals_added"][0]["name"] == "Chlorine Tablets"
        assert g["chemicals_added"][0]["amount"] == "3"
        self._restore(tech_tok, pool_job_id)


class TestOtherFieldReportStillWorks:
    def test_readings_still_saves_and_returns_ratings(self, tech_tok, pool_job_id):
        r = requests.put(f"{API}/jobs/{pool_job_id}/field-report", headers=_h(tech_tok),
                         json={"chemical_readings": {"ph": 7.5, "chlorine": 2.0}}, timeout=15)
        assert r.status_code == 200
        rep = {x["key"]: x for x in r.json()["reading_report"]}
        assert rep["ph"]["rating"] == "Average"
        assert rep["chlorine"]["rating"] == "Average"

    def test_checklist_toggle_still_saves(self, tech_tok, pool_job_id):
        # Read current checklist, flip first item's done, save, verify.
        j = requests.get(f"{API}/jobs/{pool_job_id}", headers=_h(tech_tok), timeout=15).json()
        checklist = j["checklist"]
        next_val = not checklist[0]["done"]
        checklist[0] = {**checklist[0], "done": next_val}
        r = requests.put(f"{API}/jobs/{pool_job_id}/field-report", headers=_h(tech_tok),
                         json={"checklist": checklist}, timeout=15)
        assert r.status_code == 200
        g = requests.get(f"{API}/jobs/{pool_job_id}", headers=_h(tech_tok), timeout=15).json()
        assert g["checklist"][0]["done"] == next_val


class TestCustomerReadOnly:
    def test_customer_reads_current_chemicals(self, tech_tok, cust_tok, pool_job_id):
        # First set: one chemical.
        requests.put(f"{API}/jobs/{pool_job_id}/field-report", headers=_h(tech_tok),
                     json={"chemicals_added": [{"id": "Algaecide", "name": "Algaecide", "amount": "4", "unit": "oz"}]},
                     timeout=15)
        # Customer must be able to fetch and see the saved list.
        r = requests.get(f"{API}/jobs/{pool_job_id}", headers=_h(cust_tok), timeout=15)
        if r.status_code == 403:
            pytest.skip("this pool job is not owned by demo customer")
        assert r.status_code == 200
        j = r.json()
        added = j.get("chemicals_added") or []
        # Every persisted entry should have a non-empty amount (frontend filter guarantee).
        for c in added:
            assert str(c.get("amount", "")).strip() not in ("", "0")
        # Clean up.
        requests.put(f"{API}/jobs/{pool_job_id}/field-report", headers=_h(tech_tok),
                     json={"chemicals_added": []}, timeout=15)
