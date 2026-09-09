"""QuoteIQ Phase Q2 — AI Estimator + Options Estimates backend tests.

Uses ``TEST_LLM_MOCK=1`` so the LLM path is deterministic.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest
import requests

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
from dotenv import load_dotenv
load_dotenv(BACKEND_ROOT / ".env")

from tests.conftest import demo_pw


# ─── Test-isolation guard (I1.7 leak fix, Feb-2026) ──────────────
# Previously this file did ``os.environ["TEST_LLM_MOCK"] = "1"`` at
# module scope, which polluted every subsequent test file in an
# alphabetical sweep. Scoping the flag to an autouse fixture keeps
# the mock active for every test in THIS module and tears it down
# on module exit.
@pytest.fixture(autouse=True)
def _force_test_llm_mock(monkeypatch):
    monkeypatch.setenv("TEST_LLM_MOCK", "1")
    yield

BACKEND = os.environ.get("REACT_APP_BACKEND_URL") \
    or "https://poolscape-audit.preview.emergentagent.com"
API = f"{BACKEND}/api"
# T bumped from 25 → 90 to accommodate the real Claude Sonnet round-trip
# now that TEST_LLM_MOCK=0 is the default. Mock path (CI) is fast.
T = 90


def _login(email, pw):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=T)
    r.raise_for_status()
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com", demo_pw("admin@aquaterra.com"))


@pytest.fixture(scope="module")
def super_tok():
    return _login("super@aquaterra.com", demo_pw("super@aquaterra.com"))


@pytest.fixture(scope="module")
def tech_tok():
    return _login("mike@aquaterra.com", demo_pw("mike@aquaterra.com"))


@pytest.fixture(scope="module")
def tenant_id(admin_tok):
    r = requests.get(f"{API}/tenants/current", headers=_h(admin_tok), timeout=T)
    return r.json()["id"]


@pytest.fixture(scope="module")
def demo_customer(admin_tok):
    """Create a customer to promote drafts against; cleaned up post-run."""
    r = requests.post(f"{API}/customers",
                       json={"name": f"TEST_ Q2 Customer {uuid.uuid4().hex[:6]}",
                              "email": f"q2_test_{uuid.uuid4().hex[:6]}@example.com"},
                       headers=_h(admin_tok), timeout=T)
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    yield cid
    requests.delete(f"{API}/customers/{cid}", headers=_h(admin_tok), timeout=T)


@pytest.fixture(scope="module", autouse=True)
def _cleanup(admin_tok, super_tok):
    # Ensure credits balance is generous enough for the whole run.
    requests.post(f"{API}/ai-credits/topup",
                   json={"amount": 500, "note": "q2_test_bootstrap"},
                   headers=_h(super_tok), timeout=T)
    yield
    # Purge Q2 test artifacts.
    try:
        for d in requests.get(f"{API}/ai-estimator/drafts?limit=200",
                                headers=_h(admin_tok), timeout=T).json().get("drafts", []):
            if "TEST_" in (d.get("job_description") or ""):
                requests.delete(f"{API}/ai-estimator/drafts/{d['id']}",
                                 headers=_h(admin_tok), timeout=T)
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════════════
# AI Estimator drafts
# ═════════════════════════════════════════════════════════════════════

class TestGenerateDraftLinear:
    _did = None

    def test_generate_debits_credits_and_creates_draft(self, admin_tok):
        pre = requests.get(f"{API}/ai-credits/balance",
                            headers=_h(admin_tok), timeout=T).json()
        r = requests.post(f"{API}/ai-estimator/generate",
                           json={"photo_urls": [],
                                  "job_description": "TEST_ Weekly maintenance for backyard pool with plaster finish",
                                  "options_mode": False},
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["draft"]["status"] == "complete"
        assert len(d["draft"]["line_items"]) >= 1
        assert d["draft"]["suggested_total_cents"] > 0
        assert d["draft"]["credits_debited"] == 10
        # Balance dropped by 10.
        assert d["credits_balance_after"] == pre["balance"] - 10
        TestGenerateDraftLinear._did = d["draft"]["id"]

    def test_ledger_row_exists_for_draft(self, admin_tok):
        assert TestGenerateDraftLinear._did
        txns = requests.get(f"{API}/ai-credits/transactions?feature=estimator&limit=50",
                              headers=_h(admin_tok), timeout=T).json()
        matched = [t for t in txns["transactions"]
                    if t.get("ref_id") == TestGenerateDraftLinear._did]
        assert len(matched) >= 1
        assert matched[0]["delta"] == -10
        assert matched[0]["ref_type"] == "ai_estimate_draft"

    def test_catalog_snapping_forces_known_prices(self, admin_tok):
        assert TestGenerateDraftLinear._did
        d = requests.get(
            f"{API}/ai-estimator/drafts/{TestGenerateDraftLinear._did}",
            headers=_h(admin_tok), timeout=T).json()
        # Every source='catalog' item must have unit_price_cents from the tenant catalog.
        cat = requests.get(f"{API}/chemical-products",
                            headers=_h(admin_tok), timeout=T).json()
        by_slug = {p["slug"]: p["unit_cost_cents"] for p in cat["products"]}
        for li in d["line_items"]:
            if li["source"] == "catalog" and li.get("service_slug") in by_slug:
                assert li["unit_price_cents"] == by_slug[li["service_slug"]]

    def test_list_and_filter(self, admin_tok):
        r = requests.get(f"{API}/ai-estimator/drafts?limit=5&status=complete",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        for row in r.json()["drafts"]:
            assert row["status"] == "complete"

    def test_patch_recomputes_total(self, admin_tok):
        assert TestGenerateDraftLinear._did
        r = requests.patch(
            f"{API}/ai-estimator/drafts/{TestGenerateDraftLinear._did}",
            json={"line_items": [
                {"description": "TEST_ Edited line", "qty": 2, "unit": "each",
                  "unit_price_cents": 5000, "subtotal_cents": 10000,
                  "source": "ai_inferred", "confidence": 0.8},
            ]}, headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        assert r.json()["suggested_total_cents"] == 10000


class TestGenerateDraftOptionsMode:
    _did = None

    def test_options_mode_produces_three_tiers(self, admin_tok):
        r = requests.post(f"{API}/ai-estimator/generate",
                           json={"photo_urls": [],
                                  "job_description": "TEST_ Options mode: monthly pool care",
                                  "options_mode": True},
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200, r.text
        d = r.json()["draft"]
        assert d["status"] == "complete"
        assert len(d["tiers"]) == 3
        names = [t["name"] for t in d["tiers"]]
        assert names == ["Basic", "Standard", "Premium"]
        # Exactly one default.
        defaults = [t for t in d["tiers"] if t.get("is_default")]
        assert len(defaults) == 1
        assert d["credits_debited"] == 20  # options mode = 10 + 10
        TestGenerateDraftOptionsMode._did = d["id"]

    def test_options_mode_total_matches_default_tier(self, admin_tok):
        assert TestGenerateDraftOptionsMode._did
        d = requests.get(
            f"{API}/ai-estimator/drafts/{TestGenerateDraftOptionsMode._did}",
            headers=_h(admin_tok), timeout=T).json()
        default = next(t for t in d["tiers"] if t["is_default"])
        assert d["suggested_total_cents"] == default["total_cents"]


class TestRBAC:
    def test_tech_forbidden_on_generate(self, tech_tok):
        r = requests.post(f"{API}/ai-estimator/generate",
                           json={"job_description": "TEST_ tech blocked"},
                           headers=_h(tech_tok), timeout=T)
        assert r.status_code == 403


class TestPromote:
    _est_id = None

    def test_promote_creates_estimate_with_source_ai(self, admin_tok,
                                                       demo_customer):
        # Fresh draft.
        gen = requests.post(f"{API}/ai-estimator/generate",
                              json={"job_description": "TEST_ Promotion linear",
                                     "options_mode": False},
                              headers=_h(admin_tok), timeout=T).json()
        did = gen["draft"]["id"]
        r = requests.post(f"{API}/ai-estimator/drafts/{did}/promote",
                           json={"customer_id": demo_customer,
                                  "title": "TEST_ Promoted"},
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200, r.text
        est = r.json()["estimate"]
        assert est["source"] == "ai"
        assert est["ai_draft_id"] == did
        assert est["customer_id"] == demo_customer
        assert (est.get("options") or {}).get("enabled") is False
        assert est["total_cents"] > 0
        TestPromote._est_id = est["id"]

    def test_promote_options_mode_carries_tiers(self, admin_tok,
                                                  demo_customer):
        gen = requests.post(f"{API}/ai-estimator/generate",
                              json={"job_description": "TEST_ Promotion options",
                                     "options_mode": True},
                              headers=_h(admin_tok), timeout=T).json()
        did = gen["draft"]["id"]
        r = requests.post(f"{API}/ai-estimator/drafts/{did}/promote",
                           json={"customer_id": demo_customer,
                                  "title": "TEST_ Promoted Options"},
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        est = r.json()["estimate"]
        assert (est["options"] or {}).get("enabled") is True
        assert len(est["options"]["tiers"]) == 3
        assert est["options"]["selected_tier_id"]
        # Line items materialized on the top level match the selected tier.
        selected = next(t for t in est["options"]["tiers"]
                          if t["id"] == est["options"]["selected_tier_id"])
        assert est["total_cents"] == selected["total_cents"]


class TestOptionsEnableAndSelect:
    _eid = None
    _tier_ids: list = []

    def test_enable_options_on_manual_estimate(self, admin_tok, demo_customer):
        # Create a manual estimate first via the existing endpoint.
        e = requests.post(f"{API}/estimates",
                           json={"customer_id": demo_customer,
                                  "title": "TEST_ Manual options",
                                  "line_items": []},
                           headers=_h(admin_tok), timeout=T).json()
        eid = e["id"]
        r = requests.post(
            f"{API}/estimates/{eid}/enable-options",
            json={"tiers": [
                {"name": "Basic", "line_items": [
                    {"description": "Weekly", "quantity": 4, "unit_cost": 100.00},
                ]},
                {"name": "Standard", "line_items": [
                    {"description": "Weekly", "quantity": 4, "unit_cost": 125.00},
                    {"description": "Filter", "quantity": 1, "unit_cost": 85.00},
                ], "is_default": True},
                {"name": "Premium", "line_items": [
                    {"description": "Weekly", "quantity": 4, "unit_cost": 150.00},
                    {"description": "Filter", "quantity": 1, "unit_cost": 85.00},
                    {"description": "Inspection", "quantity": 1, "unit_cost": 120.00},
                ]},
            ]}, headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200, r.text
        est = r.json()
        assert est["options"]["enabled"] is True
        assert len(est["options"]["tiers"]) == 3
        # Standard is default; total = 4*125 + 85 = 58500 cents.
        assert est["total_cents"] == 58500
        TestOptionsEnableAndSelect._eid = eid
        TestOptionsEnableAndSelect._tier_ids = [t["id"] for t in est["options"]["tiers"]]

    def test_select_option_flips_total(self, admin_tok):
        eid = TestOptionsEnableAndSelect._eid
        premium_id = TestOptionsEnableAndSelect._tier_ids[2]
        r = requests.post(f"{API}/estimates/{eid}/select-option",
                           json={"tier_id": premium_id},
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        est = r.json()
        assert est["options"]["selected_tier_id"] == premium_id
        # 4*150 + 85 + 120 = 80500 cents.
        assert est["total_cents"] == 80500

    def test_convert_to_job_uses_selected_tier(self, admin_tok):
        eid = TestOptionsEnableAndSelect._eid
        r = requests.post(f"{API}/estimates/{eid}/convert-to-job",
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        job_id = r.json()["job_id"]
        est = requests.get(f"{API}/estimates/{eid}",
                            headers=_h(admin_tok), timeout=T).json()
        assert est["status"] == "converted"
        assert est["converted_job_id"] == job_id


class TestPublicSelectOption:
    def test_public_link_and_selection(self, admin_tok, demo_customer):
        # Create + enable options.
        e = requests.post(f"{API}/estimates",
                           json={"customer_id": demo_customer,
                                  "title": "TEST_ Public options",
                                  "line_items": []},
                           headers=_h(admin_tok), timeout=T).json()
        eid = e["id"]
        r = requests.post(
            f"{API}/estimates/{eid}/enable-options",
            json={"tiers": [
                {"name": "A", "line_items": [{"description": "x",
                                                "quantity": 1, "unit_cost": 10}]},
                {"name": "B", "line_items": [{"description": "y",
                                                "quantity": 1, "unit_cost": 20}],
                  "is_default": True},
            ]}, headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        est = r.json()
        # Mint a token (admin-only) then hit the public endpoint (unauth).
        link = requests.get(f"{API}/estimates/{eid}/public-link",
                              headers=_h(admin_tok), timeout=T).json()
        tid = link["tenant_id"]
        tok = link["token"]
        target = est["options"]["tiers"][0]["id"]
        r2 = requests.post(
            f"{API}/public/estimates/{tok}/select-option"
            f"?estimate_id={eid}&tenant_id={tid}",
            json={"tier_id": target},
            timeout=T)
        assert r2.status_code == 200, r2.text
        assert r2.json()["options"]["selected_tier_id"] == target

    def test_bad_token_403(self):
        r = requests.post(
            f"{API}/public/estimates/badbadbad/select-option"
            "?estimate_id=x&tenant_id=y",
            json={"tier_id": "z"}, timeout=T)
        assert r.status_code == 403


class TestTenantIsolation:
    def test_drafts_scoped(self, admin_tok, tenant_id):
        r = requests.get(f"{API}/ai-estimator/drafts",
                          headers=_h(admin_tok), timeout=T)
        for d in r.json()["drafts"]:
            assert d["tenant_id"] == tenant_id


class TestOpenApi:
    def test_openapi_has_q2_paths(self):
        r = requests.get(f"{API}/openapi.json", timeout=T)
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        for p in [
            "/api/ai-estimator/generate",
            "/api/ai-estimator/drafts",
            "/api/ai-estimator/drafts/{did}/promote",
            "/api/estimates/{eid}/enable-options",
            "/api/estimates/{eid}/select-option",
            "/api/estimates/{eid}/public-link",
            "/api/estimates/{eid}/convert-to-job",
        ]:
            assert p in paths, f"missing OpenAPI path: {p}"
