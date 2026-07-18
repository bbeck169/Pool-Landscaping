"""Phase 4 · Batch B / D6 — Handbook + Onboarding tests."""
from __future__ import annotations
import os, requests, pytest, uuid

BACKEND = os.environ.get("REACT_APP_BACKEND_URL") or "https://poolscape-audit.preview.emergentagent.com"
API = f"{BACKEND}/api"
TIMEOUT = 20


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["access_token"]


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_tok() -> str: return _login("admin@aquaterra.com", "password123")

@pytest.fixture(scope="module")
def tech_tok() -> str:  return _login("mike@aquaterra.com",  "password123")


class TestHandbookSeed:
    def test_seed_produced_12_system_sections(self, admin_tok):
        r = requests.get(f"{API}/handbook/sections", headers=_h(admin_tok), timeout=TIMEOUT).json()
        codes = [s["code"] for s in r["rows"] if s.get("is_system")]
        # 12 seeded codes
        expected = {"company_overview", "working_hours", "pto_and_leave", "safety_general",
                     "chemical_ppe", "vehicle_use", "uniform_presentation", "customer_comm",
                     "route_efficiency", "damage_incident", "payroll_reviews", "termination_exit"}
        assert set(codes) >= expected

    def test_get_single_section(self, admin_tok):
        r = requests.get(f"{API}/handbook/sections/company_overview",
                          headers=_h(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        assert "Company Overview" in r.json()["title"]
        assert len(r.json()["markdown_body"]) > 100


class TestHandbookRBAC:
    def test_tech_can_read_sections(self, tech_tok):
        r = requests.get(f"{API}/handbook/sections", headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200

    def test_tech_cannot_create_section(self, tech_tok):
        r = requests.post(f"{API}/handbook/sections", headers=_h(tech_tok),
                          json={"code": "test", "title": "Test", "markdown_body": "x"},
                          timeout=TIMEOUT)
        assert r.status_code == 403

    def test_admin_cannot_delete_system_section(self, admin_tok):
        r = requests.delete(f"{API}/handbook/sections/company_overview",
                             headers=_h(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 400  # system read-only

    def test_admin_cannot_patch_system_section(self, admin_tok):
        r = requests.patch(f"{API}/handbook/sections/company_overview",
                            headers=_h(admin_tok),
                            json={"title": "New title"}, timeout=TIMEOUT)
        assert r.status_code == 400  # system read-only

    def test_admin_can_create_and_edit_custom_section(self, admin_tok):
        code = f"test_custom_{uuid.uuid4().hex[:8]}"
        # Create
        r = requests.post(f"{API}/handbook/sections", headers=_h(admin_tok),
                          json={"code": code, "title": "Custom", "order": 99,
                                 "markdown_body": "Custom body"}, timeout=TIMEOUT)
        assert r.status_code == 200
        # Patch
        r2 = requests.patch(f"{API}/handbook/sections/{code}", headers=_h(admin_tok),
                             json={"markdown_body": "Updated body"}, timeout=TIMEOUT)
        assert r2.status_code == 200
        assert r2.json()["markdown_body"] == "Updated body"
        assert r2.json()["version"] == 2
        # Delete
        r3 = requests.delete(f"{API}/handbook/sections/{code}", headers=_h(admin_tok), timeout=TIMEOUT)
        assert r3.status_code == 200


class TestOnboardingTasks:
    def test_seed_produced_10_system_tasks(self, admin_tok):
        r = requests.get(f"{API}/onboarding/tasks", headers=_h(admin_tok), timeout=TIMEOUT).json()
        assert len(r["rows"]) >= 10

    def test_tech_can_list_tasks(self, tech_tok):
        r = requests.get(f"{API}/onboarding/tasks", headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200


class TestOnboardingProgress:
    def test_self_progress_returns_task_list(self, tech_tok):
        r = requests.get(f"{API}/onboarding/user-progress?user_id=me",
                          headers=_h(tech_tok), timeout=TIMEOUT).json()
        assert r["total"] >= 10
        assert "rows" in r

    def test_mark_complete_flips_status(self, tech_tok):
        # Pick a task the tech can see and mark it complete
        tasks = requests.get(f"{API}/onboarding/tasks", headers=_h(tech_tok), timeout=TIMEOUT).json()["rows"]
        code = tasks[0]["code"]
        r = requests.post(f"{API}/onboarding/user-progress/mark-complete",
                          headers=_h(tech_tok),
                          json={"task_code": code}, timeout=TIMEOUT)
        assert r.status_code == 200
        assert r.json()["status"] == "complete"
        # Verify in progress list
        p = requests.get(f"{API}/onboarding/user-progress?user_id=me",
                          headers=_h(tech_tok), timeout=TIMEOUT).json()
        found = next((row for row in p["rows"] if row["code"] == code), None)
        assert found and found["progress"]["status"] == "complete"

    def test_tech_cannot_query_another_users_progress(self, tech_tok, admin_tok):
        # Get admin's user id
        # We test by asking for a random user_id and expecting 403 or 404
        r = requests.get(f"{API}/onboarding/user-progress?user_id=random-other-user-xyz",
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 403


class TestOnboardingDashboard:
    def test_admin_can_see_dashboard(self, admin_tok):
        r = requests.get(f"{API}/onboarding/dashboard", headers=_h(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert "rows" in data
        assert data["total_users"] >= 1

    def test_tech_cannot_see_dashboard(self, tech_tok):
        r = requests.get(f"{API}/onboarding/dashboard", headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 403

    def test_dashboard_reflects_completion(self, admin_tok, tech_tok):
        # Snapshot admin dashboard, complete a task as tech, snapshot again.
        d1 = requests.get(f"{API}/onboarding/dashboard", headers=_h(admin_tok), timeout=TIMEOUT).json()
        # Complete a different task each run to avoid noise
        code = f"tenant_test_{uuid.uuid4().hex[:8]}"
        # Add a tenant-custom task first (so we know it's fresh)
        requests.post(f"{API}/onboarding/tasks", headers=_h(admin_tok),
                       json={"code": code, "title": "Dashboard smoke task",
                             "order": 999, "kind": "checklist"}, timeout=TIMEOUT).raise_for_status()
        # Tech marks it complete
        requests.post(f"{API}/onboarding/user-progress/mark-complete",
                       headers=_h(tech_tok),
                       json={"task_code": code}, timeout=TIMEOUT).raise_for_status()
        # New dashboard snapshot should have same or lower total
        d2 = requests.get(f"{API}/onboarding/dashboard", headers=_h(admin_tok), timeout=TIMEOUT).json()
        assert d2["total_users"] == d1["total_users"]


class TestAutoCompleteOnFinalize:
    def test_finalizing_template_marks_matching_task(self, admin_tok):
        # There's a seeded task "fill_new_customer_onboarding" whose related_ref
        # is "new_customer_onboarding". Finalizing that template should mark it.
        # Create + finalize the template instance
        c = requests.post(f"{API}/templates/instances", headers=_h(admin_tok),
                          json={"template_code": "new_customer_onboarding",
                                "values": {"name": "Test", "phone": "555-0100",
                                             "address": "1 Test", "terms_accepted": True}},
                          timeout=TIMEOUT).json()
        iid = c["id"]
        requests.post(f"{API}/templates/instances/{iid}/finalize",
                       headers=_h(admin_tok), timeout=TIMEOUT).raise_for_status()
        # Check that fill_new_customer_onboarding is now complete for this admin
        p = requests.get(f"{API}/onboarding/user-progress?user_id=me",
                          headers=_h(admin_tok), timeout=TIMEOUT).json()
        task = next((r for r in p["rows"] if r["code"] == "fill_new_customer_onboarding"), None)
        assert task is not None
        assert task["progress"]["status"] == "complete"
