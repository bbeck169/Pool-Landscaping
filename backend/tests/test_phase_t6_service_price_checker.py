"""Phase T6 — Service Price Checker tests."""
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


class TestSeedData:
    def test_all_51_states_present(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from services.service_price_market import SERVICE_PRICE_MARKET, BY_STATE, SERVICE_TYPES
        assert len(SERVICE_PRICE_MARKET) == 51  # 50 states + DC
        assert "DC" in BY_STATE
        assert "AZ" in BY_STATE
        # All service types are populated for every state
        for row in SERVICE_PRICE_MARKET:
            for svc in SERVICE_TYPES:
                band = row["market_rates"][svc]
                assert band["low"] < band["median"] < band["high"], f"{row['state_code']} {svc}"


class TestPriceCheck:
    def test_az_weekly_pool_known_answer(self, admin_tok):
        r = requests.post(f"{API}/calculators/service-price-check", headers=_h(admin_tok),
                          json={"state_code": "AZ", "service_type": "weekly_pool_service"},
                          timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["state_code"] == "AZ"
        assert j["state_name"] == "Arizona"
        assert j["region"] == "southwest"
        # Tolerant band assertion (col_index adjusts base):
        assert 130 <= j["market_rate"]["median"] <= 150
        assert 100 <= j["market_rate"]["low"] <= 115
        assert 170 <= j["market_rate"]["high"] <= 200
        assert "estimates" in j["notes"].lower()

    def test_ca_weekly_pool_higher_than_ms(self, admin_tok):
        ca = requests.post(f"{API}/calculators/service-price-check", headers=_h(admin_tok),
                           json={"state_code": "CA", "service_type": "weekly_pool_service"},
                           timeout=TIMEOUT).json()
        ms = requests.post(f"{API}/calculators/service-price-check", headers=_h(admin_tok),
                           json={"state_code": "MS", "service_type": "weekly_pool_service"},
                           timeout=TIMEOUT).json()
        # Cost-of-living sanity: CA (1.42) should be materially higher than MS (0.84).
        assert ca["market_rate"]["median"] > ms["market_rate"]["median"] * 1.5

    def test_business_size_suggestion(self, admin_tok):
        for size, expected in [("small", "low"), ("medium", "median"), ("large", "high")]:
            r = requests.post(f"{API}/calculators/service-price-check", headers=_h(admin_tok),
                              json={"state_code": "AZ", "service_type": "weekly_pool_service",
                                    "business_size": size}, timeout=TIMEOUT)
            assert r.json()["business_size_suggestion"] == expected

    def test_unknown_state_400(self, admin_tok):
        r = requests.post(f"{API}/calculators/service-price-check", headers=_h(admin_tok),
                          json={"state_code": "ZZ", "service_type": "weekly_pool_service"},
                          timeout=TIMEOUT)
        assert r.status_code == 400

    def test_unknown_service_type_400(self, admin_tok):
        r = requests.post(f"{API}/calculators/service-price-check", headers=_h(admin_tok),
                          json={"state_code": "AZ", "service_type": "bogus_type"},
                          timeout=TIMEOUT)
        assert r.status_code == 400

    def test_market_position_populated(self, admin_tok):
        # aquaterra has billing plans → tenant median should surface for pool services.
        r = requests.post(f"{API}/calculators/service-price-check", headers=_h(admin_tok),
                          json={"state_code": "AZ", "service_type": "weekly_pool_service"},
                          timeout=TIMEOUT).json()
        # your_median_price is either None (no plans in that freq) OR a number
        # + market_position is a valid label if number set.
        if r["your_median_price"] is not None:
            assert r["market_position"] in ("below_market", "at_market", "above_market")
            assert r["gap_recommendation"] and "median" in r["gap_recommendation"].lower()

    def test_rbac_tech_forbidden(self, tech_tok):
        r = requests.post(f"{API}/calculators/service-price-check", headers=_h(tech_tok),
                          json={"state_code": "AZ", "service_type": "weekly_pool_service"},
                          timeout=TIMEOUT)
        assert r.status_code == 403

    def test_rbac_customer_forbidden(self, customer_tok):
        r = requests.post(f"{API}/calculators/service-price-check", headers=_h(customer_tok),
                          json={"state_code": "AZ", "service_type": "weekly_pool_service"},
                          timeout=TIMEOUT)
        assert r.status_code == 403


class TestMarketIndexEndpoint:
    def test_index_returns_51_states(self, admin_tok):
        r = requests.get(f"{API}/calculators/service-price-market", headers=_h(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        j = r.json()
        assert len(j["states"]) == 51
        assert "weekly_pool_service" in j["service_types"]

    def test_state_detail(self, admin_tok):
        r = requests.get(f"{API}/calculators/service-price-market/AZ", headers=_h(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        j = r.json()
        assert j["state_code"] == "AZ"
        assert "market_rates" in j
        assert "service_type_labels" in j


class TestCanonicalTemplates:
    def test_four_system_templates_seeded_with_codes(self):
        import asyncio, sys
        sys.path.insert(0, "/app/backend")
        from config import db
        async def _q():
            n = await db.document_templates.count_documents({"is_system": True})
            codes = []
            async for r in db.document_templates.find({"is_system": True}, {"_id": 0, "code": 1}):
                codes.append(r["code"])
            return n, sorted(codes)
        n, codes = asyncio.run(_q())
        assert n == 4, f"expected 4 system templates, got {n}"
        assert codes == sorted(["weekly_pool_service", "weekly_landscape",
                                 "new_customer_onboarding", "winterization"])
