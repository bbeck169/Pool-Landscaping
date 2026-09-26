"""Phase T2.5 (Feb-2026) — Material Volume + Tonnage calculator.

Stateless L × W × D → ft³ / yd³ / tons pass, with RBAC parity to
the sibling T1/T2 calculators (tech + admin allowed; customer +
anonymous denied) and unit / material / density_override
validation on the request boundary.

Mirrors the ``test_phase_t1_t2_calculators.py`` HTTP-integration
shape: hits ``localhost:8001`` with a real bearer, no DB fixtures,
no mocks.  Same aquaterra bootstrap users the sibling suite uses.
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


# ═══ Happy-path math ═════════════════════════════════════════════════
class TestMaterialMath:
    def test_gravel_dry_all_feet(self, tech_tok):
        # 10 × 10 × 1 ft = 100 ft³ = 3.7037 yd³ × 1.4 t/yd³ = 5.1852 t.
        r = requests.post(f"{API}/calculators/material",
                          json={
                              "length": {"value": 10, "unit": "ft"},
                              "width":  {"value": 10, "unit": "ft"},
                              "depth":  {"value": 1,  "unit": "ft"},
                              "material": "gravel_dry",
                          },
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["cubic_feet"] == 100.0
        assert abs(j["cubic_yards"] - 3.7037) < 0.0005
        assert abs(j["total_tons"] - 5.1852) < 0.0005
        assert j["density_used"] == 1.4
        assert j["material"] == "gravel_dry"

    def test_concrete_all_feet(self, tech_tok):
        # 3 × 3 × 0.5 ft = 4.5 ft³ = 0.1667 yd³ × 2.0 = 0.3333 t.
        r = requests.post(f"{API}/calculators/material",
                          json={
                              "length": {"value": 3, "unit": "ft"},
                              "width":  {"value": 3, "unit": "ft"},
                              "depth":  {"value": 0.5, "unit": "ft"},
                              "material": "concrete",
                          },
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["cubic_feet"] == 4.5
        assert abs(j["cubic_yards"] - 0.1667) < 0.0005
        assert abs(j["total_tons"] - 0.3333) < 0.0005
        assert j["density_used"] == 2.0

    def test_mixed_units_ft_in_yd(self, tech_tok):
        # 1 yd (=3 ft) × 12 in (=1 ft) × 6 in (=0.5 ft) = 1.5 ft³
        # cubic yards = 0.055555… ; sand_dry 1.35 → tons ≈ 0.075.
        r = requests.post(f"{API}/calculators/material",
                          json={
                              "length": {"value": 1,  "unit": "yd"},
                              "width":  {"value": 12, "unit": "in"},
                              "depth":  {"value": 6,  "unit": "in"},
                              "material": "sand_dry",
                          },
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["cubic_feet"] == 1.5
        assert abs(j["cubic_yards"] - 0.0556) < 0.0005
        assert abs(j["total_tons"] - 0.075) < 0.0005
        assert j["density_used"] == 1.35


# ═══ Density override ════════════════════════════════════════════════
class TestDensityOverride:
    def test_override_replaces_default_density(self, tech_tok):
        # 27 ft³ = exactly 1 yd³ so total_tons == density_used.
        r = requests.post(f"{API}/calculators/material",
                          json={
                              "length": {"value": 3, "unit": "ft"},
                              "width":  {"value": 3, "unit": "ft"},
                              "depth":  {"value": 3, "unit": "ft"},
                              "material": "gravel_dry",
                              "density_override": 1.62,
                          },
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["cubic_yards"] == 1.0
        assert j["total_tons"] == 1.62
        assert j["density_used"] == 1.62
        # Material key round-trips even when the density is
        # overridden — caller can still tell which pick was on
        # screen when the answer was computed.
        assert j["material"] == "gravel_dry"

    def test_override_without_material_key(self, tech_tok):
        # Passing just density_override + no material key resolves.
        r = requests.post(f"{API}/calculators/material",
                          json={
                              "length": {"value": 3, "unit": "ft"},
                              "width":  {"value": 3, "unit": "ft"},
                              "depth":  {"value": 3, "unit": "ft"},
                              "density_override": 1.5,
                          },
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["cubic_yards"] == 1.0
        assert j["total_tons"] == 1.5
        assert j["density_used"] == 1.5

    def test_zero_override_rejected(self, tech_tok):
        r = requests.post(f"{API}/calculators/material",
                          json={
                              "length": {"value": 3, "unit": "ft"},
                              "width":  {"value": 3, "unit": "ft"},
                              "depth":  {"value": 3, "unit": "ft"},
                              "material": "gravel_dry",
                              "density_override": 0,
                          },
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 400
        assert "density_override" in r.text


# ═══ Validation errors ═══════════════════════════════════════════════
class TestValidationErrors:
    def test_invalid_unit_yields_400(self, tech_tok):
        r = requests.post(f"{API}/calculators/material",
                          json={
                              "length": {"value": 10, "unit": "m"},
                              "width":  {"value": 10, "unit": "ft"},
                              "depth":  {"value": 1,  "unit": "ft"},
                              "material": "gravel_dry",
                          },
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 400
        assert "invalid unit" in r.text
        assert "length" in r.text

    def test_invalid_material_without_override_yields_400(self, tech_tok):
        r = requests.post(f"{API}/calculators/material",
                          json={
                              "length": {"value": 10, "unit": "ft"},
                              "width":  {"value": 10, "unit": "ft"},
                              "depth":  {"value": 1,  "unit": "ft"},
                              "material": "unicorn_horn",
                          },
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 400
        assert "invalid material" in r.text

    def test_no_material_and_no_override_yields_400(self, tech_tok):
        r = requests.post(f"{API}/calculators/material",
                          json={
                              "length": {"value": 10, "unit": "ft"},
                              "width":  {"value": 10, "unit": "ft"},
                              "depth":  {"value": 1,  "unit": "ft"},
                          },
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 400


# ═══ RBAC parity with sibling T1/T2 endpoints ════════════════════════
class TestRbac:
    def test_admin_role_allowed(self, admin_tok):
        r = requests.post(f"{API}/calculators/material",
                          json={
                              "length": {"value": 10, "unit": "ft"},
                              "width":  {"value": 10, "unit": "ft"},
                              "depth":  {"value": 1,  "unit": "ft"},
                              "material": "gravel_dry",
                          },
                          headers=_h(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 200, r.text

    def test_technician_role_allowed(self, tech_tok):
        r = requests.post(f"{API}/calculators/material",
                          json={
                              "length": {"value": 10, "unit": "ft"},
                              "width":  {"value": 10, "unit": "ft"},
                              "depth":  {"value": 1,  "unit": "ft"},
                              "material": "gravel_dry",
                          },
                          headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 200, r.text

    def test_customer_role_denied(self, customer_tok):
        r = requests.post(f"{API}/calculators/material",
                          json={
                              "length": {"value": 10, "unit": "ft"},
                              "width":  {"value": 10, "unit": "ft"},
                              "depth":  {"value": 1,  "unit": "ft"},
                              "material": "gravel_dry",
                          },
                          headers=_h(customer_tok), timeout=TIMEOUT)
        assert r.status_code == 403

    def test_unauthed_denied(self):
        r = requests.post(f"{API}/calculators/material",
                          json={
                              "length": {"value": 10, "unit": "ft"},
                              "width":  {"value": 10, "unit": "ft"},
                              "depth":  {"value": 1,  "unit": "ft"},
                              "material": "gravel_dry",
                          },
                          timeout=TIMEOUT)
        assert r.status_code in (401, 403)
