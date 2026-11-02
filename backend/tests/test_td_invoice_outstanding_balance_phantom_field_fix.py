"""TD-invoice-outstanding-balance-phantom-field-fix · Nov-2026 —
regression suite.

Locks the two behaviors shipped by this ticket on
``backend/routers/invoice_viewer.py``:

  1. ``outstanding_balance`` in the viewer payload is now computed
     from the customer's OTHER open invoices (sum of
     ``max(total - amount_paid, 0)`` across non-deleted,
     tenant-scoped invoices other than the one being rendered)
     instead of read from the phantom field on the invoice doc.

  2. The displayed label at the PDF + FE render sites is now
     "Prior Balance" (the JSON key ``outstanding_balance`` is
     preserved for API contract stability — only the user-visible
     label changed).

Payment-stub math contract preserved:
    PriorBalance + ThisInvoice - AmountPaid = TotalDueOnAccount

Fixture matrix:

  * One invoice open ($140, unpaid) → PriorBalance $0 (operator's
    reported James Conrad scenario — math-correct under the fix).
  * Two invoices open ($100 prior unpaid + $140 current unpaid)
    → PriorBalance $100 on the $140 render; stub math closes to
    $240 Total Due on Account.
  * Partially-paid prior ($100 total / $30 paid / $70 remaining)
    + current $140 → PriorBalance $70; stub math closes to $210.
  * Soft-deleted prior invoice → excluded from PriorBalance.
  * Paid-off prior invoice (remaining $0) → excluded.
  * Cross-tenant prior invoice → excluded.
  * Same customer, DIFFERENT render target → PriorBalance excludes
    the render target but includes the other.
"""
from __future__ import annotations

import uuid
import asyncio
import pytest

from tests._f7_loop_fixture import run_test


async def _ctx(db):
    t = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
    tid = t["id"]
    admin = await db.users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0, "id": 1, "role": 1},
    )
    return tid, admin


def _inv(cid, tid, total, paid, *, iid=None, deleted=False):
    row = {
        "id": iid or f"TD_OB_{uuid.uuid4().hex[:8]}",
        "tenant_id": tid,
        "customer_id": cid,
        "doc_type": "invoice",
        "total": total,
        "amount_paid": paid,
        "subtotal": total,
        "tax": 0,
    }
    if deleted:
        row["deleted_at"] = "2026-10-01T00:00:00Z"
    return row


async def _mk_customer(db, tid):
    cid = f"CUST_{uuid.uuid4().hex[:8]}"
    await db.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": "Phantom OB Test",
        "address": "", "phone": "", "email": "",
    })
    return cid


async def _cleanup(db, tid, cid):
    await db.quotes.delete_many(
        {"tenant_id": tid, "customer_id": cid, "doc_type": "invoice"},
    )
    await db.customers.delete_one({"id": cid, "tenant_id": tid})


def test_single_open_invoice_prior_balance_zero():
    """James-Conrad analogue: customer has one open invoice.  The
    render of THAT invoice shows PriorBalance=$0 (nothing else is
    open).  Pre-ticket this ALSO showed $0, but by phantom-field
    accident; post-ticket it's math-correct."""
    from routers.invoice_viewer import _build_viewer_payload

    async def _go(db):
        tid, admin = await _ctx(db)
        cid = await _mk_customer(db, tid)
        try:
            iid = f"TD_OB_cur_{uuid.uuid4().hex[:8]}"
            await db.quotes.insert_one(
                _inv(cid, tid, 140, 0, iid=iid),
            )
            payload = await _build_viewer_payload(
                iid, {"id": tid}, {**admin, "tenant_id": tid},
            )
            hdr = payload["header"]
            assert hdr["outstanding_balance"] == 0.0, hdr
            # Payment-stub math: 0 + 140 − 0 = 140 (Total Due on Account).
            total_due = payload["totals"]["total_due"]
            assert total_due == 140.0
            prior = hdr["outstanding_balance"]
            this_inv = payload["totals"]["this_invoice"]
            paid = payload["totals"]["amount_paid"]
            assert prior + this_inv - paid == total_due
        finally:
            await _cleanup(db, tid, cid)

    run_test(_go)


def test_two_open_invoices_prior_balance_sums_other():
    """Customer has $100 prior unpaid + $140 current unpaid.
    Render of the $140 shows PriorBalance=$100, Total Due on
    Account=$240."""
    from routers.invoice_viewer import _build_viewer_payload

    async def _go(db):
        tid, admin = await _ctx(db)
        cid = await _mk_customer(db, tid)
        try:
            prior_iid = f"TD_OB_prior_{uuid.uuid4().hex[:8]}"
            cur_iid = f"TD_OB_cur_{uuid.uuid4().hex[:8]}"
            await db.quotes.insert_many([
                _inv(cid, tid, 100, 0, iid=prior_iid),
                _inv(cid, tid, 140, 0, iid=cur_iid),
            ])
            payload = await _build_viewer_payload(
                cur_iid, {"id": tid}, {**admin, "tenant_id": tid},
            )
            hdr = payload["header"]
            assert hdr["outstanding_balance"] == 100.0, hdr
            # Payment stub math: 100 + 140 − 0 = 240.
            prior = hdr["outstanding_balance"]
            this_inv = payload["totals"]["this_invoice"]
            paid = payload["totals"]["amount_paid"]
            total_due = payload["totals"]["total_due"]
            assert prior + this_inv - paid == 240.0
            assert total_due == 140.0  # this invoice only
        finally:
            await _cleanup(db, tid, cid)

    run_test(_go)


def test_partially_paid_prior_contributes_remaining_only():
    """Prior invoice $100 total / $30 paid → remaining $70.
    PriorBalance on the current $140 render = $70."""
    from routers.invoice_viewer import _build_viewer_payload

    async def _go(db):
        tid, admin = await _ctx(db)
        cid = await _mk_customer(db, tid)
        try:
            cur_iid = f"TD_OB_cur_{uuid.uuid4().hex[:8]}"
            await db.quotes.insert_many([
                _inv(cid, tid, 100, 30),
                _inv(cid, tid, 140, 0, iid=cur_iid),
            ])
            payload = await _build_viewer_payload(
                cur_iid, {"id": tid}, {**admin, "tenant_id": tid},
            )
            assert payload["header"]["outstanding_balance"] == 70.0
        finally:
            await _cleanup(db, tid, cid)

    run_test(_go)


def test_soft_deleted_prior_excluded():
    from routers.invoice_viewer import _build_viewer_payload

    async def _go(db):
        tid, admin = await _ctx(db)
        cid = await _mk_customer(db, tid)
        try:
            cur_iid = f"TD_OB_cur_{uuid.uuid4().hex[:8]}"
            await db.quotes.insert_many([
                _inv(cid, tid, 999, 0, deleted=True),
                _inv(cid, tid, 140, 0, iid=cur_iid),
            ])
            payload = await _build_viewer_payload(
                cur_iid, {"id": tid}, {**admin, "tenant_id": tid},
            )
            assert payload["header"]["outstanding_balance"] == 0.0
        finally:
            await _cleanup(db, tid, cid)

    run_test(_go)


def test_paid_off_prior_excluded():
    """Prior invoice $200 total / $200 paid → remaining $0 →
    excluded from PriorBalance."""
    from routers.invoice_viewer import _build_viewer_payload

    async def _go(db):
        tid, admin = await _ctx(db)
        cid = await _mk_customer(db, tid)
        try:
            cur_iid = f"TD_OB_cur_{uuid.uuid4().hex[:8]}"
            await db.quotes.insert_many([
                _inv(cid, tid, 200, 200),
                _inv(cid, tid, 140, 0, iid=cur_iid),
            ])
            payload = await _build_viewer_payload(
                cur_iid, {"id": tid}, {**admin, "tenant_id": tid},
            )
            assert payload["header"]["outstanding_balance"] == 0.0
        finally:
            await _cleanup(db, tid, cid)

    run_test(_go)


def test_cross_tenant_prior_excluded():
    """A prior invoice on a DIFFERENT tenant for the same customer
    id must not contribute (tenant_id scope)."""
    from routers.invoice_viewer import _build_viewer_payload

    async def _go(db):
        tid, admin = await _ctx(db)
        cid = await _mk_customer(db, tid)
        other_tid = f"NOT_{tid}"
        try:
            cur_iid = f"TD_OB_cur_{uuid.uuid4().hex[:8]}"
            await db.quotes.insert_many([
                _inv(cid, other_tid, 999, 0),   # cross-tenant
                _inv(cid, tid, 140, 0, iid=cur_iid),
            ])
            payload = await _build_viewer_payload(
                cur_iid, {"id": tid}, {**admin, "tenant_id": tid},
            )
            assert payload["header"]["outstanding_balance"] == 0.0
        finally:
            await _cleanup(db, tid, cid)
            await db.quotes.delete_many(
                {"tenant_id": other_tid, "customer_id": cid},
            )

    run_test(_go)


def test_render_target_excluded_from_sum():
    """Same customer, two open invoices.  Render each — each
    renders with the OTHER as PriorBalance.  Locks the ``id: {$ne:
    current_invoice_id}`` clause."""
    from routers.invoice_viewer import _build_viewer_payload

    async def _go(db):
        tid, admin = await _ctx(db)
        cid = await _mk_customer(db, tid)
        try:
            iid_a = f"TD_OB_A_{uuid.uuid4().hex[:8]}"
            iid_b = f"TD_OB_B_{uuid.uuid4().hex[:8]}"
            await db.quotes.insert_many([
                _inv(cid, tid, 100, 0, iid=iid_a),
                _inv(cid, tid, 140, 0, iid=iid_b),
            ])
            pa = await _build_viewer_payload(
                iid_a, {"id": tid}, {**admin, "tenant_id": tid},
            )
            pb = await _build_viewer_payload(
                iid_b, {"id": tid}, {**admin, "tenant_id": tid},
            )
            # Render A → PriorBalance should be B's remaining ($140).
            # Render B → PriorBalance should be A's remaining ($100).
            assert pa["header"]["outstanding_balance"] == 140.0
            assert pb["header"]["outstanding_balance"] == 100.0
        finally:
            await _cleanup(db, tid, cid)

    run_test(_go)


def test_pdf_labels_show_prior_balance_not_outstanding_balance():
    """Static assertion: the shipped PDF labels at
    ``invoice_viewer.py:411`` + ``:530`` read 'Prior Balance'
    (not 'Outstanding Balance').  Guards against a label-only
    regression that would re-confuse operators.

    Strips comment lines before asserting so historical context
    comments can safely reference the pre-ticket phantom-read
    pattern without flagging as a regression."""
    import re
    raw = open("/app/backend/routers/invoice_viewer.py", "r").read()
    # Strip comment-only lines (``#`` at start-of-line after whitespace).
    live = "\n".join(
        line for line in raw.splitlines()
        if not re.match(r"^\s*#", line)
    )
    # Both PDF render sites use the shipped label.
    assert '"Prior Balance"' in live, (
        "PDF label 'Prior Balance' missing — did the rename regress?"
    )
    # The phantom-field read must NOT reappear in LIVE code (comments
    # that reference the pre-ticket pattern are permitted).
    assert 'inv.get("outstanding_balance")' not in live, (
        "Phantom-field read regressed — the fix should compute, "
        "not read the field off the invoice doc."
    )
    # The old display label must NOT appear anywhere in render code.
    for anchor in (
        '[Paragraph("Outstanding Balance"',
        '["Outstanding Balance",',
    ):
        assert anchor not in live, f"old label still at: {anchor!r}"
