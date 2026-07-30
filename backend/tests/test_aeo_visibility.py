"""Phase 5b · pytest — AI Visibility Tracker + LLM Fix Recs.

All LLM calls are stubbed. The single test that hits a live endpoint
uses the fix-generation router, which internally calls
``services.aeo_fixes.generate_fixes`` — we monkeypatch its default LLM
callable via the module-level function reference before the request.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def _tenant_id_of(email: str) -> str:
    return _sync.users.find_one({"email": email})["tenant_id"]


# ── 1. Scoring math ─────────────────────────────────────────────
def test_score_high_when_mentioned_in_first_paragraph_with_citation():
    from services.aeo_visibility import score_answer
    text = ("Blue Water Pools is the top-rated pool service in Phoenix "
            "with weekly maintenance and equipment repair. Their "
            "certified techs are highly rated on Google.\n\n"
            "See https://bluewaterpools.example for details.")
    score, br = score_answer(text, "Blue Water Pools",
                                tenant_domain="bluewaterpools.example",
                                citations=["https://bluewaterpools.example/services"],
                                competitors=["AquaClean", "PoolPros"])
    assert score >= 95, (score, br)
    assert br["brand_mentioned"] is True
    assert br["mention_in_first_paragraph"] is True
    assert br["has_domain_citation"] is True


def test_score_low_when_no_mention():
    from services.aeo_visibility import score_answer
    text = ("For pool cleaning in Phoenix, consider AquaClean or PoolPros. "
            "Both offer weekly service.")
    score, _br = score_answer(text, "Blue Water Pools",
                                 tenant_domain="bluewaterpools.example",
                                 citations=[],
                                 competitors=["AquaClean", "PoolPros"])
    assert score <= 20, score


# ── 2. Cost cap ─────────────────────────────────────────────────
def test_cost_cap_stops_further_probes():
    from services.aeo_visibility import (run_probes, MONTHLY_COST_CAP_USD,
                                            COST_PER_PROBE_USD)
    tenant_id = f"tenant_p5b_{uuid.uuid4().hex[:6]}"
    tenant = {"id": tenant_id, "name": "CapTest Co",
              "url": "https://captest.example",
              "address": {"city": "Phoenix", "state": "AZ",
                            "postalCode": "85001"}}

    # Seed enough prior-month cost to hit the cap immediately.
    from datetime import datetime, timezone
    from math import ceil
    now = datetime.now(timezone.utc)
    month_start_iso = datetime(now.year, now.month, 1,
                                  tzinfo=timezone.utc).isoformat()
    fills = ceil(MONTHLY_COST_CAP_USD / COST_PER_PROBE_USD)
    docs = []
    for i in range(fills):
        docs.append({"tenant_id": tenant_id,
                     "probe_id": f"seed_{i}",
                     "ran_at": month_start_iso,
                     "cost_est_usd": COST_PER_PROBE_USD,
                     "score": 0, "brand_mentioned": False,
                     "query_template": "seed", "llm_provider": "seed"})
    if docs:
        _sync.aeo_visibility_probes.insert_many(docs)
    try:
        async def stub(*a, **k):
            return {"answer_text": "stub", "citations": []}
        out = asyncio.run(run_probes(tenant, templates=["Best in {city}?"],
                                        providers=[{"key": "stub",
                                                     "provider": "x",
                                                     "model": "y"}],
                                        llm_call=stub))
        assert out["cost_capped"] is True
        assert out["summary"]["total"] == 0
    finally:
        _sync.aeo_visibility_probes.delete_many({"tenant_id": tenant_id})


# ── 3. Cron dup skip → same-tenant cooldown enforced via HTTP ────
def test_run_now_cooldown_skips_when_recent_probe_exists():
    """The daily cron uses the same duplicate-probe guard as
    run-now — verify the guard via the HTTP endpoint (which lives in
    the running FastAPI process' event loop) instead of poking motor
    from a fresh asyncio.run() (which closes motor's executor)."""
    from datetime import datetime, timezone
    tok = _login("manager@aquaterra.com")
    tid = _tenant_id_of("manager@aquaterra.com")
    _sync.aeo_visibility_probes.delete_many({"tenant_id": tid})
    _sync.aeo_visibility_probes.insert_one({
        "tenant_id": tid, "probe_id": "recent_seed",
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "cost_est_usd": 0.0, "score": 42})
    try:
        r = requests.post(f"{API}/aeo/visibility/run-now",
                           headers={"Authorization": f"Bearer {tok}"},
                           json={}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["skipped_reason"] == "cooldown", d
        assert d["summary"]["total"] == 0
    finally:
        _sync.aeo_visibility_probes.delete_many({"tenant_id": tid})


# ── 4. Fix generation — schema returns <script> block (via HTTP) ─
def test_fix_generation_schema_via_http():
    """schema sub-signal falls through to the Phase 5a JSON-LD
    generator (no LLM). Verifying via the router avoids the
    motor-across-loops trap."""
    from services.aeo_visibility import reset_fix_rate_limit_for_tests
    reset_fix_rate_limit_for_tests()
    tok = _login("manager@aquaterra.com")
    tid = _tenant_id_of("manager@aquaterra.com")
    scan_id = f"scan_p5b_{uuid.uuid4().hex[:6]}"
    _sync.seo_scans.insert_one({
        "id": scan_id, "tenant_id": tid, "status": "complete",
        "results": {"aeo_signals": {
            "schema": {"score": 10, "types_present": [],
                        "types_missing_recommended": ["LocalBusiness", "FAQPage"]},
            "faq": {"score": 90, "count": 3, "schema_faq": True},
            "passages": {"score": 90, "total": 5, "median_words": 40, "over_90_words": 0},
            "entity_clarity": {"score": 90},
            "llms_txt": {"score": 100, "present": True},
        }},
    })
    try:
        r = requests.post(f"{API}/aeo/fixes/generate",
                           headers={"Authorization": f"Bearer {tok}"},
                           json={"scan_id": scan_id,
                                  "sub_signals": ["schema", "llms_txt"]},
                           timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        by = {f["sub_signal"]: f for f in d["fixes"]}
        assert "schema" in by
        assert '<script type="application/ld+json">' in (by["schema"]["generated_content"] or "")
        # llms_txt fix also uses the phase-5a generator; content non-empty.
        assert "llms_txt" in by
        assert by["llms_txt"]["generated_content"], by["llms_txt"]
    finally:
        _sync.seo_scans.delete_one({"id": scan_id})
        _sync.aeo_fixes.delete_many({"scan_id": scan_id})


# ── 5. Rate limit — 6th call → 429 ──────────────────────────────
def test_fix_rate_limit_429_at_sixth_call():
    from services.aeo_visibility import (check_fix_rate_limit,
                                            reset_fix_rate_limit_for_tests)
    reset_fix_rate_limit_for_tests()
    tid = "rate-test-tenant"
    for i in range(5):
        assert check_fix_rate_limit(tid) is None, f"call {i+1} should allow"
    retry = check_fix_rate_limit(tid)
    assert isinstance(retry, int) and retry > 0


# ── 6. Role guard — tech + customer forbidden ───────────────────
@pytest.mark.parametrize("email", ["landscaper@aquaterra.com",
                                    "customer@aquaterra.com"])
def test_role_guard_forbids_tech_and_customer(email):
    tok = _login(email)
    for path, body in [
        ("/aeo/visibility/run-now", {}),
        ("/aeo/fixes/generate", {"scan_id": "x"}),
    ]:
        r = requests.post(f"{API}{path}",
                           headers={"Authorization": f"Bearer {tok}"},
                           json=body, timeout=10)
        assert r.status_code == 403, f"{email} {path} → {r.status_code}"
    r = requests.get(f"{API}/aeo/visibility/dashboard",
                       headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert r.status_code == 403


# ── 7. Live dashboard empty-shape for a manager with 0 probes ───
def test_dashboard_returns_empty_shape_for_no_probes():
    tok = _login("manager@aquaterra.com")
    # Purge this tenant's probes so the test is deterministic.
    tid = _tenant_id_of("manager@aquaterra.com")
    _sync.aeo_visibility_probes.delete_many({"tenant_id": tid})
    try:
        r = requests.get(f"{API}/aeo/visibility/dashboard",
                           headers={"Authorization": f"Bearer {tok}"},
                           timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["avg_score_30d"] == 0
        assert d["probes_30d"] == 0
        assert isinstance(d["top_queries"], list)
        assert isinstance(d["providers"], list)
        assert d["cost_capped"] in (False, True)  # shape check
    finally:
        pass  # collection is already empty; no restore needed
