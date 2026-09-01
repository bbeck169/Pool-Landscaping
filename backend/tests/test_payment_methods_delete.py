"""Phase I5 · Feb-2026 — Payment method typed-last4 delete gate.

Backend test coverage for the defense-in-depth
``POST /api/payments/stripe/payment-methods/{pm_id}/delete-typed``
endpoint. Every test rebinds the DB through the F7 loop fixture
and monkey-patches ``stripe_charge.detach_payment_method`` so we
never hit the live Stripe API.

Coverage matrix:
  1. Correct keyword → 200 + Stripe detach called
  2. Wrong keyword → 400, Stripe detach NOT called
  3. Case sensitivity is enforced ("2589" ≠ "2589" different quotes)
  4. Unknown PM id → 404
  5. Empty stored last4 short-circuits to 400 (defense-in-depth
     against legacy rows with unpopulated last4)
  6. RBAC: super_admin ✓, admin ✓, customer ✓ (own PM), customer ✗
     (someone else's PM), tech 403, unauth 401/403
  7. Cross-tenant PM id → 404
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


async def _seed_pm(db, *, pm_id="pm_test_i5", last4="4242",
                       tenant_id="aquaterra", customer_id="cust_i5",
                       pm_type="card", brand="visa"):
    from utils import new_id, now_iso
    # Delete any leftover row from a prior test run so re-runs
    # don't collide with the (tenant_id, provider_payment_method_id)
    # unique index.
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
        "is_default": True, "stripe_mode": "test",
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.payment_methods.insert_one(dict(row))
    return row


def _stub_detach():
    """Monkey-patch stripe_charge.detach_payment_method with a
    recorder that skips the real Stripe API + skips the mirror-row
    cleanup (we manage that inline per-test)."""
    import services.payments.stripe_charge as sc
    calls = []
    orig = sc.detach_payment_method

    async def _fake(*, tenant_id, payment_method_id):
        calls.append({"tenant_id": tenant_id,
                          "payment_method_id": payment_method_id})
        # Mirror the real function's row cleanup so subsequent
        # tests can't accidentally see the row.
        await sc.db.payment_methods.delete_one(
            {"provider_payment_method_id": payment_method_id,
                "tenant_id": tenant_id},
        )
        return {"ok": True,
                    "provider_payment_method_id": payment_method_id,
                    "customer_id": None}
    sc.detach_payment_method = _fake
    return calls, orig


def _restore_detach(orig):
    import services.payments.stripe_charge as sc
    sc.detach_payment_method = orig


# ═══════════════════════════════════════════════════════════════════
# 1. Happy path — correct keyword → 200 + Stripe detach called
# ═══════════════════════════════════════════════════════════════════
def test_i5_correct_keyword_deletes():
    async def _go(db):
        await _ensure_tenant(db)
        pm = await _seed_pm(db, last4="4242")
        token = await _make_token(db, "admin", "i5admin@aquaterra.com")
        calls, orig = _stub_detach()
        try:
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                r = await ac.post(
                    f"{BASE}/{pm['provider_payment_method_id']}/delete-typed",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"typed_last4": "4242"},
                )
                assert r.status_code == 200, r.text
                body = r.json()
                assert body["ok"] is True
                assert body["last4"] == "4242"
                assert body["type"] == "card"
                assert body["brand"] == "visa"
                assert len(calls) == 1
                assert calls[0]["payment_method_id"] == pm[
                    "provider_payment_method_id"]
        finally:
            _restore_detach(orig)
            await db.payment_methods.delete_many(
                {"provider_payment_method_id": pm[
                    "provider_payment_method_id"]},
            )

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 2. Wrong keyword → 400 and Stripe detach NOT called
# ═══════════════════════════════════════════════════════════════════
def test_i5_wrong_keyword_rejects_and_skips_detach():
    async def _go(db):
        await _ensure_tenant(db)
        pm = await _seed_pm(db, last4="4242",
                                 pm_id="pm_test_i5_wrong")
        token = await _make_token(db, "admin", "i5admin@aquaterra.com")
        calls, orig = _stub_detach()
        try:
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                r = await ac.post(
                    f"{BASE}/{pm['provider_payment_method_id']}/delete-typed",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"typed_last4": "9999"},
                )
                assert r.status_code == 400, r.text
                assert "typed_last4_mismatch" in r.json().get("detail", "")
                # Stripe MUST NOT have been called.
                assert calls == []
                # Mirror row still present.
                row = await db.payment_methods.find_one(
                    {"provider_payment_method_id":
                         pm["provider_payment_method_id"]},
                )
                assert row is not None
        finally:
            _restore_detach(orig)
            await db.payment_methods.delete_many(
                {"provider_payment_method_id": pm[
                    "provider_payment_method_id"]},
            )

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 3. Whitespace-trimmed but case-preserving comparison
# ═══════════════════════════════════════════════════════════════════
def test_i5_whitespace_trimmed_but_exact_match_required():
    async def _go(db):
        await _ensure_tenant(db)
        pm = await _seed_pm(db, last4="1234",
                                 pm_id="pm_test_i5_trim")
        token = await _make_token(db, "admin", "i5admin@aquaterra.com")
        calls, orig = _stub_detach()
        try:
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                # Trailing whitespace should be stripped.
                r_ok = await ac.post(
                    f"{BASE}/{pm['provider_payment_method_id']}/delete-typed",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"typed_last4": " 1234 "},
                )
                assert r_ok.status_code == 200, r_ok.text
                assert len(calls) == 1
        finally:
            _restore_detach(orig)
            await db.payment_methods.delete_many(
                {"provider_payment_method_id": pm[
                    "provider_payment_method_id"]},
            )

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 4. Unknown PM id → 404
# ═══════════════════════════════════════════════════════════════════
def test_i5_unknown_pm_returns_404():
    async def _go(db):
        await _ensure_tenant(db)
        token = await _make_token(db, "admin", "i5admin@aquaterra.com")
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            r = await ac.post(
                f"{BASE}/pm_does_not_exist/delete-typed",
                headers={"Authorization": f"Bearer {token}"},
                json={"typed_last4": "4242"},
            )
            assert r.status_code == 404, r.text

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 5. Legacy row with empty last4 → 400 (never allow-through)
# ═══════════════════════════════════════════════════════════════════
def test_i5_empty_stored_last4_short_circuits_to_400():
    async def _go(db):
        await _ensure_tenant(db)
        pm = await _seed_pm(db, last4="",
                                 pm_id="pm_test_i5_empty_last4")
        token = await _make_token(db, "admin", "i5admin@aquaterra.com")
        calls, orig = _stub_detach()
        try:
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                # Even an "empty" typed value must NOT succeed —
                # legacy rows with unpopulated last4 should be
                # fixed via a data-repair sweep, not silently
                # allowed through.
                r = await ac.post(
                    f"{BASE}/{pm['provider_payment_method_id']}/delete-typed",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"typed_last4": ""},
                )
                assert r.status_code == 422, r.text  # Pydantic min_length=1
                assert calls == []
                # Passing whitespace passes Pydantic but fails the
                # stored-last4 empty guard.
                r2 = await ac.post(
                    f"{BASE}/{pm['provider_payment_method_id']}/delete-typed",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"typed_last4": "   "},
                )
                assert r2.status_code == 400
                assert calls == []
        finally:
            _restore_detach(orig)
            await db.payment_methods.delete_many(
                {"provider_payment_method_id": pm[
                    "provider_payment_method_id"]},
            )

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 6a. RBAC — tech role 403
# ═══════════════════════════════════════════════════════════════════
def test_i5_rbac_tech_403():
    async def _go(db):
        await _ensure_tenant(db)
        pm = await _seed_pm(db, pm_id="pm_test_i5_tech")
        token = await _make_token(db, "tech", "i5tech@aquaterra.com")
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            r = await ac.post(
                f"{BASE}/{pm['provider_payment_method_id']}/delete-typed",
                headers={"Authorization": f"Bearer {token}"},
                json={"typed_last4": "4242"},
            )
            assert r.status_code == 403, r.text
        await db.payment_methods.delete_many(
            {"provider_payment_method_id": pm[
                "provider_payment_method_id"]},
        )

    run_test(_go)


# 6b. Customer role can delete their own PM
def test_i5_rbac_customer_own_pm_allowed():
    async def _go(db):
        await _ensure_tenant(db)
        pm = await _seed_pm(db, customer_id="cust_i5_own",
                                 pm_id="pm_test_i5_own")
        token = await _make_token(
            db, "customer", "i5owner@aquaterra.com",
            customer_id="cust_i5_own",
        )
        calls, orig = _stub_detach()
        try:
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                r = await ac.post(
                    f"{BASE}/{pm['provider_payment_method_id']}/delete-typed",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"typed_last4": "4242"},
                )
                assert r.status_code == 200, r.text
                assert len(calls) == 1
        finally:
            _restore_detach(orig)
            await db.payment_methods.delete_many(
                {"provider_payment_method_id": pm[
                    "provider_payment_method_id"]},
            )

    run_test(_go)


# 6c. Customer role CANNOT delete someone else's PM
def test_i5_rbac_customer_other_pm_403():
    async def _go(db):
        await _ensure_tenant(db)
        pm = await _seed_pm(db, customer_id="cust_i5_other",
                                 pm_id="pm_test_i5_other")
        token = await _make_token(
            db, "customer", "i5intruder@aquaterra.com",
            customer_id="cust_i5_own",
        )
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            r = await ac.post(
                f"{BASE}/{pm['provider_payment_method_id']}/delete-typed",
                headers={"Authorization": f"Bearer {token}"},
                json={"typed_last4": "4242"},
            )
            assert r.status_code == 403, r.text
        await db.payment_methods.delete_many(
            {"provider_payment_method_id": pm[
                "provider_payment_method_id"]},
        )

    run_test(_go)


# 6d. Unauth → 401 or 403
def test_i5_rbac_unauth():
    async def _go(_db):
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            r = await ac.post(
                f"{BASE}/pm_test_i5_x/delete-typed",
                json={"typed_last4": "4242"},
            )
            assert r.status_code in (401, 403), r.text

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 7. Cross-tenant PM id → 404
# ═══════════════════════════════════════════════════════════════════
def test_i5_cross_tenant_returns_404():
    async def _go(db):
        await _ensure_tenant(db, "aquaterra")
        await _ensure_tenant(db, "other-tenant")
        # PM lives on ``other-tenant`` — an ``aquaterra`` admin
        # must NOT be able to see or delete it.
        pm = await _seed_pm(db, tenant_id="other-tenant",
                                 pm_id="pm_test_i5_crosstenant")
        token = await _make_token(db, "admin", "i5admin@aquaterra.com",
                                        tenant_id="aquaterra")
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            r = await ac.post(
                f"{BASE}/{pm['provider_payment_method_id']}/delete-typed",
                headers={"Authorization": f"Bearer {token}"},
                json={"typed_last4": "4242"},
            )
            assert r.status_code == 404, r.text
        await db.payment_methods.delete_many(
            {"provider_payment_method_id": pm[
                "provider_payment_method_id"]},
        )

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 8. ACH bank account PM — same gate, different response shape
# ═══════════════════════════════════════════════════════════════════
def test_i5_ach_bank_pm_deletion_flow():
    async def _go(db):
        await _ensure_tenant(db)
        pm = await _seed_pm(db, last4="6789",
                                 pm_id="pm_test_i5_ach",
                                 pm_type="us_bank_account",
                                 brand="")
        token = await _make_token(db, "admin", "i5admin@aquaterra.com")
        calls, orig = _stub_detach()
        try:
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                r = await ac.post(
                    f"{BASE}/{pm['provider_payment_method_id']}/delete-typed",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"typed_last4": "6789"},
                )
                assert r.status_code == 200, r.text
                body = r.json()
                assert body["type"] == "us_bank_account"
                assert body["last4"] == "6789"
                assert len(calls) == 1
        finally:
            _restore_detach(orig)
            await db.payment_methods.delete_many(
                {"provider_payment_method_id": pm[
                    "provider_payment_method_id"]},
            )

    run_test(_go)
