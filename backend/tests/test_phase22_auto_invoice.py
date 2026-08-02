"""Phase 22 · Sub-item C — auto-invoice on job complete tests.

Covers all 5 acceptance cases from the phase brief:
    C1) Complete a job (no card on file) → invoice created, unpaid,
        job.auto_invoice_id stamped.
    C2) Complete same job again → idempotent short-circuit, NO second
        invoice.
    C3) Complete a job w/ card on file → charge_card_on_file called
        with idempotency_key="auto_invoice:{job_id}", invoice marked
        paid.
    C4) Complete a job where card charge returns ok=False → invoice
        stays unpaid, audit row written, no crash.
    C5) Complete a job on a tenant with
        auto_invoice_on_job_complete=false → NO invoice created.

Motor loop-rebinding pattern shared with test_phase18.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_FRESH = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _FRESH[_ENV["DB_NAME"]]

from services import auto_invoice as _ai  # noqa: E402
_ai.db = _DB


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _seed(tenant_setting=None, price=150.0, with_card=False,
           with_chemical_events=False):
    tid = f"p22c-{uuid.uuid4().hex[:8]}"
    cid = f"cust-{uuid.uuid4().hex[:8]}"
    jid = f"job-{uuid.uuid4().hex[:8]}"
    tdoc = {"id": tid, "name": f"P22 {tid}", "slug": f"p22c-{tid}",
             "active": True, "widget_allowed_domains": []}
    if tenant_setting is not None:
        tdoc["settings"] = {"auto_invoice_on_job_complete": tenant_setting}
    _sync.tenants.insert_one(tdoc)
    _sync.customers.insert_one({"id": cid, "tenant_id": tid, "email": f"{cid}@x.test",
                                 "name": "P22 Customer"})
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tid, "customer_id": cid,
        "customer_name": "P22 Customer",
        "service_type": "pool_cleaning", "title": "Weekly pool visit",
        "status": "in_progress", "price": price,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    if with_card:
        _sync.payment_methods.insert_one({
            "id": f"pm-{uuid.uuid4().hex[:8]}",
            "tenant_id": tid, "customer_id": cid,
            "status": "active", "brand": "visa", "last4": "4242",
        })
    if with_chemical_events:
        _sync.chemical_usage_events.insert_one({
            "id": f"ev-{uuid.uuid4().hex[:8]}",
            "tenant_id": tid, "job_id": jid, "customer_id": cid,
            "product_slug": "liquid_chlorine", "name": "Liquid Chlorine",
            "quantity_used": 3, "unit": "gal",
            "unit_cost_at_time_cents": 450,
            "total_cost_cents": 1350,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        })
    return {"tid": tid, "cid": cid, "jid": jid}


def _cleanup(tid):
    for col in ("tenants","customers","jobs","payment_methods",
                "chemical_usage_events","quotes","auto_invoice_runs"):
        _sync[col].delete_many({"tenant_id": tid})


def test_C1_creates_invoice_when_no_card(monkeypatch):
    ctx = _seed()
    try:
        # No stub — no card on file, no charge attempted.
        r = _run(_ai.create_invoice_from_job(ctx["jid"], ctx["tid"]))
        assert r["ok"] and r["created"] is True
        inv_id = r["invoice_id"]
        invoice = _sync.quotes.find_one({"id": inv_id})
        assert invoice["doc_type"] == "invoice"
        assert invoice["payment_status"] == "unpaid"
        assert invoice["total_cents"] == 15000
        assert len(invoice["line_items"]) == 1
        job = _sync.jobs.find_one({"id": ctx["jid"]})
        assert job["auto_invoice_id"] == inv_id
        audit = _sync.auto_invoice_runs.find_one({"job_id": ctx["jid"]})
        assert audit and audit["invoice_id"] == inv_id
        assert audit["card_charge_attempted"] is False
    finally:
        _cleanup(ctx["tid"])


def test_C2_is_idempotent(monkeypatch):
    ctx = _seed()
    try:
        r1 = _run(_ai.create_invoice_from_job(ctx["jid"], ctx["tid"]))
        first_id = r1["invoice_id"]
        assert r1["created"] is True
        r2 = _run(_ai.create_invoice_from_job(ctx["jid"], ctx["tid"]))
        assert r2["created"] is False
        assert r2["invoice_id"] == first_id
        assert r2["reason"] == "already_invoiced"
        # Only one invoice row exists.
        cnt = _sync.quotes.count_documents(
            {"tenant_id": ctx["tid"], "job_id": ctx["jid"]})
        assert cnt == 1
    finally:
        _cleanup(ctx["tid"])


def test_C3_charges_card_on_file(monkeypatch):
    ctx = _seed(with_card=True, with_chemical_events=True)
    calls = {}

    async def fake_charge(*, invoice_id, tenant_id, idempotency_key):
        calls["invoice_id"] = invoice_id
        calls["idempotency_key"] = idempotency_key
        return {"ok": True, "charge_id": "ch_fake",
                "amount_cents": 16350}

    from services.payments import stripe_charge as _sc
    monkeypatch.setattr(_sc, "charge_card_on_file", fake_charge)
    try:
        r = _run(_ai.create_invoice_from_job(ctx["jid"], ctx["tid"]))
        assert r["created"] is True and r["charged"] is True
        assert calls["idempotency_key"] == f"auto_invoice:{ctx['jid']}"
        invoice = _sync.quotes.find_one({"id": r["invoice_id"]})
        assert invoice["payment_status"] == "paid"
        # service line (15000) + chemical line (1350) = 16350
        assert invoice["total_cents"] == 16350
        assert len(invoice["line_items"]) == 2
    finally:
        _cleanup(ctx["tid"])


def test_C4_charge_failure_leaves_invoice_unpaid(monkeypatch):
    ctx = _seed(with_card=True)

    async def fake_charge(**kw):
        return {"ok": False, "error": "card_declined"}

    from services.payments import stripe_charge as _sc
    monkeypatch.setattr(_sc, "charge_card_on_file", fake_charge)
    try:
        r = _run(_ai.create_invoice_from_job(ctx["jid"], ctx["tid"]))
        assert r["created"] is True
        assert r["charged"] is False
        invoice = _sync.quotes.find_one({"id": r["invoice_id"]})
        assert invoice["payment_status"] == "unpaid"
        audit = _sync.auto_invoice_runs.find_one({"job_id": ctx["jid"]})
        assert audit["charge_result"] == {"ok": False,
                                            "error": "card_declined"}
        assert audit["card_charge_attempted"] is True
    finally:
        _cleanup(ctx["tid"])


def test_C5_tenant_setting_disabled(monkeypatch):
    ctx = _seed(tenant_setting=False)
    try:
        r = _run(_ai.create_invoice_from_job(ctx["jid"], ctx["tid"]))
        assert r["created"] is False
        assert r["invoice_id"] is None
        assert r["reason"] == "skipped_tenant_setting"
        assert _sync.quotes.count_documents(
            {"tenant_id": ctx["tid"], "job_id": ctx["jid"]}) == 0
    finally:
        _cleanup(ctx["tid"])
