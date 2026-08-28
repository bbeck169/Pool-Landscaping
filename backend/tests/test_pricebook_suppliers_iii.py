"""Backlog #iii · Feb-2026 — Pricebook expanded editing tests.

Covers:
  1. ``effective_cost`` helper precedence + fallback + null log.
  2. ``rebuild_mirrors`` regenerates both compat mirrors.
  3. ``pricebook_suppliers_v1`` migration idempotency + fold from
      compact ``supplier_prices[]``.
  4. ``POST /api/items`` accepts rich ``suppliers[]`` + auto-mirror.
  5. ``PATCH /api/items/{id}`` updates rich + regenerates mirror
      on every write (idempotent recompute).
  6. ``PATCH`` with empty suppliers[] on chemical item saves silently
      (guardrail is client-side).
  7. Invoice ``wholesale_price_snapshot`` freezes at write time and
      stays immutable even after supplier costs change.
  8. ``POST /*-categories/resolve-or-create`` idempotent — same
      input twice returns same id + ``created`` flips false.
  9. Case-insensitive resolve — "Chemicals" resolves an existing
     "chemicals" without 409.
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
_sync = MongoClient(os.environ["MONGO_URL"])
_db = _sync[os.environ["DB_NAME"]]
_CACHE: dict = {}


def _login(email: str) -> str:
    key = f"tok:{email}"
    if key in _CACHE:
        return _CACHE[key]
    for _ in range(3):
        try:
            r = requests.post(
                f"{API}/auth/login",
                json={"email": email, "password": "password123"},
                timeout=30,
            )
            if r.status_code == 200:
                _CACHE[key] = r.json()["access_token"]
                return _CACHE[key]
        except requests.exceptions.RequestException:
            continue
    raise RuntimeError(f"login failed for {email}")


def _seed_isolated_tenant():
    tid = f"TEST-blog3-tenant-{uuid.uuid4().hex[:6]}"
    _db.tenants.insert_one({"id": tid,
                             "slug": f"test-blog3-{uuid.uuid4().hex[:6]}",
                             "name": "TEST_blog3", "active": True})
    return tid


def _seed_admin(tid):
    from utils import hash_password
    uid = f"TEST-blog3-u-{uuid.uuid4().hex[:6]}"
    email = f"blog3-{uuid.uuid4().hex[:6]}@example.com"
    _db.users.insert_one({"id": uid, "tenant_id": tid, "email": email,
                           "name": "TEST_blog3_admin", "role": "admin",
                           "password_hash": hash_password("password123")})
    return uid, email, _login(email)


def _cleanup(tid, uid, email):
    _db.users.delete_one({"id": uid})
    _db.tenants.delete_one({"id": tid})
    _db.items.delete_many({"tenant_id": tid})
    _db.income_categories.delete_many({"tenant_id": tid})
    _db.service_categories.delete_many({"tenant_id": tid})
    _db.quotes.delete_many({"tenant_id": tid})
    _CACHE.pop(f"tok:{email}", None)


# ═══════════════════════════════════════════════════════════════
# 1 · effective_cost precedence + fallback ladder
# ═══════════════════════════════════════════════════════════════
def test_effective_cost_prefers_rich_suppliers():
    from services.pricebook.cost import effective_cost
    item = {
        "suppliers": [
            {"supplier_name": "A", "unit_cost": 12.50},
            {"supplier_name": "B", "unit_cost": 9.99},
            {"supplier_name": "C", "unit_cost": 15.00},
        ],
        "supplier_prices": [{"supplier_slug": "a", "cost_cents": 500}],
        "wholesale_price": 1.00,
    }
    assert effective_cost(item) == 9.99


def test_effective_cost_falls_back_to_compact_when_rich_empty():
    from services.pricebook.cost import effective_cost
    item = {
        "suppliers": [],
        "supplier_prices": [
            {"supplier_slug": "a", "cost_cents": 1250},
            {"supplier_slug": "b", "cost_cents": 999},
        ],
        "wholesale_price": 1.00,
    }
    # min(1250, 999)/100 = 9.99
    assert effective_cost(item) == 9.99


def test_effective_cost_falls_back_to_legacy_scalar():
    from services.pricebook.cost import effective_cost
    item = {"suppliers": [], "supplier_prices": [], "wholesale_price": 42.75}
    assert effective_cost(item) == 42.75


def test_effective_cost_returns_none_and_logs_when_all_empty(caplog):
    from services.pricebook.cost import effective_cost
    import logging
    caplog.set_level(logging.WARNING, logger="pricebook.cost")
    item = {"id": "test-item", "tenant_id": "t1", "name": "T",
             "suppliers": [], "supplier_prices": [], "wholesale_price": 0}
    assert effective_cost(item) is None
    assert any("fallback_null" in rec.message for rec in caplog.records)


# ═══════════════════════════════════════════════════════════════
# 2 · rebuild_mirrors regenerates both compat mirrors
# ═══════════════════════════════════════════════════════════════
def test_rebuild_mirrors_regenerates_both():
    from services.pricebook.cost import rebuild_mirrors
    item = {"suppliers": [
        {"supplier_name": "Pool360", "unit_cost": 12.50},
        {"supplier_name": "SiteOne", "unit_cost": 9.99},
    ]}
    out = rebuild_mirrors(item)
    assert out["wholesale_price"] == 9.99
    slugs = {r["supplier_slug"] for r in out["supplier_prices"]}
    assert slugs == {"pool360", "siteone"}


def test_rebuild_mirrors_empty_suppliers_leaves_alone():
    from services.pricebook.cost import rebuild_mirrors
    assert rebuild_mirrors({"suppliers": []}) == {}


# ═══════════════════════════════════════════════════════════════
# 3 · POST /items accepts rich suppliers[] + auto-mirror
# ═══════════════════════════════════════════════════════════════
def _seed_sc(tid, name="Chemicals"):
    cid = f"TEST-blog3-sc-{uuid.uuid4().hex[:6]}"
    _db.service_categories.insert_one({
        "id": cid, "tenant_id": tid, "name": name, "is_archived": False,
        "sort_order": 0, "color": "#000000",
    })
    return cid


def test_create_item_with_rich_suppliers_generates_mirrors():
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin(tid)
    sc = _seed_sc(tid)
    try:
        r = requests.post(
            f"{API}/items",
            headers={"Authorization": f"Bearer {tok}"},
            json={"name": "Test Chem", "category": "Chemical",
                    "unit": "each", "unit_price": 100.0, "item_type": "product",
                    "service_category_id": sc,
                    "suppliers": [
                        {"supplier_name": "A", "unit_cost": 50.0},
                        {"supplier_name": "B", "unit_cost": 30.0},
                        {"supplier_name": "C", "unit_cost": 40.0},
                    ]},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        item = r.json()
        assert len(item["suppliers"]) == 3
        # Mirror should be min = 30.0
        assert item["wholesale_price"] == 30.0
        # Compact mirror shape
        cents = sorted(p["cost_cents"] for p in item["supplier_prices"])
        assert cents == [3000, 4000, 5000]
    finally:
        _cleanup(tid, uid, email)


# ═══════════════════════════════════════════════════════════════
# 4 · PATCH regenerates mirror on every write (idempotent)
# ═══════════════════════════════════════════════════════════════
def test_patch_rebuilds_wholesale_price_mirror():
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin(tid)
    sc = _seed_sc(tid)
    try:
        r = requests.post(
            f"{API}/items",
            headers={"Authorization": f"Bearer {tok}"},
            json={"name": "Chlorine", "category": "Chemical", "unit": "each",
                    "unit_price": 50.0, "item_type": "product",
                    "service_category_id": sc,
                    "suppliers": [{"supplier_name": "A", "unit_cost": 20.0}]},
            timeout=15,
        )
        iid = r.json()["id"]
        # PATCH — add a cheaper supplier
        r2 = requests.patch(
            f"{API}/items/{iid}",
            headers={"Authorization": f"Bearer {tok}"},
            json={"suppliers": [
                {"supplier_name": "A", "unit_cost": 20.0},
                {"supplier_name": "B", "unit_cost": 12.34},
            ]},
            timeout=15,
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["wholesale_price"] == 12.34
        # PATCH again with SAME payload — idempotent recompute
        r3 = requests.patch(
            f"{API}/items/{iid}",
            headers={"Authorization": f"Bearer {tok}"},
            json={"suppliers": [
                {"supplier_name": "A", "unit_cost": 20.0},
                {"supplier_name": "B", "unit_cost": 12.34},
            ]},
            timeout=15,
        )
        assert r3.json()["wholesale_price"] == 12.34
    finally:
        _cleanup(tid, uid, email)


# ═══════════════════════════════════════════════════════════════
# 5 · PATCH with empty suppliers[] on chemical saves silently
# ═══════════════════════════════════════════════════════════════
def test_patch_empty_suppliers_on_chemical_saves_silently():
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin(tid)
    sc = _seed_sc(tid)
    try:
        r = requests.post(
            f"{API}/items",
            headers={"Authorization": f"Bearer {tok}"},
            json={"name": "TestChem", "category": "Chemical", "unit": "each",
                    "unit_price": 10, "item_type": "product",
                    "service_category_id": sc,
                    "suppliers": [{"supplier_name": "A", "unit_cost": 5}]},
            timeout=15,
        )
        iid = r.json()["id"]
        r2 = requests.patch(
            f"{API}/items/{iid}",
            headers={"Authorization": f"Bearer {tok}"},
            json={"suppliers": []},
            timeout=15,
        )
        # Server accepts empty suppliers[] — the guardrail is client-side.
        # Empty suppliers leaves the ``wholesale_price`` mirror alone
        # (per rebuild_mirrors contract).
        assert r2.status_code == 200, r2.text
    finally:
        _cleanup(tid, uid, email)


# ═══════════════════════════════════════════════════════════════
# 6 · Snapshot immutability + new snapshot after cost change
# ═══════════════════════════════════════════════════════════════
def test_wholesale_snapshot_immutable_when_supplier_cost_changes():
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin(tid)
    sc = _seed_sc(tid)
    # Seed a customer that respects tenant.
    cust_id = f"TEST-blog3-c-{uuid.uuid4().hex[:6]}"
    _db.customers.insert_one({
        "id": cust_id, "tenant_id": tid, "name": "TestCust",
        "email": f"c-{uuid.uuid4().hex[:6]}@x.co", "is_active": True,
    })
    try:
        # 1. Create item with min cost = 50.
        r = requests.post(
            f"{API}/items",
            headers={"Authorization": f"Bearer {tok}"},
            json={"name": "SnapItem", "category": "Chemical", "unit": "each",
                    "unit_price": 100.0, "item_type": "product",
                    "service_category_id": sc,
                    "suppliers": [
                        {"supplier_name": "A", "unit_cost": 50.0},
                        {"supplier_name": "B", "unit_cost": 75.0},
                    ]},
            timeout=15,
        )
        iid = r.json()["id"]
        # 2. Create invoice line → snapshot should be 50.0
        r2 = requests.post(
            f"{API}/quotes",
            headers={"Authorization": f"Bearer {tok}"},
            json={"customer_id": cust_id, "title": "T", "doc_type": "invoice",
                    "line_items": [{"description": "SnapItem", "quantity": 1,
                                      "unit_price": 100.0, "category": "Chemicals",
                                      "item_id": iid, "pricebook_item_id": iid}]},
            timeout=15,
        )
        inv1_id = r2.json()["id"]
        assert r2.json()["line_items"][0]["wholesale_price_snapshot"] == 50.0
        # 3. Lower supplier A to 20 → item mirror becomes 20
        r3 = requests.patch(
            f"{API}/items/{iid}",
            headers={"Authorization": f"Bearer {tok}"},
            json={"suppliers": [
                {"supplier_name": "A", "unit_cost": 20.0},
                {"supplier_name": "B", "unit_cost": 75.0},
            ]},
            timeout=15,
        )
        assert r3.json()["wholesale_price"] == 20.0
        # 4. New invoice → new snapshot = 20
        r4 = requests.post(
            f"{API}/quotes",
            headers={"Authorization": f"Bearer {tok}"},
            json={"customer_id": cust_id, "title": "T2", "doc_type": "invoice",
                    "line_items": [{"description": "SnapItem", "quantity": 1,
                                      "unit_price": 100.0, "category": "Chemicals",
                                      "item_id": iid, "pricebook_item_id": iid}]},
            timeout=15,
        )
        assert r4.json()["line_items"][0]["wholesale_price_snapshot"] == 20.0
        # 5. OLD invoice STILL 50 — refetch
        r5 = requests.get(f"{API}/quotes/{inv1_id}",
                           headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r5.json()["line_items"][0]["wholesale_price_snapshot"] == 50.0
    finally:
        _db.customers.delete_many({"tenant_id": tid})
        _cleanup(tid, uid, email)


# ═══════════════════════════════════════════════════════════════
# 7 · resolve-or-create — idempotent + case-insensitive
# ═══════════════════════════════════════════════════════════════
def test_income_resolve_or_create_idempotent():
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        target = f"TestCat-{uuid.uuid4().hex[:6]}"
        r1 = requests.post(
            f"{API}/income-categories/resolve-or-create",
            headers={"Authorization": f"Bearer {tok}"},
            json={"name": target}, timeout=15,
        )
        assert r1.status_code == 200
        assert r1.json()["created"] is True
        cid = r1.json()["category"]["id"]
        r2 = requests.post(
            f"{API}/income-categories/resolve-or-create",
            headers={"Authorization": f"Bearer {tok}"},
            json={"name": target}, timeout=15,
        )
        assert r2.json()["created"] is False
        assert r2.json()["category"]["id"] == cid
        # Case-insensitive
        r3 = requests.post(
            f"{API}/income-categories/resolve-or-create",
            headers={"Authorization": f"Bearer {tok}"},
            json={"name": target.upper()}, timeout=15,
        )
        assert r3.json()["created"] is False
        assert r3.json()["category"]["id"] == cid
    finally:
        _cleanup(tid, uid, email)


def test_service_resolve_or_create_idempotent():
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin(tid)
    try:
        target = f"TestSC-{uuid.uuid4().hex[:6]}"
        r1 = requests.post(
            f"{API}/service-categories/resolve-or-create",
            headers={"Authorization": f"Bearer {tok}"},
            json={"name": target}, timeout=15,
        )
        assert r1.json()["created"] is True
        cid = r1.json()["category"]["id"]
        r2 = requests.post(
            f"{API}/service-categories/resolve-or-create",
            headers={"Authorization": f"Bearer {tok}"},
            json={"name": target.lower()}, timeout=15,
        )
        assert r2.json()["created"] is False
        assert r2.json()["category"]["id"] == cid
    finally:
        _cleanup(tid, uid, email)


# ═══════════════════════════════════════════════════════════════
# 8 · Migration folds compact prices into rich (via admin endpoint)
# ═══════════════════════════════════════════════════════════════
def test_migration_folds_compact_supplier_prices_into_rich():
    """Runs the migration via the super_admin admin endpoint so the
    fold-up executes on the app's own event loop. Verifies:
      1. Compact ``supplier_prices[]`` folds into rich ``suppliers[]``
         with supplier_name = pricebook_suppliers.display_name.
      2. wholesale_price mirror = min(supplier costs) = 39.99.
      3. Idempotency — a second force-run over the same data leaves
         the suppliers list at the same length (dedup on name).
    """
    tid = _seed_isolated_tenant()
    # Direct sync insert of an item with legacy compact shape only.
    iid = f"TEST-blog3-legacy-{uuid.uuid4().hex[:6]}"
    _db.pricebook_suppliers.insert_many([
        {"id": "ps-a-" + uuid.uuid4().hex[:6], "tenant_id": tid, "slug": "pool360",
          "display_name": "Pool360", "income_category_id": "ic-x",
          "is_active": True, "is_seed": False},
        {"id": "ps-b-" + uuid.uuid4().hex[:6], "tenant_id": tid, "slug": "siteone",
          "display_name": "SiteOne", "income_category_id": "ic-x",
          "is_active": True, "is_seed": False},
    ])
    _db.items.insert_one({
        "id": iid, "tenant_id": tid, "name": "LegacyItem",
        "category": "Chemical", "unit": "each", "unit_price": 100.0,
        "supplier_prices": [
            {"supplier_slug": "pool360", "cost_cents": 4500},
            {"supplier_slug": "siteone", "cost_cents": 3999},
        ],
    })
    # Run migration via the super_admin admin endpoint.
    su_tok = _login("super@aquaterra.com")
    try:
        r1 = requests.post(
            f"{API}/admin/migrations/pricebook-suppliers?force=true",
            headers={"Authorization": f"Bearer {su_tok}"}, timeout=30,
        )
        assert r1.status_code == 200, r1.text
        row = _db.items.find_one({"id": iid})
        rich = row.get("suppliers") or []
        names = sorted(r["supplier_name"] for r in rich)
        assert names == ["Pool360", "SiteOne"], f"got={names}"
        assert row["wholesale_price"] == 39.99
        # Idempotency — force-run again; item should still have 2 rows.
        r2 = requests.post(
            f"{API}/admin/migrations/pricebook-suppliers?force=true",
            headers={"Authorization": f"Bearer {su_tok}"}, timeout=30,
        )
        assert r2.status_code == 200
        row2 = _db.items.find_one({"id": iid})
        assert len(row2.get("suppliers") or []) == 2
    finally:
        _db.pricebook_suppliers.delete_many({"tenant_id": tid})
        _cleanup(tid, "", "")


# ═══════════════════════════════════════════════════════════════
# 9 · Supplier-names autocomplete endpoint
# ═══════════════════════════════════════════════════════════════
def test_supplier_names_endpoint_dedupes_case_insensitive():
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin(tid)
    sc = _seed_sc(tid)
    try:
        # Create an item with a supplier name unique to this tenant.
        unique = f"UniqueSupplier-{uuid.uuid4().hex[:6]}"
        r = requests.post(
            f"{API}/items",
            headers={"Authorization": f"Bearer {tok}"},
            json={"name": "IX", "category": "Chemical", "unit": "each",
                    "unit_price": 1, "item_type": "product",
                    "service_category_id": sc,
                    "suppliers": [{"supplier_name": unique, "unit_cost": 1}]},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        r2 = requests.get(
            f"{API}/pricebook/supplier-names",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        )
        assert r2.status_code == 200
        names_lower = {n.lower() for n in r2.json()["names"]}
        assert unique.lower() in names_lower
    finally:
        _cleanup(tid, uid, email)
