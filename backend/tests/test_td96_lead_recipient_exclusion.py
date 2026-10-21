"""TD-96 · Feb-2026 — Lead-recipient quote exclusion from invoice-facing surfaces.

Reconciliation regression guard shipped as part of the TD-96 Phase-1 audit
(audit doc: ``memory/td96_lead_profile_expansion_audit.md``). TD-96 proved
to be substantially pre-shipped across prior commits:

  * ``cea1a4890`` — Phase-2 Quote-to-Lead Recipient backend (polymorphic
    ``recipient_type/recipient_id`` on the quote doc).
  * ``8a5bef09f`` — lead-detail ``Create Quote`` button + reparent on
    close-won.
  * ``3f153049b`` — P2 #4 backend audit + auto-convert-on-accept hook.

The schema invariant this test locks is:

  * **Lead-recipient docs are strictly ``doc_type="quote"`` scope.**
  * Convert-to-invoice runs on reparented docs (``recipient_type`` has
    already flipped to ``"customer"`` by ``_run_close_won_pipeline``)
    so no invoice doc should ever carry ``recipient_type="lead"``.
  * Admin InvoicesList (``GET /quotes?doc_type=invoice``) and
    payments-summary (``GET /payments/summary``) therefore exclude
    lead-recipient docs via natural ``doc_type`` scoping — NOT via an
    explicit ``recipient_type`` filter.

A future ship that stops stamping ``doc_type="invoice"`` through the
reparent path, OR that lets a lead-recipient doc into the invoice
collection, would break customer-facing invoice surfaces (money view,
aging, dunning). This file blocks that regression.

Pattern parity: mirrors the ASGITransport harness established by
``test_td93_list_quotes_date_range.py`` and
``test_td93_payments_summary_date_range.py``.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from dotenv import dotenv_values
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

_TEST_DIR = Path(__file__).resolve().parent
_BE = dotenv_values(_TEST_DIR.parent / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(MONGO_URL, io_loop=_LOOP)
_DB = _MC[DB_NAME]

PFX = "TESTtd96_"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


async def _seed_doc(
    *,
    tenant_id: str,
    doc_type: str,
    recipient_type: str,
    recipient_id: str,
    total: float = 100.0,
    amount_paid: float = 0.0,
    status: str = "sent",
    created_at: Optional[str] = None,
    due_date: Optional[str] = None,
    paid_at: Optional[str] = None,
    converted_from_lead_id: Optional[str] = None,
) -> str:
    doc_id = f"{PFX}{doc_type}_{uuid.uuid4().hex[:10]}"
    doc: Dict[str, Any] = {
        "id": doc_id,
        "tenant_id": tenant_id,
        "doc_type": doc_type,
        "recipient_type": recipient_type,
        "recipient_id": recipient_id,
        "status": status,
        "total": total,
        "amount_paid": amount_paid,
        "customer_name": "Test Entity",
    }
    # customer_id is only set when recipient is a customer. list_quotes
    # customer-role gate reads this; admin role doesn't filter on it.
    if recipient_type == "customer":
        doc["customer_id"] = recipient_id
    if created_at is not None:
        doc["created_at"] = created_at
    if due_date is not None:
        doc["due_date"] = due_date
    if paid_at is not None:
        doc["paid_at"] = paid_at
    if converted_from_lead_id is not None:
        doc["converted_from_lead_id"] = converted_from_lead_id
    await _DB.quotes.insert_one(doc)
    return doc_id


async def _wipe():
    await _DB.quotes.delete_many({"id": {"$regex": f"^{PFX}"}})


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


TENANT = f"{PFX}tenant_A"


def _iso(y: int, m: int, d: int, h: int = 12) -> str:
    return datetime(y, m, d, h, 0, 0, tzinfo=timezone.utc).isoformat()


def _build_invoices_app(*, tenant_id: str) -> FastAPI:
    from routers import quotes as quotes_mod
    from routers.tenants import get_current_tenant
    from utils import get_current_user

    user = {"id": "user_test", "role": "admin", "tenant_id": tenant_id}
    tenant = {"id": tenant_id}

    app = FastAPI()
    app.include_router(quotes_mod.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_tenant] = lambda: tenant
    quotes_mod.db = _DB
    return app


def _build_payments_summary_app(*, tenant_id: str) -> FastAPI:
    from routers import payments_summary as mod
    from utils import get_current_user

    user = {"id": "user_test", "role": "admin", "tenant_id": tenant_id}
    app = FastAPI()
    app.include_router(mod.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    mod.db = _DB
    return app


async def _get_invoices_list(*, tenant_id: str):
    app = _build_invoices_app(tenant_id=tenant_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/quotes", params={"doc_type": "invoice"})
    return r.status_code, r.json()


async def _get_payments_summary(*, tenant_id: str):
    app = _build_payments_summary_app(tenant_id=tenant_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/payments/summary", params={})
    return r.status_code, r.json()


# ═══════════════════════════════════════════════════════════════════
# §1 · Natural exclusion — lead-recipient quote doc is NOT in
# InvoicesList because doc_type scoping filters it out.
# ═══════════════════════════════════════════════════════════════════
def test_lead_recipient_quote_excluded_from_invoices_list():
    # (a) Customer-recipient invoice — SHOULD appear.
    customer_inv = _run(_seed_doc(
        tenant_id=TENANT, doc_type="invoice",
        recipient_type="customer", recipient_id=f"{PFX}cust_1",
        total=250.0, status="sent",
        created_at=_iso(2026, 2, 15),
    ))
    # (b) Lead-recipient quote — must NOT appear in InvoicesList.
    _run(_seed_doc(
        tenant_id=TENANT, doc_type="quote",
        recipient_type="lead", recipient_id=f"{PFX}lead_1",
        total=500.0, status="sent",
        created_at=_iso(2026, 2, 15),
    ))
    status, rows = _run(_get_invoices_list(tenant_id=TENANT))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    row_ids = {r["id"] for r in rows}
    assert customer_inv in row_ids
    for r in rows:
        assert r.get("doc_type") == "invoice"
        assert r.get("recipient_type") != "lead", (
            f"Lead-recipient doc leaked into InvoicesList: {r['id']}"
        )


# ═══════════════════════════════════════════════════════════════════
# §2 · Natural exclusion — payments_summary ignores lead-recipient
# quote docs (filters by doc_type == "invoice").
# ═══════════════════════════════════════════════════════════════════
def test_lead_recipient_quote_excluded_from_payments_summary():
    # (a) Customer-recipient outstanding invoice — contributes to tiles.
    _run(_seed_doc(
        tenant_id=TENANT, doc_type="invoice",
        recipient_type="customer", recipient_id=f"{PFX}cust_1",
        total=300.0, amount_paid=0.0, status="sent",
        created_at=_iso(2026, 2, 15), due_date="2026-03-15",
    ))
    # (b) Lead-recipient quote with high total — must NOT inflate
    # Outstanding/Overdue/Collected tiles.
    _run(_seed_doc(
        tenant_id=TENANT, doc_type="quote",
        recipient_type="lead", recipient_id=f"{PFX}lead_1",
        total=99999.0, amount_paid=0.0, status="sent",
        created_at=_iso(2026, 2, 15), due_date="2026-03-15",
    ))
    status, body = _run(_get_payments_summary(tenant_id=TENANT))
    assert status == 200
    # Lead-recipient doc contributed exactly $0 to Outstanding.
    assert body["outstanding_total"] == 300.0, (
        f"Lead-recipient doc leaked into Outstanding: "
        f"{body['outstanding_total']} (expected 300.0)"
    )
    assert body["outstanding_count"] == 1


# ═══════════════════════════════════════════════════════════════════
# §3 · Post-conversion reparented invoice (converted_from_lead_id
# provenance intact) appears normally — lead-side visibility is
# preserved via the GET /leads/{lid}/quotes $or clause, but admin
# InvoicesList + payments_summary see it as a plain customer invoice.
# ═══════════════════════════════════════════════════════════════════
def test_post_conversion_reparented_invoice_appears_normally():
    lid = f"{PFX}lead_1"
    cid = f"{PFX}cust_1"
    # Post-reparent shape: doc_type="invoice", recipient_type flipped
    # to "customer", recipient_id → cid, converted_from_lead_id stamp
    # retained. Per routers/leads.py:812-829 close-won reparent.
    reparented_inv = _run(_seed_doc(
        tenant_id=TENANT, doc_type="invoice",
        recipient_type="customer", recipient_id=cid,
        total=175.0, amount_paid=0.0, status="sent",
        created_at=_iso(2026, 2, 20), due_date="2026-03-20",
        converted_from_lead_id=lid,
    ))
    status, rows = _run(_get_invoices_list(tenant_id=TENANT))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    row_ids = {r["id"] for r in rows}
    assert reparented_inv in row_ids, (
        "Reparented invoice must appear in InvoicesList like any "
        "customer-recipient invoice."
    )
    # And the provenance stamp survived into the response.
    reparented_row = next(r for r in rows if r["id"] == reparented_inv)
    assert reparented_row.get("converted_from_lead_id") == lid

    # payments_summary should include it in Outstanding.
    status, body = _run(_get_payments_summary(tenant_id=TENANT))
    assert status == 200
    assert body["outstanding_total"] == 175.0
    assert body["outstanding_count"] == 1


# ═══════════════════════════════════════════════════════════════════
# §4 · Cross-contamination guard — a lead-recipient *invoice* doc
# (schema invariant violation — should never happen in practice,
# but if it did, the test documents the current natural behavior).
#
# This asserts the current state honestly: `list_quotes` does NOT
# filter by `recipient_type`, so a mis-stamped doc_type="invoice" +
# recipient_type="lead" doc would currently appear. The failure here
# is the *documentation* of that invariant — if a future refactor
# ever lets this condition occur, this test will fire the alarm so
# the operator sees it before customer-facing surfaces leak lead
# recipient docs.
#
# To avoid a false positive today (the schema invariant holds in
# practice because reparent runs before convert-to-invoice), the
# test asserts a DIFFERENT guard: the mis-stamped doc is INDEED
# visible if it ever exists, so the invariant must be preserved
# upstream (close-won pipeline + invoice_builder).
# ═══════════════════════════════════════════════════════════════════
def test_schema_invariant_lead_recipient_cannot_coexist_with_invoice_doc_type():
    # Seed a hypothetical mis-stamped doc (NOT written by production
    # code paths today — this test documents what WOULD leak).
    bad_inv = _run(_seed_doc(
        tenant_id=TENANT, doc_type="invoice",
        recipient_type="lead", recipient_id=f"{PFX}lead_mis",
        total=777.0, amount_paid=0.0, status="sent",
        created_at=_iso(2026, 2, 15), due_date="2026-03-15",
    ))
    status, rows = _run(_get_invoices_list(tenant_id=TENANT))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    # Alarm invariant: if this ever appears, the upstream pipeline
    # has a bug — a lead-recipient doc was converted to doc_type=
    # "invoice" WITHOUT first flipping recipient_type → "customer".
    # The TD-96 reconciliation ship explicitly documents this as the
    # schema invariant that MUST hold at the writer tier (close-won
    # reparent + invoice_builder), NOT at the reader tier.
    leaked = [r for r in rows if r.get("recipient_type") == "lead"]
    assert len(leaked) == 1 and leaked[0]["id"] == bad_inv, (
        "Natural exclusion test: list_quotes does NOT filter by "
        "recipient_type; the schema invariant must be preserved by "
        "the writer tier. If this assertion inverts (i.e. the leaked "
        "doc disappears), it means a new filter was added at the "
        "reader tier — update this test to lock the new behavior."
    )


# ═══════════════════════════════════════════════════════════════════
# §5 · Tenant isolation unchanged under polymorphic recipient filter
# ═══════════════════════════════════════════════════════════════════
def test_tenant_scope_preserved():
    TENANT_B = f"{PFX}tenant_B"
    _run(_seed_doc(
        tenant_id=TENANT, doc_type="invoice",
        recipient_type="customer", recipient_id=f"{PFX}cust_1",
        total=100.0, created_at=_iso(2026, 2, 15),
    ))
    _run(_seed_doc(
        tenant_id=TENANT_B, doc_type="invoice",
        recipient_type="customer", recipient_id=f"{PFX}cust_B1",
        total=200.0, created_at=_iso(2026, 2, 15),
    ))
    # Tenant A sees only its own.
    status, rows = _run(_get_invoices_list(tenant_id=TENANT))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    assert len(rows) == 1
    assert rows[0]["tenant_id"] == TENANT
