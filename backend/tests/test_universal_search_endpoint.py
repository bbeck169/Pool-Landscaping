"""Feb-2026 · Universal Search endpoint (INCOME-DRILLDOWN follow-up).

Locks in the consolidated ``GET /api/search`` contract:

  * Customers matched on name, email, phone (with digit-normalized
    matching), address, and billing_address.
  * Jobs matched on title / customer_name.
  * Invoices (``db.quotes`` with ``doc_type=="invoice"``) matched on
    invoice_number / customer_name / title.
  * Quotes (``db.quotes`` with ``doc_type=="quote"``) matched on
    quote_number / customer_name / title.
  * Leads matched on name / email / phone AND filtered to the
    canonical active statuses (``new`` / ``contacted`` / ``quoted``);
    closed-won / closed-lost never surface.
  * Multi-tenant scoped — cross-tenant records never bleed through.
  * Empty query returns empty groups (not 400) so the frontend can
    render its idle state without a second render pass.
  * Response shape: dict keyed by entity name, each value a list of
    ``{id, primary, secondary}`` rows.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import pytest
import requests
from dotenv import load_dotenv
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = _shared_client()
_db = _shared_db()


def _login(email: str) -> str:
    for _ in range(3):
        try:
            r = requests.post(
                f"{API}/auth/login",
                json={"email": email, "password": "password123"},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()["access_token"]
        except requests.exceptions.RequestException:
            pass
    pytest.skip(f"login unavailable for {email}")


def _admin_ctx() -> dict:
    tok = _login("super@aquaterra.com")
    me = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tok}"}, timeout=15,
    ).json()
    return {
        "headers": {"Authorization": f"Bearer {tok}"},
        "tenant_id": me["tenant_id"],
    }


def _get_search(headers: dict, **params) -> dict:
    r = requests.get(f"{API}/search", params=params, headers=headers, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def seeded_tenant_records():
    """Seed one distinctive record of every kind so the test can
    assert entity-by-entity filtering.  Uses a unique marker string
    embedded in every seeded field so we never collide with the
    aquaterra demo data."""
    ctx = _admin_ctx()
    marker = f"USEARCH{uuid.uuid4().hex[:8].upper()}"
    now_iso = datetime.now(timezone.utc).isoformat()
    seed = {
        "marker": marker,
        "customer_id": f"tc-{uuid.uuid4().hex[:8]}",
        "job_id": f"tj-{uuid.uuid4().hex[:8]}",
        "invoice_id": f"ti-{uuid.uuid4().hex[:8]}",
        "quote_id": f"tq-{uuid.uuid4().hex[:8]}",
        "active_lead_id": f"tl-{uuid.uuid4().hex[:8]}",
        "closed_lead_id": f"tlc-{uuid.uuid4().hex[:8]}",
        "cross_tenant_customer_id": f"txt-{uuid.uuid4().hex[:8]}",
    }
    _db.customers.insert_one({
        "id": seed["customer_id"], "tenant_id": ctx["tenant_id"],
        "name": f"{marker} Testcust", "email": f"{marker.lower()}@t.co",
        "phone": "(555) 555-1234",  # digit-normalized match target
        "address": f"1234 {marker} Way",
        "billing_address": "PO Box 99",
        "created_at": now_iso,
    })
    _db.jobs.insert_one({
        "id": seed["job_id"], "tenant_id": ctx["tenant_id"],
        "title": f"Weekly {marker} service", "customer_name": "Someone",
        "status": "scheduled", "created_at": now_iso,
    })
    _db.quotes.insert_one({
        "id": seed["invoice_id"], "tenant_id": ctx["tenant_id"],
        "doc_type": "invoice",
        "invoice_number": f"INV-{marker}",
        "customer_name": "Someone", "title": "Test invoice",
        "total": 123.45, "status": "sent", "created_at": now_iso,
    })
    _db.quotes.insert_one({
        "id": seed["quote_id"], "tenant_id": ctx["tenant_id"],
        "doc_type": "quote",
        "quote_number": f"QT-{marker}",
        "customer_name": "Someone", "title": "Test quote",
        "total": 999.99, "status": "sent", "created_at": now_iso,
    })
    _db.leads.insert_one({
        "id": seed["active_lead_id"], "tenant_id": ctx["tenant_id"],
        "name": f"{marker} Activelead", "email": "a@t.co", "phone": "555",
        "status": "new", "created_at": now_iso,
    })
    _db.leads.insert_one({
        "id": seed["closed_lead_id"], "tenant_id": ctx["tenant_id"],
        "name": f"{marker} Closedlead", "email": "c@t.co", "phone": "555",
        "status": "closed_lost", "created_at": now_iso,
    })
    _db.customers.insert_one({
        "id": seed["cross_tenant_customer_id"],
        "tenant_id": "TEST-OTHER-TENANT-search",
        "name": f"{marker} DoNotLeak", "email": "leak@x.co",
        "created_at": now_iso,
    })
    try:
        yield {**ctx, **seed}
    finally:
        _db.customers.delete_many({"id": {"$in": [
            seed["customer_id"], seed["cross_tenant_customer_id"],
        ]}})
        _db.jobs.delete_many({"id": seed["job_id"]})
        _db.quotes.delete_many({"id": {"$in": [
            seed["invoice_id"], seed["quote_id"],
        ]}})
        _db.leads.delete_many({"id": {"$in": [
            seed["active_lead_id"], seed["closed_lead_id"],
        ]}})


# ═════════════════════════════════════════════════════════════════════
# 1) Customer name match (multi-tenant scoped)
# ═════════════════════════════════════════════════════════════════════
def test_customer_match_by_name(seeded_tenant_records):
    ctx = seeded_tenant_records
    r = _get_search(ctx["headers"], q=ctx["marker"])
    ids = [row["id"] for row in r.get("customers") or []]
    assert ctx["customer_id"] in ids, (
        f"seeded customer not surfaced: got ids={ids!r}"
    )


# ═════════════════════════════════════════════════════════════════════
# 2) Phone digit-normalized match — typed "5555551234", stored
#    "(555) 555-1234"
# ═════════════════════════════════════════════════════════════════════
def test_customer_phone_digit_normalized_match(seeded_tenant_records):
    ctx = seeded_tenant_records
    r = _get_search(ctx["headers"], q="5555551234")
    ids = [row["id"] for row in r.get("customers") or []]
    assert ctx["customer_id"] in ids, (
        f"digit-normalized phone match failed: got ids={ids!r}"
    )


# ═════════════════════════════════════════════════════════════════════
# 3) Address substring match
# ═════════════════════════════════════════════════════════════════════
def test_customer_address_substring_match(seeded_tenant_records):
    ctx = seeded_tenant_records
    # Search on a substring that uniquely identifies our seeded
    # address (the marker + " Way").
    r = _get_search(ctx["headers"], q=f"{ctx['marker']} Way")
    ids = [row["id"] for row in r.get("customers") or []]
    assert ctx["customer_id"] in ids, (
        f"address substring match failed: got ids={ids!r}"
    )


# ═════════════════════════════════════════════════════════════════════
# 4) Invoices — doc_type=="invoice"
# ═════════════════════════════════════════════════════════════════════
def test_invoice_match_by_number(seeded_tenant_records):
    ctx = seeded_tenant_records
    r = _get_search(ctx["headers"], q=f"INV-{ctx['marker']}")
    ids = [row["id"] for row in r.get("invoices") or []]
    assert ctx["invoice_id"] in ids, (
        f"invoice not surfaced: got ids={ids!r}"
    )
    # The quote bucket must NOT contain the invoice — doc_type
    # discrimination lock.
    quote_ids = [row["id"] for row in r.get("quotes") or []]
    assert ctx["invoice_id"] not in quote_ids


# ═════════════════════════════════════════════════════════════════════
# 5) Quotes — doc_type=="quote"
# ═════════════════════════════════════════════════════════════════════
def test_quote_match_by_number(seeded_tenant_records):
    ctx = seeded_tenant_records
    r = _get_search(ctx["headers"], q=f"QT-{ctx['marker']}")
    ids = [row["id"] for row in r.get("quotes") or []]
    assert ctx["quote_id"] in ids, (
        f"quote not surfaced: got ids={ids!r}"
    )
    invoice_ids = [row["id"] for row in r.get("invoices") or []]
    assert ctx["quote_id"] not in invoice_ids


# ═════════════════════════════════════════════════════════════════════
# 6) Jobs match
# ═════════════════════════════════════════════════════════════════════
def test_job_match_by_title(seeded_tenant_records):
    ctx = seeded_tenant_records
    r = _get_search(ctx["headers"], q=f"Weekly {ctx['marker']}")
    ids = [row["id"] for row in r.get("jobs") or []]
    assert ctx["job_id"] in ids


# ═════════════════════════════════════════════════════════════════════
# 7) Leads — active only; closed_lost excluded
# ═════════════════════════════════════════════════════════════════════
def test_leads_active_only_closed_excluded(seeded_tenant_records):
    ctx = seeded_tenant_records
    r = _get_search(ctx["headers"], q=ctx["marker"])
    ids = [row["id"] for row in r.get("leads") or []]
    assert ctx["active_lead_id"] in ids, (
        f"active lead not surfaced: got ids={ids!r}"
    )
    assert ctx["closed_lead_id"] not in ids, (
        f"closed lead leaked into active drop-down: got ids={ids!r}"
    )


# ═════════════════════════════════════════════════════════════════════
# 8) Cross-tenant leakage guard
# ═════════════════════════════════════════════════════════════════════
def test_cross_tenant_leak_guard(seeded_tenant_records):
    ctx = seeded_tenant_records
    r = _get_search(ctx["headers"], q=ctx["marker"])
    ids = [row["id"] for row in r.get("customers") or []]
    assert ctx["cross_tenant_customer_id"] not in ids, (
        f"cross-tenant customer leaked: got ids={ids!r}"
    )


# ═════════════════════════════════════════════════════════════════════
# 9) Empty query returns empty groups (not 400)
# ═════════════════════════════════════════════════════════════════════
def test_empty_query_returns_empty_groups():
    ctx = _admin_ctx()
    r = _get_search(ctx["headers"], q="")
    # Every requested entity present, each an empty list.
    for e in ("customers", "jobs", "invoices", "quotes", "leads"):
        assert e in r, f"empty-query response missing group {e!r}: {r!r}"
        assert r[e] == [], f"empty-query group {e!r} not empty: {r[e]!r}"


# ═════════════════════════════════════════════════════════════════════
# 10) Response shape — grouped dict, each row has id + primary + secondary
# ═════════════════════════════════════════════════════════════════════
def test_response_grouped_shape(seeded_tenant_records):
    ctx = seeded_tenant_records
    r = _get_search(ctx["headers"], q=ctx["marker"])
    assert isinstance(r, dict), f"expected grouped dict, got {type(r).__name__}"
    for kind in ("customers", "jobs", "invoices", "quotes", "leads"):
        assert kind in r, f"missing group {kind!r} in {list(r.keys())}"
        rows = r[kind]
        assert isinstance(rows, list), (
            f"group {kind!r} not a list: {type(rows).__name__}"
        )
        for row in rows:
            assert "id" in row and row["id"]
            assert "primary" in row
            assert "secondary" in row


# ═════════════════════════════════════════════════════════════════════
# 11) Entity filter — client can request a subset (e.g. just leads)
# ═════════════════════════════════════════════════════════════════════
def test_entity_filter_narrows_response(seeded_tenant_records):
    ctx = seeded_tenant_records
    r = _get_search(ctx["headers"], q=ctx["marker"], entities="leads")
    assert "leads" in r
    # Non-requested buckets omitted.
    for e in ("customers", "jobs", "invoices", "quotes"):
        assert e not in r, (
            f"entity filter should omit {e!r} but response has it: {list(r.keys())}"
        )
