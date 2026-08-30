"""Phase B3 · Feb-2026 — setup_intent.* webhook handlers.

Verifies the three new handlers flip ``verification_status`` on the
matching ``payment_methods`` row.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values

from services.payments import stripe_charge as sc


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
PREFIX = f"b3si-{uuid.uuid4().hex[:8]}"
TID = f"tenSI-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def db():
    return sc.db


@pytest.fixture(autouse=True)
def _clean(db):
    async def _wipe():
        await db.payment_methods.delete_many({"tenant_id": TID})
    asyncio.get_event_loop().run_until_complete(_wipe())
    yield
    asyncio.get_event_loop().run_until_complete(_wipe())


async def _seed_pm(pm_id: str, status: str = "pending") -> None:
    await sc.db.payment_methods.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": TID,
        "customer_id": "cust-x",
        "provider": "stripe",
        "provider_payment_method_id": pm_id,
        "us_bank_account": {"bank_name": "Test Bank", "last4": "1234"},
        "verification_status": status,
        "stripe_mode": "test",
    })


def _si_event(evt_type: str, pm_id: str, last_error: str | None = None) -> dict:
    obj = {"id": "si_" + pm_id, "payment_method": pm_id}
    if last_error:
        obj["last_setup_error"] = {"message": last_error, "code": "verification_failed"}
    return {"id": f"evt_{uuid.uuid4().hex}", "type": evt_type,
            "data": {"object": obj}}


def test_setup_intent_succeeded_flips_to_verified(db):
    pm_id = f"pm_{PREFIX}_ok"
    asyncio.get_event_loop().run_until_complete(_seed_pm(pm_id, "pending"))
    evt = _si_event("setup_intent.succeeded", pm_id)
    res = asyncio.get_event_loop().run_until_complete(sc.handle_webhook_event(evt))
    assert res["handled"] is True
    assert res["new_status"] == "verified"
    row = asyncio.get_event_loop().run_until_complete(
        db.payment_methods.find_one({"provider_payment_method_id": pm_id}, {"_id": 0}),
    )
    assert row["verification_status"] == "verified"
    assert row.get("verified_at")


def test_setup_intent_setup_failed_flips_to_failed_and_stores_reason(db):
    pm_id = f"pm_{PREFIX}_fail"
    asyncio.get_event_loop().run_until_complete(_seed_pm(pm_id, "pending"))
    evt = _si_event("setup_intent.setup_failed", pm_id,
                     last_error="micro-deposit amounts incorrect")
    res = asyncio.get_event_loop().run_until_complete(sc.handle_webhook_event(evt))
    assert res["handled"] is True
    assert res["new_status"] == "failed"
    row = asyncio.get_event_loop().run_until_complete(
        db.payment_methods.find_one({"provider_payment_method_id": pm_id}, {"_id": 0}),
    )
    assert row["verification_status"] == "failed"
    assert row["verification_error"] == "micro-deposit amounts incorrect"


def test_setup_intent_requires_action_flips_to_pending(db):
    pm_id = f"pm_{PREFIX}_req"
    # Seed as "unverified" — verifies transition to pending works even
    # from unverified (not just idle-pending).
    asyncio.get_event_loop().run_until_complete(_seed_pm(pm_id, "unverified"))
    evt = _si_event("setup_intent.requires_action", pm_id)
    res = asyncio.get_event_loop().run_until_complete(sc.handle_webhook_event(evt))
    assert res["handled"] is True
    assert res["new_status"] == "pending"
    row = asyncio.get_event_loop().run_until_complete(
        db.payment_methods.find_one({"provider_payment_method_id": pm_id}, {"_id": 0}),
    )
    assert row["verification_status"] == "pending"


def test_setup_intent_without_payment_method_is_noop(db):
    evt = {"id": "evt_none", "type": "setup_intent.succeeded",
            "data": {"object": {"id": "si_none"}}}
    res = asyncio.get_event_loop().run_until_complete(sc.handle_webhook_event(evt))
    assert res["handled"] is False  # no PM to flip → not handled

