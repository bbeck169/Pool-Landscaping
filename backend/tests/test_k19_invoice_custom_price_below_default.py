"""Phase K19 · Feb-2026 — Invoice-create regression lock for the user's
exact prod-P0 scenario.

Reproducer (as reported by the user):
  * A pricebook item "Clean Up and Trim Trees" exists at $875.00.
  * Operator creates an invoice for a customer.
  * Adds a single line item at ``unit_price=300`` (BELOW pricebook
    default) with the FK to that pricebook row.
  * "Also save this to the pricebook" is UNCHECKED
    (``pricebook_writeback=False``).
  * Prod returns 502; expected: 200 + invoice created with
    ``overridden_price=True``.

Preview does NOT reproduce with the current code (both product and
service ``item_type`` variants succeed). This test locks that
behaviour so a regression that reintroduces a 4xx / 5xx on the
"below-default, no-writeback" combo is caught immediately.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _login(email: str = "admin@aquaterra.com") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _me(tok: str) -> dict:
    return requests.get(f"{API}/auth/me",
                         headers={"Authorization": f"Bearer {tok}"},
                         timeout=15).json()


def _seed_customer(tenant_id: str) -> str:
    cid = f"TEST-k19-cust-{uuid.uuid4().hex[:8]}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "TEST_k19_cust", "email": f"k19-{cid}@example.com",
        "is_active": True,
    })
    return cid


def _seed_pricebook(tenant_id: str, *, item_type: str) -> str:
    iid = f"TEST-k19-pb-{uuid.uuid4().hex[:10]}"
    _sync.items.insert_one({
        "id": iid, "tenant_id": tenant_id,
        "name": f"TEST_k19_Clean Up and Trim Trees {iid[-4:]}",
        "unit_price": 875.0, "unit": "each",
        "category": "Landscaping", "item_type": item_type,
    })
    return iid


def _cleanup(pb: list[str], custs: list[str], invs: list[str]) -> None:
    if pb: _sync.items.delete_many({"id": {"$in": pb}})
    if custs: _sync.customers.delete_many({"id": {"$in": custs}})
    if invs: _sync.quotes.delete_many({"id": {"$in": invs}})


@pytest.mark.parametrize("item_type", ["service", "product"])
def test_k19_custom_price_below_default_no_writeback(item_type: str):
    """User's prod-P0 exact scenario: below-default price, FK set,
    writeback UNCHECKED. Both ``service`` and ``product`` variants
    must return 200 + ``overridden_price=True`` (post-Feb-2026
    softened rule)."""
    tok = _login()
    tenant = _me(tok)["tenant_id"]
    pb_id = _seed_pricebook(tenant, item_type=item_type)
    cust_id = _seed_customer(tenant)
    inv_ids: list[str] = []
    try:
        payload = {
            "customer_id": cust_id,
            "doc_type": "invoice",
            "title": "TEST_k19_below_default",
            "tax_rate": 0,
            "line_items": [{
                "description": "Clean Up and Trim Trees",
                "quantity": 1,
                "unit_price": 300.00,          # ← BELOW pricebook default 875
                "category": "Landscaping",
                "item_id": pb_id,
                "pricebook_item_id": pb_id,
                "pricebook_writeback": False,   # unchecked
            }],
        }
        r = requests.post(f"{API}/quotes", json=payload,
                           headers={"Authorization": f"Bearer {tok}"},
                           timeout=15)
        assert r.status_code == 200, (
            f"K19 regression ({item_type}): expected 200, got "
            f"{r.status_code} {r.text[:400]}"
        )
        inv = r.json()
        inv_ids.append(inv["id"])
        li = inv["line_items"][0]
        assert li["unit_price"] == 300.0
        assert li.get("overridden_price") is True, (
            f"below-default price must stamp overridden_price=True "
            f"({item_type})")
        # Invoice landed with a number and totals resolved from the
        # custom price, not the pricebook default.
        assert inv["total"] == 300.0
        assert inv.get("invoice_number", "").startswith("INV-"), (
            f"invoice_number should be assigned on birth "
            f"({item_type}): {inv.get('invoice_number')!r}"
        )
        # Pricebook row untouched (writeback=False).
        pb_row = _sync.items.find_one({"id": pb_id}, {"_id": 0})
        assert pb_row["unit_price"] == 875.0, (
            f"pricebook untouched without writeback ({item_type})")
    finally:
        _cleanup([pb_id], [cust_id], inv_ids)


def test_k19_custom_price_no_pricebook_fk():
    """Same scenario minus the FK — operator manually typed the
    description that DOESN'T resolve to a pricebook entry. Must
    still land 200 without any pricebook coupling."""
    tok = _login()
    tenant = _me(tok)["tenant_id"]
    cust_id = _seed_customer(tenant)
    inv_ids: list[str] = []
    try:
        payload = {
            "customer_id": cust_id, "doc_type": "invoice",
            "title": "TEST_k19_no_fk", "tax_rate": 0,
            "line_items": [{
                "description": "TEST_k19_no_fk unique service",
                "quantity": 1, "unit_price": 300.00,
                "category": "Landscaping",
                "pricebook_writeback": False,
            }],
        }
        r = requests.post(f"{API}/quotes", json=payload,
                           headers={"Authorization": f"Bearer {tok}"},
                           timeout=15)
        assert r.status_code == 200, r.text
        inv = r.json()
        inv_ids.append(inv["id"])
        li = inv["line_items"][0]
        assert li["unit_price"] == 300.0
        assert li.get("item_id") in (None, "")
        # No pricebook coupling → overridden_price stays False
        # (there's no default to override).
        assert li.get("overridden_price") is False
    finally:
        _cleanup([], [cust_id], inv_ids)
