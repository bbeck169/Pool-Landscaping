"""Ship 1 · Polish Batch — comprehensive backend tests.

Covers:
  * T4.3 · Route Valuation PDF (`POST /api/documents/route-valuation-pdf`)
  * T4.1 · System templates list + clone-to-edit + delete guard
  * T3-followup · pricing-defaults GET/PUT + validation bounds
  * T3.2 · Recommend price increase (suggestion + preview/draft/send +
             idempotency snapshot)
"""
from __future__ import annotations
import os
from io import BytesIO

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


# ═══ T4.3 · Route Valuation PDF ═══════════════════════════════════════
class TestRouteValuationPDF:
    _payload = {
        "active_customers": 100,
        "avg_monthly_revenue_per_customer": 150,
        "total_monthly_revenue": 15000,
        "annual_revenue": 180000,
        "annual_gross_profit": 68400,
        "route_multiple": 7.3,
        "route_valuation": 109500,
        "valuation_per_customer": 1095,
        "breakdown": {
            "density": "dense", "density_factor": 1.0,
            "churn_rate_pct": 5, "churn_factor": 0.88,
            "contract_length_avg_months": 24, "contract_factor": 0.6,
            "combined_factor": 0.83, "multiple_min": 4, "multiple_max": 8,
        },
        "benchmarks": {
            "industry_per_customer_low": 1500,
            "industry_per_customer_high": 3500,
            "position": "below_industry",
        },
        "generated_by": "admin@aquaterra.com",
    }

    def test_admin_pdf_stream(self, admin_tok):
        r = requests.post(f"{API}/documents/route-valuation-pdf",
                          headers=_h(admin_tok), json=self._payload, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:5] == b"%PDF-"
        assert len(r.content) > 800

    def test_pdf_contains_headline_and_multiple(self, admin_tok):
        r = requests.post(f"{API}/documents/route-valuation-pdf",
                          headers=_h(admin_tok), json=self._payload, timeout=TIMEOUT)
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError:
            pytest.skip("pypdf not installed")
        text = "".join(p.extract_text() for p in PdfReader(BytesIO(r.content)).pages)
        assert "109,500.00" in text or "109500" in text
        assert "7.3x" in text
        assert "dense" in text
        assert "below industry" in text or "below_industry" in text

    def test_tech_403(self, tech_tok):
        r = requests.post(f"{API}/documents/route-valuation-pdf",
                          headers=_h(tech_tok), json=self._payload, timeout=TIMEOUT)
        assert r.status_code == 403

    def test_customer_403(self, customer_tok):
        r = requests.post(f"{API}/documents/route-valuation-pdf",
                          headers=_h(customer_tok), json=self._payload, timeout=TIMEOUT)
        assert r.status_code == 403


# ═══ T4.1 · SYSTEM templates + clone-to-edit + delete guard ═══════════
class TestSystemTemplates:
    def test_list_includes_system_rows(self, admin_tok):
        r = requests.get(f"{API}/documents/checklist-templates",
                         headers=_h(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        rows = r.json()["rows"]
        sys_rows = [x for x in rows if x.get("is_system")]
        assert len(sys_rows) >= 4, f"expected ≥4 system templates seeded, got {len(sys_rows)}"
        codes = {x.get("code") for x in sys_rows}
        assert "weekly_pool_service" in codes
        assert "weekly_landscape" in codes

    def test_delete_system_template_blocked(self, admin_tok):
        r = requests.get(f"{API}/documents/checklist-templates",
                         headers=_h(admin_tok), timeout=TIMEOUT)
        sys_row = next(x for x in r.json()["rows"] if x.get("is_system"))
        r2 = requests.delete(f"{API}/documents/checklist-templates/{sys_row['id']}",
                             headers=_h(admin_tok), timeout=TIMEOUT)
        assert r2.status_code == 403
        # Still in list.
        r3 = requests.get(f"{API}/documents/checklist-templates",
                          headers=_h(admin_tok), timeout=TIMEOUT)
        assert sys_row["id"] in {x["id"] for x in r3.json()["rows"]}

    def test_clone_creates_tenant_scoped_copy(self, admin_tok):
        r = requests.get(f"{API}/documents/checklist-templates",
                         headers=_h(admin_tok), timeout=TIMEOUT)
        sys_row = next(x for x in r.json()["rows"] if x.get("is_system"))
        r2 = requests.post(
            f"{API}/documents/checklist-templates/{sys_row['id']}/clone",
            headers=_h(admin_tok), timeout=TIMEOUT)
        assert r2.status_code == 200, r2.text
        clone = r2.json()
        assert clone["id"] != sys_row["id"]
        assert clone.get("is_system") is False
        assert clone.get("cloned_from_id") == sys_row["id"]
        assert clone["name"].endswith(" (copy)")
        # Persisted and appears in list.
        r3 = requests.get(f"{API}/documents/checklist-templates",
                          headers=_h(admin_tok), timeout=TIMEOUT)
        assert clone["id"] in {x["id"] for x in r3.json()["rows"]}
        # Clone can now be edited (save with id).
        clone["name"] = clone["name"] + " test"
        r4 = requests.post(f"{API}/documents/checklist-template/save",
                            headers=_h(admin_tok), json=clone, timeout=TIMEOUT)
        assert r4.status_code == 200
        # Clone can also be deleted (unlike system row).
        r5 = requests.delete(
            f"{API}/documents/checklist-templates/{clone['id']}",
            headers=_h(admin_tok), timeout=TIMEOUT)
        assert r5.status_code == 200

    def test_tech_cannot_clone(self, tech_tok, admin_tok):
        r = requests.get(f"{API}/documents/checklist-templates",
                         headers=_h(admin_tok), timeout=TIMEOUT)
        sys_row = next(x for x in r.json()["rows"] if x.get("is_system"))
        r2 = requests.post(
            f"{API}/documents/checklist-templates/{sys_row['id']}/clone",
            headers=_h(tech_tok), timeout=TIMEOUT)
        assert r2.status_code == 403


# ═══ T3-followup · pricing-defaults CRUD + validation ═════════════════
class TestPricingDefaults:
    def test_get_shape(self, admin_tok):
        r = requests.get(f"{API}/settings/pricing-defaults",
                         headers=_h(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        d = r.json()
        for key in ("spec_defaults", "tenant_overrides", "effective"):
            assert key in d
        for section in ("pricing_defaults", "route_valuation_defaults", "pay_model_defaults"):
            assert section in d["spec_defaults"]
            assert section in d["effective"]
        # Sanity — spec dict has known keys
        assert "base_weekly" in d["spec_defaults"]["pricing_defaults"]
        assert "multiple_max" in d["spec_defaults"]["route_valuation_defaults"]
        assert "hourly_rate" in d["spec_defaults"]["pay_model_defaults"]

    def test_put_and_reset_roundtrip(self, admin_tok):
        # Set override
        r = requests.put(f"{API}/settings/pricing-defaults",
                         headers=_h(admin_tok),
                         json={"pricing_defaults": {"base_weekly": 175.0},
                               "pay_model_defaults": {"hourly_rate": 30.0}},
                         timeout=TIMEOUT)
        assert r.status_code == 200
        overrides = r.json()["tenant_overrides"]
        assert overrides["pricing_defaults"]["base_weekly"] == 175.0
        assert overrides["pay_model_defaults"]["hourly_rate"] == 30.0
        # Confirm effective reflects override
        r2 = requests.get(f"{API}/settings/pricing-defaults",
                          headers=_h(admin_tok), timeout=TIMEOUT)
        assert r2.json()["effective"]["pricing_defaults"]["base_weekly"] == 175.0
        # Reset base_weekly (null)
        r3 = requests.put(f"{API}/settings/pricing-defaults",
                          headers=_h(admin_tok),
                          json={"pricing_defaults": {"base_weekly": None},
                                "pay_model_defaults": {"hourly_rate": None}},
                          timeout=TIMEOUT)
        assert r3.status_code == 200
        overrides = r3.json()["tenant_overrides"]
        assert "base_weekly" not in overrides["pricing_defaults"]
        assert "hourly_rate" not in overrides["pay_model_defaults"]

    def test_validation_bounds_rejected(self, admin_tok):
        # margin_target_pct upper bound is 200
        r = requests.put(f"{API}/settings/pricing-defaults",
                         headers=_h(admin_tok),
                         json={"pricing_defaults": {"margin_target_pct": 250}},
                         timeout=TIMEOUT)
        assert r.status_code == 422
        assert "must be in" in r.text
        # base_weekly negative
        r2 = requests.put(f"{API}/settings/pricing-defaults",
                          headers=_h(admin_tok),
                          json={"pricing_defaults": {"base_weekly": -10}},
                          timeout=TIMEOUT)
        assert r2.status_code == 422

    def test_tech_403(self, tech_tok):
        r = requests.get(f"{API}/settings/pricing-defaults",
                         headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 403

    def test_customer_403(self, customer_tok):
        r = requests.put(f"{API}/settings/pricing-defaults",
                         headers=_h(customer_tok),
                         json={"pricing_defaults": {"base_weekly": 200}}, timeout=TIMEOUT)
        assert r.status_code == 403

    def test_effective_reflects_service_price_calculator(self, admin_tok):
        """Set base_weekly override → /calculators/service-price should return it."""
        requests.put(f"{API}/settings/pricing-defaults",
                     headers=_h(admin_tok),
                     json={"pricing_defaults": {"base_weekly": 200.0}},
                     timeout=TIMEOUT)
        try:
            r = requests.post(f"{API}/calculators/service-price",
                              headers=_h(admin_tok),
                              json={"pool_gallons": 15000, "visit_type": "weekly",
                                    "pool_features": []},
                              timeout=TIMEOUT)
            assert r.status_code == 200
            assert r.json()["breakdown"]["base"] == 200.0
        finally:
            # Cleanup — reset base_weekly.
            requests.put(f"{API}/settings/pricing-defaults",
                         headers=_h(admin_tok),
                         json={"pricing_defaults": {"base_weekly": None}},
                         timeout=TIMEOUT)


# ═══ T3.2 · Recommend price increase ══════════════════════════════════
def _find_low_margin_customer(tok):
    r = requests.get(f"{API}/calculators/cost-per-pool", headers=_h(tok), timeout=TIMEOUT)
    for row in r.json().get("rows", []):
        if "low_margin" in row.get("flags", []) or "negative_margin" in row.get("flags", []):
            return row
    # Fall back to any row with a plan
    for row in r.json().get("rows", []):
        return row
    return None


class TestRecommendPriceIncrease:
    def test_suggestion_endpoint(self, admin_tok):
        row = _find_low_margin_customer(admin_tok)
        assert row, "no cost-per-pool rows to test against"
        r = requests.get(
            f"{API}/calculators/price-increase-suggestion?customer_id={row['customer_id']}",
            headers=_h(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("customer_id", "customer_name", "per_visit_in_cost",
                   "current_price_per_visit", "recommended_price_per_visit",
                   "target_margin_pct"):
            assert k in d
        # Sanity: recommended > in_cost
        assert d["recommended_price_per_visit"] >= d["per_visit_in_cost"]

    def test_preview_does_not_persist(self, admin_tok):
        row = _find_low_margin_customer(admin_tok)
        r = requests.post(f"{API}/calculators/recommend-price-increase",
                          headers=_h(admin_tok),
                          json={"customer_id": row["customer_id"],
                                "current_price": 45.0, "recommended_price": 65.0,
                                "reason": "cost-of-goods increase",
                                "action": "preview"},
                          timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["action"] == "preview"
        assert "subject" in d and "html" in d and "text" in d
        assert "$65.00" in d["html"] or "65.00" in d["html"]

    def test_draft_idempotent_snapshot(self, admin_tok):
        row = _find_low_margin_customer(admin_tok)
        # 1st draft
        r1 = requests.post(f"{API}/calculators/recommend-price-increase",
                            headers=_h(admin_tok),
                            json={"customer_id": row["customer_id"],
                                  "current_price": 45.0, "recommended_price": 65.0,
                                  "action": "draft"}, timeout=TIMEOUT)
        assert r1.status_code == 200
        first_id = r1.json()["id"]
        assert r1.json()["status"] == "draft"
        # 2nd draft same snapshot → same id
        r2 = requests.post(f"{API}/calculators/recommend-price-increase",
                            headers=_h(admin_tok),
                            json={"customer_id": row["customer_id"],
                                  "current_price": 45.0, "recommended_price": 65.0,
                                  "action": "draft"}, timeout=TIMEOUT)
        assert r2.json()["id"] == first_id
        # Different snapshot (new recommended price) → NEW id
        r3 = requests.post(f"{API}/calculators/recommend-price-increase",
                            headers=_h(admin_tok),
                            json={"customer_id": row["customer_id"],
                                  "current_price": 45.0, "recommended_price": 70.0,
                                  "action": "draft"}, timeout=TIMEOUT)
        assert r3.json()["id"] != first_id
        assert r3.json()["status"] == "draft"

    def test_send_falls_back_gracefully(self, admin_tok):
        row = _find_low_margin_customer(admin_tok)
        r = requests.post(f"{API}/calculators/recommend-price-increase",
                          headers=_h(admin_tok),
                          json={"customer_id": row["customer_id"],
                                "current_price": 50.0, "recommended_price": 60.0,
                                "action": "send"}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        d = r.json()
        # In test-mode Resend or missing key both are legitimate outcomes.
        assert d["status"] in ("sent", "failed", "not_sent_missing_key")

    def test_invalid_action_422(self, admin_tok):
        row = _find_low_margin_customer(admin_tok)
        r = requests.post(f"{API}/calculators/recommend-price-increase",
                          headers=_h(admin_tok),
                          json={"customer_id": row["customer_id"],
                                "current_price": 50.0, "recommended_price": 60.0,
                                "action": "publish"}, timeout=TIMEOUT)
        assert r.status_code == 422

    def test_negative_price_422(self, admin_tok):
        row = _find_low_margin_customer(admin_tok)
        r = requests.post(f"{API}/calculators/recommend-price-increase",
                          headers=_h(admin_tok),
                          json={"customer_id": row["customer_id"],
                                "current_price": 50.0, "recommended_price": 0,
                                "action": "draft"}, timeout=TIMEOUT)
        assert r.status_code == 422

    def test_tech_403(self, tech_tok, admin_tok):
        row = _find_low_margin_customer(admin_tok)
        r = requests.post(f"{API}/calculators/recommend-price-increase",
                          headers=_h(tech_tok),
                          json={"customer_id": row["customer_id"],
                                "current_price": 50.0, "recommended_price": 60.0,
                                "action": "preview"}, timeout=TIMEOUT)
        assert r.status_code == 403

    def test_customer_403_suggestion(self, customer_tok, admin_tok):
        row = _find_low_margin_customer(admin_tok)
        r = requests.get(
            f"{API}/calculators/price-increase-suggestion?customer_id={row['customer_id']}",
            headers=_h(customer_tok), timeout=TIMEOUT)
        assert r.status_code == 403
