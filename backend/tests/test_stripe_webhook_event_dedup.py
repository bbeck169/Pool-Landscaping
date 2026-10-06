"""Phase B3 · Feb-2026 — Stripe webhook event dedup ledger tests.

Verifies that the ``insert_or_skip`` gate short-circuits duplicate
Stripe deliveries of the same ``event.id`` and that distinct event
ids continue to process normally.

Bypasses the FastAPI/router path — exercises the ledger helper
directly against the live Motor client bound at module import.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values

from services.payments import stripe_webhook_ledger as ledger
from tests._phase34_asyncio import batch_safe_run
from services.payments import stripe_charge as sc


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
PREFIX = f"b3dedup-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def db():
    # STRIPE-TEST-ISOLATION · Feb-2026 — trigger the Phase-41.1d
    # Motor-client rebuild on the session-persistent loop BEFORE
    # handing ``sc.db`` to the test. After the rebuild, ``sc.db``
    # points at the fresh client bound to the persistent loop
    # (see tests/_phase34_asyncio._rebuild_motor_client_on_loop).
    import asyncio as _asyncio
    batch_safe_run(_asyncio.sleep(0))
    return sc.db


@pytest.fixture(autouse=True)
def _clean(db):
    async def _wipe():
        await db.stripe_webhook_events.delete_many(
            {"event_id": {"$regex": f"^evt_{PREFIX}"}},
        )
    batch_safe_run(_wipe())
    yield
    batch_safe_run(_wipe())


def _snapshot_event(evt_id: str, tenant_id: str = "tenA") -> dict:
    return {
        "id": evt_id,
        "object": "event",
        "type": "payment_intent.succeeded",
        "data": {"object": {
            "id": "pi_abc", "amount": 500, "currency": "usd",
            "metadata": {"crm_tenant_id": tenant_id},
        }},
    }


def test_first_insert_returns_received(db):
    evt = _snapshot_event(f"evt_{PREFIX}_1")
    res = batch_safe_run(ledger.insert_or_skip(evt))
    assert res["status"] == "received"
    assert res["event_id"] == f"evt_{PREFIX}_1"
    row = batch_safe_run(
        db.stripe_webhook_events.find_one({"event_id": f"evt_{PREFIX}_1"}, {"_id": 0}),
    )
    assert row is not None
    assert row["status"] == "received"
    assert row["tenant_id_hint"] == "tenA"
    assert row["retry_count"] == 0


def test_duplicate_event_id_returns_skipped_duplicate(db):
    evt = _snapshot_event(f"evt_{PREFIX}_2")
    first = batch_safe_run(ledger.insert_or_skip(evt))
    second = batch_safe_run(ledger.insert_or_skip(evt))
    third = batch_safe_run(ledger.insert_or_skip(evt))
    assert first["status"] == "received"
    assert second["status"] == "skipped_duplicate"
    assert third["status"] == "skipped_duplicate"
    row = batch_safe_run(
        db.stripe_webhook_events.find_one({"event_id": f"evt_{PREFIX}_2"}, {"_id": 0}),
    )
    # Two duplicate attempts should bump the retry counter twice.
    assert row["retry_count"] == 2
    assert row.get("last_duplicate_at")


def test_different_event_ids_both_insert(db):
    a = _snapshot_event(f"evt_{PREFIX}_a")
    b = _snapshot_event(f"evt_{PREFIX}_b")
    ra = batch_safe_run(ledger.insert_or_skip(a))
    rb = batch_safe_run(ledger.insert_or_skip(b))
    assert ra["status"] == "received"
    assert rb["status"] == "received"
    count = batch_safe_run(
        db.stripe_webhook_events.count_documents({"event_id": {"$regex": f"^evt_{PREFIX}_[ab]$"}}),
    )
    assert count == 2


def test_event_with_no_id_returns_no_event_id():
    res = batch_safe_run(
        ledger.insert_or_skip({"type": "payment_intent.succeeded", "data": {"object": {}}}),
    )
    assert res["status"] == "no_event_id"


def test_mark_handled_and_failed_transitions(db):
    evt = _snapshot_event(f"evt_{PREFIX}_flow")
    batch_safe_run(ledger.insert_or_skip(evt))
    batch_safe_run(
        ledger.mark_handled(f"evt_{PREFIX}_flow", result={"handled": True}),
    )
    row = batch_safe_run(
        db.stripe_webhook_events.find_one({"event_id": f"evt_{PREFIX}_flow"}, {"_id": 0}),
    )
    assert row["status"] == "handled"
    assert row.get("first_handled_at")
    batch_safe_run(
        ledger.mark_failed(f"evt_{PREFIX}_flow", error="downstream boom"),
    )
    row2 = batch_safe_run(
        db.stripe_webhook_events.find_one({"event_id": f"evt_{PREFIX}_flow"}, {"_id": 0}),
    )
    assert row2["status"] == "failed"
    assert row2["last_error"] == "downstream boom"


def test_tenant_hint_falls_back_to_customer_metadata(db):
    """When the event object itself has no metadata but the customer
    is expanded inline with metadata, the tenant hint uses the
    customer's metadata."""
    evt = {
        "id": f"evt_{PREFIX}_th",
        "type": "customer.subscription.updated",
        "data": {"object": {
            "id": "sub_x",
            "customer": {"id": "cus_x", "metadata": {"crm_tenant_id": "fallback-ten"}},
        }},
    }
    batch_safe_run(ledger.insert_or_skip(evt))
    row = batch_safe_run(
        db.stripe_webhook_events.find_one({"event_id": f"evt_{PREFIX}_th"}, {"_id": 0}),
    )
    assert row["tenant_id_hint"] == "fallback-ten"
