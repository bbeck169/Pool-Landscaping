"""Phase 15 · Feb-2026 — Backfill Lumino paid_at tests.

Seeds synthetic ``payment_events`` + ``quotes`` rows, runs the migration
in-process against a per-loop DB, asserts each behaviour, cleans up.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_FRESH = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_ASYNC_DB = _FRESH[_ENV["DB_NAME"]]

from scripts.backfill_lumino_paid_at import backfill  # noqa: E402

_TAG = "TEST_p15"


def _run(coro):
    try:
        asyncio.set_event_loop(_LOOP)
    except Exception:
        pass
    return _LOOP.run_until_complete(coro)


def _cleanup() -> None:
    _sync.payment_events.delete_many({"id": {"$regex": f"^{_TAG}"}})
    _sync.quotes.delete_many({"id": {"$regex": f"^{_TAG}"}})
    _sync.invoice_reconciliation_log.delete_many({"invoice_id": {"$regex": f"^{_TAG}"}})


def _seed_invoice(iid: str, *, total: float = 100.0,
                   payment_status: str = "unpaid",
                   paid_at: str | None = None,
                   amount_paid: float = 0.0) -> None:
    _sync.quotes.insert_one({
        "id": iid,
        "tenant_id": f"{_TAG}_tenant",
        "customer_id": f"{_TAG}_cust",
        "doc_type": "invoice",
        "title": f"{_TAG} inv",
        "line_items": [{"description": "x", "quantity": 1, "unit_price": total}],
        "total": total,
        "amount_paid": amount_paid,
        "payment_status": payment_status,
        "paid_at": paid_at,
        "created_at": "2026-01-01T00:00:00Z",
    })


def _seed_event(*, invoice_id: str | None, occurred_at: str,
                 event_type: str = "payment.created",
                 inner_status: str = "succeeded",
                 evt_id: str | None = None) -> str:
    eid = evt_id or f"{_TAG}_evt_{uuid.uuid4().hex[:8]}"
    _sync.payment_events.insert_one({
        "id": eid,
        "event_type": event_type,
        "invoice_id": invoice_id,
        "occurred_at": occurred_at,
        "received_at": occurred_at,
        "source": "zapier",
        "raw": {"data": {"status": inner_status}},
    })
    return eid


@pytest.fixture(autouse=True)
def _cleanup_around_each():
    _cleanup()
    yield
    _cleanup()


# ═════════════════════════════════════════════════════════════════════
# Tests
# ═════════════════════════════════════════════════════════════════════
def test_backfill_picks_earliest_event_on_duplicates():
    inv = f"{_TAG}_inv_dup"
    _seed_invoice(inv, total=200.0)
    later = "2026-05-01T12:00:00+00:00"
    earlier = "2026-04-01T09:30:00+00:00"
    latest = "2026-06-15T18:15:00+00:00"
    _seed_event(invoice_id=inv, occurred_at=later, evt_id=f"{_TAG}_e2")
    _seed_event(invoice_id=inv, occurred_at=earlier, evt_id=f"{_TAG}_e1")
    _seed_event(invoice_id=inv, occurred_at=latest, evt_id=f"{_TAG}_e3")

    summary = _run(backfill(db=_ASYNC_DB, dry_run=False))
    assert summary["backfilled"] == 1
    assert summary["scanned"] == 1  # 3 events → 1 invoice
    assert summary["already_paid"] == 0
    updated = _sync.quotes.find_one({"id": inv})
    assert updated["payment_status"] == "paid"
    assert updated["paid_at"] == earlier
    assert updated["amount_paid"] == 200.0

    # Log entry references the earliest event id.
    log = _sync.invoice_reconciliation_log.find_one({"invoice_id": inv})
    assert log is not None
    assert log["action"] == "backfill_lumino_paid_at"
    assert log["source_event_id"] == f"{_TAG}_e1"
    assert log["applied_paid_at"] == earlier


def test_backfill_skips_already_paid_invoices():
    inv = f"{_TAG}_inv_paid"
    _seed_invoice(inv, total=50.0, payment_status="paid",
                    paid_at="2026-01-15T00:00:00+00:00",
                    amount_paid=50.0)
    _seed_event(invoice_id=inv, occurred_at="2026-05-01T00:00:00+00:00")

    summary = _run(backfill(db=_ASYNC_DB, dry_run=False))
    assert summary["already_paid"] == 1
    assert summary["backfilled"] == 0
    # DB row untouched.
    row = _sync.quotes.find_one({"id": inv})
    assert row["paid_at"] == "2026-01-15T00:00:00+00:00"
    assert row.get("backfilled_from_lumino_event_at") is None
    # No log entry.
    assert _sync.invoice_reconciliation_log.count_documents(
        {"invoice_id": inv}
    ) == 0


def test_backfill_skips_missing_invoices():
    missing = f"{_TAG}_inv_missing"
    _seed_event(invoice_id=missing, occurred_at="2026-05-01T00:00:00+00:00")
    summary = _run(backfill(db=_ASYNC_DB, dry_run=False))
    assert summary["invoice_not_found"] == 1
    assert summary["backfilled"] == 0
    assert _sync.invoice_reconciliation_log.count_documents(
        {"invoice_id": missing}
    ) == 0


def test_backfill_is_idempotent():
    inv = f"{_TAG}_inv_idem"
    _seed_invoice(inv, total=75.0)
    _seed_event(invoice_id=inv, occurred_at="2026-05-01T00:00:00+00:00",
                 evt_id=f"{_TAG}_idem_evt")

    first = _run(backfill(db=_ASYNC_DB, dry_run=False))
    assert first["backfilled"] == 1
    second = _run(backfill(db=_ASYNC_DB, dry_run=False))
    assert second["backfilled"] == 0
    assert second["already_paid"] == 1
    # Exactly one log entry — the second run must not duplicate.
    assert _sync.invoice_reconciliation_log.count_documents(
        {"invoice_id": inv, "action": "backfill_lumino_paid_at"}
    ) == 1


def test_backfill_dry_run_writes_nothing():
    inv = f"{_TAG}_inv_dry"
    _seed_invoice(inv, total=42.0)
    _seed_event(invoice_id=inv, occurred_at="2026-05-01T00:00:00+00:00")

    summary = _run(backfill(db=_ASYNC_DB, dry_run=True))
    assert summary["dry_run"] is True
    assert summary["backfilled"] == 1  # counted, but not applied.
    row = _sync.quotes.find_one({"id": inv})
    assert row.get("payment_status") == "unpaid"
    assert row.get("paid_at") is None
    assert _sync.invoice_reconciliation_log.count_documents(
        {"invoice_id": inv}
    ) == 0


def test_backfill_ignores_non_success_event_types():
    inv = f"{_TAG}_inv_link"
    _seed_invoice(inv, total=10.0)
    _seed_event(invoice_id=inv,
                 occurred_at="2026-05-01T00:00:00+00:00",
                 event_type="invoice.link_created")
    summary = _run(backfill(db=_ASYNC_DB, dry_run=False))
    assert summary["backfilled"] == 0
    assert summary["scanned"] == 0  # not a success event


def test_backfill_ignores_null_invoice_id_events():
    # Matches the current smoke-test seed condition (5 events all with
    # invoice_id=None) — investigation gate case.
    _seed_event(invoice_id=None, occurred_at="2026-05-01T00:00:00+00:00")
    _seed_event(invoice_id=None, occurred_at="2026-05-02T00:00:00+00:00")
    summary = _run(backfill(db=_ASYNC_DB, dry_run=False))
    assert summary["backfilled"] == 0
    assert summary["scanned"] == 0


def test_backfill_respects_inner_status_when_not_succeeded():
    inv = f"{_TAG}_inv_pending"
    _seed_invoice(inv, total=88.0)
    _seed_event(invoice_id=inv,
                 occurred_at="2026-05-01T00:00:00+00:00",
                 inner_status="pending")
    summary = _run(backfill(db=_ASYNC_DB, dry_run=False))
    assert summary["backfilled"] == 0


def test_backfill_leaves_amount_paid_if_already_partial():
    inv = f"{_TAG}_inv_partial"
    _seed_invoice(inv, total=100.0, amount_paid=25.0,
                    payment_status="unpaid")
    _seed_event(invoice_id=inv, occurred_at="2026-05-01T00:00:00+00:00")
    summary = _run(backfill(db=_ASYNC_DB, dry_run=False))
    assert summary["backfilled"] == 1
    row = _sync.quotes.find_one({"id": inv})
    assert row["payment_status"] == "paid"
    # amount_paid remains at 25 — script only stamps when currently 0.
    assert row["amount_paid"] == 25.0


def test_grep_lint_no_writes_to_db_invoices():
    """Phase 11 invariant — the backfill script must not touch
    ``db.invoices``. Writes must all go through ``db.quotes``."""
    import re
    src = Path(__file__).resolve().parents[1] / "scripts" / "backfill_lumino_paid_at.py"
    text = src.read_text(encoding="utf-8")
    assert not re.search(r"db\.invoices\.(insert|update|delete|find_one_and_)",
                          text)
