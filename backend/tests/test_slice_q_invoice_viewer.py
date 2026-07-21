"""Feb 2026 · Slice Q — Invoice viewer aggregator + PDF tests.

Coverage:
* Admin GET /api/invoices/{iid}/full returns the shape used by
  <InvoiceView>: company, bill_to, property_address, header,
  line_items, totals, notes, is_due_on_receipt.
* Customer sees own invoice; other-tenant customer gets 404.
* Technician role is 403 on both endpoints.
* PDF endpoint returns application/pdf with %PDF- magic bytes.
"""
from __future__ import annotations

import asyncio
import os

import pytest
import requests

API = "http://localhost:8001/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(os.environ["MONGO_URL"],
                               io_loop=_LOOP)[os.environ["DB_NAME"]]


async def _pick_customer_invoice(customer_email="customer@aquaterra.com"):
    u = await _db().users.find_one({"email": customer_email},
                                     {"_id": 0, "customer_id": 1, "id": 1,
                                      "tenant_id": 1})
    cid = u.get("customer_id") or u.get("id")
    inv = await _db().quotes.find_one(
        {"tenant_id": u["tenant_id"], "doc_type": "invoice",
         "customer_id": cid}, {"_id": 0, "id": 1},
    )
    return inv["id"] if inv else None


async def _pick_any_invoice(tenant_slug="aquaterra"):
    t = await _db().tenants.find_one({"slug": tenant_slug},
                                       {"_id": 0, "id": 1})
    inv = await _db().quotes.find_one(
        {"tenant_id": t["id"], "doc_type": "invoice"},
        {"_id": 0, "id": 1},
    )
    return inv["id"] if inv else None


# ── /invoices/{iid}/full ─────────────────────────────────────────
def test_admin_full_shape(admin_headers):
    iid = _run(_pick_any_invoice())
    assert iid, "need an invoice in aquaterra"
    r = requests.get(f"{API}/invoices/{iid}/full",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("company", "bill_to", "property_address", "header",
                "line_items", "totals", "notes", "is_due_on_receipt"):
        assert key in body, f"missing key {key}"
    for key in ("invoice_number", "invoice_date",
                "credit_available", "outstanding_balance"):
        assert key in body["header"], f"missing header.{key}"
    for key in ("subtotal", "this_invoice", "amount_paid", "total_due"):
        assert key in body["totals"], f"missing totals.{key}"
    # Company reads from tenant public config.
    assert body["company"]["phone"] == "+16028874400"


def test_customer_can_view_own_invoice(customer_headers):
    iid = _run(_pick_customer_invoice())
    if not iid:
        pytest.skip("no invoice for demo customer")
    r = requests.get(f"{API}/invoices/{iid}/full",
                      headers=customer_headers, timeout=15)
    assert r.status_code == 200, r.text


def test_customer_cannot_view_other_invoice(customer_headers):
    """An arbitrary invoice not tied to the demo customer must 404."""
    async def _find_other():
        u = await _db().users.find_one({"email": "customer@aquaterra.com"},
                                         {"_id": 0, "customer_id": 1, "id": 1,
                                          "tenant_id": 1})
        cid = u.get("customer_id") or u.get("id")
        other = await _db().quotes.find_one(
            {"tenant_id": u["tenant_id"], "doc_type": "invoice",
             "customer_id": {"$ne": cid}},
            {"_id": 0, "id": 1},
        )
        return other["id"] if other else None
    other = _run(_find_other())
    if not other:
        pytest.skip("no non-customer invoice available")
    r = requests.get(f"{API}/invoices/{other}/full",
                      headers=customer_headers, timeout=15)
    assert r.status_code == 404, r.text


def test_tech_forbidden(tech_headers):
    iid = _run(_pick_any_invoice())
    r = requests.get(f"{API}/invoices/{iid}/full",
                      headers=tech_headers, timeout=15)
    assert r.status_code == 403


# ── /invoices/{iid}/pdf ─────────────────────────────────────────
def test_admin_pdf_download(admin_headers):
    iid = _run(_pick_any_invoice())
    r = requests.get(f"{API}/invoices/{iid}/pdf",
                      headers=admin_headers, timeout=30)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert r.content[:4] == b"%PDF", "PDF magic bytes missing"
    assert len(r.content) > 500


def test_customer_can_download_own_pdf(customer_headers):
    iid = _run(_pick_customer_invoice())
    if not iid:
        pytest.skip("no invoice for demo customer")
    r = requests.get(f"{API}/invoices/{iid}/pdf",
                      headers=customer_headers, timeout=30)
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"


def test_pdf_tech_forbidden(tech_headers):
    iid = _run(_pick_any_invoice())
    r = requests.get(f"{API}/invoices/{iid}/pdf",
                      headers=tech_headers, timeout=15)
    assert r.status_code == 403


def test_missing_invoice_404(admin_headers):
    r = requests.get(f"{API}/invoices/does-not-exist/full",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 404
