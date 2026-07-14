"""Phase 21 · Field Estimator backend tests."""
import time
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status(); return r.json()


@pytest.fixture(scope="module")
def dbc(): return MongoClient(MONGO_URL)[DB_NAME]

@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def customer_h():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def sunbelt_admin_h():
    try:
        return {"Authorization": f"Bearer {_login('admin@sunbelt.com')['access_token']}"}
    except Exception:
        pytest.skip("no sunbelt admin")


@pytest.fixture()
def a_customer_id(dbc):
    t = dbc.tenants.find_one({"slug": "aquaterra"})
    c = dbc.customers.find_one({"tenant_id": t["id"]}, sort=[("created_at", -1)])
    assert c, "aquaterra needs at least one customer"
    return c["id"]


# ═══════════════════════════════════════════════════════════════════════
# Rate catalog
# ═══════════════════════════════════════════════════════════════════════

def test_rate_catalog_seed_and_update(admin_h, dbc):
    # Reset first so we start from a known 20-item baseline
    rst = requests.post(f"{API}/estimator/rate-catalog/reset-defaults",
                         headers=admin_h, timeout=15).json()
    codes = {i["code"] for i in rst["items"]}
    for req in ("pool_tech_hourly", "landscape_crew_hourly", "mulch",
                 "pool_tile", "pool_permit"):
        assert req in codes, f"starter catalog missing {req}"

    # Explicit replace-all wipes and installs exactly the payload
    put = requests.post(f"{API}/estimator/rate-catalog/replace-all",
                         headers=admin_h,
                         json={"items": [{"code": "test_code",
                                            "description": "Test",
                                            "category": "misc", "unit": "ea",
                                            "default_price": 1.23}]},
                         timeout=15).json()
    assert len(put["items"]) == 1
    assert put["items"][0]["code"] == "test_code"

    # Reset restores starter
    rst = requests.post(f"{API}/estimator/rate-catalog/reset-defaults",
                         headers=admin_h, timeout=15).json()
    codes2 = {i["code"] for i in rst["items"]}
    assert "pool_tech_hourly" in codes2


def test_rate_catalog_put_merges_by_code(admin_h, dbc):
    """PUT is merge-by-code: updates existing rows, appends new ones,
    and does NOT touch codes absent from the payload."""
    rst = requests.post(f"{API}/estimator/rate-catalog/reset-defaults",
                         headers=admin_h, timeout=15).json()
    n = len(rst["items"])
    assert n >= 20
    other_code = "landscape_crew_hourly"
    other_before = next(i for i in rst["items"]
                          if i["code"] == other_code)["default_price"]

    # PUT with 1 new + 1 existing (change its price)
    put = requests.put(f"{API}/estimator/rate-catalog", headers=admin_h,
                        json={"items": [
                            {"code": "brand_new_row",
                              "description": "Newly added",
                              "category": "misc", "unit": "ea",
                              "default_price": 42.42},
                            {"code": "pool_tech_hourly",
                              "description": "Pool tech (hourly)",
                              "category": "labor", "unit": "hr",
                              "default_price": 111.11},
                        ]}, timeout=15).json()
    codes_after = {i["code"]: i for i in put["items"]}
    # +1 net growth
    assert len(put["items"]) == n + 1, (
        f"expected {n + 1} rows after merge PUT, got {len(put['items'])}")
    # Existing code updated in place (not duplicated)
    assert sum(1 for i in put["items"]
               if i["code"] == "pool_tech_hourly") == 1
    assert codes_after["pool_tech_hourly"]["default_price"] == 111.11
    # Untouched code kept its original value
    assert codes_after[other_code]["default_price"] == other_before
    # New code appended
    assert codes_after["brand_new_row"]["default_price"] == 42.42

    # DELETE /items/{code} removes a single row
    dl = requests.delete(f"{API}/estimator/rate-catalog/items/brand_new_row",
                          headers=admin_h, timeout=15).json()
    assert "brand_new_row" not in {i["code"] for i in dl["items"]}
    assert len(dl["items"]) == n  # back to the reset baseline count


# ═══════════════════════════════════════════════════════════════════════
# Create + generate (Claude vision LIVE)
# ═══════════════════════════════════════════════════════════════════════

def test_create_and_generate_live(admin_h, dbc, a_customer_id):
    r = requests.post(f"{API}/estimator/estimates", headers=admin_h,
                       json={"title": "Backyard turf install",
                              "customer_id": a_customer_id,
                              "address": "1000 Test Ave",
                              "description":
                                "Homeowner wants ~800 sqft of natural grass "
                                "replaced with artificial turf, plus a 30 "
                                "linft border of paver edging. Crew of 2 "
                                "for one day.",
                              "service_type": "landscape"}, timeout=30).json()
    eid = r["estimate_id"]
    assert r["estimate"]["status"] == "draft"

    g = requests.post(f"{API}/estimator/estimates/{eid}/generate",
                       headers=admin_h, timeout=180).json()
    assert g["mocked"] is False
    assert len(g["line_items"]) >= 4
    assert len(g["upsells"]) >= 3
    for u in g["upsells"]:
        assert u["title"] and "estimated_add_price" in u
    for li in g["line_items"]:
        assert li["quantity"] > 0
        assert li["unit_price"] >= 0
        assert li["unit_price_source"] in {"tenant_rate", "ai_estimate"}
        assert li["extended_price"] == round(li["quantity"] * li["unit_price"], 2)
    assert g["subtotal"] > 0
    assert g["markup_amount"] >= 0
    assert g["total"] >= g["subtotal"]
    assert g["status"] == "generated"

    # cleanup
    dbc.estimator_estimates.delete_one({"id": eid})


def test_rate_catalog_price_match(admin_h, dbc, a_customer_id):
    """Seed a specific code + inject an AI-generated line item with that
    same code, then confirm _apply_catalog stamps `tenant_rate`."""
    # Ensure our known rate exists at a controlled price.
    known_price = 88.50
    tenant = dbc.tenants.find_one({"slug": "aquaterra"})
    doc = dbc.estimator_rate_catalog.find_one({"tenant_id": tenant["id"]}) or {}
    items = doc.get("items") or []
    items = [i for i in items if i.get("code") != "pool_tech_hourly"]
    items.append({"code": "pool_tech_hourly",
                    "description": "Pool tech (hourly)",
                    "category": "labor", "unit": "hr",
                    "default_price": known_price})
    dbc.estimator_rate_catalog.update_one(
        {"tenant_id": tenant["id"]},
        {"$set": {"items": items, "updated_at": "test"}},
        upsert=True,
    )
    # Insert an estimate whose Claude output would include our code — we
    # instead directly test the merge helper by patching an estimate's items.
    from routers.estimator import _apply_catalog
    fake_ai_items = [
        {"code": "pool_tech_hourly", "quantity": 3,
          "unit": "hr", "description": "Pool tech (from AI)"},
        {"code": "unknown_code", "quantity": 1, "unit": "ea",
          "description": "AI-only item", "unit_price": 42.0,
          "confidence": 0.6},
    ]
    merged = _apply_catalog(fake_ai_items, items)
    tenant_priced = [x for x in merged if x["code"] == "pool_tech_hourly"][0]
    assert tenant_priced["unit_price_source"] == "tenant_rate"
    assert tenant_priced["unit_price"] == known_price
    assert tenant_priced["extended_price"] == round(3 * known_price, 2)
    ai_priced = [x for x in merged if x["code"] == "unknown_code"][0]
    assert ai_priced["unit_price_source"] == "ai_estimate"
    assert ai_priced["unit_price"] == 42.0


# ═══════════════════════════════════════════════════════════════════════
# Convert → real quote doc
# ═══════════════════════════════════════════════════════════════════════

def test_convert_to_quote(admin_h, dbc, a_customer_id):
    # Create an estimate with manual line items so we skip the slow LLM path.
    e = requests.post(f"{API}/estimator/estimates", headers=admin_h,
                       json={"title": "Convert test",
                              "customer_id": a_customer_id,
                              "description": "Test convert",
                              "service_type": "pool"}, timeout=15).json()
    eid = e["estimate_id"]
    # Add two manual line items via /add-line-item.
    requests.post(f"{API}/estimator/estimates/{eid}/add-line-item",
                   headers=admin_h,
                   json={"description": "Item A", "quantity": 2,
                          "unit": "hr", "unit_price": 100.0,
                          "category": "labor"}, timeout=15)
    requests.post(f"{API}/estimator/estimates/{eid}/add-line-item",
                   headers=admin_h,
                   json={"description": "Item B", "quantity": 1,
                          "unit": "ea", "unit_price": 500.0,
                          "category": "material"}, timeout=15)
    # Confirm totals: subtotal=700, markup 20%=140, total=840
    got = requests.get(f"{API}/estimator/estimates/{eid}",
                        headers=admin_h, timeout=15).json()
    assert got["subtotal"] == 700.0
    assert got["total"] == 840.0

    conv = requests.post(f"{API}/estimator/estimates/{eid}/convert-to-quote",
                          headers=admin_h, timeout=15).json()
    assert conv["quote_id"]
    quote = dbc.quotes.find_one({"id": conv["quote_id"]})
    assert quote is not None
    assert quote["source_estimate_id"] == eid
    # Markup folded into per-line prices → quote total should match estimate total.
    assert quote["total"] == 840.0
    # Status flipped
    after = requests.get(f"{API}/estimator/estimates/{eid}",
                          headers=admin_h, timeout=15).json()
    assert after["status"] == "converted"
    assert after["quote_id"] == conv["quote_id"]
    # Idempotency: second convert returns the same quote_id
    again = requests.post(f"{API}/estimator/estimates/{eid}/convert-to-quote",
                           headers=admin_h, timeout=15).json()
    assert again["quote_id"] == conv["quote_id"]
    assert again.get("already_converted") is True

    dbc.estimator_estimates.delete_one({"id": eid})
    dbc.quotes.delete_one({"id": conv["quote_id"]})


# ═══════════════════════════════════════════════════════════════════════
# PDF
# ═══════════════════════════════════════════════════════════════════════

def test_estimate_pdf(admin_h, dbc, a_customer_id):
    e = requests.post(f"{API}/estimator/estimates", headers=admin_h,
                       json={"title": "PDF test",
                              "customer_id": a_customer_id,
                              "description": "Test PDF",
                              "service_type": "pool"}, timeout=15).json()
    eid = e["estimate_id"]
    requests.post(f"{API}/estimator/estimates/{eid}/add-line-item",
                   headers=admin_h,
                   json={"description": "Sample", "quantity": 4,
                          "unit": "hr", "unit_price": 75.0,
                          "category": "labor"}, timeout=15)
    pdf_meta = requests.post(f"{API}/estimator/estimates/{eid}/pdf",
                              headers=admin_h, timeout=15).json()
    assert pdf_meta["file_url"].endswith(f"/{eid}/pdf.file")
    pdf = requests.get(f"{BASE}{pdf_meta['file_url']}",
                        headers=admin_h, timeout=30)
    assert pdf.status_code == 200
    ct = pdf.headers.get("content-type", "")
    # PDF or graceful HTML fallback
    assert ("application/pdf" in ct) or ("text/html" in ct)
    assert "attachment" in (pdf.headers.get("content-disposition") or "").lower()
    dbc.estimator_estimates.delete_one({"id": eid})


# ═══════════════════════════════════════════════════════════════════════
# Guards
# ═══════════════════════════════════════════════════════════════════════

def test_tenant_isolation(admin_h, sunbelt_admin_h, dbc, a_customer_id):
    e = requests.post(f"{API}/estimator/estimates", headers=admin_h,
                       json={"title": "Iso", "customer_id": a_customer_id,
                              "description": "iso", "service_type": "pool"},
                       timeout=15).json()
    eid = e["estimate_id"]
    r = requests.get(f"{API}/estimator/estimates/{eid}",
                      headers=sunbelt_admin_h, timeout=15)
    assert r.status_code == 404
    dbc.estimator_estimates.delete_one({"id": eid})


def test_role_gating(admin_h, tech_h, customer_h, dbc, a_customer_id):
    # Customer → 403 on every estimator endpoint
    for path, method in (
        ("/estimator/estimates", "GET"),
        ("/estimator/estimates", "POST"),
        ("/estimator/rate-catalog", "GET"),
        ("/estimator/settings", "GET"),
    ):
        fn = getattr(requests, method.lower())
        kwargs = {"headers": customer_h, "timeout": 15}
        if method == "POST": kwargs["json"] = {"title": "x",
                                                  "description": "y",
                                                  "service_type": "pool"}
        r = fn(f"{API}{path}", **kwargs)
        assert r.status_code == 403, f"customer got {r.status_code} on {method} {path}"
    # Tech CAN create
    tec = requests.post(f"{API}/estimator/estimates", headers=tech_h,
                        json={"title": "Tech add-on",
                              "customer_id": a_customer_id,
                              "description": "field add-on",
                              "service_type": "pool"}, timeout=15)
    assert tec.status_code == 200
    eid = tec.json()["estimate_id"]
    # But tech CANNOT convert-to-quote (admin-only)
    conv = requests.post(f"{API}/estimator/estimates/{eid}/convert-to-quote",
                          headers=tech_h, timeout=15)
    assert conv.status_code == 403
    # And tech CANNOT edit rate catalog
    put = requests.put(f"{API}/estimator/rate-catalog", headers=tech_h,
                        json={"items": []}, timeout=15)
    assert put.status_code == 403

    dbc.estimator_estimates.delete_one({"id": eid})
