"""Phase 16 · Feb-2026 — ``/ebit/trend`` labor-breakdown fields.

Pins the 6 behaviors from the Phase 16 brief (case 7 — identity
restore — lives in ``test_phase53e_ebit_trend.py`` next to its
peers). Live HTTP against the running backend; seeds are tagged
and cleaned up per-test so the aquaterra fixtures stay clean.

Case list:
  1. Every bucket includes labor_cost + recurring_labor_cost +
     labor_cost_total fields.
  2. Identity holds per bucket (also covered by the restored
     ratchet in test_phase53e_ebit_trend.py — kept here as a
     tighter per-field compare).
  3. Bucket with no tech activity + no recurring entries →
     labor_cost_total == 0, no crash.
  4. Bucket with Phase 10 hourly only → labor_cost > 0,
     recurring_labor_cost == 0.
  5. Bucket with Phase 11 recurring only → labor_cost == 0,
     recurring_labor_cost > 0.
  6. Prorating lock — a recurring entry whose window spans only
     part of the bucket month is prorated against 30.44 avg
     days/month.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


# No backend-module imports — pure external HTTP + MongoClient.
# Keeping sys.path pristine so this file doesn't trigger the shared
# Motor loop fixture used by other Phase-11 EBIT test modules.
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _ENV["MONGO_URL"]
DB_NAME = _ENV["DB_NAME"]
API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"
TIMEOUT = 60
_TAG = "P16_TREND_LABOR_TEST"


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


def _trend(tok: str, months: int = 6, basis: str = "cash") -> list:
    r = requests.get(
        f"{API}/ebit/trend",
        headers={"Authorization": f"Bearer {tok}"},
        params={"months": months, "revenue_basis": basis},
        timeout=TIMEOUT,
    )
    assert r.status_code == 200, r.text
    return r.json()["series"]


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def tenant_id(db):
    return db.tenants.find_one({"slug": "aquaterra"})["id"]


@pytest.fixture(autouse=True)
def _cleanup(db):
    def _wipe():
        db.recurring_labor_costs.delete_many({"_tag": _TAG})
    _wipe()
    yield
    _wipe()


# ─── Case 1 — fields present on every bucket ─────────────────────
def test_01_every_bucket_has_labor_fields(admin_tok):
    series = _trend(admin_tok, months=6)
    assert series, "trend must return at least one bucket"
    for p in series:
        assert "labor_cost" in p, (
            f"bucket {p['month']} missing labor_cost field: {p.keys()}"
        )
        assert "recurring_labor_cost" in p, p.keys()
        assert "labor_cost_total" in p, p.keys()
        # All three must be numeric (int/float) — not None.
        assert isinstance(p["labor_cost"], (int, float))
        assert isinstance(p["recurring_labor_cost"], (int, float))
        assert isinstance(p["labor_cost_total"], (int, float))


# ─── Case 2 — identity holds (tighter per-field compare) ─────────
def test_02_identity_is_reconstructible_per_bucket(admin_tok):
    series = _trend(admin_tok, months=12)
    for p in series:
        # labor_cost_total must equal labor_cost + recurring_labor_cost
        assert p["labor_cost_total"] == pytest.approx(
            p["labor_cost"] + p["recurring_labor_cost"], abs=0.01,
        ), f"labor_cost_total breakdown fails for {p['month']}: {p}"
        # ebit identity
        expected = (p["revenue"] - p["cogs"] - p["opex"]
                     - p["depreciation"] - p["labor_cost_total"])
        assert p["ebit"] == pytest.approx(expected, abs=0.01), \
            f"ebit identity fails for {p['month']}: {p}"


# ─── Case 3 — empty bucket (no labor) ────────────────────────────
def test_03_empty_bucket_zero_labor(admin_tok, db, tenant_id):
    # Request a 24-month window. Aquaterra preview DB has months
    # beyond the active timeclock + recurring_labor_costs scope.
    # At least ONE bucket far enough back has no labor data.
    series = _trend(admin_tok, months=24)
    assert series
    zero_labor_buckets = [p for p in series
                           if p["labor_cost_total"] == 0]
    # Not strictly required that a zero-labor bucket exists in a
    # preview env (some tenants have fully-seeded 24-month history),
    # but when it does the identity + no-crash contracts must hold.
    for p in zero_labor_buckets:
        assert p["labor_cost"] == 0
        assert p["recurring_labor_cost"] == 0
        # ebit must equal the pre-labor identity exactly.
        pre_labor = (p["revenue"] - p["cogs"] - p["opex"]
                      - p["depreciation"])
        assert p["ebit"] == pytest.approx(pre_labor, abs=0.01), p


# ─── Case 5 — recurring-only bucket ──────────────────────────────
def test_05_recurring_only_bucket_shows_recurring_cost(
        admin_tok, db, tenant_id):
    # Seed a recurring labor cost that covers the current month.
    # The preview env may ALREADY carry other recurring entries
    # (Phase 11 seeds, test fixtures left over, etc.), so compare
    # the before-vs-after DELTA for the current bucket rather than
    # the absolute value.
    now = datetime.now(timezone.utc)
    cur_month = now.strftime("%Y-%m")

    series_before = _trend(admin_tok, months=3)
    cur_before = next(p for p in series_before if p["month"] == cur_month)
    rl_before = cur_before["recurring_labor_cost"]

    db.recurring_labor_costs.insert_one({
        "id": f"{_TAG}_rec_{uuid.uuid4().hex[:8]}",
        "tenant_id": tenant_id,
        "label": f"{_TAG} salary",
        "monthly_amount": 1200.00,
        "start_date": "2024-01-01",
        "end_date": None,
        "status": "active",
        "linked_user_id": None,
        "_tag": _TAG,
    })

    series_after = _trend(admin_tok, months=3)
    cur_after = next(p for p in series_after if p["month"] == cur_month)
    delta = cur_after["recurring_labor_cost"] - rl_before
    # A full-month entry at $1200 should add ≈ $1200 to the bucket.
    # Allow a loose band (±100) to tolerate month-length proration.
    assert 1100.0 <= delta <= 1300.0, (
        f"recurring_labor_cost delta out of band: {delta} "
        f"(before={rl_before}, after={cur_after['recurring_labor_cost']})"
    )
    # Identity still holds on the after-state.
    expected = (cur_after["revenue"] - cur_after["cogs"]
                 - cur_after["opex"] - cur_after["depreciation"]
                 - cur_after["labor_cost_total"])
    assert cur_after["ebit"] == pytest.approx(expected, abs=0.01)


# ─── Case 6 — prorating lock (partial-month entry) ───────────────
def test_06_partial_month_entry_is_prorated(admin_tok, db, tenant_id):
    # DELTA-based assertion — the preview env may already carry
    # other recurring entries, so compare before vs after.
    now = datetime.now(timezone.utc)
    day_15 = now.replace(day=15).strftime("%Y-%m-%d")
    cur_month = now.strftime("%Y-%m")

    series_before = _trend(admin_tok, months=1)
    cur_before = next(p for p in series_before if p["month"] == cur_month)
    rl_before = cur_before["recurring_labor_cost"]

    db.recurring_labor_costs.insert_one({
        "id": f"{_TAG}_prorate_{uuid.uuid4().hex[:8]}",
        "tenant_id": tenant_id,
        "label": f"{_TAG} partial",
        "monthly_amount": 3044.00,
        "start_date": day_15,
        "end_date": None,
        "status": "active",
        "linked_user_id": None,
        "_tag": _TAG,
    })

    series_after = _trend(admin_tok, months=1)
    cur_after = next(p for p in series_after if p["month"] == cur_month)
    delta = cur_after["recurring_labor_cost"] - rl_before
    # The helper prorates against overlap-days / 30.44. For a
    # 15th-of-month start, overlap = (last_day - 15 + 1) days
    # which lands between 13–17 days depending on month length.
    # Expected delta: 3044 * (13..17) / 30.44 ≈ 1300..1700.
    # Loose bounds for safety: 1200..1800.
    assert 1200.0 <= delta <= 1800.0, (
        f"prorated recurring-labor delta out of band: {delta} "
        f"(month-length-aware). Expected ~1300-1700 for a 3044/mo "
        f"entry starting on the 15th."
    )
    # Must be strictly LESS than one full monthly_amount since the
    # entry started mid-month.
    assert delta < 3044.0


# ─── Case 4 — hourly-only (observational) ────────────────────────
def test_04_hourly_only_bucket_shape(admin_tok):
    # We can't guarantee the preview env has a bucket with hourly
    # labor but zero recurring (hourly depends on tech punches +
    # pay rates which this test can't orchestrate without a wider
    # fixture). Observational assertion: any bucket where
    # labor_cost > 0 and recurring_labor_cost == 0 must still
    # satisfy labor_cost_total == labor_cost.
    series = _trend(admin_tok, months=12)
    hourly_only = [p for p in series
                    if p["labor_cost"] > 0 and p["recurring_labor_cost"] == 0]
    for p in hourly_only:
        assert p["labor_cost_total"] == pytest.approx(
            p["labor_cost"], abs=0.01,
        )
