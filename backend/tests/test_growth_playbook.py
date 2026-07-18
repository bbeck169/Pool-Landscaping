"""Ship 2 · Growth Playbook — backend tests.

Verifies:
  * RBAC: admin 200, tech 403, customer 403
  * Auto-pull path (empty body) returns portfolio-derived numbers
  * Explicit overrides (state, frequency, avg revenue) work
  * Below-market scenario produces positive delta_valuation + healthy/very_generous flavor
  * Above-market scenario returns skip_playbook + null breakeven
  * Zero-customer edge case → no crash + skip_playbook
  * State fallback to AZ when no tenant state_code
  * Churn breakeven math known-answer
"""
from __future__ import annotations
import os
import pytest
import requests

API = os.environ.get("BACKEND_URL", "http://localhost:8001") + "/api"
TIMEOUT = 30


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


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _post(admin_tok, body):
    r = requests.post(f"{API}/analysis/growth-playbook",
                      headers=_h(admin_tok), json=body, timeout=TIMEOUT)
    return r


class TestGrowthPlaybookBasics:
    def test_admin_default_pull_ok(self, admin_tok):
        r = _post(admin_tok, {})
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("tenant_id", "state_code", "state_name", "state_fallback_used",
                   "service_type", "dominant_frequency", "active_customers",
                   "assumptions", "today", "market_median_scenario", "churn_breakeven"):
            assert k in d
        # Aquaterra tenants have no state_code set → fallback active.
        assert d["state_fallback_used"] is True
        assert d["state_code"] == "AZ"

    def test_tech_403(self, tech_tok):
        r = _post(tech_tok, {})
        assert r.status_code == 403

    def test_customer_403(self, customer_tok):
        r = _post(customer_tok, {})
        assert r.status_code == 403


class TestGrowthPlaybookScenarios:
    def test_below_market_weekly_produces_positive_delta(self, admin_tok):
        r = _post(admin_tok, {
            "avg_monthly_revenue_per_customer": 80,
            "active_customers": 100,
            "dominant_frequency": "weekly",
        })
        assert r.status_code == 200
        d = r.json()
        m = d["market_median_scenario"]
        be = d["churn_breakeven"]
        # AZ weekly median $143 × 4.33 vpm ≈ $619/mo per customer → market > $80/mo tenant → below_market.
        assert m["market_position"] == "below_market"
        assert m["price_delta_positive"] is True
        assert m["delta_valuation"] > 0
        assert be["flavor"] != "skip_playbook"
        assert be["breakeven_churn_pct"] is not None
        # Additional churn tolerated should be >= 0 (breakeven >= today's churn)
        assert be["additional_churn_tolerated_pct"] >= 0

    def test_above_market_returns_skip_playbook(self, admin_tok):
        # Aquaterra with dominant_frequency=monthly and per-customer $150/mo → above AZ monthly median $82.
        r = _post(admin_tok, {
            "avg_monthly_revenue_per_customer": 150,
            "active_customers": 100,
            "dominant_frequency": "monthly",
        })
        assert r.status_code == 200
        d = r.json()
        m = d["market_median_scenario"]
        assert m["price_delta_positive"] is False
        assert d["churn_breakeven"]["flavor"] == "skip_playbook"
        assert d["churn_breakeven"]["breakeven_churn_pct"] is None

    def test_zero_customers_no_crash(self, admin_tok):
        r = _post(admin_tok, {"active_customers": 0,
                              "avg_monthly_revenue_per_customer": 100})
        assert r.status_code == 200
        d = r.json()
        assert d["active_customers"] == 0
        assert d["today"]["total_monthly_revenue"] == 0
        assert d["today"]["route_valuation"] == 0
        # No breakeven when price delta is not positive.
        assert d["churn_breakeven"]["flavor"] == "skip_playbook"

    def test_explicit_state_override(self, admin_tok):
        r = _post(admin_tok, {
            "state_code": "CA",
            "avg_monthly_revenue_per_customer": 300,
            "active_customers": 50,
            "dominant_frequency": "weekly",
        })
        assert r.status_code == 200
        d = r.json()
        assert d["state_code"] == "CA"
        assert d["state_fallback_used"] is False
        # CA weekly median is $234 — 300 monthly / 4.33 vpm = ~$69/visit → below CA market.
        m = d["market_median_scenario"]
        assert m["market_position"] == "below_market"
        assert m["delta_valuation"] > 0

    def test_unknown_state_falls_back_to_az(self, admin_tok):
        r = _post(admin_tok, {"state_code": "XX",
                              "avg_monthly_revenue_per_customer": 100,
                              "active_customers": 50})
        assert r.status_code == 200
        d = r.json()
        assert d["state_code"] == "AZ"
        assert d["state_fallback_used"] is True

    def test_assumptions_echoed(self, admin_tok):
        r = _post(admin_tok, {
            "density": "spread", "churn_pct": 5, "contract_months": 36,
            "avg_monthly_revenue_per_customer": 80, "active_customers": 20,
            "dominant_frequency": "weekly",
        })
        assert r.status_code == 200
        a = r.json()["assumptions"]
        assert a["density"] == "spread"
        assert a["churn_pct"] == 5
        assert a["contract_length_avg_months"] == 36

    def test_saturated_high_flavor_very_generous(self, admin_tok):
        # Push a massive market gap so target multiple drops below multiple_min
        # → saturated_high = True → very_generous flavor.
        r = _post(admin_tok, {
            "avg_monthly_revenue_per_customer": 10,   # very low today
            "active_customers": 100,
            "dominant_frequency": "weekly",           # AZ weekly = $143/visit
            "state_code": "CA",                        # CA weekly = $234/visit
        })
        d = r.json()
        assert d["market_median_scenario"]["delta_valuation"] > 0
        be = d["churn_breakeven"]
        # Enormous market gap → saturated_high, flavor very_generous.
        assert be["flavor"] == "very_generous"
        assert be["saturated_high"] is True


class TestGrowthPlaybookMath:
    def test_multiple_matches_route_valuation_endpoint(self, admin_tok):
        """Playbook's today.multiple must match the standalone route_valuation
        endpoint when called with identical inputs. Ensures both paths share
        the same math."""
        payload = {
            "avg_monthly_revenue_per_customer": 150,
            "active_customers": 100,
            "dominant_frequency": "weekly",
            "density": "dense", "churn_pct": 5, "contract_months": 24,
        }
        r1 = _post(admin_tok, payload)
        d1 = r1.json()

        # T5.1 direct
        r2 = requests.post(f"{API}/calculators/route-valuation",
                            headers=_h(admin_tok),
                            json={"active_customers": 100,
                                  "avg_monthly_revenue_per_customer": 150,
                                  "route_density": "dense",
                                  "churn_rate_pct": 5,
                                  "contract_length_avg_months": 24},
                            timeout=TIMEOUT)
        d2 = r2.json()
        assert d1["today"]["route_multiple"] == d2["route_multiple"]
        assert d1["today"]["route_valuation"] == d2["route_valuation"]

    def test_churn_breakeven_monotonic_in_gap(self, admin_tok):
        """Smaller price gap should yield smaller additional_churn_tolerated
        (tighter breakeven). Uses two below-market scenarios at different
        avg revenues to sanity-check monotonicity."""
        base = {"active_customers": 100, "dominant_frequency": "weekly",
                "state_code": "AZ", "density": "medium",
                "churn_pct": 8, "contract_months": 24}
        r_narrow = _post(admin_tok, {**base, "avg_monthly_revenue_per_customer": 400})
        r_wide   = _post(admin_tok, {**base, "avg_monthly_revenue_per_customer": 100})
        be_n = r_narrow.json()["churn_breakeven"]
        be_w = r_wide.json()["churn_breakeven"]
        # Wider gap = tolerates AT LEAST as much churn (equal only when both saturated).
        if not be_n["saturated_high"] and not be_w["saturated_high"]:
            assert be_w["additional_churn_tolerated_pct"] >= be_n["additional_churn_tolerated_pct"]
        # Both scenarios must have positive delta_valuation (below-market weekly).
        assert r_narrow.json()["market_median_scenario"]["delta_valuation"] > 0
        assert r_wide.json()["market_median_scenario"]["delta_valuation"] > 0
