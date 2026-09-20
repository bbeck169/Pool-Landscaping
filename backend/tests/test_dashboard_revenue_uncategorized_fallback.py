"""Feb-2026 · Priority 6 (Bug 3) — revenue-by-category fallback chain.

The dashboard's ``revenue-by-category`` + ``income-by-service-category``
tiles were silently dropping paid invoices whose line items lacked an
inline ``category`` value OR that had no ``line_items`` array at all.
The top-card lifetime-paid number would then diverge from the tile sum
and operators would spend hours chasing "phantom" revenue.

This suite locks the new fallback chain:

  1. Line ``category`` missing but ``item_id`` maps to a pricebook item
     with ``category`` set → tile buckets under the pricebook category.
  2. Line ``category`` missing AND ``item_id`` missing / unresolvable
     → tile buckets under ``"Uncategorized"``.
  3. Invoice with an empty ``line_items`` array but a positive ``total``
     → tile recognises the invoice ``total`` under ``"Uncategorized"``
     so paid revenue never silently disappears from the chart.
  4. Same fallback (rule 3) applies to
     ``/admin/dashboard/income-by-service-category``.

Harness mirrors ``test_dashboard_revenue_paid_only.py`` (sync PyMongo
for setup, HTTP against the live pod backend, JWT via
``/api/auth/login`` of the admin seed).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
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
_sync = _shared_client()
_db = _shared_db()
_TOK_CACHE: dict = {}


def _login(email: str = "admin@aquaterra.com") -> tuple[str, str]:
    key = f"tok:{email}"
    if _TOK_CACHE.get(key):
        return _TOK_CACHE[key]
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=30)
    r.raise_for_status()
    tok = r.json()["access_token"]
    me = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tok}"}, timeout=30,
    ).json()
    tid = me.get("tenant_id") or me.get("tenant", {}).get("id") or ""
    _TOK_CACHE[key] = (tok, tid)
    return tok, tid


_FIXTURE_PREFIX = f"TEST-p6-{uuid.uuid4().hex[:6]}"


def _seed_invoice(*, tenant_id: str,
                    line_items: list[dict],
                    total_override: float | None = None) -> str:
    iid = f"{_FIXTURE_PREFIX}-inv-{uuid.uuid4().hex[:6]}"
    when = datetime.now(timezone.utc).replace(day=1)
    total = (total_override if total_override is not None
              else sum(li.get("quantity", 0) * li.get("unit_price", 0)
                       for li in line_items))
    _db.quotes.insert_one({
        "id": iid, "tenant_id": tenant_id, "doc_type": "invoice",
        "invoice_number": iid,
        "created_at": when.isoformat(),
        "status": "accepted",
        "payment_status": "paid",
        "currency": "USD",
        "total": total,
        "subtotal": total,
        "line_items": line_items,
    })
    return iid


def _seed_pricebook_item(*, tenant_id: str, category: str) -> str:
    iid = f"{_FIXTURE_PREFIX}-pb-{uuid.uuid4().hex[:6]}"
    _db.items.insert_one({
        "id": iid, "tenant_id": tenant_id,
        "name": "P6 pricebook fixture", "category": category,
        "unit_price": 0.0,
    })
    return iid


def _cleanup() -> None:
    _db.quotes.delete_many({"id": {"$regex": f"^{_FIXTURE_PREFIX}"}})
    _db.items.delete_many({"id": {"$regex": f"^{_FIXTURE_PREFIX}"}})


def setup_module(module):
    _cleanup()


def teardown_module(module):
    _cleanup()


def _month_range() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    start = now.replace(day=1).date().isoformat()
    end = now.date().isoformat()
    return start, end


# ══════════════════════════════════════════════════════════════════════
# Rule 1 — line category missing, item_id resolves via pricebook.
# ══════════════════════════════════════════════════════════════════════
def test_line_without_category_falls_back_to_pricebook_category():
    tok, tid = _login()
    pb_id = _seed_pricebook_item(
        tenant_id=tid, category="TEST-p6-Pool",
    )
    inv_id = _seed_invoice(
        tenant_id=tid,
        line_items=[{"description": "line no cat but has item_id",
                      "quantity": 1, "unit_price": 175.0,
                      "item_id": pb_id}],
    )
    try:
        start, end = _month_range()
        r = requests.get(
            f"{API}/admin/dashboard/revenue-by-category",
            params={"start": start, "end": end},
            headers={"Authorization": f"Bearer {tok}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        cats = {c["category"]: c["amount"] for c in r.json()["items"]}
        assert cats.get("TEST-p6-Pool") == 175.0, (
            f"pricebook fallback must bucket under item's category; got {cats}"
        )
    finally:
        _db.quotes.delete_one({"id": inv_id})
        _db.items.delete_one({"id": pb_id})


# ══════════════════════════════════════════════════════════════════════
# Rule 2 — no inline category, no item_id → Uncategorized.
# ══════════════════════════════════════════════════════════════════════
def test_line_without_category_or_item_id_buckets_uncategorized():
    tok, tid = _login()
    inv_id = _seed_invoice(
        tenant_id=tid,
        line_items=[{"description": "orphan line", "quantity": 2,
                      "unit_price": 40.0}],
    )
    try:
        start, end = _month_range()
        r = requests.get(
            f"{API}/admin/dashboard/revenue-by-category",
            params={"start": start, "end": end},
            headers={"Authorization": f"Bearer {tok}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        cats = {c["category"]: c["amount"] for c in r.json()["items"]}
        assert cats.get("Uncategorized", 0) >= 80.0, (
            f"orphan line must fall through to Uncategorized; got {cats}"
        )
    finally:
        _db.quotes.delete_one({"id": inv_id})


# ══════════════════════════════════════════════════════════════════════
# Rule 3 — empty line_items array + positive total → Uncategorized.
# ══════════════════════════════════════════════════════════════════════
def test_invoice_with_empty_line_items_falls_back_on_total():
    tok, tid = _login()
    inv_id = _seed_invoice(
        tenant_id=tid, line_items=[], total_override=310.0,
    )
    try:
        start, end = _month_range()
        r = requests.get(
            f"{API}/admin/dashboard/revenue-by-category",
            params={"start": start, "end": end},
            headers={"Authorization": f"Bearer {tok}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        cats = {c["category"]: c["amount"] for c in r.json()["items"]}
        assert cats.get("Uncategorized", 0) >= 310.0, (
            f"empty-line invoice total must land in Uncategorized; got {cats}"
        )
    finally:
        _db.quotes.delete_one({"id": inv_id})


# ══════════════════════════════════════════════════════════════════════
# Rule 4 — same fallback applies to income-by-service-category.
# ══════════════════════════════════════════════════════════════════════
def test_income_by_service_category_recognises_empty_line_invoice():
    tok, tid = _login()
    inv_id = _seed_invoice(
        tenant_id=tid, line_items=[], total_override=420.0,
    )
    try:
        start, end = _month_range()
        r = requests.get(
            f"{API}/admin/dashboard/income-by-service-category",
            params={"start": start, "end": end},
            headers={"Authorization": f"Bearer {tok}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        cats = {c["category"]: c["amount"] for c in r.json()["items"]}
        assert cats.get("Uncategorized", 0) >= 420.0, (
            f"empty-line invoice must appear in income tile; got {cats}"
        )
    finally:
        _db.quotes.delete_one({"id": inv_id})


# ══════════════════════════════════════════════════════════════════════
# Uncategorized bucket colour — stable neutral grey so it's spottable.
# ══════════════════════════════════════════════════════════════════════
def test_uncategorized_bucket_uses_neutral_grey():
    tok, tid = _login()
    inv_id = _seed_invoice(
        tenant_id=tid,
        line_items=[{"description": "orphan for colour",
                      "quantity": 1, "unit_price": 12.34}],
    )
    try:
        start, end = _month_range()
        r = requests.get(
            f"{API}/admin/dashboard/revenue-by-category",
            params={"start": start, "end": end},
            headers={"Authorization": f"Bearer {tok}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        entry = next((c for c in r.json()["items"]
                        if c["category"] == "Uncategorized"), None)
        assert entry is not None
        # American spelling — matches the sibling tile.
        assert entry["color"].lower() == "#94a3b8", entry
    finally:
        _db.quotes.delete_one({"id": inv_id})
