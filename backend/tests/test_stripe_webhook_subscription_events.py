"""Phase B3 · Feb-2026 — customer.subscription.* webhook handlers.

Verifies:
  * ``customer.subscription.created`` upserts into
    ``stripe_subscriptions`` with the canonical shape.
  * ``customer.subscription.updated`` refreshes status +
    period fields.
  * ``customer.subscription.deleted`` marks the mirror row canceled
    with a stamped ``canceled_at``.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from dotenv import dotenv_values

from services.payments import stripe_charge as sc


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
TID = f"tenSUB-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def db():
    return sc.db


@pytest.fixture(autouse=True)
def _clean(db):
    async def _wipe():
        await db.stripe_subscriptions.delete_many({"tenant_id": TID})
        await db.customers.delete_many({"tenant_id": TID})
    asyncio.get_event_loop().run_until_complete(_wipe())
    yield
    asyncio.get_event_loop().run_until_complete(_wipe())


async def _seed_customer(stripe_customer_id: str) -> str:
    cust_id = f"crm-cust-{uuid.uuid4().hex[:8]}"
    await sc.db.customers.insert_one({
        "id": cust_id, "tenant_id": TID,
        "stripe_customer_id": stripe_customer_id, "name": "Sub Test",
    })
    return cust_id


def _sub_event(
    evt_type: str, sub_id: str, stripe_customer_id: str,
    status: str = "active",
    tenant_hint_in_metadata: bool = True,
    cancel_at_period_end: bool = False,
) -> dict:
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    meta = {"crm_tenant_id": TID} if tenant_hint_in_metadata else {}
    return {"id": f"evt_{uuid.uuid4().hex}", "type": evt_type,
            "data": {"object": {
                "id": sub_id,
                "customer": stripe_customer_id,
                "status": status,
                "current_period_start": now_epoch,
                "current_period_end": now_epoch + 30 * 86400,
                "cancel_at_period_end": cancel_at_period_end,
                "canceled_at": None,
                "created": now_epoch,
                "metadata": meta,
            }}}


def test_subscription_created_upserts_mirror_row(db):
    stripe_cust = f"cus_{uuid.uuid4().hex[:14]}"
    crm_cust_id = asyncio.get_event_loop().run_until_complete(_seed_customer(stripe_cust))
    sub_id = f"sub_{uuid.uuid4().hex[:14]}"
    evt = _sub_event("customer.subscription.created", sub_id, stripe_cust)
    res = asyncio.get_event_loop().run_until_complete(sc.handle_webhook_event(evt))
    assert res["handled"] is True
    assert res["stripe_subscription_id"] == sub_id
    row = asyncio.get_event_loop().run_until_complete(
        db.stripe_subscriptions.find_one({"stripe_subscription_id": sub_id}, {"_id": 0}),
    )
    assert row is not None
    assert row["tenant_id"] == TID
    assert row["customer_id"] == crm_cust_id
    assert row["stripe_customer_id"] == stripe_cust
    assert row["status"] == "active"
    assert row["current_period_start"]
    assert row["current_period_end"]
    assert row["webhook_source"] == "customer.subscription.created"


def test_subscription_updated_refreshes_status_and_period(db):
    stripe_cust = f"cus_{uuid.uuid4().hex[:14]}"
    asyncio.get_event_loop().run_until_complete(_seed_customer(stripe_cust))
    sub_id = f"sub_{uuid.uuid4().hex[:14]}"
    # 1. First a `created` to seed the row.
    asyncio.get_event_loop().run_until_complete(
        sc.handle_webhook_event(_sub_event("customer.subscription.created", sub_id, stripe_cust)),
    )
    # 2. Now an `updated` flips status to past_due + cancel_at_period_end.
    upd = _sub_event("customer.subscription.updated", sub_id, stripe_cust,
                       status="past_due", cancel_at_period_end=True)
    res = asyncio.get_event_loop().run_until_complete(sc.handle_webhook_event(upd))
    assert res["handled"] is True
    row = asyncio.get_event_loop().run_until_complete(
        db.stripe_subscriptions.find_one({"stripe_subscription_id": sub_id}, {"_id": 0}),
    )
    assert row["status"] == "past_due"
    assert row["cancel_at_period_end"] is True
    assert row["webhook_source"] == "customer.subscription.updated"


def test_subscription_deleted_marks_row_canceled(db):
    stripe_cust = f"cus_{uuid.uuid4().hex[:14]}"
    asyncio.get_event_loop().run_until_complete(_seed_customer(stripe_cust))
    sub_id = f"sub_{uuid.uuid4().hex[:14]}"
    asyncio.get_event_loop().run_until_complete(
        sc.handle_webhook_event(_sub_event("customer.subscription.created", sub_id, stripe_cust)),
    )
    evt = _sub_event("customer.subscription.deleted", sub_id, stripe_cust,
                       status="canceled")
    res = asyncio.get_event_loop().run_until_complete(sc.handle_webhook_event(evt))
    assert res["handled"] is True
    row = asyncio.get_event_loop().run_until_complete(
        db.stripe_subscriptions.find_one({"stripe_subscription_id": sub_id}, {"_id": 0}),
    )
    assert row["status"] == "canceled"
    assert row.get("canceled_at")


def test_subscription_created_falls_back_to_customer_metadata_for_tenant(db):
    """When the sub metadata is missing but the customer object is
    inline-expanded with metadata, the handler should still resolve
    the tenant."""
    stripe_cust = f"cus_{uuid.uuid4().hex[:14]}"
    asyncio.get_event_loop().run_until_complete(_seed_customer(stripe_cust))
    sub_id = f"sub_{uuid.uuid4().hex[:14]}"
    evt = {
        "id": f"evt_{uuid.uuid4().hex}",
        "type": "customer.subscription.created",
        "data": {"object": {
            "id": sub_id,
            "customer": {"id": stripe_cust, "metadata": {"crm_tenant_id": TID}},
            "status": "active",
            "current_period_start": 1700000000,
            "current_period_end": 1702592000,
            "cancel_at_period_end": False,
            "canceled_at": None,
            "created": 1700000000,
            "metadata": {},  # empty on the sub itself
        }},
    }
    res = asyncio.get_event_loop().run_until_complete(sc.handle_webhook_event(evt))
    assert res["handled"] is True
    row = asyncio.get_event_loop().run_until_complete(
        db.stripe_subscriptions.find_one({"stripe_subscription_id": sub_id}, {"_id": 0}),
    )
    assert row["tenant_id"] == TID
