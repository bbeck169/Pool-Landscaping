"""PERF-AUDIT-C · Feb-2026 — Customer-balance compute + denorm + audit tests.

Locks the contract for
``services.customer_balance.compute_customer_balance`` across the
balance edge cases flagged by the Feb-2026 performance audit:

  * Empty — no invoices, no credits → every tile zero.
  * Draft invoice counted ONLY when payment_status unpaid/partial.
  * Void (soft-deleted) invoice excluded.
  * Partial payment reflects the unpaid remainder.
  * Past-due filter kicks in on due_date < today_iso.
  * Credit applied partial: ``amount_paid`` moves, remaining
    balance drops, unapplied credit sits on
    ``customer_credits_balance``.
  * Unapplied credit alone: credit_balance_cents > 0, balance_due
    unchanged.

Also covers:

  * ``recompute_customer_balance_denorm`` writes to the customer
    doc + reports ``persisted=True``.
  * ``ensure_fresh_balance_denorm`` returns the cached values when
    stored fields are fresh; triggers a recompute when stale.
  * ``audit_tenant_customer_balances`` dry-run reports drift
    without writing; ``fix=True`` writes.
  * ``POST /api/admin/customers/balance-audit`` auth gate (non-
    admin → 403) + report shape.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

import pytest
from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


_TENANT_PREFIX = "TEST-balance-audit-"


def _mk_tid() -> str:
    return _TENANT_PREFIX + uuid.uuid4().hex[:12]


def _mk_cid() -> str:
    return _TENANT_PREFIX + "c-" + uuid.uuid4().hex[:12]


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _yesterday_iso() -> str:
    return (datetime.now(timezone.utc)
            - timedelta(days=1)).date().isoformat()


def _tomorrow_iso() -> str:
    return (datetime.now(timezone.utc)
            + timedelta(days=1)).date().isoformat()


async def _seed_customer(db, tid: str, cid: str) -> None:
    await db.customers.insert_one({
        "id": cid, "tenant_id": tid,
        "name": "Test Customer", "email": f"{cid}@t.local",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


async def _seed_invoice(
    db, tid: str, cid: str, *,
    total: float,
    amount_paid: float = 0.0,
    payment_status: str = "unpaid",
    due_date: str | None = None,
    deleted: bool = False,
    status: str = "sent",
) -> str:
    iid = _TENANT_PREFIX + "i-" + uuid.uuid4().hex[:10]
    await db.quotes.insert_one({
        "id": iid, "tenant_id": tid, "customer_id": cid,
        "doc_type": "invoice", "status": status,
        "payment_status": payment_status,
        "total": total, "amount_paid": amount_paid,
        "due_date": due_date,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "deleted_at": datetime.now(timezone.utc).isoformat()
        if deleted else None,
    })
    return iid


async def _seed_credit(
    db, tid: str, cid: str, *, balance_cents: int,
) -> None:
    await db.customer_credits_balance.update_one(
        {"tenant_id": tid, "customer_id": cid},
        {"$set": {"balance_cents": balance_cents}},
        upsert=True,
    )


async def _cleanup(db, tid: str) -> None:
    await db.customers.delete_many({"tenant_id": tid})
    await db.quotes.delete_many({"tenant_id": tid})
    await db.customer_credits_balance.delete_many({"tenant_id": tid})


# ═══════════════════════════════════════════════════════════════════
# compute_customer_balance — edge cases
# ═══════════════════════════════════════════════════════════════════
def test_compute_balance_empty_returns_all_zeros():
    async def _go(db):
        from services.customer_balance import compute_customer_balance
        tid = _mk_tid()
        cid = _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed_customer(db, tid, cid)
            r = await compute_customer_balance(db, tid, cid)
            assert r["balance_due"] == 0.0
            assert r["past_due"] == 0.0
            assert r["credit_balance_cents"] == 0
            assert r["overdue_count"] == 0
            assert r["as_of"]
        finally:
            await _cleanup(db, tid)
    run_test(_go)


def test_compute_balance_draft_unpaid_invoice_counted_in_balance_due():
    """Draft invoices sitting at payment_status=unpaid DO count
    toward balance_due — matches the current KPI endpoint behavior
    which filters on payment_status, not status."""
    async def _go(db):
        from services.customer_balance import compute_customer_balance
        tid = _mk_tid()
        cid = _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed_customer(db, tid, cid)
            await _seed_invoice(db, tid, cid, total=100.0,
                                 status="draft",
                                 payment_status="unpaid")
            r = await compute_customer_balance(db, tid, cid)
            assert r["balance_due"] == 100.0
            assert r["overdue_count"] == 0  # no due_date
        finally:
            await _cleanup(db, tid)
    run_test(_go)


def test_compute_balance_void_invoice_excluded():
    """Soft-deleted invoice must NOT contribute to balance_due."""
    async def _go(db):
        from services.customer_balance import compute_customer_balance
        tid = _mk_tid()
        cid = _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed_customer(db, tid, cid)
            await _seed_invoice(db, tid, cid, total=1_000.0,
                                 deleted=True)
            r = await compute_customer_balance(db, tid, cid)
            assert r["balance_due"] == 0.0
        finally:
            await _cleanup(db, tid)
    run_test(_go)


def test_compute_balance_paid_invoice_excluded():
    """Fully-paid invoice (payment_status=paid) must NOT contribute."""
    async def _go(db):
        from services.customer_balance import compute_customer_balance
        tid = _mk_tid()
        cid = _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed_customer(db, tid, cid)
            await _seed_invoice(db, tid, cid, total=500.0,
                                 amount_paid=500.0,
                                 payment_status="paid")
            r = await compute_customer_balance(db, tid, cid)
            assert r["balance_due"] == 0.0
        finally:
            await _cleanup(db, tid)
    run_test(_go)


def test_compute_balance_partial_payment_reflects_remainder():
    async def _go(db):
        from services.customer_balance import compute_customer_balance
        tid = _mk_tid()
        cid = _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed_customer(db, tid, cid)
            await _seed_invoice(db, tid, cid, total=400.0,
                                 amount_paid=150.0,
                                 payment_status="partial")
            r = await compute_customer_balance(db, tid, cid)
            assert r["balance_due"] == 250.0
            assert r["past_due"] == 0.0  # no due_date
        finally:
            await _cleanup(db, tid)
    run_test(_go)


def test_compute_balance_past_due_filter_kicks_in_on_due_date_before_today():
    async def _go(db):
        from services.customer_balance import compute_customer_balance
        tid = _mk_tid()
        cid = _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed_customer(db, tid, cid)
            # Past-due: due yesterday, unpaid.
            await _seed_invoice(db, tid, cid, total=300.0,
                                 due_date=_yesterday_iso())
            # Not past-due: due tomorrow, unpaid.
            await _seed_invoice(db, tid, cid, total=150.0,
                                 due_date=_tomorrow_iso())
            r = await compute_customer_balance(db, tid, cid)
            assert r["balance_due"] == 450.0
            assert r["past_due"] == 300.0
            assert r["overdue_count"] == 1
        finally:
            await _cleanup(db, tid)
    run_test(_go)


def test_compute_balance_unapplied_credit_only():
    """Unapplied credit sitting on customer_credits_balance surfaces
    in ``credit_balance_cents`` without affecting ``balance_due``."""
    async def _go(db):
        from services.customer_balance import compute_customer_balance
        tid = _mk_tid()
        cid = _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed_customer(db, tid, cid)
            await _seed_credit(db, tid, cid, balance_cents=2500)
            r = await compute_customer_balance(db, tid, cid)
            assert r["credit_balance_cents"] == 2500
            assert r["balance_due"] == 0.0
        finally:
            await _cleanup(db, tid)
    run_test(_go)


def test_compute_balance_credit_applied_partial_scenario():
    """Credit partially applied to an invoice: ``amount_paid``
    advances by the applied portion → balance drops; the unapplied
    remainder sits on ``customer_credits_balance``."""
    async def _go(db):
        from services.customer_balance import compute_customer_balance
        tid = _mk_tid()
        cid = _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed_customer(db, tid, cid)
            # Invoice $200 with $75 already applied from a credit.
            await _seed_invoice(db, tid, cid, total=200.0,
                                 amount_paid=75.0,
                                 payment_status="partial")
            # $25 unapplied credit sitting on the account.
            await _seed_credit(db, tid, cid, balance_cents=2500)
            r = await compute_customer_balance(db, tid, cid)
            assert r["balance_due"] == 125.0
            assert r["credit_balance_cents"] == 2500
        finally:
            await _cleanup(db, tid)
    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# recompute_customer_balance_denorm — persists to customer doc
# ═══════════════════════════════════════════════════════════════════
def test_recompute_denorm_writes_fields_to_customer_doc():
    async def _go(db):
        from services.customer_balance import (
            recompute_customer_balance_denorm,
        )
        tid = _mk_tid()
        cid = _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed_customer(db, tid, cid)
            await _seed_invoice(db, tid, cid, total=333.0,
                                 due_date=_yesterday_iso())
            r = await recompute_customer_balance_denorm(db, tid, cid)
            assert r["persisted"] is True

            cust = await db.customers.find_one(
                {"id": cid, "tenant_id": tid},
                {"_id": 0, "balance_due": 1, "past_due": 1,
                 "overdue_count": 1, "credit_balance_cents": 1,
                 "balance_recomputed_at": 1},
            )
            assert cust["balance_due"] == 333.0
            assert cust["past_due"] == 333.0
            assert cust["overdue_count"] == 1
            assert cust["credit_balance_cents"] == 0
            assert cust["balance_recomputed_at"]
        finally:
            await _cleanup(db, tid)
    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# ensure_fresh_balance_denorm — stale/fresh branching
# ═══════════════════════════════════════════════════════════════════
def test_ensure_fresh_denorm_recomputes_when_missing():
    async def _go(db):
        from services.customer_balance import ensure_fresh_balance_denorm
        tid = _mk_tid()
        cid = _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed_customer(db, tid, cid)
            await _seed_invoice(db, tid, cid, total=50.0)
            r = await ensure_fresh_balance_denorm(db, tid, cid)
            assert r["balance_due"] == 50.0
            cust = await db.customers.find_one(
                {"id": cid, "tenant_id": tid},
                {"_id": 0, "balance_due": 1,
                 "balance_recomputed_at": 1},
            )
            assert cust["balance_due"] == 50.0
            assert cust["balance_recomputed_at"]
        finally:
            await _cleanup(db, tid)
    run_test(_go)


def test_ensure_fresh_denorm_returns_cached_when_fresh():
    async def _go(db):
        from services.customer_balance import ensure_fresh_balance_denorm
        tid = _mk_tid()
        cid = _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed_customer(db, tid, cid)
            # Pre-stamp a FAKE value with a very recent timestamp
            # (within the stale threshold).  ensure_fresh must
            # trust the cache and NOT re-aggregate.
            await db.customers.update_one(
                {"id": cid, "tenant_id": tid},
                {"$set": {
                    "balance_due": 99.99,
                    "past_due": 0.0,
                    "credit_balance_cents": 0,
                    "overdue_count": 0,
                    "balance_recomputed_at":
                        datetime.now(timezone.utc).isoformat(),
                }},
            )
            # Seed an invoice that would push true balance_due to
            # 500 — but ensure_fresh must return the cached 99.99.
            await _seed_invoice(db, tid, cid, total=500.0)
            r = await ensure_fresh_balance_denorm(db, tid, cid)
            assert r["balance_due"] == 99.99
        finally:
            await _cleanup(db, tid)
    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# audit_tenant_customer_balances — dry-run + fix
# ═══════════════════════════════════════════════════════════════════
def test_audit_reports_drift_without_writing_in_dry_run():
    async def _go(db):
        from services.customer_balance import (
            audit_tenant_customer_balances,
        )
        tid = _mk_tid()
        cid = _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed_customer(db, tid, cid)
            # Stored stale value — stored=0, computed will be 42.
            await db.customers.update_one(
                {"id": cid, "tenant_id": tid},
                {"$set": {
                    "balance_due": 0.0, "past_due": 0.0,
                    "credit_balance_cents": 0, "overdue_count": 0,
                    "balance_recomputed_at":
                        datetime.now(timezone.utc).isoformat(),
                }},
            )
            await _seed_invoice(db, tid, cid, total=42.0)

            r = await audit_tenant_customer_balances(
                db, tid, fix=False,
            )
            assert r["ok"] is True
            assert r["customers_drifted"] == 1
            assert r["customers_fixed"] == 0
            assert len(r["mismatches"]) == 1
            assert r["mismatches"][0]["customer_id"] == cid

            # Dry-run must NOT have written.
            cust = await db.customers.find_one(
                {"id": cid, "tenant_id": tid},
                {"_id": 0, "balance_due": 1},
            )
            assert cust["balance_due"] == 0.0
        finally:
            await _cleanup(db, tid)
    run_test(_go)


def test_audit_fix_writes_computed_values_back():
    async def _go(db):
        from services.customer_balance import (
            audit_tenant_customer_balances,
        )
        tid = _mk_tid()
        cid = _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed_customer(db, tid, cid)
            await _seed_invoice(db, tid, cid, total=77.0,
                                 due_date=_yesterday_iso())

            r = await audit_tenant_customer_balances(
                db, tid, fix=True,
            )
            assert r["customers_missing"] == 1
            assert r["customers_fixed"] == 1

            cust = await db.customers.find_one(
                {"id": cid, "tenant_id": tid},
                {"_id": 0, "balance_due": 1, "past_due": 1,
                 "overdue_count": 1, "balance_recomputed_at": 1},
            )
            assert cust["balance_due"] == 77.0
            assert cust["past_due"] == 77.0
            assert cust["overdue_count"] == 1
            assert cust["balance_recomputed_at"]
        finally:
            await _cleanup(db, tid)
    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# POST /admin/customers/balance-audit — auth gate
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("role", ["customer", "technician"])
def test_balance_audit_endpoint_rejects_non_admin(role):
    async def _go(db):
        import routers.admin_migrations as _am
        _am.db = db
        from routers.admin_migrations import run_customer_balance_audit
        user = {"id": "u", "role": role}
        tenant = {"id": "t-x"}
        with pytest.raises(HTTPException) as excinfo:
            await run_customer_balance_audit(
                fix=False, limit=None, user=user, tenant=tenant,
            )
        assert excinfo.value.status_code == 403
    run_test(_go)


def test_balance_audit_endpoint_admin_dry_run_returns_report_shape():
    async def _go(db):
        import routers.admin_migrations as _am
        _am.db = db
        from routers.admin_migrations import run_customer_balance_audit
        tid = _mk_tid()
        cid = _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed_customer(db, tid, cid)
            await _seed_invoice(db, tid, cid, total=10.0)
            user = {"id": "admin-x", "role": "admin"}
            tenant = {"id": tid}
            r = await run_customer_balance_audit(
                fix=False, limit=None, user=user, tenant=tenant,
            )
            assert r["ok"] is True
            assert r["fix"] is False
            assert r["tenant_id"] == tid
            assert r["customers_scanned"] >= 1
            assert "mismatches" in r
        finally:
            await _cleanup(db, tid)
    run_test(_go)
