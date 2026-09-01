"""Phase K1 · Feb-2026 — Stripe config endpoint contract.

Locks the response shape of ``GET /api/payments/stripe/config`` so
the K1 frontend fallback can rely on ``stripe_configured``.
"""
from __future__ import annotations

import httpx
import pytest

from tests._f7_loop_fixture import run_test


BASE = "/api/payments/stripe/config"


def _get_app():
    from server import app
    return app


async def _ensure_tenant(db, tenant_id="aquaterra"):
    from utils import now_iso
    existing = await db.tenants.find_one({"id": tenant_id})
    if existing:
        if not existing.get("active"):
            await db.tenants.update_one(
                {"id": tenant_id}, {"$set": {"active": True}},
            )
        return existing
    row = {"id": tenant_id, "slug": tenant_id, "name": tenant_id,
              "active": True, "created_at": now_iso()}
    await db.tenants.insert_one(dict(row))
    return row


async def _make_token(db, role, email, tenant_id="aquaterra"):
    from utils import create_token, new_id
    from datetime import datetime, timezone
    user = await db.users.find_one({"email": email})
    if user:
        if user.get("role") != role:
            await db.users.update_one({"email": email},
                                             {"$set": {"role": role}})
            user["role"] = role
        return create_token(user)
    doc = {
        "id": new_id(), "email": email, "role": role,
        "tenant_id": tenant_id, "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(dict(doc))
    return create_token(doc)


# ═══════════════════════════════════════════════════════════════════
# 1. Response shape carries stripe_configured
# ═══════════════════════════════════════════════════════════════════
def test_k1_config_response_carries_stripe_configured_flag():
    async def _go(db):
        await _ensure_tenant(db)
        token = await _make_token(db, "admin",
                                          "k1admin@aquaterra.com")
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            r = await ac.get(
                BASE, headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200, r.text
            body = r.json()
            # Contract keys are always present.
            assert "publishable_key" in body
            assert "stripe_configured" in body
            assert "mode" in body
            assert "stripe_mode" in body
            # ``stripe_configured`` is a plain bool.
            assert isinstance(body["stripe_configured"], bool)
            # Truthy publishable_key ↔ stripe_configured=True.
            if body["publishable_key"]:
                assert body["stripe_configured"] is True
            else:
                assert body["stripe_configured"] is False

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 2. Unconfigured pod returns stripe_configured=false and no env-var
#    names leak into the response body
# ═══════════════════════════════════════════════════════════════════
def test_k1_unconfigured_returns_false_and_no_env_leak(monkeypatch):
    async def _go(db):
        await _ensure_tenant(db)
        token = await _make_token(db, "admin",
                                          "k1admin@aquaterra.com")
        # Force the env into "unconfigured" state for THIS test only.
        # ``_mode()`` reads ``STRIPE_MODE`` which we leave untouched
        # so the same env-var name that ``_publishable_key`` uses
        # returns empty.
        monkeypatch.delenv("STRIPE_PUBLISHABLE_KEY_TEST", raising=False)
        monkeypatch.delenv("STRIPE_PUBLISHABLE_KEY_LIVE", raising=False)
        # Reset the once-warned flag so the rate-limited warn helper
        # can fire during the test.
        import services.payments.stripe_charge as sc
        sc._PUB_KEY_UNCONFIGURED_LAST_WARN_TS = 0.0

        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            r = await ac.get(
                BASE, headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["stripe_configured"] is False
            assert body["publishable_key"] == ""
            # Belt-and-suspenders: the response body must NOT
            # mention any Stripe env-var name.  The frontend
            # relies on the boolean; nothing customer-facing
            # should ever surface the internal env-var identifier.
            raw = r.text
            assert "STRIPE_PUBLISHABLE_KEY_TEST" not in raw
            assert "STRIPE_PUBLISHABLE_KEY_LIVE" not in raw

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 3. Rate-limited warn — called twice inside the hour, logs once
# ═══════════════════════════════════════════════════════════════════
def test_k1_unconfigured_warn_is_rate_limited(caplog, monkeypatch):
    async def _go(db):
        await _ensure_tenant(db)
        token = await _make_token(db, "admin",
                                          "k1admin@aquaterra.com")
        monkeypatch.delenv("STRIPE_PUBLISHABLE_KEY_TEST", raising=False)
        monkeypatch.delenv("STRIPE_PUBLISHABLE_KEY_LIVE", raising=False)
        import services.payments.stripe_charge as sc
        sc._PUB_KEY_UNCONFIGURED_LAST_WARN_TS = 0.0
        caplog.set_level("WARNING", logger="stripe_router")

        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            for _ in range(3):
                r = await ac.get(
                    BASE, headers={"Authorization": f"Bearer {token}"})
                assert r.status_code == 200
        # Exactly one "config endpoint hit while … is unset" warn
        # across the three back-to-back calls.
        matching = [rec for rec in caplog.records
                        if "config endpoint hit while" in rec.getMessage()]
        assert len(matching) == 1, [r.getMessage() for r in matching]

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 4. Tech role is 403'd (no config leak to non-payment surfaces)
# ═══════════════════════════════════════════════════════════════════
def test_k1_tech_role_403():
    async def _go(db):
        await _ensure_tenant(db)
        token = await _make_token(db, "tech", "k1tech@aquaterra.com")
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            r = await ac.get(
                BASE, headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 403, r.text

    run_test(_go)
