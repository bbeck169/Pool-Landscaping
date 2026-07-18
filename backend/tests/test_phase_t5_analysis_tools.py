"""Phase T5 — Business Analysis Tools tests.

Two admin-only endpoints:
  * POST /api/calculators/route-valuation
  * POST /api/calculators/pay-model-compare
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
def admin_tok(): return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def tech_tok(): return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def customer_tok(): return _login("customer@aquaterra.com")


def _h(t): return {"Authorization": f"Bearer {t}"}


# ═══ T5.1 Route Valuation ════════════════════════════════════════════
class TestRouteValuation:
    def test_known_answer(self, admin_tok):
        # 100 customers, $150/mo avg, dense, 5% churn, 24mo contracts
        # density_factor(dense)=1.0
        # churn_factor = 1 - (5-4)/(12-4) = 0.875
        # contract_factor = (24-6)/(36-6) = 0.6
        # combined = (1.0 + 0.875 + 0.6)/3 = 0.825
        # multiple = 4 + (8-4) * 0.825 = 7.3x
        # valuation = 100 * 150 * 7.3 = $109,500
        # per_customer = $1,095
        r = requests.post(f"{API}/calculators/route-valuation", headers=_h(admin_tok),
                          json={"active_customers": 100,
                                "avg_monthly_revenue_per_customer": 150,
                                "churn_rate_pct": 5,
                                "route_density": "dense",
                                "contract_length_avg_months": 24},
                          timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        j = r.json()
        assert 6.9 <= j["route_multiple"] <= 7.6, j["route_multiple"]
        assert 103_000 <= j["route_valuation"] <= 114_000, j["route_valuation"]
        assert 1030 <= j["valuation_per_customer"] <= 1140, j["valuation_per_customer"]
        assert j["benchmarks"]["position"] == "below_industry"

    def test_zero_customers_no_divzero(self, admin_tok):
        r = requests.post(f"{API}/calculators/route-valuation", headers=_h(admin_tok),
                          json={"active_customers": 0,
                                "avg_monthly_revenue_per_customer": 150},
                          timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["route_valuation"] == 0.0
        assert j["valuation_per_customer"] == 0.0

    def test_interpolation_sanity_dense_beats_spread(self, admin_tok):
        base = {"active_customers": 100, "avg_monthly_revenue_per_customer": 150,
                "churn_rate_pct": 5, "contract_length_avg_months": 24}
        r1 = requests.post(f"{API}/calculators/route-valuation", headers=_h(admin_tok),
                           json={**base, "route_density": "dense"}, timeout=TIMEOUT).json()
        r2 = requests.post(f"{API}/calculators/route-valuation", headers=_h(admin_tok),
                           json={**base, "route_density": "spread"}, timeout=TIMEOUT).json()
        assert r1["route_multiple"] > r2["route_multiple"]
        assert r1["route_valuation"] > r2["route_valuation"]

    def test_rbac_tech_forbidden(self, tech_tok):
        r = requests.post(f"{API}/calculators/route-valuation", headers=_h(tech_tok),
                          json={"active_customers": 100}, timeout=TIMEOUT)
        assert r.status_code == 403

    def test_rbac_customer_forbidden(self, customer_tok):
        r = requests.post(f"{API}/calculators/route-valuation", headers=_h(customer_tok),
                          json={"active_customers": 100}, timeout=TIMEOUT)
        assert r.status_code == 403

    def test_auto_pull_from_tenant(self, admin_tok):
        # Passing no active_customers → auto-pulls tenant active count.
        # We only assert the shape + that the count is > 0 (aquaterra has customers).
        r = requests.post(f"{API}/calculators/route-valuation", headers=_h(admin_tok),
                          json={}, timeout=TIMEOUT)
        assert r.status_code == 200
        assert r.json()["active_customers"] > 0


# ═══ T5.2 Pay Model Compare ══════════════════════════════════════════
class TestPayModel:
    def test_known_answer(self, admin_tok):
        # 40 customers, 45min avg, $135/mo, weekly (4.33 vpcm):
        # monthly_visits = 40 * 4.33 = 173.2
        # monthly_hours = 173.2 * 45/60 = 129.9
        # monthly_revenue = 40 * 135 = $5400
        # hourly: 129.9 * $22 = $2857.80
        # per_pool: 173.2 * $18 = $3117.60
        # route_buy: 5400 * 0.65 = $3510.00
        r = requests.post(f"{API}/calculators/pay-model-compare", headers=_h(admin_tok),
                          json={"tech_route_customers": 40,
                                "avg_visit_time_minutes": 45,
                                "avg_revenue_per_customer_month": 135,
                                "visits_per_customer_per_month": 4.33},
                          timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        j = r.json()
        m = j["models"]
        # ±10% tolerance per spec
        assert 2570 <= m["hourly"]["monthly_tech_pay"] <= 3145, m["hourly"]
        assert 2805 <= m["per_pool"]["monthly_tech_pay"] <= 3430, m["per_pool"]
        assert 3160 <= m["route_buy"]["monthly_tech_pay"] <= 3860, m["route_buy"]
        # Recommendation always names hourly as best margin at these inputs
        # (lowest tech pay → highest company margin)
        assert j["best_company_margin"] == "hourly"

    def test_zero_customers_no_crash(self, admin_tok):
        r = requests.post(f"{API}/calculators/pay-model-compare", headers=_h(admin_tok),
                          json={"tech_route_customers": 0,
                                "avg_visit_time_minutes": 45,
                                "avg_revenue_per_customer_month": 135,
                                "visits_per_customer_per_month": 4.33},
                          timeout=TIMEOUT)
        assert r.status_code == 200
        j = r.json()
        for k in ("hourly", "per_pool", "route_buy"):
            assert j["models"][k]["monthly_tech_pay"] == 0.0

    def test_rbac_tech_forbidden(self, tech_tok):
        r = requests.post(f"{API}/calculators/pay-model-compare", headers=_h(tech_tok),
                          json={"tech_route_customers": 40, "avg_visit_time_minutes": 45,
                                "avg_revenue_per_customer_month": 135,
                                "visits_per_customer_per_month": 4.33},
                          timeout=TIMEOUT)
        assert r.status_code == 403

    def test_rbac_customer_forbidden(self, customer_tok):
        r = requests.post(f"{API}/calculators/pay-model-compare", headers=_h(customer_tok),
                          json={"tech_route_customers": 40, "avg_visit_time_minutes": 45,
                                "avg_revenue_per_customer_month": 135,
                                "visits_per_customer_per_month": 4.33},
                          timeout=TIMEOUT)
        assert r.status_code == 403
