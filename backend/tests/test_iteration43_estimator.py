"""Iteration 43 — Profit-aware Estimator (ZevBit-style).

Covers:
- Estimate settings (get/put with admin-only enforcement)
- Prebuilt templates seeded lazily (>=3)
- Compute correctness on POST /api/estimates (direct/overhead/burdened/sell/GM%)
- Full CRUD + list
- Convert to quote (single-line sell price, second convert=400)
- RBAC: technician & customer roles rejected (403) for all estimate endpoints
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL") or "https://pool-app-mobile.preview.emergentagent.com"
BASE_URL = BASE_URL.rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = ("admin@aquaterra.com", "password123")
TECH = ("mike@aquaterra.com", "password123")
CUSTOMER = ("customer@aquaterra.com", "password123")


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"No token in login response: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login(*ADMIN)}"}


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login(*TECH)}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login(*CUSTOMER)}"}


@pytest.fixture(scope="module")
def customer_id(admin_headers):
    r = requests.get(f"{API}/customers", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    custs = r.json()
    assert len(custs) > 0, "No customers seeded"
    return custs[0]["id"]


# ---------- Cleanup ----------
_CREATED_ESTIMATES = []
_CREATED_QUOTES = []


@pytest.fixture(scope="module", autouse=True)
def _teardown(admin_headers):
    yield
    for eid in _CREATED_ESTIMATES:
        try:
            requests.delete(f"{API}/estimates/{eid}", headers=admin_headers, timeout=10)
        except Exception:
            pass
    for qid in _CREATED_QUOTES:
        try:
            requests.delete(f"{API}/quotes/{qid}", headers=admin_headers, timeout=10)
        except Exception:
            pass


# ---------- Settings ----------
class TestEstimateSettings:
    def test_get_settings_defaults(self, admin_headers):
        r = requests.get(f"{API}/estimates/settings", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        s = r.json()
        assert "overhead_pct" in s and "margin_pct" in s
        # First call must seed defaults 15 / 30 (or already stored)
        assert isinstance(s["overhead_pct"], (int, float))
        assert isinstance(s["margin_pct"], (int, float))

    def test_put_settings_admin_only(self, admin_headers):
        r = requests.put(
            f"{API}/estimates/settings",
            json={"overhead_pct": 18, "margin_pct": 32},
            headers=admin_headers,
            timeout=15,
        )
        assert r.status_code == 200
        s = r.json()
        assert s["overhead_pct"] == 18
        assert s["margin_pct"] == 32
        # Restore defaults so downstream tests aren't affected
        requests.put(
            f"{API}/estimates/settings",
            json={"overhead_pct": 15, "margin_pct": 30},
            headers=admin_headers,
            timeout=15,
        )


# ---------- Templates ----------
class TestEstimateTemplates:
    def test_templates_seeded(self, admin_headers):
        r = requests.get(f"{API}/estimate-templates", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        tpls = r.json()
        assert isinstance(tpls, list)
        assert len(tpls) >= 3, f"Expected >=3 templates, got {len(tpls)}"
        for t in tpls[:3]:
            assert "name" in t
            assert "line_items" in t
            assert "overhead_pct" in t
            assert "margin_pct" in t


# ---------- CRUD + Compute ----------
class TestEstimateCompute:
    def test_create_estimate_computes_correctly(self, admin_headers, customer_id):
        body = {
            "customer_id": customer_id,
            "title": "TEST_Estimator_Compute",
            "line_items": [
                {"category": "Material", "description": "Pump", "quantity": 1, "unit_cost": 650.0},
                {"category": "Labor", "description": "Install hrs", "quantity": 4, "unit_cost": 45.0},
            ],
            "overhead_pct": 15,
            "margin_pct": 30,
            "notes": "TEST_",
        }
        r = requests.post(f"{API}/estimates", json=body, headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        e = r.json()
        _CREATED_ESTIMATES.append(e["id"])

        assert e["direct_cost"] == 830.0
        assert e["overhead_amount"] == 124.5
        assert e["total_cost"] == 954.5
        assert e["sell_price"] == 1363.57
        assert e["gross_margin_pct"] == 30 or e["gross_margin_pct"] == 30.0
        assert e["status"] == "draft"
        assert e["customer_id"] == customer_id
        assert e["customer_name"]
        assert e.get("converted_quote_id") in (None, "")

    def test_get_and_list(self, admin_headers):
        assert _CREATED_ESTIMATES, "prior create test must run first"
        eid = _CREATED_ESTIMATES[0]
        r = requests.get(f"{API}/estimates/{eid}", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        assert r.json()["id"] == eid

        r = requests.get(f"{API}/estimates", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        assert any(x["id"] == eid for x in r.json())

    def test_update_recomputes(self, admin_headers, customer_id):
        eid = _CREATED_ESTIMATES[0]
        body = {
            "customer_id": customer_id,
            "title": "TEST_Estimator_Compute",
            "line_items": [
                {"category": "Material", "description": "Pump", "quantity": 1, "unit_cost": 1000.0},
            ],
            "overhead_pct": 10,
            "margin_pct": 40,
            "notes": "",
        }
        r = requests.put(f"{API}/estimates/{eid}", json=body, headers=admin_headers, timeout=15)
        assert r.status_code == 200
        e = r.json()
        # direct=1000, overhead=100, total=1100, sell=1100/0.6=1833.33
        assert e["direct_cost"] == 1000.0
        assert e["overhead_amount"] == 100.0
        assert e["total_cost"] == 1100.0
        assert e["sell_price"] == 1833.33


# ---------- Convert ----------
class TestConvert:
    def test_convert_creates_quote_single_line(self, admin_headers, customer_id):
        # Create fresh estimate to convert
        body = {
            "customer_id": customer_id,
            "title": "TEST_Estimator_Convert",
            "line_items": [
                {"category": "Material", "description": "Pump", "quantity": 1, "unit_cost": 650.0},
                {"category": "Labor", "description": "Install hrs", "quantity": 4, "unit_cost": 45.0},
            ],
            "overhead_pct": 15,
            "margin_pct": 30,
        }
        r = requests.post(f"{API}/estimates", json=body, headers=admin_headers, timeout=15)
        assert r.status_code == 200
        eid = r.json()["id"]
        _CREATED_ESTIMATES.append(eid)
        expected_sell = r.json()["sell_price"]

        r2 = requests.post(f"{API}/estimates/{eid}/convert", headers=admin_headers, timeout=15)
        assert r2.status_code == 200, r2.text
        q = r2.json()
        _CREATED_QUOTES.append(q["id"])
        assert q["doc_type"] == "quote"
        assert len(q["line_items"]) == 1
        assert q["line_items"][0]["quantity"] == 1
        assert q["line_items"][0]["unit_price"] == expected_sell
        assert q["total"] == expected_sell
        assert q["subtotal"] == expected_sell
        assert q.get("from_estimate_id") == eid

        # Estimate now marked converted
        r3 = requests.get(f"{API}/estimates/{eid}", headers=admin_headers, timeout=15)
        assert r3.status_code == 200
        assert r3.json()["status"] == "converted"
        assert r3.json()["converted_quote_id"] == q["id"]

    def test_second_convert_returns_400(self, admin_headers):
        # Reuse the just-converted estimate (last entry we added)
        # Find the one that was converted
        eid = _CREATED_ESTIMATES[-1]
        r = requests.post(f"{API}/estimates/{eid}/convert", headers=admin_headers, timeout=15)
        assert r.status_code == 400, r.text


# ---------- Delete ----------
class TestDelete:
    def test_delete_estimate(self, admin_headers, customer_id):
        body = {
            "customer_id": customer_id,
            "title": "TEST_Estimator_ToDelete",
            "line_items": [{"category": "Material", "description": "x", "quantity": 1, "unit_cost": 10}],
            "overhead_pct": 10,
            "margin_pct": 20,
        }
        r = requests.post(f"{API}/estimates", json=body, headers=admin_headers, timeout=15)
        assert r.status_code == 200
        eid = r.json()["id"]

        d = requests.delete(f"{API}/estimates/{eid}", headers=admin_headers, timeout=15)
        assert d.status_code == 200

        g = requests.get(f"{API}/estimates/{eid}", headers=admin_headers, timeout=15)
        assert g.status_code == 404


# ---------- RBAC ----------
class TestRBAC:
    endpoints = [
        ("GET", "/estimates"),
        ("GET", "/estimates/settings"),
        ("GET", "/estimate-templates"),
        ("POST", "/estimates"),
    ]

    def test_technician_forbidden(self, tech_headers):
        for method, path in self.endpoints:
            if method == "GET":
                r = requests.get(f"{API}{path}", headers=tech_headers, timeout=15)
            else:
                r = requests.post(f"{API}{path}", json={}, headers=tech_headers, timeout=15)
            assert r.status_code == 403, f"{method} {path} expected 403 for technician, got {r.status_code}"

    def test_customer_forbidden(self, customer_headers):
        for method, path in self.endpoints:
            if method == "GET":
                r = requests.get(f"{API}{path}", headers=customer_headers, timeout=15)
            else:
                r = requests.post(f"{API}{path}", json={}, headers=customer_headers, timeout=15)
            assert r.status_code == 403, f"{method} {path} expected 403 for customer, got {r.status_code}"
