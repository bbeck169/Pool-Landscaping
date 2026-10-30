"""FIN-PARITY-A · Feb-2026 — Parity guard between reconciler
and native ``record_payment``.

The reconciler duplicates ``record_payment``'s numeric rules
rather than refactoring them into a shared helper (see the
FIN-PARITY-A brief §5 for the design fork rationale). This
test file is the load-bearing regression prevention that keeps
the two paths in lockstep.

Two guards:

1. **Source-inspect**: assert the reconciler + ``record_payment``
   both reference the same numeric constants + enum values
   (0.01 tolerance, "paid" / "partial" enum, ``min(paid, total)``
   overpay cap). If a future change edits one but not the other,
   this test trips.

2. **Behavioural parity**: for a set of scenarios, compute the
   final invoice state via BOTH paths:
   (a) reconciler on a seeded invoice + payments,
   (b) ``record_payment``'s inline logic on the same numbers.
   Assert ``amount_paid`` / ``payment_status`` / ``status`` are
   byte-identical.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

PFX = "TESTfpp_"
TENANT = f"{PFX}tenant"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


async def _wipe():
    await _DB.quotes.delete_many({"id": {"$regex": f"^{PFX}"}})
    await _DB.payments.delete_many({"id": {"$regex": f"^{PFX}"}})


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


# ═══════════════════════════════════════════════════════════════════
# §1 · Source-inspect — same constants on both paths
# ═══════════════════════════════════════════════════════════════════
def test_reconciler_and_record_payment_share_tolerance_constant():
    """Both paths must use ``total - 0.01`` (one cent) as the
    fully-paid boundary. If either edits to a different value,
    this test trips."""
    from pathlib import Path
    reconciler_src = (
        Path(__file__).resolve().parents[1] / "services" / "imports"
        / "payment_reconciler.py"
    ).read_text()
    quotes_src = (
        Path(__file__).resolve().parents[1] / "routers" / "quotes.py"
    ).read_text()

    # Reconciler exports the constant + uses it in the compare.
    assert "FULLY_PAID_TOLERANCE = 0.01" in reconciler_src
    assert "total - FULLY_PAID_TOLERANCE" in reconciler_src

    # record_payment uses the same literal 0.01 — grep for the
    # exact incremental-add expression that gates its full-paid
    # transition.
    assert "fully_paid = paid >= total - 0.01" in quotes_src, (
        "record_payment no longer uses `paid >= total - 0.01` for "
        "the fully-paid boundary. Update payment_reconciler."
        "FULLY_PAID_TOLERANCE to match and re-run parity tests."
    )


def test_both_paths_use_min_paid_total_on_overpay():
    """Overpay handling: both paths cap ``amount_paid`` at
    ``total`` via ``min(...)``. If a future change lifts the cap
    on one side (e.g., to persist credit balances), the two
    paths must diverge intentionally, not silently."""
    from pathlib import Path
    reconciler_src = (
        Path(__file__).resolve().parents[1] / "services" / "imports"
        / "payment_reconciler.py"
    ).read_text()
    quotes_src = (
        Path(__file__).resolve().parents[1] / "routers" / "quotes.py"
    ).read_text()

    assert "min(total_paid, total)" in reconciler_src
    # record_payment uses ``min(paid, total)`` in the $set body.
    assert "min(paid, total)" in quotes_src


def test_both_paths_use_paid_partial_enum():
    """Payment status enum values are the same three strings on
    both paths. If ``record_payment`` swaps to a different enum
    (e.g., "closed") the reconciler must be updated in the same
    PR."""
    from pathlib import Path
    reconciler_src = (
        Path(__file__).resolve().parents[1] / "services" / "imports"
        / "payment_reconciler.py"
    ).read_text()
    quotes_src = (
        Path(__file__).resolve().parents[1] / "routers" / "quotes.py"
    ).read_text()

    # record_payment writes exactly two of the three (paid /
    # partial); the third (unpaid) is the initial state.
    assert '"paid" if fully_paid else "partial"' in quotes_src
    # Reconciler exports all three enum constants.
    assert 'PAYMENT_STATUS_UNPAID = "unpaid"' in reconciler_src
    assert 'PAYMENT_STATUS_PARTIAL = "partial"' in reconciler_src
    assert 'PAYMENT_STATUS_PAID = "paid"' in reconciler_src


def test_both_paths_upgrade_status_to_paid_on_full_pay():
    """The status transition rule — full pay flips status to
    ``"paid"`` — must be identical between paths.

    Feb-2026 · FIN-PAID-STATUS-PARITY — flipped from ``"accepted"``
    to ``"paid"`` to match the Stripe-webhook ``_mark_invoice_paid``
    Fix A. Both the native ``record_payment`` and the reconciler
    now emit the same terminal literal so this guard stays
    load-bearing against future drift."""
    from pathlib import Path
    reconciler_src = (
        Path(__file__).resolve().parents[1] / "services" / "imports"
        / "payment_reconciler.py"
    ).read_text()
    quotes_src = (
        Path(__file__).resolve().parents[1] / "routers" / "quotes.py"
    ).read_text()

    # Reconciler upgrades to paid on the fully-paid branch.
    assert 'new_status = "paid"' in reconciler_src
    # record_payment does the same via $set inside the fully_paid
    # if-block. The literal appears in BOTH ``record_payment`` AND
    # ``pay_quote`` (the ``/pay`` sibling) — grep count must be ≥ 2.
    assert quotes_src.count('"status": "paid"') >= 2


# ═══════════════════════════════════════════════════════════════════
# §2 · Behavioural parity — for the same numbers, both paths
#      produce the same final invoice state.
# ═══════════════════════════════════════════════════════════════════
def _record_payment_inline(
    *,
    doc_total: float,
    prior_amount_paid: float,
    prior_status: str,
    incoming_amount: float,
) -> Dict[str, Any]:
    """Compute the post-``record_payment`` invoice state for the
    given inputs — mirrors the exact expressions at
    ``routers/quotes.py:1766-1794``. Kept ASCII-identical to the
    source so a future edit that breaks parity is easy to spot."""
    total = float(doc_total or 0)
    paid = round(float(prior_amount_paid or 0) + incoming_amount, 2)
    fully_paid = paid >= total - 0.01
    update: Dict[str, Any] = {
        "amount_paid": min(paid, total),
        "payment_status": "paid" if fully_paid else "partial",
    }
    if fully_paid:
        update["status"] = "paid"
    else:
        update["status"] = prior_status
    return update


@pytest.mark.parametrize("total, incoming, expected_status", [
    (100.0, 100.0,   "paid"),       # exact full
    (100.0,  50.0,   "partial"),    # partial
    (100.0, 120.0,   "paid"),       # overpay
    (100.0,  99.998, "paid"),       # within tolerance
    (100.0,  99.98,  "partial"),    # outside tolerance
    (100.0, 100.005, "paid"),       # just over
])
def test_behavioural_parity_reconciler_matches_record_payment(
    total, incoming, expected_status,
):
    """For each scenario, seed an invoice with prior_amount_paid=0
    + one payment for ``incoming``. Run the reconciler AND
    compute ``record_payment``'s inline result. Assert
    ``amount_paid`` / ``payment_status`` / ``status`` byte-match."""
    from services.imports.payment_reconciler import (
        reconcile_invoice_after_payment,
    )

    inv_id = f"{PFX}inv_{uuid.uuid4().hex[:10]}"
    _run(_DB.quotes.insert_one({
        "id": inv_id,
        "tenant_id": TENANT,
        "doc_type": "invoice",
        "total": total,
        "amount_paid": 0.0,
        "payment_status": "unpaid",
        "status": "sent",
        "customer_id": f"{PFX}cust",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }))
    _run(_DB.payments.insert_one({
        "id": f"{PFX}pay_{uuid.uuid4().hex[:10]}",
        "tenant_id": TENANT,
        "invoice_id": inv_id,
        "amount": incoming,
        "status": "succeeded",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }))

    # Reconciler path.
    result = _run(
        reconcile_invoice_after_payment(_DB, TENANT, inv_id)
    )
    row = _run(_DB.quotes.find_one({"id": inv_id}))

    # record_payment inline path (no Mongo involvement).
    inline = _record_payment_inline(
        doc_total=total,
        prior_amount_paid=0.0,
        prior_status="sent",
        incoming_amount=incoming,
    )

    # Sanity check the scenario expectation.
    assert inline["payment_status"] == expected_status, (
        f"scenario setup broken: inline says "
        f"{inline['payment_status']!r} but expected "
        f"{expected_status!r}"
    )

    # THE parity assertion — both paths land the same numbers.
    assert row["amount_paid"] == inline["amount_paid"], (
        f"amount_paid drift: reconciler={row['amount_paid']}, "
        f"record_payment_inline={inline['amount_paid']}"
    )
    assert row["payment_status"] == inline["payment_status"], (
        f"payment_status drift: reconciler={row['payment_status']}, "
        f"record_payment_inline={inline['payment_status']}"
    )
    assert row["status"] == inline["status"], (
        f"status drift: reconciler={row['status']}, "
        f"record_payment_inline={inline['status']}"
    )


def test_parity_holds_when_prior_amount_paid_is_nonzero():
    """When the invoice already has ``amount_paid > 0`` and a
    NEW payment lands, the reconciler must reach the same final
    state as ``record_payment`` would have (given the same
    total of payments)."""
    from services.imports.payment_reconciler import (
        reconcile_invoice_after_payment,
    )
    # Scenario: $100 invoice, $30 already paid, $70 arrives.
    inv_id = f"{PFX}inv_{uuid.uuid4().hex[:10]}"
    _run(_DB.quotes.insert_one({
        "id": inv_id,
        "tenant_id": TENANT,
        "doc_type": "invoice",
        "total": 100.0,
        "amount_paid": 30.0,
        "payment_status": "partial",
        "status": "sent",
        "customer_id": f"{PFX}cust",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }))
    # Two payment rows summing to 100 (30 prior + 70 new).
    _run(_DB.payments.insert_one({
        "id": f"{PFX}pay1_{uuid.uuid4().hex[:8]}",
        "tenant_id": TENANT, "invoice_id": inv_id,
        "amount": 30.0, "status": "succeeded",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }))
    _run(_DB.payments.insert_one({
        "id": f"{PFX}pay2_{uuid.uuid4().hex[:8]}",
        "tenant_id": TENANT, "invoice_id": inv_id,
        "amount": 70.0, "status": "succeeded",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }))

    result = _run(
        reconcile_invoice_after_payment(_DB, TENANT, inv_id)
    )
    inline = _record_payment_inline(
        doc_total=100.0, prior_amount_paid=30.0,
        prior_status="sent", incoming_amount=70.0,
    )

    row = _run(_DB.quotes.find_one({"id": inv_id}))
    assert row["amount_paid"] == inline["amount_paid"] == 100.0
    assert row["payment_status"] == inline["payment_status"] == "paid"
    assert row["status"] == inline["status"] == "paid"


def test_parity_holds_on_partial_when_prior_status_is_terminal():
    """Guardrail — if an invoice was previously fully-paid then
    reached a terminal status (``"paid"`` under FIN-PAID-STATUS-
    PARITY, or legacy ``"accepted"`` for pre-backfill rows), a
    subsequent partial recompute (e.g., a payment was voided
    out-of-band) must NOT downgrade the status. Both paths hold
    the same posture: ``record_payment`` cannot downgrade because
    it only adds; the reconciler explicitly guards
    ``prior_status not in ("paid", "accepted")`` before upgrading.

    Feb-2026 · FIN-PAID-STATUS-PARITY — the guard now accepts
    BOTH terminal literals so pre-backfill (``"accepted"``) and
    post-backfill (``"paid"``) rows both no-op on repeat.
    """
    from services.imports.payment_reconciler import (
        reconcile_invoice_after_payment,
    )
    for terminal_prior in ("paid", "accepted"):
        inv_id = f"{PFX}inv_{uuid.uuid4().hex[:10]}"
        _run(_DB.quotes.insert_one({
            "id": inv_id,
            "tenant_id": TENANT,
            "doc_type": "invoice",
            "total": 100.0,
            "amount_paid": 100.0,
            "payment_status": "paid",
            "status": terminal_prior,
            "customer_id": f"{PFX}cust",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }))
        # Only one $50 payment survives after the void.
        _run(_DB.payments.insert_one({
            "id": f"{PFX}pay_{uuid.uuid4().hex[:8]}",
            "tenant_id": TENANT, "invoice_id": inv_id,
            "amount": 50.0, "status": "succeeded",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }))
        result = _run(
            reconcile_invoice_after_payment(_DB, TENANT, inv_id)
        )
        row = _run(_DB.quotes.find_one({"id": inv_id}))
        # amount_paid + payment_status recomputed correctly.
        assert row["amount_paid"] == 50.0
        assert row["payment_status"] == "partial"
        # BUT status stays at the terminal literal — no downgrade.
        assert row["status"] == terminal_prior, (
            f"status drift from terminal {terminal_prior!r}: "
            f"got {row['status']!r}"
        )
        # Result transitions log documents the divergence.
        assert "payment_status: paid → partial" in result.transitions
        # No status transition emitted.
        assert not any(
            t.startswith("status:") for t in result.transitions
        )


# ═══════════════════════════════════════════════════════════════════
# §3 · FIN-PAID-STATUS-PARITY · Feb-2026 — status="paid" + audit
#      crumb coverage for record_payment / pay_quote.
#
# Operator spec (Deliverable 1, Commit 1a):
#   (1) record_payment on fully-paid → status="paid" + crumb
#   (2) /quotes/{id}/pay on fully-paid → same
#   (3) record_payment partial payment → status unchanged
#   (4) record_payment on already-paid invoice → idempotent
#       (no double-flip, previous_status_before_paid preserved)
#
# Pattern: HTTP against the live backend + ``pymongo`` sync for DB
# assertions. This matches the shipped
# ``test_invoice_edit_metadata_bypass_beta.py`` pattern (which the
# earlier Commit A/B dispatch locked as the canonical integration-
# test shape in this codebase). Avoids the custom-event-loop
# binding issue that bites tests which try to call the async
# handler directly with their own Motor client.
# ═══════════════════════════════════════════════════════════════════


_HTTP_API = "http://localhost:8001/api"
_HTTP_TIMEOUT = 15


def _sync_db_handle():
    """Lazy sync pymongo handle on the shipped Mongo URL — matches
    the ``routers.quotes`` live DB so our ``requests`` calls and
    our assertions read/write the same documents."""
    from pymongo import MongoClient as _MC_sync
    return _MC_sync(MONGO_URL)[DB_NAME]


def _login_admin_sync() -> str:
    import requests
    r = requests.post(
        f"{_HTTP_API}/auth/login",
        json={"email": "admin@aquaterra.com", "password": "password123"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _admin_tenant_id_sync(tok: str) -> str:
    import requests
    r = requests.get(
        f"{_HTTP_API}/auth/me",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=_HTTP_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    tid = r.json().get("tenant_id") or ""
    assert tid, "admin login returned no tenant_id"
    return tid


_PFX3 = "TESTfpp3_"


def _wipe3(sdb) -> None:
    sdb.quotes.delete_many({"id": {"$regex": f"^{_PFX3}"}})


def _seed_live_invoice(
    sdb,
    *,
    tenant_id: str,
    total: float = 100.0,
    status: str = "sent",
    payment_status: str = "unpaid",
) -> str:
    inv_id = f"{_PFX3}inv_{uuid.uuid4().hex[:10]}"
    sdb.quotes.insert_one({
        "id": inv_id,
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "title": "Parity live-handler probe",
        "total": total,
        "amount_paid": 0.0,
        "payment_status": payment_status,
        "status": status,
        "customer_id": f"{_PFX3}cust",
        "customer_name": "Parity Test Customer",
        "line_items": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return inv_id


@pytest.fixture
def _live_admin():
    """Admin JWT + tenant_id against the live backend. Guards the
    §3 suite from running when the server isn't up (returns a
    skip marker instead of a cryptic connection error)."""
    import requests
    try:
        tok = _login_admin_sync()
    except (requests.exceptions.ConnectionError,
            requests.exceptions.ReadTimeout) as exc:
        pytest.skip(f"backend not reachable at {_HTTP_API}: {exc}")
    tid = _admin_tenant_id_sync(tok)
    sdb = _sync_db_handle()
    _wipe3(sdb)
    yield {"token": tok, "tenant_id": tid, "sdb": sdb}
    _wipe3(sdb)


def test_record_payment_fully_paid_flips_status_to_paid_with_audit_crumb(_live_admin):
    """§3 · (1) — ``record_payment`` on a fully-paid transition
    must emit ``status="paid"`` AND stamp
    ``previous_status_before_paid`` with the prior ``status``.
    This is the audit crumb a future refund-restore flow uses to
    roll back cleanly (TD-stripe-refund-restore-prepaid-status).
    """
    import requests
    sdb = _live_admin["sdb"]
    inv_id = _seed_live_invoice(
        sdb, tenant_id=_live_admin["tenant_id"],
        total=100.0, status="sent",
    )
    r = requests.post(
        f"{_HTTP_API}/quotes/{inv_id}/record-payment",
        json={"amount": 100.0},
        headers={"Authorization": f"Bearer {_live_admin['token']}"},
        timeout=_HTTP_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    row = sdb.quotes.find_one({"id": inv_id})
    assert row["payment_status"] == "paid"
    assert row["status"] == "paid"
    assert row["previous_status_before_paid"] == "sent"
    assert row["payment_method"] == "manual"
    assert row["amount_paid"] == 100.0


def test_pay_quote_full_payment_flips_status_to_paid_with_audit_crumb(_live_admin):
    """§3 · (2) — ``/quotes/{id}/pay`` (the admin "always full"
    sibling of ``record_payment``) must behave identically. Both
    paths now flip ``status`` to ``"paid"`` and write the audit
    crumb; this is what keeps the FIN-PAID-STATUS-PARITY
    invariant load-bearing against future drift on either
    handler.
    """
    import requests
    sdb = _live_admin["sdb"]
    inv_id = _seed_live_invoice(
        sdb, tenant_id=_live_admin["tenant_id"],
        total=250.0, status="accepted",
    )
    r = requests.post(
        f"{_HTTP_API}/quotes/{inv_id}/pay",
        headers={"Authorization": f"Bearer {_live_admin['token']}"},
        timeout=_HTTP_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    row = sdb.quotes.find_one({"id": inv_id})
    assert row["payment_status"] == "paid"
    assert row["status"] == "paid"
    assert row["previous_status_before_paid"] == "accepted"
    assert row["payment_method"] == "manual"
    assert row["amount_paid"] == 250.0


def test_record_payment_partial_leaves_status_unchanged(_live_admin):
    """§3 · (3) — A partial payment must NOT flip ``status`` and
    must NOT write ``previous_status_before_paid``. Regression
    lock against a future refactor that accidentally moves the
    status write out of the ``fully_paid`` branch.
    """
    import requests
    sdb = _live_admin["sdb"]
    inv_id = _seed_live_invoice(
        sdb, tenant_id=_live_admin["tenant_id"],
        total=100.0, status="sent",
    )
    r = requests.post(
        f"{_HTTP_API}/quotes/{inv_id}/record-payment",
        json={"amount": 40.0},
        headers={"Authorization": f"Bearer {_live_admin['token']}"},
        timeout=_HTTP_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    row = sdb.quotes.find_one({"id": inv_id})
    assert row["payment_status"] == "partial"
    assert row["status"] == "sent", (
        f"partial payment leaked status flip: {row['status']!r}"
    )
    assert row["amount_paid"] == 40.0
    assert "previous_status_before_paid" not in row, (
        "audit crumb written on partial — must only fire on the "
        "fully-paid transition"
    )


def test_record_payment_on_already_paid_invoice_is_idempotent(_live_admin):
    """§3 · (4) — Calling ``record_payment`` a SECOND time (overpay
    / credit-note scenario) must keep ``status="paid"`` AND must
    PRESERVE the ORIGINAL ``previous_status_before_paid`` — never
    clobber it to ``"paid"``. That's the whole point of the
    crumb: a future refund-restore flow needs the ORIGINAL
    pre-paid status, not the terminal status it was between
    calls.
    """
    import requests
    sdb = _live_admin["sdb"]
    inv_id = _seed_live_invoice(
        sdb, tenant_id=_live_admin["tenant_id"],
        total=100.0, status="sent",
    )
    headers = {"Authorization": f"Bearer {_live_admin['token']}"}
    # First call — real fully-paid transition.
    r1 = requests.post(
        f"{_HTTP_API}/quotes/{inv_id}/record-payment",
        json={"amount": 100.0}, headers=headers, timeout=_HTTP_TIMEOUT,
    )
    assert r1.status_code == 200, r1.text
    row1 = sdb.quotes.find_one({"id": inv_id})
    assert row1["previous_status_before_paid"] == "sent"

    # Second call — overpay / credit scenario. amount>0 so the
    # 400 guard doesn't fire; ``min(paid, total)`` caps
    # ``amount_paid``; the fully_paid branch runs AGAIN with
    # ``doc.get("status") == "paid"`` — the audit crumb MUST
    # NOT get clobbered to ``"paid"``.
    r2 = requests.post(
        f"{_HTTP_API}/quotes/{inv_id}/record-payment",
        json={"amount": 5.0}, headers=headers, timeout=_HTTP_TIMEOUT,
    )
    assert r2.status_code == 200, r2.text
    row2 = sdb.quotes.find_one({"id": inv_id})
    assert row2["payment_status"] == "paid"
    assert row2["status"] == "paid"
    assert row2["previous_status_before_paid"] == "sent", (
        f"audit crumb clobbered on repeat call: "
        f"{row2['previous_status_before_paid']!r} (expected 'sent')"
    )
    # amount_paid caps at total — no over-posting.
    assert row2["amount_paid"] == 100.0
