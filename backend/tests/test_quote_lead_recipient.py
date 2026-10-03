"""Phase 2 · Feb-2026 · Quote-to-Lead Recipient — end-to-end pytest.

Loop-isolation: fixture re-applies the db monkeypatch BEFORE every
test, so cross-file pytest collection order can't shadow our
loop-bound client (see Phase 1 ``test_convert_quote_to_invoice.py``
which patches the same module-level ``db`` aliases against ITS own
event loop).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_ENV = {k: (v.strip().strip('"').strip("'") if isinstance(v, str) else v)
        for k, v in _ENV.items()}
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
    for mod in ("routers.quotes", "routers.estimates", "routers.reports",
                "routers.estimate_viewer", "services.invoice_builder",
                "services.invoice_numbering", "services.recipient",
                "routers.finances"):
        __import__(mod)
        import sys as _sys
        _sys.modules[mod].db = _DB


# NOTE: Phase 2 isolation fix (Feb-2026) — module-scope
# ``_patch_db_everywhere()`` call removed. The autouse ``_clean``
# fixture below already re-pins before every test; the module-scope
# call was redundant AND clobbered Phase 1's patches at collection
# time when both suites ran in the same pytest invocation.


PREFIX = f"ph2lead-{uuid4().hex[:8]}"
TENANT_A = f"{PREFIX}-tenant-a"
TENANT_B = f"{PREFIX}-tenant-b"


async def _seed_tenant(tid):
    await _DB.tenants.insert_one({"id": tid, "name": f"Tenant {tid}",
        "timezone": "America/Phoenix", "settings": {}})


async def _seed_customer(cid, tid, name="Carla Cust", email="carla@example.com"):
    await _DB.customers.insert_one({"id": cid, "tenant_id": tid,
        "name": name, "email": email})


async def _seed_lead(lid, tid, name="Larry Lead", email="larry@example.com",
                       phone="480-555-0001", address="100 Palo Verde Way"):
    await _DB.leads.insert_one({"id": lid, "tenant_id": tid, "name": name,
        "email": email, "phone": phone, "address": address,
        "status": "New", "source": "admin_manual"})


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in ("quotes", "customers", "leads", "audit_logs",
                 "invoice_number_sequences", "settings", "properties"):
        await _DB[coll].delete_many({"$or": [{"id": rx}, {"tenant_id": rx}]})
    await _DB.tenants.delete_many({"id": rx})


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()  # re-pin before every test
    _run(_cleanup())
    yield
    _run(_cleanup())


_ADMIN = {"id": f"{PREFIX}-u-admin", "role": "admin"}


async def _post_quote(**body_kwargs):
    from routers.quotes import create_quote
    from models import QuoteIn, LineItem
    tenant_id = body_kwargs.pop("_tenant", TENANT_A)
    line_items = body_kwargs.pop("line_items", None) or [
        LineItem(description="Service", quantity=1, unit_price=100.0),
    ]
    body = QuoteIn(line_items=line_items, title="Test", **body_kwargs)
    return await create_quote(body, user=_ADMIN, tenant={"id": tenant_id})


def test_legacy_customer_id_path_still_works():
    cid = f"{PREFIX}-cust-legacy"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_customer(cid, TENANT_A))
    out = _run(_post_quote(customer_id=cid))
    assert out["customer_id"] == cid
    assert out["recipient_type"] == "customer"
    assert out["recipient_id"] == cid


def test_lead_recipient_happy_path():
    lid = f"{PREFIX}-lead-happy"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid, TENANT_A))
    out = _run(_post_quote(recipient_type="lead", recipient_id=lid))
    assert out["recipient_type"] == "lead"
    assert out["recipient_id"] == lid
    assert out.get("customer_id") in (None, "")
    assert out["customer_name"] == "Larry Lead"
    assert out["customer_address"] == "100 Palo Verde Way"
    assert out.get("property_id") is None


def test_lead_recipient_quote_does_not_create_customer_row():
    lid = f"{PREFIX}-lead-np"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid, TENANT_A, name="Noah Nopromote"))
    before = _run(_DB.customers.count_documents({"tenant_id": TENANT_A}))
    _run(_post_quote(recipient_type="lead", recipient_id=lid))
    after = _run(_DB.customers.count_documents({"tenant_id": TENANT_A}))
    assert after == before
    lead_after = _run(_DB.leads.find_one({"id": lid}, {"_id": 0}))
    assert lead_after is not None and lead_after.get("status") == "New"


def test_lead_recipient_invalid_id_returns_400():
    _run(_seed_tenant(TENANT_A))
    with pytest.raises(HTTPException) as exc:
        _run(_post_quote(recipient_type="lead",
                           recipient_id=f"{PREFIX}-does-not-exist"))
    assert exc.value.status_code == 400


def test_lead_recipient_cross_tenant_returns_400():
    lid = f"{PREFIX}-lead-xten"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_tenant(TENANT_B))
    _run(_seed_lead(lid, TENANT_B))
    with pytest.raises(HTTPException) as exc:
        _run(_post_quote(recipient_type="lead", recipient_id=lid,
                            _tenant=TENANT_A))
    assert exc.value.status_code == 400


def test_missing_both_recipient_shapes_returns_400():
    _run(_seed_tenant(TENANT_A))
    with pytest.raises(HTTPException) as exc:
        _run(_post_quote())
    assert exc.value.status_code == 400


def test_get_quote_returns_recipient_fields():
    from unittest.mock import MagicMock
    lid = f"{PREFIX}-lead-get"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid, TENANT_A))
    created = _run(_post_quote(recipient_type="lead", recipient_id=lid))
    from routers.quotes import get_quote
    request = MagicMock(); request.headers = {}; request.client = None
    doc = _run(get_quote(created["id"], request=request, user=_ADMIN,
        tenant={"id": TENANT_A}))
    assert doc["recipient_type"] == "lead"
    assert doc["recipient_id"] == lid
    assert doc["customer_name"] == "Larry Lead"
    assert doc.get("customer_email") == "larry@example.com"


def test_phase1_convert_to_invoice_on_lead_recipient_quote():
    lid = f"{PREFIX}-lead-conv"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid, TENANT_A, name="Clara Convert"))
    created = _run(_post_quote(recipient_type="lead", recipient_id=lid))
    _run(_DB.quotes.update_one(
        {"id": created["id"], "tenant_id": TENANT_A},
        {"$set": {"status": "accepted"}}))
    from routers.quotes import convert_quote_to_invoice
    out = _run(convert_quote_to_invoice(
        created["id"], user=_ADMIN, tenant={"id": TENANT_A}))
    inv = _run(_DB.quotes.find_one({"id": out["invoice_id"]}, {"_id": 0}))
    assert inv["doc_type"] == "invoice"
    assert inv["recipient_type"] == "lead"
    assert inv["recipient_id"] == lid
    assert inv.get("customer_id") in (None, "")
    assert inv.get("customer_name") == "Clara Convert"
    src = _run(_DB.quotes.find_one({"id": created["id"]}, {"_id": 0}))
    assert src["converted_invoice_id"] == out["invoice_id"]


def test_lead_no_email_send_to_customer_returns_phase2_error_copy():
    lid = f"{PREFIX}-lead-noemail"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid, TENANT_A, email=""))
    created = _run(_post_quote(recipient_type="lead", recipient_id=lid))
    _run(_DB.quotes.update_one(
        {"id": created["id"], "tenant_id": TENANT_A},
        {"$set": {"status": "draft"}}))
    from routers.quotes import send_quote_to_customer, _SendToCustomerIn
    body = _SendToCustomerIn(recipient_email="", note="")
    with pytest.raises(HTTPException) as exc:
        _run(send_quote_to_customer(
            created["id"], body, user=_ADMIN, tenant={"id": TENANT_A}))
    assert exc.value.status_code == 400
    detail = str(exc.value.detail)
    assert "Lead has no email on file" in detail
    assert "recipient_email" in detail


def test_revenue_by_customer_includes_lead_recipient_paid_invoice():
    lid = f"{PREFIX}-lead-rev"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid, TENANT_A, name="Rhonda Revenue"))
    _run(_DB.quotes.insert_one({
        "id": f"{PREFIX}-inv-rev", "tenant_id": TENANT_A, "doc_type": "invoice",
        "customer_id": None, "customer_name": "Rhonda Revenue",
        "recipient_type": "lead", "recipient_id": lid,
        "line_items": [], "subtotal": 500.0, "tax": 0.0, "total": 500.0,
        "amount_paid": 500.0, "status": "paid", "payment_status": "paid",
        "paid_at": "2026-02-15T12:00:00+00:00",
        "created_at": "2026-02-10T00:00:00+00:00",
    }))
    cid = f"{PREFIX}-cust-rev"
    _run(_seed_customer(cid, TENANT_A, name="Charles Customer"))
    _run(_DB.quotes.insert_one({
        "id": f"{PREFIX}-inv-rev-cust", "tenant_id": TENANT_A,
        "doc_type": "invoice",
        "customer_id": cid, "customer_name": "Charles Customer",
        "recipient_type": "customer", "recipient_id": cid,
        "line_items": [], "subtotal": 300.0, "tax": 0.0, "total": 300.0,
        "amount_paid": 300.0, "status": "paid", "payment_status": "paid",
        "paid_at": "2026-02-15T12:00:00+00:00",
        "created_at": "2026-02-10T00:00:00+00:00",
    }))
    from routers.reports import revenue_by_customer
    out = _run(revenue_by_customer(start=None, end=None,
        user=_ADMIN, tenant={"id": TENANT_A}))
    rows_by_name = {r["customer_name"]: r for r in out["rows"]}
    assert "Rhonda Revenue" in rows_by_name
    assert "Charles Customer" in rows_by_name
    lead_row = rows_by_name["Rhonda Revenue"]
    cust_row = rows_by_name["Charles Customer"]
    assert abs(lead_row["amount"] - 500.0) < 0.01
    assert abs(cust_row["amount"] - 300.0) < 0.01
    assert lead_row != cust_row
    assert lead_row["customer_id"] == "unknown"
    assert cust_row["customer_id"] == cid
