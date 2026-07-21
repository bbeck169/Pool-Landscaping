"""
Slice M + K RBAC + pricing leak smoke tests.
Verifies:
- login works for admin/tech/customer
- /api/workstream/jobs enforces tech scoping (tech_id override ignored) and blocks customer
- /api/jobs/{jid}/detail strips pricing fields for technicians
- admin sees job_totals + internal_notes fields
"""
import os
import json
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://poolscape-audit.preview.emergentagent.com").rstrip("/")

FORBIDDEN_TECH_KEYS = {"job_totals", "unit_price", "subtotal", "tax_rate", "cost", "internal_notes"}


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:200]}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"no token in login response: {data}"
    return tok


@pytest.fixture(scope="module")
def admin_token():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def tech_token():
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def customer_token():
    return _login("customer@aquaterra.com")


def _headers(tok):
    return {"Authorization": f"Bearer {tok}"}


def _deep_find_keys(obj, forbidden):
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in forbidden:
                hits.append(k)
            hits.extend(_deep_find_keys(v, forbidden))
    elif isinstance(obj, list):
        for it in obj:
            hits.extend(_deep_find_keys(it, forbidden))
    return hits


class TestWorkstreamRBAC:
    def test_login_all_roles(self, admin_token, tech_token, customer_token):
        assert admin_token and tech_token and customer_token

    def test_admin_workstream_list(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/workstream/jobs", headers=_headers(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        # Accept dict with jobs or list
        jobs = data.get("jobs", data) if isinstance(data, dict) else data
        assert isinstance(jobs, list)
        assert len(jobs) > 0, "expected admin to see >0 jobs"

    def test_customer_workstream_forbidden(self, customer_token):
        r = requests.get(f"{BASE_URL}/api/workstream/jobs", headers=_headers(customer_token), timeout=30)
        assert r.status_code == 403, f"expected 403 for customer, got {r.status_code}: {r.text[:200]}"

    def test_tech_workstream_scoped(self, tech_token):
        r = requests.get(f"{BASE_URL}/api/workstream/jobs", headers=_headers(tech_token), timeout=30)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        jobs = data.get("jobs", data) if isinstance(data, dict) else data
        assert isinstance(jobs, list)
        # collect tech ids in response
        tech_ids = set()
        for j in jobs:
            tid = j.get("technician_id") or j.get("assigned_to") or j.get("assigned_technician_id")
            if tid:
                tech_ids.add(tid)
        # should all resolve to mike (single tech scope)
        assert len(tech_ids) <= 1, f"tech saw multiple technician_ids: {tech_ids}"

    def test_tech_cannot_override_tech_id(self, tech_token):
        # Try to spy on another tech via tech_id query param
        r = requests.get(f"{BASE_URL}/api/workstream/jobs?tech_id=SOME_OTHER_ID", headers=_headers(tech_token), timeout=30)
        assert r.status_code == 200
        data = r.json()
        jobs = data.get("jobs", data) if isinstance(data, dict) else data
        # should be filtered to mike, not empty (unless mike has 0), and shouldn't contain other tech
        tech_ids = {j.get("technician_id") or j.get("assigned_to") or j.get("assigned_technician_id") for j in jobs}
        tech_ids.discard(None)
        assert "SOME_OTHER_ID" not in tech_ids


class TestJobDetailPricingLeak:
    @pytest.fixture(scope="class")
    def a_job_id(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/workstream/jobs", headers=_headers(admin_token), timeout=30)
        assert r.status_code == 200
        data = r.json()
        jobs = data.get("jobs", data) if isinstance(data, dict) else data
        assert jobs, "no jobs available for admin"
        return jobs[0].get("id") or jobs[0].get("job_id") or jobs[0].get("_id")

    @pytest.fixture(scope="class")
    def tech_job_id(self, tech_token):
        r = requests.get(f"{BASE_URL}/api/workstream/jobs", headers=_headers(tech_token), timeout=30)
        assert r.status_code == 200
        data = r.json()
        jobs = data.get("jobs", data) if isinstance(data, dict) else data
        assert jobs, "no jobs available for tech"
        return jobs[0].get("id") or jobs[0].get("job_id") or jobs[0].get("_id")

    def test_admin_detail_has_pricing(self, admin_token, a_job_id):
        r = requests.get(f"{BASE_URL}/api/jobs/{a_job_id}/detail", headers=_headers(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:500]
        data = r.json()
        # Sections
        assert "sections" in data or "header" in data
        sections = data.get("sections", data)
        # job_totals may be null, but the *key* should exist somewhere for admin
        raw = json.dumps(data)
        assert "job_totals" in raw, "admin detail missing job_totals field"
        assert "internal_notes" in raw, "admin detail missing internal_notes field"

    def test_tech_detail_no_pricing_leak(self, tech_token, tech_job_id):
        r = requests.get(f"{BASE_URL}/api/jobs/{tech_job_id}/detail", headers=_headers(tech_token), timeout=30)
        assert r.status_code == 200, r.text[:500]
        data = r.json()
        raw = json.dumps(data)
        # Deep key scan
        hits = _deep_find_keys(data, FORBIDDEN_TECH_KEYS)
        assert not hits, f"pricing/internal keys leaked to tech: {hits}"
        # Also string scan
        for banned in ["job_totals", "unit_price", "tax_rate", "internal_notes"]:
            assert banned not in raw, f"forbidden string '{banned}' present in tech job detail response"

    def test_tech_detail_sections_shape(self, tech_token, tech_job_id):
        r = requests.get(f"{BASE_URL}/api/jobs/{tech_job_id}/detail", headers=_headers(tech_token), timeout=30)
        assert r.status_code == 200
        data = r.json()
        sections = data.get("sections", data)
        expected = {"header", "media", "line_items", "notes", "checklist", "forms", "timeline"}
        present = set(sections.keys()) if isinstance(sections, dict) else set()
        missing = expected - present
        assert not missing, f"tech detail missing sections: {missing}; got {present}"
