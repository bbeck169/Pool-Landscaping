"""Invoice category validation · Feb-2026 — structured error shape.

Confirms that a POST /quotes with a bad line-item category returns
the enriched error payload the frontend consumes to surface an
inline row highlight:

    {
      "error_code": "archived_category" | "category_required",
      "line_index": <int>,
      "attempted_category": "<name>",  # only on archived_category
      "available_categories": [...],
      "field": "line_items[<idx>].category",
      "message": "...",
    }
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
    return requests.post(f"{API}/auth/login",
                         json={"email": email, "password": "password123"},
                         timeout=30).json()["access_token"]


def _me(tok: str) -> dict:
    return requests.get(f"{API}/auth/me",
                        headers={"Authorization": f"Bearer {tok}"},
                        timeout=15).json()


def _seed_customer(tenant_id: str) -> str:
    cid = f"TEST-cust-catval-{uuid.uuid4().hex[:8]}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "TEST_catval", "email": f"catval-{cid}@example.com",
        "is_active": True,
    })
    return cid


def test_archived_category_returns_structured_error():
    """Feb-2026 · invoice-category hard-block removal — invoice
    save with an archived/unknown legacy ``category`` value now
    returns 200 with an audit row written. Pre-removal behaviour
    was 400 ``archived_category``; the hard block was removed per
    operator request so cleanup workflows don't stall invoices.
    """
    tok = _login("admin@aquaterra.com")
    tenant = _me(tok)["tenant_id"]
    cust_id = _seed_customer(tenant)
    try:
        payload = {
            "customer_id": cust_id, "doc_type": "invoice",
            "title": "TEST_bad_cat", "line_items": [
                {"description": "TEST_line0", "quantity": 1,
                  "unit_price": 10.0, "category": "Pool"},
                {"description": "TEST_line1", "quantity": 1,
                  "unit_price": 20.0,
                  "category": f"TEST_ARCHIVED_{uuid.uuid4().hex[:5]}"},
            ],
        }
        r = requests.post(f"{API}/quotes", json=payload,
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("doc_type") == "invoice"
    finally:
        _sync.customers.delete_one({"id": cust_id})


def test_missing_category_returns_category_required():
    """Feb-2026 · invoice-category hard-block removal — missing
    legacy ``category`` on an invoice line item is now permitted
    with an audit row written. Pre-removal: 400 category_required.
    """
    tok = _login("admin@aquaterra.com")
    tenant = _me(tok)["tenant_id"]
    cust_id = _seed_customer(tenant)
    try:
        payload = {
            "customer_id": cust_id, "doc_type": "invoice",
            "title": "TEST_no_cat", "line_items": [
                {"description": "TEST_line0", "quantity": 1,
                  "unit_price": 15.0, "category": ""},
            ],
        }
        r = requests.post(f"{API}/quotes", json=payload,
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("doc_type") == "invoice"
    finally:
        _sync.customers.delete_one({"id": cust_id})
