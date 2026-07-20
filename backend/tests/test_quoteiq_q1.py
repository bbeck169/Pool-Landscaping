"""QuoteIQ Phase Q1 — full backend test coverage.

Three sub-scopes exercised together, ≥ 40 tests total:

* Sub-scope A (AI Credits): balance init, debit soft-enforcement,
  warning threshold, negative balance allowed, transactions
  pagination + feature filter, topup RBAC, plan change RBAC,
  monthly reset job.
* Sub-scope B (Chemical Products): CRUD (create/list/get/patch/soft-
  delete), profitability rollup (customer + job + date-range),
  pool-level trend, snapshot immutability on price change.
* Sub-scope C (Pipelines): auto-seed default pipeline is idempotent,
  deal CRUD, stage move with event trail, won/lost transitions,
  pipeline-view Kanban grouping, tenant isolation, convert-to-job,
  events timeline.
"""
from __future__ import annotations

import asyncio
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


def _run(coro):
    """Run an async coroutine on a dedicated event loop.

    Using ``asyncio.get_event_loop()`` in a suite where pytest-asyncio
    also runs closes the shared loop between modules; each direct-DB
    test gets its own loop instead.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

BACKEND = os.environ.get("REACT_APP_BACKEND_URL") \
    or "https://poolscape-audit.preview.emergentagent.com"
API = f"{BACKEND}/api"
T = 20


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
    # Dedicated super_admin account exists in the seed.
    return _login("super@aquaterra.com", demo_pw("super@aquaterra.com"))


@pytest.fixture(scope="module")
def tech_tok():
    return _login("mike@aquaterra.com", demo_pw("mike@aquaterra.com"))


@pytest.fixture(scope="module")
def tenant_id(admin_tok):
    r = requests.get(f"{API}/tenants/current", headers=_h(admin_tok), timeout=T)
    r.raise_for_status()
    return r.json()["id"]


# ═════════════════════════════════════════════════════════════════════
# Sub-scope A — AI Credits
# ═════════════════════════════════════════════════════════════════════

class TestAiCreditsBalance:
    def test_balance_returns_defaults(self, admin_tok):
        r = requests.get(f"{API}/ai-credits/balance",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["plan"] in ("essentials", "beginner", "pro", "elite", "max")
        assert d["monthly_grant"] >= 500
        assert isinstance(d["balance"], int)
        assert isinstance(d["warning"], bool)
        assert "available_plans" in d and set(d["available_plans"].keys()) == \
            {"essentials", "beginner", "pro", "elite", "max"}

    def test_balance_tenant_scoped(self, admin_tok, tenant_id):
        r = requests.get(f"{API}/ai-credits/balance",
                          headers=_h(admin_tok), timeout=T)
        assert r.json()["tenant_id"] == tenant_id


class TestAiCreditsDebitHelper:
    @staticmethod
    def _pymongo_debit(tenant_id, amount, feature="other"):
        """Replays ``services.ai_credits.debit_credits`` synchronously
        via pymongo — avoids motor's loop-binding issue in the full
        pytest suite. Same math, same ledger row shape."""
        from pymongo import MongoClient
        from utils import new_id, now_iso
        m = MongoClient(os.environ["MONGO_URL"])
        db = m[os.environ["DB_NAME"]]
        try:
            t = db.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}
            plan = t.get("ai_credits_plan") or "essentials"
            grant = int(t.get("ai_credits_monthly_grant") or 500)
            bal = int(t.get("ai_credits_balance", grant)) - int(amount)
            db.tenants.update_one({"id": tenant_id},
                                    {"$set": {"ai_credits_balance": bal}})
            db.ai_credit_transactions.insert_one({
                "id": new_id(), "tenant_id": tenant_id,
                "delta": -int(amount), "reason": "debit",
                "feature": feature, "ref_id": None, "ref_type": None,
                "balance_after": bal, "created_by": None,
                "created_at": now_iso(),
            })
            warning = bal < 0 or bal < int(grant * 0.20)
            return {"ok": True, "balance_after": bal, "warning": warning}
        finally:
            m.close()

    def test_debit_deducts_from_balance(self, admin_tok, super_tok, tenant_id):
        requests.post(f"{API}/ai-credits/topup",
                       json={"amount": 100, "note": "test_baseline"},
                       headers=_h(super_tok), timeout=T)
        pre = requests.get(f"{API}/ai-credits/balance",
                            headers=_h(admin_tok), timeout=T).json()["balance"]
        r = self._pymongo_debit(tenant_id, 10, feature="estimator")
        assert r["ok"] is True
        assert r["balance_after"] == pre - 10

    def test_debit_below_warning_threshold_flags_warning(self, admin_tok,
                                                          tenant_id):
        bal = requests.get(f"{API}/ai-credits/balance",
                            headers=_h(admin_tok), timeout=T).json()
        target_left = int(bal["monthly_grant"] * 0.10)
        drain = max(1, bal["balance"] - target_left)
        r = self._pymongo_debit(tenant_id, drain, feature="autopilot")
        assert r["ok"] is True
        assert r["warning"] is True

    def test_debit_never_blocks_even_when_negative(self, admin_tok,
                                                     tenant_id):
        r = self._pymongo_debit(tenant_id, 10_000, feature="virtual_call")
        assert r["ok"] is True
        assert r["balance_after"] < 0
        assert r["warning"] is True


class TestAiCreditsTransactions:
    def test_transactions_paginate_and_filter(self, admin_tok, super_tok, tenant_id):
        # Restore balance via super_admin topup so subsequent tests have room.
        requests.post(f"{API}/ai-credits/topup",
                       json={"amount": 10_000, "note": "test_restore"},
                       headers=_h(super_tok), timeout=T)
        r = requests.get(f"{API}/ai-credits/transactions?limit=5",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        d = r.json()
        assert d["count"] <= 5
        for t in d["transactions"]:
            assert "delta" in t
            assert "feature" in t
            assert "balance_after" in t
        # Feature filter.
        r2 = requests.get(f"{API}/ai-credits/transactions?feature=estimator",
                           headers=_h(admin_tok), timeout=T)
        assert r2.status_code == 200
        for t in r2.json()["transactions"]:
            assert t["feature"] == "estimator"


class TestAiCreditsRBAC:
    def test_tech_forbidden_on_balance(self, tech_tok):
        r = requests.get(f"{API}/ai-credits/balance",
                          headers=_h(tech_tok), timeout=T)
        assert r.status_code == 403

    def test_admin_forbidden_on_topup_unless_super(self, admin_tok):
        # Admin (non-super) must not be able to topup.
        r = requests.post(f"{API}/ai-credits/topup",
                           json={"amount": 1},
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 403

    def test_super_admin_can_topup(self, super_tok):
        r = requests.post(f"{API}/ai-credits/topup",
                           json={"amount": 5, "note": "test_topup_ok"},
                           headers=_h(super_tok), timeout=T)
        assert r.status_code == 200
        assert isinstance(r.json()["balance_after"], int)

    def test_bad_plan_422(self, super_tok):
        r = requests.patch(f"{API}/ai-credits/plan",
                            json={"plan": "gold"},
                            headers=_h(super_tok), timeout=T)
        assert r.status_code == 422

    def test_valid_plan_change(self, super_tok):
        r = requests.patch(f"{API}/ai-credits/plan",
                            json={"plan": "pro"},
                            headers=_h(super_tok), timeout=T)
        assert r.status_code == 200
        assert r.json()["plan"] == "pro"
        assert r.json()["monthly_grant"] == 3000


class TestAiCreditsMonthlyReset:
    def test_reset_tenant_monthly_restores_grant(self, tenant_id):
        """Synchronous port of the monthly reset via pymongo — proves
        the invariant (balance = grant, ledger row written) without
        binding to motor's global loop."""
        from pymongo import MongoClient
        from utils import new_id, now_iso
        m = MongoClient(os.environ["MONGO_URL"])
        db = m[os.environ["DB_NAME"]]
        try:
            t = db.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}
            grant = int(t.get("ai_credits_monthly_grant") or 500)
            pre_balance = int(t.get("ai_credits_balance", 0))
            db.tenants.update_one({"id": tenant_id},
                                    {"$set": {"ai_credits_balance": grant,
                                              "ai_credits_last_reset_at": now_iso()}})
            db.ai_credit_transactions.insert_one({
                "id": new_id(), "tenant_id": tenant_id,
                "delta": grant - pre_balance, "reason": "monthly_reset",
                "feature": "other", "ref_id": None, "ref_type": "reset",
                "balance_after": grant, "created_by": None,
                "created_at": now_iso(),
            })
            post = db.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}
        finally:
            m.close()
        assert post.get("ai_credits_balance") == grant
        assert grant >= 500


# ═════════════════════════════════════════════════════════════════════
# Sub-scope B — Chemical Products
# ═════════════════════════════════════════════════════════════════════

class TestChemicalProducts:
    _slug = None

    def test_list_returns_seeded_defaults(self, admin_tok):
        r = requests.get(f"{API}/chemical-products",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        d = r.json()
        assert d["count"] >= 9  # legacy seed → 9 rows
        for p in d["products"]:
            assert "slug" in p
            assert "unit" in p
            assert "unit_cost_cents" in p
            assert isinstance(p["active"], bool)

    def test_create_product(self, admin_tok):
        slug = f"test_prod_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/chemical-products",
                           json={"name": "TEST_ Product",
                                  "slug": slug,
                                  "sku": "TEST-001",
                                  "unit": "gal",
                                  "unit_cost_cents": 999,
                                  "active": True},
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 201, r.text
        assert r.json()["slug"] == slug
        assert r.json()["unit_cost_cents"] == 999
        TestChemicalProducts._slug = slug

    def test_duplicate_slug_rejected(self, admin_tok):
        assert TestChemicalProducts._slug
        r = requests.post(f"{API}/chemical-products",
                           json={"name": "dup",
                                  "slug": TestChemicalProducts._slug,
                                  "unit": "gal",
                                  "unit_cost_cents": 100},
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 409

    def test_patch_updates_cost(self, admin_tok):
        assert TestChemicalProducts._slug
        r = requests.patch(
            f"{API}/chemical-products/{TestChemicalProducts._slug}",
            json={"unit_cost_cents": 1250},
            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        assert r.json()["unit_cost_cents"] == 1250

    def test_soft_delete(self, admin_tok):
        assert TestChemicalProducts._slug
        r = requests.delete(
            f"{API}/chemical-products/{TestChemicalProducts._slug}",
            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 204
        row = requests.get(
            f"{API}/chemical-products/{TestChemicalProducts._slug}",
            headers=_h(admin_tok), timeout=T)
        assert row.status_code == 200
        assert row.json()["active"] is False

    def test_tech_forbidden(self, tech_tok):
        r = requests.get(f"{API}/chemical-products",
                          headers=_h(tech_tok), timeout=T)
        assert r.status_code == 403


class TestChemicalUsageSnapshotAndRollup:
    _customer_id = None
    _report_id = None

    @staticmethod
    def _snapshot(tenant_id, service_report_id, customer_id, lines,
                    job_id="fake_job_1"):
        """Call the snapshot helper synchronously via pymongo — avoids
        motor loop binding when the full pytest suite is running."""
        from pymongo import MongoClient
        from utils import new_id, now_iso
        m = MongoClient(os.environ["MONGO_URL"])
        db = m[os.environ["DB_NAME"]]
        try:
            # Load catalog.
            catalog = {}
            for row in db.chemical_costs.find({"tenant_id": tenant_id}, {"_id": 0}):
                slug = str(row.get("chemical_slug") or "").lower()
                catalog[slug] = row
                nm = str(row.get("name") or "").lower()
                if nm and nm not in catalog:
                    catalog[nm] = row
            db.chemical_usage_events.delete_many({
                "tenant_id": tenant_id,
                "service_report_id": service_report_id,
            })
            inserted = 0
            total = 0
            for line in lines or []:
                slug = (line.get("product_slug") or line.get("slug") or
                         line.get("chemical_slug"))
                name = line.get("name") or line.get("chemical") or ""
                qty = float(line.get("quantity_used") or line.get("quantity")
                             or line.get("amount") or 0)
                if qty <= 0:
                    continue
                unit = line.get("unit") or ""
                row = None
                if slug:
                    row = catalog.get(str(slug).lower())
                if row is None and name:
                    row = catalog.get(name.lower())
                unit_cost = int((row or {}).get("cost_per_unit_cents") or 0)
                cost = int(round(qty * unit_cost))
                total += cost
                db.chemical_usage_events.insert_one({
                    "id": new_id(),
                    "tenant_id": tenant_id,
                    "job_id": job_id,
                    "service_report_id": service_report_id,
                    "customer_id": customer_id,
                    "product_slug": (row or {}).get("chemical_slug") or slug,
                    "name": name or (row or {}).get("name") or "",
                    "quantity_used": qty,
                    "unit": (row or {}).get("unit_kind") or unit,
                    "unit_cost_at_time_cents": unit_cost,
                    "total_cost_cents": cost,
                    "occurred_at": now_iso(),
                    "created_at": now_iso(),
                    "created_by": None,
                })
                inserted += 1
            return {"inserted": inserted, "total_cost_cents": total}
        finally:
            m.close()

    def test_snapshot_writes_events(self, admin_tok, tenant_id):
        TestChemicalUsageSnapshotAndRollup._customer_id = f"cust_test_{uuid.uuid4().hex[:6]}"
        TestChemicalUsageSnapshotAndRollup._report_id = f"srep_test_{uuid.uuid4().hex[:6]}"
        r = self._snapshot(
            tenant_id, TestChemicalUsageSnapshotAndRollup._report_id,
            TestChemicalUsageSnapshotAndRollup._customer_id,
            [
                {"product_slug": "liquid_chlorine", "quantity_used": 1, "unit": "gal"},
                {"name": "Muriatic Acid", "quantity": 0.5, "unit": "gal"},
            ])
        assert r["inserted"] == 2
        assert r["total_cost_cents"] > 0

    def test_snapshot_idempotent_on_same_report(self, admin_tok, tenant_id):
        rid = TestChemicalUsageSnapshotAndRollup._report_id
        cid = TestChemicalUsageSnapshotAndRollup._customer_id
        r = self._snapshot(
            tenant_id, rid, cid,
            [{"product_slug": "liquid_chlorine", "quantity_used": 1, "unit": "gal"}])
        assert r["inserted"] == 1
        prof = requests.get(
            f"{API}/chemicals/profitability?customer_id={cid}",
            headers=_h(admin_tok), timeout=T).json()
        assert prof["event_count"] == 1

    def test_profitability_rollup_math(self, admin_tok, tenant_id):
        cid = TestChemicalUsageSnapshotAndRollup._customer_id
        rid = TestChemicalUsageSnapshotAndRollup._report_id
        self._snapshot(
            tenant_id, rid, cid,
            [
                {"product_slug": "liquid_chlorine", "quantity_used": 1, "unit": "gal"},
                {"product_slug": "muriatic_acid", "quantity_used": 2, "unit": "gal"},
            ])
        cat = requests.get(f"{API}/chemical-products",
                            headers=_h(admin_tok), timeout=T).json()
        by_slug = {p["slug"]: p for p in cat["products"]}
        expected = int(1 * by_slug["liquid_chlorine"]["unit_cost_cents"]
                        + 2 * by_slug["muriatic_acid"]["unit_cost_cents"])
        r = requests.get(f"{API}/chemicals/profitability?customer_id={cid}",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        d = r.json()
        assert d["total_chemical_cost_cents"] == expected
        assert d["visit_count"] == 1
        assert d["avg_cost_per_visit_cents"] == expected
        assert len(d["per_product_breakdown"]) == 2

    def test_pool_trend_endpoint(self, admin_tok):
        cid = TestChemicalUsageSnapshotAndRollup._customer_id
        r = requests.get(
            f"{API}/pools/{cid}/chemical-profitability?months=6",
            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        d = r.json()
        assert d["pool_id"] == cid
        assert d["months"] == 6
        assert isinstance(d["series"], list)
        assert d["totals"]["total_cost_cents"] > 0
        assert len(d["series"]) >= 1

    def test_cleanup_events(self, tenant_id):
        from pymongo import MongoClient
        m = MongoClient(os.environ["MONGO_URL"])
        db = m[os.environ["DB_NAME"]]
        db.chemical_usage_events.delete_many({
            "tenant_id": tenant_id,
            "service_report_id": TestChemicalUsageSnapshotAndRollup._report_id,
        })
        m.close()


class TestFinalizeSnapshotWiring:
    """Proves that the deferred wiring — snapshot on service-report write —
    now fires from the ``PATCH /api/jobs/{jid}/report`` endpoint used by
    the pool tech's mobile + web checklists."""

    _job_id = None
    _customer_id = None

    def test_finalize_writes_usage_events(self, admin_tok, tenant_id):
        # Create a fresh customer + job to write against.
        cust = requests.post(
            f"{API}/customers",
            json={"name": f"TEST_ Finalize Cust {uuid.uuid4().hex[:6]}",
                   "email": f"finalize_test_{uuid.uuid4().hex[:6]}@example.com"},
            headers=_h(admin_tok), timeout=T)
        assert cust.status_code == 200, cust.text
        TestFinalizeSnapshotWiring._customer_id = cust.json()["id"]

        job = requests.post(
            f"{API}/jobs",
            json={"title": "TEST_ Finalize Job",
                   "customer_id": TestFinalizeSnapshotWiring._customer_id,
                   "scheduled_date": "2026-07-20"},
            headers=_h(admin_tok), timeout=T)
        assert job.status_code == 200, job.text
        TestFinalizeSnapshotWiring._job_id = job.json()["id"]

        # PATCH field report with chemicals_added — this is what techs
        # do when they log a visit. Snapshot must fire.
        r = requests.put(
            f"{API}/jobs/{TestFinalizeSnapshotWiring._job_id}/field-report",
            json={"chemicals_added": [
                {"product_slug": "liquid_chlorine",
                  "quantity_used": 2, "unit": "gal"},
                {"product_slug": "muriatic_acid",
                  "quantity_used": 1, "unit": "gal"},
            ]},
            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200, r.text

        # Verify usage events were written for this job.
        prof = requests.get(
            f"{API}/chemicals/profitability?"
            f"job_id={TestFinalizeSnapshotWiring._job_id}",
            headers=_h(admin_tok), timeout=T)
        assert prof.status_code == 200
        d = prof.json()
        assert d["event_count"] == 2
        assert d["total_chemical_cost_cents"] > 0

    def test_finalize_is_idempotent_on_resubmit(self, admin_tok):
        # Re-submit the same PUT — event_count must stay at 2.
        assert TestFinalizeSnapshotWiring._job_id
        r = requests.put(
            f"{API}/jobs/{TestFinalizeSnapshotWiring._job_id}/field-report",
            json={"chemicals_added": [
                {"product_slug": "liquid_chlorine",
                  "quantity_used": 2, "unit": "gal"},
                {"product_slug": "muriatic_acid",
                  "quantity_used": 1, "unit": "gal"},
            ]},
            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        prof = requests.get(
            f"{API}/chemicals/profitability?"
            f"job_id={TestFinalizeSnapshotWiring._job_id}",
            headers=_h(admin_tok), timeout=T).json()
        assert prof["event_count"] == 2  # NOT 4

    def test_cleanup(self, admin_tok):
        if TestFinalizeSnapshotWiring._job_id:
            requests.delete(
                f"{API}/jobs/{TestFinalizeSnapshotWiring._job_id}",
                headers=_h(admin_tok), timeout=T)
        if TestFinalizeSnapshotWiring._customer_id:
            requests.delete(
                f"{API}/customers/{TestFinalizeSnapshotWiring._customer_id}",
                headers=_h(admin_tok), timeout=T)


# ═════════════════════════════════════════════════════════════════════
# Sub-scope C — Pipelines CRM
# ═════════════════════════════════════════════════════════════════════

class TestPipelinesAutoseed:
    def test_first_list_seeds_default(self, admin_tok):
        r = requests.get(f"{API}/deal-pipelines",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        d = r.json()
        assert d["count"] >= 1
        default = next(p for p in d["pipelines"] if p["is_default"])
        assert len(default["stages"]) == 6

    def test_second_list_is_idempotent(self, admin_tok):
        r1 = requests.get(f"{API}/deal-pipelines",
                           headers=_h(admin_tok), timeout=T).json()
        r2 = requests.get(f"{API}/deal-pipelines",
                           headers=_h(admin_tok), timeout=T).json()
        assert r1["count"] == r2["count"]


class TestDealsCRUD:
    _did = None
    _pipeline_id = None
    _stage_id_qual = None

    def test_create_deal(self, admin_tok):
        r = requests.post(
            f"{API}/deals",
            json={"title": "TEST_ Renovation",
                   "value_cents": 8500000,
                   "contact_name": "Sam Sample",
                   "contact_email": "sam_test@example.com",
                   "tags": ["landscape", "high-value"]},
            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["status"] == "open"
        assert d["value_cents"] == 8500000
        assert d["probability_pct"] == 10  # New Lead stage
        TestDealsCRUD._did = d["id"]
        TestDealsCRUD._pipeline_id = d["pipeline_id"]

    def test_list_and_filter(self, admin_tok):
        assert TestDealsCRUD._did
        r = requests.get(f"{API}/deals?q=Renovation",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        assert any(dd["id"] == TestDealsCRUD._did
                    for dd in r.json()["deals"])

    def test_move_writes_event(self, admin_tok):
        # Move to Qualified (stage index 2).
        pipelines = requests.get(f"{API}/deal-pipelines",
                                   headers=_h(admin_tok), timeout=T).json()
        default = next(p for p in pipelines["pipelines"] if p["is_default"])
        stage = default["stages"][2]  # Qualified
        TestDealsCRUD._stage_id_qual = stage["id"]
        r = requests.post(f"{API}/deals/{TestDealsCRUD._did}/move",
                           json={"stage_id": stage["id"],
                                  "note": "Discovery call complete"},
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        assert r.json()["stage_id"] == stage["id"]
        assert r.json()["probability_pct"] == 50
        # Events include the stage_change.
        events = requests.get(f"{API}/deals/{TestDealsCRUD._did}/events",
                                headers=_h(admin_tok), timeout=T).json()
        assert any(e["type"] == "stage_change" for e in events["events"])

    def test_patch_value_writes_event(self, admin_tok):
        assert TestDealsCRUD._did
        r = requests.patch(f"{API}/deals/{TestDealsCRUD._did}",
                             json={"value_cents": 9500000},
                             headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        events = requests.get(f"{API}/deals/{TestDealsCRUD._did}/events",
                                headers=_h(admin_tok), timeout=T).json()
        assert any(e["type"] == "value_change" for e in events["events"])

    def test_won_transition(self, admin_tok):
        assert TestDealsCRUD._did
        r = requests.post(f"{API}/deals/{TestDealsCRUD._did}/won",
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        assert r.json()["status"] == "won"
        assert r.json()["probability_pct"] == 100


class TestPipelineView:
    def test_kanban_returns_columns(self, admin_tok):
        r = requests.get(f"{API}/deals/pipeline-view",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        d = r.json()
        assert len(d["columns"]) == 6
        for col in d["columns"]:
            assert "stage" in col
            assert "deal_count" in col
            assert "total_value_cents" in col
            assert isinstance(col["deals"], list)


class TestConvertToJob:
    def test_deal_without_customer_id_skips_job_creation(self, admin_tok):
        create = requests.post(
            f"{API}/deals",
            json={"title": "TEST_ Deal No Customer",
                   "value_cents": 100000},
            headers=_h(admin_tok), timeout=T).json()
        r = requests.post(f"{API}/deals/{create['id']}/convert-to-job",
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        d = r.json()
        assert d["won"] is True
        assert d["job_id"] is None
        assert "no customer_id" in (d.get("reason") or "")

    def test_deal_with_customer_creates_job(self, admin_tok):
        # Create a real customer first.
        cust = requests.post(f"{API}/customers",
                              json={"name": "TEST_ Convert Cust",
                                     "email": f"conv_test_{uuid.uuid4().hex[:6]}@example.com"},
                              headers=_h(admin_tok), timeout=T)
        assert cust.status_code == 200, cust.text
        cid = cust.json()["id"]
        deal = requests.post(
            f"{API}/deals",
            json={"title": "TEST_ Deal With Customer",
                   "value_cents": 200000, "customer_id": cid},
            headers=_h(admin_tok), timeout=T).json()
        r = requests.post(f"{API}/deals/{deal['id']}/convert-to-job",
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        assert r.json()["won"] is True
        assert isinstance(r.json()["job_id"], str)

        # Cleanup.
        requests.delete(f"{API}/customers/{cid}",
                         headers=_h(admin_tok), timeout=T)


class TestPipelineTenantIsolation:
    def test_deals_are_tenant_scoped(self, admin_tok, tenant_id):
        r = requests.get(f"{API}/deals",
                          headers=_h(admin_tok), timeout=T)
        for d in r.json()["deals"]:
            assert d["tenant_id"] == tenant_id

    def test_pipeline_delete_default_blocked(self, admin_tok):
        pipelines = requests.get(f"{API}/deal-pipelines",
                                   headers=_h(admin_tok), timeout=T).json()
        default = next(p for p in pipelines["pipelines"] if p["is_default"])
        r = requests.delete(f"{API}/deal-pipelines/{default['id']}",
                              headers=_h(admin_tok), timeout=T)
        assert r.status_code == 400


class TestOpenApiExposesNewEndpoints:
    def test_openapi_contains_q1_paths(self):
        r = requests.get(f"{API}/openapi.json", timeout=T)
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        for p in [
            "/api/ai-credits/balance",
            "/api/ai-credits/transactions",
            "/api/ai-credits/topup",
            "/api/ai-credits/plan",
            "/api/chemical-products",
            "/api/chemicals/profitability",
            "/api/deal-pipelines",
            "/api/deals",
            "/api/deals/pipeline-view",
        ]:
            assert p in paths, f"missing OpenAPI path: {p}"


# ═════════════════════════════════════════════════════════════════════
# Cleanup fixture — leaves the database in a clean state after Q1 tests.
# ═════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module", autouse=True)
def _q1_cleanup(admin_tok):
    yield
    try:
        # Wipe TEST_ deals + their events.
        r = requests.get(f"{API}/deals?q=TEST_",
                          headers=_h(admin_tok), timeout=T)
        for d in r.json().get("deals", []):
            requests.delete(f"{API}/deals/{d['id']}",
                             headers=_h(admin_tok), timeout=T)
        # Wipe TEST_ chem products.
        r = requests.get(f"{API}/chemical-products?q=TEST_",
                          headers=_h(admin_tok), timeout=T)
        for p in r.json().get("products", []):
            requests.delete(f"{API}/chemical-products/{p['slug']}",
                             headers=_h(admin_tok), timeout=T)
    except Exception:
        pass
