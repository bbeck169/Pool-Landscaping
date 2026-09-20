"""Invoice inline edit · Feb-2026 — custom unit_price acceptance.

Confirms the softened price-lock rule:
  * A line item whose ``unit_price`` diverges from the pricebook
    default is accepted (no more ``product_price_locked`` 400).
  * The line's ``overridden_price`` flag flips to ``True``.
  * The pricebook row itself is untouched unless the caller opted
    into ``pricebook_writeback`` (covered in a separate test).
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = _shared_db()
def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": "password123"},
                      timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _me(tok: str) -> dict:
    return requests.get(f"{API}/auth/me",
                        headers={"Authorization": f"Bearer {tok}"},
                        timeout=15).json()


def _seed_pricebook_item(tenant_id: str, *, unit_price: float = 100.0,
                          item_type: str = "product",
                          name: str | None = None) -> str:
    iid = f"TEST-pbitem-{uuid.uuid4().hex[:10]}"
    _sync.items.insert_one({
        "id": iid,
        "tenant_id": tenant_id,
        "name": name or f"TEST_pbitem_{iid[-4:]}",
        "unit_price": unit_price,
        "unit": "each",
        "category": "Pool",
        "item_type": item_type,
    })
    return iid


def _seed_customer(tenant_id: str) -> str:
    cid = f"TEST-cust-cprice-{uuid.uuid4().hex[:8]}"
    _sync.customers.insert_one({
        "id": cid,
        "tenant_id": tenant_id,
        "name": "TEST_custprice",
        "email": f"cprice-{cid}@example.com",
        "is_active": True,
    })
    return cid


def _cleanup(*, pb: list[str] | None = None,
              custs: list[str] | None = None,
              invs: list[str] | None = None) -> None:
    if pb:
        _sync.items.delete_many({"id": {"$in": pb}})
    if custs:
        _sync.customers.delete_many({"id": {"$in": custs}})
    if invs:
        _sync.quotes.delete_many({"id": {"$in": invs}})


def test_custom_unit_price_accepted_on_product_line():
    tok = _login("admin@aquaterra.com")
    me = _me(tok)
    tenant = me["tenant_id"]
    pb_id = _seed_pricebook_item(tenant, unit_price=100.0, item_type="product")
    cust_id = _seed_customer(tenant)
    inv_ids: list[str] = []
    try:
        payload = {
            "customer_id": cust_id,
            "doc_type": "invoice",
            "title": "TEST_custprice_invoice",
            "line_items": [{
                "description": "TEST_pbitem_line",
                "quantity": 2,
                "unit_price": 137.50,          # ← diverges from pricebook $100
                "category": "Pool",
                "item_id": pb_id,
                "pricebook_item_id": pb_id,
                "pricebook_writeback": False,   # explicit: no writeback
            }],
        }
        r = requests.post(f"{API}/quotes", json=payload,
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=15)
        assert r.status_code == 200, r.text
        inv = r.json()
        inv_ids.append(inv["id"])
        li = inv["line_items"][0]
        assert li["unit_price"] == 137.50
        assert li.get("overridden_price") is True, (
            "custom price should stamp overridden_price=True")
        # Pricebook row untouched.
        pb_row = _sync.items.find_one({"id": pb_id}, {"_id": 0})
        assert pb_row["unit_price"] == 100.0, (
            "pricebook untouched without writeback flag")
    finally:
        _cleanup(pb=[pb_id], custs=[cust_id], invs=inv_ids)


def test_no_override_flag_when_price_matches_pricebook():
    tok = _login("admin@aquaterra.com")
    tenant = _me(tok)["tenant_id"]
    pb_id = _seed_pricebook_item(tenant, unit_price=42.0, item_type="product")
    cust_id = _seed_customer(tenant)
    inv_ids: list[str] = []
    try:
        payload = {
            "customer_id": cust_id, "doc_type": "invoice",
            "title": "TEST_noovr", "line_items": [{
                "description": "TEST_matches", "quantity": 1,
                "unit_price": 42.0, "category": "Pool",
                "item_id": pb_id, "pricebook_item_id": pb_id,
            }],
        }
        r = requests.post(f"{API}/quotes", json=payload,
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=15)
        assert r.status_code == 200, r.text
        inv = r.json()
        inv_ids.append(inv["id"])
        li = inv["line_items"][0]
        assert li.get("overridden_price") is False
    finally:
        _cleanup(pb=[pb_id], custs=[cust_id], invs=inv_ids)
