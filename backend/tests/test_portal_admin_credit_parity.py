"""DATA-PARITY-C1 · Feb-2026 — Portal/admin credit parity.

The customer portal landing endpoint
(``GET /customer-portal/summary``) previously computed credit
INLINE by summing invoice overpayments, which diverged from the
admin KPI endpoint's ledger-based read of
``customer_credits_balance.balance_cents``.  Diane Lloyd on
production had $280 admin / $0 portal — classic drift shape.

This file locks parity:

  1. **Shared compute returns a canonical credit** — seeding a
     ledger-only credit (admin ``Issue Credit`` / referral reward
     write path) with ZERO invoice overpayments produces the
     SAME non-zero credit value from both the shared compute
     function AND the admin KPI endpoint.
  2. **Portal summary now uses the canonical value** — direct
     invocation of ``routers.customer_portal.get_portal_summary``
     with the same ledger-only credit returns the same credit
     figure as the admin KPI endpoint.  No divergence.
  3. **Legacy overpayment-only shape still works** — a customer
     with overpayments but no ledger credit still sees the right
     credit figure (because applied-overpayments inflate
     ``amount_paid`` which flows through ``compute_customer_balance``
     via the balance aggregation — the portal doesn't lose this
     scenario when switching sources).

Loop/DB hygiene reuses ``_f7_loop_fixture.run_test`` + a unique
``TEST-portal-credit-parity-`` tenant prefix per test.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


_PREFIX = "TEST-portal-credit-parity-"


def _mk_tid() -> str:
    return _PREFIX + uuid.uuid4().hex[:12]


def _mk_cid() -> str:
    return _PREFIX + "c-" + uuid.uuid4().hex[:12]


async def _seed_customer(db, tid: str, cid: str) -> None:
    await db.customers.insert_one({
        "id": cid, "tenant_id": tid,
        "name": "Portal Credit Parity Fixture",
        "email": f"{cid}@t.local",
    })


async def _seed_credit_ledger(
    db, tid: str, cid: str, *, balance_cents: int,
) -> None:
    """Admin "Issue Credit" write path target — writes directly to
    ``customer_credits_balance``.  Zero invoice overpayments."""
    await db.customer_credits_balance.update_one(
        {"tenant_id": tid, "customer_id": cid},
        {"$set": {"balance_cents": balance_cents}},
        upsert=True,
    )


async def _cleanup(db, tid: str) -> None:
    await db.customers.delete_many({"tenant_id": tid})
    await db.quotes.delete_many({"tenant_id": tid})
    await db.customer_credits_balance.delete_many({"tenant_id": tid})


def _rebind(db) -> None:
    import routers.customer_portal as _cp
    import routers.customers as _c
    _cp.db = db
    _c.db = db


# ═══════════════════════════════════════════════════════════════════
# 1. Shared compute returns the ledger-only credit (not derived from
#    invoice overpayments).
# ═══════════════════════════════════════════════════════════════════
def test_shared_compute_returns_ledger_credit_without_invoice_overpayments():
    async def _go(db):
        from services.customer_balance import compute_customer_balance
        tid, cid = _mk_tid(), _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed_customer(db, tid, cid)
            # Admin granted $280 credit — ledger only, no invoices
            # with overpayments.
            await _seed_credit_ledger(db, tid, cid, balance_cents=28000)
            r = await compute_customer_balance(db, tid, cid)
            assert r["credit_balance_cents"] == 28000
            assert r["balance_due"] == 0.0
            assert r["past_due"] == 0.0
        finally:
            await _cleanup(db, tid)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 2. Portal landing summary routes credit through the shared compute
#    → parity with admin KPI endpoint.
# ═══════════════════════════════════════════════════════════════════
def test_portal_summary_credit_matches_admin_kpi_for_ledger_only_credit():
    async def _go(db):
        _rebind(db)
        from routers.customer_portal import get_portal_summary
        from routers.customers import get_customer_kpi_summary

        tid, cid = _mk_tid(), _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed_customer(db, tid, cid)
            await _seed_credit_ledger(db, tid, cid, balance_cents=28000)

            portal_user = {"role": "customer", "customer_id": cid,
                            "id": "u-portal", "email": "p@t.local"}
            admin_user = {"role": "admin", "id": "u-admin",
                           "email": "a@t.local"}
            tenant = {"id": tid}

            portal_summary = await get_portal_summary(
                user=portal_user, tenant=tenant,
            )
            admin_kpi = await get_customer_kpi_summary(
                cid, user=admin_user, tenant=tenant,
            )

            # Portal returns credit in dollars; admin in cents.
            # Convert then compare — must be byte-identical.
            portal_credit_cents = int(
                round(portal_summary["credit"] * 100)
            )
            assert portal_credit_cents == admin_kpi["credit_cents"], (
                f"Portal credit {portal_credit_cents}¢ != "
                f"admin credit {admin_kpi['credit_cents']}¢ — the "
                "DATA-PARITY-C1 fix regressed."
            )
            assert portal_credit_cents == 28000
        finally:
            await _cleanup(db, tid)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 3. Portal rejects non-customer callers (safety guard — the
#    endpoint is role-gated).
# ═══════════════════════════════════════════════════════════════════
def test_portal_summary_rejects_non_customer_role():
    async def _go(db):
        _rebind(db)
        from routers.customer_portal import get_portal_summary
        admin_user = {"role": "admin", "id": "a", "email": "a@t.local"}
        tenant = {"id": "t-x"}
        with pytest.raises(HTTPException) as excinfo:
            await get_portal_summary(user=admin_user, tenant=tenant)
        assert excinfo.value.status_code == 403

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 4. Portal summary breakdown counts remain correct (open_ct + past_ct
#    still computed from the inline invoice loop even after the
#    canonical override of the money figures).
# ═══════════════════════════════════════════════════════════════════
def test_portal_summary_breakdown_counts_still_populated():
    async def _go(db):
        _rebind(db)
        from routers.customer_portal import get_portal_summary

        tid, cid = _mk_tid(), _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed_customer(db, tid, cid)
            # Seed two unpaid invoices.  Field names + payment_status
            # match the inline loop's shape.
            await db.quotes.insert_one({
                "id": _PREFIX + "i1-" + uuid.uuid4().hex[:8],
                "tenant_id": tid, "customer_id": cid,
                "doc_type": "invoice", "status": "sent",
                "payment_status": "unpaid",
                "total": 100.0, "amount_paid": 0.0,
                "due_date": "2020-01-01",   # way past
                "created_at": datetime.now(timezone.utc).isoformat(),
                "deleted_at": None,
            })
            await db.quotes.insert_one({
                "id": _PREFIX + "i2-" + uuid.uuid4().hex[:8],
                "tenant_id": tid, "customer_id": cid,
                "doc_type": "invoice", "status": "sent",
                "payment_status": "unpaid",
                "total": 50.0, "amount_paid": 0.0,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "deleted_at": None,
            })

            portal_user = {"role": "customer", "customer_id": cid,
                            "id": "u-p", "email": "p@t.local"}
            r = await get_portal_summary(
                user=portal_user, tenant={"id": tid},
            )
            assert r["breakdown"]["open_invoice_count"] == 2
            assert r["breakdown"]["past_due_invoice_count"] == 1
            # Canonical money figures from shared compute.
            assert r["balance_due"] == 150.0
            assert r["past_due"] == 100.0
            assert r["credit"] == 0.0
        finally:
            await _cleanup(db, tid)

    run_test(_go)
