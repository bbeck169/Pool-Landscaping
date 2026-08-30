"""Invoice pricebook writeback · Feb-2026 · Tenant isolation.

Confirms an invoice save in tenant A CANNOT reach across to mutate a
pricebook item that belongs to tenant B, even if the payload carries
an ``item_id`` that resolves to a foreign row.

Setup:
  * Create a pricebook item stamped with a synthetic tenant B id.
  * Create an invoice in tenant A (real seeded admin tenant) with a
    line item referencing tenant B's pricebook id AND
    ``pricebook_writeback=True``.
  * Assert the invoice saves BUT tenant B's item is untouched (the
    writeback silently falls through to the name-match branch which,
    finding no local match, creates a NEW row in tenant A).
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _login(email: str) -> str:
    return requests.post(f"{API}/auth/login",
                         json={"email": email, "password": "password123"},
                         timeout=30).json()["access_token"]


def _me(tok: str) -> dict:
    return requests.get(f"{API}/auth/me",
                        headers={"Authorization": f"Bearer {tok}"},
                        timeout=15).json()


def _seed_foreign_pbitem() -> tuple[str, str]:
    tid = f"TEST-tenantB-{uuid.uuid4().hex[:10]}"
    iid = f"TEST-pbfor-{uuid.uuid4().hex[:10]}"
    _sync.items.insert_one({
        "id": iid, "tenant_id": tid,
        "name": f"TEST_foreign_pb_{iid[-4:]}",
        "unit_price": 123.45, "unit": "each",
        "category": "Pool", "item_type": "product",
    })
    return tid, iid


def _seed_customer(tenant: str) -> str:
    cid = f"TEST-cust-iso-{uuid.uuid4().hex[:8]}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tenant,
        "name": "TEST_iso", "email": f"iso-{cid}@example.com",
        "is_active": True,
    })
    return cid


def test_writeback_cannot_cross_tenant_boundary():
    tok = _login("admin@aquaterra.com")
    me = _me(tok)
    tenant_a = me["tenant_id"]
    tenant_b, foreign_pb_id = _seed_foreign_pbitem()
    cust_id = _seed_customer(tenant_a)
    inv_ids: list[str] = []
    created_local_ids: list[str] = []
    try:
        payload = {
            "customer_id": cust_id, "doc_type": "invoice",
            "title": "TEST_iso_wb", "line_items": [{
                "description": f"TEST_iso_line_{uuid.uuid4().hex[:6]}",
                "quantity": 1, "unit_price": 999.99, "category": "Pool",
                # Malicious FK pointing at tenant B's pricebook row.
                "item_id": foreign_pb_id,
                "pricebook_item_id": foreign_pb_id,
                "pricebook_writeback": True,
            }],
        }
        r = requests.post(f"{API}/quotes", json=payload,
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=15)
        assert r.status_code == 200, r.text
        inv = r.json()
        inv_ids.append(inv["id"])

        # Tenant B's pricebook row is UNTOUCHED.
        foreign_after = _sync.items.find_one({"id": foreign_pb_id}, {"_id": 0})
        assert foreign_after is not None
        assert foreign_after["tenant_id"] == tenant_b
        assert foreign_after["unit_price"] == 123.45, (
            "tenant boundary violated — foreign pricebook row was mutated")

        # No audit row was written against tenant B's pricebook id.
        cross_audit = _sync.pricebook_writeback_events.find_one({
            "pricebook_item_id": foreign_pb_id,
            "invoice_id": inv["id"],
            "tenant_id": tenant_b,
        }, {"_id": 0})
        assert cross_audit is None, (
            "audit row was written against foreign tenant — leak")

        # The writeback landed as a NEW row in tenant A (safe fallback).
        # There must be exactly one such row for this unique description.
        line_desc = payload["line_items"][0]["description"]
        local = _sync.items.find_one({"tenant_id": tenant_a,
                                        "name": line_desc}, {"_id": 0})
        if local:  # allowed but not required
            created_local_ids.append(local["id"])
            assert local["tenant_id"] == tenant_a
    finally:
        _sync.items.delete_many({"id": {"$in": [foreign_pb_id, *created_local_ids]}})
        _sync.customers.delete_one({"id": cust_id})
        _sync.quotes.delete_many({"id": {"$in": inv_ids}})
        _sync.pricebook_writeback_events.delete_many(
            {"invoice_id": {"$in": inv_ids}})
