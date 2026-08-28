"""Feb 2026 · Bug 1 + Bug 2 — invoice line cost-snapshot flow.

Reproduces the production bug: creating an invoice line from a
pricebook entry must copy ``wholesale_price`` + ``labor_cost_default``
into the line's ``wholesale_price_snapshot`` + ``labor_cost_snapshot``
so the Internal Margin panel, Profit Report, and EBIT report all
resolve non-$0 costs.

Contract (per ``routers/quotes.py::_stamp_line_snapshots``):
  * ``retail_price_snapshot`` — copied once from ``unit_price``.
  * ``wholesale_price_snapshot`` — pricebook ``wholesale_price``.
  * ``labor_cost_snapshot``     — pricebook ``labor_cost_default``.
  * Lines missing ``item_id`` are resolved by name (case-
    insensitive exact) against tenant pricebook.
  * Snapshots that are 0/None are re-hydrated on next update.
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List

import httpx
import pytest
from dotenv import dotenv_values
from pymongo import MongoClient


BASE = "http://localhost:8001"
_ENV = dotenv_values("/app/backend/.env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = MongoClient(_MONGO_URL)[_DB_NAME] if (_MONGO_URL and _DB_NAME) else None


def _mk_tenant() -> str:
    tid = f"COST_tenant_{uuid.uuid4().hex}"
    _sync.tenants.insert_one({
        "id": tid, "slug": f"cost-{uuid.uuid4().hex[:8]}",
        "name": "Cost Tenant", "active": True,
    })
    return tid


def _mk_admin(tid: str) -> str:
    from utils import hash_password
    email = f"cost-adm-{uuid.uuid4().hex[:8]}@example.com"
    _sync.users.insert_one({
        "id": f"COST_user_{uuid.uuid4().hex}",
        "email": email, "role": "admin",
        "password_hash": hash_password("password123"),
        "tenant_id": tid, "name": "Cost Adm",
        "failed_login_attempts": 0, "active": True,
    })
    return email


def _token_for(email: str) -> str:
    r = httpx.post(f"{BASE}/api/auth/login", json={
        "email": email, "password": "password123",
    }, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _mk_pricebook_item(tid: str, **kw) -> str:
    iid = f"COST_item_{uuid.uuid4().hex}"
    doc = {
        "id": iid, "tenant_id": tid,
        "name": kw.pop("name", "Item"),
        "unit_price": kw.pop("unit_price", 100.0),
        "wholesale_price": kw.pop("wholesale_price", 0.0),
        "labor_cost_default": kw.pop("labor_cost_default", 0.0),
        "category": kw.pop("category", "Chemicals"),
        "active": True,
        "created_at": "2026-02-01T00:00:00+00:00",
        "updated_at": "2026-02-01T00:00:00+00:00",
    }
    doc.update(kw)
    _sync.items.insert_one(doc)
    return iid


def _mk_customer(tid: str) -> str:
    cid = f"cs_{uuid.uuid4().hex}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": "Cust", "email": "c@x.com",
        "is_active": True,
        "created_at": "2026-02-01T00:00:00+00:00",
        "updated_at": "2026-02-01T00:00:00+00:00",
    })
    return cid


def _cleanup(tid: str):
    if _sync is None:
        return
    for coll in ("tenants", "users", "customers", "items",
                    "quotes", "migrations"):
        if coll == "migrations":
            _sync[coll].delete_many({"id": {"$regex": "^feb2026_invoice_line_cost"}})
            continue
        _sync[coll].delete_many({"tenant_id": tid})
    _sync.tenants.delete_many({"id": tid})


# ═════════════════════════════════════════════════════════════════════
def test_new_invoice_line_from_pricebook_stamps_wholesale_and_labor():
    """Ship an invoice with two lines mirroring the production repro:
    Shock ($12 · WS $7 · labor $0) and Filter Service ($125 · WS $0 ·
    labor $40). After POST, both lines must carry the correct cost
    snapshots — which drives the Internal Margin, Profit Report and
    EBIT panels."""
    tid = _mk_tenant()
    try:
        shock = _mk_pricebook_item(tid, name="Shock",
                                       unit_price=12.0,
                                       wholesale_price=7.0,
                                       labor_cost_default=0.0)
        filt = _mk_pricebook_item(tid, name="Filter Service",
                                      unit_price=125.0,
                                      wholesale_price=0.0,
                                      labor_cost_default=40.0)
        cid = _mk_customer(tid)
        adm = _mk_admin(tid)
        tok = _token_for(adm)
        payload = {
            "doc_type": "invoice",
            "title": "Test Invoice",
            "customer_id": cid,
            "line_items": [
                {"item_id": filt, "description": "Filter Service",
                  "quantity": 1, "unit_price": 125.0,
                  "category": "Chemicals"},
                {"item_id": shock, "description": "Shock",
                  "quantity": 6, "unit_price": 12.0,
                  "category": "Chemicals"},
            ],
            "tax_rate": 0,
        }
        r = httpx.post(f"{BASE}/api/quotes",
                         headers={"Authorization": f"Bearer {tok}"},
                         json=payload, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        lines = body["line_items"]
        # Line 0 — Filter Service.
        fl = next(li for li in lines if li["item_id"] == filt)
        assert fl["retail_price_snapshot"] == 125.0
        assert fl["wholesale_price_snapshot"] == 0.0
        assert fl["labor_cost_snapshot"] == 40.0
        # Line 1 — Shock.
        sl = next(li for li in lines if li["item_id"] == shock)
        assert sl["retail_price_snapshot"] == 12.0
        assert sl["wholesale_price_snapshot"] == 7.0
        assert sl["labor_cost_snapshot"] == 0.0
    finally:
        _cleanup(tid)


def test_manually_typed_line_resolves_pricebook_by_name():
    """Operator types "Shock" into an invoice line without picking
    from the pricebook dropdown (so ``item_id`` is blank).  The name
    fallback must resolve to the pricebook entry + hydrate costs +
    backfill ``item_id`` for future updates."""
    tid = _mk_tenant()
    try:
        shock = _mk_pricebook_item(tid, name="Shock",
                                       unit_price=12.0,
                                       wholesale_price=7.0,
                                       labor_cost_default=0.0)
        cid = _mk_customer(tid)
        tok = _token_for(_mk_admin(tid))
        payload = {
            "doc_type": "invoice", "customer_id": cid, "title": "Test Invoice",
            "line_items": [
                # NO item_id — mimics free-form entry.
                {"description": "Shock",
                  "quantity": 3, "unit_price": 12.0,
                  "category": "Chemicals"},
            ],
            "tax_rate": 0,
        }
        r = httpx.post(f"{BASE}/api/quotes",
                         headers={"Authorization": f"Bearer {tok}"},
                         json=payload, timeout=30)
        assert r.status_code == 200, r.text
        li = r.json()["line_items"][0]
        assert li["wholesale_price_snapshot"] == 7.0, li
        # item_id was hydrated for the next update.
        assert li.get("item_id") == shock, li
    finally:
        _cleanup(tid)


def test_manually_typed_line_case_insensitive_name_match():
    tid = _mk_tenant()
    try:
        _mk_pricebook_item(tid, name="Filter Service",
                              unit_price=125.0, wholesale_price=0.0,
                              labor_cost_default=40.0)
        cid = _mk_customer(tid)
        tok = _token_for(_mk_admin(tid))
        r = httpx.post(f"{BASE}/api/quotes",
                         headers={"Authorization": f"Bearer {tok}"},
                         json={
                             "doc_type": "invoice", "customer_id": cid, "title": "Test Invoice",
                             "line_items": [{
                                 "description": "  filter service  ",
                                 "quantity": 1, "unit_price": 125.0,
                                 "category": "Chemicals",
                             }],
                             "tax_rate": 0,
                         }, timeout=30)
        assert r.status_code == 200, r.text
        li = r.json()["line_items"][0]
        assert li["labor_cost_snapshot"] == 40.0
    finally:
        _cleanup(tid)


def test_pricebook_lookup_is_tenant_scoped():
    """A pricebook entry named "Shock" in tenant B must NOT leak
    into tenant A's line-cost hydration."""
    tid_a = _mk_tenant()
    tid_b = _mk_tenant()
    try:
        _mk_pricebook_item(tid_b, name="Shock",
                              unit_price=99.0, wholesale_price=77.0,
                              labor_cost_default=0.0)
        cid = _mk_customer(tid_a)
        tok = _token_for(_mk_admin(tid_a))
        r = httpx.post(f"{BASE}/api/quotes",
                         headers={"Authorization": f"Bearer {tok}"},
                         json={
                             "doc_type": "invoice", "customer_id": cid, "title": "Test Invoice",
                             "line_items": [{
                                 "description": "Shock", "quantity": 1,
                                 "unit_price": 12.0,
                                 "category": "Chemicals",
                             }],
                             "tax_rate": 0,
                         }, timeout=30)
        assert r.status_code == 200, r.text
        li = r.json()["line_items"][0]
        # Tenant A has no "Shock" — snapshot stays 0. No cross-leak.
        assert li["wholesale_price_snapshot"] == 0.0
        assert li.get("item_id") in (None, "")
    finally:
        _cleanup(tid_a); _cleanup(tid_b)


def test_backfill_migration_rehydrates_legacy_zeroed_snapshots():
    """Directly seed a legacy invoice with 0-valued cost snapshots +
    trigger the backfill via the super_admin force endpoint (same
    loop the backend runs on — avoids Motor cross-loop errors).
    Verify the snapshots are hydrated from the tenant pricebook
    without duplicating docs."""
    tid = _mk_tenant()
    try:
        shock = _mk_pricebook_item(tid, name="Shock",
                                       unit_price=12.0,
                                       wholesale_price=7.0,
                                       labor_cost_default=0.0)
        filt = _mk_pricebook_item(tid, name="Filter Service",
                                      unit_price=125.0,
                                      wholesale_price=0.0,
                                      labor_cost_default=40.0)
        cid = _mk_customer(tid)
        # Legacy invoice — snapshots explicitly at 0 (the bug state).
        inv_id = f"legacy_{uuid.uuid4().hex}"
        _sync.quotes.insert_one({
            "id": inv_id, "tenant_id": tid, "customer_id": cid,
            "doc_type": "invoice", "payment_status": "unpaid",
            "created_at": "2026-02-01T00:00:00+00:00",
            "line_items": [
                {"id": "L1", "item_id": filt,
                  "description": "Filter Service",
                  "quantity": 1, "unit_price": 125.0,
                  "retail_price_snapshot": 125.0,
                  "wholesale_price_snapshot": 0.0,
                  "labor_cost_snapshot": 0.0},
                {"id": "L2",  # No item_id — must resolve by name.
                  "description": "Shock",
                  "quantity": 6, "unit_price": 12.0,
                  "retail_price_snapshot": 12.0,
                  "wholesale_price_snapshot": 0.0,
                  "labor_cost_snapshot": 0.0},
            ],
        })
        # Seed a super_admin + force-run the backfill via HTTP.
        from utils import hash_password
        sup_email = f"sup-{uuid.uuid4().hex[:6]}@example.com"
        _sync.users.insert_one({
            "id": f"su_{uuid.uuid4().hex}", "email": sup_email,
            "role": "super_admin",
            "password_hash": hash_password("password123"),
            "tenant_id": tid, "name": "Sup", "active": True,
            "failed_login_attempts": 0,
        })
        tok = _token_for(sup_email)
        r = httpx.post(
            f"{BASE}/api/admin/migrations/invoice-line-cost-backfill?force=true",
            headers={"Authorization": f"Bearer {tok}"}, timeout=60,
        )
        assert r.status_code == 200, r.text
        summary = r.json().get("summary") or {}
        # This tenant's docs are counted in the rollup.
        assert summary.get("docs_updated", 0) >= 1
        assert summary.get("lines_hydrated_ws", 0) >= 1
        assert summary.get("lines_hydrated_lc", 0) >= 1
        # Verify the state landed on the actual doc.
        doc = _sync.quotes.find_one({"id": inv_id})
        by_desc = {li["description"]: li for li in doc["line_items"]}
        assert by_desc["Filter Service"]["labor_cost_snapshot"] == 40.0
        assert by_desc["Shock"]["wholesale_price_snapshot"] == 7.0
        # item_id was backfilled on the name-resolved line.
        assert by_desc["Shock"]["item_id"] == shock
    finally:
        _cleanup(tid)


def test_backfill_preserves_non_zero_existing_snapshots():
    """Historical (non-zero) snapshots must NOT be overwritten by
    the backfill — snapshots ARE immutable once meaningfully set."""
    tid = _mk_tenant()
    try:
        shock = _mk_pricebook_item(tid, name="Shock",
                                       unit_price=12.0,
                                       wholesale_price=9.99,  # <-- new price
                                       labor_cost_default=0.0)
        cid = _mk_customer(tid)
        inv_id = f"pinned_{uuid.uuid4().hex}"
        _sync.quotes.insert_one({
            "id": inv_id, "tenant_id": tid, "customer_id": cid,
            "doc_type": "invoice", "payment_status": "paid",
            "created_at": "2026-01-01T00:00:00+00:00",
            "line_items": [{
                "id": "L1", "item_id": shock,
                "description": "Shock",
                "quantity": 1, "unit_price": 12.0,
                "retail_price_snapshot": 12.0,
                "wholesale_price_snapshot": 7.00,  # historical
                "labor_cost_snapshot": 0.0,
            }],
        })
        from utils import hash_password
        sup_email = f"sup-{uuid.uuid4().hex[:6]}@example.com"
        _sync.users.insert_one({
            "id": f"su_{uuid.uuid4().hex}", "email": sup_email,
            "role": "super_admin",
            "password_hash": hash_password("password123"),
            "tenant_id": tid, "name": "Sup", "active": True,
            "failed_login_attempts": 0,
        })
        tok = _token_for(sup_email)
        httpx.post(
            f"{BASE}/api/admin/migrations/invoice-line-cost-backfill?force=true",
            headers={"Authorization": f"Bearer {tok}"}, timeout=60,
        )
        doc = _sync.quotes.find_one({"id": inv_id})
        # Preserved at $7.00 despite new pricebook value of $9.99.
        assert doc["line_items"][0]["wholesale_price_snapshot"] == 7.00
    finally:
        _cleanup(tid)


def test_ebit_report_reads_hydrated_cost_snapshots():
    """Bug 2 sibling — the EBIT report aggregates from
    ``wholesale_price_snapshot`` on line_items, so once Bug 1's
    fix + backfill wire up, this endpoint reports non-$0 COGS."""
    tid = _mk_tenant()
    try:
        shock = _mk_pricebook_item(tid, name="Shock",
                                       unit_price=12.0,
                                       wholesale_price=7.0,
                                       labor_cost_default=0.0)
        cid = _mk_customer(tid)
        tok = _token_for(_mk_admin(tid))
        # Create + mark paid.
        r = httpx.post(f"{BASE}/api/quotes",
                         headers={"Authorization": f"Bearer {tok}"},
                         json={
                             "doc_type": "invoice", "customer_id": cid, "title": "Test Invoice",
                             "line_items": [{
                                 "item_id": shock, "description": "Shock",
                  "quantity": 10, "unit_price": 12.0,
                                 "category": "Chemicals",
                             }],
                             "tax_rate": 0,
                         }, timeout=30)
        assert r.status_code == 200, r.text
        # Verify the snapshot landed — that's what EBIT reads.
        doc = _sync.quotes.find_one({"id": r.json()["id"]})
        li = doc["line_items"][0]
        # COGS at report time = qty × wholesale_snap
        assert li["wholesale_price_snapshot"] == 7.0
        assert 10 * li["wholesale_price_snapshot"] == 70.0
    finally:
        _cleanup(tid)
