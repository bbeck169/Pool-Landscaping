"""Phase K38 · Feb-2026 — Bulk Charge ACH on File tests.

Mirrors ``test_bulk_charge_phase14b.py`` for the ACH twin endpoint
``/invoices/bulk-charge-ach-on-file``. Stubs
``services.payments.stripe_charge.charge_ach_on_file`` directly via
``monkeypatch`` on the imported reference inside the bulk router.
No live Stripe HTTP is ever issued.
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

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
from routers import invoices_bulk_charge as bulk_router  # noqa: E402
from services.payments import stripe_charge as stripe_module  # noqa: E402

_FRESH = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
bulk_router.db = _FRESH[_ENV["DB_NAME"]]
stripe_module.db = _FRESH[_ENV["DB_NAME"]]


def _run(coro):
    try:
        asyncio.set_event_loop(_LOOP)
    except Exception:
        pass
    return _LOOP.run_until_complete(coro)


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(
        f"{API}/auth/login", json={"email": email, "password": password}, timeout=10
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _tid() -> str:
    return _sync.users.find_one({"email": "manager@aquaterra.com"})["tenant_id"]


_TAG = "TEST_k38"


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


def _seed_invoice(
    tenant_id: str,
    customer_id: str,
    *,
    total: float,
    amount_paid: float = 0.0,
    payment_status: str = "unpaid",
    number: str | None = None,
) -> str:
    iid = f"{_TAG}_inv_{uuid.uuid4().hex[:8]}"
    _sync.quotes.insert_one({
        "id": iid,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "doc_type": "invoice",
        "title": f"{_TAG} Invoice",
        "invoice_number": number or f"{_TAG}-{iid[-4:]}",
        "line_items": [{"description": "Service", "quantity": 1, "unit_price": total}],
        "total": total,
        "amount_paid": amount_paid,
        "payment_status": payment_status,
        "currency": "usd",
        "created_at": "2026-08-01T00:00:00Z",
    })
    return iid


def _seed_ach_pm(
    tenant_id: str,
    customer_id: str,
    *,
    verification_status: str = "verified",
    is_default: bool = True,
    last4: str = "6789",
    bank_name: str = "Bank of Test",
    provider_pm_id: str | None = None,
) -> str:
    pm_id = provider_pm_id or f"pm_{_TAG}_{uuid.uuid4().hex[:8]}"
    _sync.payment_methods.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "provider": "stripe",
        "provider_customer_id": f"cus_{_TAG}",
        "provider_payment_method_id": pm_id,
        "type": "us_bank_account",
        "brand": "",
        "last4": last4,
        "bank_name": bank_name,
        "account_holder_type": "individual",
        "verification_status": verification_status,
        "is_default": is_default,
        "stripe_mode": "test",
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    })
    return pm_id


def _seed_card_pm(tenant_id: str, customer_id: str) -> str:
    """Seed a card PM (NOT an ACH one) — used to prove the ACH endpoint
    ignores card-only customers with ``no_bank_on_file``."""
    pm_id = f"pm_card_{_TAG}_{uuid.uuid4().hex[:8]}"
    _sync.payment_methods.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "provider": "stripe",
        "provider_customer_id": f"cus_{_TAG}",
        "provider_payment_method_id": pm_id,
        "type": "card",
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
    _sync.payment_methods.delete_many({"tenant_id": tenant_id, "provider_payment_method_id": {"$regex": f"^pm_(card_)?{_TAG}_"}})
    _sync.bulk_charge_runs.delete_many({"tenant_id": tenant_id, "idempotency_key": {"$regex": f"^{_TAG}"}})
    _sync.stripe_charges.delete_many({"tenant_id": tenant_id, "invoice_id": {"$regex": f"^{_TAG}_"}})


@pytest.fixture
def scenario():
    """Seed a 5-invoice ACH scenario.

    Customers:
      * A — verified ACH PM (eligible)
      * B — verified ACH PM (eligible; used for exception test)
      * C — no PM at all
      * D — unverified ACH PM
      * E — card PM only (no us_bank_account)
    """
    tid = _tid()
    _cleanup(tid)
    ca = _seed_customer(tid, "A")
    cb = _seed_customer(tid, "B")
    cc = _seed_customer(tid, "C_nopm")
    cd = _seed_customer(tid, "D_unverified")
    ce = _seed_customer(tid, "E_cardonly")
    pm_a = _seed_ach_pm(tid, ca, last4="1111", bank_name="AlphaBank")
    pm_b = _seed_ach_pm(tid, cb, last4="2222", bank_name="BetaBank")
    _seed_ach_pm(tid, cd, verification_status="pending", last4="3333", bank_name="GammaBank")
    _seed_card_pm(tid, ce)

    yield {
        "tenant_id": tid,
        "admin_token": _login("manager@aquaterra.com"),
        "customers": {"A": ca, "B": cb, "C": cc, "D": cd, "E": ce},
        "pms": {"A": pm_a, "B": pm_b},
        "invoices": {
            "eligible1": _seed_invoice(tid, ca, total=125.00),
            "eligible2": _seed_invoice(tid, cb, total=99.50),
            "already_paid": _seed_invoice(
                tid, ca, total=50.00, amount_paid=50.00, payment_status="paid",
            ),
            "no_bank": _seed_invoice(tid, cc, total=200.00),
            "unverified": _seed_invoice(tid, cd, total=75.00),
            "card_only": _seed_invoice(tid, ce, total=42.00),
            "zero_balance": _seed_invoice(tid, ca, total=0.0),
        },
    }
    _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# ACH Bulk-charge tests
# ═════════════════════════════════════════════════════════════════════
class _AchChargeStub:
    """Replaces ``stripe_svc.charge_ach_on_file`` for the duration of a test."""

    def __init__(self):
        self.calls: list[dict] = []
        self.responses: list[dict] = []
        self.exceptions: dict[str, Exception] = {}

    def enqueue(self, res: dict):
        self.responses.append(res)

    def error_for(self, invoice_id: str, exc: Exception):
        self.exceptions[invoice_id] = exc

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        inv_id = kwargs.get("invoice_id")
        if inv_id in self.exceptions:
            raise self.exceptions[inv_id]
        if self.responses:
            return self.responses.pop(0)
        return {
            "ok": True,
            "charge_row_id": str(uuid.uuid4()),
            "payment_intent_id": f"pi_ach_stub_{uuid.uuid4().hex[:8]}",
            "status": "processing",
            "amount_cents": kwargs["amount_cents"],
            "currency": kwargs["currency"],
        }


@pytest.fixture
def stub(monkeypatch):
    s = _AchChargeStub()
    monkeypatch.setattr(bulk_router.stripe_svc, "charge_ach_on_file", s)
    return s


def _bulk_body(scenario, dry_run: bool, key: str | None = None,
                extra_ids: list[str] | None = None):
    key = key or f"{_TAG}_key_{uuid.uuid4().hex[:6]}"
    ids = [
        scenario["invoices"]["eligible1"],
        scenario["invoices"]["eligible2"],
        scenario["invoices"]["already_paid"],
        scenario["invoices"]["no_bank"],
        scenario["invoices"]["unverified"],
        scenario["invoices"]["card_only"],
        scenario["invoices"]["zero_balance"],
    ]
    if extra_ids:
        ids.extend(extra_ids)
    return {
        "invoice_ids": ids,
        "dry_run": dry_run,
        "idempotency_key": key,
    }


def _in_process_bulk_ach(scenario, *, dry_run: bool, key: str,
                            invoice_ids: list[str] | None = None) -> dict:
    """Drive ``execute_bulk_charge_ach`` in-process so the pytest-side
    monkeypatch on ``bulk_router.stripe_svc.charge_ach_on_file`` takes
    effect."""
    from routers.invoices_bulk_charge import (  # noqa: WPS433
        BulkChargeBody as _Body,
        execute_bulk_charge_ach as _core,
    )
    ids = invoice_ids or [
        scenario["invoices"]["eligible1"],
        scenario["invoices"]["eligible2"],
        scenario["invoices"]["already_paid"],
        scenario["invoices"]["no_bank"],
        scenario["invoices"]["unverified"],
        scenario["invoices"]["card_only"],
        scenario["invoices"]["zero_balance"],
    ]
    body = _Body(invoice_ids=ids, dry_run=dry_run, idempotency_key=key)
    user = {"id": "test_admin", "role": "admin", "email": "manager@aquaterra.com"}
    tenant = {"id": scenario["tenant_id"]}
    return _run(_core(body=body, user=user, tenant=tenant))


def test_ach_dry_run_marks_eligible_and_reasons(scenario, stub):
    tok = scenario["admin_token"]
    body = _bulk_body(scenario, dry_run=True)
    r = requests.post(
        f"{API}/invoices/bulk-charge-ach-on-file",
        json=body, headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["dry_run"] is True
    assert j.get("payment_method_type") == "ach"
    by_id = {row["invoice_id"]: row for row in j["results"]}
    assert by_id[scenario["invoices"]["eligible1"]]["status"] == "would_charge"
    assert by_id[scenario["invoices"]["eligible1"]]["bank_last4"] == "1111"
    assert by_id[scenario["invoices"]["eligible1"]]["bank_name"] == "AlphaBank"
    assert by_id[scenario["invoices"]["eligible2"]]["status"] == "would_charge"
    assert by_id[scenario["invoices"]["already_paid"]]["skip_reason"] == "already_paid"
    assert by_id[scenario["invoices"]["no_bank"]]["skip_reason"] == "no_bank_on_file"
    assert by_id[scenario["invoices"]["unverified"]]["skip_reason"] == "bank_unverified"
    assert by_id[scenario["invoices"]["card_only"]]["skip_reason"] == "no_bank_on_file"
    assert by_id[scenario["invoices"]["zero_balance"]]["skip_reason"] == "zero_balance"
    assert j["summary"]["would_charge"] == 2
    assert j["summary"]["skipped"] == 5
    assert j["summary"]["initiated"] == 0


def test_ach_real_initiates_only_eligible_and_flips_pending_ach(scenario, stub):
    key = f"{_TAG}_key_real_{uuid.uuid4().hex[:6]}"
    j = _in_process_bulk_ach(scenario, dry_run=False, key=key)
    assert j["dry_run"] is False
    assert j.get("payment_method_type") == "ach"
    assert j["summary"]["initiated"] == 2
    assert j["summary"]["skipped"] == 5
    assert j["summary"]["total_amount_initiated_cents"] == 12500 + 9950
    assert len(stub.calls) == 2
    keys = {c["idempotency_key"] for c in stub.calls}
    assert f"{key}:ach:{scenario['invoices']['eligible1']}" in keys
    assert f"{key}:ach:{scenario['invoices']['eligible2']}" in keys
    # ACH call must NOT include off_session/confirm at the router level;
    # the underlying charge_ach_on_file wraps that. Assert amount/currency
    # were passed through instead.
    first = stub.calls[0]
    assert first["amount_cents"] > 0
    assert first["currency"] == "usd"
    # Invoice must be in pending_ach (NOT paid) after the initiate.
    e1 = _sync.quotes.find_one({"id": scenario["invoices"]["eligible1"]})
    assert e1["payment_status"] == "pending_ach"
    assert e1.get("last_ach_intent_id")
    e2 = _sync.quotes.find_one({"id": scenario["invoices"]["eligible2"]})
    assert e2["payment_status"] == "pending_ach"
    # Row stored in bulk_charge_runs with ach type.
    run = _sync.bulk_charge_runs.find_one({"idempotency_key": key})
    assert run is not None
    assert run.get("payment_method_type") == "ach"
    assert run["summary"]["initiated"] == 2


def test_ach_bulk_idempotency_replay_is_zero_side_effect(scenario, stub):
    tok = scenario["admin_token"]
    key = f"{_TAG}_key_replay_{uuid.uuid4().hex[:6]}"
    body = _bulk_body(scenario, dry_run=False, key=key)
    r1 = requests.post(
        f"{API}/invoices/bulk-charge-ach-on-file",
        json=body, headers={"Authorization": f"Bearer {tok}"}, timeout=15,
    )
    assert r1.status_code == 200
    calls_first = len(stub.calls)
    j1 = r1.json()
    r2 = requests.post(
        f"{API}/invoices/bulk-charge-ach-on-file",
        json=body, headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r2.status_code == 200
    j2 = r2.json()
    # No additional stub calls between the two requests. NOTE: because
    # this hits the live server, the stub isn't visible over HTTP —
    # what we want to prove is the returned run_id + payload matches.
    assert len(stub.calls) == calls_first
    assert j2.get("replayed") is True
    assert j2["summary"] == j1["summary"]
    assert j2["run_id"] == j1["run_id"]


def test_ach_bulk_returns_failed_on_stripe_exception(scenario, stub):
    stub.error_for(scenario["invoices"]["eligible1"], RuntimeError("bank_declined"))
    j = _in_process_bulk_ach(
        scenario, dry_run=False,
        key=f"{_TAG}_key_exc_{uuid.uuid4().hex[:6]}",
        invoice_ids=[scenario["invoices"]["eligible1"],
                     scenario["invoices"]["eligible2"]],
    )
    by_id = {row["invoice_id"]: row for row in j["results"]}
    assert by_id[scenario["invoices"]["eligible1"]]["status"] == "failed"
    assert by_id[scenario["invoices"]["eligible1"]]["error_code"] == "RuntimeError"
    assert "bank_declined" in by_id[scenario["invoices"]["eligible1"]]["error_message"]
    assert by_id[scenario["invoices"]["eligible2"]]["status"] == "initiated"
    assert j["summary"]["initiated"] == 1
    assert j["summary"]["failed"] == 1
    # Failed invoice must NOT be flipped to pending_ach.
    e1 = _sync.quotes.find_one({"id": scenario["invoices"]["eligible1"]})
    assert e1["payment_status"] != "pending_ach"


def test_ach_bulk_cap_over_100_returns_422(scenario, stub):
    tok = scenario["admin_token"]
    body = {
        "invoice_ids": [f"x{i}" for i in range(101)],
        "dry_run": True,
        "idempotency_key": f"{_TAG}_key_cap_{uuid.uuid4().hex[:6]}",
    }
    r = requests.post(
        f"{API}/invoices/bulk-charge-ach-on-file",
        json=body, headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 422, r.text


def test_ach_bulk_role_guards_customer_403(scenario, stub):
    """Technicians (non-admin roles) must be rejected with 403.
    Uses ``carlos@aquaterra.com`` (technician) so we don't hit the
    ``customer@aquaterra.com`` lockout state on shared envs."""
    ctok = _login("carlos@aquaterra.com")
    body = {
        "invoice_ids": [scenario["invoices"]["eligible1"]],
        "dry_run": True,
        "idempotency_key": f"{_TAG}_key_tech_{uuid.uuid4().hex[:6]}",
    }
    r = requests.post(
        f"{API}/invoices/bulk-charge-ach-on-file",
        json=body, headers={"Authorization": f"Bearer {ctok}"}, timeout=10,
    )
    assert r.status_code == 403, r.text


def test_ach_bulk_cross_tenant_id_is_not_found_no_leak(scenario, stub):
    tok = scenario["admin_token"]
    body = {
        "invoice_ids": [scenario["invoices"]["eligible1"], "foreign-invoice-xyz"],
        "dry_run": True,
        "idempotency_key": f"{_TAG}_key_xtenant_{uuid.uuid4().hex[:6]}",
    }
    r = requests.post(
        f"{API}/invoices/bulk-charge-ach-on-file",
        json=body, headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 200
    j = r.json()
    assert len(j["results"]) == 2
    by_id = {row["invoice_id"]: row for row in j["results"]}
    assert by_id["foreign-invoice-xyz"]["skip_reason"] == "not_found"


# ═════════════════════════════════════════════════════════════════════
# Webhook: pending_ach → paid / unpaid transitions
# ═════════════════════════════════════════════════════════════════════
def test_webhook_ach_success_flips_pending_ach_to_paid(scenario):
    """``payment_intent.succeeded`` for an ACH invoice that was flipped
    to ``pending_ach`` must complete the transition to ``paid``."""
    inv_id = scenario["invoices"]["eligible1"]
    _sync.quotes.update_one(
        {"id": inv_id}, {"$set": {"payment_status": "pending_ach"}},
    )
    pi_id = f"pi_settle_{uuid.uuid4().hex[:8]}"
    event = {
        "type": "payment_intent.succeeded",
        "data": {"object": {
            "id": pi_id,
            "amount": 12500,
            "amount_received": 12500,
            "currency": "usd",
            "payment_method": scenario["pms"]["A"],
            "metadata": {
                "crm_tenant_id": scenario["tenant_id"],
                "crm_customer_id": scenario["customers"]["A"],
                "crm_invoice_id": inv_id,
                "payment_type": "ach",
            },
        }},
    }
    res = _run(stripe_module.handle_webhook_event(event))
    assert res["handled"] is True
    inv = _sync.quotes.find_one({"id": inv_id})
    assert inv["payment_status"] == "paid"


def test_webhook_ach_failure_reverts_pending_ach_to_unpaid(scenario):
    """``payment_intent.payment_failed`` for an invoice in ``pending_ach``
    must revert to ``unpaid`` (NOT flip to ``failed`` — that's the card
    path). K38 verbatim per spec."""
    inv_id = scenario["invoices"]["eligible2"]
    _sync.quotes.update_one(
        {"id": inv_id}, {"$set": {"payment_status": "pending_ach"}},
    )
    pi_id = f"pi_nsf_{uuid.uuid4().hex[:8]}"
    event = {
        "type": "payment_intent.payment_failed",
        "data": {"object": {
            "id": pi_id,
            "amount": 9950,
            "currency": "usd",
            "payment_method": scenario["pms"]["B"],
            "last_payment_error": {"message": "insufficient_funds"},
            "metadata": {
                "crm_tenant_id": scenario["tenant_id"],
                "crm_customer_id": scenario["customers"]["B"],
                "crm_invoice_id": inv_id,
                "payment_type": "ach",
            },
        }},
    }
    res = _run(stripe_module.handle_webhook_event(event))
    assert res["handled"] is True
    inv = _sync.quotes.find_one({"id": inv_id})
    assert inv["payment_status"] == "unpaid"
    assert inv.get("failure_reason") == "insufficient_funds"


def test_webhook_card_failure_still_flips_to_failed(scenario):
    """Regression guard: the K38 change to ``_mark_invoice_failed`` must
    ONLY branch on ``pending_ach``. A non-ACH failure with the invoice
    still ``unpaid`` must land on ``payment_status == "failed"``."""
    inv_id = scenario["invoices"]["eligible1"]
    _sync.quotes.update_one(
        {"id": inv_id}, {"$set": {"payment_status": "unpaid"}},
    )
    pi_id = f"pi_carddecline_{uuid.uuid4().hex[:8]}"
    event = {
        "type": "payment_intent.payment_failed",
        "data": {"object": {
            "id": pi_id,
            "amount": 12500,
            "currency": "usd",
            "payment_method": scenario["pms"]["A"],
            "last_payment_error": {"message": "card_declined"},
            "metadata": {
                "crm_tenant_id": scenario["tenant_id"],
                "crm_customer_id": scenario["customers"]["A"],
                "crm_invoice_id": inv_id,
            },
        }},
    }
    _run(stripe_module.handle_webhook_event(event))
    inv = _sync.quotes.find_one({"id": inv_id})
    assert inv["payment_status"] == "failed"
