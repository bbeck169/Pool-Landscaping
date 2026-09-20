"""P0 · Feb-2026 — Checklist / 429-leak regression guards.

Diagnostic tests locking three invariants exposed by a mobile-app P0
report ("Unable to open checklist — Request failed (429)"):

  H1 — the D2D Zillow rate limiter must ONLY scope Zillow endpoints,
       never bleed into unrelated tenant routes.
  H2 — the unified ``services.provider_health.cron`` probing MUST NOT
       count against any tenant's monthly BYO cap.
  H3 — the mobile checklist load path
       (``GET /api/jobs/{id}`` + ``GET /api/jobs/{id}/service-report``)
       must never 429 under normal single-user load.

These are the "belt-and-suspenders" tests the hotfix report calls for.
They run against the live backend on ``localhost:8001``, seeded users.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import List

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API = "http://localhost:8001/api"
_sync = _shared_db()
def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _tenant_id(tok: str) -> str:
    r = requests.get(f"{API}/tenants/current",
                       headers=_hdrs(tok), timeout=15)
    r.raise_for_status()
    return r.json()["id"]


def _pick_job_id_for_tech(tok: str) -> str:
    """Grab any job assigned to the currently authenticated tech.

    Falls back to the tenant's first job if the assignment lookup
    returns nothing — a super-user token still needs *some* jid to
    exercise the checklist load path.
    """
    r = requests.get(f"{API}/jobs?limit=1",
                       headers=_hdrs(tok), timeout=15)
    r.raise_for_status()
    payload = r.json()
    jobs = payload if isinstance(payload, list) else payload.get("jobs", [])
    assert jobs, "seed did not produce a job for the tech to open"
    return jobs[0]["id"]


# ══════════════════════════════════════════════════════════════════
# H3 · Checklist load NEVER 429s under normal load
# ══════════════════════════════════════════════════════════════════
def test_checklist_endpoint_never_429s_under_normal_load():
    """100-request burst against the exact two endpoints the mobile
    checklist screen hits on open. The screen surfaces
    ``"Unable to open checklist — Request failed (429)"`` if either
    returns 429 (see /app/mobile/app/job/[id]/checklist.tsx L195).
    None of these calls has a legitimate 429 path today; this test
    locks that in so the I1.7.e Messaging / AI / Maps / Calendars /
    Payments migration cannot silently regress it.
    """
    tok = _login("super@aquaterra.com")
    jid = _pick_job_id_for_tech(tok)

    codes: List[int] = []
    for _ in range(50):
        r = requests.get(f"{API}/jobs/{jid}",
                            headers=_hdrs(tok), timeout=15)
        codes.append(r.status_code)
    for _ in range(50):
        r = requests.get(f"{API}/jobs/{jid}/service-report",
                            headers=_hdrs(tok), timeout=15)
        codes.append(r.status_code)

    four_two_nines = [c for c in codes if c == 429]
    assert four_two_nines == [], (
        f"checklist load endpoints returned {len(four_two_nines)} × 429 "
        f"under a 100-request burst — a rate limiter has leaked. "
        f"Full status distribution: {sorted(set(codes))}"
    )
    # All responses must be 2xx — 401/403/404 would mean the seed shape
    # drifted, not that the invariant was broken. Fail loudly either way.
    non_2xx = [c for c in codes if not (200 <= c < 300)]
    assert non_2xx == [], (
        f"checklist load endpoints returned non-2xx codes: "
        f"{sorted(set(non_2xx))} · full distribution: {sorted(set(codes))}"
    )


def test_checklist_endpoint_never_429s_for_technician():
    """Same invariant, but from the tech role — the actual mobile
    audience. Techs on jobs they own MUST NOT get 429 on either load
    endpoint."""
    tok = _login("mike@aquaterra.com")
    # Find a job the tech is on.
    r = requests.get(f"{API}/jobs?assigned_to_me=true&limit=1",
                       headers=_hdrs(tok), timeout=15)
    if r.status_code != 200:
        pytest.skip(f"tech can't list own jobs (status={r.status_code})")
    payload = r.json()
    jobs = payload if isinstance(payload, list) else payload.get("jobs", [])
    if not jobs:
        pytest.skip("seed did not produce a job assigned to the tech")
    jid = jobs[0]["id"]

    for _ in range(20):
        r1 = requests.get(f"{API}/jobs/{jid}",
                            headers=_hdrs(tok), timeout=15)
        r2 = requests.get(f"{API}/jobs/{jid}/service-report",
                            headers=_hdrs(tok), timeout=15)
        assert r1.status_code != 429, "GET /jobs/{id} returned 429 for tech"
        assert r2.status_code != 429, "GET /jobs/{id}/service-report returned 429 for tech"


# ══════════════════════════════════════════════════════════════════
# H1 · D2D Zillow rate limiter is scoped ONLY to Zillow endpoints
# ══════════════════════════════════════════════════════════════════
def test_zillow_rate_limiter_only_scopes_zillow_endpoints():
    """Simulate a Zillow-cap-exhausted tenant by writing usage rows
    that would trip ``services.zillow_rate_limit.check_caps`` on the
    NEXT Zillow lookup — then hit five unrelated endpoints from the
    mobile checklist load path and adjacent surfaces. None of them
    may return 429.

    Regression scenario: the checklist P0 report suggested the
    Zillow limiter might be applied broadly (e.g. as middleware or
    a shared-prefix decorator). It is not — the limiter is called
    only from ``fetch_zillow_property()`` inside
    ``services/enrichment/zillow.py``, itself invoked only from
    ``POST /api/d2d/prospects/{id}/enrich-zillow`` and the
    admin lookup routes. This test locks that scoping in.
    """
    admin = _login("super@aquaterra.com")
    tid = _tenant_id(admin)
    from datetime import datetime, timezone

    # Simulate cap exhaustion at both the tenant + tech level.
    from services.zillow_rate_limit import TECH_DAILY_CAP, TENANT_MONTHLY_BUDGET_DEFAULT
    period_month = datetime.now(timezone.utc).strftime("%Y-%m")
    period_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for _ in range(TENANT_MONTHLY_BUDGET_DEFAULT + 5):
        _sync.zillow_usage.insert_one({
            "tenant_id": tid, "tech_id": "test-fake-tech",
            "period_month": period_month, "period_day": period_day,
            "at": datetime.now(timezone.utc),
            "endpoint": "test/fake",
        })
    try:
        jid = _pick_job_id_for_tech(admin)
        # ── Endpoints from the mobile checklist load path + adjacents ──
        probes = [
            ("GET", f"/jobs/{jid}"),
            ("GET", f"/jobs/{jid}/service-report"),
            ("GET", "/training/modules"),
            ("GET", "/d2d/knocks"),               # unrelated D2D read
            ("GET", "/tenants/me/integrations/schemas"),
        ]
        for method, path in probes:
            r = requests.request(method, f"{API}{path}",
                                 headers=_hdrs(admin), timeout=15)
            assert r.status_code != 429, (
                f"{method} {path} returned 429 while Zillow tenant "
                f"cap was exhausted — the Zillow rate limiter has "
                f"leaked into an unrelated endpoint. Body: "
                f"{r.text[:200]}"
            )
    finally:
        _sync.zillow_usage.delete_many(
            {"tenant_id": tid, "tech_id": "test-fake-tech"},
        )


# ══════════════════════════════════════════════════════════════════
# H2 · Health cron probes do NOT count against tenant caps
# ══════════════════════════════════════════════════════════════════
def test_health_cron_probes_do_not_count_against_cap():
    """The unified ``services.provider_health.cron`` calls
    ``provider.test_connection(...)`` on every connected BYO
    provider every 15 minutes. That MUST NOT increment
    ``tenant_payments_usage.charge_count`` /
    ``tenant_payments_usage.ops_total`` — otherwise a heavily-
    probed tenant would burn through their monthly cap and every
    subsequent legitimate charge would 429.

    Structural invariant: the cron module MUST NOT import or
    reference any of the ``record_op`` / ``enforce_cap`` /
    ``record_call`` usage-mutating helpers. It may only touch
    ``services.provider_health.store`` (writes to the health
    collection, never usage) and the provider families'
    ``test_connection`` methods (which are pure network probes).
    """
    import inspect
    from services.provider_health import cron as health_cron

    src = inspect.getsource(health_cron)
    forbidden = [
        "record_op",           # payments_byo.usage
        "enforce_cap_or_raise",# payments_byo.usage / maps.usage
        "record_call",         # zillow_rate_limit
        "check_and_charge",    # zillow_rate_limit
        "usage.record",        # generic
        "increment_usage",     # generic
    ]
    for sym in forbidden:
        assert sym not in src, (
            f"services.provider_health.cron references '{sym}' — "
            f"health probes would count against a tenant cap and "
            f"cause exactly the P0 429-leak the mobile checklist "
            f"screenshot showed."
        )
    # Runtime probe: the only writes the cron performs must land in
    # the health collection, never in a usage collection. Verify by
    # inspecting the module's imports.
    assert "from services.payments_byo.usage import" not in src
    assert "from services.zillow_rate_limit import" not in src
    assert "from services.maps.usage import" not in src


def test_health_cron_writes_only_land_in_health_collection():
    """Complementary structural test on
    ``services.provider_health.store`` — the ONLY collection it may
    write to is ``tenant_provider_health``. If someone adds a
    ``db.tenant_payments_usage.update_one`` here, this test flags it."""
    import inspect
    from services.provider_health import store as health_store

    src = inspect.getsource(health_store)
    for forbidden_coll in ("tenant_payments_usage", "zillow_usage",
                             "tenant_ai_usage", "tenant_maps_usage",
                             "tenant_calendars_usage"):
        assert forbidden_coll not in src, (
            f"services.provider_health.store writes to '{forbidden_coll}' — "
            f"health-cron probes would count against a tenant cap."
        )
