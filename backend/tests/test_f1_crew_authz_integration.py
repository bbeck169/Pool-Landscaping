"""Phase F1 integration tests (live HTTP, preview URL).

Covers:
  * P0-B — crew-membership authorization across every refactored tech
    gate (jobs.py, workstream_job_detail.py, job_media_line_items.py,
    maintenance.py, service_reports.py).
  * P0-A — portal service-request identity sourcing.

Seeds crew-only jobs directly into MongoDB (the crews API surface is
admin-only and the demo dataset ships only two crews), then drives the
public HTTP surface with a real technician JWT.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

frontend_env = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or frontend_env.get("REACT_APP_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"

backend_env = dotenv_values("/app/backend/.env")
MONGO_URL = backend_env["MONGO_URL"]
DB_NAME = backend_env["DB_NAME"]

TENANT = "affdfbfa-88b9-4baa-ae45-2ef78531b6e4"
BLUE_CREW = "10851a3d-1321-4d9e-99af-0096325a7652"   # mike + carlos
GREEN_CREW = "1c1ec59e-6733-4064-ad10-c5f0f753ae4a"  # neither
CARLOS_TECH_ID = "cc683510-b8f9-4762-b571-d1b389be8080"
MIKE_TECH_ID = "b8a68119-7dc6-46dd-9e24-447ca230bfde"
CUSTOMER_ID = "8910bfde-3ba0-4b18-b54f-6ac5657af13d"

PREFIX = "TEST_F1_"


def _now():
    return datetime.now(tz=timezone.utc).isoformat()


def _login(email, password="password123"):
    """Retry once — the preview ingress intermittently drops the first
    TLS handshake of a fresh pytest process (observed ~2/6 runs)."""
    last = None
    for attempt in range(3):
        try:
            r = requests.post(f"{API}/auth/login",
                              json={"email": email, "password": password}, timeout=60)
            if r.status_code == 200:
                return r.json()["access_token"]
            last = f"{r.status_code} {r.text[:300]}"
        except requests.RequestException as exc:  # noqa: PERF203
            last = repr(exc)
    pytest.fail(f"login failed for {email} after 3 attempts: {last}")


# ── fixtures ──────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login('carlos@aquaterra.com')}"}


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


def _base_job(**over):
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": TENANT,
        "title": f"{PREFIX}job",
        "customer_id": CUSTOMER_ID,
        "customer_name": "Jennifer Carson",
        "address": "12 Vistancia Blvd, Peoria, AZ",
        "service_type": "Pool Cleaning",
        "scheduled_date": datetime.now(tz=timezone.utc).date().isoformat(),
        "status": "scheduled",
        "technician_id": None,
        "crew_id": None,
        "price": 100.0,
        "created_at": _now(),
        "photos": [],
        "service_issues": [],
    }
    doc.update(over)
    return doc


@pytest.fixture(scope="module")
def jobs(mongo):
    """Seed the four authorization scenarios + specials."""
    crew_only = _base_job(crew_id=BLUE_CREW, title=f"{PREFIX}crew_only")
    crew_teammate = _base_job(crew_id=BLUE_CREW, technician_id=MIKE_TECH_ID,
                              technician_name="Mike Rivera",
                              title=f"{PREFIX}crew_teammate")
    other_crew = _base_job(crew_id=GREEN_CREW, title=f"{PREFIX}other_crew")
    direct = _base_job(technician_id=CARLOS_TECH_ID, technician_name="Carlos",
                       title=f"{PREFIX}direct")
    completed = _base_job(crew_id=BLUE_CREW, status="completed",
                          completed_at=_now(), title=f"{PREFIX}completed_crew")
    maint = _base_job(crew_id=BLUE_CREW, service_type="Filter Cleaning",
                      maintenance_type="filter", title=f"{PREFIX}maint_crew")
    docs = {
        "crew_only": crew_only, "crew_teammate": crew_teammate,
        "other_crew": other_crew, "direct": direct,
        "completed": completed, "maint": maint,
    }
    mongo.jobs.insert_many([dict(d) for d in docs.values()])
    yield {k: v["id"] for k, v in docs.items()}
    mongo.jobs.delete_many({"id": {"$in": [v["id"] for v in docs.values()]}})
    mongo.service_reports.delete_many({"job_id": {"$in": [v["id"] for v in docs.values()]}})


# ── P0-B · GET /api/jobs/{jid} ────────────────────────────────────────
class TestJobDetailCrewAuthz:
    def test_crew_only_job_returns_200(self, tech_headers, jobs):
        r = requests.get(f"{API}/jobs/{jobs['crew_only']}", headers=tech_headers, timeout=30)
        assert r.status_code == 200, r.text[:400]
        assert r.json()["id"] == jobs["crew_only"]

    def test_crew_job_assigned_to_teammate_returns_200(self, tech_headers, jobs):
        r = requests.get(f"{API}/jobs/{jobs['crew_teammate']}", headers=tech_headers, timeout=30)
        assert r.status_code == 200, r.text[:400]

    def test_direct_assignee_still_200(self, tech_headers, jobs):
        r = requests.get(f"{API}/jobs/{jobs['direct']}", headers=tech_headers, timeout=30)
        assert r.status_code == 200, r.text[:400]

    def test_non_member_crew_job_still_403(self, tech_headers, jobs):
        r = requests.get(f"{API}/jobs/{jobs['other_crew']}", headers=tech_headers, timeout=30)
        assert r.status_code == 403, r.text[:400]

    def test_workstream_detail_crew_only_200(self, tech_headers, jobs):
        r = requests.get(f"{API}/jobs/{jobs['crew_only']}/detail", headers=tech_headers, timeout=30)
        assert r.status_code == 200, r.text[:400]

    def test_workstream_detail_non_member_403(self, tech_headers, jobs):
        r = requests.get(f"{API}/jobs/{jobs['other_crew']}/detail", headers=tech_headers, timeout=30)
        assert r.status_code == 403, r.text[:400]

    def test_work_order_pdf_crew_only_not_403(self, tech_headers, jobs):
        r = requests.get(f"{API}/jobs/{jobs['crew_only']}/work-order.pdf",
                         headers=tech_headers, timeout=60)
        assert r.status_code != 403, r.text[:300]

    def test_job_edits_crew_only_not_403(self, tech_headers, jobs):
        r = requests.get(f"{API}/jobs/{jobs['crew_only']}/edits", headers=tech_headers, timeout=30)
        assert r.status_code != 403, r.text[:300]


# ── Schedule ↔ detail parity ──────────────────────────────────────────
class TestScheduleDetailParity:
    def test_schedule_includes_crew_only_job(self, tech_headers, jobs):
        r = requests.get(f"{API}/jobs", headers=tech_headers, timeout=60)
        assert r.status_code == 200, r.text[:300]
        payload = r.json()
        rows = payload if isinstance(payload, list) else payload.get("jobs", [])
        ids = {j["id"] for j in rows}
        assert jobs["crew_only"] in ids, "crew-only job missing from tech schedule"
        assert jobs["other_crew"] not in ids, "non-member crew job leaked into schedule"

    def test_every_scheduled_job_opens_in_detail(self, tech_headers):
        r = requests.get(f"{API}/jobs", headers=tech_headers, timeout=60)
        assert r.status_code == 200
        payload = r.json()
        rows = payload if isinstance(payload, list) else payload.get("jobs", [])
        forbidden = []
        for j in rows[:25]:
            d = requests.get(f"{API}/jobs/{j['id']}", headers=tech_headers, timeout=30)
            if d.status_code == 403:
                forbidden.append(j["id"])
        assert not forbidden, f"schedule surfaced jobs that 403 on detail: {forbidden}"


# ── Mutating tech gates ───────────────────────────────────────────────
class TestCrewMemberMutations:
    def test_field_report_put(self, tech_headers, jobs):
        r = requests.put(f"{API}/jobs/{jobs['crew_only']}/field-report",
                         headers=tech_headers,
                         json={"customer_notes": f"{PREFIX}note"}, timeout=60)
        assert r.status_code != 403, r.text[:300]
        assert r.status_code == 200, r.text[:300]

    def test_on_my_way(self, tech_headers, jobs):
        r = requests.post(f"{API}/jobs/{jobs['crew_only']}/on-my-way",
                          headers=tech_headers, json={}, timeout=60)
        assert r.status_code != 403, r.text[:300]

    def test_arrive(self, tech_headers, jobs):
        r = requests.post(f"{API}/jobs/{jobs['crew_only']}/arrive",
                          headers=tech_headers,
                          json={"lat": 33.7670356, "lng": -112.3397496}, timeout=60)
        assert r.status_code != 403, r.text[:400]

    def test_timer_undo_start(self, tech_headers, jobs):
        r = requests.post(f"{API}/jobs/{jobs['crew_only']}/timer/undo-start",
                          headers=tech_headers, json={}, timeout=60)
        assert r.status_code != 403, r.text[:400]

    def test_add_photo(self, tech_headers, jobs):
        png = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1"
               "HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
        r = requests.post(f"{API}/jobs/{jobs['crew_only']}/photos",
                          headers=tech_headers,
                          json={"data": png, "label": f"{PREFIX}photo"}, timeout=60)
        assert r.status_code != 403, r.text[:300]
        assert r.status_code in (200, 201), r.text[:300]

    def test_add_issue(self, tech_headers, jobs):
        r = requests.post(f"{API}/jobs/{jobs['crew_only']}/issues",
                          headers=tech_headers,
                          json={"description": f"{PREFIX}leaking valve"}, timeout=60)
        assert r.status_code != 403, r.text[:300]
        assert r.status_code in (200, 201), r.text[:300]

    def test_patch_edit_window_completed_crew_job(self, tech_headers, jobs):
        r = requests.patch(f"{API}/jobs/{jobs['completed']}",
                           headers=tech_headers,
                           json={"notes": f"{PREFIX}edit", "edit_reason": "qa"}, timeout=60)
        assert r.status_code != 403, r.text[:400]
        assert r.status_code == 200, r.text[:400]

    def test_patch_edit_window_non_member_still_403(self, tech_headers, mongo):
        doc = _base_job(crew_id=GREEN_CREW, status="completed", completed_at=_now(),
                        title=f"{PREFIX}completed_other")
        mongo.jobs.insert_one(dict(doc))
        try:
            r = requests.patch(f"{API}/jobs/{doc['id']}", headers=tech_headers,
                               json={"notes": "x"}, timeout=60)
            assert r.status_code == 403, r.text[:300]
        finally:
            mongo.jobs.delete_one({"id": doc["id"]})


# ── line items (job_media_line_items.py) ──────────────────────────────
class TestLineItemsCrewAuthz:
    @pytest.fixture(scope="class")
    def pricebook_item(self, mongo):
        it = mongo.items.find_one({"tenant_id": TENANT, "active": {"$ne": False}},
                                  {"_id": 0, "id": 1})
        if not it:
            it = mongo.items.find_one({}, {"_id": 0, "id": 1})
        if not it:
            pytest.skip("no pricebook item available in tenant")
        return it["id"]

    def test_get_line_items(self, tech_headers, jobs):
        r = requests.get(f"{API}/jobs/{jobs['crew_only']}/line-items",
                         headers=tech_headers, timeout=30)
        assert r.status_code != 403, r.text[:300]
        assert r.status_code == 200, r.text[:300]

    def test_post_patch_delete_line_item(self, tech_headers, jobs, pricebook_item):
        r = requests.post(f"{API}/jobs/{jobs['crew_only']}/line-items",
                          headers=tech_headers,
                          json={"pricebook_item_id": pricebook_item, "quantity": 2}, timeout=60)
        assert r.status_code != 403, r.text[:400]
        assert r.status_code in (200, 201), r.text[:400]
        body = r.json()
        # POST returns the created line-item row itself.
        lid = body.get("id") or (body.get("line_item") or {}).get("id")
        assert lid, f"no line-item id in response: {str(body)[:300]}"
        assert body.get("quantity") == 2.0, str(body)[:300]
        # Tech responses must be stripped of pricing.
        for banned in ("unit_price", "subtotal", "tax_rate", "cost"):
            assert banned not in body, f"pricing field {banned} leaked to tech"

        p = requests.patch(f"{API}/jobs/{jobs['crew_only']}/line-items/{lid}",
                           headers=tech_headers, json={"quantity": 3}, timeout=60)
        assert p.status_code != 403, p.text[:300]
        assert p.status_code == 200, p.text[:300]

        d = requests.delete(f"{API}/jobs/{jobs['crew_only']}/line-items/{lid}",
                            headers=tech_headers, timeout=60)
        assert d.status_code != 403, d.text[:300]
        assert d.status_code in (200, 204), d.text[:300]

    def test_non_member_line_items_403(self, tech_headers, jobs):
        r = requests.get(f"{API}/jobs/{jobs['other_crew']}/line-items",
                         headers=tech_headers, timeout=30)
        assert r.status_code == 403, r.text[:300]


# ── maintenance.py ────────────────────────────────────────────────────
class TestMaintenanceCrewAuthz:
    def test_maintenance_log_crew_member(self, tech_headers, jobs):
        r = requests.post(f"{API}/jobs/{jobs['maint']}/maintenance-log",
                          headers=tech_headers,
                          json={"psi": 12.5, "filter_condition": "good",
                                "notes": f"{PREFIX}maint"}, timeout=60)
        assert r.status_code != 403, r.text[:400]
        assert r.status_code in (200, 201), r.text[:400]

    def test_maintenance_log_non_member_403(self, tech_headers, mongo):
        doc = _base_job(crew_id=GREEN_CREW, service_type="Filter Cleaning",
                        maintenance_type="filter", title=f"{PREFIX}maint_other")
        mongo.jobs.insert_one(dict(doc))
        try:
            r = requests.post(f"{API}/jobs/{doc['id']}/maintenance-log",
                              headers=tech_headers, json={"psi": 10}, timeout=60)
            assert r.status_code == 403, r.text[:300]
        finally:
            mongo.jobs.delete_one({"id": doc["id"]})


# ── service_reports.py ────────────────────────────────────────────────
class TestServiceReportCrewAuthz:
    def test_get_and_patch_service_report(self, tech_headers, jobs):
        g = requests.get(f"{API}/jobs/{jobs['crew_only']}/service-report",
                         headers=tech_headers, timeout=60)
        assert g.status_code != 403, g.text[:400]
        assert g.status_code == 200, g.text[:400]

        p = requests.patch(f"{API}/jobs/{jobs['crew_only']}/service-report",
                           headers=tech_headers,
                           json={"notes": f"{PREFIX}sr note"}, timeout=60)
        assert p.status_code != 403, p.text[:400]
        assert p.status_code == 200, p.text[:400]

    def test_service_report_non_member_403(self, tech_headers, jobs):
        r = requests.get(f"{API}/jobs/{jobs['other_crew']}/service-report",
                         headers=tech_headers, timeout=30)
        assert r.status_code == 403, r.text[:300]


# ── P0-A · portal service requests ────────────────────────────────────
class TestPortalServiceRequest:
    def test_happy_path_persists_session_identity(self, customer_headers, mongo):
        marker = f"{PREFIX}marker-{uuid.uuid4().hex[:8]}"
        r = requests.post(f"{API}/customer-portal/service-requests",
                          headers=customer_headers,
                          json={"service_type": "Pool Cleaning",
                                "notes": marker,
                                # hostile body: must be ignored
                                "customer_id": "ATTACKER-CUSTOMER-ID"}, timeout=60)
        assert r.status_code == 200, r.text[:500]
        assert r.json().get("ok") is True, r.text[:300]

        msg = mongo.messages.find_one({"tenant_id": TENANT,
                                       "text": {"$regex": marker}}, {"_id": 0})
        assert msg is not None, "service request did not persist a message row"
        assert msg.get("customer_id") == CUSTOMER_ID, (
            f"customer_id came from body/stale session: {msg.get('customer_id')}")
        # P0-A: identity strings must come from the customers row.
        assert msg.get("sender_name") == "Jennifer Carson", msg.get("sender_name")
        assert "Jennifer Carson" in (msg.get("text") or ""), msg.get("text")
        assert msg["kind"] == "service_request"
        mongo.messages.delete_one({"id": msg["id"]})

    def test_customer_can_read_own_messages(self, customer_headers):
        r = requests.get(f"{API}/me/messages", headers=customer_headers, timeout=60)
        assert r.status_code == 200, r.text[:300]

    def test_admin_role_forbidden(self, admin_headers):
        r = requests.post(f"{API}/customer-portal/service-requests",
                          headers=admin_headers,
                          json={"service_type": "Pool Cleaning"}, timeout=30)
        assert r.status_code in (401, 403), f"admin got {r.status_code}: {r.text[:300]}"

    def test_technician_role_forbidden(self, tech_headers):
        r = requests.post(f"{API}/customer-portal/service-requests",
                          headers=tech_headers,
                          json={"service_type": "Pool Cleaning"}, timeout=30)
        assert r.status_code in (401, 403), f"tech got {r.status_code}: {r.text[:300]}"

    def test_anonymous_forbidden(self):
        r = requests.post(f"{API}/customer-portal/service-requests",
                          json={"service_type": "Pool Cleaning"}, timeout=30)
        assert r.status_code in (401, 403), f"anon got {r.status_code}: {r.text[:300]}"


def teardown_module(module):
    c = MongoClient(MONGO_URL)
    db = c[DB_NAME]
    db.jobs.delete_many({"title": {"$regex": f"^{PREFIX}"}})
    c.close()
