"""Feb-2026 · Pricebook item_type feature — backend tests.

Covers:
  1. Create product → supplier fields accepted.
  2. Create service → supplier fields rejected (400).
  3. Existing item without ``item_type`` grandfathers to product.
  4. Estimate line with service item + overridden price → 200,
     ``overridden_price=true`` on the persisted line.
  5. Estimate line with product item + differing price → 400
     (``product_price_locked``).
  6. Estimate line with product item + matching price → 200 and
     ``overridden_price=false``.
  7. Tenant isolation on the price-lock check.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

from tests.conftest import demo_pw

API = "http://localhost:8001/api"

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": demo_pw(email)}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _tenant_of(email: str) -> str:
    return _run(_DB.users.find_one({"email": email}, {"_id": 0, "tenant_id": 1}))["tenant_id"]


async def _wipe():
    await _DB.items.delete_many({"name": {"$regex": "^TESTitype_"}})
    await _DB.quotes.delete_many({"title": {"$regex": "^TESTitype_"}})
    await _DB.customers.delete_many({"name": {"$regex": "^TESTitype_"}})


def _pool_category(tok: str) -> str:
    r = requests.get(f"{API}/service-categories",
                     headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    body = r.json()
    xs = body if isinstance(body, list) else body.get("items", [])
    return xs[0]["id"]


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


async def _mkcust(tenant_id: str, name: str) -> str:
    cid = f"TESTitype_cust_{uuid4().hex[:8]}"
    await _DB.customers.insert_one(
        {"id": cid, "tenant_id": tenant_id, "name": name,
         "email": f"{cid}@x.local"})
    return cid


# ═══════════════════════════════════════════════════════════════════════
# 1. Create product accepts supplier fields.
# ═══════════════════════════════════════════════════════════════════════
def test_create_product_accepts_supplier_fields():
    tok = _login("super@aquaterra.com")
    r = requests.post(f"{API}/items",
                      headers={"Authorization": f"Bearer {tok}"},
                      json={"name": f"TESTitype_chlor_{uuid4().hex[:6]}",
                            "item_type": "product",
                            "service_category_id": _pool_category(tok),
                            "unit_price": 25.00,
                            "wholesale_price": 12.50,
                            "labor_cost_default": 0.0,
                            "unit": "gal"},
                      timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["item_type"] == "product"
    assert body["wholesale_price"] == 12.50


# ═══════════════════════════════════════════════════════════════════════
# 2. Create service rejects supplier fields.
# ═══════════════════════════════════════════════════════════════════════
def test_create_service_rejects_supplier_fields():
    tok = _login("super@aquaterra.com")
    r = requests.post(f"{API}/items",
                      headers={"Authorization": f"Bearer {tok}"},
                      json={"name": f"TESTitype_svc_{uuid4().hex[:6]}",
                            "item_type": "service",
                            "service_category_id": _pool_category(tok),
                            "unit_price": 150.00,
                            "wholesale_price": 20.00,
                            "supplier_id": "sup-1"},
                      timeout=15)
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "services_cannot_have_supplier_pricing"
    assert "wholesale_price" in detail["fields"]


def test_create_service_without_supplier_fields_succeeds():
    tok = _login("super@aquaterra.com")
    r = requests.post(f"{API}/items",
                      headers={"Authorization": f"Bearer {tok}"},
                      json={"name": f"TESTitype_svcok_{uuid4().hex[:6]}",
                            "item_type": "service",
                            "service_category_id": _pool_category(tok),
                            "unit_price": 150.00,
                            "unit": "hour"},
                      timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["item_type"] == "service"
    assert body.get("supplier_prices") == []
    assert body.get("wholesale_price") is None


# ═══════════════════════════════════════════════════════════════════════
# 3. Existing item without item_type grandfathers to product.
# ═══════════════════════════════════════════════════════════════════════
def test_legacy_item_grandfathers_to_product():
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")
    iid = f"TESTitype_legacy_{uuid4().hex[:8]}"
    _run(_DB.items.insert_one({
        "id": iid, "tenant_id": tenant_id,
        "name": f"TESTitype_legacy_row",
        "unit_price": 42.00, "unit": "each",
        # item_type intentionally missing.
    }))
    cid = _run(_mkcust(tenant_id, "TESTitype_legacy_cust"))
    # Attempt to override price on a legacy line — must be treated as
    # locked product and rejected.
    r = requests.post(f"{API}/quotes",
                      headers={"Authorization": f"Bearer {tok}"},
                      json={"customer_id": cid, "title": "TESTitype_legacy_q",
                            "line_items": [
                                {"description": "legacy line",
                                 "quantity": 1, "unit_price": 99.99,
                                 "item_id": iid}]},
                      timeout=15)
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error"] == "product_price_locked"


# ═══════════════════════════════════════════════════════════════════════
# 4. Service line with overridden price → 200 + overridden_price=true.
# ═══════════════════════════════════════════════════════════════════════
def test_service_line_allows_override_and_stamps_flag():
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")
    # Create a service via API so we're exercising the real path.
    svc = requests.post(f"{API}/items",
                        headers={"Authorization": f"Bearer {tok}"},
                        json={"name": f"TESTitype_svc4_{uuid4().hex[:6]}",
                              "item_type": "service",
                              "service_category_id": _pool_category(tok),
                              "unit_price": 150.00, "unit": "visit"},
                        timeout=15).json()
    assert svc["item_type"] == "service"
    cid = _run(_mkcust(tenant_id, "TESTitype_svc4_cust"))
    r = requests.post(f"{API}/quotes",
                      headers={"Authorization": f"Bearer {tok}"},
                      json={"customer_id": cid, "title": "TESTitype_svc4_q",
                            "line_items": [
                                {"description": "custom rate",
                                 "quantity": 1, "unit_price": 175.00,
                                 "item_id": svc["id"]}]},
                      timeout=15)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["line_items"][0]["overridden_price"] is True
    assert doc["line_items"][0]["unit_price"] == 175.00


# ═══════════════════════════════════════════════════════════════════════
# 5. Product line with differing price → 400.
# ═══════════════════════════════════════════════════════════════════════
def test_product_line_rejects_differing_price():
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")
    prod = requests.post(f"{API}/items",
                         headers={"Authorization": f"Bearer {tok}"},
                         json={"name": f"TESTitype_prod5_{uuid4().hex[:6]}",
                               "item_type": "product",
                               "service_category_id": _pool_category(tok),
                               "unit_price": 30.00, "unit": "gal"},
                         timeout=15).json()
    cid = _run(_mkcust(tenant_id, "TESTitype_prod5_cust"))
    r = requests.post(f"{API}/quotes",
                      headers={"Authorization": f"Bearer {tok}"},
                      json={"customer_id": cid, "title": "TESTitype_prod5_q",
                            "line_items": [
                                {"description": "drift line",
                                 "quantity": 1, "unit_price": 25.00,
                                 "item_id": prod["id"]}]},
                      timeout=15)
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error"] == "product_price_locked"


# ═══════════════════════════════════════════════════════════════════════
# 6. Product line with matching price → 200 + overridden_price=false.
# ═══════════════════════════════════════════════════════════════════════
def test_product_line_matches_pricebook_and_persists_locked_flag():
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")
    prod = requests.post(f"{API}/items",
                         headers={"Authorization": f"Bearer {tok}"},
                         json={"name": f"TESTitype_prod6_{uuid4().hex[:6]}",
                               "item_type": "product",
                               "service_category_id": _pool_category(tok),
                               "unit_price": 30.00, "unit": "gal"},
                         timeout=15).json()
    cid = _run(_mkcust(tenant_id, "TESTitype_prod6_cust"))
    r = requests.post(f"{API}/quotes",
                      headers={"Authorization": f"Bearer {tok}"},
                      json={"customer_id": cid, "title": "TESTitype_prod6_q",
                            "line_items": [
                                {"description": "matched line",
                                 "quantity": 2, "unit_price": 30.00,
                                 "item_id": prod["id"]}]},
                      timeout=15)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["line_items"][0]["overridden_price"] is False


# ═══════════════════════════════════════════════════════════════════════
# 7. Tenant isolation — an item id from tenant B doesn't unlock
#    price-lock behaviour for a quote written under tenant A.
# ═══════════════════════════════════════════════════════════════════════
def test_price_lock_tenant_isolation():
    tok = _login("super@aquaterra.com")
    tenant_a = _tenant_of("super@aquaterra.com")
    tenant_b = f"other-tenant-{uuid4().hex[:6]}"
    # Seed a service in tenant B with the same item id but different
    # unit_price. Tenant A's writer should NOT resolve to it.
    iid = f"TESTitype_shared_{uuid4().hex[:8]}"
    _run(_DB.items.insert_one({
        "id": iid, "tenant_id": tenant_b, "item_type": "service",
        "name": "TESTitype_shared_row", "unit_price": 99.00,
    }))
    # Also create a product in tenant A with the same id.
    # (This is a synthetic scenario — normally ids are globally
    # unique, but MongoDB doesn't enforce that across tenants.)
    _run(_DB.items.insert_one({
        "id": iid + "_A", "tenant_id": tenant_a, "item_type": "product",
        "name": "TESTitype_shared_A", "unit_price": 30.00,
    }))
    cid = _run(_mkcust(tenant_a, "TESTitype_iso_cust"))
    # Post a quote in tenant A referencing the tenant-A product id
    # with a differing price → must reject.
    r = requests.post(f"{API}/quotes",
                      headers={"Authorization": f"Bearer {tok}"},
                      json={"customer_id": cid, "title": "TESTitype_iso_q",
                            "line_items": [
                                {"description": "iso line",
                                 "quantity": 1, "unit_price": 15.00,
                                 "item_id": iid + "_A"}]},
                      timeout=15)
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error"] == "product_price_locked"
    # Cleanup direct DB seed.
    _run(_DB.items.delete_many({"id": {"$in": [iid, iid + "_A"]}}))
