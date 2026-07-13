"""Iteration 5 — Phase 2 web-mirroring: Leads, Team, Price Book (items), Payments.

Covers:
- GET/POST/PUT /api/leads and POST /api/leads/{id}/convert (admin-only; 403 for tech/customer)
- GET /api/team (admin-only)
- GET /api/items (Price Book — admin-only)
- GET /api/payments (admin-only)
- Regression: login for all 3 roles + /api/dashboard KPIs still load
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be set"

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}
CUST = {"email": "customer@aquaterra.com", "password": "password123"}


def _login(session: requests.Session, creds):
    r = session.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    body = r.json()
    assert "access_token" in body
    assert "user" in body and body["user"]["email"] == creds["email"]
    return body["access_token"], body["user"]


@pytest.fixture(scope="module")
def admin_headers():
    s = requests.Session()
    tok, _ = _login(s, ADMIN)
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def tech_headers():
    s = requests.Session()
    tok, _ = _login(s, TECH)
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def customer_headers():
    s = requests.Session()
    tok, _ = _login(s, CUST)
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# --------------------------- Regression: auth + dashboard ---------------------------
class TestAuthRegression:
    def test_admin_login(self):
        s = requests.Session()
        tok, u = _login(s, ADMIN)
        assert u["role"] == "admin"
        assert tok

    def test_tech_login(self):
        s = requests.Session()
        _, u = _login(s, TECH)
        assert u["role"] == "technician"

    def test_customer_login(self):
        s = requests.Session()
        _, u = _login(s, CUST)
        assert u["role"] == "customer"

    def test_dashboard_admin(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/dashboard", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        d = r.json()
        # admin KPIs include leads counters (phase-2 additions)
        assert "total_leads" in d
        assert "open_leads" in d
        assert isinstance(d["total_leads"], int)

    def test_dashboard_technician(self, tech_headers):
        r = requests.get(f"{BASE_URL}/api/dashboard", headers=tech_headers, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d.get("role") == "technician"
        # CRITICAL: technician dashboard must not leak any pricing
        for key in ("revenue", "total_revenue", "price", "amount"):
            assert key not in d, f"pricing key '{key}' leaked to technician dashboard"

    def test_dashboard_customer(self, customer_headers):
        r = requests.get(f"{BASE_URL}/api/dashboard", headers=customer_headers, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d.get("role") == "customer"


# --------------------------- Leads ---------------------------
class TestLeads:
    """Admin CRUD + conversion; 403 for tech/customer"""

    @pytest.fixture(scope="class")
    def created_lead_id(self, admin_headers):
        payload = {
            "name": "TEST_Iter5 Lead Alpha",
            "phone": "480-555-0101",
            "email": "test_iter5_alpha@example.com",
            "source": "Website",
            "notes": "Automated test lead",
            "est_value": 555.5,
        }
        r = requests.post(f"{BASE_URL}/api/leads", json=payload, headers=admin_headers, timeout=15)
        assert r.status_code == 200, f"POST /leads failed: {r.status_code} {r.text}"
        body = r.json()
        assert body["name"] == payload["name"]
        assert body["est_value"] == 555.5
        assert body.get("status") == "new"
        assert "id" in body
        assert "_id" not in body
        return body["id"]

    def test_list_leads_admin(self, admin_headers, created_lead_id):
        r = requests.get(f"{BASE_URL}/api/leads", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        leads = r.json()
        assert isinstance(leads, list)
        assert any(l["id"] == created_lead_id for l in leads)
        for l in leads:
            assert "_id" not in l

    def test_list_leads_filter_status(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/leads?status=new", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        for l in r.json():
            assert l["status"] == "new"

    def test_update_lead_status_and_persist(self, admin_headers, created_lead_id):
        r = requests.put(
            f"{BASE_URL}/api/leads/{created_lead_id}",
            json={"status": "contacted"},
            headers=admin_headers,
            timeout=15,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "contacted"

        # GET-verify persistence
        rl = requests.get(f"{BASE_URL}/api/leads", headers=admin_headers, timeout=15)
        target = next((l for l in rl.json() if l["id"] == created_lead_id), None)
        assert target is not None
        assert target["status"] == "contacted"

    def test_leads_admin_only_get_denies_tech(self, tech_headers):
        r = requests.get(f"{BASE_URL}/api/leads", headers=tech_headers, timeout=15)
        assert r.status_code == 403, f"tech should be blocked from /leads, got {r.status_code}"

    def test_leads_admin_only_get_denies_customer(self, customer_headers):
        r = requests.get(f"{BASE_URL}/api/leads", headers=customer_headers, timeout=15)
        assert r.status_code == 403

    def test_leads_admin_only_post_denies_tech(self, tech_headers):
        r = requests.post(
            f"{BASE_URL}/api/leads",
            json={"name": "TEST_Iter5 tech-attempt"},
            headers=tech_headers,
            timeout=15,
        )
        assert r.status_code == 403

    def test_leads_admin_only_put_denies_customer(self, customer_headers, created_lead_id):
        r = requests.put(
            f"{BASE_URL}/api/leads/{created_lead_id}",
            json={"status": "won"},
            headers=customer_headers,
            timeout=15,
        )
        assert r.status_code == 403

    def test_convert_lead_creates_customer(self, admin_headers, created_lead_id):
        r = requests.post(
            f"{BASE_URL}/api/leads/{created_lead_id}/convert",
            headers=admin_headers,
            timeout=15,
        )
        assert r.status_code == 200, f"convert failed: {r.status_code} {r.text}"
        cust = r.json()
        assert "id" in cust
        assert cust["name"] == "TEST_Iter5 Lead Alpha"
        assert "_id" not in cust

        # Lead should now be marked won
        rl = requests.get(f"{BASE_URL}/api/leads", headers=admin_headers, timeout=15)
        target = next((l for l in rl.json() if l["id"] == created_lead_id), None)
        assert target is not None
        assert target["status"] == "won"

    def test_convert_lead_denies_tech(self, tech_headers, created_lead_id):
        r = requests.post(
            f"{BASE_URL}/api/leads/{created_lead_id}/convert",
            headers=tech_headers,
            timeout=15,
        )
        assert r.status_code == 403

    def test_convert_unknown_lead_404(self, admin_headers):
        r = requests.post(
            f"{BASE_URL}/api/leads/does-not-exist-xyz/convert",
            headers=admin_headers,
            timeout=15,
        )
        assert r.status_code == 404


# --------------------------- Team ---------------------------
class TestTeam:
    def test_list_team_admin(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/team", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        team = r.json()
        assert isinstance(team, list)
        assert len(team) >= 2  # at least admin + one technician seeded
        roles = {u["role"] for u in team}
        assert roles.issubset({"admin", "technician"})
        assert "customer" not in roles
        for u in team:
            assert "password_hash" not in u
            assert "_id" not in u
            assert "email" in u
            assert "name" in u

    def test_team_denies_tech(self, tech_headers):
        r = requests.get(f"{BASE_URL}/api/team", headers=tech_headers, timeout=15)
        assert r.status_code == 403

    def test_team_denies_customer(self, customer_headers):
        r = requests.get(f"{BASE_URL}/api/team", headers=customer_headers, timeout=15)
        assert r.status_code == 403


# --------------------------- Price Book (items) ---------------------------
class TestPriceBook:
    def test_list_items_admin(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/items", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list)
        assert len(items) >= 1
        first = items[0]
        for field in ("id", "name", "unit_price", "category", "unit"):
            assert field in first, f"missing field {field}: {first}"
        assert "_id" not in first

    def test_items_denies_tech(self, tech_headers):
        # CRITICAL: technicians must not see pricing catalog
        r = requests.get(f"{BASE_URL}/api/items", headers=tech_headers, timeout=15)
        assert r.status_code == 403, f"tech should be blocked from /items (pricing), got {r.status_code}"

    def test_items_denies_customer(self, customer_headers):
        r = requests.get(f"{BASE_URL}/api/items", headers=customer_headers, timeout=15)
        assert r.status_code == 403


# --------------------------- Payments ---------------------------
class TestPayments:
    def test_list_payments_admin(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/payments", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        payments = r.json()
        assert isinstance(payments, list)
        # seed provides paid invoices for revenue chart; must have at least one
        if payments:
            p = payments[0]
            for field in ("id", "customer_name", "title", "amount", "method"):
                assert field in p, f"missing field {field}: {p}"
            assert isinstance(p["amount"], (int, float))
            assert "_id" not in p

    def test_payments_denies_tech(self, tech_headers):
        # CRITICAL: technicians must NEVER see pricing/payments
        r = requests.get(f"{BASE_URL}/api/payments", headers=tech_headers, timeout=15)
        assert r.status_code == 403, f"tech should be blocked from /payments, got {r.status_code}"

    def test_payments_denies_customer(self, customer_headers):
        r = requests.get(f"{BASE_URL}/api/payments", headers=customer_headers, timeout=15)
        assert r.status_code == 403


# --------------------------- Auth negatives ---------------------------
class TestAuthNegatives:
    def test_no_token_401(self):
        r = requests.get(f"{BASE_URL}/api/leads", timeout=15)
        assert r.status_code in (401, 403)

    def test_bad_token_401(self):
        r = requests.get(
            f"{BASE_URL}/api/leads",
            headers={"Authorization": "Bearer not-a-valid-jwt"},
            timeout=15,
        )
        assert r.status_code == 401
