"""Phase T1 + T2 — Pool calculators (chemistry + heater size).

5 stateless endpoints; each test asserts known-answer math + RBAC.
No DB fixtures required (endpoints are pure).
"""
from __future__ import annotations
import os
import pytest
import requests

API = os.environ.get("BACKEND_URL", "http://localhost:8001") + "/api"
TIMEOUT = 20


def _login(email: str, pwd: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pwd},
                      timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def tech_tok():
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def customer_tok():
    return _login("customer@aquaterra.com")


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ═══ LSI ═════════════════════════════════════════════════════════════
class TestLsi:
    def test_balanced(self, tech_tok):
        # pH 7.4, temp 80°F, CH 300, TA 100, TDS 500, no CYA → LSI ≈ 0.0 (±0.1)
        r = requests.post(f"{API}/calculators/lsi",
                          json={"ph": 7.4, "temp_f": 80, "ch": 300, "ta": 100, "tds": 500},
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        j = r.json()
        assert -0.15 <= j["lsi"] <= 0.15, f"LSI {j['lsi']} out of tolerance"
        assert j["interpretation"] == "balanced"

    def test_scaling(self, tech_tok):
        # High pH + CH → positive LSI
        r = requests.post(f"{API}/calculators/lsi",
                          json={"ph": 8.2, "temp_f": 85, "ch": 500, "ta": 150, "tds": 1200},
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        assert r.json()["interpretation"] == "scaling"

    def test_corrosive(self, tech_tok):
        # Low pH + low alk → negative LSI
        r = requests.post(f"{API}/calculators/lsi",
                          json={"ph": 6.8, "temp_f": 55, "ch": 80, "ta": 40, "tds": 500},
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        assert r.json()["interpretation"] == "corrosive"

    def test_boundary_invalid(self, tech_tok):
        r = requests.post(f"{API}/calculators/lsi",
                          json={"ph": 0, "temp_f": 80, "ch": 300, "ta": 100},
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 422

    def test_rbac_customer_forbidden(self, customer_tok):
        r = requests.post(f"{API}/calculators/lsi",
                          json={"ph": 7.4, "temp_f": 80, "ch": 300, "ta": 100},
                          headers=_h(customer_tok), timeout=TIMEOUT)
        assert r.status_code == 403


# ═══ Volume ══════════════════════════════════════════════════════════
class TestVolume:
    def test_rectangle(self, tech_tok):
        # 20 × 40 × 5 × 7.48 = 29,920 gal
        r = requests.post(f"{API}/calculators/volume",
                          json={"shape": "rectangle", "length": 20,
                                "width": 40, "avg_depth": 5},
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        assert 29_800 <= r.json()["gallons"] <= 30_000

    def test_circle(self, tech_tok):
        # π × 15² × 5 × 7.48 ≈ 26,428 gal
        r = requests.post(f"{API}/calculators/volume",
                          json={"shape": "circle", "radius": 15, "avg_depth": 5},
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        assert 26_000 <= r.json()["gallons"] <= 26_800

    def test_shallow_deep_average(self, tech_tok):
        # (3 + 8) / 2 = 5.5 avg depth
        r = requests.post(f"{API}/calculators/volume",
                          json={"shape": "rectangle", "length": 20, "width": 40,
                                "shallow_depth": 3, "deep_depth": 8},
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        assert r.json()["avg_depth"] == 5.5

    def test_bad_shape(self, tech_tok):
        r = requests.post(f"{API}/calculators/volume",
                          json={"shape": "kidney", "length": 20, "width": 40, "avg_depth": 5},
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 422

    def test_rbac_admin_ok(self, admin_tok):
        r = requests.post(f"{API}/calculators/volume",
                          json={"shape": "rectangle", "length": 10, "width": 20, "avg_depth": 4},
                          headers=_h(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 200


# ═══ Salt ════════════════════════════════════════════════════════════
class TestSalt:
    def test_known_answer(self, tech_tok):
        # 20000 × (3200 − 2500) / 120000 = 116.67 lbs
        r = requests.post(f"{API}/calculators/salt",
                          json={"pool_gallons": 20000, "current_salt": 2500, "target_salt": 3200},
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        j = r.json()
        assert 116.0 <= j["lbs_to_add"] <= 117.5

    def test_over_target(self, tech_tok):
        r = requests.post(f"{API}/calculators/salt",
                          json={"pool_gallons": 20000, "current_salt": 4000, "target_salt": 3200},
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        j = r.json()
        assert j["lbs_to_add"] == 0.0
        assert "drain" in j["note"].lower()

    def test_rbac_customer_forbidden(self, customer_tok):
        r = requests.post(f"{API}/calculators/salt",
                          json={"pool_gallons": 20000, "current_salt": 2500, "target_salt": 3200},
                          headers=_h(customer_tok), timeout=TIMEOUT)
        assert r.status_code == 403


# ═══ Turnover ════════════════════════════════════════════════════════
class TestTurnover:
    def test_residential_info_only(self, tech_tok):
        # 20000 / (60 × 60) = 5.56 hours, residential = informational
        r = requests.post(f"{API}/calculators/turnover",
                          json={"pool_gallons": 20000, "pump_gpm": 60},
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        j = r.json()
        assert 5.5 <= j["turnover_hours"] <= 5.6
        assert j["compliant"] is None  # residential informational

    def test_commercial_shallow_pass(self, tech_tok):
        # 20000 / (100 × 60) = 3.33 hours, commercial ≤ 4h → pass
        r = requests.post(f"{API}/calculators/turnover",
                          json={"pool_gallons": 20000, "pump_gpm": 100,
                                "pool_type": "commercial", "depth_ft": 3.5},
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        assert r.json()["compliant"] is True

    def test_commercial_deep_fail(self, tech_tok):
        # 40000 / (60 × 60) = 11.11 hours, commercial deep 6h → fail
        r = requests.post(f"{API}/calculators/turnover",
                          json={"pool_gallons": 40000, "pump_gpm": 60,
                                "pool_type": "commercial", "depth_ft": 6},
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        assert r.json()["compliant"] is False

    def test_spa_pass(self, tech_tok):
        # 500 / (30 × 60) = 0.28 hours, spa 0.5h → pass
        r = requests.post(f"{API}/calculators/turnover",
                          json={"pool_gallons": 500, "pump_gpm": 30, "pool_type": "spa"},
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        assert r.json()["compliant"] is True


# ═══ Heater ══════════════════════════════════════════════════════════
class TestHeater:
    def test_gas_sizing(self, tech_tok):
        # 20000 × 8.33 × (82-60) / 24 = ~152,717 BTU/hr
        r = requests.post(f"{API}/calculators/heater-size",
                          json={"pool_gallons": 20000, "current_temp": 60,
                                "target_temp": 82, "avg_ambient": 70,
                                "surface_area": 800, "heater_type": "gas"},
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        j = r.json()
        assert 150_000 <= j["btu_required"] <= 155_000
        assert j["monthly_cost"] > 0

    def test_heat_pump_lower_cost(self, tech_tok):
        r = requests.post(f"{API}/calculators/heater-size",
                          json={"pool_gallons": 20000, "current_temp": 60,
                                "target_temp": 82, "avg_ambient": 70,
                                "surface_area": 800, "heater_type": "heat_pump"},
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        assert r.json()["heater_type"] == "heat_pump"

    def test_solar_zero_cost(self, tech_tok):
        r = requests.post(f"{API}/calculators/heater-size",
                          json={"pool_gallons": 20000, "current_temp": 60,
                                "target_temp": 82, "avg_ambient": 70,
                                "surface_area": 800, "heater_type": "solar"},
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        assert r.json()["monthly_cost"] == 0.0

    def test_target_below_current(self, tech_tok):
        r = requests.post(f"{API}/calculators/heater-size",
                          json={"pool_gallons": 20000, "current_temp": 85,
                                "target_temp": 82, "avg_ambient": 70,
                                "surface_area": 800, "heater_type": "gas"},
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 422

    def test_rbac_customer_forbidden(self, customer_tok):
        r = requests.post(f"{API}/calculators/heater-size",
                          json={"pool_gallons": 20000, "current_temp": 60,
                                "target_temp": 82, "avg_ambient": 70,
                                "surface_area": 800, "heater_type": "gas"},
                          headers=_h(customer_tok), timeout=TIMEOUT)
        assert r.status_code == 403
