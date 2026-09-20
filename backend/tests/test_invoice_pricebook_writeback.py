"""Invoice pricebook writeback · Feb-2026 · Fan-out semantics.

Confirms:
  1. ``pricebook_writeback=True`` updates the linked pricebook row's
     ``unit_price`` after a successful invoice save.
  2. An audit row lands in ``db.pricebook_writeback_events`` with the
     before/after diff and the actor id.
  3. Free-text lines with ``pricebook_writeback=True`` and no
     ``item_id`` create a NEW pricebook row.
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


def _seed_pbitem(tenant: str, *, unit_price: float = 50.0) -> str:
    iid = f"TEST-pbwb-{uuid.uuid4().hex[:10]}"
    _sync.items.insert_one({
        "id": iid, "tenant_id": tenant,
        "name": f"TEST_pbwb_{iid[-4:]}", "unit_price": unit_price,
        "unit": "each", "category": "Pool", "item_type": "product",
    })
    return iid


def _seed_customer(tenant: str) -> str:
    cid = f"TEST-cust-pbwb-{uuid.uuid4().hex[:8]}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tenant,
        "name": "TEST_pbwb_cust", "email": f"pbwb-{cid}@example.com",
        "is_active": True,
    })
    return cid


def _cleanup(pb: list[str], custs: list[str], invs: list[str]):
    _sync.items.delete_many({"id": {"$in": pb}})
    _sync.customers.delete_many({"id": {"$in": custs}})
    _sync.quotes.delete_many({"id": {"$in": invs}})


def test_writeback_updates_existing_pricebook_item_and_audits():
    tok = _login("admin@aquaterra.com")
    me = _me(tok)
    tenant = me["tenant_id"]
    pb_id = _seed_pbitem(tenant, unit_price=50.0)
    cust_id = _seed_customer(tenant)
    inv_ids: list[str] = []
    created_ids: list[str] = []
    try:
        payload = {
            "customer_id": cust_id, "doc_type": "invoice",
            "title": "TEST_wb_update", "line_items": [{
                "description": "TEST_wb_line", "quantity": 1,
                "unit_price": 88.0, "category": "Pool",
                "item_id": pb_id, "pricebook_item_id": pb_id,
                "pricebook_writeback": True,
            }],
        }
        r = requests.post(f"{API}/quotes", json=payload,
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=15)
        assert r.status_code == 200, r.text
        inv = r.json()
        inv_ids.append(inv["id"])
        # Pricebook was updated.
        pb_after = _sync.items.find_one({"id": pb_id}, {"_id": 0})
        assert pb_after["unit_price"] == 88.0, (
            f"expected writeback to overwrite unit_price, got {pb_after}")
        # Audit row landed.
        audit = _sync.pricebook_writeback_events.find_one(
            {"invoice_id": inv["id"], "pricebook_item_id": pb_id},
            {"_id": 0},
        )
        assert audit is not None, "audit row missing"
        assert audit["action"] == "update"
        assert audit["before"]["unit_price"] == 50.0
        assert audit["after"]["unit_price"] == 88.0
        assert audit["actor_user_id"]
    finally:
        _cleanup([pb_id, *created_ids], [cust_id], inv_ids)
        _sync.pricebook_writeback_events.delete_many(
            {"invoice_id": {"$in": inv_ids}})


def test_writeback_free_text_line_creates_new_pricebook_item():
    tok = _login("admin@aquaterra.com")
    tenant = _me(tok)["tenant_id"]
    cust_id = _seed_customer(tenant)
    inv_ids: list[str] = []
    created_ids: list[str] = []
    unique_name = f"TEST_wb_new_{uuid.uuid4().hex[:6]}"
    try:
        payload = {
            "customer_id": cust_id, "doc_type": "invoice",
            "title": "TEST_wb_create", "line_items": [{
                "description": unique_name, "quantity": 2,
                "unit_price": 19.99, "category": "Pool",
                "pricebook_writeback": True,
            }],
        }
        r = requests.post(f"{API}/quotes", json=payload,
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=15)
        assert r.status_code == 200, r.text
        inv = r.json()
        inv_ids.append(inv["id"])
        # Pricebook has a fresh row with the same name.
        fresh = _sync.items.find_one({"tenant_id": tenant, "name": unique_name},
                                       {"_id": 0})
        assert fresh is not None, f"pricebook row missing for {unique_name}"
        assert fresh["unit_price"] == 19.99
        assert fresh.get("source") == "invoice_writeback"
        created_ids.append(fresh["id"])
        # Audit row confirms create.
        audit = _sync.pricebook_writeback_events.find_one(
            {"invoice_id": inv["id"], "pricebook_item_id": fresh["id"]},
            {"_id": 0},
        )
        assert audit is not None
        assert audit["action"] == "create"
        assert audit["before"] is None
    finally:
        _sync.items.delete_many({"id": {"$in": created_ids}})
        _sync.customers.delete_one({"id": cust_id})
        _sync.quotes.delete_many({"id": {"$in": inv_ids}})
        _sync.pricebook_writeback_events.delete_many(
            {"invoice_id": {"$in": inv_ids}})


def test_writeback_off_leaves_pricebook_untouched():
    tok = _login("admin@aquaterra.com")
    tenant = _me(tok)["tenant_id"]
    pb_id = _seed_pbitem(tenant, unit_price=77.0)
    cust_id = _seed_customer(tenant)
    inv_ids: list[str] = []
    try:
        payload = {
            "customer_id": cust_id, "doc_type": "invoice",
            "title": "TEST_wb_off", "line_items": [{
                "description": "TEST_wb_off_line", "quantity": 1,
                "unit_price": 999.0,  # divergent but writeback is False
                "category": "Pool",
                "item_id": pb_id, "pricebook_item_id": pb_id,
                "pricebook_writeback": False,
            }],
        }
        r = requests.post(f"{API}/quotes", json=payload,
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=15)
        assert r.status_code == 200, r.text
        inv_ids.append(r.json()["id"])
        # Pricebook untouched.
        pb_after = _sync.items.find_one({"id": pb_id}, {"_id": 0})
        assert pb_after["unit_price"] == 77.0
        # No audit row.
        audit_count = _sync.pricebook_writeback_events.count_documents(
            {"invoice_id": {"$in": inv_ids}})
        assert audit_count == 0
    finally:
        _cleanup([pb_id], [cust_id], inv_ids)
        _sync.pricebook_writeback_events.delete_many(
            {"invoice_id": {"$in": inv_ids}})
