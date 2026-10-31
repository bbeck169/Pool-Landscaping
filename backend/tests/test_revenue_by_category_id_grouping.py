"""Feb-2026 · TD-revenue-by-category-id-grouping — pytest.

Locks the invariants shipped in commit {this}:

  * ``revenue_by_category`` groups by FK (``income_category_id``)
    not by display name — two line items pointing at the same
    income_categories id bucket together even when one carries a
    stale/duplicated inline ``category`` string.
  * ``income_by_category_rows`` drill-down accepts the stable
    ``category_key`` (``id:<uuid>`` | ``name:<lower>`` | ``pb:<lower>``
    | ``uncategorized``) emitted by the tile.  Clicking a tile row
    filters its drill-down by that key — eliminating the Hardscaping
    → Irrigation collision class caused by name-string matching.
  * Legacy ``category`` name-match path still works (back-compat).

End-to-end HTTP against the running backend; isolated TEST- tenant
so the test fixtures never collide with the shared aquaterra seed.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from pymongo import MongoClient


load_dotenv(Path(__file__).resolve().parent.parent / ".env")
API = "http://localhost:8001/api"
_db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": password},
                        timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


def _seed_tenant_and_admin() -> tuple[str, str]:
    from utils import hash_password
    tid = f"TEST-idgrp-tenant-{uuid.uuid4().hex[:6]}"
    _db.tenants.insert_one({"id": tid, "slug": tid, "name": tid,
                              "active": True})
    uid = f"TEST-idgrp-u-{uuid.uuid4().hex[:6]}"
    email = f"idgrp-{uuid.uuid4().hex[:6]}@example.com"
    _db.users.insert_one({
        "id": uid, "tenant_id": tid, "email": email,
        "role": "admin", "name": "T",
        "password_hash": hash_password("password123"),
    })
    return tid, _login(email)


def _seed_income_category(tid: str, name: str) -> str:
    cid = f"TEST-idgrp-ic-{uuid.uuid4().hex[:8]}"
    _db.income_categories.insert_one({
        "id": cid, "tenant_id": tid, "name": name,
        "is_archived": False,
    })
    return cid


def _seed_invoice(tid: str, lines: list[dict],
                    created_at: str = "2026-06-15T12:00:00+00:00") -> str:
    iid = f"TEST-idgrp-inv-{uuid.uuid4().hex[:8]}"
    total = sum((li.get("quantity", 0) * li.get("unit_price", 0))
                for li in lines)
    _db.quotes.insert_one({
        "id": iid, "tenant_id": tid, "doc_type": "invoice",
        "invoice_number": iid, "created_at": created_at,
        "status": "paid", "payment_status": "paid",
        "currency": "USD", "total": total, "subtotal": total,
        "line_items": lines,
    })
    return iid


def _cleanup(tid: str):
    _db.quotes.delete_many({"tenant_id": tid})
    _db.income_categories.delete_many({"tenant_id": tid})
    _db.users.delete_many({"tenant_id": tid})
    _db.tenants.delete_one({"id": tid})


# ═══════════════════════════════════════════════════════════════════
# Bug B — FK grouping folds display-name drift into one bucket.
# ═══════════════════════════════════════════════════════════════════
def test_two_lines_same_fk_distinct_inline_names_bucket_as_one():
    tid, tok = _seed_tenant_and_admin()
    hdr = {"Authorization": f"Bearer {tok}"}
    try:
        ic_id = _seed_income_category(tid, "Landscaping")
        # Line A: canonical FK + canonical inline name.
        # Line B: SAME FK but legacy inline string "Landscape".
        _seed_invoice(tid, [
            {"description": "A", "quantity": 1, "unit_price": 100.0,
             "income_category_id": ic_id, "category": "Landscaping"},
            {"description": "B", "quantity": 1, "unit_price": 200.0,
             "income_category_id": ic_id, "category": "Landscape"},
        ])
        r = requests.get(
            f"{API}/admin/dashboard/revenue-by-category"
            f"?start=2026-06-01&end=2026-06-30",
            headers=hdr, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        buckets = [b for b in body["items"]
                   if b.get("category_id") == ic_id]
        assert len(buckets) == 1, (
            f"FK grouping must fold inline-string drift into one "
            f"bucket; got {buckets}"
        )
        assert buckets[0]["amount"] == 300.0
        assert buckets[0]["count"] == 2
        # Display name comes from the live income_categories row.
        assert buckets[0]["category_name"] == "Landscaping"
        assert buckets[0]["bucket_key"] == f"id:{ic_id}"
    finally:
        _cleanup(tid)


# ═══════════════════════════════════════════════════════════════════
# Bug C — drill-down filters by ``category_key`` (stable identity).
# ═══════════════════════════════════════════════════════════════════
def test_drilldown_by_category_key_returns_only_fk_rooted_rows():
    tid, tok = _seed_tenant_and_admin()
    hdr = {"Authorization": f"Bearer {tok}"}
    try:
        hard_id = _seed_income_category(tid, "Hardscaping")
        irri_id = _seed_income_category(tid, "Irrigation")
        _seed_invoice(tid, [
            {"description": "Pavers",     "quantity": 1,
             "unit_price": 500.0,
             "income_category_id": hard_id, "category": "Hardscaping"},
            {"description": "Drip line",  "quantity": 1,
             "unit_price": 250.0,
             "income_category_id": irri_id, "category": "Irrigation"},
        ])
        # Drill-down by Hardscaping key → only Hardscaping line.
        r = requests.get(
            f"{API}/dashboard/income/by-category/rows"
            f"?category=Hardscaping"
            f"&category_key=id:{hard_id}"
            f"&from=2026-06-01&to=2026-06-30",
            headers=hdr, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        descs = {row["description"] for row in body["rows"]}
        assert descs == {"Pavers"}, (
            f"Drill-down by Hardscaping key must NOT leak Irrigation "
            f"rows; got {descs}"
        )
        # Companion check — drill-down by Irrigation key returns only
        # Irrigation.  Pins the symmetric case.
        r2 = requests.get(
            f"{API}/dashboard/income/by-category/rows"
            f"?category=Irrigation"
            f"&category_key=id:{irri_id}"
            f"&from=2026-06-01&to=2026-06-30",
            headers=hdr, timeout=15,
        )
        descs2 = {row["description"] for row in r2.json()["rows"]}
        assert descs2 == {"Drip line"}
    finally:
        _cleanup(tid)


# ═══════════════════════════════════════════════════════════════════
# Back-compat — pre-ticket callers (no ``category_key``) still work.
# ═══════════════════════════════════════════════════════════════════
def test_drilldown_without_key_falls_back_to_name_match():
    tid, tok = _seed_tenant_and_admin()
    hdr = {"Authorization": f"Bearer {tok}"}
    try:
        _seed_invoice(tid, [
            {"description": "Weekly",  "quantity": 1,
             "unit_price": 100.0, "category": "Pool"},
            {"description": "Chems",   "quantity": 1,
             "unit_price":  50.0, "category": "Chemicals"},
        ])
        r = requests.get(
            f"{API}/dashboard/income/by-category/rows"
            f"?category=Pool&from=2026-06-01&to=2026-06-30",
            headers=hdr, timeout=15,
        )
        assert r.status_code == 200, r.text
        descs = {row["description"] for row in r.json()["rows"]}
        assert descs == {"Weekly"}
    finally:
        _cleanup(tid)


# ═══════════════════════════════════════════════════════════════════
# Bucket key emission — tile emits the correct identity for each
# category source so the FE can forward it on legend-click.
# ═══════════════════════════════════════════════════════════════════
def test_tile_emits_bucket_key_per_resolution_source():
    tid, tok = _seed_tenant_and_admin()
    hdr = {"Authorization": f"Bearer {tok}"}
    try:
        fk_id = _seed_income_category(tid, "FkCat")
        # 3 lines, 3 different resolution paths:
        #   A: FK → bucket_key = "id:<fk_id>"
        #   B: inline-only string → bucket_key = "name:namecat"
        #   C: no FK, no inline, no item_id → bucket_key = "uncategorized"
        _seed_invoice(tid, [
            {"description": "A", "quantity": 1, "unit_price": 10.0,
             "income_category_id": fk_id, "category": "FkCat"},
            {"description": "B", "quantity": 1, "unit_price": 20.0,
             "category": "NameCat"},
            {"description": "C", "quantity": 1, "unit_price": 30.0},
        ])
        r = requests.get(
            f"{API}/admin/dashboard/revenue-by-category"
            f"?start=2026-06-01&end=2026-06-30",
            headers=hdr, timeout=15,
        )
        body = r.json()
        keys = {b["bucket_key"]: b for b in body["items"]}
        assert f"id:{fk_id}" in keys
        assert keys[f"id:{fk_id}"]["category_id"] == fk_id
        assert "name:namecat" in keys
        assert keys["name:namecat"]["category_id"] is None
        assert keys["name:namecat"]["category_name"] == "NameCat"
        assert "uncategorized" in keys
        assert keys["uncategorized"]["category_id"] is None
    finally:
        _cleanup(tid)
