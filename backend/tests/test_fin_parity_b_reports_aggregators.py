"""FIN-PARITY-B · Feb-2026 — Reports aggregators pick up FIN-PARITY-A
reconciled totals.

Locks:

  * ``PAID_STATUS_FILTER`` includes reconciler-written
    ``amount_paid > 0`` invoices even when ``payment_status`` is
    still ``partial`` (partial payments count as collected).
  * ``OUTSTANDING_STATUS_FILTER`` includes ``payment_status="partial"``
    invoices so their unpaid remainder shows up in AR / unpaid-list
    metrics (regression guard on the FIN-PARITY-B change to the
    filter's ``$in`` list).
  * The Revenue-slice helpers ``_fetch_paid`` /
    ``_fetch_all_invoices`` return reconciler-written rows without
    an explicit ``paid_at`` (they lean on the shared status filter).
  * The reports gross_sales endpoint's ``summary.collected`` sums
    ``_paid_amt`` across three states (unpaid / partial / paid).
  * Tenant isolation — an aggregator on tenant A never returns
    tenant B's invoices.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

_TEST_DIR = Path(__file__).resolve().parent
_BE = dotenv_values(_TEST_DIR.parent / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(MONGO_URL, io_loop=_LOOP)
_DB = _MC[DB_NAME]

# Isolate this suite's seed rows from every other test suite.
PFX = "TESTfpB_"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


async def _seed_invoice(
    *,
    tenant_id: str,
    total: float,
    amount_paid: float = 0.0,
    payment_status: str = "unpaid",
    status: str = "sent",
    paid_at: Optional[str] = None,
    created_at: Optional[str] = None,
) -> str:
    inv_id = f"{PFX}inv_{uuid.uuid4().hex[:10]}"
    doc: Dict[str, Any] = {
        "id": inv_id,
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "total": total,
        "amount_paid": amount_paid,
        "payment_status": payment_status,
        "status": status,
        "customer_id": f"{PFX}cust_{uuid.uuid4().hex[:6]}",
        "customer_name": "Test Customer",
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
    }
    if paid_at:
        doc["paid_at"] = paid_at
    await _DB.quotes.insert_one(doc)
    return inv_id


async def _wipe():
    await _DB.quotes.delete_many({"id": {"$regex": f"^{PFX}"}})


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


TENANT = f"{PFX}tenant_A"
TENANT_B = f"{PFX}tenant_B"


# ═══════════════════════════════════════════════════════════════════
# §1 · PAID_STATUS_FILTER picks up reconciler-written amount_paid
# ═══════════════════════════════════════════════════════════════════
def test_paid_status_filter_includes_partial_payments():
    """A partial-paid invoice (amount_paid > 0, payment_status=partial)
    must satisfy PAID_STATUS_FILTER because ``amount_paid > 0`` — no
    schema change required to surface reconciled partials in the
    Collected column."""
    from services.reporting.paid_date import PAID_STATUS_FILTER

    async def _go():
        await _seed_invoice(
            tenant_id=TENANT, total=200.0,
            amount_paid=75.0, payment_status="partial",
        )
        # This mirrors what revenue_total / cashflow / pnl aggregate
        # into when they slice on PAID_STATUS_FILTER.
        cursor = _DB.quotes.find(
            {"tenant_id": TENANT, **PAID_STATUS_FILTER},
        )
        docs = await cursor.to_list(None)
        assert len(docs) == 1
        assert docs[0]["payment_status"] == "partial"
        assert docs[0]["amount_paid"] == 75.0
    _run(_go())


def test_paid_status_filter_still_matches_legacy_paid_flag_only():
    """Legacy rows: payment_status=paid but amount_paid=0/None still
    show up (backward-compat via the ``payment_status=paid`` branch)."""
    from services.reporting.paid_date import PAID_STATUS_FILTER

    async def _go():
        await _seed_invoice(
            tenant_id=TENANT, total=100.0,
            amount_paid=0.0, payment_status="paid",
        )
        docs = await _DB.quotes.find(
            {"tenant_id": TENANT, **PAID_STATUS_FILTER},
        ).to_list(None)
        assert len(docs) == 1
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# §2 · OUTSTANDING_STATUS_FILTER includes partial payments (regression
# guard on the FIN-PARITY-B change to the $in list)
# ═══════════════════════════════════════════════════════════════════
def test_outstanding_filter_includes_partial_status():
    from services.reporting.paid_date import OUTSTANDING_STATUS_FILTER

    async def _go():
        # Three invoices — unpaid, partial (FIN-PARITY-A reconciler
        # target), fully paid.
        await _seed_invoice(
            tenant_id=TENANT, total=100.0,
            amount_paid=0.0, payment_status="unpaid",
        )
        await _seed_invoice(
            tenant_id=TENANT, total=200.0,
            amount_paid=50.0, payment_status="partial",
        )
        await _seed_invoice(
            tenant_id=TENANT, total=300.0,
            amount_paid=300.0, payment_status="paid", status="accepted",
        )
        rows = await _DB.quotes.find(
            {"tenant_id": TENANT, **OUTSTANDING_STATUS_FILTER},
        ).to_list(None)
        statuses = sorted(r["payment_status"] for r in rows)
        # Unpaid + partial land in outstanding; paid does not.
        assert statuses == ["partial", "unpaid"]
    _run(_go())


def test_outstanding_filter_excludes_paid_status():
    from services.reporting.paid_date import OUTSTANDING_STATUS_FILTER

    async def _go():
        await _seed_invoice(
            tenant_id=TENANT, total=100.0,
            amount_paid=100.0, payment_status="paid", status="accepted",
        )
        rows = await _DB.quotes.find(
            {"tenant_id": TENANT, **OUTSTANDING_STATUS_FILTER},
        ).to_list(None)
        assert rows == []
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# §3 · Revenue-slice helpers behave the same for reconciled invoices
# ═══════════════════════════════════════════════════════════════════
def test_fetch_paid_picks_up_reconciled_partial_via_amount_paid_gt_0():
    """``routers.reports._fetch_paid`` uses the same PAID_STATUS_FILTER
    shape inline; make sure a reconciler-partial row lands in the
    result set even without payment_status=paid."""
    from routers import reports as reports_mod

    async def _go():
        inv_id = await _seed_invoice(
            tenant_id=TENANT, total=500.0,
            amount_paid=200.0, payment_status="partial",
            created_at="2026-01-15T10:00:00Z",
        )
        orig_db = reports_mod.db
        reports_mod.db = _DB
        try:
            rows = await reports_mod._fetch_paid(TENANT, None, None)
        finally:
            reports_mod.db = orig_db
        matching = [r for r in rows if r.get("id") == inv_id]
        assert len(matching) == 1
    _run(_go())


def test_paid_amt_returns_amount_paid_verbatim_for_partial():
    """``_paid_amt`` on a partial row returns ``amount_paid`` directly
    (not the legacy ``total if payment_status==paid`` shim). Verifies
    the FIN-PARITY-A reconciled amount is what gross_sales.collected
    consumes."""
    from routers.reports import _paid_amt

    row = {
        "amount_paid": 275.50,
        "payment_status": "partial",
        "total": 500.0,
    }
    assert _paid_amt(row) == 275.50


def test_paid_amt_legacy_shim_preserved_for_paid_status_without_amount():
    """Legacy backward-compat: paid_status=paid with amount_paid=0
    still returns total (matches pre-FIN-PARITY-A behavior for rows
    that never got a reconciler pass)."""
    from routers.reports import _paid_amt

    row = {
        "amount_paid": 0.0,
        "payment_status": "paid",
        "total": 400.0,
    }
    assert _paid_amt(row) == 400.0


# ═══════════════════════════════════════════════════════════════════
# §4 · Aggregate sanity — gross_sales.collected across 3-state mix
# ═══════════════════════════════════════════════════════════════════
def test_gross_sales_collected_sums_across_unpaid_partial_paid():
    """Seed one of each state, run _fetch_all_invoices + _paid_amt
    the same way ``gross_sales`` does, verify collected = 0 (unpaid) +
    75 (partial reconciler) + 300 (paid) = 375."""
    from routers import reports as reports_mod

    async def _go():
        # Bracket everything inside a stable window so the range
        # filter is a no-op.
        window = "2026-03-15T00:00:00Z"
        await _seed_invoice(
            tenant_id=TENANT, total=100.0,
            amount_paid=0.0, payment_status="unpaid",
            created_at=window,
        )
        await _seed_invoice(
            tenant_id=TENANT, total=200.0,
            amount_paid=75.0, payment_status="partial",
            created_at=window,
        )
        await _seed_invoice(
            tenant_id=TENANT, total=300.0,
            amount_paid=300.0, payment_status="paid", status="accepted",
            created_at=window,
        )
        orig_db = reports_mod.db
        reports_mod.db = _DB
        try:
            invs = await reports_mod._fetch_all_invoices(TENANT, None, None)
        finally:
            reports_mod.db = orig_db
        # Filter to this suite's rows only (other suites can leave
        # stragglers if they leak — belt & braces).
        ours = [i for i in invs if i.get("id", "").startswith(PFX)]
        assert len(ours) == 3
        total = round(sum(float(i.get("total") or 0) for i in ours), 2)
        paid = round(sum(reports_mod._paid_amt(i) for i in ours), 2)
        outstanding = round(total - paid, 2)
        assert total == 600.0
        assert paid == 375.0
        assert outstanding == 225.0
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# §5 · Reconciler-written invoice flows through same aggregators
# ═══════════════════════════════════════════════════════════════════
def test_reconciler_write_shows_up_in_paid_status_filter():
    """End-to-end sanity: seed an unpaid invoice + a payment, run the
    FIN-PARITY-A reconciler, then query PAID_STATUS_FILTER. The row
    must land in the paid set."""
    from services.imports.payment_reconciler import (
        reconcile_invoice_after_payment,
    )
    from services.reporting.paid_date import PAID_STATUS_FILTER

    async def _go():
        inv_id = await _seed_invoice(
            tenant_id=TENANT, total=250.0,
            amount_paid=0.0, payment_status="unpaid",
        )
        pay_id = f"{PFX}pay_{uuid.uuid4().hex[:10]}"
        await _DB.payments.insert_one({
            "id": pay_id, "tenant_id": TENANT,
            "invoice_id": inv_id, "amount": 250.0,
            "status": "succeeded",
            "paid_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            await reconcile_invoice_after_payment(
                db=_DB, tenant_id=TENANT, invoice_id=inv_id,
            )
            docs = await _DB.quotes.find(
                {"tenant_id": TENANT, "id": inv_id, **PAID_STATUS_FILTER},
            ).to_list(None)
            assert len(docs) == 1
            assert docs[0]["payment_status"] == "paid"
        finally:
            await _DB.payments.delete_one({"id": pay_id})
    _run(_go())


# ═══════════════════════════════════════════════════════════════════
# §6 · Tenant isolation — aggregators do not leak across tenants
# ═══════════════════════════════════════════════════════════════════
def test_fetch_paid_is_tenant_scoped():
    from routers import reports as reports_mod

    async def _go():
        await _seed_invoice(
            tenant_id=TENANT, total=100.0,
            amount_paid=100.0, payment_status="paid",
        )
        await _seed_invoice(
            tenant_id=TENANT_B, total=999.0,
            amount_paid=999.0, payment_status="paid",
        )
        orig_db = reports_mod.db
        reports_mod.db = _DB
        try:
            rows_a = await reports_mod._fetch_paid(TENANT, None, None)
            rows_b = await reports_mod._fetch_paid(TENANT_B, None, None)
        finally:
            reports_mod.db = orig_db
        # Filter to this suite's rows for cross-suite noise
        # tolerance.
        a_ids = {r["id"] for r in rows_a if r.get("id", "").startswith(PFX)}
        b_ids = {r["id"] for r in rows_b if r.get("id", "").startswith(PFX)}
        # No overlap between tenants.
        assert a_ids.isdisjoint(b_ids)
        # Each tenant only sees its own row.
        assert len(a_ids) == 1
        assert len(b_ids) == 1
    _run(_go())


def test_outstanding_filter_is_tenant_scoped():
    from services.reporting.paid_date import OUTSTANDING_STATUS_FILTER

    async def _go():
        await _seed_invoice(
            tenant_id=TENANT, total=100.0,
            amount_paid=0.0, payment_status="unpaid",
        )
        await _seed_invoice(
            tenant_id=TENANT_B, total=500.0,
            amount_paid=250.0, payment_status="partial",
        )
        rows = await _DB.quotes.find(
            {"tenant_id": TENANT, **OUTSTANDING_STATUS_FILTER},
        ).to_list(None)
        # Must NOT see tenant B's partial row.
        assert all(r["tenant_id"] == TENANT for r in rows)
        assert len(rows) == 1
    _run(_go())
