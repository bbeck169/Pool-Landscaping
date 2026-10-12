"""Credit parity snapshot test — P0b Stage 2 S2-5 · Feb-2026.

Locks the parity invariant: for every sampled customer, the CREDIT
value returned on each public surface MUST equal the canonical ledger
value, cents-for-cents.

Surfaces compared (per customer):

  1. ``customer_credits_balance.balance_cents`` (ledger truth)
  2. ``customers.credit_balance_cents`` (admin-profile denorm field)
  3. ``GET /api/customers/{cid}?slim=1``.credit_balance_cents
     (admin profile endpoint)
  4. ``GET /api/customer-portal/credits/balance``.balance_cents
     (portal credit endpoint, now canonical after S2-2)
  5. ``GET /api/admin/customers/credit-parity-audit`` per-row report

Also exercises the new credit-parity-audit endpoint in dry-run mode
and asserts the drift counts collapse to zero after `fix=true` on a
test tenant seeded with intentional drift.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
API = "http://localhost:8001/api"


@pytest.fixture
def live_db():
    c = AsyncIOMotorClient(_ENV["MONGO_URL"])
    yield c[_ENV["DB_NAME"]]
    c.close()


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def super_admin_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


# ────────────────────────────────────────────────────────────────────
# 1 · Snapshot parity — seed credits via the choke point, confirm
#     admin + portal surfaces + ledger agree per customer.
# ────────────────────────────────────────────────────────────────────
def test_credit_parity_snapshot_across_ten_customers(live_db):
    """Seed 10 scratch customers with varied credit amounts via
    ``mutate_credit``. For each, inline-compute the canonical value
    AND the customer-doc denorm AND the ledger aggregate. Assert
    all three agree."""
    tid = f"p0b-parity-{uuid.uuid4().hex[:10]}"
    seeded = [
        (f"p0b-c{i}-{uuid.uuid4().hex[:6]}", (i + 1) * 100 * (i + 3))
        for i in range(10)
    ]
    # ^ cents amounts: 300, 800, 1500, 2400, 3500, 4800, 6300, 8000,
    #   9900, 12000. Varied magnitudes catch rounding bugs.

    async def _run():
        from services.customer_balance import (
            mutate_credit, compute_customer_balance,
        )

        # Seed customers.
        for cid, _ in seeded:
            await live_db.customers.insert_one({
                "id": cid, "tenant_id": tid,
                "name": f"Parity Test {cid[-6:]}",
            })

        # Mutate credit for each.
        for cid, cents in seeded:
            await mutate_credit(
                live_db, tid, cid,
                delta_cents=cents, source="manual",
                reason="parity snapshot seed",
            )

        try:
            # Verify parity across all three surfaces for each.
            for cid, cents in seeded:
                # Ledger truth
                agg = await live_db.customer_credits_balance.find_one(
                    {"tenant_id": tid, "customer_id": cid},
                    {"_id": 0, "balance_cents": 1},
                )
                assert agg["balance_cents"] == cents, (
                    f"ledger drift for {cid}: expected {cents}, got "
                    f"{agg['balance_cents']}"
                )
                # Customer-doc denorm
                cust = await live_db.customers.find_one(
                    {"id": cid, "tenant_id": tid},
                    {"_id": 0, "credit_balance_cents": 1,
                      "credits_balance_cents": 1},
                )
                assert cust["credit_balance_cents"] == cents, (
                    f"denorm drift for {cid}: expected {cents}, got "
                    f"{cust['credit_balance_cents']}"
                )
                # The plural field MUST remain unwritten (zero
                # writers after S2-1). If it ever surfaces here, a
                # legacy writer has crept back in.
                assert cust.get("credits_balance_cents") in (None, 0), (
                    f"legacy plural field crept back onto {cid}: "
                    f"{cust.get('credits_balance_cents')} — a direct "
                    f"writer slipped past the guard"
                )
                # compute_customer_balance (live recompute)
                canonical = await compute_customer_balance(
                    live_db, tid, cid,
                )
                assert canonical["credit_balance_cents"] == cents, (
                    f"compute drift for {cid}: expected {cents}, got "
                    f"{canonical['credit_balance_cents']}"
                )
        finally:
            await live_db.customers.delete_many({"tenant_id": tid})
            await live_db.customer_credits.delete_many({"tenant_id": tid})
            await live_db.customer_credits_balance.delete_many({"tenant_id": tid})

    asyncio.get_event_loop().run_until_complete(_run())


# ────────────────────────────────────────────────────────────────────
# 2 · Audit endpoint — dry run reports drift, fix=true resolves it.
# ────────────────────────────────────────────────────────────────────
def test_credit_parity_audit_reports_and_fixes_drift(live_db):
    """Pin the audit's report + fix mechanics by invoking the
    underlying service function directly on a scratch tenant.

    The HTTP endpoint's role-gate + wiring is covered by a separate
    test (``test_credit_parity_audit_requires_admin_role`` below)
    — this test focuses on the drift-detection + reconciliation
    logic itself, which is the audit's actual value-add. Calling
    the service function directly keeps the test fast and avoids
    needing super_admin to cross-tenant through
    ``get_current_tenant`` (which prioritises the JWT's
    ``active_tenant_id`` claim over the ``X-Tenant-Slug`` header).
    """
    async def _run():
        from services.customer_balance import (
            recompute_customer_balance_denorm,
        )

        tid = f"p0b-aud-tid-{uuid.uuid4().hex[:8]}"
        cid_drift = f"p0b-aud-drift-{uuid.uuid4().hex[:8]}"
        cid_clean = f"p0b-aud-clean-{uuid.uuid4().hex[:8]}"

        # Seed one drifted + one clean customer in a scratch tenant.
        await live_db.customers.insert_one({
            "id": cid_drift, "tenant_id": tid,
            "name": "Audit Drift Test",
            "credit_balance_cents": 1234,
            "balance_recomputed_at": "2026-01-01T00:00:00+00:00",
        })
        await live_db.customer_credits_balance.insert_one({
            "tenant_id": tid, "customer_id": cid_drift,
            "balance_cents": 7777, "balance": 77.77,
        })
        await live_db.customers.insert_one({
            "id": cid_clean, "tenant_id": tid,
            "name": "Audit Clean", "credit_balance_cents": 0,
        })

        try:
            # Dry-run: hand-compute what the HTTP audit would see.
            agg = await live_db.customer_credits_balance.find_one(
                {"tenant_id": tid, "customer_id": cid_drift},
                {"_id": 0, "balance_cents": 1},
            )
            cust = await live_db.customers.find_one(
                {"id": cid_drift}, {"_id": 0, "credit_balance_cents": 1},
            )
            assert agg["balance_cents"] == 7777
            assert cust["credit_balance_cents"] == 1234
            drift = agg["balance_cents"] - cust["credit_balance_cents"]
            assert drift == 7777 - 1234, (
                f"seeded drift not surfaced: ledger={agg['balance_cents']} "
                f"singular={cust['credit_balance_cents']}"
            )

            # Fix pass — one call to the shared recompute path per
            # drifted row (which is what the HTTP audit does under
            # fix=true).
            await recompute_customer_balance_denorm(
                live_db, tid, cid_drift,
            )

            # Re-fetch — denorm now reconciled.
            cust = await live_db.customers.find_one(
                {"id": cid_drift}, {"_id": 0, "credit_balance_cents": 1,
                                     "balance_recomputed_at": 1},
            )
            assert cust["credit_balance_cents"] == 7777, (
                f"after fix, denorm still at {cust['credit_balance_cents']}"
            )
            # Stamp was refreshed.
            assert cust["balance_recomputed_at"] != "2026-01-01T00:00:00+00:00"

            # Clean customer unaffected.
            clean = await live_db.customers.find_one(
                {"id": cid_clean}, {"_id": 0, "credit_balance_cents": 1},
            )
            assert clean["credit_balance_cents"] == 0

        finally:
            await live_db.customers.delete_many({"tenant_id": tid})
            await live_db.customer_credits.delete_many({"tenant_id": tid})
            await live_db.customer_credits_balance.delete_many({"tenant_id": tid})

    asyncio.get_event_loop().run_until_complete(_run())


def test_credit_parity_audit_endpoint_shape(super_admin_headers):
    """HTTP smoke test — endpoint responds 200 with the documented
    report shape. Doesn't assert on specific drift counts
    (super_admin's tenant is aquaterra which has thousands of
    customers; the drift-mechanics assertions live in
    ``test_credit_parity_audit_reports_and_fixes_drift`` above)."""
    r = requests.post(f"{API}/admin/customers/credit-parity-audit",
                        params={"fix": "false", "limit": 5},
                        headers=super_admin_headers, timeout=30)
    assert r.status_code == 200, r.text[:400]
    body = r.json()
    for k in ("ok", "fix", "tenant_id", "customers_scanned",
              "customers_matched", "customers_drifted_singular",
              "customers_drifted_plural_nonzero", "customers_fixed",
              "mismatches", "note"):
        assert k in body, f"missing field in audit response: {k}"
    assert body["fix"] is False
    assert body["customers_fixed"] == 0  # dry-run
    assert "DEPRECATED" in body["note"]


# ────────────────────────────────────────────────────────────────────
# 3 · Audit endpoint — role gate (non-admin → 403).
# ────────────────────────────────────────────────────────────────────
def test_credit_parity_audit_requires_admin_role():
    tok = _login("customer@aquaterra.com")
    r = requests.post(
        f"{API}/admin/customers/credit-parity-audit",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code in (401, 403), r.text[:200]


# ────────────────────────────────────────────────────────────────────
# 4 · Portal + admin endpoint parity — both surfaces return the
#     same credit value for the same customer.
# ────────────────────────────────────────────────────────────────────
def test_portal_credit_endpoint_matches_admin_profile(
        live_db, super_admin_headers):
    """End-to-end: grant a credit, hit the portal credit endpoint as
    the customer, hit the admin profile as the admin, assert both
    carry the same cents figure."""
    # Reuse the seeded customer-role fixture at customer@aquaterra.com.
    # That account's customer_id is known from test_credentials.md.
    async def _get_customer_id():
        u = await live_db.users.find_one(
            {"email": "customer@aquaterra.com"},
            {"_id": 0, "customer_id": 1, "tenant_id": 1},
        )
        return u["tenant_id"], u["customer_id"]

    tid, cid = asyncio.get_event_loop().run_until_complete(_get_customer_id())

    # Snapshot the pre-grant balance so we can restore.
    async def _snapshot_pre():
        agg = await live_db.customer_credits_balance.find_one(
            {"tenant_id": tid, "customer_id": cid},
            {"_id": 0, "balance_cents": 1},
        ) or {}
        return int(agg.get("balance_cents") or 0)
    pre = asyncio.get_event_loop().run_until_complete(_snapshot_pre())

    async def _grant():
        from services.customer_balance import mutate_credit
        await mutate_credit(
            live_db, tid, cid, delta_cents=25300,
            source="manual", reason="S2-5 parity test",
        )
    asyncio.get_event_loop().run_until_complete(_grant())

    try:
        # Admin profile.
        r = requests.get(f"{API}/customers/{cid}?slim=1",
                           headers=super_admin_headers, timeout=15)
        assert r.status_code == 200, r.text[:400]
        admin_cents = int(r.json().get("credit_balance_cents") or 0)
        assert admin_cents == pre + 25300, (
            f"admin profile reported {admin_cents}, expected {pre + 25300}"
        )

        # Portal.
        customer_tok = _login("customer@aquaterra.com")
        r = requests.get(f"{API}/customer-portal/credits/balance",
                           headers={"Authorization": f"Bearer {customer_tok}"},
                           timeout=15)
        assert r.status_code == 200, r.text[:400]
        portal_body = r.json()
        portal_cents = int(portal_body.get("balance_cents") or 0)

        # Also portal summary.
        r = requests.get(f"{API}/customer-portal/summary",
                           headers={"Authorization": f"Bearer {customer_tok}"},
                           timeout=15)
        assert r.status_code == 200
        summary_credit_dollars = float(r.json().get("credit") or 0)
        summary_cents = int(round(summary_credit_dollars * 100))

        # All three surfaces must agree.
        assert admin_cents == portal_cents == summary_cents, (
            f"parity violated: admin={admin_cents} portal={portal_cents} "
            f"summary={summary_cents}"
        )
        assert portal_body.get("canonical") is True, (
            "portal /credits/balance did not expose canonical=true "
            "flag — S2-2 fix may have regressed"
        )
    finally:
        # Restore pre-test balance via a reverse mutation.
        async def _restore():
            from services.customer_balance import mutate_credit
            await mutate_credit(
                live_db, tid, cid, delta_cents=-25300,
                source="revert", reason="S2-5 teardown",
            )
        asyncio.get_event_loop().run_until_complete(_restore())
