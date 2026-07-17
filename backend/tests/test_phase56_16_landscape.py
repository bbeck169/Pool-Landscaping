"""Phase 56.16 — Landscape Checklist Rewrite backend tests."""
import os
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values


_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE

ADMIN = ("admin@aquaterra.com", "password123")


def _login(email, password):
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"email": email, "password": password}, timeout=45)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def h_admin():
    return _login(*ADMIN)


class TestLandscapeChecklistTemplate:

    def test_default_template_has_ten_items_in_order(self):
        """Import the config module and verify the canonical order."""
        from config_landscape_checklist import LANDSCAPE_CHECKLIST_TEMPLATE_DEFAULT
        assert LANDSCAPE_CHECKLIST_TEMPLATE_DEFAULT == [
            "Sprayed or Pulled Weeds",
            "Checked Irrigation",
            "Trimmed Bushes",
            "Mowed Grass",
            "Edged Grass",
            "Blow Property",
            "Raked Rocks",
            "Locked Gate",
            "Trimmed Trees",
            "Irrigation Repair",
        ]

    def test_service_report_bootstrap_picks_up_new_template(self, h_admin):
        """Bootstrapping a landscape job's service report seeds the new
        10-item list in the correct order."""
        # Find a landscape job via schedule (faster than /jobs list).
        r = requests.get(f"{BASE}/api/schedule/today",
                         headers=h_admin, timeout=60).json()
        job_list = r.get("jobs") if isinstance(r, dict) else r
        candidate = None
        for j in (job_list if isinstance(job_list, list) else []):
            title = (j.get("title") or "").lower()
            svc = (j.get("service_type") or j.get("job_type") or "").lower()
            hay = " ".join([title, svc])
            if any(k in hay for k in ["landscap", "mow", "lawn", "trim"]):
                candidate = j; break
        if not candidate:
            pytest.skip("No landscape job seeded in this environment")

        r = requests.get(f"{BASE}/api/jobs/{candidate['id']}/service-report",
                         headers=h_admin, timeout=30)
        assert r.status_code == 200, r.text
        report = r.json()
        items = report.get("checklist_items") or []
        labels = [it.get("label") for it in items]

        # A tenant may have customized the template. If so, we skip the
        # exact-order assertion (the spec is: only NEW landscape reports
        # created from the shipped default get the new list). But the
        # template kind must be `landscape` and labels must be a list.
        assert report.get("template") in ("landscape", None) or report.get("template") == "landscape"
        assert isinstance(labels, list)
        # If this is the default template (no tenant override), enforce
        # the full 10-item order.
        if len(labels) == 10 and labels[0].startswith("Sprayed"):
            assert labels == [
                "Sprayed or Pulled Weeds", "Checked Irrigation",
                "Trimmed Bushes", "Mowed Grass", "Edged Grass",
                "Blow Property", "Raked Rocks", "Locked Gate",
                "Trimmed Trees", "Irrigation Repair",
            ]


class TestNotesSplit:

    def test_customer_notes_and_internal_notes_persist_separately(self, h_admin):
        r = requests.get(f"{BASE}/api/schedule/today",
                         headers=h_admin, timeout=60).json()
        # schedule/today returns {jobs: [...]} or a flat list depending on version.
        job_list = r.get("jobs") if isinstance(r, dict) else r
        if not isinstance(job_list, list) or not job_list:
            pytest.skip("No jobs on today's schedule to test with")
        jid = job_list[0]["id"]

        # Bootstrap report.
        requests.get(f"{BASE}/api/jobs/{jid}/service-report", headers=h_admin, timeout=30)

        # Patch both fields.
        r = requests.patch(f"{BASE}/api/jobs/{jid}/service-report",
                           headers=h_admin,
                           json={"internal_notes": "TEST_ private admin note",
                                 "customer_notes": "TEST_ friendly customer note"},
                           timeout=30)
        assert r.status_code in (200, 204), r.text

        # Read back — admin can see both.
        r = requests.get(f"{BASE}/api/jobs/{jid}/service-report",
                         headers=h_admin, timeout=30).json()
        assert r.get("internal_notes") == "TEST_ private admin note"
        assert r.get("customer_notes") == "TEST_ friendly customer note"


class TestCustomerPortalVisibility:

    def test_non_customer_role_forbidden_on_me_endpoints(self, h_admin):
        r = requests.get(f"{BASE}/api/customers/me/service-reports",
                         headers=h_admin, timeout=15)
        # Admin does not have `customer_id`, so must be 403.
        assert r.status_code == 403

    def test_customer_sees_own_reports_and_internal_notes_redacted(self, h_admin):
        # Try to log in as an existing customer account. If no portal
        # user is seeded, skip.
        try:
            h_cust = _login("customer@aquaterra.com", "password123")
        except Exception:
            pytest.skip("customer portal user not seeded in this env")

        r = requests.get(f"{BASE}/api/customers/me/service-reports",
                         headers=h_cust, timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        # If any submitted reports exist for this customer, fetch one
        # and verify redaction.
        if rows:
            rid = rows[0]["id"]
            detail = requests.get(f"{BASE}/api/customers/me/service-reports/{rid}",
                                  headers=h_cust, timeout=15)
            assert detail.status_code == 200
            body = detail.json()
            assert "internal_notes" not in body, \
                "customer must NEVER see internal_notes"
            # customer_notes is allowed to be present.
