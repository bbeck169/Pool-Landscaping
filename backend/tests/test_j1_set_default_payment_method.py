"""Phase J1 · Feb-2026 — Payment method set-default endpoint.

Backend test coverage for the new
``POST /api/payments/stripe/payment-methods/{pm_id}/set-default``
endpoint.  Mirrors the loop-fixture pattern established in
``test_payment_methods_delete.py`` so the two related endpoints
share a maintenance model.

Coverage matrix:
  1. Happy path — flip a non-default PM to default; sibling flips
     to non-default; ``customers.stripe_default_payment_method_id``
     stamped.
  2. Stripe ``Customer.modify`` sync fires (best-effort) but a
     Stripe SDK failure does NOT block the mirror flip.
  3. Unknown PM id → 404.
  4. RBAC: admin ✓, customer ✓ (own PM), customer ✗ (someone
     else's PM), tech 403.
  5. Cross-tenant PM id → 404.
  6. Idempotent — flipping the already-default PM is a no-op
     (still 200, no sibling changes).
"""
from __future__ import annotations

import httpx

from tests._f7_loop_fixture import run_test


BASE = "/api/payments/stripe/payment-methods"


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


async def _make_token(db, role, email, tenant_id="aquaterra",
                          customer_id=None):
    from utils import create_token, new_id
    from datetime import datetime, timezone
    user = await db.users.find_one({"email": email})
    if user:
        patch = {}
        if user.get("role") != role:
            patch["role"] = role
        if customer_id and user.get("customer_id") != customer_id:
            patch["customer_id"] = customer_id
        if patch:
            await db.users.update_one({"email": email}, {"$set": patch})
            user.update(patch)
        return create_token(user)
    doc = {
        "id": new_id(), "email": email, "role": role,
        "tenant_id": tenant_id, "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if customer_id:
        doc["customer_id"] = customer_id
    await db.users.insert_one(dict(doc))
    return create_token(doc)


async def _ensure_customer(db, *, customer_id="cust_j1",
                                 tenant_id="aquaterra",
                                 stripe_customer_id="cus_j1_stripe"):
    from utils import now_iso
    existing = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id})
    if existing:
        return existing
    row = {"id": customer_id, "tenant_id": tenant_id,
              "stripe_customer_id": stripe_customer_id,
              "first_name": "J1", "last_name": "Tester",
              "created_at": now_iso()}
    await db.customers.insert_one(dict(row))
    return row


async def _seed_pm(db, *, pm_id, last4="4242",
                       tenant_id="aquaterra", customer_id="cust_j1",
                       is_default=False, pm_type="card", brand="visa"):
    from utils import new_id, now_iso
    await db.payment_methods.delete_many(
        {"provider_payment_method_id": pm_id},
    )
    row = {
        "id": new_id(), "tenant_id": tenant_id,
        "customer_id": customer_id, "provider": "stripe",
        "provider_customer_id": f"cus_{customer_id}",
        "provider_payment_method_id": pm_id,
        "type": pm_type, "brand": brand, "last4": last4,
        "exp_month": 12, "exp_year": 2028,
        "bank_name": "" if pm_type == "card" else "Chase",
        "account_holder_type": "" if pm_type == "card" else "individual",
        "verification_status": None,
        "is_default": is_default, "stripe_mode": "test",
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.payment_methods.insert_one(dict(row))
    return row


def _stub_stripe_modify(*, raises=False):
    """Monkey-patch ``_stripe.Customer.modify`` to record + no-op."""
    import services.payments.stripe_charge as sc
    calls = []
    orig = sc._stripe

    class _FakeCustomer:
        @staticmethod
        def modify(cust_id, **kwargs):
            calls.append({"customer_id": cust_id, **kwargs})
            if raises:
                raise RuntimeError("stripe unavailable")
            return {"id": cust_id, **kwargs}

    class _FakeStripe:
        Customer = _FakeCustomer

    sc._stripe = _FakeStripe
    return calls, orig


def _restore_stripe(orig):
    import services.payments.stripe_charge as sc
    sc._stripe = orig


# ═══════════════════════════════════════════════════════════════════
# 1. Happy path
# ═══════════════════════════════════════════════════════════════════
def test_j1_set_default_happy_path():
    async def _go(db):
        await _ensure_tenant(db)
        await _ensure_customer(db, customer_id="cust_j1_hp")
        pm_default = await _seed_pm(
            db, pm_id="pm_j1_hp_default", last4="1111",
            customer_id="cust_j1_hp", is_default=True,
        )
        pm_other = await _seed_pm(
            db, pm_id="pm_j1_hp_other", last4="2222",
            customer_id="cust_j1_hp", is_default=False,
        )
        token = await _make_token(db, "admin",
                                          "j1admin@aquaterra.com")
        calls, orig = _stub_stripe_modify()
        try:
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                r = await ac.post(
                    f"{BASE}/{pm_other['provider_payment_method_id']}/set-default",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert r.status_code == 200, r.text
                body = r.json()
                assert body["ok"] is True
                assert body["last4"] == "2222"
                assert body["provider_payment_method_id"] == pm_other[
                    "provider_payment_method_id"]
        finally:
            _restore_stripe(orig)

        # Mirror flipped — old default is now non-default; target is
        # default; customer pointer updated.
        row_old = await db.payment_methods.find_one(
            {"provider_payment_method_id": pm_default[
                "provider_payment_method_id"]})
        row_new = await db.payment_methods.find_one(
            {"provider_payment_method_id": pm_other[
                "provider_payment_method_id"]})
        assert row_old["is_default"] is False
        assert row_new["is_default"] is True
        cust = await db.customers.find_one({"id": "cust_j1_hp"})
        assert cust["stripe_default_payment_method_id"] == pm_other[
            "provider_payment_method_id"]
        # Stripe.Customer.modify fired exactly once for the customer's
        # stripe_customer_id.
        assert len(calls) == 1
        assert calls[0]["invoice_settings"]["default_payment_method"] \
            == pm_other["provider_payment_method_id"]

        # Cleanup.
        await db.payment_methods.delete_many(
            {"customer_id": "cust_j1_hp"})
        await db.customers.delete_many({"id": "cust_j1_hp"})

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 2. Stripe SDK failure does NOT block the mirror flip
# ═══════════════════════════════════════════════════════════════════
def test_j1_set_default_survives_stripe_sync_failure():
    async def _go(db):
        await _ensure_tenant(db)
        await _ensure_customer(db, customer_id="cust_j1_fail")
        pm = await _seed_pm(
            db, pm_id="pm_j1_fail", last4="3333",
            customer_id="cust_j1_fail", is_default=False,
        )
        token = await _make_token(db, "admin",
                                          "j1admin@aquaterra.com")
        calls, orig = _stub_stripe_modify(raises=True)
        try:
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                r = await ac.post(
                    f"{BASE}/{pm['provider_payment_method_id']}/set-default",
                    headers={"Authorization": f"Bearer {token}"},
                )
                # Endpoint still returns 200 — mirror is the source
                # of truth for autobilling + reporting.
                assert r.status_code == 200, r.text
        finally:
            _restore_stripe(orig)

        row = await db.payment_methods.find_one(
            {"provider_payment_method_id": pm[
                "provider_payment_method_id"]})
        assert row["is_default"] is True
        # Stripe.Customer.modify was attempted (best-effort).
        assert len(calls) == 1

        await db.payment_methods.delete_many(
            {"customer_id": "cust_j1_fail"})
        await db.customers.delete_many({"id": "cust_j1_fail"})

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 3. Unknown PM id → 404
# ═══════════════════════════════════════════════════════════════════
def test_j1_set_default_unknown_pm_returns_404():
    async def _go(db):
        await _ensure_tenant(db)
        token = await _make_token(db, "admin",
                                          "j1admin@aquaterra.com")
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            r = await ac.post(
                f"{BASE}/pm_does_not_exist/set-default",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 404, r.text

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 4a. RBAC — tech role 403
# ═══════════════════════════════════════════════════════════════════
def test_j1_set_default_tech_403():
    async def _go(db):
        await _ensure_tenant(db)
        pm = await _seed_pm(db, pm_id="pm_j1_tech")
        token = await _make_token(db, "tech", "j1tech@aquaterra.com")
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            r = await ac.post(
                f"{BASE}/{pm['provider_payment_method_id']}/set-default",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 403, r.text
        await db.payment_methods.delete_many(
            {"provider_payment_method_id": pm[
                "provider_payment_method_id"]})

    run_test(_go)


# 4b. Customer role CAN flip their own PM
def test_j1_set_default_customer_own_pm_allowed():
    async def _go(db):
        await _ensure_tenant(db)
        await _ensure_customer(db, customer_id="cust_j1_own")
        pm = await _seed_pm(db, pm_id="pm_j1_own",
                                 customer_id="cust_j1_own")
        token = await _make_token(
            db, "customer", "j1owner@aquaterra.com",
            customer_id="cust_j1_own",
        )
        calls, orig = _stub_stripe_modify()
        try:
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                r = await ac.post(
                    f"{BASE}/{pm['provider_payment_method_id']}/set-default",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert r.status_code == 200, r.text
        finally:
            _restore_stripe(orig)
        await db.payment_methods.delete_many(
            {"customer_id": "cust_j1_own"})
        await db.customers.delete_many({"id": "cust_j1_own"})

    run_test(_go)


# 4c. Customer role CANNOT flip someone else's PM
def test_j1_set_default_customer_other_pm_403():
    async def _go(db):
        await _ensure_tenant(db)
        pm = await _seed_pm(db, pm_id="pm_j1_other",
                                 customer_id="cust_j1_other")
        token = await _make_token(
            db, "customer", "j1intruder@aquaterra.com",
            customer_id="cust_j1_own",
        )
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            r = await ac.post(
                f"{BASE}/{pm['provider_payment_method_id']}/set-default",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 403, r.text
        await db.payment_methods.delete_many(
            {"provider_payment_method_id": pm[
                "provider_payment_method_id"]})

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 5. Cross-tenant PM id → 404
# ═══════════════════════════════════════════════════════════════════
def test_j1_set_default_cross_tenant_returns_404():
    async def _go(db):
        await _ensure_tenant(db, "aquaterra")
        await _ensure_tenant(db, "other-tenant")
        pm = await _seed_pm(db, tenant_id="other-tenant",
                                 pm_id="pm_j1_crosstenant")
        token = await _make_token(db, "admin",
                                          "j1admin@aquaterra.com",
                                          tenant_id="aquaterra")
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            r = await ac.post(
                f"{BASE}/{pm['provider_payment_method_id']}/set-default",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 404, r.text
        await db.payment_methods.delete_many(
            {"provider_payment_method_id": pm[
                "provider_payment_method_id"]})

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 6. Idempotent — flipping the already-default PM stays default
# ═══════════════════════════════════════════════════════════════════
def test_j1_set_default_idempotent_on_already_default():
    async def _go(db):
        await _ensure_tenant(db)
        await _ensure_customer(db, customer_id="cust_j1_idem")
        pm = await _seed_pm(
            db, pm_id="pm_j1_idem", last4="9999",
            customer_id="cust_j1_idem", is_default=True,
        )
        token = await _make_token(db, "admin",
                                          "j1admin@aquaterra.com")
        calls, orig = _stub_stripe_modify()
        try:
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                r = await ac.post(
                    f"{BASE}/{pm['provider_payment_method_id']}/set-default",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert r.status_code == 200, r.text
        finally:
            _restore_stripe(orig)
        row = await db.payment_methods.find_one(
            {"provider_payment_method_id": pm[
                "provider_payment_method_id"]})
        assert row["is_default"] is True

        await db.payment_methods.delete_many(
            {"customer_id": "cust_j1_idem"})
        await db.customers.delete_many({"id": "cust_j1_idem"})

    run_test(_go)
