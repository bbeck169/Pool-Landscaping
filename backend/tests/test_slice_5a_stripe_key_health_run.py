"""Phase 4B follow-up · Feb 2026 — manual Stripe key health-run endpoint.

Covers ``POST /api/dev/stripe-key-health-run`` — the on-demand trigger
that mirrors the daily scheduler entry point. Verifies:

* happy path        → ``ping.ok=true``, ``alert_fanned_out=false``,
                       zero deliveries.
* failure path      → ``alert_fanned_out=true``, ≥1 email +
                       ≥1 sms delivery created.
* cooldown          → repeat call within 4h → ``cooldown_active=true``,
                       ``alert_fanned_out=false``, no new deliveries.
* non-admin RBAC    → 403 for technician + customer roles.
* test mode         → returns ``skipped=true`` with reason set.

Uses the same in-process SDK stubs pattern as the ``stripe_key_alert``
suite. Tenant/admin fixture is scoped to the module.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import requests

API = "http://localhost:8001/api"

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "aquaterra")]


def _jwt_secret() -> str:
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return os.environ["JWT_SECRET"]


def _mk_token(user_id: str, role: str) -> str:
    return jwt.encode(
        {"sub": user_id, "email": f"{user_id}@ex.com", "role": role,
         "exp": datetime.now(timezone.utc) + timedelta(hours=2)},
        _jwt_secret(), algorithm="HS256",
    )


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _login_admin() -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": "admin@aquaterra.com",
                                "password": "password123"}, timeout=15)
    assert r.status_code == 200
    return r.json()["access_token"]


# ─── SDK stubs (backend process, via test-only endpoints) ────────────
@pytest.fixture(scope="module", autouse=True)
def stubs():
    r = requests.post(f"{API}/dev/_phase4b_stub_stripe", timeout=15)
    assert r.status_code == 200
    requests.post(f"{API}/dev/_phase4b_stub_account_ok", timeout=15)
    yield
    requests.post(f"{API}/dev/_phase4b_stub_account_ok", timeout=15)
    requests.post(f"{API}/dev/_phase4b_unstub_stripe", timeout=15)


def _set_ok():
    requests.post(f"{API}/dev/_phase4b_stub_account_ok", timeout=15)


def _set_fail():
    requests.post(f"{API}/dev/_phase4b_stub_account_raise", timeout=15)


# ─── Isolated tenant fixture ─────────────────────────────────────────
@pytest.fixture(scope="module")
def env():
    from utils import now_iso
    tenant_id = f"TEST_tenant_{uuid.uuid4().hex[:8]}"
    admin_id = f"TEST_admin_{uuid.uuid4().hex[:8]}"
    slug = f"test-hr-{uuid.uuid4().hex[:6]}"
    db = _db()

    async def _seed():
        await db.tenants.update_many(
            {"active": {"$ne": False}},
            {"$set": {"_phase4b_hr_hidden": True, "active": False}},
        )
        await db.tenants.insert_one({
            "id": tenant_id, "name": "TEST hr tenant", "slug": slug,
            "active": True,
            "sms_escalation_recipients": ["+15005550006"],
            "created_at": now_iso(),
        })
        await db.users.insert_one({
            "id": admin_id, "email": f"admin_{admin_id}@ex.com",
            "role": "admin", "tenant_id": tenant_id,
            "active": True, "phone": "+15005550006",
            "created_at": now_iso(),
        })
    _run(_seed())
    yield {"tenant_id": tenant_id, "admin_id": admin_id}

    async def _cleanup():
        await db.tenants.delete_one({"id": tenant_id})
        await db.users.delete_many({"tenant_id": tenant_id})
        await db.marketing_deliveries.delete_many({"tenant_id": tenant_id})
        await db.ops_alerts_state.delete_many({"tenant_id": tenant_id})
        await db.tenants.update_many(
            {"_phase4b_hr_hidden": True},
            {"$set": {"active": True},
             "$unset": {"_phase4b_hr_hidden": ""}},
        )
    _run(_cleanup())


def _reset(tenant_id: str):
    _run(_db().ops_alerts_state.delete_many({"tenant_id": tenant_id}))
    _run(_db().marketing_deliveries.delete_many({"tenant_id": tenant_id}))


# ─── Tests ────────────────────────────────────────────────────────────
def test_manual_run_happy_path(env):
    _reset(env["tenant_id"])
    _set_ok()
    tok = _login_admin()
    r = requests.post(f"{API}/dev/stripe-key-health-run",
                        headers=_hdr(tok), timeout=20)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ping"]["ok"] is True
    assert j["alert_fanned_out"] is False
    assert j["cooldown_active"] is False
    assert j["deliveries_created"] == {"email": 0, "sms": 0}
    assert j["ran_at"]

    n = _run(_db().marketing_deliveries.count_documents(
        {"tenant_id": env["tenant_id"]}
    ))
    assert n == 0


def test_manual_run_failure_path_fanout(env):
    _reset(env["tenant_id"])
    _set_fail()
    try:
        tok = _login_admin()
        r = requests.post(f"{API}/dev/stripe-key-health-run",
                            headers=_hdr(tok), timeout=20)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ping"]["ok"] is False
        assert j["alert_fanned_out"] is True
        assert j["deliveries_created"]["email"] >= 1
        assert j["deliveries_created"]["sms"] >= 1

        async def _check():
            deliveries = await _db().marketing_deliveries.find(
                {"tenant_id": env["tenant_id"]}, {"_id": 0},
            ).to_list(50)
            channels = {d["channel"] for d in deliveries}
            assert channels == {"email", "sms"}
            for d in deliveries:
                assert d["kind"] == "transactional"
                assert d["trigger_entity"]["kind"] == "stripe_key_alert"
        _run(_check())
    finally:
        _set_ok()


def test_manual_run_cooldown_suppression(env):
    _reset(env["tenant_id"])
    _set_fail()
    try:
        tok = _login_admin()
        r1 = requests.post(f"{API}/dev/stripe-key-health-run",
                             headers=_hdr(tok), timeout=20)
        assert r1.status_code == 200
        j1 = r1.json()
        assert j1["alert_fanned_out"] is True
        n1 = _run(_db().marketing_deliveries.count_documents(
            {"tenant_id": env["tenant_id"]}
        ))

        # Second call, same signature, within 4h → suppressed.
        r2 = requests.post(f"{API}/dev/stripe-key-health-run",
                             headers=_hdr(tok), timeout=20)
        assert r2.status_code == 200
        j2 = r2.json()
        assert j2["ping"]["ok"] is False
        assert j2["alert_fanned_out"] is False
        assert j2["cooldown_active"] is True
        assert j2["cooldown_expires_at"] is not None
        assert j2["deliveries_created"] == {"email": 0, "sms": 0}

        n2 = _run(_db().marketing_deliveries.count_documents(
            {"tenant_id": env["tenant_id"]}
        ))
        assert n2 == n1
    finally:
        _set_ok()


def test_manual_run_denies_technician(env):
    _set_ok()
    async def _tid():
        db = _db()
        row = await db.users.find_one({"email": "mike@aquaterra.com"}, {"_id": 0, "id": 1})
        return row["id"] if row else None
    uid = _run(_tid())
    if not uid:
        pytest.skip("mike@aquaterra.com missing")
    tok = _mk_token(uid, "technician")
    r = requests.post(f"{API}/dev/stripe-key-health-run",
                        headers=_hdr(tok), timeout=15)
    assert r.status_code == 403


def test_manual_run_denies_customer(env):
    _set_ok()
    async def _cid():
        db = _db()
        row = await db.users.find_one({"email": "customer@aquaterra.com"}, {"_id": 0, "id": 1})
        return row["id"] if row else None
    uid = _run(_cid())
    if not uid:
        pytest.skip("customer@aquaterra.com missing")
    tok = _mk_token(uid, "customer")
    r = requests.post(f"{API}/dev/stripe-key-health-run",
                        headers=_hdr(tok), timeout=15)
    assert r.status_code == 403


def test_manual_run_skips_when_not_live_mode(env):
    _set_ok()
    saved = os.environ.get("STRIPE_MODE")
    # Runtime env can be set via HTTP-only through supervisor; instead we
    # simulate the branch by editing the .env-mirrored os.environ inside
    # the running backend via a tiny test helper. The scheduler function
    # reads ``os.environ["STRIPE_MODE"]`` from the backend process, so
    # we swap it there via the phase-4b stub hooks — a dedicated toggle
    # keeps the swap local + reversible.
    requests.post(f"{API}/dev/_phase4b_env_set",
                    json={"key": "STRIPE_MODE", "value": "test"},
                    timeout=15)
    try:
        tok = _login_admin()
        r = requests.post(f"{API}/dev/stripe-key-health-run",
                            headers=_hdr(tok), timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("skipped") is True
        assert "not live" in (j.get("reason") or "").lower()
    finally:
        requests.post(f"{API}/dev/_phase4b_env_set",
                        json={"key": "STRIPE_MODE", "value": saved or "live"},
                        timeout=15)
