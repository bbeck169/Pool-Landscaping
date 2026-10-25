"""TD-stripe-webhook-mark-invoice-paid · Feb-2026
=================================================

Regression lock for:

  Fix A — _mark_invoice_paid flips status="paid" on full payment,
          stamps previous_status_before_paid audit crumb; partial
          payments leave status untouched; idempotent on replay;
          already-paid replay is a no-op.
  Fix B — payments_summary Outstanding filter guards on
          payment_status != "paid" (sub-penny drift tolerant,
          FE/BE aligned).
  Backfill — paid_invoice_status_backfill_v1: dry-run writes
             nothing; apply flips historical draft/issued/sent
             rows; idempotent re-run no-ops; sentinel tracked;
             tenant scope works; partial-payment rows NOT flipped.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _patch_db_everywhere():
    import config
    config.db = _DB
    import routers.payments_summary as _ps_mod
    _ps_mod.db = _DB
    import services.payments.stripe_charge as _sc_mod
    _sc_mod.db = _DB
    import migrations.paid_invoice_status_backfill_v1 as _bf_mod
    _bf_mod.db = _DB


_PFX = f"TESTtdPFP-{uuid4().hex[:8]}"
TENANT = f"{_PFX}-t-a"
TENANT_B = f"{_PFX}-t-b"


async def _seed_tenant(tid):
    await _DB.tenants.update_one(
        {"id": tid}, {"$set": {"id": tid, "name": tid}}, upsert=True,
    )


async def _seed_invoice(
    *, tid, status="issued", payment_status="unpaid",
    amount_paid=0.0, total=100.0, paid_at=None,
    invoice_id=None,
):
    inv_id = invoice_id or f"{_PFX}-inv-{uuid4().hex[:8]}"
    doc = {
        "id": inv_id, "tenant_id": tid, "doc_type": "invoice",
        "customer_id": f"{_PFX}-cust",
        "customer_name": "Test Cust",
        "status": status, "payment_status": payment_status,
        "amount_paid": amount_paid, "total": total,
        "subtotal": total, "tax": 0.0, "tax_rate": 0.0,
        "line_items": [{"id": f"{inv_id}-li1",
                          "description": "svc",
                          "quantity": 1, "unit_price": total}],
        "invoice_number": f"INV-TEST-{uuid4().hex[:6].upper()}",
        "created_at": "2026-02-10T00:00:00+00:00",
        "due_date": "2026-03-10",
    }
    if paid_at:
        doc["paid_at"] = paid_at
    await _DB.quotes.insert_one(doc)
    return inv_id


async def _wipe():
    for coll in ("quotes", "customers", "tenants"):
        await _DB[coll].delete_many({"id": {"$regex": f"^{_PFX}"}})
    await _DB["_migrations"].delete_many(
        {"key": "paid_invoice_status_backfill_v1"},
    )


@pytest.fixture(autouse=True)
def _env():
    _patch_db_everywhere()
    _run(_wipe())
    yield
    _run(_wipe())


# ═══════════════════════════════════════════════════════════════════
# §1 · Fix A — _mark_invoice_paid flips all 5 fields + audit crumb
# ═══════════════════════════════════════════════════════════════════
def test_mark_invoice_paid_full_payment_flips_status_and_all_fields():
    """Full payment → status="paid", payment_status="paid",
    amount_paid=total, paid_at set, payment_method="stripe",
    previous_status_before_paid preserved."""
    from services.payments.stripe_charge import _mark_invoice_paid

    _run(_seed_tenant(TENANT))
    inv_id = _run(_seed_invoice(
        tid=TENANT, status="issued", payment_status="unpaid",
        amount_paid=0.0, total=100.0,
    ))
    paid = _run(_mark_invoice_paid(
        tenant_id=TENANT, invoice_id=inv_id,
        amount_cents=10000, paid_at="2026-11-01T12:00:00+00:00",
        payment_intent_id="pi_test_fullpay_1",
    ))
    assert paid is True

    inv = _run(_DB.quotes.find_one({"id": inv_id}, {"_id": 0}))
    assert inv["status"] == "paid"
    assert inv["payment_status"] == "paid"
    assert inv["amount_paid"] == 100.0
    assert inv["paid_at"] == "2026-11-01T12:00:00+00:00"
    assert inv["payment_method"] == "stripe"
    # Audit crumb — pre-paid status preserved for refund-restore flow.
    assert inv["previous_status_before_paid"] == "issued"


def test_mark_invoice_paid_partial_payment_leaves_status_untouched():
    """Partial payment MUST NOT flip status — invoice must stay
    'live' in Outstanding until fully paid."""
    from services.payments.stripe_charge import _mark_invoice_paid

    _run(_seed_tenant(TENANT))
    inv_id = _run(_seed_invoice(
        tid=TENANT, status="issued", payment_status="unpaid",
        amount_paid=0.0, total=100.0,
    ))
    _run(_mark_invoice_paid(
        tenant_id=TENANT, invoice_id=inv_id,
        amount_cents=4000, paid_at="2026-11-01T12:00:00+00:00",
        payment_intent_id="pi_test_partial_1",
    ))
    inv = _run(_DB.quotes.find_one({"id": inv_id}, {"_id": 0}))
    assert inv["status"] == "issued", (
        f"partial payment flipped status — got {inv['status']!r}"
    )
    assert inv["payment_status"] == "partial"
    assert inv["amount_paid"] == 40.0
    assert "previous_status_before_paid" not in inv
    assert "paid_at" not in inv


def test_mark_invoice_paid_pi_dedup_is_idempotent_on_replay():
    """Replay with the SAME PI id is a no-op — doesn't double-count
    amount_paid, doesn't re-stamp status/crumb."""
    from services.payments.stripe_charge import _mark_invoice_paid

    _run(_seed_tenant(TENANT))
    inv_id = _run(_seed_invoice(
        tid=TENANT, status="issued", total=100.0,
    ))
    pi = "pi_test_replay_1"
    first = _run(_mark_invoice_paid(
        tenant_id=TENANT, invoice_id=inv_id,
        amount_cents=10000, paid_at="2026-11-01T12:00:00+00:00",
        payment_intent_id=pi,
    ))
    second = _run(_mark_invoice_paid(
        tenant_id=TENANT, invoice_id=inv_id,
        amount_cents=10000, paid_at="2026-11-02T12:00:00+00:00",
        payment_intent_id=pi,
    ))
    assert first is True
    assert second is False, "replay should be a no-op"

    inv = _run(_DB.quotes.find_one({"id": inv_id}, {"_id": 0}))
    # Amount NOT doubled.
    assert inv["amount_paid"] == 100.0
    # paid_at stayed on the first delivery's timestamp.
    assert inv["paid_at"] == "2026-11-01T12:00:00+00:00"
    assert inv["status"] == "paid"


def test_mark_invoice_paid_full_payment_does_not_touch_pre_paid_crumb_on_pi_replay():
    """A PI-replay (same payment_intent_id, same amount) is a no-op
    — amount, status, crumb all stable from the first call. This
    is the real-world idempotency contract (replay dedupe is on PI
    id; the legacy-fallback no-PI path is documented in the fn's
    docstring as having known double-count exposure)."""
    from services.payments.stripe_charge import _mark_invoice_paid

    _run(_seed_tenant(TENANT))
    inv_id = _run(_seed_invoice(
        tid=TENANT, status="sent", total=100.0,
    ))
    pi = "pi_test_crumb_stable"
    first = _run(_mark_invoice_paid(
        tenant_id=TENANT, invoice_id=inv_id,
        amount_cents=10000, paid_at="2026-11-01T12:00:00+00:00",
        payment_intent_id=pi,
    ))
    assert first is True

    inv_before = _run(_DB.quotes.find_one({"id": inv_id}, {"_id": 0}))
    assert inv_before["status"] == "paid"
    assert inv_before["previous_status_before_paid"] == "sent"
    assert inv_before["amount_paid"] == 100.0

    # Replay — same PI, blocked by paid_from_intents guard.
    second = _run(_mark_invoice_paid(
        tenant_id=TENANT, invoice_id=inv_id,
        amount_cents=10000, paid_at="2026-11-02T12:00:00+00:00",
        payment_intent_id=pi,
    ))
    assert second is False
    inv_after = _run(_DB.quotes.find_one({"id": inv_id}, {"_id": 0}))
    # Crumb preserves the FIRST call's pre-paid value, not a
    # second-call "paid" value.
    assert inv_after["previous_status_before_paid"] == "sent"
    assert inv_after["status"] == "paid"
    assert inv_after["amount_paid"] == 100.0
    # paid_at stayed on the first delivery's timestamp.
    assert inv_after["paid_at"] == "2026-11-01T12:00:00+00:00"


# ═══════════════════════════════════════════════════════════════════
# §2 · Fix B — Outstanding filter honours payment_status != "paid"
# ═══════════════════════════════════════════════════════════════════
def test_outstanding_filter_excludes_paid_invoice_with_subpenny_drift():
    """An invoice with payment_status="paid" but amount_paid lagging
    total by 0.004 (sub-penny) must NOT tally into Outstanding.
    Belt-and-braces regression lock on the Fix B guard."""
    from routers.payments_summary import payments_summary

    _run(_seed_tenant(TENANT))
    # Fully-paid invoice with a sub-penny gap — simulates
    # floating-point drift from the fully-paid gate
    # (new_paid + 0.01 >= total means amount_paid can lag by up
    # to one cent).
    _run(_seed_invoice(
        tid=TENANT, status="issued",
        payment_status="paid",
        amount_paid=99.996, total=100.0,
        paid_at="2026-11-01T12:00:00+00:00",
    ))
    # Also seed an unpaid issued invoice so there's a positive
    # control — the filter still catches real outstanding rows.
    _run(_seed_invoice(
        tid=TENANT, status="issued", payment_status="unpaid",
        amount_paid=0.0, total=50.0,
    ))

    res = _run(payments_summary(
        user={"role": "admin", "tenant_id": TENANT},
    ))
    # Only the unpaid $50 lands in Outstanding — the paid-but-drifty
    # row is excluded by Fix B.
    assert res["outstanding_count"] == 1
    assert res["outstanding_total"] == 50.0


def test_outstanding_filter_still_counts_truly_unpaid():
    """Positive control — regression lock that Fix B didn't break
    the common case."""
    from routers.payments_summary import payments_summary

    _run(_seed_tenant(TENANT))
    _run(_seed_invoice(
        tid=TENANT, status="issued", payment_status="unpaid",
        amount_paid=0.0, total=100.0,
    ))
    _run(_seed_invoice(
        tid=TENANT, status="past_due", payment_status="unpaid",
        amount_paid=0.0, total=200.0,
    ))
    res = _run(payments_summary(
        user={"role": "admin", "tenant_id": TENANT},
    ))
    assert res["outstanding_count"] == 2
    assert res["outstanding_total"] == 300.0


# ═══════════════════════════════════════════════════════════════════
# §3 · Backfill CLI — dry-run / apply / idempotency / scoping
# ═══════════════════════════════════════════════════════════════════
def test_backfill_dry_run_writes_nothing():
    """--dry-run reports counts, zero writes, zero sentinel."""
    from migrations.paid_invoice_status_backfill_v1 import run

    _run(_seed_tenant(TENANT))
    inv_id = _run(_seed_invoice(
        tid=TENANT, status="issued", payment_status="paid",
        amount_paid=100.0, total=100.0,
        paid_at="2026-10-01T00:00:00+00:00",
    ))

    res = _run(run(apply=False, tenant_id=TENANT))
    assert res["status"] == "dry-run"
    assert res["stats"]["candidates"] >= 1
    assert res["stats"]["moved"] == 0

    inv = _run(_DB.quotes.find_one({"id": inv_id}, {"_id": 0}))
    assert inv["status"] == "issued"
    assert "previous_status_before_paid" not in inv

    sentinel = _run(_DB["_migrations"].find_one(
        {"key": "paid_invoice_status_backfill_v1"},
    ))
    assert sentinel is None


def test_backfill_apply_flips_status_and_preserves_crumb():
    """--apply flips status to paid, stamps previous_status_before_paid,
    writes sentinel."""
    from migrations.paid_invoice_status_backfill_v1 import run

    _run(_seed_tenant(TENANT))
    inv_issued = _run(_seed_invoice(
        tid=TENANT, status="issued", payment_status="paid",
        amount_paid=100.0, total=100.0,
        paid_at="2026-10-01T00:00:00+00:00",
    ))
    inv_sent = _run(_seed_invoice(
        tid=TENANT, status="sent", payment_status="paid",
        amount_paid=200.0, total=200.0,
        paid_at="2026-10-02T00:00:00+00:00",
    ))

    res = _run(run(apply=True, tenant_id=TENANT, force=True))
    assert res["status"] == "applied"
    assert res["stats"]["moved"] >= 2

    i1 = _run(_DB.quotes.find_one({"id": inv_issued}, {"_id": 0}))
    assert i1["status"] == "paid"
    assert i1["previous_status_before_paid"] == "issued"

    i2 = _run(_DB.quotes.find_one({"id": inv_sent}, {"_id": 0}))
    assert i2["status"] == "paid"
    assert i2["previous_status_before_paid"] == "sent"

    sentinel = _run(_DB["_migrations"].find_one(
        {"key": "paid_invoice_status_backfill_v1"}, {"_id": 0},
    ))
    assert sentinel is not None
    assert sentinel["mode"] == "apply"
    assert sentinel["stats"]["candidates_after"] == 0
    assert sentinel["stats"]["clean"] is True


def test_backfill_apply_is_idempotent_on_rerun():
    """Second apply reports 0 moved."""
    from migrations.paid_invoice_status_backfill_v1 import run

    _run(_seed_tenant(TENANT))
    _run(_seed_invoice(
        tid=TENANT, status="issued", payment_status="paid",
        amount_paid=100.0, total=100.0,
        paid_at="2026-10-01T00:00:00+00:00",
    ))

    r1 = _run(run(apply=True, tenant_id=TENANT, force=True))
    assert r1["stats"]["moved"] >= 1

    r2 = _run(run(apply=True, tenant_id=TENANT, force=True))
    assert r2["stats"]["moved"] == 0


def test_backfill_leaves_partial_payment_rows_alone():
    """payment_status="partial" rows are NEVER touched — scope filter
    requires strict payment_status="paid"."""
    from migrations.paid_invoice_status_backfill_v1 import run

    _run(_seed_tenant(TENANT))
    partial_id = _run(_seed_invoice(
        tid=TENANT, status="issued", payment_status="partial",
        amount_paid=40.0, total=100.0,
    ))

    res = _run(run(apply=True, tenant_id=TENANT, force=True))
    assert res["stats"]["moved"] == 0

    inv = _run(_DB.quotes.find_one({"id": partial_id}, {"_id": 0}))
    assert inv["status"] == "issued"
    assert inv["payment_status"] == "partial"


def test_backfill_leaves_refunded_rows_alone():
    """Refunded invoices preserve whatever status the refund flow
    left — the scope filter excludes 'refunded' and
    'partially_refunded' NON-NEGOTIABLY."""
    from migrations.paid_invoice_status_backfill_v1 import run

    _run(_seed_tenant(TENANT))
    refunded_id = _run(_seed_invoice(
        tid=TENANT, status="refunded", payment_status="paid",
        amount_paid=100.0, total=100.0,
        paid_at="2026-10-01T00:00:00+00:00",
    ))

    res = _run(run(apply=True, tenant_id=TENANT, force=True))
    assert res["stats"]["moved"] == 0

    inv = _run(_DB.quotes.find_one({"id": refunded_id}, {"_id": 0}))
    assert inv["status"] == "refunded"


def test_backfill_tenant_scope_does_not_bleed():
    """--tenant X apply MUST NOT touch tenant Y's rows."""
    from migrations.paid_invoice_status_backfill_v1 import run

    _run(_seed_tenant(TENANT))
    _run(_seed_tenant(TENANT_B))
    inv_a = _run(_seed_invoice(
        tid=TENANT, status="issued", payment_status="paid",
        amount_paid=100.0, total=100.0,
        paid_at="2026-10-01T00:00:00+00:00",
    ))
    inv_b = _run(_seed_invoice(
        tid=TENANT_B, status="issued", payment_status="paid",
        amount_paid=100.0, total=100.0,
        paid_at="2026-10-02T00:00:00+00:00",
    ))

    res = _run(run(apply=True, tenant_id=TENANT, force=True))

    a = _run(_DB.quotes.find_one({"id": inv_a}, {"_id": 0}))
    assert a["status"] == "paid"

    b = _run(_DB.quotes.find_one({"id": inv_b}, {"_id": 0}))
    assert b["status"] == "issued", (
        f"tenant isolation leak — tenant B row flipped: "
        f"status={b['status']!r}"
    )

    assert res["stats"]["candidates"] == 1


def test_backfill_mutually_exclusive_flags():
    """--apply + --report-only MUST raise."""
    from migrations.paid_invoice_status_backfill_v1 import run

    with pytest.raises(ValueError):
        _run(run(apply=True, report_only=True))
