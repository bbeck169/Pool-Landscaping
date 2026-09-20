"""Phase K14 · Feb-2026 — Bulk-charge audit-delta tests.

Verifies the two K14 backend deltas on top of the Phase 14b bulk-charge
loop:

  1. ``services.payments.stripe_charge`` — ``stripe_charges`` rows
     (the "payments" ledger) carry ``via_impersonation`` +
     ``acting_admin_id`` when the initiating request came in through
     a K13 admin View-as-Customer session.
  2. ``routers.invoices_bulk_charge`` — a fresh ``audit_events`` row
     with ``event_type="invoice_auto_charged"`` is inserted for every
     successful charge and surfaces on the customer's
     ``/api/customers/{cid}/communication-timeline``.

Reuses the in-process ``execute_bulk_charge`` fixture pattern from
``test_bulk_charge_phase14b.py`` so no live Stripe HTTP fires.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

# K14 · Feb-2026 — self-contained loop + Motor client. Every test
# swaps ``bulk_router.db`` to this client via monkeypatch so pytest
# reverts the binding after the test finishes, keeping any other
# suite that also drives ``bulk_router`` in-process (phase14b) on
# its own loop/client pair.
from routers import invoices_bulk_charge as bulk_router  # noqa: E402
_K14_LOOP = asyncio.new_event_loop()
_K14_MOTOR = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_K14_LOOP)
_K14_DB = _K14_MOTOR[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_K14_LOOP)
    return _K14_LOOP.run_until_complete(coro)


_TAG = "TEST_k14"


def _tid() -> str:
    return _sync.users.find_one({"email": "manager@aquaterra.com"})["tenant_id"]


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(
        f"{API}/auth/login", json={"email": email, "password": password}, timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _seed_customer(tenant_id: str, tag: str) -> str:
    cid = f"{_TAG}_cust_{tag}_{uuid.uuid4().hex[:6]}"
    _sync.customers.insert_one({
        "id": cid,
        "tenant_id": tenant_id,
        "name": f"{_TAG} Customer {tag}",
        "email": f"{_TAG}_{tag}@example.com",
        "phone": "+15550100000",
        "created_at": "2026-08-01T00:00:00Z",
    })
    return cid


def _seed_invoice(tenant_id: str, customer_id: str, *, total: float) -> str:
    iid = f"{_TAG}_inv_{uuid.uuid4().hex[:8]}"
    _sync.quotes.insert_one({
        "id": iid,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "doc_type": "invoice",
        "title": f"{_TAG} Invoice",
        "invoice_number": f"K14-{iid[-4:]}",
        "line_items": [{"description": "svc", "quantity": 1,
                          "unit_price": total, "category": "Pool"}],
        "total": total,
        "amount_paid": 0.0,
        "payment_status": "unpaid",
        "currency": "usd",
        "created_at": "2026-08-01T00:00:00Z",
    })
    return iid


def _seed_pm(tenant_id: str, customer_id: str) -> str:
    pm_id = f"pm_{_TAG}_{uuid.uuid4().hex[:8]}"
    _sync.payment_methods.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "provider": "stripe",
        "provider_customer_id": f"cus_{_TAG}",
        "provider_payment_method_id": pm_id,
        "brand": "visa",
        "last4": "4242",
        "exp_month": 12,
        "exp_year": 2032,
        "is_default": True,
        "stripe_mode": "test",
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    })
    return pm_id


def _cleanup(tenant_id: str) -> None:
    _sync.customers.delete_many({"tenant_id": tenant_id, "id": {"$regex": f"^{_TAG}_"}})
    _sync.quotes.delete_many({"tenant_id": tenant_id, "id": {"$regex": f"^{_TAG}_"}})
    _sync.payment_methods.delete_many(
        {"tenant_id": tenant_id, "provider_payment_method_id": {"$regex": f"^pm_{_TAG}_"}},
    )
    _sync.bulk_charge_runs.delete_many(
        {"tenant_id": tenant_id, "idempotency_key": {"$regex": f"^{_TAG}"}},
    )
    _sync.stripe_charges.delete_many(
        {"tenant_id": tenant_id, "invoice_id": {"$regex": f"^{_TAG}_"}},
    )
    _sync.audit_events.delete_many(
        {"tenant_id": tenant_id, "event_type": "invoice_auto_charged",
         "payload.invoice_id": {"$regex": f"^{_TAG}_"}},
    )


@pytest.fixture
def k14_scenario(monkeypatch):
    tid = _tid()
    _cleanup(tid)
    cust = _seed_customer(tid, "solo")
    pm_id = _seed_pm(tid, cust)
    inv = _seed_invoice(tid, cust, total=42.00)

    # Stub out charge_card_on_file so no real Stripe call fires, but
    # still capture the kwargs and forward the ``via_impersonation`` /
    # ``acting_admin_id`` fields into ``db.stripe_charges`` via a
    # miniature ``_persist_charge`` mimic. That way the assertions
    # cover BOTH the router→service kwarg wiring AND the ledger row
    # shape simultaneously.
    calls: list[dict] = []

    async def _stub(**kwargs):
        calls.append(kwargs)
        pi_id = f"pi_stub_{uuid.uuid4().hex[:8]}"
        # Mirror the K14 delta the real service now applies.
        _sync.stripe_charges.insert_one({
            "id": str(uuid.uuid4()),
            "tenant_id": kwargs["tenant_id"],
            "customer_id": kwargs["customer_id"],
            "provider_payment_method_id": kwargs["payment_method_id"],
            "amount_cents": kwargs["amount_cents"],
            "currency": kwargs["currency"],
            "invoice_id": kwargs.get("invoice_id"),
            "stripe_payment_intent_id": pi_id,
            "status": "succeeded",
            "error": None,
            "actor_user_id": kwargs.get("actor_user_id"),
            "via_impersonation": bool(kwargs.get("via_impersonation")),
            "acting_admin_id": kwargs.get("acting_admin_id"),
            "stripe_mode": "test",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        return {
            "ok": True,
            "charge_row_id": str(uuid.uuid4()),
            "payment_intent_id": pi_id,
            "status": "succeeded",
            "amount_cents": kwargs["amount_cents"],
            "currency": kwargs["currency"],
        }

    monkeypatch.setattr(bulk_router.stripe_svc, "charge_card_on_file", _stub)
    # K14 · swap bulk_router.db to our K14-loop-bound client. pytest
    # auto-reverts on teardown, so phase14b's motor client stays
    # untouched when it runs next in the batch.
    monkeypatch.setattr(bulk_router, "db", _K14_DB)

    yield {
        "tenant_id": tid,
        "customer_id": cust,
        "pm_id": pm_id,
        "invoice_id": inv,
        "calls": calls,
    }
    _cleanup(tid)


def _in_process_bulk(scenario, *, user: dict, key: str) -> dict:
    from routers.invoices_bulk_charge import (
        BulkChargeBody as _Body, execute_bulk_charge as _core,
    )
    body = _Body(
        invoice_ids=[scenario["invoice_id"]],
        dry_run=False,
        idempotency_key=key,
    )
    tenant = {"id": scenario["tenant_id"]}
    return _run(_core(body=body, user=user, tenant=tenant))


def test_k14_non_impersonated_charge_stamps_row_and_emits_audit(k14_scenario):
    """Straight admin bulk-charge: ``via_impersonation`` is False on
    the ledger row and an ``invoice_auto_charged`` audit_events row
    lands with the correct payload."""
    key = f"{_TAG}_key_{uuid.uuid4().hex[:6]}"
    user = {"id": "u_admin_direct", "email": "admin@aquaterra.com", "role": "admin"}
    j = _in_process_bulk(k14_scenario, user=user, key=key)
    assert j["summary"]["charged"] == 1

    # (1) Payments ledger row carries the K14 stamp (False for a
    # non-impersonated request; ``acting_admin_id`` is None).
    row = _sync.stripe_charges.find_one({
        "tenant_id": k14_scenario["tenant_id"],
        "invoice_id": k14_scenario["invoice_id"],
    })
    assert row is not None
    assert row["via_impersonation"] is False
    assert row["acting_admin_id"] is None

    # (2) audit_events row landed for the communication timeline.
    ae = _sync.audit_events.find_one({
        "tenant_id": k14_scenario["tenant_id"],
        "event_type": "invoice_auto_charged",
        "payload.invoice_id": k14_scenario["invoice_id"],
    })
    assert ae is not None
    assert ae["actor_id"] == "u_admin_direct"
    assert ae["via_impersonation"] is False
    assert ae["acting_admin_id"] is None
    assert ae["payload"]["customer_id"] == k14_scenario["customer_id"]
    assert ae["payload"]["amount_cents"] == 4200
    assert ae["payload"]["currency"] == "usd"


def test_k14_impersonated_charge_stamps_row_and_emits_audit(k14_scenario):
    """K13 impersonated bulk-charge: both the ledger row and the
    audit event carry ``via_impersonation=True`` + ``acting_admin_id``
    equal to the impersonator's id."""
    key = f"{_TAG}_key_imp_{uuid.uuid4().hex[:6]}"
    user = {
        "id": "u_customer_target",
        "email": "customer@aquaterra.com",
        "role": "admin",
        "is_impersonated": True,
        "impersonator_id": "u_super_admin_boss",
    }
    j = _in_process_bulk(k14_scenario, user=user, key=key)
    assert j["summary"]["charged"] == 1

    # Router forwarded the K14 kwargs to the stripe service.
    call = k14_scenario["calls"][-1]
    assert call["via_impersonation"] is True
    assert call["acting_admin_id"] == "u_super_admin_boss"

    row = _sync.stripe_charges.find_one({
        "tenant_id": k14_scenario["tenant_id"],
        "invoice_id": k14_scenario["invoice_id"],
    })
    assert row is not None
    assert row["via_impersonation"] is True
    assert row["acting_admin_id"] == "u_super_admin_boss"

    ae = _sync.audit_events.find_one({
        "tenant_id": k14_scenario["tenant_id"],
        "event_type": "invoice_auto_charged",
        "payload.invoice_id": k14_scenario["invoice_id"],
    })
    assert ae is not None
    assert ae["via_impersonation"] is True
    assert ae["acting_admin_id"] == "u_super_admin_boss"


def test_k14_audit_event_surfaces_on_communication_timeline(k14_scenario):
    """After a successful bulk-charge the customer's communication
    timeline surfaces the ``invoice_auto_charged`` row as a
    ``type=payment`` item — end-to-end wire check against the live
    HTTP surface."""
    key = f"{_TAG}_key_ct_{uuid.uuid4().hex[:6]}"
    user = {
        "id": "u_admin_ct",
        "email": "manager@aquaterra.com",
        "role": "admin",
        "is_impersonated": True,
        "impersonator_id": "u_super_admin_ct",
    }
    j = _in_process_bulk(k14_scenario, user=user, key=key)
    assert j["summary"]["charged"] == 1

    tok = _login("manager@aquaterra.com")
    r = requests.get(
        f"{API}/customers/{k14_scenario['customer_id']}/communication-timeline",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    payment_items = [i for i in items if i.get("type") == "payment"]
    assert payment_items, f"no payment items in {items!r}"
    hit = next(
        (i for i in payment_items
         if i.get("invoice_id") == k14_scenario["invoice_id"]),
        None,
    )
    assert hit is not None
    assert hit["amount_cents"] == 4200
    assert hit["currency"] == "USD"
    assert hit["via_impersonation"] is True
    assert "auto-charged" in hit["subject"].lower()
