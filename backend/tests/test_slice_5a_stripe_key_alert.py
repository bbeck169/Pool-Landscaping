"""Phase 4B follow-up · Feb 2026 — daily Stripe live-key health alert.

Direct-import tests of ``services.stripe_key_health.run_stripe_key_health_scan``
against a locally seeded tenant + admin. Verifies:

* ok=true path             → INFO log only, no deliveries created.
* ok=false path            → 1 email delivery per admin + 1 SMS per
                             escalation recipient, each stamped
                             ``trigger_entity.kind == 'stripe_key_alert'``.
* idempotency (4-hour)     → running the failure path twice with the
                             same signature produces deliveries only
                             once.
* STRIPE_MODE != live      → job short-circuits with skipped=True and
                             creates nothing.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "aquaterra")]


# ─── In-process Stripe SDK stubs (this test's own interpreter) ───────
_ACCT_MODE = {"raise": False}


def _acct_ok(*_args, **_kw):
    return {
        "id": "acct_test_alert_ok",
        "country": "US",
        "charges_enabled": True,
        "payouts_enabled": True,
        "details_submitted": True,
    }


def _acct_fail(*_args, **_kw):
    class AuthenticationError(Exception):
        pass
    raise AuthenticationError("Expired API Key provided: sk_live_test_stub_XyMtod")


@pytest.fixture(scope="module", autouse=True)
def stubs_local():
    from services.stripe_client import get_stripe
    st = get_stripe()
    saved = st.Account.retrieve

    def _dispatch(*a, **kw):
        return _acct_fail(*a, **kw) if _ACCT_MODE["raise"] else _acct_ok(*a, **kw)

    st.Account.retrieve = _dispatch
    yield
    st.Account.retrieve = saved


def _set_ok():   _ACCT_MODE["raise"] = False
def _set_fail(): _ACCT_MODE["raise"] = True


# ─── Seed a lone tenant + admin + escalation number ──────────────────
@pytest.fixture(scope="module")
def env():
    from utils import now_iso
    tenant_id = f"TEST_tenant_{uuid.uuid4().hex[:8]}"
    admin_id = f"TEST_admin_{uuid.uuid4().hex[:8]}"
    slug = f"test-key-alert-{uuid.uuid4().hex[:6]}"
    db = _db()

    async def _seed():
        await db.tenants.update_many(
            {"active": {"$ne": False}},
            {"$set": {"_phase4b_alert_test_hidden": True, "active": False}},
        )
        await db.tenants.insert_one({
            "id": tenant_id, "name": "TEST alert tenant", "slug": slug,
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
            {"_phase4b_alert_test_hidden": True},
            {"$set": {"active": True},
             "$unset": {"_phase4b_alert_test_hidden": ""}},
        )
    _run(_cleanup())


def _reset(tenant_id: str):
    _run(_db().ops_alerts_state.delete_many({"tenant_id": tenant_id}))
    _run(_db().marketing_deliveries.delete_many({"tenant_id": tenant_id}))


@pytest.fixture(autouse=True)
def force_live_mode():
    saved = os.environ.get("STRIPE_MODE")
    os.environ["STRIPE_MODE"] = "live"
    yield
    if saved is None:
        os.environ.pop("STRIPE_MODE", None)
    else:
        os.environ["STRIPE_MODE"] = saved


# ─── Tests ────────────────────────────────────────────────────────────
def test_ok_path_creates_no_deliveries(env):
    _set_ok()
    _reset(env["tenant_id"])
    from services.stripe_key_health import run_stripe_key_health_scan
    res = _run(run_stripe_key_health_scan())
    assert res.get("ok") is True, res
    assert res.get("alerted") is False

    async def _check():
        n = await _db().marketing_deliveries.count_documents(
            {"tenant_id": env["tenant_id"]}
        )
        assert n == 0
    _run(_check())


def test_failure_path_fans_out_email_and_sms(env):
    _reset(env["tenant_id"])
    _set_fail()
    try:
        from services.stripe_key_health import run_stripe_key_health_scan
        res = _run(run_stripe_key_health_scan())
        assert res["ok"] is False
        assert res["alerted"] is True
        assert res["tenants_alerted"] >= 1

        async def _check():
            deliveries = await _db().marketing_deliveries.find(
                {"tenant_id": env["tenant_id"]}, {"_id": 0},
            ).to_list(50)
            assert len(deliveries) >= 2
            channels = {d["channel"] for d in deliveries}
            assert channels == {"email", "sms"}
            for d in deliveries:
                assert d["kind"] == "transactional"
                assert d["trigger_entity"]["kind"] == "stripe_key_alert"
        _run(_check())
    finally:
        _set_ok()


def test_idempotency_within_4_hours(env):
    _reset(env["tenant_id"])
    _set_fail()
    try:
        from services.stripe_key_health import run_stripe_key_health_scan
        _run(run_stripe_key_health_scan())
        n1 = _run(_db().marketing_deliveries.count_documents(
            {"tenant_id": env["tenant_id"]}
        ))
        res2 = _run(run_stripe_key_health_scan())
        n2 = _run(_db().marketing_deliveries.count_documents(
            {"tenant_id": env["tenant_id"]}
        ))
        assert n2 == n1, "duplicate alert inside cooldown window"
        assert res2["tenants_alerted"] == 0
    finally:
        _set_ok()


def test_skips_when_not_live_mode(env):
    _reset(env["tenant_id"])
    saved = os.environ.get("STRIPE_MODE")
    os.environ["STRIPE_MODE"] = "test"
    try:
        from services.stripe_key_health import run_stripe_key_health_scan
        res = _run(run_stripe_key_health_scan())
        assert res.get("skipped") is True
        assert res.get("reason") == "not_live_mode"
        n = _run(_db().marketing_deliveries.count_documents(
            {"tenant_id": env["tenant_id"]}
        ))
        assert n == 0
    finally:
        if saved is None:
            os.environ.pop("STRIPE_MODE", None)
        else:
            os.environ["STRIPE_MODE"] = saved
