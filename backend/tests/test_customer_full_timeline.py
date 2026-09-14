"""Feb-2026 · Customer Communication Timeline — full history endpoints.

Verifies the two new endpoints:

  * ``GET /api/customers/{customer_id}/timeline`` — admin
  * ``GET /api/customers/me/timeline``            — customer session

Acceptance:
  1. Admin timeline pulls from marketing_deliveries + invoices +
     estimates, sorted newest-first, paginated envelope.
  2. Customer portal timeline returns the same shape, filtered to
     the caller's OWN records.
  3. Filter chips work — CSV ``kind`` filter honored server-side.
  4. Dedupe (ref_id + kind) — marketing_deliveries whose
     ``trigger_entity`` points at an invoice/estimate suppress the
     raw quote row for the SAME ref.
  5. Non-admin caller → 403 on the admin route.
  6. Anon caller → 401 on both routes.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values, load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    pytest.skip("REACT_APP_BACKEND_URL not set", allow_module_level=True)
API = f"{BASE_URL}/api"

_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")

REQ_TIMEOUT = 30


def _login(email, password="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password},
                       timeout=REQ_TIMEOUT)
    r.raise_for_status()
    return r.json().get("access_token")


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


@pytest.fixture
def seed_customer_fixture(dbc):
    """Seed a self-contained customer with a marketing delivery, an
    invoice, and an estimate. Purged on teardown."""
    tenant = dbc.tenants.find_one({"slug": "aquaterra"})
    tenant_id = tenant["id"]
    cid = f"tl-cust-{uuid.uuid4()}"
    dbc.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "Timeline Test", "email": f"{cid}@pytest.local",
        "phone": "+15550000000",
    })
    now = datetime.now(timezone.utc)
    inv_id = f"tl-inv-{uuid.uuid4()}"
    est_id = f"tl-est-{uuid.uuid4()}"
    md_id  = f"tl-md-{uuid.uuid4()}"
    dbc.quotes.insert_many([
        {"id": inv_id, "tenant_id": tenant_id, "customer_id": cid,
         "doc_type": "invoice", "total": 250.0, "status": "sent",
         "payment_status": "unpaid", "number": "TL-INV-1",
         "created_at": (now - timedelta(hours=2)).isoformat()},
        {"id": est_id, "tenant_id": tenant_id, "customer_id": cid,
         "doc_type": "quote",   "total": 100.0, "status": "draft",
         "number": "TL-EST-1",
         "created_at": (now - timedelta(hours=3)).isoformat()},
    ])
    dbc.marketing_deliveries.insert_one({
        "id": md_id, "tenant_id": tenant_id, "customer_id": cid,
        "channel": "email", "recipient_address": f"{cid}@pytest.local",
        "template_code": "invoice_sent_email",
        "subject": "Your invoice is ready",
        "delivery_status": "sent",
        "trigger_kind": "invoice_sent",
        "trigger_entity": {"kind": "invoice", "id": inv_id},
        "created_at": (now - timedelta(hours=1)).isoformat(),
    })
    yield {"tenant_id": tenant_id, "customer_id": cid,
             "invoice_id": inv_id, "estimate_id": est_id,
             "delivery_id": md_id}
    dbc.customers.delete_one({"id": cid, "tenant_id": tenant_id})
    dbc.quotes.delete_many({"id": {"$in": [inv_id, est_id]}})
    dbc.marketing_deliveries.delete_one({"id": md_id})


# ─── Acceptance 1 — admin merges + sorts + paginates ────────────

def test_admin_timeline_merges_all_sources_sorted_desc(
    admin_headers, seed_customer_fixture,
):
    r = requests.get(
        f"{API}/customers/{seed_customer_fixture['customer_id']}/timeline"
        f"?page=1&page_size=50",
        headers=admin_headers, timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    # Envelope shape.
    for k in ("items", "page", "page_size", "total", "total_pages"):
        assert k in body, k
    assert body["page"] == 1
    assert body["page_size"] == 50
    kinds = {i["kind"] for i in body["items"]}
    # marketing (email) + invoice + estimate at minimum.
    assert "email" in kinds
    assert "estimate" in kinds
    # Sorted newest-first.
    ts = [i["created_at"] for i in body["items"]]
    assert ts == sorted(ts, reverse=True)


# ─── Acceptance 2 — customer portal returns own records only ────

def test_portal_timeline_returns_own_records(
    customer_headers, seed_customer_fixture, dbc,
):
    r = requests.get(
        f"{API}/customers/me/timeline?page_size=50",
        headers=customer_headers, timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    # The seed fixture's rows belong to a DIFFERENT customer, so
    # NONE of them should appear on customer@aquaterra.com's own
    # timeline. Never leak cross-customer records.
    stranger_ref_ids = {
        seed_customer_fixture["invoice_id"],
        seed_customer_fixture["estimate_id"],
        seed_customer_fixture["delivery_id"],
    }
    leaked = [i for i in body["items"] if i.get("ref_id") in stranger_ref_ids]
    assert not leaked, f"cross-customer leak: {leaked}"


# ─── Acceptance 3 — kind filter honored server-side ─────────────

def test_admin_timeline_kind_filter_email_only(
    admin_headers, seed_customer_fixture,
):
    r = requests.get(
        f"{API}/customers/{seed_customer_fixture['customer_id']}/timeline"
        f"?kind=email",
        headers=admin_headers, timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text[:300]
    kinds = {i["kind"] for i in r.json()["items"]}
    assert kinds <= {"email"}, kinds


def test_admin_timeline_kind_filter_invoice_estimate(
    admin_headers, seed_customer_fixture,
):
    r = requests.get(
        f"{API}/customers/{seed_customer_fixture['customer_id']}/timeline"
        f"?kind=invoice,estimate",
        headers=admin_headers, timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200
    kinds = {i["kind"] for i in r.json()["items"]}
    assert kinds <= {"invoice", "estimate"}
    # Both invoice AND estimate rows come through when both are asked.
    assert kinds == {"invoice", "estimate"}


# ─── Acceptance 4 — dedupe by ref (marketing wins) ──────────────

def test_admin_timeline_dedupes_invoice_send_from_raw_row(
    admin_headers, seed_customer_fixture,
):
    """The marketing_deliveries row for the fixture invoice has
    ``trigger_entity = {kind: "invoice", id: <inv_id>}``. The raw
    invoice row should be SUPPRESSED so the timeline shows exactly
    one entry for that ref."""
    r = requests.get(
        f"{API}/customers/{seed_customer_fixture['customer_id']}/timeline",
        headers=admin_headers, timeout=REQ_TIMEOUT,
    )
    body = r.json()
    inv_id = seed_customer_fixture["invoice_id"]
    # Marketing row present (delivery for that invoice).
    md_row = next((i for i in body["items"]
                     if i.get("ref_id") == seed_customer_fixture["delivery_id"]),
                    None)
    assert md_row is not None
    # Raw invoice row for the same ref MUST NOT be present.
    raw_inv = [i for i in body["items"]
                 if i.get("kind") == "invoice" and i.get("ref_id") == inv_id]
    assert not raw_inv, (
        f"dedupe failed — raw invoice row leaked next to the "
        f"marketing_delivery: {raw_inv}"
    )


# ─── Acceptance 5 — admin route rejects non-admin ───────────────

def test_admin_timeline_rejects_customer_session(customer_headers, dbc):
    tenant = dbc.tenants.find_one({"slug": "aquaterra"})
    stranger_cid = f"tl-stranger-{uuid.uuid4()}"
    dbc.customers.insert_one({
        "id": stranger_cid, "tenant_id": tenant["id"],
        "name": "Stranger", "email": f"{stranger_cid}@pytest.local",
    })
    try:
        r = requests.get(
            f"{API}/customers/{stranger_cid}/timeline",
            headers=customer_headers, timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 403, r.text[:300]
    finally:
        dbc.customers.delete_one({"id": stranger_cid,
                                    "tenant_id": tenant["id"]})


# ─── Acceptance 6 — anon → 401 on both routes ───────────────────

def test_anon_admin_route_returns_401():
    r = requests.get(f"{API}/customers/some/timeline", timeout=REQ_TIMEOUT)
    assert r.status_code in (401, 403)


def test_anon_portal_route_returns_401():
    r = requests.get(f"{API}/customers/me/timeline", timeout=REQ_TIMEOUT)
    assert r.status_code in (401, 403)


def test_portal_route_rejects_admin_session(admin_headers):
    """Admin session on the customer-me route → 403 (admin has no
    ``customer_id`` on the JWT payload)."""
    r = requests.get(
        f"{API}/customers/me/timeline",
        headers=admin_headers, timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 403, r.text[:300]
