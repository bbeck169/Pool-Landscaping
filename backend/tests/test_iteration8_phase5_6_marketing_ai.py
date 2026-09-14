"""
Iteration 8 — Phase 5 (Marketing) + Phase 6 (Admin: AI Employees, Access Settings) tests.

Covers:
- Forms: GET/POST admin-only, POST /forms/{id}/submit PUBLIC creates a lead
- Automations: GET/POST/PUT admin-only, toggle active
- Campaigns: GET/POST admin-only, POST sets sent_count = customer count
- Reviews: GET returns {items,average,count}; POST + PUT respond admin-only
- Check-ins: GET admin-only; POST allowed for technician + admin, 403 for customer
- Rank Grid: GET admin-only returns keywords with avg_rank & top3_pct
- AI Employees: GET admin-only (4 personas, no `system` leaked); chat returns real Claude reply
  and persists both messages; history returns them; invalid employee_id → 404
- Access Settings: GET returns {modules, matrix}; PUT persists changes
- RBAC: tech + customer get 403 on all admin-only endpoints (except tech POST /checkins)
"""

import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://pool-app-mobile.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


# ---------------- fixtures ----------------
def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def tech_token():
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def customer_token():
    return _login("customer@aquaterra.com")


def H(t): return {"Authorization": f"Bearer {t}"}


# ---------------- Forms ----------------
class TestForms:
    def test_list_forms_admin(self, admin_token):
        r = requests.get(f"{API}/forms", headers=H(admin_token), timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 2
        for f in data:
            assert "id" in f and "name" in f and "submissions" in f
            assert "_id" not in f

    def test_list_forms_forbidden_tech(self, tech_token):
        r = requests.get(f"{API}/forms", headers=H(tech_token), timeout=15)
        assert r.status_code == 403

    def test_list_forms_forbidden_customer(self, customer_token):
        r = requests.get(f"{API}/forms", headers=H(customer_token), timeout=15)
        assert r.status_code == 403

    def test_create_form_admin(self, admin_token):
        payload = {"name": "TEST_Iter8 Form", "description": "pytest", "fields": ["name", "email", "phone"]}
        r = requests.post(f"{API}/forms", headers=H(admin_token), json=payload, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["name"] == payload["name"] and d["submissions"] == 0
        assert "id" in d
        pytest.form_id = d["id"]

    def test_public_form_submit_creates_lead(self):
        # count leads before
        # public no-auth
        fid = pytest.form_id
        r = requests.post(f"{API}/forms/{fid}/submit",
                          json={"values": {"name": "TEST_Iter8 Lead", "email": "iter8@example.com",
                                           "phone": "555-1234", "message": "pytest submission"}}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True and d.get("lead_created") is True

    def test_public_form_submit_bumps_submission_count(self, admin_token):
        r = requests.get(f"{API}/forms", headers=H(admin_token), timeout=15)
        assert r.status_code == 200
        form = next((f for f in r.json() if f["id"] == pytest.form_id), None)
        assert form is not None
        assert form["submissions"] >= 1

    def test_public_form_submit_lead_visible_in_leads(self, admin_token):
        r = requests.get(f"{API}/leads", headers=H(admin_token), timeout=15)
        assert r.status_code == 200
        leads = r.json()
        match = [l for l in leads if l.get("name") == "TEST_Iter8 Lead"]
        assert match, "Lead created via public form-submit not found"
        assert match[0].get("email") == "iter8@example.com"

    def test_public_form_submit_404_unknown(self):
        r = requests.post(f"{API}/forms/nonexistent-id/submit", json={"values": {}}, timeout=15)
        assert r.status_code == 404


# ---------------- Automations ----------------
class TestAutomations:
    def test_list_automations_admin(self, admin_token):
        r = requests.get(f"{API}/automations", headers=H(admin_token), timeout=15)
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list) and len(arr) >= 3
        for a in arr:
            assert "id" in a and "name" in a and "active" in a
            assert "_id" not in a

    def test_list_automations_forbidden_tech(self, tech_token):
        assert requests.get(f"{API}/automations", headers=H(tech_token), timeout=15).status_code == 403

    def test_list_automations_forbidden_customer(self, customer_token):
        assert requests.get(f"{API}/automations", headers=H(customer_token), timeout=15).status_code == 403

    def test_create_and_toggle_automation(self, admin_token):
        payload = {"name": "TEST_Iter8 Automation", "trigger": "lead_created",
                   "action": "send_welcome_sms", "active": True}
        r = requests.post(f"{API}/automations", headers=H(admin_token), json=payload, timeout=15)
        assert r.status_code == 200
        d = r.json()
        aid = d["id"]
        assert d["active"] is True
        # toggle off
        r2 = requests.put(f"{API}/automations/{aid}", headers=H(admin_token), json={"active": False}, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["active"] is False


# ---------------- Campaigns ----------------
class TestCampaigns:
    def test_list_campaigns_admin(self, admin_token):
        r = requests.get(f"{API}/campaigns", headers=H(admin_token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_forbidden_tech_customer(self, tech_token, customer_token):
        assert requests.get(f"{API}/campaigns", headers=H(tech_token), timeout=15).status_code == 403
        assert requests.get(f"{API}/campaigns", headers=H(customer_token), timeout=15).status_code == 403

    def test_create_campaign_sent_count_equals_customer_count(self, admin_token):
        cust_count = len(requests.get(f"{API}/customers", headers=H(admin_token), timeout=15).json())
        payload = {"channel": "email", "subject": "TEST_Iter8 Campaign",
                   "body": "pytest hello", "audience": "all_customers"}
        r = requests.post(f"{API}/campaigns", headers=H(admin_token), json=payload, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "sent"
        assert d["sent_count"] == cust_count, f"sent_count {d['sent_count']} != customer count {cust_count}"


# ---------------- Reviews ----------------
class TestReviews:
    def test_list_reviews_shape(self, admin_token):
        r = requests.get(f"{API}/reviews", headers=H(admin_token), timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert set(["items", "average", "count"]).issubset(d.keys())
        assert isinstance(d["items"], list)
        assert d["count"] == len(d["items"])
        # average sanity
        if d["count"]:
            calc = round(sum(x["rating"] for x in d["items"]) / d["count"], 1)
            assert d["average"] == calc

    def test_forbidden_tech_customer(self, tech_token, customer_token):
        assert requests.get(f"{API}/reviews", headers=H(tech_token), timeout=15).status_code == 403
        assert requests.get(f"{API}/reviews", headers=H(customer_token), timeout=15).status_code == 403

    def test_create_and_respond(self, admin_token):
        payload = {"customer_name": "TEST_Iter8 Reviewer", "rating": 5,
                   "text": "pytest review", "source": "Google"}
        r = requests.post(f"{API}/reviews", headers=H(admin_token), json=payload, timeout=15)
        assert r.status_code == 200
        d = r.json()
        rid = d["id"]
        assert d["response"] is None
        r2 = requests.put(f"{API}/reviews/{rid}/respond", headers=H(admin_token),
                          json={"response": "Thanks!"}, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["response"] == "Thanks!"


# ---------------- Check-ins ----------------
class TestCheckins:
    def test_list_checkins_admin(self, admin_token):
        r = requests.get(f"{API}/checkins", headers=H(admin_token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_checkins_forbidden_tech_customer(self, tech_token, customer_token):
        assert requests.get(f"{API}/checkins", headers=H(tech_token), timeout=15).status_code == 403
        assert requests.get(f"{API}/checkins", headers=H(customer_token), timeout=15).status_code == 403

    def test_post_checkin_technician_allowed(self, tech_token):
        # Feb-2026 · Technician Check-In flow — the endpoint now
        # enforces ``job_id`` + ``photo_file_ids`` (min 1). The
        # legacy shape (address+lat+lng+note) is rejected with 422
        # so a mobile client that forgets to upload a photo first
        # gets a clear validation error, not a silent no-op.
        payload = {"address": "TEST_Iter8 Site",
                    "lat": 33.7, "lng": -112.3, "note": "pytest check-in"}
        r = requests.post(f"{API}/checkins", headers=H(tech_token),
                            json=payload, timeout=15)
        assert r.status_code == 422, r.text

    def test_post_checkin_admin_allowed(self, admin_token):
        # Same as above — RBAC lets admin through but the tightened
        # payload contract rejects the legacy shape with 422.
        r = requests.post(f"{API}/checkins", headers=H(admin_token),
                          json={"address": "TEST_Iter8 Admin",
                                 "lat": 33.7, "lng": -112.3,
                                 "note": "admin"}, timeout=15)
        assert r.status_code == 422, r.text

    def test_post_checkin_customer_forbidden(self, customer_token):
        # RBAC still short-circuits before the validator, so
        # customers get 403 regardless of payload shape.
        r = requests.post(f"{API}/checkins", headers=H(customer_token),
                          json={"address": "x", "lat": 0, "lng": 0}, timeout=15)
        assert r.status_code == 403


# ---------------- Rank Grid ----------------
class TestRankGrid:
    def test_rank_grid_admin(self, admin_token):
        r = requests.get(f"{API}/rank-grid", headers=H(admin_token), timeout=15)
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list) and len(arr) >= 1
        for k in arr:
            assert "keyword" in k and "grid" in k and "avg_rank" in k and "top3_pct" in k
            assert 0 <= k["top3_pct"] <= 100
            assert k["avg_rank"] >= 0

    def test_forbidden_tech_customer(self, tech_token, customer_token):
        assert requests.get(f"{API}/rank-grid", headers=H(tech_token), timeout=15).status_code == 403
        assert requests.get(f"{API}/rank-grid", headers=H(customer_token), timeout=15).status_code == 403


# ---------------- AI Employees ----------------
class TestAIEmployees:
    def test_list_ai_employees_admin(self, admin_token):
        r = requests.get(f"{API}/ai-employees", headers=H(admin_token), timeout=15)
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list) and len(arr) == 4
        ids = {e["id"] for e in arr}
        assert ids == {"sales", "support", "ops", "marketing"}
        for e in arr:
            assert "system" not in e, "system prompt should not be leaked"
            assert e["name"] and e["role"] and e["tagline"]

    def test_list_ai_employees_forbidden(self, tech_token, customer_token):
        assert requests.get(f"{API}/ai-employees", headers=H(tech_token), timeout=15).status_code == 403
        assert requests.get(f"{API}/ai-employees", headers=H(customer_token), timeout=15).status_code == 403

    def test_ai_chat_invalid_employee_404(self, admin_token):
        r = requests.post(f"{API}/ai-employees/chat", headers=H(admin_token),
                          json={"employee_id": "nonexistent", "message": "hi"}, timeout=30)
        assert r.status_code == 404

    def test_ai_chat_forbidden_tech(self, tech_token):
        r = requests.post(f"{API}/ai-employees/chat", headers=H(tech_token),
                          json={"employee_id": "sales", "message": "hi"}, timeout=30)
        assert r.status_code == 403

    def test_ai_chat_real_claude_reply(self, admin_token):
        session_id = f"pytest-iter8-{int(time.time())}"
        payload = {"employee_id": "sales", "message": "Say hi in 5 words.", "session_id": session_id}
        r = requests.post(f"{API}/ai-employees/chat", headers=H(admin_token), json=payload, timeout=60)
        assert r.status_code == 200, f"status {r.status_code} body {r.text}"
        d = r.json()
        assert d["session_id"] == session_id
        assert isinstance(d["reply"], str) and len(d["reply"]) > 0
        pytest.ai_session_id = session_id

    def test_ai_history_persists(self, admin_token):
        sid = pytest.ai_session_id
        r = requests.get(f"{API}/ai-employees/sales/history", headers=H(admin_token),
                         params={"session_id": sid}, timeout=15)
        assert r.status_code == 200
        msgs = r.json()
        assert isinstance(msgs, list) and len(msgs) >= 2
        roles = [m["role"] for m in msgs]
        assert "user" in roles and "assistant" in roles


# ---------------- Access Settings ----------------
class TestAccessSettings:
    def test_get_access_settings_admin(self, admin_token):
        r = requests.get(f"{API}/access-settings", headers=H(admin_token), timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "modules" in d and "matrix" in d
        assert isinstance(d["modules"], list) and len(d["modules"]) >= 1
        assert "technician" in d["matrix"] and "customer" in d["matrix"]

    def test_forbidden(self, tech_token, customer_token):
        assert requests.get(f"{API}/access-settings", headers=H(tech_token), timeout=15).status_code == 403
        assert requests.get(f"{API}/access-settings", headers=H(customer_token), timeout=15).status_code == 403

    def test_put_access_settings_persists(self, admin_token):
        # flip technician.marketing to True
        r = requests.put(f"{API}/access-settings", headers=H(admin_token),
                         json={"role": "technician", "module": "marketing", "enabled": True}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["matrix"]["technician"]["marketing"] is True
        # verify persistence via GET
        r2 = requests.get(f"{API}/access-settings", headers=H(admin_token), timeout=15)
        assert r2.status_code == 200
        assert r2.json()["matrix"]["technician"]["marketing"] is True
        # reset to False for hygiene
        requests.put(f"{API}/access-settings", headers=H(admin_token),
                     json={"role": "technician", "module": "marketing", "enabled": False}, timeout=15)
