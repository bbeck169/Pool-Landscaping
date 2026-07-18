"""Phase T3 — Business Pricing Tools tests.

Three admin-only endpoints on the calculators router:
  * POST /calculators/service-in-cost
  * GET  /calculators/cost-per-pool
  * POST /calculators/service-price
"""
from __future__ import annotations
import os
import pytest
import requests

API = os.environ.get("BACKEND_URL", "http://localhost:8001") + "/api"
TIMEOUT = 20


def _login(email, pwd="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=TIMEOUT)
    r.raise_for_status()
    j = r.json()
    return j.get("access_token") or j.get("token")


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def tech_tok():
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def customer_tok():
    return _login("customer@aquaterra.com")


def _h(t): return {"Authorization": f"Bearer {t}"}


# ═══ T3.1 Service In-cost ════════════════════════════════════════════
class TestInCost:
    def test_known_answer(self, admin_tok):
        # Baseline: 20000 gal weekly, standard chem load, 45min @ $35/hr,
        # overhead 1.25, margin 40%.
        # Chem cost: liquid_chlorine 1gal ($4.50) + muriatic_acid 0.25gal ($1.50)
        #  + chlorine_tabs 2 tabs ($1.50) = $7.50
        # Labor: 45/60 * 35 = $26.25
        # Overhead: (7.50 + 26.25) * 0.25 = $8.44
        # Total in-cost: ~$42.19
        # Minimum price: 42.19 * 1.40 = $59.07
        r = requests.post(f"{API}/calculators/service-in-cost", headers=_h(admin_tok),
                          json={"pool_gallons": 20000, "visit_type": "weekly",
                                "chemicals_per_visit": [
                                    {"chemical_slug": "liquid_chlorine", "quantity": 1.0, "unit": "gal"},
                                    {"chemical_slug": "muriatic_acid", "quantity": 0.25, "unit": "gal"},
                                    {"chemical_slug": "chlorine_tabs", "quantity": 2, "unit": "tab"},
                                ],
                                "tech_time_minutes": 45, "tech_hourly_cost": 35,
                                "overhead_multiplier": 1.25, "margin_target_pct": 40},
                          timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        j = r.json()
        assert 6 <= j["chemical_cost_total"] <= 10
        assert 25 <= j["labor_cost"] <= 27
        assert 40 <= j["total_in_cost"] <= 45
        assert 55 <= j["minimum_price_per_visit"] <= 62
        assert j["visits_per_year"] == 52
        # Annualized within reason for a 40% margin weekly.
        assert j["annualized_revenue"] >= j["minimum_price_per_visit"] * 51

    def test_rbac_tech_forbidden(self, tech_tok):
        r = requests.post(f"{API}/calculators/service-in-cost", headers=_h(tech_tok),
                          json={"pool_gallons": 20000, "chemicals_per_visit": []}, timeout=TIMEOUT)
        assert r.status_code == 403

    def test_rbac_customer_forbidden(self, customer_tok):
        r = requests.post(f"{API}/calculators/service-in-cost", headers=_h(customer_tok),
                          json={"pool_gallons": 20000, "chemicals_per_visit": []}, timeout=TIMEOUT)
        assert r.status_code == 403


# ═══ T3.2 Cost per Pool ══════════════════════════════════════════════
class TestCostPerPool:
    def test_aggregation_shape(self, admin_tok):
        r = requests.get(f"{API}/calculators/cost-per-pool", headers=_h(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "count" in j
        assert isinstance(j["rows"], list)
        assert "median_margin_pct" in j["summary"]
        # If we have rows, they must have the right fields + margin_pct is a number or None
        if j["rows"]:
            r0 = j["rows"][0]
            for k in ("customer_id", "customer_name", "pool_gallons",
                      "visit_type", "monthly_in_cost", "monthly_revenue",
                      "margin_amount", "margin_pct", "flags"):
                assert k in r0
            assert isinstance(r0["flags"], list)

    def test_filter_by_visit_type(self, admin_tok):
        r = requests.get(f"{API}/calculators/cost-per-pool?visit_type_filter=weekly",
                         headers=_h(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        j = r.json()
        for row in j["rows"]:
            assert row["visit_type"] in ("weekly",)

    def test_rbac_tech_forbidden(self, tech_tok):
        r = requests.get(f"{API}/calculators/cost-per-pool", headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 403


# ═══ T3.3 Service Price ══════════════════════════════════════════════
class TestServicePrice:
    def test_known_answer(self, admin_tok):
        # 20000 gal weekly, saltwater + heater:
        # base 135 + salt 15 + heater 10 + gallons over baseline (20000-15000=5000, 1 step) 5 = $165
        r = requests.post(f"{API}/calculators/service-price", headers=_h(admin_tok),
                          json={"pool_gallons": 20000, "visit_type": "weekly",
                                "pool_features": ["saltwater", "heater"]}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["recommended_price"] == 165.0, j
        assert j["breakdown"]["base"] == 135.0
        assert j["breakdown"]["features_total"] == 25.0
        assert j["breakdown"]["gallons_adder"] == 5.0

    def test_biweekly_no_features(self, admin_tok):
        # base_bi_weekly 95, no features, 15000 gal = no adder
        r = requests.post(f"{API}/calculators/service-price", headers=_h(admin_tok),
                          json={"pool_gallons": 15000, "visit_type": "bi-weekly",
                                "pool_features": []}, timeout=TIMEOUT)
        assert r.status_code == 200
        assert r.json()["recommended_price"] == 95.0

    def test_bad_visit_type(self, admin_tok):
        r = requests.post(f"{API}/calculators/service-price", headers=_h(admin_tok),
                          json={"pool_gallons": 20000, "visit_type": "daily",
                                "pool_features": []}, timeout=TIMEOUT)
        assert r.status_code == 422

    def test_rbac_tech_forbidden(self, tech_tok):
        r = requests.post(f"{API}/calculators/service-price", headers=_h(tech_tok),
                          json={"pool_gallons": 20000, "visit_type": "weekly"}, timeout=TIMEOUT)
        assert r.status_code == 403

    def test_rbac_customer_forbidden(self, customer_tok):
        r = requests.post(f"{API}/calculators/service-price", headers=_h(customer_tok),
                          json={"pool_gallons": 20000, "visit_type": "weekly"}, timeout=TIMEOUT)
        assert r.status_code == 403
