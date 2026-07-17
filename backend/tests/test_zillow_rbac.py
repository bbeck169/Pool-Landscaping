"""Phase 56.9b Step 5 — Zillow rate-limit + budget + cache tests.

Tests exercise the pure-service functions directly against Mongo,
which is the correct scope for this session (Option A: RBAC swap is
Step 8, deferred to the next session — so we don't test the wired
endpoint gates yet, just the guardrail primitives).

Test IDs mirror the ship-report evidence cases:
  1. `test_tech_within_daily_cap_allowed`
  2. `test_tech_hits_daily_cap_denied_with_reset`
  3. `test_tenant_budget_reaches_100pct_denied_for_admin`
  4. `test_tenant_budget_warns_at_90pct`
  5. `test_super_admin_override_writes_audit_event`
  6. `test_cache_hit_does_not_decrement_counters`
  7. `test_widget_endpoint_admin_ok_tech_403`
"""
import asyncio
import os
import uuid
import sys
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from services.zillow_rate_limit import (  # noqa: E402
    check_caps, log_call, apply_override_or_fail,
    read_cache, write_cache, address_hash,
    TECH_DAILY_CAP, TECH_MONTHLY_CAP, TENANT_MONTHLY_BUDGET_DEFAULT,
    _month_key, _now,
)


_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL")
        or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
BE_ENV = dotenv_values("/app/backend/.env")


_LOOP = asyncio.new_event_loop()


def _run(coro):
    """Reuse a single event loop across all tests. The Motor client in
    services/zillow_rate_limit.py is bound to the first loop it sees;
    creating fresh loops per test triggers "attached to a different
    loop" errors."""
    return _LOOP.run_until_complete(coro)


def _mongo():
    c = AsyncIOMotorClient(BE_ENV["MONGO_URL"])
    return c[BE_ENV["DB_NAME"]]


async def _seed_tenant_and_users():
    """Isolated per-test tenant so we never touch aquaterra usage."""
    db = _mongo()
    tid = f"56.9b-test-{uuid.uuid4().hex[:8]}"
    tenant = {"id": tid, "slug": tid, "name": "56.9b test",
              "zillow_monthly_budget": TENANT_MONTHLY_BUDGET_DEFAULT}
    await db.tenants.insert_one(tenant)
    tech = {"id": f"{tid}-tech", "tenant_id": tid, "role": "technician",
            "name": "Test Tech", "email": f"{tid}-tech@t.co"}
    admin = {"id": f"{tid}-admin", "tenant_id": tid, "role": "admin",
             "name": "Test Admin", "email": f"{tid}-admin@t.co"}
    sadmin = {"id": f"{tid}-sadmin", "tenant_id": tid, "role": "super_admin",
              "name": "Root", "email": f"{tid}-sadmin@t.co"}
    await db.users.insert_many([tech, admin, sadmin])
    return tenant, tech, admin, sadmin


async def _cleanup(tenant_id: str):
    db = _mongo()
    await db.tenants.delete_many({"id": tenant_id})
    await db.users.delete_many({"tenant_id": tenant_id})
    await db.zillow_usage.delete_many({"tenant_id": tenant_id})
    await db.zillow_audit.delete_many({"tenant_id": tenant_id})


# ─── 1. Tech within daily cap → allowed ───────────────────────────────
def test_tech_within_daily_cap_allowed():
    async def go():
        tenant, tech, *_ = await _seed_tenant_and_users()
        try:
            caps = await check_caps(tech, tenant)
            assert caps["allowed"] is True
            assert caps["reason"] is None
            assert caps["usage"]["tech_daily_cap"] == TECH_DAILY_CAP
            assert caps["usage"]["tech_monthly_cap"] == TECH_MONTHLY_CAP
            assert caps["tenant_budget"] == TENANT_MONTHLY_BUDGET_DEFAULT
            assert caps["reset_at"] is None
        finally:
            await _cleanup(tenant["id"])
    _run(go())


# ─── 2. Tech at daily cap → denied with reset_at ─────────────────────
def test_tech_hits_daily_cap_denied_with_reset():
    async def go():
        tenant, tech, *_ = await _seed_tenant_and_users()
        try:
            for i in range(TECH_DAILY_CAP):
                await log_call(tech, tenant, "/property/lookup", f"addr {i}")
            caps = await check_caps(tech, tenant)
            assert caps["allowed"] is False
            assert caps["reason"] == "tech_daily_cap"
            assert caps["reset_at"] is not None
            assert caps["reset_at"] > _now().isoformat()
        finally:
            await _cleanup(tenant["id"])
    _run(go())


# ─── 3. Tenant at 100 % → denied for admin (no super_admin override) ─
def test_tenant_budget_reaches_100pct_denied_for_admin():
    async def go():
        tenant, tech, admin, sadmin = await _seed_tenant_and_users()
        try:
            # Fill the tenant budget with admin calls (admin has no
            # per-user cap so we can pump to 1000 quickly).
            for i in range(TENANT_MONTHLY_BUDGET_DEFAULT):
                await log_call(admin, tenant, "/property/lookup", f"a{i}")
            caps = await check_caps(admin, tenant)
            assert caps["allowed"] is False
            assert caps["reason"] == "tenant_budget_exhausted"
            assert caps["tenant_used"] >= TENANT_MONTHLY_BUDGET_DEFAULT
            # Admin trying `override_budget=True` — MUST NOT unlock
            # (only super_admin can).
            still = await apply_override_or_fail(
                caps, admin, tenant, "/property/lookup", "x", True
            )
            assert still["allowed"] is False
        finally:
            await _cleanup(tenant["id"])
    _run(go())


# ─── 4. Tenant at 90 % → warning header flag ──────────────────────────
def test_tenant_budget_warns_at_90pct():
    async def go():
        tenant, tech, admin, *_ = await _seed_tenant_and_users()
        try:
            # 900 calls = 90 % of 1000.
            for i in range(900):
                await log_call(admin, tenant, "/property/lookup", f"a{i}")
            caps = await check_caps(tech, tenant)
            assert caps["allowed"] is True
            assert caps["budget_warning"] is True
            assert caps["tenant_pct"] >= 0.90
        finally:
            await _cleanup(tenant["id"])
    _run(go())


# ─── 5. Super_admin override at 100 % → writes audit event ────────────
def test_super_admin_override_writes_audit_event():
    async def go():
        tenant, tech, admin, sadmin = await _seed_tenant_and_users()
        try:
            for i in range(TENANT_MONTHLY_BUDGET_DEFAULT):
                await log_call(admin, tenant, "/property/lookup", f"a{i}")
            caps = await check_caps(sadmin, tenant)
            assert caps["allowed"] is False
            unlocked = await apply_override_or_fail(
                caps, sadmin, tenant, "/property/lookup",
                "123 test st", override_budget=True,
            )
            assert unlocked["allowed"] is True
            assert unlocked["reason"] is None
            assert unlocked.get("override_audit_id")
            db = _mongo()
            audit = await db.zillow_audit.find_one(
                {"id": unlocked["override_audit_id"]}
            )
            assert audit is not None
            assert audit["event"] == "zillow_budget_override"
            assert audit["tenant_used_at_override"] >= 1000
        finally:
            await _cleanup(tenant["id"])
    _run(go())


# ─── 6. Cache hit does NOT decrement counters ─────────────────────────
def test_cache_hit_does_not_decrement_counters():
    async def go():
        tenant, tech, *_ = await _seed_tenant_and_users()
        try:
            addr = "456 Cache Ave, Peoria AZ"
            # No cache initially.
            assert await read_cache(addr) is None
            # Prime the cache.
            await write_cache(addr, {"zpid": "42", "price": 500000})
            # Cache hit returns data.
            data = await read_cache(addr)
            assert data == {"zpid": "42", "price": 500000}
            # Verify counters are still zero (cache read didn't call log_call).
            caps = await check_caps(tech, tenant)
            assert caps["usage"]["tech_today"] == 0
            assert caps["usage"]["tenant_month"] == 0
            # Address hash is deterministic.
            assert address_hash(addr) == address_hash(addr.upper())
        finally:
            db = _mongo()
            await db.zillow_cache.delete_many(
                {"address_hash": address_hash("456 Cache Ave, Peoria AZ")}
            )
            await _cleanup(tenant["id"])
    _run(go())


# ─── 7. Widget endpoint RBAC via HTTP ─────────────────────────────────
def test_widget_endpoint_admin_ok_tech_403():
    assert BASE, "REACT_APP_BACKEND_URL missing"
    def login(email):
        r = requests.post(f"{BASE}/api/auth/login",
                          json={"email": email, "password": "password123"},
                          timeout=45)
        r.raise_for_status()
        return r.json()["access_token"]
    adm = login("admin@aquaterra.com")
    tech = login("mike@aquaterra.com")

    # Admin OK
    r = requests.get(f"{BASE}/api/zillow/usage/this-month",
                     headers={"Authorization": f"Bearer {adm}"}, timeout=45)
    assert r.status_code == 200, r.text
    body = r.json()
    for k in ("month", "total_lookups", "top_users", "tenant_budget",
              "tenant_used", "tenant_pct", "budget_warning",
              "cache_hits", "cache_hit_rate"):
        assert k in body, f"missing '{k}'"

    # Tech blocked
    r = requests.get(f"{BASE}/api/zillow/usage/this-month",
                     headers={"Authorization": f"Bearer {tech}"}, timeout=45)
    assert r.status_code == 403
